"""Public live reply previews and clearly attributed local activity."""
import json
import os
import re
import sys
from .logging_utils import now, redact
from .protocol import BEGIN, END

PUBLIC_FIELDS = ('user_response', 'task_interpretation', 'decision_summary', 'assumptions', 'action_plan', 'risk_summary')
ROLE_STYLES = {
    'System': '97;44',
    'Orchestrator': '97;45',
    'Copilot': '30;46',
    'User': '30;42',
    'Approval': '30;43',
    'Error': '97;41',
    'Tool': '30;104',
}


def _enable_colour(stream) -> bool:
    if os.environ.get('NO_COLOR') is not None or os.environ.get('TERM', '').casefold() == 'dumb':
        return False
    if not getattr(stream, 'isatty', lambda: False)():
        return False
    if os.name != 'nt':
        return True
    try:
        import ctypes
        handle = ctypes.windll.kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if not ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError):
        return False


def _actor_style(actor: str) -> str:
    if actor.startswith('Tool/'):
        return ROLE_STYLES['Tool']
    if actor.startswith('Copilot'):
        return ROLE_STYLES['Copilot']
    return ROLE_STYLES.get(actor, ROLE_STYLES['System'])


def _terminal_text(value, preserve_markup=False) -> str:
    message = redact(str(value)).replace('\r', '')
    # Untrusted reply/tool text cannot inject terminal controls or actor headers.
    message = ''.join(char if char in '\n\t' or ord(char) >= 32 and not 127 <= ord(char) <= 159
                      else '\\x' + format(ord(char), '02x') for char in message)
    if not preserve_markup:
        message = re.sub(r'(?m)^\s{0,3}#{1,6}\s+', '', message)
        message = message.replace('```json', '').replace('```', '')
        message = re.sub(r'\*\*([^*]+)\*\*', r'\1', message)
        message = re.sub(r'`([^`\n]+)`', r'\1', message)
    lines, blank = [], False
    for line in message.strip().split('\n'):
        empty = not line.strip()
        if empty and blank:
            continue
        lines.append(line.rstrip())
        blank = empty
    return '\n'.join(lines)


def public_preview(raw, session_id, request_id):
    """Read completed top-level JSON values during rendering; never authorize actions."""
    if raw.count(BEGIN) != 1 or raw.count(END) > 1:
        return {}
    text = raw.split(BEGIN, 1)[1].split(END, 1)[0].lstrip()
    if text.startswith('```'):
        if '\n' not in text:
            return {}
        text = text.split('\n', 1)[1].lstrip()
    if not text.startswith('{'):
        return {}
    decoder = json.JSONDecoder()
    values, cursor = {}, 1
    try:
        while cursor < len(text):
            while cursor < len(text) and text[cursor].isspace(): cursor += 1
            if cursor >= len(text) or text[cursor] == '}': break
            key, cursor = decoder.raw_decode(text, cursor)
            if type(key) is not str or key in values: return {}
            while cursor < len(text) and text[cursor].isspace(): cursor += 1
            if cursor >= len(text) or text[cursor] != ':': break
            cursor += 1
            while cursor < len(text) and text[cursor].isspace(): cursor += 1
            value, cursor = decoder.raw_decode(text, cursor)
            values[key] = value
            while cursor < len(text) and text[cursor].isspace(): cursor += 1
            if cursor >= len(text) or text[cursor] != ',': break
            cursor += 1
    except (ValueError, RecursionError):
        pass  # Incomplete values remain buffered, including split escapes/secrets.
    if values.get('session_id') != session_id or values.get('request_id') != request_id:
        return {}
    return {key: redact(values[key]) for key in PUBLIC_FIELDS if key in values}


class Feedback:
    def __init__(self, sink=None, state=None, color=None):
        self.sink, self.state = sink or print, state
        self.color = _enable_colour(sys.stdout) if color is None and (sink is None or sink is print) else bool(color)

    def emit(self, actor, message, preserve_markup=False, **metadata):
        stamp = now()
        message = _terminal_text(message, preserve_markup=preserve_markup)
        plain_label = '[' + actor + ']'
        label = ('\x1b[' + _actor_style(actor) + 'm ' + actor + ' \x1b[0m') if self.color else plain_label
        clock = ('\x1b[2m[' + stamp[11:19] + ']\x1b[0m') if self.color else '[' + stamp[11:19] + ']'
        prefix = clock + ' ' + label + ' '
        self.sink('\n'.join(prefix + line for line in message.split('\n')))
        if self.state:
            self.state.event('feedback', actor=actor, message=message, **metadata)

    def record(self, actor, message, **metadata):
        """Retain detailed feedback in the audit log without adding terminal noise."""
        if self.state:
            self.state.event('feedback_detail', actor=actor,
                             message=_terminal_text(message), **metadata)

    def section(self, actor, title, items=(), **metadata):
        lines = [str(title)]
        for label, value in items:
            if value in (None, '', [], {}):
                continue
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            lines.append('  ' + str(label) + ': ' + rendered)
        self.emit(actor, '\n'.join(lines), **metadata)

    def prompt(self, actor, message):
        label = ('\x1b[' + _actor_style(actor) + 'm ' + actor + ' \x1b[0m') if self.color else '[' + actor + ']'
        return label + ' ' + _terminal_text(message)
