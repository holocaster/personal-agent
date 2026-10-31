import os
import re
import shlex
from pathlib import Path

_PUNCTUATION_CHARS = ";&|()\n"
_SHELL_TOKENS = re.compile(
    r'''\#[^\n]*|(?:[^\s;&|()'"\\]|\\[\s\S]|'[^']*'|"(?:\\[\s\S]|[^"\\])*")+|[;&|()\n]+'''
)
_PREFIX_WORDS = frozenset({"then", "do", "else", "elif", "{", "!", "time", "sudo"})
_PROTECTED_LITERALS = frozenset({"/", "~", "$HOME", "${HOME}", "*", ".."})
_CHOWN_CHMOD_LITERALS = frozenset({"/", "/*", "~", "~/", "$HOME", "${HOME}"})
_HOME_PREFIXES = ("${HOME}", "$HOME", "~")
_REDIRECT_OPERATOR = re.compile(r"^\d*(?:>>|>|<|&>|>&|<&)(?:&\d+)?$")
_REDIRECT_PREFIX = re.compile(r"^\d*(?:>>|>|<|&>)")
_BLOCK_DEVICE_REDIRECT = re.compile(
    r"\d*\s*(?:>>?|>&|&>)\s*/dev/(?:sd|hd|vd|xvd|nvme|mmcblk|dm-|md)\w*"
)
_FORK_BOMB = re.compile(r"([^\s(){}|;&]+)\s*\(\s*\)\s*\{\s*\1\s*\|\s*\1\s*&\s*\}\s*;\s*\1")
_PIPE_INTO_INTERPRETER = re.compile(
    r"(?:(?<!\|)\|(?!\|)|\|&)\s*(?:(?:sudo|env)\s+)?(?:\S*/)?"
    r"(?:sh|bash|zsh|python3?(?:\.\d+)?|perl|node)(?![\w.-])"
)
_SHELL_C_SUBSTITUTION = re.compile(r"\b(?:bash|sh)\s+-c\s+[\"']?\$\(")
_PROCESS_SUBSTITUTION_SOURCE = re.compile(r"(?:^|[\s;&|()])(?:source|\.)\s+<\(")


def _strip_quotes(word: str) -> str:
    if len(word) >= 2 and word[0] == word[-1] and word[0] in ("'", '"'):
        return word[1:-1]
    return word


def _segments(command: str) -> list[list[str]]:
    try:
        uncommented = _SHELL_TOKENS.sub(
            lambda match: "" if match[0].startswith("#") else match[0], command
        )
        shlex.split(uncommented, comments=False)
        tokens = [token for token in _SHELL_TOKENS.findall(command) if not token.startswith("#")]
        tokenizable = True
    except ValueError:
        tokens = command.replace("\n", " ; ").split()
        tokenizable = False

    joined: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "&" and joined and re.fullmatch(r"\d*[<>]", joined[-1]):
            joined[-1] += "&"
            if index + 1 < len(tokens) and tokens[index + 1].isdigit():
                index += 1
                joined[-1] += tokens[index]
        elif token == "&" and index + 1 < len(tokens) and tokens[index + 1].startswith(">"):
            index += 1
            joined.append("&" + tokens[index])
        else:
            joined.append(token)
        index += 1

    segments: list[list[str]] = [[]]
    for token in joined:
        if token and all(ch in _PUNCTUATION_CHARS for ch in token):
            segments.append([])
        else:
            segments[-1].append(shlex.split(token)[0] if tokenizable else token)
    return [segment for segment in segments if segment]


def _leading_prefix_words(segment: list[str]) -> list[str]:
    """The run of words at the start of `segment` that are each one of the
    shell keywords/prefixes `then`, `do`, `else`, `elif`, `{`, `!`, `time` or
    `sudo` (R1); a prefix word anywhere else in the segment is an ordinary
    argument."""
    index = 0
    while index < len(segment) and segment[index] in _PREFIX_WORDS:
        index += 1
    return segment[:index]


