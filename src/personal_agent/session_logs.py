import base64
import hmac
import json
import os
import re
import secrets
import stat
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from personal_agent import call_log
from personal_agent.call_log import COMPRESS_TASK

MAX_ENTRIES = 4096
MAX_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 8192
MAX_RECORD_BYTES = 256 * 1024
_FILE_PATTERN = re.compile(r'pa_log-(\d{8}T\d{6}Z-[a-z0-9]{6})\.jsonl\Z')
_CURSOR_KEY = secrets.token_bytes(32)
_SELECTORS = ('last', 'previous')


def candidates(project: str | None) -> list[dict]:
    rows = []
    inspected = 0
    try:
        with call_log.storage_directory() as root:
            projects = []
            with os.scandir(root) as entries:
                for entry in entries:
                    inspected += 1
                    if inspected > MAX_ENTRIES:
                        raise ValueError('Session catalog entry budget exhausted')
                    if project is None and re.fullmatch(r'[A-Za-z0-9._-]+--[0-9a-f]{12}', entry.name):
                        if entry.is_dir(follow_symlinks=False):
                            projects.append(entry.name)
                        else:
                            rows.append({'project_id': entry.name, 'session_id': None,
                                         'warning': 'unsafe project directory'})
            if project is not None:
                projects = [project]
            for selected in sorted(projects):
                try:
                    with call_log.storage_directory(selected) as directory:
                        with os.scandir(directory) as entries:
                            for entry in entries:
                                inspected += 1
                                if inspected > MAX_ENTRIES:
                                    raise ValueError('Session catalog entry budget exhausted')
                                match = _FILE_PATTERN.fullmatch(entry.name)
                                if match:
                                    info = entry.stat(follow_symlinks=False)
                                    rows.append({'project_id': selected, 'session_id': match[1],
                                                 'identity': [info.st_dev, info.st_ino],
                                                 'warning': None if stat.S_ISREG(info.st_mode) else 'unsafe Session file'})
                except FileNotFoundError:
                    if project is None:
                        raise ValueError('Session catalog changed; restart discovery')
    except FileNotFoundError:
        return []
    rows.sort(key=lambda row: row['session_id'] or '', reverse=True)
    rows.sort(key=lambda row: row['project_id'])
    return rows


def _exhausted(budget):
    return budget['bytes'] >= MAX_BYTES or budget['records'] >= MAX_RECORDS


def _record_start(position=0, line=1):
    return {'position': position, 'line': line, 'discarding': False}


def _record(file, session_id, budget, state):
    if _exhausted(budget):
        return None
    start = state['position']
    file.seek(start)
    if start >= os.fstat(file.fileno()).st_size:
        return None
    budget['records'] += 1
    line = state['line']
    if state['discarding']:
        while budget['bytes'] < MAX_BYTES:
            chunk = file.readline(min(65536, MAX_BYTES - budget['bytes']))
            budget['bytes'] += len(chunk)
            state['position'] = file.tell()
            if not chunk or chunk.endswith(b'\n'):
                state['discarding'] = False
                state['line'] += 1
                break
        return {'line': line, 'entry': None, 'warning': None, 'skipped': True}
    remaining = MAX_BYTES - budget['bytes']
    fragment = file.readline(min(MAX_RECORD_BYTES + 1, remaining))
    budget['bytes'] += len(fragment)
    state['position'] = file.tell()
    oversized = len(fragment) > MAX_RECORD_BYTES
    if not fragment.endswith(b'\n') and file.tell() < os.fstat(file.fileno()).st_size:
        if not oversized and remaining < MAX_RECORD_BYTES + 1:
            state['position'] = start
            return None
        oversized = True
        state['discarding'] = True
    else:
        state['line'] += 1
    parsed = None
    warning = None
    if oversized:
        warning = 'oversized record; inspection incomplete'
    elif not fragment.endswith(b'\n'):
        warning = 'incomplete record'
    else:
        try:
            parsed = json.loads(fragment.decode('utf-8'))
            if not isinstance(parsed, dict):
                warning = 'non-object record'
            elif parsed.get('session_id') != session_id:
                warning = 'wrong Session identity'
        except (ValueError, UnicodeError, RecursionError):
            warning = 'invalid JSON or UTF-8 record'
    return {'line': line, 'entry': parsed if isinstance(parsed, dict) else None,
            'warning': warning, 'skipped': False}


