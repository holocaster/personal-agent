import pickle

from personal_agent.tools.builtins import ToolExecutionError

MAX_MESSAGE_BYTES = 16 * 1024 * 1024


def send(channel, message):
    encoded = pickle.dumps(message)
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ToolExecutionError("Subagent IPC message exceeds its bound")
    channel.send_bytes(encoded)


def receive(channel):
    encoded = channel.recv_bytes(MAX_MESSAGE_BYTES)
    try:
        return pickle.loads(encoded)
    except (pickle.UnpicklingError, ValueError, TypeError, AttributeError, ImportError, EOFError):
        raise ToolExecutionError("malformed Subagent IPC payload") from None
