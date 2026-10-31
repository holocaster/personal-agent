import email.message
import io
import json

from personal_agent import model_catalog


class Repeat:
    """Wraps an outcome so install_fake_urlopen returns/raises it for every
    remaining call once the scripted list runs out, instead of IndexError-ing."""

    def __init__(self, outcome):
        self.outcome = outcome


class FakeOpenRouterResponse:
    def __init__(self, payload: dict):
        self.payload = payload
        self._body = json.dumps(payload).encode("utf-8")
        self._offset = 0
        self.closed = False
        self._streaming = False

    def stream(self):
        self._streaming = True
        if "content" in self.payload:
            blocks = self.payload["content"]
            message = {"role": "assistant", "content": [], "stop_reason": None}
            if "usage" in self.payload:
                message["usage"] = self.payload["usage"]
            frames = [{"type": "message_start", "message": message}]
            for index, block in enumerate(blocks):
                frames.extend([{"type": "content_block_start", "index": index, "content_block": block},
                               {"type": "content_block_stop", "index": index}])
            finish = self.payload.get("stop_reason") or (
                "tool_use" if any(block["type"] == "tool_use" for block in blocks) else "end_turn")
            frames.extend([{"type": "message_delta", "delta": {"stop_reason": finish}}, {"type": "message_stop"}])
            self._body = "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames).encode()
            return self
        if "candidates" in self.payload:
            frame = {**self.payload, "candidates": [
                {"index": index, "finishReason": "STOP", **candidate}
                for index, candidate in enumerate(self.payload["candidates"])]}
            self._body = ("data: " + json.dumps(frame) + "\n\n").encode()
            return self
        choice = (self.payload.get("choices") or [{}])[0]
        frame = self.payload
        if "message" in choice and "error" not in choice:
            delta = dict(choice["message"])
            for index, tool in enumerate(delta.get("tool_calls") or []):
                tool["index"] = index
            finish = choice.get("finish_reason") or ("tool_calls" if delta.get("tool_calls") else "stop")
            frame = {**self.payload, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        self._body = ("data: " + json.dumps(frame) + "\n\ndata: [DONE]\n\n").encode()
        return self

    def read(self, size=None) -> bytes:
        if size is None:
            return self._body
        body = self._body[self._offset:self._offset + size]
        self._offset += len(body)
        return body

    def read1(self, size):
        if not self._streaming:
            self.stream()
        return self.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed = True
        return False


class FakeCatalogResponse:
    def __init__(self, body, *, status=200, content_type="application/json", url=model_catalog.URL, headers=None,
                 on_read=None):
        self.status = status
        self.url = url
        self.headers = email.message.Message()
        self.headers["Content-Type"] = content_type
        for name, value in (headers or {}).items():
            self.headers[name] = value
        self._body = io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode())
        self._on_read = on_read

    def geturl(self):
        return self.url

    def read(self, size=-1):
        if self._on_read:
            self._on_read()
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def synthetic_models_dev(model_ids, context=128000, output=16000) -> dict:
    model = lambda key: {"id": key, "name": key, "tool_call": True, "limit": {"context": context, "output": output},
                         "modalities": {"input": ["text"], "output": ["text"]}}
    return {upstream: {"id": upstream, "models": {key: model(key) for key in model_ids}}
            for upstream in model_catalog.UPSTREAM_IDS.values()}