def _command_word(segment: list[str]) -> tuple[str | None, list[str]]:
    """Returns (command_word, remaining_words) - remaining_words is the
    segment with its leading prefix words and the command word itself
    removed, so callers can scan for flags/arguments without re-skipping
    either."""
    prefix = _leading_prefix_words(segment)
    words = segment[len(prefix) :]
    if not words:
        return None, []
    return words[0], words[1:]


def _strip_redirections(rest: list[str]) -> list[str]:
    """Drops redirection operators and their operands from `rest` (R1):
    a standalone operator word consumes the word right after it too, and a
    word with an operand attached to the operator (`>/dev/null`) is dropped
    on its own. Neither counts as an rm or chmod/chown target."""
    result: list[str] = []
    skip_next = False
    for word in rest:
        if skip_next:
            skip_next = False
            continue
        if _REDIRECT_OPERATOR.match(word):
            skip_next = re.search(r"&\d+$", word) is None
            continue
        if _REDIRECT_PREFIX.match(word):
            continue
        result.append(word)
    return result


def _strip_trailing_slash(target: str) -> str:
    stripped = target.rstrip("/")
    return stripped if stripped else "/"


def _expand_home(target: str) -> str:
    for prefix in _HOME_PREFIXES:
        if target == prefix:
            return str(Path.home())
        if target.startswith(prefix + "/"):
            return str(Path.home() / target[len(prefix) + 1 :])
    return target


def _normalizes_outside_workspace(target: str, workspace_root: Path) -> bool:
    expanded = _expand_home(target)
    path = Path(expanded)
    if not path.is_absolute():
        path = workspace_root / path
    normalized = Path(os.path.normpath(str(path)))
    if normalized == workspace_root:
        return False
    try:
        normalized.relative_to(workspace_root)
        return False
    except ValueError:
        return True


def _is_protected_rm_target(raw_target: str, workspace_root: Path) -> bool:
    target = _strip_trailing_slash(_strip_quotes(raw_target))
    if target in _PROTECTED_LITERALS:
        return True
    return _normalizes_outside_workspace(target, workspace_root)


def _is_recursive_rm_flag(word: str) -> bool:
    if word == "--recursive":
        return True
    if word.startswith("-") and not word.startswith("--") and len(word) > 1:
        return "r" in word or "R" in word
    return False


def _check_recursive_rm(segments: list[list[str]], workspace_root: Path) -> bool:
    for segment in segments:
        command_word, rest = _command_word(segment)
        if command_word != "rm":
            continue
        rest = _strip_redirections(rest)
        if not any(_is_recursive_rm_flag(word) for word in rest):
            continue
        targets = [word for word in rest if not word.startswith("-")]
        if any(_is_protected_rm_target(target, workspace_root) for target in targets):
            return True
    return False


def _check_sudo(segments: list[list[str]]) -> bool:
    return any("sudo" in _leading_prefix_words(segment) for segment in segments)


def _has_short_flag_letter(rest: list[str], letter: str) -> bool:
    return any(word.startswith("-") and not word.startswith("--") and letter in word for word in rest)


def _check_git_reset_hard(segments: list[list[str]]) -> bool:
    for segment in segments:
        command_word, rest = _command_word(segment)
        if command_word == "git" and "reset" in rest and "--hard" in rest:
            return True
    return False


def _check_git_clean_force(segments: list[list[str]]) -> bool:
    for segment in segments:
        command_word, rest = _command_word(segment)
        if command_word != "git" or "clean" not in rest:
            continue
        if "--force" in rest or _has_short_flag_letter(rest, "f"):
            return True
    return False


def _check_git_push_force(segments: list[list[str]]) -> bool:
    for segment in segments:
        command_word, rest = _command_word(segment)
        if command_word != "git" or "push" not in rest:
            continue
        if "--force" in rest or _has_short_flag_letter(rest, "f"):
            return True
    return False


