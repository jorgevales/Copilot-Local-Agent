from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl

SENSITIVE = re.compile(r'(?i)(?:bearer\s+[\w.\-]+|(?:password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret)\s*[:=]\s*[^\s,;]+|(?:sk-|ghp_)[A-Za-z0-9_-]{12,}|eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)')


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def redact(value):
    if isinstance(value, str):
        def safe_link(match):
            original = match.group(0)
            try:
                parsed = urlsplit(original)
                sensitive = {'sig','signature','token','access_token','auth','authorization','code','key','api_key','client_secret','password','sas'}
                if parsed.username or parsed.password or any(key.casefold() in sensitive for key, _ in parse_qsl(parsed.query)):
                    host = parsed.hostname or ''
                    if parsed.port: host += ':' + str(parsed.port)
                    return urlunsplit((parsed.scheme,host,parsed.path,'','')) + ('?[REDACTED]' if parsed.query else '')
            except ValueError:
                return '[REDACTED_URL]'
            return original
        value = re.sub(r'https?://[^\s<>"\x00-\x1f]+', safe_link, value)
        return SENSITIVE.sub('[REDACTED]', value)
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if re.search(r'(?i)^(password|secret|token|credential|cookie|authorization)$', k) else redact(v)) for k, v in value.items()}
    return value


class EventLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **details) -> None:
        with self.path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(redact({'timestamp': now(), 'event': event, **details}), ensure_ascii=False) + '\n')
            handle.flush()
