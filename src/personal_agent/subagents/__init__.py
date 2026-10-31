import multiprocessing
import os
import signal
import threading
import time
from dataclasses import asdict, replace

from personal_agent import call_log, context_budget
from personal_agent.providers.contract import ToolResult
from personal_agent.subagents.definitions import MAX_BYTES, discover, revalidate, tool_definition
from personal_agent.subagents.protocol import receive, send
from personal_agent.tools.builtins import ToolExecutionError

worker_bootstrap = None
GRACE_SECONDS = 4
_guard = threading.Lock()


def bounded(text, session):
    data = text.encode("utf-8")
    if len(data) <= MAX_BYTES:
        return text
    marker = f"\n[...truncated; full answer in child Session {session}]"
    return data[:MAX_BYTES - len(marker.encode())].decode("utf-8", errors="ignore") + marker


class Delegation:
    def __init__(self, config, instructions, mode, confirm, output, secrets, run_busy=None, plan_state=None):
        from personal_agent.tools import registry, shell, workspace
        self.config = replace(config, api_keys=dict(config.api_keys),
                              capacity_overrides=tuple(dict(item) for item in config.capacity_overrides),
                              capacity_snapshot=asdict(context_budget.resolve(config, config.provider, config.model)))
        self.instructions = instructions
        self.mode = mode
        self.confirm = confirm
        self.output = output
        self.run_busy = run_busy or (lambda operation: operation())
        self.plan_state = plan_state if plan_state is not None else []
        self.secrets = (*config.api_keys.values(), *secrets)
        try:
            self.workspace = workspace.configured_workspace()
            self.roles, diagnostics = discover()
        except ToolExecutionError as exc:
            self.workspace = None
            self.roles, diagnostics = {}, [str(exc)]
        self.advertised = bool(self.roles or diagnostics)
        self.definition = tool_definition(self.roles, diagnostics)
        self.capabilities = registry.capability_snapshot()
        self.shell = shell.effective_shell_config() if self.workspace is not None else None

    def execute(self, call):
        name = call.arguments["name"]
        expected = self.roles.get(name)
        if expected is None:
            raise ToolExecutionError("named agent is unavailable in this task")
        try:
            task_bytes = call.arguments["task"].encode("utf-8")
            for reference in call.arguments.get("references", []):
                reference.encode("utf-8")
        except UnicodeError:
            raise ToolExecutionError("agent task and references must be valid UTF-8 text") from None
        if len(task_bytes) > MAX_BYTES:
            raise ToolExecutionError("agent task exceeds 32 KiB")
        revalidate(expected)
        if self.plan_state:
            raise ToolExecutionError("ChatGPT plan limit reached in this execution; Subagent not dispatched")
        if not _guard.acquire(blocking=False):
            raise ToolExecutionError("another Subagent is already active")
        try:
            return self._run(call, expected)
        finally:
            _guard.release()

    def _run(self, call, role):
        from personal_agent.subagents.worker import run
        execution = call_log.latest_execution()
        if execution is None:
            raise ToolExecutionError("Subagent requires an open parent execution")
        context = multiprocessing.get_context("spawn")
        try:
            parent, child = context.Pipe()
            try:
                watch_parent, watch_child = context.Pipe()
            except BaseException:
                parent.close()
                child.close()
                raise
        except OSError as exc:
            raise ToolExecutionError(f"cannot create Subagent IPC: {exc}") from exc
        metadata = {"parent_session_id": call_log.current_session_id(), "parent_execution": execution,
                    "parent_tool_call_id": call.id, "agent_name": role.name}
        sid = call_log.mint_session_id()
        payload = {"config": self.config, "workspace": self.workspace, "shell": self.shell,
                   "capabilities": self.capabilities, "role": role, "instructions": self.instructions,
                   "task": call.arguments["task"], "references": call.arguments.get("references", []),
                   "metadata": metadata, "session_id": sid, "protected_keys": self.secrets,
                   "detailed_audit": call_log.detail_enabled()}
        process = context.Process(target=run, args=(child, watch_child, payload, worker_bootstrap), daemon=False)
        attribution = {"parent_execution": execution, "parent_tool_call_id": call.id, "agent_name": role.name}
        result = None
        groups = set()
        interrupted = False
        fatal_failure = False
        def handle(message, stopping=False):
            nonlocal fatal_failure
            if not isinstance(message, dict):
                raise ToolExecutionError("malformed child IPC")
            kind = message.get("kind")
            if kind == "ready" and message.get("session_id") == sid:
                return None
            def reply(value):
                send(parent, {"seq": message.get("seq"), "value": value})
            if kind == "receipt" and isinstance(message.get("receipt"), dict):
                call_log.credit_delegated_attempt(sid, message["receipt"], **attribution)
                reply(True)
            elif kind == "group":
                pgid = message.get("pgid")
                if type(pgid) is not int or pgid <= 1 or pgid == os.getpgrp():
                    raise ToolExecutionError("invalid child process group")
                if message.get("event") == "started":
                    groups.add(pgid)
                elif message.get("event") == "finished":
                    groups.discard(pgid)
                else:
                    raise ToolExecutionError("invalid child process event")
                reply(True)
            elif kind == "mode":
                reply("plan" if stopping else self.mode() if callable(self.mode) else self.mode)
            elif kind == "confirm":
                args = message.get("arguments")
                if (not isinstance(args, list) or len(args) != 5
                        or any(not isinstance(value, str) for value in args[:3])
                        or any(not isinstance(value, (list, tuple)) for value in args[3:])):
                    raise ToolExecutionError("malformed child confirmation")
                args[1] = f"{role.name} / {sid}: {args[1]}"
                reply(bool(not stopping and self.confirm and self.confirm(*args)))
            elif kind == "tool" and isinstance(message.get("result"), ToolResult):
                if self.output is not None and not stopping:
                    output = message["result"]
                    self.output(replace(output, name=f"{role.name}/{sid}: {output.name}"))
            elif kind == "fatal":
                fatal_failure = True
                if not stopping:
                    raise call_log.PersistenceError("Subagent evidence persistence failed; dependent dispatch stopped")
            elif kind == "result":
                outcome = message.get("result")
                exhausted = isinstance(outcome, dict) and outcome.get("condition") == "plan_exhausted"
                if exhausted:
                    outcome = {key: value for key, value in outcome.items() if key != "condition"}
                if (not isinstance(outcome, dict) or outcome.get("status") not in {"completed", "error"}
                        or set(outcome) != {"status", "answer" if outcome["status"] == "completed" else "error"}
                        or not isinstance(outcome.get("answer", outcome.get("error")), str)
                        or len(outcome.get("answer", outcome.get("error")).encode()) > MAX_BYTES):
                    raise ToolExecutionError("malformed child outcome")
                if exhausted and outcome["status"] == "error" and self.config.provider == "chatgpt":
                    self.plan_state.append(f"Subagent {role.name} stopped: {outcome['error']}")
                return outcome
            else:
                raise ToolExecutionError("unexpected child IPC message")
            return None
        try:
            call_log.write_delegation("started", child_session_id=sid, **attribution)
            process.start()
            child.close()
            watch_child.close()
            while result is None:
                def wait_message():
                    while not parent.poll(0.05):
                        if not process.is_alive():
                            raise ToolExecutionError(f"worker exited without a handoff (exit {process.exitcode})")
                    return receive(parent)
                result = handle(self.run_busy(wait_message))
            process.join(timeout=3)
            if process.exitcode != 0:
                raise ToolExecutionError(f"worker exit {process.exitcode}")
        except KeyboardInterrupt:
            interrupted = True
            if result is None:
                result = {"status": "error", "error": "Subagent interrupted"}
        except (EOFError, BrokenPipeError, OSError, ValueError, ToolExecutionError) as exc:
            error = "child IPC closed before a handoff" if isinstance(exc, (EOFError, BrokenPipeError)) else str(exc)
            result = {"status": "error", "error": bounded(error, sid)}
        finally:
            forced = []
            swap = threading.current_thread() is threading.main_thread()
            if swap:
                previous = signal.signal(signal.SIGINT, lambda *args: forced.append(True))
            try:
                if process.pid is not None:
                    if process.is_alive():
                        try:
                            os.kill(process.pid, signal.SIGINT)
                        except ProcessLookupError:
                            pass
                        deadline = time.monotonic() + GRACE_SECONDS
                        while process.is_alive() and not forced and time.monotonic() < deadline:
                            try:
                                if parent.poll(0.05):
                                    handle(receive(parent), stopping=True)
                            except (EOFError, BrokenPipeError, OSError, ValueError, ToolExecutionError,
                                    call_log.PersistenceError, call_log.AuditError):
                                break
                        process.join(timeout=0)
                    if process.is_alive():
                        process.kill()
                    process.join(timeout=2)
                process.close()
                self._stop_groups(groups)
                parent.close()
                child.close()
                watch_parent.close()
                watch_child.close()
                def finish(coverage):
                    nonlocal interrupted
                    interrupted = interrupted or bool(forced)
                    call_log.write_delegation("finished", child_session_id=sid,
                                              status="interrupted" if interrupted else (result or {}).get("status", "error"),
                                              coverage=coverage, **attribution)
                try:
                    coverage = self._reconcile(sid, attribution)
                except call_log.PersistenceError:
                    try:
                        finish("incomplete")
                    except (call_log.PersistenceError, call_log.AuditError):
                        pass
                    raise
                finish("incomplete" if fatal_failure else coverage)
            finally:
                if swap:
                    signal.signal(signal.SIGINT, previous)
        if interrupted and result.get("status") == "completed":
            result = {"status": "error", "error": "Subagent interrupted after completing its handoff",
                      "answer": result["answer"]}
        result = call_log.redact_data({"name": role.name, "session_id": sid, **result}, self.secrets)
        if interrupted:
            exc = KeyboardInterrupt()
            exc.partial_results = [ToolResult(call.id, call.name, result, True, call.id_is_generated, call.arguments)]
            raise exc
        return result

    @staticmethod
    def _stop_groups(groups):
        from personal_agent.tools import shell
        shell.kill_process_groups([(None, pgid) for pgid in groups])

    def _reconcile(self, sid, attribution):
        from personal_agent import session_logs
        complete = False
        try:
            for row in session_logs.records(call_log.storage_identity()["project_id"], sid):
                if row["warning"] or row["entry"] is None:
                    return "incomplete"
                entry = row["entry"]
                if entry.get("type") == "attempt":
                    call_log.credit_delegated_attempt(sid, entry, **attribution)
                elif entry.get("type") == "session_end":
                    complete = True
        except (OSError, ValueError):
            return "incomplete"
        return "complete" if complete else "incomplete"
