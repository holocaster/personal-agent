import base64
import copy
import difflib
import hashlib
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path

from personal_agent import call_log
from personal_agent.tools.builtins import ToolExecutionError

IMAGE_LIMIT = 4 * 1024 * 1024
SNAPSHOT_LIMIT = 16 * 1024 * 1024
MANIFEST_LIMIT = 24 * 1024 * 1024
STORAGE_LIMIT = 80 * 1024 * 1024
PATH_LIMIT = 64


def image_limit():
    from personal_agent.tools.workspace import configured_workspace
    return min(IMAGE_LIMIT, configured_workspace().max_write_bytes)


def _image(data, mode=0o600):
    if data is None:
        return {"exists": False}
    if len(data) > image_limit():
        raise ToolExecutionError(f"file recovery image exceeds {image_limit()} bytes")
    return {"exists": True, "data": base64.b64encode(data).decode("ascii"),
            "sha256": hashlib.sha256(data).hexdigest(), "mode": mode}


def _bytes(state):
    return base64.b64decode(state["data"], validate=True) if state["exists"] else None


def _identities(effect):
    return [effect["identity"], *effect.get("aliases", [])]


def _validate_path_identity(identity):
    if not isinstance(identity, dict) or set(identity) != {"supplied", "canonical", "parents", "target_parents", "link"}:
        raise ValueError("invalid recovery path identity")
    for key in ("supplied", "canonical"):
        value = identity[key]
        if (not isinstance(value, str) or not value or len(value) > 4096
                or Path(value).is_absolute() or ".." in Path(value).parts or Path(value).as_posix() != value):
            raise ValueError("invalid recovery path")
    for key in ("parents", "target_parents"):
        if (not isinstance(identity[key], list) or not identity[key] or len(identity[key]) > 1024
                or any(not isinstance(pair, list) or len(pair) != 2
                       or any(type(value) is not int or value < 0 for value in pair)
                       for pair in identity[key])):
            raise ValueError("invalid recovery parent identity")
    link = identity["link"]
    if link is not None and (not isinstance(link, dict) or set(link) != {"target", "device", "inode"}
            or not isinstance(link["target"], str) or not link["target"] or len(link["target"]) > 4096
            or any(type(link[key]) is not int or link[key] < 0 for key in ("device", "inode"))):
        raise ValueError("invalid recovery leaf link identity")


@contextmanager
def _parent(relative):
    from personal_agent.tools.workspace import configured_workspace
    root = configured_workspace().root
    path = Path(relative)
    if not isinstance(relative, str) or path.is_absolute() or not path.name or ".." in path.parts:
        raise ToolExecutionError("invalid recovery path")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identities = []
    try:
        info = os.fstat(fd)
        identities.append([info.st_dev, info.st_ino])
        for part in path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            identities.append([info.st_dev, info.st_ino])
        yield fd, path.name, identities
    finally:
        os.close(fd)


def _identity(supplied):
    from personal_agent.tools.workspace import configured_workspace, _is_excluded
    root = configured_workspace().root
    path = Path(supplied)
    if _is_excluded(path):
        raise ToolExecutionError("requested file is excluded from recovery")
    with _parent(supplied) as (fd, name, parents):
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            info = None
        link = None
        if info is not None and stat.S_ISLNK(info.st_mode):
            link = {"target": os.readlink(name, dir_fd=fd), "device": info.st_dev, "inode": info.st_ino}
    resolved = (root / path).resolve(strict=False)
    try:
        canonical = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ToolExecutionError("recovery path resolves outside the workspace") from exc
    if _is_excluded(resolved):
        raise ToolExecutionError("resolved file is excluded from recovery")
    storage = Path(call_log.session_log_path()).parent
    if resolved.is_relative_to(storage):
        raise ToolExecutionError("Session storage is excluded from recovery")
    with _parent(canonical) as (_, _, target_parents):
        pass
    return {"supplied": supplied, "canonical": canonical, "parents": parents,
            "target_parents": target_parents, "link": link}


