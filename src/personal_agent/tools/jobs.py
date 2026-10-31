import subprocess
import threading

from personal_agent.tools import shell, workspace
from personal_agent.tools.builtins import ToolExecutionError

MAX_RUNNING = 4
MAX_FINISHED = 16
RING_BYTES = 64 * 1024
DISCARD_MARKER = "[...earlier output discarded]\n"
_READ_CHUNK_SIZE = 65536


class _Job:
    def __init__(self, job_id: int, command: str, process: subprocess.Popen):
        self.job_id = job_id
        self.command = command
        self.process = process
        self.pgid = process.pid
        self.state = "running"
        self.exit_code: int | None = None
        self.output = bytearray()
        self.discarded = False
        self.watcher: threading.Thread | None = None


_lock = threading.Lock()
_jobs: dict[int, _Job] = {}
_finished: list[int] = []
_cleaning: set[_Job] = set()
_next_id = 1


def _running() -> list[_Job]:
    return [job for job in _jobs.values() if job.state == "running"]


def check_capacity() -> None:
    if len(_running()) >= MAX_RUNNING:
        raise ToolExecutionError(f"at most {MAX_RUNNING} Background Jobs can run at once; "
                                 "stop one with job_stop first")


def _finish(job: _Job, state: str) -> None:
    job.state = state
    job.exit_code = job.process.returncode
    _finished.append(job.job_id)
    while len(_finished) > MAX_FINISHED:
        _jobs.pop(_finished.pop(0), None)


def _drain(job: _Job) -> None:
    stream = job.process.stdout
    while chunk := stream.read1(_READ_CHUNK_SIZE):
        with _lock:
            job.output.extend(chunk)
            if len(job.output) > RING_BYTES:
                del job.output[:len(job.output) - RING_BYTES]
                job.discarded = True
    stream.close()


def _watch(job: _Job) -> None:
    job.process.wait()
    with _lock:
        if job.state == "running":
            _finish(job, "exited")
    shell.kill_process_groups([(job.process, job.pgid)])
    with _lock:
        _cleaning.discard(job)


def start(shell_path: str, command: str) -> int:
    global _next_id
    with _lock:
        check_capacity()
        try:
            process = subprocess.Popen(
                [shell_path, "-c", command],
                cwd=workspace.configured_workspace().root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=shell.shell_environment(),
            )
        except OSError as exc:
            raise ToolExecutionError(f"failed to start command: {exc}") from exc
        shell.process_started(process)
        job = _Job(_next_id, command, process)
        _next_id += 1
        _jobs[job.job_id] = job
        _cleaning.add(job)
        job.watcher = threading.Thread(target=_watch, args=(job,), daemon=True)
    threading.Thread(target=_drain, args=(job,), daemon=True).start()
    job.watcher.start()
    return job.job_id


def _get(job_id: int) -> _Job:
    job = _jobs.get(job_id)
    if job is None:
        raise ToolExecutionError(f"unknown Background Job id {job_id}")
    return job


def status(job_id: int) -> dict:
    cap = shell.effective_shell_config().max_output_bytes
    with _lock:
        job = _get(job_id)
        data = bytes(job.output[-cap:])
        discarded = job.discarded or len(job.output) > cap
        text = data.decode("utf-8", errors="replace")
        return {"job_id": job.job_id, "command": job.command, "state": job.state, "exit_code": job.exit_code,
                "output": DISCARD_MARKER + text if discarded else text}


def _stop_jobs(selected: list[_Job]) -> list[int]:
    with _lock:
        stopped = [job for job in selected if job.state == "running"]
        for job in stopped:
            job.state = "stopping"
        watched = [job for job in selected if job in _cleaning]
    shell.kill_process_groups([(job.process, job.pgid) for job in watched])
    for job in watched:
        job.watcher.join(timeout=shell.KILL_GRACE_SECONDS + 1)
    with _lock:
        for job in stopped:
            _finish(job, "stopped")
    return [job.job_id for job in stopped]


def stop(job_id: int) -> dict:
    with _lock:
        job = _get(job_id)
    _stop_jobs([job])
    return status(job_id)


def stop_all() -> list[int]:
    with _lock:
        selected = list(_cleaning)
    return sorted(_stop_jobs(selected))


def listing() -> list[dict]:
    with _lock:
        return [{"job_id": job.job_id, "command": job.command, "state": job.state, "exit_code": job.exit_code}
                for job in sorted(_jobs.values(), key=lambda job: job.job_id)]


def reset() -> None:
    global _next_id
    stop_all()
    with _lock:
        _jobs.clear()
        _finished.clear()
        _next_id = 1
