import ast
import math
from datetime import datetime, timezone

MAX_EXPRESSION_CHARS = 256
MAX_SYNTAX_NODES = 64
MAX_ABS_VALUE = 1e100

_clock = lambda: datetime.now(timezone.utc)  # noqa: E731 - swappable seam for deterministic tests


class ToolExecutionError(Exception):
    pass


def _check_finite(value) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolExecutionError("only numeric values are allowed")
    if not math.isfinite(value) or abs(value) > MAX_ABS_VALUE:
        raise ToolExecutionError("value out of bounds")


def _eval_node(node: ast.AST):
    if isinstance(node, ast.Constant):
        _check_finite(node.value)
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            result = left + right
        elif isinstance(node.op, ast.Sub):
            result = left - right
        elif isinstance(node.op, ast.Mult):
            result = left * right
        else:
            if right == 0:
                raise ToolExecutionError("division by zero")
            result = left / right
        _check_finite(result)
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        result = value if isinstance(node.op, ast.UAdd) else -value
        _check_finite(result)
        return result
    raise ToolExecutionError("unsupported expression: only numbers, + - * /, and parentheses are allowed")


def calculator(arguments: dict) -> dict:
    expression = arguments["expression"]
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise ToolExecutionError(f"expression exceeds {MAX_EXPRESSION_CHARS} characters")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolExecutionError(f"invalid expression syntax: {exc.msg}") from exc

    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > MAX_SYNTAX_NODES:
        raise ToolExecutionError(f"expression exceeds {MAX_SYNTAX_NODES} syntax-tree nodes")

    return {"result": _eval_node(tree.body)}


def current_time(arguments: dict) -> dict:
    return {"utc_time": _clock().isoformat()}