def observe(identity):
    if _identity(identity["supplied"]) != identity:
        raise ToolExecutionError(f"recovery path identity changed: {identity['supplied']}")
    with _parent(identity["canonical"]) as (parent, name, _):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except FileNotFoundError:
            return _image(None)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ToolExecutionError(f"recovery requires a regular file without hard links: {identity['supplied']}")
            if info.st_size > image_limit():
                raise ToolExecutionError(f"file recovery image exceeds {image_limit()} bytes")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(image_limit() + 1)
            return _image(data, stat.S_IMODE(info.st_mode))
        finally:
            os.close(fd)


def prepare_effect(path, data, original):
    try:
        identity = _identity(path)
        before = observe(identity)
        if _bytes(before) != original:
            raise ToolExecutionError(f"file changed during preparation: {path}")
        if data is None and identity["link"] is not None:
            raise ToolExecutionError("deleting leaf symlinks is unavailable for file recovery")
        return {"identity": identity, "before": before,
                "after": _image(data, before.get("mode", 0o600))}
    except (OSError, ValueError) as exc:
        raise ToolExecutionError(f"cannot prepare file recovery for {path}: {exc}") from exc


def put(identity, state):
    if _identity(identity["supplied"]) != identity:
        raise ToolExecutionError(f"recovery path identity changed: {identity['supplied']}")
    with _parent(identity["canonical"]) as (parent, name, _):
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            info = None
        if info is not None and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ToolExecutionError(f"unsafe recovery target: {identity['supplied']}")
        if not state["exists"]:
            if info is not None:
                os.unlink(name, dir_fd=parent)
        else:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
            try:
                opened = os.fstat(fd)
                if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                    raise ToolExecutionError("unsafe recovery write target")
                with os.fdopen(fd, "wb", closefd=False) as stream:
                    stream.truncate(0)
                    data = _bytes(state)
                    if stream.write(data) != len(data):
                        raise OSError("short file write")
                    stream.flush()
                os.fchmod(fd, state["mode"])
                os.fsync(fd)
            finally:
                os.close(fd)
        os.fsync(parent)


def apply_effects(effects):
    try:
        for effect in effects:
            if observe(effect["identity"]) != effect["before"]:
                raise ToolExecutionError(f"file changed after preparation: {effect['identity']['supplied']}")
        touched = []
        try:
            for effect in effects:
                if effect["before"] == effect["after"]:
                    continue
                touched.append(effect)
                put(effect["identity"], effect["after"])
        except (OSError, ToolExecutionError) as exc:
            failures = []
            for effect in reversed(touched):
                try:
                    if observe(effect["identity"]) != effect["before"]:
                        put(effect["identity"], effect["before"])
                except (OSError, ToolExecutionError):
                    failures.append(effect["identity"]["supplied"])
            message = f"file mutation failed for {touched[-1]['identity']['supplied']}: {exc}"
            if failures:
                message += f"; could not restore: {', '.join(failures)}"
            raise ToolExecutionError(message) from exc
    except OSError as exc:
        raise ToolExecutionError(f"file mutation failed: {exc}") from exc


