import hashlib
import math
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal

from personal_agent import call_log, session_logs
from personal_agent.chatgpt_auth import account_label, valid_reference
from personal_agent.terminal.tty import sanitize_control_chars

MAX_SUMMARY_BYTES = 16 * 1024
MAX_EXECUTIONS = 20
MAX_ROUTES = 16
MAX_ACCESS = 8
_METRICS = ("latency_ms", "cost", "prompt_tokens", "completion_tokens", "cached_tokens", "cache_write_tokens")
_GROUPS = {"execution": "execution", "compression": "Compression", "unknown": "unknown purpose"}


def _number(value, tokens=False):
    return (type(value) is int and value >= 0 if tokens else
            type(value) in (int, float) and value >= 0 and (type(value) is int or math.isfinite(value)))


def _access(entry):
    method = entry.get("access_method")
    if method == "chatgpt_plan" or method is None and entry.get("provider") == "chatgpt":
        reference = entry.get("registration_ref")
        return "ChatGPT plan, " + (account_label(reference).removeprefix("ChatGPT ") if valid_reference(reference)
                                   else "unknown account")
    return "API key" if method in (None, "api_key") else "unknown access"


def _display(value):
    if type(value) is int:
        if value.bit_length() > 256:
            return "[subtotal exceeds rendering bound]"
        try:
            return str(value)
        except ValueError:
            return "[subtotal exceeds rendering bound]"
    return format(value, ".6g") if value else "0"


@dataclass
class _Metric:
    total: Decimal | int = 0
    known: int = 0
    missing: int = 0
    invalid: int = 0

    def add(self, value, tokens=False):
        if value is None:
            self.missing += 1
        elif not _number(value, tokens):
            self.invalid += 1
            return False
        else:
            self.known += 1
            self.total += value if tokens else Decimal(value) if type(value) is int else Decimal(str(value))
        return True

    def coverage(self, attempts):
        return f"{self.known}/{attempts} known, {self.missing} missing, {self.invalid} invalid"


