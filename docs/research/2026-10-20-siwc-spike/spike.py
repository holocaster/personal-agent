import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from pathlib import Path

DIR = Path(__file__).resolve().parent
HOST_FILE = DIR / "host_id"
TOKENS_FILE = Path(os.environ.get("SPIKE_TOKENS", DIR / "tokens.json"))
AUTH_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
API = "https://api.openai.com/v1"
RESOURCE = "https://api.openai.com/v1"
SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def host_id() -> str:
    if not HOST_FILE.exists():
        HOST_FILE.write_text(f"urn:uuid:{uuid.uuid4()}")
    return HOST_FILE.read_text().strip()


def jwt_claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def fail(message: str):
    print("FAIL:", message)
    sys.exit(1)


def http_error(exc: urllib.error.HTTPError):
    body = exc.read().decode(errors="replace")[:2000]
    fail(f"HTTP {exc.code} request_id={exc.headers.get('x-request-id')} body={body}")


def wait_for_callback(state_holder: dict) -> tuple[str, dict]:
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path != "/auth/callback":
                self.send_response(404)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"personal-agent spike: done, you can close this tab.")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
    state_holder["start"](redirect)
    while not result:
        server.handle_request()
    server.server_close()
    return redirect, result


def login(reauth: bool = False):
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    previous = json.loads(TOKENS_FILE.read_text()) if reauth else None
    if reauth:
        identity = {"client_id": previous["client_id"], "id_token_hint": previous["id_token"],
                    "login_hint": jwt_claims(previous["id_token"]).get("email")}
    else:
        identity = {"client_id": "dynamic_agent_client", "agent_name_hint": "personal-agent"}

    def start(redirect: str):
        params = {
            **identity,
            "ext_agent_host_id": host_id(),
            "response_type": "code",
            "redirect_uri": redirect,
            "scope": SCOPE,
            "resource": RESOURCE,
            "state": state,
            "nonce": nonce,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        url = AUTH_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        print("Opening browser. If it does not open, visit:\n" + url + "\n", flush=True)
        webbrowser.open(url)

    redirect, callback = wait_for_callback({"start": start})
    if callback.get("state") != state:
        fail("state mismatch")
    if "error" in callback:
        fail(f"authorize error: {callback.get('error')} {callback.get('error_description', '')}")
    client_id = callback.get("client_id")
    if reauth:
        if client_id and client_id != previous["client_id"]:
            fail("callback client_id differs from the registered one")
        print("reauth: callback client_id", "matches saved" if client_id else "omitted")
        client_id = previous["client_id"]
    if not client_id:
        fail(f"no client_id in callback, keys={sorted(callback)}")
    print("callback ok: client_id issued, callback scope =", callback.get("scope"))

    form = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": callback["code"],
        "code_verifier": verifier,
        "redirect_uri": redirect,
        "resource": RESOURCE,
    }).encode()
    request = urllib.request.Request(TOKEN_URL, data=form, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            tokens = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        http_error(exc)
    print("token response keys:", sorted(tokens))

    granted = tokens.get("scope") or tokens.get("scopes") or ""
    granted = granted.split() if isinstance(granted, str) else list(granted)
    print("granted scopes:", granted)

    # ponytail: spike skips JWKS signature check; the real provider must verify it
    claims = jwt_claims(tokens["id_token"])
    aud = claims.get("aud")
    checks = {
        "iss": claims.get("iss") == "https://auth.openai.com",
        "aud": client_id == aud or (isinstance(aud, list) and client_id in aud),
        "nonce": claims.get("nonce") == nonce,
        "exp": claims.get("exp", 0) > time.time(),
        "plan_scope": PLAN_SCOPE in granted,
    }
    if reauth:
        checks["same_sub"] = claims.get("sub") == jwt_claims(previous["id_token"]).get("sub")
    print("id_token checks:", checks)
    print("id_token claims:", json.dumps({k: v for k, v in claims.items() if k not in ("nonce", "at_hash")}, indent=2))

    fd = os.open(TOKENS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"client_id": client_id, "host_id": host_id(), "obtained_at": int(time.time()), **tokens}, f)
    print("saved", TOKENS_FILE)
    if not all(checks.values()):
        fail("some checks failed")
    print("LOGIN OK")


def api_get(path: str, token: str) -> dict:
    request = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        http_error(exc)


def test(model: str | None):
    if not TOKENS_FILE.exists():
        fail("run login first")
    saved = json.loads(TOKENS_FILE.read_text())
    token = saved["access_token"]

    data = api_get("/models", token)
    if "models" not in data:
        fail(f"unexpected /models shape, keys={sorted(data)}")
    listed = [m for m in data["models"] if m.get("visibility") == "list"]
    print(f"models: {len(data['models'])} total, {len(listed)} listed")
    for m in listed:
        print(f"  {m.get('slug')}  ({m.get('display_name')})")
    model = model or (listed[0]["slug"] if listed else None)
    if not model:
        fail("no listed model")

    body = {
        "model": model,
        "instructions": "Answer tersely.",
        "input": [{"role": "user", "content": "Say exactly: Hello, world!"}],
        "store": False,
        "stream": True,
    }
    request = urllib.request.Request(API + "/responses", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {token}",
                                              "Content-Type": "application/json",
                                              "Accept": "text/event-stream"})
    print(f"\nPOST /responses model={model}")
    completed = False
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            print("request_id:", response.headers.get("x-request-id"))
            print("output: ", end="", flush=True)
            for raw in response:
                line = raw.decode().rstrip("\r\n")
                if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                    continue
                event = json.loads(line[5:])
                kind = event.get("type")
                if kind == "response.output_text.delta":
                    print(event["delta"], end="", flush=True)
                elif kind == "response.completed":
                    completed = True
                    print("\nusage:", json.dumps(event["response"].get("usage")))
                elif kind in ("response.failed", "response.incomplete", "error"):
                    print("\n" + kind + ":", json.dumps(event)[:2000])
    except urllib.error.HTTPError as exc:
        http_error(exc)
    print("INFERENCE OK" if completed else "FAIL: no response.completed")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("login", "reauth", "test"):
        fail("usage: spike.py login | reauth | test [model-slug]")
    if sys.argv[1] == "test":
        test(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        login(reauth=sys.argv[1] == "reauth")