class FileRecovery:
    def __init__(self):
        self.session = call_log.current_session_id()
        self.execution = None
        self.latest = None
        self.active = None
        self.blocked = None
        try:
            self._check_storage()
            self.latest = self._read("latest.json")
            self.active = self._read("active.json")
            for manifest in (self.latest, self.active):
                if manifest is not None:
                    call_log.execution_outcome(manifest["execution"], self.session)
            self._reconcile()
        except (OSError, ValueError, ToolExecutionError, call_log.ResumeError) as exc:
            self.blocked = f"unresolved file recovery: {exc}"

    def _check_storage(self):
        try:
            with self._directory() as directory:
                total = 0
                for name in os.listdir(directory):
                    if name not in {"latest.json", "active.json", "manifest.tmp"}:
                        raise OSError("unexpected recovery storage file")
                    fd = self._open(directory, name, os.O_RDONLY)
                    total += os.fstat(fd).st_size
                    os.close(fd)
                if total > STORAGE_LIMIT:
                    raise ValueError("recovery storage exceeds 80 MiB")
        except FileNotFoundError:
            pass

    @contextmanager
    def _directory(self, create=False):
        project = call_log.storage_identity()["project_id"]
        with call_log.storage_directory(project, create=create, private=create) as parent:
            name = f"recovery-{self.session}"
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=parent)
                except FileExistsError:
                    pass
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                if not create:
                    with call_log.storage_directory(project, private=True):
                        pass
                info = os.fstat(fd)
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise OSError("unsafe recovery directory permissions or owner")
                yield fd
            finally:
                os.close(fd)

    def _read(self, name):
        try:
            with self._directory() as directory:
                fd = self._open(directory, name, os.O_RDONLY)
                with os.fdopen(fd, "rb") as stream:
                    raw = stream.read(MANIFEST_LIMIT + 1)
                if len(raw) > MANIFEST_LIMIT:
                    raise ValueError("recovery manifest exceeds byte limit")
                manifest = json.loads(raw)
                self._validate(manifest)
                return manifest
        except FileNotFoundError:
            return None

    def _open(self, directory, name, flags):
        fd = os.open(name, (flags & ~os.O_TRUNC) | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > MANIFEST_LIMIT):
                raise OSError("unsafe recovery file permissions, owner, type or size")
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _validate(self, manifest):
        required = {"version", "session_id", "project_id", "workspace_root", "execution", "outcome", "state", "entries", "pending", "progress"}
        if (not isinstance(manifest, dict) or set(manifest) != required or type(manifest["version"]) is not int
                or manifest["version"] != 1 or manifest["session_id"] != self.session
                or any(manifest[key] != value for key, value in call_log.storage_identity().items())
                or not isinstance(manifest["state"], str)
                or manifest["state"] not in {"capturing", "ready", "restoring", "recovered", "unresolved"}
                or not isinstance(manifest["outcome"], str)
                or manifest["outcome"] not in {"open", "ok", "error", "interrupted", "unknown"}):
            raise ValueError("invalid recovery schema or Session/project identity")
        reference = manifest["execution"]
        if (not isinstance(reference, dict) or set(reference) != {"run_id", "opening", "ordinal"}
                or not isinstance(reference["run_id"], str) or len(reference["run_id"]) != 32
                or any(ch not in "0123456789abcdef" for ch in reference["run_id"])
                or any(type(reference[key]) is not int or reference[key] <= 0 for key in ("opening", "ordinal"))):
            raise ValueError("invalid recovery execution identity")
        total = 0
        for collection in ("entries", "pending"):
            values = manifest[collection]
            if not isinstance(values, list) or len(values) > PATH_LIMIT:
                raise ValueError("recovery exceeds 64 paths")
            seen = set()
            for effect in values:
                if (not isinstance(effect, dict) or set(effect) not in (
                        {"identity", "before", "after"}, {"identity", "before", "after", "aliases"})
                        or not isinstance(effect.get("aliases", []), list) or len(effect.get("aliases", [])) > PATH_LIMIT):
                    raise ValueError("invalid recovery effect")
                identity = effect["identity"]
                for alias in _identities(effect):
                    _validate_path_identity(alias)
                    if (alias["canonical"] != identity["canonical"]
                            or alias["target_parents"] != identity["target_parents"]):
                        raise ValueError("inconsistent recovery alias identity")
                if identity["canonical"] in seen:
                    raise ValueError("duplicate canonical recovery path")
                seen.add(identity["canonical"])
                for key in ("before", "after"):
                    state = effect[key]
                    if not isinstance(state, dict) or type(state.get("exists")) is not bool:
                        raise ValueError("invalid recovery image")
                    if not state["exists"]:
                        if state != {"exists": False}:
                            raise ValueError("invalid absent recovery image")
                        continue
                    if (set(state) != {"exists", "data", "sha256", "mode"} or not isinstance(state["data"], str)
                            or len(state["data"]) > 4 * ((image_limit() + 2) // 3)
                            or type(state["mode"]) is not int or not 0 <= state["mode"] <= 0o7777):
                        raise ValueError("invalid or oversized recovery image")
                    data = _bytes(state)
                    if len(data) > image_limit() or hashlib.sha256(data).hexdigest() != state["sha256"]:
                        raise ValueError("recovery image integrity or byte limit failure")
                    total += len(data)
        if total > SNAPSHOT_LIMIT:
            raise ValueError("recovery snapshots exceed 16 MiB")
        if (not isinstance(manifest["progress"], list) or len(manifest["progress"]) > PATH_LIMIT
                or any(type(index) is not int for index in manifest["progress"])
                or manifest["progress"] != list(range(len(manifest["progress"])))
                or len(manifest["progress"]) > len(manifest["entries"])):
            raise ValueError("invalid recovery restoration progress")

    def _encoded(self, manifest):
        self._validate(manifest)
        raw = json.dumps(manifest, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > MANIFEST_LIMIT:
            raise ValueError("recovery manifest exceeds 24 MiB")
        return raw

    def _reserve(self, candidate, intent):
        complete = copy.deepcopy(candidate)
        complete.update(state="unresolved", outcome="interrupted", progress=list(range(len(complete["entries"]))))
        size = max(len(self._encoded(complete)), len(self._encoded(intent)))
        latest_size = 0
        with self._directory(create=True) as directory:
            try:
                fd = self._open(directory, "latest.json", os.O_RDONLY)
            except FileNotFoundError:
                pass
            else:
                latest_size = os.fstat(fd).st_size
                os.close(fd)
        if latest_size + 2 * size > STORAGE_LIMIT:
            raise ValueError("recovery Session storage would exceed 80 MiB")

    def _save(self, manifest, name="active.json"):
        raw = self._encoded(manifest)
        with self._directory(create=True) as directory:
            total = len(raw)
            for existing in os.listdir(directory):
                if existing not in {"active.json", "latest.json", "manifest.tmp"}:
                    raise OSError("unexpected file in recovery storage")
                fd = self._open(directory, existing, os.O_RDONLY)
                if existing != "manifest.tmp":
                    total += os.fstat(fd).st_size
                os.close(fd)
            if total > STORAGE_LIMIT:
                raise ValueError("recovery Session storage exceeds 80 MiB")
            fd = self._open(directory, "manifest.tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
            with os.fdopen(fd, "wb") as stream:
                stream.truncate(0)
                if stream.write(raw) != len(raw):
                    raise OSError("short recovery manifest write")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace("manifest.tmp", name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)

    def _promote(self, manifest):
        self._save(manifest)
        with self._directory() as directory:
            os.replace("active.json", "latest.json", src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        self.latest = manifest
        self.active = None

    def _discard_active(self):
        with self._directory() as directory:
            os.unlink("active.json", dir_fd=directory)
            os.fsync(directory)
        self.active = None

    def _merge(self, manifest, effects):
        for effect in effects:
            old = next((entry for entry in manifest["entries"]
                        if entry["identity"]["canonical"] == effect["identity"]["canonical"]), None)
            if old is not None:
                if (old["after"] != effect["before"]
                        or old["identity"]["target_parents"] != effect["identity"]["target_parents"]
                        or any(_identity(alias["supplied"]) != alias for alias in _identities(old))):
                    raise ToolExecutionError(f"external change between mutations: {effect['identity']['supplied']}")
                if effect["identity"] not in _identities(old):
                    old.setdefault("aliases", []).append(copy.deepcopy(effect["identity"]))
                old["after"] = copy.deepcopy(effect["after"])
            elif effect["before"] != effect["after"]:
                manifest["entries"].append(copy.deepcopy(effect))

    def _reconcile(self):
        manifest = self.active
        if manifest is None:
            if self.latest and self.latest["state"] == "unresolved":
                self.blocked = "unresolved file recovery journal"
            return
        if manifest["state"] == "capturing":
            observed = []
            for effect in manifest["pending"]:
                state = observe(effect["identity"])
                if state == effect["after"]:
                    observed.append(effect)
                elif state != effect["before"]:
                    raise ToolExecutionError(f"ambiguous interrupted mutation: {effect['identity']['supplied']}")
            self._merge(manifest, observed)
            manifest.update(pending=[], state="ready", outcome="unknown")
            if manifest["entries"]:
                self._promote(manifest)
            else:
                self._discard_active()
        elif manifest["state"] == "restoring":
            for index, effect in enumerate(manifest["entries"]):
                state = observe(effect["identity"])
                if index in manifest["progress"]:
                    if state != effect["before"]:
                        raise ToolExecutionError(f"interrupted restore conflict: {effect['identity']['supplied']}")
                elif state not in (effect["before"], effect["after"]):
                    raise ToolExecutionError(f"ambiguous interrupted restore: {effect['identity']['supplied']}")
            self.blocked = "unresolved interrupted restoration; files were not automatically restored"
        elif manifest["state"] == "ready":
            self._promote(manifest)
        elif manifest["state"] == "recovered":
            completed = call_log.file_recovery_outcome(manifest["execution"], self.session) == "ok"
            if completed and all(observe(e["identity"]) == e["before"] for e in manifest["entries"]):
                self._promote(manifest)
            else:
                self.blocked = "unresolved recovery completion; verify durable Call Log completion"
        else:
            self.blocked = "unresolved file recovery journal"

    def ensure_safe(self):
        if self.blocked:
            raise call_log.PersistenceError(self.blocked)

    def begin(self, reference):
        self.ensure_safe()
        self.execution = reference

    def apply(self, prepared, operation):
        self.ensure_safe()
        effects = list(prepared.effects)
        try:
            for effect in effects:
                if observe(effect["identity"]) != effect["before"]:
                    raise ToolExecutionError(f"file changed after preparation: {effect['identity']['supplied']}")
            manifest = (copy.deepcopy(self.latest) if self.latest and self.latest["execution"] == self.execution
                        else {"version": 1, "session_id": self.session, **call_log.storage_identity(),
                              "execution": self.execution, "outcome": "open", "state": "capturing",
                              "entries": [], "pending": [], "progress": []})
            candidate = copy.deepcopy(manifest)
            self._merge(candidate, effects)
            self._validate(candidate)
            manifest.update(state="capturing", pending=copy.deepcopy(effects))
            self._reserve(candidate, manifest)
            self._save(manifest)
            self.active = manifest
        except (OSError, ValueError) as exc:
            raise ToolExecutionError(f"cannot capture file recovery before mutation: {exc}") from exc
        try:
            result = operation()
        except BaseException:
            try:
                self._reconcile()
            except (OSError, ValueError, ToolExecutionError) as exc:
                self.blocked = f"unresolved failed file mutation: {exc}"
                raise call_log.PersistenceError(self.blocked) from exc
            raise
        try:
            for effect in effects:
                if observe(effect["identity"]) != effect["after"]:
                    raise ToolExecutionError(f"unexpected file after mutation: {effect['identity']['supplied']}")
            self._merge(manifest, effects)
            manifest.update(pending=[], state="ready")
            if manifest["entries"]:
                self._promote(manifest)
            else:
                self._discard_active()
        except (OSError, ValueError, ToolExecutionError) as exc:
            self.blocked = f"unresolved file mutation after write: {exc}"
            raise call_log.PersistenceError(self.blocked) from exc
        return result

    def close(self, outcome):
        if self.latest and self.latest["execution"] == self.execution:
            manifest = copy.deepcopy(self.latest)
            manifest["outcome"] = outcome
            try:
                self._save(manifest, "latest.json")
            except (OSError, ValueError) as exc:
                raise call_log.PersistenceError(f"cannot close file recovery execution: {exc}") from exc
            self.latest = manifest

    def validate_current(self):
        if self.blocked:
            raise ToolExecutionError(self.blocked)
        manifest = self.latest
        if manifest is None or manifest["state"] == "recovered":
            raise ToolExecutionError("no available file checkpoint (already recovered or no file changes)")
        self._validate(manifest)
        if self._read("latest.json") != manifest:
            raise ToolExecutionError("file recovery manifest changed; nothing restored")
        conflicts = []
        for effect in manifest["entries"]:
            try:
                if any(observe(identity) != effect["after"] for identity in _identities(effect)):
                    conflicts.append(effect["identity"]["supplied"])
            except (OSError, ValueError, ToolExecutionError):
                conflicts.append(effect["identity"]["supplied"])
        if conflicts:
            raise ToolExecutionError("file recovery conflicts; nothing restored: " + ", ".join(conflicts))
        result = copy.deepcopy(manifest)
        result["outcome"] = call_log.execution_outcome(manifest["execution"], self.session)
        return result

    def preview(self, secrets=()):
        from personal_agent.terminal.tty import sanitize_control_chars

        def safe(text):
            return sanitize_control_chars(call_log.redact_value(text, secrets), multiline=True)

        manifest = self.validate_current()
        ref = manifest["execution"]
        parts = [f"File recovery: Session {self.session}, Run {ref['run_id']}, opening {ref['opening']}, "
                 f"ordinal {ref['ordinal']}; outcome {manifest['outcome']}.\n",
                 "Latest changed execution only; earlier Retry changes and shell effects are outside this set.\n",
                 "Exact owner-only snapshots; excludes .env, *.pem, *.key and Session storage. "
                 "Limits: min(PA_MAX_WRITE_BYTES, 4 MiB)/image, 64 paths, 16 MiB snapshots, "
                 "24 MiB/manifest, 80 MiB/Session.\n"]
        budget = 32000
        for effect in manifest["entries"]:
            path = ", ".join(identity["supplied"] for identity in _identities(effect))
            before, after = effect["before"], effect["after"]
            action = ("remove created file" if not before["exists"] else
                      "recreate deleted file" if not after["exists"] else "restore contents/mode")
            parts.append(safe(f"{path}: {action}, {after.get('mode', 'absent')} -> {before.get('mode', 'absent')}\n"))
            diff = safe("".join(difflib.unified_diff(
                (_bytes(after) or b"").decode("utf-8", errors="replace").splitlines(keepends=True),
                (_bytes(before) or b"").decode("utf-8", errors="replace").splitlines(keepends=True),
                fromfile=path, tofile=path)))
            parts.append(diff[:budget])
            if len(diff) > budget:
                parts.append("\n[reverse diff omitted beyond preview bound]\n")
            budget = max(0, budget - len(diff))
        preview = "".join(parts)
        return preview if len(preview) <= 60000 else preview[:60000] + "\n[paths/diff omitted beyond preview bound]\n"

    def restore(self, invalidate):
        manifest = copy.deepcopy(self.validate_current())
        reference = manifest["execution"]
        try:
            manifest.update(state="restoring", progress=[])
            self._save(manifest)
            self.active = manifest
            call_log.write_file_recovery("started", reference)
        except (OSError, ValueError) as exc:
            raise call_log.PersistenceError(f"cannot persist file recovery intent; no files restored: {exc}") from exc
        invalidate(reference)
        touched = []
        try:
            for index, effect in enumerate(manifest["entries"]):
                touched.append(effect)
                put(effect["identity"], effect["before"])
                manifest["progress"].append(index)
                try:
                    self._save(manifest)
                except (OSError, ValueError) as exc:
                    raise call_log.PersistenceError(f"cannot persist restoration progress: {exc}") from exc
            manifest["state"] = "recovered"
            try:
                self._save(manifest)
            except (OSError, ValueError) as exc:
                raise call_log.PersistenceError(f"cannot persist completed file restoration: {exc}") from exc
            call_log.write_file_recovery("finished", reference, "ok")
        except (OSError, ValueError, ToolExecutionError, call_log.PersistenceError) as exc:
            failures = []
            for effect in reversed(touched):
                try:
                    if observe(effect["identity"]) != effect["after"]:
                        put(effect["identity"], effect["after"])
                except (OSError, ValueError, ToolExecutionError):
                    failures.append(effect["identity"]["supplied"])
            message = f"file recovery failed: {exc}; affected: " + ", ".join(e["identity"]["supplied"] for e in touched)
            try:
                manifest.update(state="unresolved" if failures else "ready", progress=[])
                self._save(manifest)
                call_log.write_file_recovery("finished", reference, "error")
                if not failures:
                    self._discard_active()
            except (OSError, ValueError, call_log.PersistenceError) as failure:
                failures.append(f"recovery persistence: {failure}")
            if failures:
                self.blocked = message + "; could not roll back: " + ", ".join(failures)
                raise call_log.PersistenceError(self.blocked) from exc
            if isinstance(exc, call_log.PersistenceError):
                self.blocked = message + "; restored known after-states; persistence failure halted this Run"
                raise call_log.PersistenceError(self.blocked) from exc
            raise ToolExecutionError(message + "; restored known after-states") from exc
        try:
            self._promote(manifest)
        except (OSError, ValueError) as exc:
            self.blocked = f"unresolved recovery promotion after durable completion: {exc}"
            raise call_log.PersistenceError(self.blocked) from exc
