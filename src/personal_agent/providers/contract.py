from dataclasses import dataclass


class ToolsUnsupportedError(RuntimeError):
    """A Provider's API rejected Tool support for the requested model (R09)."""


class ContextOverflowError(RuntimeError):
    pass


class OutputAllowanceError(ValueError):
    pass


def validate_output_allowance(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise OutputAllowanceError("output allowance must be a positive integer")


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    parameters: dict


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict | None
    arguments_raw: str | None = None
    # True only when a Provider invented this id locally because the vendor
    # response omitted one (e.g. older Gemini function calls, R08); such ids
    # are for our own correlation only and must never be sent back to the
    # vendor on the wire.
    id_is_generated: bool = False


@dataclass(frozen=True)
class ToolResult:
    id: str
    name: str
    content: object
    is_error: bool = False
    id_is_generated: bool = False
    # The object passed to the Tool, or None when the Tool boundary rejected
    # the call before invoking it (unknown name, invalid/malformed
    # arguments, wrong types, extra keys) - distinct from is_error, which is
    # also True for an execution-time failure (e.g. division by zero) where
    # arguments *were* passed to the Tool (Call Log tool_execution, R07).
    arguments: dict | None = None
    # The Dangerous Command rules matched against a `shell` call (spec 0023
    # R1/R5), empty for every other Tool and for an unflagged `shell` call.
    dangerous_rules: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssistantMessage:
    text: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    replay: object = None
    termination: str | None = None

    @property
    def truncated(self) -> bool:
        return self.termination in {"length", "max_tokens", "MAX_TOKENS", "model_context_window_exceeded"}
