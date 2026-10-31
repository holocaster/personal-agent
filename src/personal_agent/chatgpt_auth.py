import base64
import fcntl
import hashlib
import http.client
import json
import math
import os
import re
import secrets
import stat
import time
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

import jwt

from personal_agent.model_catalog import Offering
from personal_agent.terminal.tty import sanitize_control_chars

ISSUER = "https://auth.openai.com"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
JWKS = ISSUER + "/.well-known/jwks.json"
DISCOVERY = ISSUER + "/.well-known/openid-configuration"
RESOURCE = "https://api.openai.com/v1"
MODELS = RESOURCE + "/models"
USAGE_URL = "https://chatgpt.com/settings/usage"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
DIRECT = "chatgpt.tokens.use.direct"
MAX_BYTES = 8 * 1024 * 1024
STORE_BYTES = 1024 * 1024
LOGIN_SECONDS = 300
KNOWN_SECRETS: set[str] = set()


class AuthError(Exception):
    pass


class TemporaryError(AuthError):
    pass


class TerminalError(AuthError):
    pass


def valid_reference(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None


def account_label(reference):
    return "ChatGPT account " + reference[:12]


@dataclass(frozen=True)
class Binding:
    registration: str
    generation: str


@dataclass(frozen=True)
class Status:
    connected: bool = False
    permission: bool = False
    acknowledged: bool = False
    label: str = "disconnected"
    binding: Binding | None = None
    selected_model: str | None = None


@dataclass(frozen=True)
class Credentials:
    access_token: str = field(repr=False)
    binding: Binding


def _learn(*values):
    KNOWN_SECRETS.update(value for value in values if isinstance(value, str) and value)


def safe(text: str) -> str:
    for secret in sorted(KNOWN_SECRETS, key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    return sanitize_control_chars(text, multiline=False)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise AuthError("ChatGPT refused an HTTP redirect")


_open = build_opener(_NoRedirect).open


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("invalid number")
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError):
        raise AuthError("ChatGPT returned malformed JSON") from None


def _request(url, *, form=None, bearer=None):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc not in {"auth.openai.com", "api.openai.com"}
            or parts.username or parts.fragment):
        raise AuthError("ChatGPT refused an untrusted endpoint")
    headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(url, data=urlencode(form).encode() if form is not None else None, headers=headers)
    try:
        with _open(request, timeout=10) as response:
            if response.status != 200:
                raise AuthError("ChatGPT returned an unexpected HTTP status")
            if response.headers.get("Content-Encoding", "identity") not in {"", "identity"}:
                raise AuthError("ChatGPT returned unsupported compressed data")
            chunks, total = [], 0
            deadline = time.monotonic() + 30
            while True:
                if time.monotonic() >= deadline:
                    raise TemporaryError("ChatGPT response timed out; retry later")
                chunk = response.read1(min(65536, MAX_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_BYTES:
                    raise AuthError("ChatGPT response exceeds 8 MiB")
            raw = b"".join(chunks)
            return _json(raw) if raw else None
    except HTTPError as exc:
        code = exc.code
        try:
            error = _json(exc.read(65537))
        except (AuthError, OSError):
            error = None
        finally:
            exc.close()
        if code >= 500 or code in {408, 429}:
            raise TemporaryError(f"ChatGPT temporarily unavailable (HTTP {code}); retry later") from None
        if (url == TOKEN and code in {400, 401} and isinstance(error, dict)
                and isinstance(error.get("error"), str)
                and error["error"] in {"invalid_grant", "invalid_client", "invalid_token", "refresh_token_invalidated"}):
            raise TerminalError("ChatGPT session invalid; reconnect with /connect chatgpt") from None
        raise AuthError(f"ChatGPT request denied (HTTP {code}); check permission/eligibility or configure your own API key with /config") from None
    except (OSError, http.client.HTTPException):
        raise TemporaryError("ChatGPT network unavailable; retry later") from None


def _check_file(fd, directory=False):
    info = os.fstat(fd)
    if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or (not directory and info.st_nlink != 1)):
        raise AuthError("Unsafe ChatGPT credential storage; require owned private directory/file (0700/0600)")


class ChatGPTAuth:
    def __init__(self, path=None, *, transport=None, browser=None):
        self.path = Path(path) if path is not None else Path.home() / ".personal_agent" / "chatgpt-auth.json"
        self.transport = transport or _request
        self.browser = browser or webbrowser.open

    @contextmanager
    def _locked(self):
        directory = lock = None
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            _check_file(directory, True)
            lock = os.open(self.path.name + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
            _check_file(lock)
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield directory
        except OSError:
            raise AuthError("ChatGPT private credential storage unavailable") from None
        finally:
            if lock is not None:
                os.close(lock)
            if directory is not None:
                os.close(directory)

    def _read(self, directory):
        try:
            fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return {"version": 1, "host": "urn:uuid:" + str(uuid4()), "registrations": [], "active": None, "revision": uuid4().hex}
        with os.fdopen(fd, "rb") as handle:
            _check_file(handle.fileno())
            raw = handle.read(STORE_BYTES + 1)
        if len(raw) > STORE_BYTES:
            raise AuthError("ChatGPT credential record exceeds limit")
        record = _json(raw)
        self._validate_record(record)
        session = record.get("session")
        if session:
            _learn(session["access_token"], session["refresh_token"], session["id_token"])
        return record

    def _validate_record(self, record):
        try:
            if not (isinstance(record, dict) and type(record["version"]) is int and record["version"] == 1):
                raise ValueError()
            if not (isinstance(record["host"], str) and 1 <= len(record["host"]) <= 256):
                raise ValueError()
            if not (isinstance(record["revision"], str) and len(record["revision"]) == 32):
                raise ValueError()
            pending = record.get("pending_client")
            if pending is not None and (not isinstance(pending, dict)
                    or not isinstance(pending.get("client_id"), str) or not 0 < len(pending["client_id"]) <= 1024
                    or pending["client_id"] == "dynamic_agent_client" or type(pending.get("different")) is not bool):
                raise ValueError()
            registrations = record["registrations"]
            if not (isinstance(registrations, list) and len(registrations) <= 1000):
                raise ValueError()
            refs = set()
            for item in registrations:
                if not (all(isinstance(item[key], str) and 0 < len(item[key]) <= 1024
                           for key in ("ref", "subject", "client_id", "issuer"))):
                    raise ValueError()
                if not (item["issuer"] == ISSUER and item["client_id"] != "dynamic_agent_client"):
                    raise ValueError()
                if not (item["ref"] not in refs):
                    raise ValueError()
                refs.add(item["ref"])
                if not (type(item["acknowledged"]) is bool):
                    raise ValueError()
            if not (record["active"] is None or record["active"] in refs):
                raise ValueError()
            session = record.get("session")
            if "session" in record:
                if not isinstance(session, dict) or not session:
                    raise ValueError()
                if not (record["active"] in refs):
                    raise ValueError()
                if not (all(isinstance(session[key], str) and 0 < len(session[key]) <= 65536
                           for key in ("generation", "access_token", "id_token"))):
                    raise ValueError()
                if re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", session["access_token"]) is None:
                    raise ValueError()
                if not isinstance(session["refresh_token"], str) or len(session["refresh_token"]) > 65536:
                    raise ValueError()
                if not (isinstance(session["scopes"], list) and len(session["scopes"]) <= 100
                        and all(isinstance(s, str) and len(s) <= 1024 for s in session["scopes"])):
                    raise ValueError()
                if not (type(session["expires_at"]) in (int, float) and math.isfinite(session["expires_at"])):
                    raise ValueError()
                if not (type(session["earliest_refresh_at"]) in (int, float) and math.isfinite(session["earliest_refresh_at"])):
                    raise ValueError()
                if not (session.get("selected_model") is None or isinstance(session["selected_model"], str)):
                    raise ValueError()
        except (AssertionError, KeyError, TypeError, ValueError):
            raise AuthError("Invalid ChatGPT credential record; repair private storage before continuing") from None

    def _save(self, directory, record):
        self._validate_record(record)
        record["revision"] = uuid4().hex
        payload = json.dumps(record, ensure_ascii=True).encode()
        if len(payload) > STORE_BYTES:
            raise AuthError("ChatGPT credential record exceeds limit")
        temporary = ".chatgpt-auth." + uuid4().hex
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path.name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass

    def _registration(self, record):
        return next((r for r in record["registrations"] if r["ref"] == record["active"]), None)

    def status(self):
        with self._locked() as directory:
            record = self._read(directory)
        registration, session = self._registration(record), record.get("session")
        if registration is None:
            return Status()
        label = account_label(registration["ref"])
        return Status(bool(session), bool(session and DIRECT in session["scopes"]),
                      registration["acknowledged"], label,
                      Binding(registration["ref"], session["generation"]) if session else None,
                      session.get("selected_model") if session else None)

    def _session(self, record, binding):
        session = record.get("session")
        if not session or record["active"] != binding.registration or session["generation"] != binding.generation:
            raise AuthError("ChatGPT session changed or disconnected; reconnect and select a model")
        return session

    def _identity(self, token, client_id, nonce=None):
        _learn(token)
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise ValueError()
            jwks = self.transport(JWKS)
            keys = [key for key in jwks["keys"] if key.get("kid") == header["kid"]
                    and key.get("kty") == "RSA" and key.get("alg", "RS256") == "RS256"
                    and key.get("use", "sig") == "sig"]
            if len(keys) != 1:
                raise ValueError()
            claims = jwt.decode(token, jwt.PyJWK.from_dict(keys[0]).key, algorithms=["RS256"],
                                issuer=ISSUER, audience=client_id, options={"require": ["exp", "iss", "sub", "aud"]})
            if not claims["sub"].strip() or len(claims["sub"]) > 1024:
                raise ValueError()
            if nonce is not None and claims.get("nonce") != nonce:
                raise ValueError()
            audience = claims["aud"]
            if ("azp" in claims and claims["azp"] != client_id
                    or isinstance(audience, list) and len(audience) > 1 and claims.get("azp") != client_id):
                raise ValueError()
            return claims
        except (jwt.PyJWTError, ValueError, KeyError, TypeError, AttributeError):
            raise AuthError("ChatGPT ID token verification failed; earlier connection preserved") from None

    def _tokens(self, data, client_id, *, nonce=None, previous=None):
        if isinstance(data, dict):
            _learn(*(data.get(key) for key in ("access_token", "refresh_token", "id_token")))
        try:
            if not (isinstance(data, dict) and data["token_type"].lower() == "bearer"):
                raise ValueError()
            if not (all(isinstance(data[key], str) and 0 < len(data[key]) <= 65536
                       for key in ("access_token", "id_token"))):
                raise ValueError()
            if re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", data["access_token"]) is None:
                raise ValueError()
            expires = data["expires_in"]
            if not (type(expires) in (float, int) and math.isfinite(expires) and expires > 0):
                raise ValueError()
            scope = data.get("scope")
            if not (isinstance(scope, str) or previous is not None and scope is None):
                raise ValueError()
            scopes = scope.split() if scope is not None else previous["scopes"]
            refresh = data.get("refresh_token", "")
            if (not isinstance(refresh, str) or len(refresh) > 65536
                    or not refresh and (previous is not None or "offline_access" in scopes)):
                raise ValueError()
            earliest = data.get("earliest_refresh_at", 0)
            if not (type(earliest) in (float, int) and math.isfinite(earliest) and earliest >= 0):
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError):
            raise AuthError("ChatGPT returned invalid credentials; earlier connection preserved") from None
        claims = self._identity(data["id_token"], client_id, nonce)
        session = {key: data[key] for key in ("access_token", "id_token")}
        session["refresh_token"] = refresh
        session.update(scopes=scopes, expires_at=time.time() + expires, earliest_refresh_at=earliest,
                       generation=previous["generation"] if previous else uuid4().hex,
                       selected_model=previous.get("selected_model") if previous else None)
        return session, claims

    def connect(self, *, different=False, enable_plan=False, cancel=None):
        with self._locked() as directory:
            record = self._read(directory)
            self._save(directory, record)
        registration = None if different else self._registration(record)
        pending = record.get("pending_client")
        issued_client = (registration["client_id"] if registration else
                         pending["client_id"] if pending and pending["different"] == different else None)
        previous_revision = record["revision"]
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        _learn(state, nonce, verifier)
        callback = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def setup(self):
                super().setup()
                self.connection.settimeout(0.5)

            def do_GET(self):
                try:
                    parts = urlsplit(self.path)
                    params = parse_qs(parts.query, keep_blank_values=True, max_num_fields=16, strict_parsing=True)
                    if not (parts.path == "/auth/callback" and not callback):
                        raise ValueError()
                    if not (all(len(values) == 1 and values[0] for values in params.values())):
                        raise ValueError()
                    if not (secrets.compare_digest(params["state"][0], state)):
                        raise ValueError()
                    if "error" in params:
                        if not ("code" not in params):
                            raise ValueError()
                        callback["error"] = True
                    else:
                        code = params["code"][0]
                        issued = params["client_id"][0]
                        if not (issued and issued != "dynamic_agent_client" and len(issued) <= 1024):
                            raise ValueError()
                        if issued_client is not None and issued != issued_client:
                            raise ValueError()
                        _learn(code)
                        callback.update(code=code, client_id=issued)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"Return to Personal Agent.")
                except (AssertionError, ValueError, KeyError):
                    self.send_response(400)
                    self.end_headers()
                except OSError:
                    pass

        try:
            with HTTPServer(("127.0.0.1", 0), Handler) as server:
                server.timeout = 0.1
                redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
                query = {"client_id": issued_client or "dynamic_agent_client",
                         "ext_agent_host_id": record["host"], "response_type": "code", "redirect_uri": redirect,
                         "scope": SCOPES, "resource": RESOURCE, "state": state, "nonce": nonce,
                         "code_challenge_method": "S256",
                         "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()}
                if registration:
                    if record.get("session"):
                        query["id_token_hint"] = record["session"]["id_token"]
                if issued_client is None:
                    query["agent_name_hint"] = "Personal Agent"
                if enable_plan:
                    query["prompt"] = "consent"
                url = AUTHORIZE + "?" + urlencode(query)
                _learn(url)
                if cancel is not None and cancel.is_set():
                    raise AuthError("ChatGPT connection cancelled; connection unchanged")
                if not self.browser(url):
                    raise AuthError("Could not open the local browser; connection unchanged")
                deadline = time.monotonic() + LOGIN_SECONDS
                while not callback:
                    if time.monotonic() >= deadline or cancel is not None and cancel.is_set():
                        raise AuthError("ChatGPT connection cancelled or timed out; connection unchanged")
                    server.handle_request()
            if callback.get("error"):
                raise AuthError("ChatGPT authorization declined; enable plan use explicitly or configure your own API key with /config")
            if registration is None:
                with self._locked() as directory:
                    latest = self._read(directory)
                    if latest["revision"] != previous_revision:
                        raise AuthError("ChatGPT session changed during login; connection was not replaced")
                    latest["pending_client"] = {"client_id": callback["client_id"], "different": different}
                    self._save(directory, latest)
                    previous_revision = latest["revision"]
            data = self.transport(TOKEN, form={"grant_type": "authorization_code", "client_id": callback["client_id"],
                                  "code": callback["code"], "code_verifier": verifier,
                                  "redirect_uri": redirect, "resource": RESOURCE})
            session, claims = self._tokens(data, callback["client_id"], nonce=nonce)
            if registration and (claims["iss"], claims["sub"]) != (registration["issuer"], registration["subject"]):
                raise AuthError("ChatGPT returning identity mismatch; earlier connection preserved. Use /connect chatgpt different")
            with self._locked() as directory:
                latest = self._read(directory)
                if latest["revision"] != previous_revision:
                    raise AuthError("ChatGPT session changed during login; connection was not replaced")
                if registration is None:
                    registration = next((r for r in latest["registrations"] if
                                         (r["issuer"], r["subject"], r["client_id"]) ==
                                         (claims["iss"], claims["sub"], callback["client_id"])), None)
                    if registration is None:
                        registration = {"ref": uuid4().hex, "issuer": claims["iss"], "subject": claims["sub"],
                                        "client_id": callback["client_id"], "acknowledged": False}
                        latest["registrations"].append(registration)
                latest.update(active=registration["ref"], session=session)
                latest.pop("pending_client", None)
                self._save(directory, latest)
            return Binding(registration["ref"], session["generation"])
        except (KeyboardInterrupt, EOFError):
            raise AuthError("ChatGPT connection cancelled; connection unchanged") from None
        except OSError:
            raise AuthError("ChatGPT connection or credential save failed; earlier connection preserved") from None

    def models(self, binding):
        credentials = self.resolve(binding, require_ack=False)
        data = self.transport(MODELS, bearer=credentials.access_token)
        try:
            if not (isinstance(data, dict) and isinstance(data["models"], list) and len(data["models"]) <= 10000):
                raise ValueError()
            result, seen = [], set()
            for model in data["models"]:
                if not (isinstance(model, dict) and isinstance(model["visibility"], str)):
                    raise ValueError()
                if model["visibility"] != "list":
                    continue
                slug, name = model["slug"], model["display_name"]
                if not (isinstance(slug, str) and 0 < len(slug) <= 256 and slug == slug.strip()):
                    raise ValueError()
                if safe(slug) != slug or any(ord(c) < 33 or ord(c) == 127 for c in slug):
                    raise ValueError()
                if not (isinstance(name, str) and 0 < len(name) <= 256 and slug not in seen):
                    raise ValueError()
                seen.add(slug)
                levels = model.get("supported_reasoning_levels", [])
                if not isinstance(levels, list) or len(levels) > 32:
                    raise ValueError()
                efforts = []
                for level in levels:
                    effort = level.get("effort") if isinstance(level, dict) else None
                    if (not isinstance(effort, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", effort)
                            or safe(effort) != effort or effort == "auto" or effort in efforts):
                        raise ValueError()
                    efforts.append(effort)
                default = model.get("default_reasoning_level")
                if "default_reasoning_level" in model and (not isinstance(default, str)
                        or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", default) or safe(default) != default or default == "auto"
                        or "supported_reasoning_levels" in model and default not in efforts):
                    raise ValueError()
                result.append(Offering("chatgpt", slug, safe(name), None, None, None, None, None,
                                       tuple(efforts), default))
        except (ValueError, KeyError, TypeError):
            raise AuthError("ChatGPT returned an invalid account model list; retry /models chatgpt") from None
        with self._locked() as directory:
            self._session(self._read(directory), binding)
        return result

    def resolve(self, binding, *, require_ack=True):
        with self._locked() as directory:
            record = self._read(directory)
            session = self._session(record, binding)
            registration = self._registration(record)
            if DIRECT not in session["scopes"]:
                raise AuthError("ChatGPT plan permission disabled; /connect chatgpt enable-plan or configure your own API key with /config")
            if require_ack and not registration["acknowledged"]:
                raise AuthError("Acknowledge plan use in an interactive /connect chatgpt before continuing")
            if (time.time() >= session["expires_at"] - 60
                    and (time.time() >= session["earliest_refresh_at"] or time.time() >= session["expires_at"])):
                try:
                    if not session["refresh_token"]:
                        raise TerminalError("ChatGPT session expired; reconnect with /connect chatgpt")
                    data = self._retry(lambda: self.transport(TOKEN, form={"grant_type": "refresh_token",
                                       "client_id": registration["client_id"], "refresh_token": session["refresh_token"],
                                       "resource": RESOURCE}))
                    rotated, claims = self._tokens(data, registration["client_id"], previous=session)
                    if (claims["iss"], claims["sub"]) != (registration["issuer"], registration["subject"]):
                        raise TerminalError("ChatGPT refreshed identity mismatch; reconnect")
                    record["session"] = session = rotated
                    self._save(directory, record)
                except TerminalError:
                    record.pop("session", None)
                    self._save(directory, record)
                    raise
            if DIRECT not in session["scopes"]:
                raise AuthError("ChatGPT plan permission disabled after refresh; enable plan use or configure your own API key")
            return Credentials(session["access_token"], binding)

    def _retry(self, operation):
        for attempt in range(3):
            try:
                return operation()
            except TemporaryError:
                if attempt == 2:
                    raise
                time.sleep(0.1 * 2 ** attempt)

    def acknowledge(self, binding):
        with self._locked() as directory:
            record = self._read(directory)
            self._session(record, binding)
            self._registration(record)["acknowledged"] = True
            self._save(directory, record)

    def activate(self, binding, slug, save_pair):
        with self._locked() as directory:
            record = self._read(directory)
            session = self._session(record, binding)
            if DIRECT not in session["scopes"] or not self._registration(record)["acknowledged"]:
                raise AuthError("ChatGPT plan permission/notice acknowledgement required")
            previous = session.get("selected_model")
            session["selected_model"] = slug
            self._save(directory, record)
            try:
                save_pair()
            except BaseException:
                session["selected_model"] = previous
                self._save(directory, record)
                raise

    def disconnect(self):
        confirmed = True
        with self._locked() as directory:
            record = self._read(directory)
            registration, session = self._registration(record), record.get("session")
            if session:
                try:
                    def revoke():
                        discovery = self.transport(DISCOVERY)
                        endpoint = discovery["revocation_endpoint"]
                        parts = urlsplit(endpoint)
                        if (discovery.get("issuer") != ISSUER or parts.scheme != "https"
                                or parts.netloc != "auth.openai.com" or parts.fragment):
                            raise AuthError("Untrusted ChatGPT revocation discovery")
                        self.transport(endpoint, form={"token": session["refresh_token"],
                                       "token_type_hint": "refresh_token", "client_id": registration["client_id"]})
                    if session["refresh_token"]:
                        self._retry(revoke)
                except (AuthError, KeyError, TypeError, ValueError):
                    confirmed = False
                record.pop("session", None)
            self._save(directory, record)
        return confirmed