def _initial(entry):
    return (entry is not None and entry.get('type') == 'session_start'
            and type(entry.get('log_version')) is int and entry['log_version'] > 0)


def records(project: str, session_id: str, budget: dict | None = None):
    if budget is None:
        budget = {'bytes': 0, 'records': 0}
    state = _record_start()
    with call_log.open_session_file(session_id, project=project) as file:
        while state['position'] < os.fstat(file.fileno()).st_size:
            row = _record(file, session_id, budget, state)
            if row is None:
                raise ValueError('Session selection scan budget exhausted')
            if not row['skipped']:
                yield row


def latest_run(project: str, session_id: str, budget: dict | None = None) -> dict:
    latest = None
    initial = None
    for row in records(project, session_id, budget):
        entry = row['entry']
        if row['line'] == 1:
            if row['warning'] or not _initial(entry):
                raise ValueError(f'{session_id}: invalid initial Run metadata')
            initial = entry
        if entry is None or entry.get('type') not in ('session_start', 'session_resumed'):
            continue
        call_log.validate_identity(entry, session_id, project)
        latest = entry
    if initial is None or latest is None:
        raise ValueError(f'{session_id}: no usable Run metadata')
    try:
        timestamp = datetime.fromisoformat(latest['timestamp'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            raise ValueError('missing UTC offset')
        timestamp = timestamp.astimezone(timezone.utc)
    except (KeyError, AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f'{session_id}: unknown latest Run timestamp') from exc
    return {'initial': initial, 'latest': latest, 'recency': timestamp}


def last_session(project: str) -> str:
    budget = {'bytes': 0, 'records': 0}
    latest = None
    for candidate in candidates(project):
        sid = candidate['session_id']
        if candidate['warning']:
            raise ValueError(f"{sid}: {candidate['warning']}")
        run = latest_run(project, sid, budget)
        if run['initial'].get('session_kind') == 'subagent':
            continue
        key = (run['recency'], sid)
        if latest is None or key > latest:
            latest = key
    if latest is None:
        raise ValueError('no sessions to resume')
    return latest[1]


PARAMETERS = {
    'type': 'object',
    'properties': {
        'action': {'type': 'string', 'enum': ['list', 'read', 'search']},
        'project': {'type': 'string', 'minLength': 1, 'maxLength': 4096},
        'session': {'type': 'string'},
        'source': {'type': 'string', 'enum': ['call_log', 'audit'], 'default': 'call_log'},
        'query': {'type': 'string', 'minLength': 1, 'maxLength': 500},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
        'cursor': {'type': 'string', 'minLength': 1, 'maxLength': 8192},
    },
    'required': ['action'], 'additionalProperties': False,
}


def _arguments(arguments):
    action = arguments['action']
    source = arguments.get('source', 'call_log')
    session = arguments.get('session')
    if action == 'list' and (session is not None or source != 'call_log'):
        raise ValueError('list forbids session and audit source')
    if action == 'read' and session is None:
        raise ValueError('read requires session')
    if (action == 'search') != ('query' in arguments) or (action == 'search' and not arguments['query'].strip()):
        raise ValueError('only search requires a nonblank query')
    if session is not None and session not in _SELECTORS and not call_log.SESSION_ID_PATTERN.fullmatch(session):
        raise ValueError('invalid Session Id')
    project = arguments.get('project', call_log.storage_identity()['workspace_root'])
    if project != 'all' and (not project.startswith('/') or project.startswith('//')
                             or any(part in ('.', '..') for part in project.split('/'))
                             or str(Path(project)) != project):
        raise ValueError('project must be an absolute normalized original directory')
    return action, project, session, source


def _header(candidate, budget):
    with call_log.open_session_file(candidate['session_id'], project=candidate['project_id']) as file:
        info = os.fstat(file.fileno())
        if [info.st_dev, info.st_ino] != candidate['identity']:
            raise ValueError('source replaced after catalog inspection; restart discovery')
        row = _record(file, candidate['session_id'], budget, _record_start())
        if row is None and info.st_size:
            raise ValueError('Session selection scan budget exhausted')
    if row is None or row['warning'] or not _initial(row['entry']):
        return 'unknown', 'invalid initial Run metadata', None, info.st_size
    try:
        call_log.validate_identity(row['entry'], candidate['session_id'], candidate['project_id'])
    except (call_log.ResumeError, UnicodeError):
        return 'unknown', 'invalid project or Run identity', row['entry'], info.st_size
    return row['entry']['workspace_root'], None, row['entry'], info.st_size


def _reference(candidate, project, line, entry=None, source='call_log'):
    stamp = (entry or {}).get('timestamp')
    try:
        parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
    except (ValueError, AttributeError, TypeError):
        stamp = 'unknown'
    sid = candidate['session_id'] or 'unknown'
    suffix = '.audit.jsonl' if source == 'audit' else '.jsonl'
    return f"project={project} project_id={candidate['project_id']} session={sid} pa_log-{sid}{suffix}:{line} timestamp={stamp}"


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _encode(state):
    state = {**state, 'signature': hmac.digest(_CURSOR_KEY, _digest(state).encode(), 'sha256').hex()}
    encoded = base64.urlsafe_b64encode(json.dumps(state, separators=(',', ':')).encode()).decode()
    if len(encoded) > 8192:
        raise ValueError('continuation metadata exceeded its bound; restart with a narrower selection')
    return encoded


def _decode(cursor, binding, catalog_hash, length):
    try:
        state = json.loads(base64.b64decode(cursor, altchars=b'-_', validate=True))
        if not isinstance(state, dict) or not isinstance(state.get('signature'), str):
            raise ValueError()
        signature = state.pop('signature')
        if not hmac.compare_digest(signature, hmac.digest(_CURSOR_KEY, _digest(state).encode(), 'sha256').hex()):
            raise ValueError()
        expected = {'version', 'binding', 'catalog', 'filter', 'index', 'position', 'line', 'discarding',
                    'file_identity', 'run', 'turn', 'phase', 'coverage', 'ordinary'}
        if (not isinstance(state, dict) or set(state) != expected or state['version'] != 1
                or state['binding'] != binding or state['catalog'] != catalog_hash):
            raise ValueError()
        if state['ordinary'] is not None and (type(state['ordinary']) is not int or state['ordinary'] < 0):
            raise ValueError()
        for key in ('index', 'position', 'line'):
            if type(state[key]) is not int or state[key] < (1 if key == 'line' else 0):
                raise ValueError()
        if state['index'] >= length or state['line'] > state['position'] + 1:
            raise ValueError()
        if any(type(state[key]) is not bool for key in ('discarding', 'run', 'turn')):
            raise ValueError()
        if state['phase'] not in ('coverage', 'data'):
            raise ValueError()
        identity = state['file_identity']
        if identity is not None and (not isinstance(identity, list) or len(identity) != 3
                                     or any(type(n) is not int or n < 0 for n in identity)):
            raise ValueError()
        if state['filter'] is not None and (type(state['filter']) is not int or not 0 <= state['filter'] < length):
            raise ValueError()
        coverage = state['coverage']
        if not isinstance(coverage, dict) or set(coverage) - {'enabled', 'disabled', 'open', 'malformed', 'run', 'run_open', 'boundary', 'proof'}:
            raise ValueError()
        if any(type(value) is not bool for key, value in coverage.items() if key not in ('run', 'boundary', 'proof')):
            raise ValueError()
        if 'run' in coverage and (not isinstance(coverage['run'], str) or not re.fullmatch(r'[0-9a-f]{64}', coverage['run'])):
            raise ValueError()
        proof = coverage.get('proof', [])
        if not isinstance(proof, list) or len(proof) not in (0, 2) or any(point is None for point in proof):
            raise ValueError()
        for point in [coverage.get('boundary'), *proof]:
            if point is not None and (not isinstance(point, list) or len(point) != 2
                                      or any(type(n) is not int for n in point)
                                      or point[0] < 0 or not 1 <= point[1] <= point[0] + 1):
                raise ValueError()
        return state
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('invalid or stale cursor/binding; restart discovery') from None


def _missing(state):
    closes = (['missing Run close'] if state['run'] else []) + (['missing Turn close'] if state['turn'] else [])
    return ', '.join(closes)


def _timeline(entry, state):
    kind = entry.get('type', 'unknown')
    rendered = {key: value for key, value in entry.items() if key not in ('session_id', 'timestamp')}
    if kind in ('session_start', 'session_resumed'):
        missing = _missing(state)
        prefix = f'prior activity unresolved: {missing}; ' if missing else ''
        state['run'] = True
        state['turn'] = False
        return prefix + str(kind) + ' ' + json.dumps(rendered, ensure_ascii=False)
    elif kind == 'session_end':
        prefix = 'prior activity unresolved: missing Turn close; ' if state['turn'] else ''
        state['run'] = state['turn'] = False
        return prefix + str(kind) + ' ' + json.dumps(rendered, ensure_ascii=False)
    elif kind in ('routed_task_submitted', 'routed_task_retried'):
        prefix = 'prior activity unresolved: missing Turn close; ' if state['turn'] else ''
        state['turn'] = True
        label = 'submitted user request ' if kind == 'routed_task_submitted' else 'retried user request '
        return prefix + label + json.dumps(rendered, ensure_ascii=False)
    elif kind == 'attempt':
        maintenance = (entry.get('purpose') == 'compression'
                       or ('purpose' not in entry and entry.get('task') == COMPRESS_TASK))
        if state['turn']:
            rendered.pop('task', None)
        if entry.get('task') == COMPRESS_TASK and isinstance(entry.get('answer'), str):
            rendered['answer'] = f"[Compression answer omitted: {len(entry['answer'])} chars; search matches it]"
        label = 'maintenance Attempt' if maintenance else 'assistant Attempt'
        if entry.get('tool_calls'):
            label += '; unresolved Tool intent only, actual execution requires tool_execution evidence'
        return label + ' ' + json.dumps(rendered, ensure_ascii=False)
    elif kind == 'tool_execution':
        return 'actual Tool execution ' + json.dumps(rendered, ensure_ascii=False)
    elif kind == 'turn_end':
        rendered.pop('messages', None)
        rendered.pop('continuation', None)
        rendered.pop('replay', None)
        status = entry.get('status')
        state['turn'] = False
        return ('Turn End; unresolved recorded outcome' if status != 'ok' else 'Turn End outcome') + ' ' + json.dumps(rendered, ensure_ascii=False)
    elif kind == 'conversation_forked':
        turns = rendered.pop('turns', None)
        rendered.pop('summary', None)
        rendered.pop('todo_baseline', None)
        rendered.pop('replays', None)
        rendered['copied_turns'] = len(turns) if isinstance(turns, list) else None
        return str(kind) + ' ' + json.dumps(rendered, ensure_ascii=False)
    return str(kind) + ' ' + json.dumps(rendered, ensure_ascii=False)


def _without_replay(entry):
    if not isinstance(entry, dict):
        return entry
    entry = {key: value for key, value in entry.items() if key not in ('replay', 'replays')}
    if isinstance(entry.get('continuation'), dict):
        entry['continuation'] = {key: value for key, value in entry['continuation'].items() if key != 'replay'}
    return entry


def _source(file, state, expected_identity=None):
    info = os.fstat(file.fileno())
    identity = [info.st_dev, info.st_ino, info.st_size]
    if expected_identity is not None and identity[:2] != expected_identity:
        raise ValueError('source replaced after catalog inspection; restart discovery')
    previous = state['file_identity']
    if previous is not None and (identity[:2] != previous[:2] or identity[2] < previous[2]):
        raise ValueError('source replaced or truncated; restart discovery')
    if state['position'] > info.st_size:
        raise ValueError('source position unavailable; restart discovery')
    state['file_identity'] = identity
    return info.st_size


def _audit_proof(candidate, coverage, budget):
    proof = coverage.get('proof')
    if not isinstance(proof, list) or len(proof) != 2:
        raise ValueError('audit coverage proof unavailable; restart discovery')
    entries = []
    with call_log.open_session_file(candidate['session_id'], project=candidate['project_id']) as file:
        info = os.fstat(file.fileno())
        if [info.st_dev, info.st_ino] != candidate['identity']:
            raise ValueError('audit coverage source replaced; restart discovery')
        for position, line in proof:
            if position >= info.st_size:
                raise ValueError('audit coverage proof position unavailable; restart discovery')
            if _exhausted(budget):
                return False
            if position:
                file.seek(position - 1)
                preceding = file.read(1)
                budget['bytes'] += len(preceding)
                if preceding != b'\n':
                    raise ValueError('invalid audit coverage record position; restart discovery')
            row = _record(file, candidate['session_id'], budget, _record_start(position, line))
            if row is None:
                return False
            if row['warning'] or row['entry'] is None:
                raise ValueError('audit coverage proof unverifiable; restart discovery')
            entries.append(row['entry'])
    boundary, enabled = entries
    call_log.validate_identity(boundary, candidate['session_id'], candidate['project_id'])
    if (boundary.get('type') not in ('session_start', 'session_resumed')
            or enabled.get('type') != 'audit_coverage_start' or enabled.get('enabled') is not True
            or enabled.get('run_id') != boundary.get('run_id')):
        raise ValueError('audit coverage proof unverifiable; restart discovery')
    return True


def _new_state(binding, catalog_hash, selected, source):
    return {'version': 1, 'binding': binding, 'catalog': catalog_hash, 'filter': selected, 'index': 0,
            **_record_start(), 'file_identity': None, 'run': False, 'turn': False,
            'phase': 'coverage' if source == 'audit' else 'data', 'coverage': {}, 'ordinary': None}


def _advance(state, source, length):
    following = length if state['filter'] is not None and state['index'] == state['filter'] else state['index'] + 1
    state.update(_new_state(state['binding'], state['catalog'], state['filter'], source), index=following)


def _previous(catalog, budget):
    latest = None
    for candidate in catalog:
        if _is_current(candidate):
            continue
        if candidate['warning']:
            raise ValueError('cannot select previous: unsafe candidate; specify an explicit Session')
        run = latest_run(candidate['project_id'], candidate['session_id'], budget)
        if run['initial'].get('session_kind') == 'subagent':
            continue
        key = (run['recency'], candidate['session_id'])
        if latest is None or key > latest[0]:
            latest = (key, candidate)
    return None if latest is None else catalog.index(latest[1])


def _explicit(catalog, session):
    matches = [row for row in catalog if row['session_id'] == session]
    if len(matches) > 1:
        raise ValueError('Session Id is ambiguous; specify the original project directory')
    if not matches:
        raise ValueError('selected Session not found')
    return catalog.index(matches[0])


def _resume(cursor, binding, catalog, session, source):
    state = _decode(cursor, binding, _digest(catalog), len(catalog))
    if source == 'call_log' and (state['phase'] != 'data' or state['coverage']):
        raise ValueError('invalid cursor source phase; restart discovery')
    if (session is None) != (state['filter'] is None):
        raise ValueError('invalid cursor selection; restart discovery')
    if state['filter'] is not None:
        if not 0 <= state['filter'] < len(catalog):
            raise ValueError('stale cursor selection; restart discovery')
        if session not in _SELECTORS and catalog[state['filter']]['session_id'] != session:
            raise ValueError('invalid cursor selection; restart discovery')
    return state


def _is_current(candidate):
    return (candidate['session_id'] == call_log.active_session_id()
            and candidate['project_id'] == call_log.storage_identity()['project_id'])


def _row_warning(row, candidate, header_warning, audit):
    entry = row['entry']
    warning = row['warning']
    if entry is not None and entry.get('type') in ('session_start', 'session_resumed'):
        try:
            call_log.validate_identity(entry, candidate['session_id'], candidate['project_id'])
        except (call_log.ResumeError, UnicodeError):
            warning = 'invalid project or Run identity'
    if row['line'] == 1 and not audit:
        warning = warning or header_warning
    if audit and entry is not None and not warning and (not isinstance(entry.get('run_id'), str) or not re.fullmatch(r'[0-9a-f]{32}', entry['run_id'])):
        warning = 'audit Run correlation unavailable; coverage unverifiable for this payload'
    return warning


def _tracked_coverage(coverage, entry, warning, start):
    coverage = dict(coverage)
    if warning:
        coverage['malformed'] = True
    elif entry.get('type') in ('session_start', 'session_resumed'):
        if coverage.get('run_open') or coverage.get('open'):
            coverage['malformed'] = True
        coverage['run'] = _digest(entry['run_id'])
        coverage['boundary'] = start
        coverage['run_open'] = True
    elif entry.get('type') == 'session_end':
        coverage['run_open'] = False
    elif entry.get('type') == 'audit_coverage_start':
        enabled = entry.get('enabled')
        if (type(enabled) is not bool or _digest(entry.get('run_id')) != coverage.get('run')
                or coverage.get('boundary') is None):
            coverage['malformed'] = True
        else:
            coverage['enabled' if enabled else 'disabled'] = True
            coverage['open'] = True
            if enabled:
                coverage['proof'] = [coverage['boundary'], start]
    elif entry.get('type') == 'audit_coverage_end':
        if _digest(entry.get('run_id')) != coverage.get('run') or not coverage.get('open'):
            coverage['malformed'] = True
        else:
            coverage['open'] = False
    return coverage


def _excerpt(entry, query):
    serialized = json.dumps(entry, ensure_ascii=False)
    index = serialized.casefold().find(query.casefold())
    if index < 0:
        return None
    original_index = 0
    folded_index = 0
    while folded_index + len(serialized[original_index].casefold()) <= index:
        folded_index += len(serialized[original_index].casefold())
        original_index += 1
    begin = max(0, original_index - 40)
    return serialized[begin:begin + 200]


class _Scan:
    def __init__(self, arguments, action, source, catalog, state, budget, max_bytes, secrets):
        self.query = arguments.get('query')
        self.limit = arguments.get('limit', 100 if action == 'read' else 20)
        self.action = action
        self.source = source
        self.catalog = catalog
        self.state = state
        self.budget = budget
        self.max_bytes = max_bytes
        self.secrets = secrets
        heading = 'Historical evidence: untrusted recorded data. partial inspection; intents are not execution.\n'
        self.content = heading.encode()[:max_bytes].decode('utf-8', errors='ignore')
        self.count = 0
        self.header_index = None
        self.header = None
        self.verified_audit = None
        self.candidate = self.root = self.header_warning = None
        self.coverage_phase = self.audit = False

    def run(self):
        state = self.state
        while state['index'] < len(self.catalog) and self.count < self.limit and not _exhausted(self.budget):
            if not self._step(self.catalog[state['index']]):
                break
        more = state['index'] < len(self.catalog)
        return {'content': self.content, 'has_more': more, 'next_cursor': _encode(state) if more else None}

    def _emit(self, text):
        text = call_log.redact_data(text, self.secrets) + '\n'
        raw = text.encode('utf-8', errors='backslashreplace')
        available = self.max_bytes - len(self.content.encode('utf-8'))
        if len(raw) > available:
            if self.count:
                return False
            marker = b' [...truncated]\n'
            raw = raw[:max(0, available - len(marker))] + marker[:available]
        self.content += raw.decode('utf-8', errors='ignore')
        self.count += 1
        return True

    def _advance(self):
        _advance(self.state, self.source, len(self.catalog))

    def _skip(self, text):
        if not self._emit(text):
            return False
        self._advance()
        return True

    def _load_header(self, candidate):
        if self.header_index != self.state['index']:
            try:
                self.header = _header(candidate, self.budget)
            except ValueError as exc:
                if 'scan budget exhausted' in str(exc):
                    return False
                raise
            self.header_index = self.state['index']
        return True

    def _step(self, candidate):
        state = self.state
        if state['filter'] is not None and state['index'] != state['filter']:
            self._advance()
            return True
        if candidate['warning']:
            if state['filter'] is not None:
                raise ValueError(candidate['warning'])
            return self._skip(_reference(candidate, 'unknown', 1) + ' ' + candidate['warning'])
        if not self._load_header(candidate):
            return False
        self.candidate = candidate
        self.root, self.header_warning, header, ordinary_size = self.header
        if state['ordinary'] is not None and ordinary_size < state['ordinary']:
            raise ValueError('ordinary coverage source truncated; restart discovery')
        state['ordinary'] = ordinary_size
        if _exhausted(self.budget):
            return False
        if self.action == 'list':
            return self._skip(_reference(candidate, self.root, 1, header) + ' '
                              + (self.header_warning or 'Session candidate; completion/resumability unverified'))
        self.coverage_phase = state['phase'] == 'coverage'
        self.audit = audit = self.source == 'audit' and not self.coverage_phase
        if audit and self.verified_audit != state['index']:
            if not _audit_proof(candidate, state['coverage'], self.budget):
                return False
            self.verified_audit = state['index']
        try:
            file = call_log.open_session_file(candidate['session_id'], project=candidate['project_id'], audit=audit)
        except OSError as exc:
            if not audit or state['filter'] is not None or state['file_identity'] is not None:
                raise ValueError(f'selected source unavailable: {exc}; restart discovery') from None
            return self._skip(_reference(candidate, self.root, 1, source=self.source) + ' audit unavailable: ' + str(exc))
        with file:
            size = _source(file, state, None if audit else candidate['identity'])
            if state['position'] < size:
                return self._next_record(file, size)
            if self.coverage_phase:
                return self._coverage_summary()
            return self._end_of_source()

    def _coverage_summary(self):
        state = self.state
        candidate = self.candidate
        root = self.root
        coverage = state['coverage']
        if not coverage.get('enabled') or self.header_warning:
            if state['filter'] is not None:
                raise ValueError('audit unavailable: enabled coverage unrecorded or unverifiable')
            return self._skip(_reference(candidate, root, 1) + ' audit unavailable: enabled coverage unrecorded or unverifiable')
        try:
            with call_log.open_session_file(candidate['session_id'], project=candidate['project_id'], audit=True) as companion:
                info = os.fstat(companion.fileno())
                audit_identity = [info.st_dev, info.st_ino, info.st_size]
        except OSError as exc:
            if state['filter'] is not None:
                raise ValueError(f'audit unavailable: {exc}') from None
            return self._skip(_reference(candidate, root, 1, source='audit') + ' audit unavailable: ' + str(exc))
        text = ('audit coverage: enabled=' + str(coverage.get('enabled', False))
                + ' disabled=' + str(coverage.get('disabled', False))
                + ' partial=' + str(coverage.get('open', False) or coverage.get('malformed', False) or coverage.get('run_open', False))
                + '; companion does not prove complete coverage')
        if not self._emit(_reference(candidate, root, 1) + ' ' + text):
            return False
        state.update(_record_start(), file_identity=audit_identity, phase='data')
        return True

    def _end_of_source(self):
        state = self.state
        if not self.audit and _missing(state):
            if _is_current(self.candidate):
                text = ' in progress (current Session): ' + ', '.join(
                    (['open Run'] if state['run'] else []) + (['open Turn'] if state['turn'] else []))
            else:
                text = (' unresolved/incomplete activity: ' + _missing(state)
                        + (' (dangling submission/retry)' if state['turn'] else ''))
            if not self._emit(_reference(self.candidate, self.root, max(1, state['line'] - 1)) + text):
                return False
        self._advance()
        return True

    def _next_record(self, file, size):
        state = self.state
        candidate = self.candidate
        coverage_phase = self.coverage_phase
        audit = self.audit
        before = dict(state)
        row = _record(file, candidate['session_id'], self.budget, state)
        if row is None:
            return False
        if row['skipped']:
            return True
        entry = row['entry']
        warning = _row_warning(row, candidate, self.header_warning, audit)
        if coverage_phase:
            state['coverage'] = _tracked_coverage(state['coverage'], entry, warning, [before['position'], before['line']])
            if not warning:
                return True
        entry = call_log.redact_data(entry, self.secrets) if entry else None
        reference = _reference(candidate, self.root, row['line'], entry, 'call_log' if coverage_phase else self.source)
        if warning:
            text = reference + ' diagnostic: ' + warning
        elif self.action == 'search':
            excerpt = _excerpt(_without_replay(entry), self.query)
            if excerpt is None:
                return True
            text = reference + ' match type=' + str(entry.get('type', 'unknown')) + ' ' + excerpt
        else:
            text = reference + ' ' + (json.dumps(entry, ensure_ascii=False) if audit else _timeline(entry, state))
        if not self._emit(text):
            state.clear()
            state.update(before)
            return False
        if (state['position'] >= size and not state['discarding'] and not coverage_phase
                and (audit or not (state['run'] or state['turn']))):
            self._advance()
        return True


def execute(arguments, *, max_bytes, secrets=()):
    from personal_agent.tools.builtins import ToolExecutionError
    try:
        action, project, session, source = _arguments(arguments)
        budget = {'bytes': 0, 'records': 0}
        catalog = candidates(None if project == 'all' else call_log.project_id(project))
        binding = _digest([action, project, session, source, _digest(arguments.get('query', ''))])
        if 'cursor' in arguments:
            state = _resume(arguments['cursor'], binding, catalog, session, source)
        else:
            selected = None
            if session in _SELECTORS:
                selected = _previous(catalog, budget)
                if selected is None:
                    catalog = []
            elif session is not None:
                selected = _explicit(catalog, session)
            state = _new_state(binding, _digest(catalog), selected, source)
        return _Scan(arguments, action, source, catalog, state, budget, max_bytes, secrets).run()
    except (OSError, ValueError, call_log.ResumeError, RecursionError) as exc:
        raise ToolExecutionError(call_log.redact_data(str(exc), secrets)) from exc