@dataclass
class _Group:
    attempts: int = 0
    outcomes: dict = field(default_factory=lambda: dict.fromkeys(("ok", "error", "interrupted", "failed-or-interrupted", "unknown outcome"), 0))
    retries: dict = field(default_factory=lambda: dict.fromkeys(("initial", "transient", "context_overflow", "unknown"), 0))
    metrics: dict = field(default_factory=lambda: {name: _Metric() for name in _METRICS})
    costs: dict = field(default_factory=lambda: {name: _Metric() for name in ("reported", "estimated", "unknown provenance")})
    first: _Metric = field(default_factory=_Metric)
    text: dict = field(default_factory=lambda: dict.fromkeys(("textless/undelivered", "unmeasured", "unknown", "invalid"), 0))
    fraction_read: int = 0
    fraction_prompt: int = 0
    fraction_samples: int = 0
    plan: int = 0
    reasoning: _Metric = field(default_factory=_Metric)

    def add(self, entry):
        self.attempts += 1
        plan = _access(entry).startswith("ChatGPT plan")
        outcome = entry.get("outcome")
        if "outcome" not in entry:
            outcome = "ok" if entry.get("ok") is True else "failed-or-interrupted" if entry.get("ok") is False else None
        valid = ("ok", "error", "interrupted") if "outcome" in entry else ("ok", "failed-or-interrupted")
        self.outcomes[outcome if isinstance(outcome, str) and outcome in valid else "unknown outcome"] += 1
        retry = entry.get("retry_kind")
        self.retries[retry if isinstance(retry, str) and retry in self.retries else "unknown"] += 1
        invalid = []
        for name, metric in self.metrics.items():
            if name == "cost" and plan:
                if entry.get("cost") is not None:
                    metric.invalid += 1
                    invalid.append(name)
            elif not metric.add(entry.get(name), tokens=name.endswith("tokens")):
                invalid.append(name)
        if plan:
            self.plan += 1
            if not self.reasoning.add(entry.get("reasoning_tokens"), tokens=True):
                invalid.append("reasoning_tokens")
        prompt, read, write = (entry.get(key) for key in ("prompt_tokens", "cached_tokens", "cache_write_tokens"))
        if (_number(prompt, True) and prompt > 0 and _number(read, True) and read <= prompt
                and (write is None or _number(write, True) and read + write <= prompt)):
            self.fraction_read += read
            self.fraction_prompt += prompt
            self.fraction_samples += 1
        cost = entry.get("cost")
        if cost is not None and _number(cost) and not plan:
            provenance = "estimated" if entry.get("cost_estimated") is True else "reported" if entry.get("cost_estimated") is False else "unknown provenance"
            self.costs[provenance].add(cost)
        latency = entry.get("first_text_latency_ms")
        if latency is not None and not _number(latency):
            self.text["invalid"] += 1
            invalid.append("first_text_latency_ms")
        elif entry.get("streamed") is True:
            if latency is None:
                self.text["textless/undelivered"] += 1
            else:
                self.first.add(latency)
        elif entry.get("streamed") is False:
            self.text["unmeasured"] += 1
        else:
            self.text["unknown"] += 1
        return invalid

    def render(self, label):
        n = self.attempts
        duration = self.metrics["latency_ms"]
        mean = f"{_display(duration.total / duration.known)} ms" if duration.known else "unavailable"
        first = f"{_display(self.first.total / self.first.known)} ms" if self.first.known else "unavailable"
        outcomes = "; ".join(f"{name} {count}" for name, count in self.outcomes.items())
        r = self.retries
        tokens = "; ".join(f"{label} {_display(self.metrics[key].total) if self.metrics[key].known or not n else 'unavailable'} [{self.metrics[key].coverage(n)}]"
                           for label, key in (("prompt", "prompt_tokens"), ("completion", "completion_tokens"),
                                              ("cache-read", "cached_tokens"), ("cache-write", "cache_write_tokens")))
        cost = self.metrics["cost"]
        api = n - self.plan
        spend = ("API " if self.plan else "") + (f"${_display(cost.total)}" if cost.known or not api else "unavailable")
        costs = "; ".join(f"{name} ${_display(metric.total)} ({metric.known})" for name, metric in self.costs.items())
        recorded = ("no API Attempts" if self.plan and not api else
                    f"recorded {spend}; {costs}; known {cost.known}/{api}, missing {cost.missing}, invalid {cost.invalid}")
        return [f"{label}: Attempts {n}; {outcomes}",
                f"  technical retries {r['transient'] + r['context_overflow']} (transient {r['transient']}, context-overflow {r['context_overflow']}); initial {r['initial']}; unknown {r['unknown']}/{n}",
                f"  duration: sum {_display(duration.total)} ms; mean {mean}; known {duration.known}/{n}, missing {duration.missing}, invalid {duration.invalid}",
                f"  first text: mean {first}; known {self.first.known}/{n}; " + "; ".join(f"{key} {count}" for key, count in self.text.items()),
                f"  tokens: {tokens}",
                f"  cost: {recorded}{self.unpriced('unavailable')}",
                f"  {self.fraction()}"]

    def fraction(self):
        value = f"{100 * self.fraction_read / self.fraction_prompt:.6g}%" if self.fraction_prompt else "unavailable"
        return f"cache-read fraction {value} [{self.fraction_samples}/{self.attempts} compatible samples]"

    def compact(self):
        n = self.attempts
        metrics = "; ".join(f"{label} {_display(self.metrics[key].total) if self.metrics[key].known else '?'} "
                            f"[{self.metrics[key].coverage(n)}]" for label, key in
                            (("duration ms", "latency_ms"), ("prompt", "prompt_tokens"),
                             ("output", "completion_tokens"), ("cache-read", "cached_tokens"),
                             ("cache-write", "cache_write_tokens")))
        costs = "; ".join(f"{key} ${_display(metric.total)} ({metric.known})" for key, metric in self.costs.items())
        return (f"Attempts {n}; technical retries {self.retries['transient'] + self.retries['context_overflow']}; "
                f"retry kind unknown {self.retries['unknown']}; {metrics}; "
                f"first text mean {_display(self.first.total / self.first.known) if self.first.known else '?'} ms "
                f"[known {self.first.known}/{n}; " + "; ".join(f"{key} {value}" for key, value in self.text.items()) +
                f"]; {self.fraction()}; "
                + ("no API Attempts" if self.plan == n else f"cost {costs} [{self.metrics['cost'].coverage(n - self.plan)}]")
                + self.unpriced("?"))

    def unpriced(self, absent):
        if not self.plan:
            return ""
        reasoning = _display(self.reasoning.total) if self.reasoning.known else absent
        return (f"; ChatGPT plan Attempts {self.plan}: cost unavailable (not priced); "
                f"reasoning {reasoning} [{self.reasoning.coverage(self.plan)}]")


