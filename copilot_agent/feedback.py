"""Public live reply previews and clearly attributed local activity."""
import json
from .logging_utils import now, redact
from .protocol import BEGIN, END

PUBLIC_FIELDS = ('user_response', 'task_interpretation', 'decision_summary', 'assumptions', 'action_plan', 'risk_summary')


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
    def __init__(self, sink=print, state=None):
        self.sink, self.state = sink, state

    def emit(self, actor, message, **metadata):
        stamp = now()
        message = redact(str(message))
        # Untrusted reply/tool text cannot inject terminal controls or actor headers.
        message = ''.join(char if char in '\n\t' or ord(char) >= 32 and not 127 <= ord(char) <= 159
                          else '\\x' + format(ord(char), '02x') for char in message)
        prefix = '[' + stamp[11:19] + '] [' + actor + '] '
        self.sink('\n'.join(prefix + line for line in message.split('\n')))
        if self.state:
            self.state.event('feedback', actor=actor, message=message, **metadata)
