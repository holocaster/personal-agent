import hashlib
import importlib.util
import json
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


_ASSETS = {
    "cl100k_base": ("9b5ad71b2ce5302211f9c61530b329a4922fc6a4", "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"),
    "o200k_base": ("fb374d419588a4632f3f557e76b4b70aebbca790", "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"),
}


@dataclass(frozen=True)
class TokenEstimate:
    tokens: int
    encoding: str
    generic: bool

    @property
    def label(self) -> str:
        return f"approximate {self.encoding}" + (" (generic fallback)" if self.generic else "")


def _valid_asset(directory: Path, encoding: str) -> bool:
    filename, expected_hash = _ASSETS[encoding]
    try:
        return hashlib.sha256((directory / filename).read_bytes()).hexdigest() == expected_hash
    except OSError:
        return False


@lru_cache(maxsize=1)
def local_library():
    spec = importlib.util.find_spec("litellm")
    if spec is None or spec.origin is None:
        raise ValueError("local LiteLLM is unavailable")
    bundled = Path(spec.origin).parent / "litellm_core_utils" / "tokenizers"
    custom = os.environ.get("CUSTOM_TIKTOKEN_CACHE_DIR")
    candidates = ([Path(custom)] if custom else []) + [bundled]
    directory = next((path for path in candidates if _valid_asset(path, "cl100k_base")), None)
    if directory is None:
        raise ValueError("no valid local tokenizer assets; downloads are disabled")
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["LITELLM_MODE"] = "PRODUCTION"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["CUSTOM_TIKTOKEN_CACHE_DIR"] = str(directory)
    os.environ["TIKTOKEN_CACHE_DIR"] = str(directory)
    import tiktoken

    tiktoken.get_encoding("cl100k_base")
    if _valid_asset(directory, "o200k_base"):
        tiktoken.get_encoding("o200k_base")
    import litellm

    litellm.disable_hf_tokenizer_download = True
    litellm.suppress_debug_info = True
    return litellm, directory


def render_input(prepared: dict) -> str:
    def validate(value):
        if value is None or type(value) in (str, int, bool):
            return
        if type(value) is float and math.isfinite(value):
            return
        if type(value) is list:
            for item in value:
                validate(item)
            return
        if type(value) is dict and all(type(key) is str for key in value):
            for item in value.values():
                validate(item)
            return
        raise ValueError("prepared input must contain strictly valid JSON values")

    validate(prepared)
    rendered = json.dumps(prepared, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    rendered.encode("utf-8", errors="strict")
    return rendered


def estimate(model: str, prepared: dict) -> TokenEstimate:
    rendered = render_input(prepared)
    litellm, directory = local_library()
    if litellm.disable_token_counter:
        raise ValueError("local token counting is disabled")
    litellm.disable_hf_tokenizer_download = True
    import tiktoken

    generic = model not in litellm.open_ai_chat_completion_models
    tokenizer_model = "gpt-3.5-turbo" if generic else model
    try:
        encoding = tiktoken.model.encoding_name_for_model(tokenizer_model)
    except KeyError:
        encoding = "cl100k_base"
        generic = True
    if encoding not in _ASSETS or not _valid_asset(directory, encoding):
        encoding, tokenizer_model, generic = "cl100k_base", "gpt-3.5-turbo", True
    if not _valid_asset(directory, encoding):
        raise ValueError("no valid local tokenizer assets; downloads are disabled")
    count = litellm.token_counter(model=tokenizer_model, text=rendered)
    if type(count) is not int or count <= 0:
        raise ValueError("local tokenizer returned an invalid or non-positive count")
    return TokenEstimate(count, encoding, generic)