def _route(entry):
    result = []
    for key in ("provider", "model"):
        value = entry.get(key)
        if not isinstance(value, str) or not value:
            result.append(None)
        elif len(value) > 96:
            result.append(value[:96] + "[truncated " + hashlib.sha256(value.encode()).hexdigest() + "]")
        else:
            result.append(value)
    return tuple(result)


def _label(value):
    return sanitize_control_chars(value, multiline=False) if value else "unknown"


@dataclass
class _Execution:
    run: str
    line: int
    ordinal: int
    retried: bool
    outcome: str = "unresolved"
    routes: list = field(default_factory=list)
    omitted: int = 0

    def add(self, entry, purpose, changed):
        route = (*_route(entry), _access(entry))
        key = (purpose, route)
        if self.routes and self.routes[-1][0] == key and not self.omitted:
            self.routes[-1][1].add(entry)
        elif len(self.routes) < MAX_ROUTES:
            group = _Group()
            group.add(entry)
            self.routes.append((key, group, changed))
        else:
            self.omitted += 1

    def header(self):
        return (f"Run {self.run}; opening line {self.line}; ordinal {_display(self.ordinal)}; "
                f"{'Retry' if self.retried else 'submitted'}; outcome {self.outcome}")


def render(protected_api_keys: tuple[str, ...] = ()) -> str:
    sid = call_log.active_session_id()
    groups = {name: _Group() for name in _GROUPS}
    total = _Group()
    runs = retries = diagnostic_count = 0
    diagnostics = []
    partial = False
    run_id = None
    turn_open = False
    executions = deque(maxlen=MAX_EXECUTIONS)
    opened = unattributed = 0
    current = None
    previous_route = None
    initial = False
    delegated = _Metric()
    delegated_ids = set()
    delegated_plan = 0
    access = {}
    other_access = 0
    child_links = {}
    incomplete_children = set()
    filename = f"pa_log-{sid}.jsonl"

    def note(message, line=None, incomplete=False):
        nonlocal diagnostic_count, partial
        partial |= incomplete
        diagnostic_count += 1
        if len(diagnostics) < 8:
            diagnostics.append(f"{filename}{':' + str(line) if line else ''}: {message}")

    try:
        if sid is None:
            raise ValueError("no current Session")
        identity = call_log.storage_identity()
        for row in session_logs.records(identity["project_id"], sid):
            entry, line = row["entry"], row["line"]
            if line == 1:
                if row["warning"] or entry is None or entry.get("type") != "session_start" or entry.get("log_version") != call_log.LOG_VERSION:
                    raise ValueError("invalid initial Run metadata")
                call_log.validate_identity(entry, sid)
                initial = True
            if row["warning"] or entry is None:
                note(row["warning"] or "unusable record", line, incomplete=True)
                current, previous_route = None, None
                continue
            if any(key in entry and entry[key] != identity[key] for key in ("workspace_root", "project_id")):
                note("wrong project identity", line, incomplete=True)
                current, previous_route = None, None
                continue
            kind = entry.get("type")
            if kind in {"delegation_started", "delegation_receipt", "delegation_finished"}:
                child = entry.get("child_session_id")
                if not isinstance(child, str) or not call_log.SESSION_ID_PATTERN.fullmatch(child):
                    note("invalid delegated Session identity", line, incomplete=True)
                    continue
                if len(child_links) < 20 or child in child_links:
                    child_links[child] = _label(entry.get("agent_name"))
                if kind == "delegation_started":
                    incomplete_children.add(child)
                elif kind == "delegation_finished" and entry.get("coverage") == "complete":
                    incomplete_children.discard(child)
                elif kind == "delegation_receipt":
                    identifier = entry.get("attempt_id")
                    if not isinstance(identifier, str) or len(identifier) != 32:
                        note("invalid delegated Attempt identity", line, incomplete=True)
                        continue
                    key = child, identifier
                    if key not in delegated_ids:
                        delegated_ids.add(key)
                        if entry.get("access_method") == "chatgpt_plan":
                            delegated_plan += 1
                        elif entry.get("cost_status") == "invalid":
                            delegated.invalid += 1
                        else:
                            delegated.add(entry.get("cost"))
            elif kind in ("session_start", "session_resumed"):
                try:
                    call_log.validate_identity(entry, sid)
                except call_log.ResumeError:
                    note("invalid project or Run identity", line, incomplete=True)
                    current, run_id, previous_route = None, None, None
                    continue
                if run_id is not None:
                    note("prior Run unresolved: missing Run close", line)
                if turn_open:
                    note("submission unresolved: missing Turn End", line)
                runs += 1
                run_id, turn_open = entry["run_id"], False
                current = None
            elif kind == "session_end":
                if turn_open:
                    note("submission unresolved: missing Turn End", line)
                run_id, turn_open = None, False
                current = None
            elif kind in ("routed_task_submitted", "routed_task_retried"):
                if type(entry.get("ordinal")) is not int or entry["ordinal"] <= 0:
                    note("invalid submission/Retry ordinal", line, incomplete=True)
                    current = None
                    continue
                if turn_open:
                    note("submission unresolved: missing Turn End", line)
                turn_open = True
                retries += kind == "routed_task_retried"
                current = None
                if run_id is not None:
                    opened += 1
                    current = _Execution(run_id, line, entry["ordinal"], kind == "routed_task_retried")
                    executions.append(current)
            elif kind == "turn_end":
                if current is not None:
                    status = entry.get("status")
                    current.outcome = status if status in ("ok", "error", "interrupted") else "unknown recorded outcome"
                current = None
                turn_open = False
            elif kind == "attempt":
                purpose = entry.get("purpose")
                if "purpose" not in entry:
                    purpose = "compression" if entry.get("task") == call_log.COMPRESS_TASK else "execution"
                group = groups[purpose if isinstance(purpose, str) and purpose in groups else "unknown"]
                invalid = group.add(entry)
                total.add(entry)
                label = _access(entry)
                if label in access or len(access) < MAX_ACCESS:
                    access.setdefault(label, _Group()).add(entry)
                else:
                    other_access += 1
                purpose = purpose if isinstance(purpose, str) and purpose in groups else "unknown"
                safe = {**entry, **{key: call_log.redact_value(entry.get(key), protected_api_keys)
                                   for key in ("provider", "model")}}
                route = _route(safe)
                ordinary = route if purpose == "execution" and all(route) else None
                changed = ordinary is not None and previous_route is not None and ordinary != previous_route
                if ordinary is not None:
                    previous_route = ordinary
                if current is None:
                    unattributed += 1
                else:
                    current.add(safe, purpose, changed)
                if invalid:
                    note("invalid " + ", ".join(invalid), line)
        if not initial:
            raise ValueError("no usable initial Run metadata")
    except (OSError, ValueError, call_log.ResumeError) as exc:
        note(str(exc), 1 if not initial else None, incomplete=True)
    if turn_open:
        note("submission unresolved: missing Turn End")
    if run_id is not None and run_id != call_log.active_run_id():
        note("prior Run unresolved: missing Run close")
    lines = [f"Recorded Session report: {sid}; inspected Runs: {runs}",
             "PARTIAL INSPECTION: recorded subtotals have incomplete coverage." if partial else "Recorded subtotals; coverage describes inspected Attempts.",
             f"Explicit user Retry: {retries}", f"Unattributed Attempts: {unattributed}"]
    for name, group in groups.items():
        if group.attempts:
            lines.extend(group.render(_GROUPS[name]))
    lines.extend(total.render("Session subtotal"))
    if any(label.startswith("ChatGPT plan") for label in access):
        lines.append("By access method (API costs exclude ChatGPT plan use):")
        lines.extend(f"  {_label(label)}: {group.compact()}" for label, group in access.items())
        if other_access:
            lines.append(f"  other access identities omitted: {other_access} Attempts")
    if child_links or delegated_ids:
        delegated_api = len(delegated_ids) - delegated_plan
        cost = (f"${_display(delegated.total)}; coverage: {delegated.coverage(delegated_api)}" if delegated_api or not delegated_plan
                else "no API Attempts")
        lines.append(f"Delegated {'API ' if delegated_plan else ''}cost subtotal: {cost}; "
                     + (f"delegated ChatGPT plan Attempts {delegated_plan}: cost unavailable; " if delegated_plan else "")
                     + f"child evidence incomplete/unavailable: {len(incomplete_children)}")
        lines.extend(f"  Child Session {child}: {name}" for child, name in child_links.items())
    lines.append("Provider duration is dispatch-to-response, excluding Tool/human waiting and backoff; it does not separate network/generation time.")
    lines.extend(diagnostics)
    if diagnostic_count > len(diagnostics):
        lines.append(f"Diagnostics truncated: {diagnostic_count - len(diagnostics)} additional notices.")
    if executions:
        lines.append(f"Latest opened executions: {len(executions)}/{opened}; older executions omitted {opened - len(executions)}.")
        lines.append("Adjacent ordinary rows show recorded cache observations; route changes imply no cache loss, savings or causality.")
        reserved = sum(len(execution.header().encode()) + 100 for execution in executions)
        remaining = max(0, MAX_SUMMARY_BYTES - len("\n".join(lines).encode()) - reserved - 128)
        for index, execution in enumerate(executions):
            lines.append(execution.header())
            allowance = remaining // (len(executions) - index)
            omitted = 0
            for (purpose, route), group, changed in execution.routes:
                label = "/".join(_label(value) for value in route[:2]) + f" [{_label(route[2])}]"
                row = f"  {_GROUPS[purpose]} {label}" + (" [observed Provider/model change]" if changed else "") + ": " + group.compact()
                size = len(row.encode()) + 1
                if size <= allowance:
                    lines.append(row)
                    allowance -= size
                    remaining -= size
                else:
                    omitted += 1
            if omitted or execution.omitted:
                lines.append(f"  Details omitted: {omitted} retained route groups; {execution.omitted} Attempts beyond {MAX_ROUTES} route groups.")
    rendered = sanitize_control_chars(call_log.redact_value("\n".join(lines) + "\n", protected_api_keys), multiline=True)
    encoded = rendered.encode("utf-8")
    if len(encoded) > MAX_SUMMARY_BYTES:
        marker = b"\n[Report truncated; coverage/details incomplete]\n"
        return encoded[:MAX_SUMMARY_BYTES - len(marker)].decode("utf-8", errors="ignore") + marker.decode()
    return rendered