def _check_git_checkout_dash_dash_dot(segments: list[list[str]]) -> bool:
    for segment in segments:
        command_word, rest = _command_word(segment)
        if command_word != "git" or "checkout" not in rest:
            continue
        for index, word in enumerate(rest):
            if word == "--" and index + 1 < len(rest) and rest[index + 1] == ".":
                return True
    return False


def _check_mkfs(segments: list[list[str]]) -> bool:
    for segment in segments:
        command_word, _rest = _command_word(segment)
        if command_word is not None and (command_word == "mkfs" or command_word.startswith("mkfs.")):
            return True
    return False


def _check_dd_of(segments: list[list[str]]) -> bool:
    for segment in segments:
        command_word, rest = _command_word(segment)
        if command_word != "dd":
            continue
        if any(word.startswith("of=") for word in rest):
            return True
    return False


def _check_recursive_chmod_chown(segments: list[list[str]]) -> bool:
    for segment in segments:
        command_word, rest = _command_word(segment)
        if command_word not in ("chmod", "chown"):
            continue
        rest = _strip_redirections(rest)
        has_recursive = any(
            word == "--recursive"
            or (word.startswith("-") and not word.startswith("--") and "R" in word)
            for word in rest
        )
        if not has_recursive:
            continue
        targets = [_strip_quotes(word) for word in rest if not word.startswith("-")]
        if any(target in _CHOWN_CHMOD_LITERALS for target in targets):
            return True
    return False


def _check_eval(segments: list[list[str]]) -> bool:
    for segment in segments:
        command_word, _rest = _command_word(segment)
        if command_word == "eval":
            return True
    return False


_RULES: tuple[tuple[str, object], ...] = (
    ("sudo", lambda command, segments, workspace_root: _check_sudo(segments)),
    (
        "recursive rm on a protected path",
        lambda command, segments, workspace_root: _check_recursive_rm(segments, workspace_root),
    ),
    ("git reset --hard", lambda command, segments, workspace_root: _check_git_reset_hard(segments)),
    ("git clean -f", lambda command, segments, workspace_root: _check_git_clean_force(segments)),
    ("git push --force", lambda command, segments, workspace_root: _check_git_push_force(segments)),
    ("git checkout -- .", lambda command, segments, workspace_root: _check_git_checkout_dash_dash_dot(segments)),
    ("mkfs", lambda command, segments, workspace_root: _check_mkfs(segments)),
    ("dd of=", lambda command, segments, workspace_root: _check_dd_of(segments)),
    (
        "redirect to a block device",
        lambda command, segments, workspace_root: bool(_BLOCK_DEVICE_REDIRECT.search(command)),
    ),
    (
        "recursive chmod/chown on / or ~",
        lambda command, segments, workspace_root: _check_recursive_chmod_chown(segments),
    ),
    ("fork bomb", lambda command, segments, workspace_root: bool(_FORK_BOMB.search(command))),
    (
        "pipe into a shell or interpreter",
        lambda command, segments, workspace_root: bool(_PIPE_INTO_INTERPRETER.search(command)),
    ),
    ("eval", lambda command, segments, workspace_root: _check_eval(segments)),
    (
        "shell -c with command substitution",
        lambda command, segments, workspace_root: bool(_SHELL_C_SUBSTITUTION.search(command)),
    ),
    (
        "source of process substitution",
        lambda command, segments, workspace_root: bool(_PROCESS_SUBSTITUTION_SOURCE.search(command)),
    ),
)


def matched_rules(command: str, workspace_root: Path) -> tuple[str, ...]:
    """R1: the fixed, ordered Dangerous Command rules, matched against the
    raw command string and its shell-like segments (`;`, `&&`, `||`, `|`,
    `&`, `(`, `)`, newline separated, quote-aware with a whitespace-splitting
    fallback for unbalanced quoting). Pure and side-effect free: no shell is
    invoked, no path touches disk. Returns matched rule names in rule order,
    each at most once."""
    segments = _segments(command)
    return tuple(name for name, check in _RULES if check(command, segments, workspace_root))
