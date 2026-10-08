"""Pure generated-artifact intent hints; policy/observed UI still authorize delivery.

These helpers never create, download, extract or execute a file. They are deliberately
conservative lexical hints, not a substitute for tool schemas or human clarification.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


OFFICE_EXTENSIONS = frozenset({
    'doc', 'docx', 'docm', 'dot', 'dotx', 'dotm',
    'xls', 'xlsx', 'xlsm', 'xlsb', 'xlt', 'xltx', 'xltm', 'xla', 'xlam',
    'ppt', 'pptx', 'pptm', 'pot', 'potx', 'potm', 'pps', 'ppsx', 'ppsm', 'ppam',
})
NONOFFICE_EXTENSIONS = frozenset({
    'py', 'md', 'txt', 'json', 'csv', 'pdf', 'html', 'htm', 'css', 'js', 'ts',
    'tsx', 'jsx', 'sql', 'xml', 'yaml', 'yml', 'ini', 'toml', 'ps1', 'bat',
    'cmd', 'sh', 'png', 'jpg', 'jpeg', 'webp', 'svg', 'zip',
})
_EXTENSIONS = '|'.join(sorted(OFFICE_EXTENSIONS | NONOFFICE_EXTENSIONS, key=len, reverse=True))
_OFFICE_FORMAT = re.compile(r'(?<![\w.])\.?(?:' + '|'.join(sorted(OFFICE_EXTENSIONS, key=len, reverse=True)) + r')\b', re.I)
_FILE = re.compile(r'(?<![\w.])([\w][\w.-]*\.(?:' + _EXTENSIONS + r'))(?!\w|\.\w)', re.I)
_QUOTED_FILE = re.compile(r'["`\']([^"`\'\r\n/\\]+\.(?:' + _EXTENSIONS + r'))["`\']', re.I)
_CREATE = re.compile(r'\b(?:create|generate|build|make|write|produce|deliver|provide|give|export|save|convert|package|prepare|draft|return|download)\b', re.I)
_INFORMATIONAL = re.compile(r'^\s*(?:how\s+(?:do|does|can|should|would|to)\b|what\s+(?:is|are|does)\b)', re.I)
_READ_ONLY = re.compile(r'^\s*(?:please\s+)?(?:read|inspect|review|analy[sz]e|open|list|summari[sz]e|explain|check|verify|report)\b', re.I)
_EXECUTION = re.compile(r'^\s*(?:please\s+)?(?:(?:run|execute|start)\b|request\s+(?:exactly\s+)?(?:one\s+|a\s+)?code_runner\b)', re.I)
_INPUT_PREFIX = re.compile(r'\b(?:read|parse|inspect|review|open|analy[sz]e|existing|input|source|from)\s+(?:the\s+|file\s+|existing\s+|named\s+|called\s+)*["`\']?$', re.I)
_OFFICE_KIND = re.compile(r'\b(?:word\s+(?:document|file|template|report|table)|excel\s+(?:workbook|spreadsheet|file|template)|powerpoint(?:\s+(?:presentation|file|template))?|workbook|slide\s+deck|office\s+(?:document|file))\b', re.I)
_DIRECT_KIND = re.compile(r'\b(?:file|document|script|markdown|plain\s+text|json|csv|pdf|image|downloadable|download\s+link)\b', re.I)
_PROJECT = re.compile(
    r'\b(?:(?:full|complete|entire|whole)\s+(?:(?:coding|code|source|python|software)\s+)?(?:project|package|codebase|source\s+code)|'
    r'(?:coding|software|python|automation|application|website|source\s+code)\s+(?:project|package)|'
    r'project\s+(?:package|archive)|codebase)\b|'
    r'\b(?:create|build|generate|make|deliver|provide)\s+(?:me\s+)?(?:a|an|the)\s+(?:new\s+)?project\b(?!\s+(?:plan|proposal|timeline|summary|report|specification)\b)',
    re.I,
)
_MULTIPLE = re.compile(r'\b(?:(?:multiple|several)\s+(?:files|documents|scripts|outputs)|(?:files|documents|scripts)\s+(?:together|as\s+a\s+package))\b', re.I)
_ZIP = re.compile(r'\b(?:zip(?:ped)?(?:\s+(?:file|archive|package))?|archive\s+package)\b', re.I)
_NEGATION = re.compile(r"\b(?:do\s+not|don['’]t|never|not\s+(?:a\s+)?request\s+to|no\s+request\s+to)\b", re.I)
_CLAUSE_END = re.compile(r'[.!?;](?=\s|$)|\n|\b(?:but|however|instead)\b(?=\s)', re.I)


@dataclass(frozen=True)
class DeliveryRequirements:
    mode: Literal['direct', 'zip', 'none']
    expected_names: tuple[str, ...]
    reason: str

    def as_dict(self) -> dict:
        return {'mode': self.mode, 'expected_names': list(self.expected_names), 'reason': self.reason}


def _expected_names(text: str) -> tuple[str, ...]:
    """Collect explicit output basenames, ignoring clearly named input files."""
    candidates = []
    quoted_spans = []
    for match in _QUOTED_FILE.finditer(text):
        quoted_spans.append(match.span())
        if not _INPUT_PREFIX.search(text[max(0, match.start() - 70):match.start()]):
            candidates.append((match.start(), match.group(1).strip()))
    for match in _FILE.finditer(text):
        if any(start <= match.start() < end for start, end in quoted_spans):
            continue
        if not _INPUT_PREFIX.search(text[max(0, match.start() - 70):match.start()]):
            candidates.append((match.start(), match.group(1)))
    names, seen = [], set()
    for _, name in sorted(candidates):
        if name.casefold() not in seen:
            names.append(name)
            seen.add(name.casefold())
    return tuple(names)


def _without_negated_clauses(text: str) -> str:
    """Mask explicit negative clauses while retaining separate positive requests.

    This narrow lexical rule handles the stated prohibitions, not arbitrary
    language inference. Sentence/semicolon boundaries and explicit contrasts
    end their scope. Filenames remain data, including words such as never.txt.
    """
    filename_spans = [match.span() for pattern in (_QUOTED_FILE, _FILE) for match in pattern.finditer(text)]
    def inside_filename(position):
        return any(start <= position < end for start, end in filename_spans)
    masked = list(text)
    for negative in _NEGATION.finditer(text):
        if inside_filename(negative.start()):
            continue
        end = len(text)
        for boundary in _CLAUSE_END.finditer(text, negative.end()):
            if not inside_filename(boundary.start()):
                end = boundary.start()
                break
        masked[negative.start():end] = ' ' * (end - negative.start())
    return ''.join(masked)


def detect_requirements(user_text: str) -> DeliveryRequirements:
    if not isinstance(user_text, str):
        raise TypeError('user_text must be a string')
    text = _without_negated_clauses(user_text.strip()).strip()
    if not text or _INFORMATIONAL.search(text):
        return DeliveryRequirements('none', (), 'No generated artifact was requested.')
    # A filename such as synthetic-download-run.py is data, not a download verb.
    action_text = _FILE.sub(' ', _QUOTED_FILE.sub(' ', text))
    execution_intent = re.split(r'\bArguments:\s*\n', action_text, maxsplit=1, flags=re.I)[0]
    if _EXECUTION.search(text) and not re.search(r'\b(?:downloadable|download\s+(?:link|a\s+new|new\s+file)|copilot\s+(?:artifact|file))\b', execution_intent, re.I):
        return DeliveryRequirements('none', (), 'Execute existing local code; no new Copilot artifact delivery was requested.')
    actions = list(_CREATE.finditer(action_text))
    if not actions:
        return DeliveryRequirements('none', (), 'No file-generation or delivery request was detected.')
    if _READ_ONLY.search(text) and not any(match.group().lower() in {
        'create', 'generate', 'build', 'make', 'write', 'produce', 'export', 'save', 'convert', 'package', 'draft'
    } for match in actions):
        return DeliveryRequirements('none', (), 'Read-only discussion is not artifact delivery.')
    names = _expected_names(text)
    office_names = [name for name in names if name.rsplit('.', 1)[-1].lower() in OFFICE_EXTENSIONS]
    office_kind = bool(_OFFICE_KIND.search(text) or _OFFICE_FORMAT.search(text))
    if office_names or office_kind:
        return DeliveryRequirements('zip', names, 'Office outputs always require a downloadable ZIP, including single files.')
    if _PROJECT.search(text):
        return DeliveryRequirements('zip', names, 'A complete coding project/package requires a downloadable ZIP.')
    if len(names) > 1 or _MULTIPLE.search(text):
        return DeliveryRequirements('zip', names, 'Multiple output files require a single downloadable ZIP.')
    explicit_zip = any(name.lower().endswith('.zip') for name in names)
    for mention in _ZIP.finditer(text):
        prefix = re.split(r'[.!?\n]', text[:mention.start()])[-1]
        suffix = text[mention.end():mention.end() + 30]
        if not re.search(r'\b(?:if|fallback|otherwise)\b', prefix, re.I) and not re.match(r'\s+fallback\b', suffix, re.I):
            explicit_zip = True
    if explicit_zip and (names or _DIRECT_KIND.search(text) or _CREATE.search(text)):
        return DeliveryRequirements('zip', names, 'The user explicitly requested an archive/package.')
    format_reference = bool(re.search(r'(?<![\w])\.(?:' + _EXTENSIONS + r')\b', text, re.I))
    if names or _DIRECT_KIND.search(text) or format_reference:
        return DeliveryRequirements('direct', names, 'One non-Office artifact needs an actual UI download link, with ZIP fallback.')
    return DeliveryRequirements('none', (), 'No concrete generated-file output was detected.')


detect_delivery_requirements = detect_requirements


def delivery_requirements(user_text: str) -> dict:
    """JSON-compatible integration API used by prompts and the delivery gate."""
    return detect_requirements(user_text).as_dict()


def delivery_instruction(user_text: str) -> str:
    requirement = detect_requirements(user_text)
    if requirement.mode == 'none':
        return ''
    names = (' Expected original output names: ' + ', '.join(requirement.expected_names) + '.') if requirement.expected_names else ''
    if requirement.mode == 'zip':
        packaging = 'Generate a downloadable ZIP containing the requested original files/package structure; even a single Office file must be inside ZIP.'
    else:
        packaging = 'Generate the requested non-Office file as an actual downloadable UI artifact. If only plaintext, a code block or a sandbox reference is available, provide a downloadable ZIP containing that same file instead.'
    return (packaging + names + ' Keep one strict JSON response envelope. Put one actual clickable Markdown artifact download link AFTER '
            '<<<COPILOT_AGENT_V1_END>>>, outside the JSON object; a URL inside user_response is not a clickable anchor. '
            'Use only an actual available artifact link; do not invent a URL/hash or claim a sandbox path is delivery. '
            'Local download, inspection and extraction remain policy-controlled; do not execute delivered code. '
            'If artifact creation is unavailable, report it honestly without expanding the task.')


def retry_message(reason: str, attempt: int, max_attempts: int = 3, office: bool = False) -> str:
    """Return a compact correction, or an empty string once the budget is exhausted.

    ``attempt`` is the one-based number of the retry being considered (one for
    the first retry). Submitting this correction is an ordinary counted chat message.
    The caller must reconcile uncertain side effects before requesting a retry.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('A nonempty observed failure reason is required')
    if type(attempt) is not int or attempt < 1 or type(max_attempts) is not int or max_attempts < 0:
        raise ValueError('attempt must be a positive integer and max_attempts a nonnegative integer')
    if type(office) is not bool:
        raise ValueError('office must be boolean')
    if attempt > max_attempts:
        return ''
    format_rule = ('Office outputs must remain inside a downloadable ZIP; do not substitute plaintext or another format.'
                   if office else 'For a plaintext/code-block/sandbox-only result, provide a downloadable ZIP of the same requested artifact; otherwise reissue its actual downloadable link.')
    return (f'Delivery correction {attempt}/{max_attempts}: observed problem: {reason.strip()[:1200]}. '
            'Reissue the same requested artifact without changing user intent or expanding scope. ' + format_rule +
            ' Keep one strict envelope and put one actual clickable Markdown download link AFTER <<<COPILOT_AGENT_V1_END>>>, '
            'outside the JSON object. Do not invent URLs or claim local delivery; report unavailable capability honestly. '
            'This is an ordinary conversation submission; findings keep their normal counting/attachment rules.')
