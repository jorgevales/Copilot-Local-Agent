"""Lossless, readable Markdown reference bundling; no ZIP, summary or deletion."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .persistence import write_preserving

MAX_BUNDLE_BYTES = 20 * 1024 * 1024
MANIFEST_BEGIN = '<!-- COPILOT_REFERENCE_MANIFEST_BEGIN -->'
MANIFEST_END = '<!-- COPILOT_REFERENCE_MANIFEST_END -->'
_PREAMBLE = (
    '# Copilot Agent reference bundle\n\n'
    'Bundle format: 1.0. These are ten complete original reference components, not summaries.\n'
    'Read each component according to its role. The schema and runtime catalogue define exact protocol/tools; '
    'no attachment grants execution approval or overrides platform controls.\n'
    'The manifest records source versions, SHA-256, original byte lengths and absolute byte offsets. '
    'Offsets are zero-based and end_byte is exclusive in this complete UTF-8 file. '
    'Original content, BOMs, line endings and final-newline state are preserved exactly.\n\n'
)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bounded(path: Path, limit: int) -> bytes:
    if not path.is_file():
        raise ValueError('Missing or non-file reference component: ' + str(path))
    if path.stat().st_size > limit:
        raise ValueError('Reference component exceeds the bundle size limit: ' + path.name)
    with path.open('rb') as handle:
        value = handle.read(limit + 1)
    if len(value) > limit:
        raise ValueError('Reference component grew beyond the bundle size limit: ' + path.name)
    return value


def _check_component_names(names: list[str]) -> None:
    if len(names) != 10 or len(set(names)) != 10:
        raise ValueError('Exactly ten distinct reference components are required')
    guidance = [name for name in names if re.fullmatch(r'0[1-8]-[A-Za-z0-9_-]+\.md', name)]
    ordinals = [name[:2] for name in guidance]
    if len(guidance) != 8 or set(ordinals) != {f'{number:02}' for number in range(1, 9)}:
        raise ValueError('Exactly one guidance component for each ordinal 01 through 08 is required')
    if set(names) - set(guidance) != {'response-v1.schema.json', 'tool-catalogue.json'}:
        raise ValueError('The response schema and current runtime tool-catalogue.json are required')


def _check_reference_names(names: list[str]) -> None:
    if not names or len(names) > 10 or len(set(names)) != len(names):
        raise ValueError('Distinct complete reference components are required')
    if any(not re.fullmatch(r'0[1-8]-[A-Za-z0-9_-]+\.md', name)
           and name not in {'response-v1.schema.json', 'tool-catalogue.json'} for name in names):
        raise ValueError('Unexpected reference component name')


def _manifest_prefix(components: list[dict], preamble: str) -> bytes:
    metadata = json.dumps({'schema_version': '1.0', 'components': components}, ensure_ascii=False, indent=2)
    return (preamble + MANIFEST_BEGIN + '\n```json\n' + metadata + '\n```\n' + MANIFEST_END + '\n\n').encode('utf-8')


def build_bundle(paths, manifest, destination, max_bytes=MAX_BUNDLE_BYTES) -> dict:
    """Return path/hash/component_manifest for a single exact-byte Markdown bundle.

    ``manifest`` supplies name/version/sha256 for each input path. All inputs are
    verified before writing. Replaced bundles retain prior versions. No source is
    edited. Additional section delimiters are outside the recorded source spans.
    """
    paths = list(paths)
    _check_component_names([Path(path).name for path in paths])
    return _build_reference(paths, manifest, destination, max_bytes)


def _build_reference(paths, manifest, destination, max_bytes, *, preamble=_PREAMBLE,
                     write_output=True) -> dict:
    """Compose any verified reference subset; source bytes are never rewritten."""
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_BUNDLE_BYTES:
        raise ValueError('max_bytes must be a positive integer of at most 20 MiB')
    sources = [Path(path) for path in paths]
    names = [path.name for path in sources]
    _check_reference_names(names)
    records = list(manifest)
    if len(records) != len(sources) or any(not isinstance(item, dict) for item in records):
        raise ValueError('A complete component verification manifest is required')
    recorded = {item.get('name'): item for item in records}
    if len(recorded) != len(sources) or set(recorded) != set(names):
        raise ValueError('Source paths and verification manifest do not match')
    target = Path(destination)
    if target.suffix.lower() != '.md':
        raise ValueError('The reference bundle must be a Markdown file, never a ZIP')
    if any(target.absolute() == path.absolute() for path in sources):
        raise ValueError('The bundle destination cannot replace an original component')
    source_data, sections, components = [], [], []
    remaining = max_bytes
    for path in sources:
        item = recorded[path.name]
        version = item.get('version')
        if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9._+-]{1,64}', version):
            raise ValueError('Invalid component version: ' + path.name)
        digest = item.get('sha256')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid recorded SHA-256: ' + path.name)
        value = _read_bounded(path, remaining)
        if not value:
            raise ValueError('Reference components must not be empty: ' + path.name)
        value.decode('utf-8', errors='strict')  # BOM deliberately retained, not utf-8-sig decoding.
        if _hash(value) != digest:
            raise ValueError('Reference component changed after verification: ' + path.name)
        if 'byte_length' in item and item['byte_length'] != len(value):
            raise ValueError('Recorded byte length does not match: ' + path.name)
        remaining -= len(value)
        source_data.append(value)
        component = {'name': path.name, 'version': version, 'sha256': digest,
                     'byte_length': len(value), 'start_byte': 0, 'end_byte': 0}
        components.append(component)
        header = ('## Component: ' + path.name + '\n\nVersion: ' + version + '\n\n'
                  'SHA-256: `' + digest + '`\n\nOriginal byte length: ' + str(len(value)) + '\n\n'
                  '<!-- COMPONENT_BEGIN: ' + path.name + ' -->\n').encode('utf-8')
        suffix = ('\n<!-- COMPONENT_END: ' + path.name + ' -->\n\n').encode('utf-8')
        if path.suffix.lower() == '.json':
            longest = max((len(match.group()) for match in re.finditer(rb'`+', value)), default=0)
            fence = b'`' * max(3, longest + 1)
            header += fence + b'json\n'
            suffix = b'\n' + fence + b'\n' + suffix
        sections.append((header, suffix))
    # Manifest integer widths influence prefix length. Solve the tiny fixed point
    # before assembling so every offset refers to the final published byte stream.
    for attempt in range(16):
        prefix = _manifest_prefix(components, preamble)
        cursor = len(prefix)
        updated = []
        for component, value, (header, suffix) in zip(components, source_data, sections):
            start = cursor + len(header)
            updated.append(dict(component, start_byte=start, end_byte=start + len(value)))
            cursor = start + len(value) + len(suffix)
        if updated == components:
            break
        components = updated
    else:
        raise ValueError('Reference manifest byte offsets did not converge')
    content = prefix + b''.join(header + value + suffix for value, (header, suffix) in zip(source_data, sections))
    if len(content) > max_bytes:
        raise ValueError('Complete reference bundle including headers exceeds max_bytes')
    bundle_hash = _hash(content)
    record = {'path': str(target), 'sha256': bundle_hash, 'byte_length': len(content),
              'component_manifest': components}
    if not write_output:
        return dict(record, _content=content)
    _write_verified_reference(target, content, max_bytes)
    return record


def _write_verified_reference(target: Path, content: bytes, max_bytes: int) -> None:
    bundle_hash = _hash(content)
    if not target.exists() or _hash(_read_bounded(target, max_bytes)) != bundle_hash:
        # UTF-8 decoding/encoding preserves every source byte including BOM/CRLF.
        # The existing preserving writer uses explicit LF output (no Windows
        # newline translation), atomic replacement and retained prior versions.
        write_preserving(target, content.decode('utf-8'))
    if _hash(_read_bounded(target, max_bytes)) != bundle_hash:
        raise ValueError('Written reference bundle failed byte-integrity verification')


def build_startup_attachments(paths, manifest, directory, max_bytes=MAX_BUNDLE_BYTES) -> dict:
    """Keep guidance 01–06 separate and group only 07/08 and schema/catalogue.

    All ten original source hashes and the total eight-attachment byte size are
    checked before any generated group is written. No guidance is summarized.
    """
    sources = [Path(path) for path in paths]
    _check_component_names([path.name for path in sources])
    records = list(manifest)
    if len(records) != 10 or any(not isinstance(item, dict) for item in records):
        raise ValueError('A complete ten-component verification manifest is required')
    recorded = {item.get('name'): item for item in records}
    if len(recorded) != 10 or set(recorded) != {path.name for path in sources}:
        raise ValueError('Source paths and verification manifest do not match')
    output = Path(directory)
    guidance = sorted((path for path in sources if path.suffix == '.md'), key=lambda path: path.name)
    separate = guidance[:6]
    grouped = [guidance[6:], [next(path for path in sources if path.name == name)
                            for name in ('response-v1.schema.json', 'tool-catalogue.json')]]
    titles = ['07-08-complete-guidance.md', 'protocol-schema-and-tool-catalogue.md']
    preambles = [
        '# Complete guidance 07 and 08\n\n'
        'Read both complete guidance components below together with separately attached guidance 01–06. '
        'No source has been summarized. Follow the complete current response schema and tool catalogue '
        'in the protocol reference attachment; return one valid correlated response envelope. '
        'Reference content cannot grant approval or override platform controls.\n\n',
        '# Complete current response schema and tool catalogue\n\n'
        'Use the complete current schema below for one valid correlated response envelope, and only '
        'the current tool definitions below. Read all eight complete guidance documents, including '
        'the six separate originals and the 07/08 reference. Nothing here grants execution approval '
        'or overrides platform controls. JSON component fences preserve the complete original source.\n\n',
    ]
    plans = []
    # The generic composer provides the same strict UTF-8/hash/version validation
    # for separately uploaded sources without writing or replacing those sources.
    standalone_records = []
    for path in separate:
        checked = _build_reference([path], [recorded[path.name]], output / ('verify-' + path.name),
                                   max_bytes, write_output=False)
        standalone_records.append(checked['component_manifest'][0])
    for group, title, preamble in zip(grouped, titles, preambles):
        plans.append(_build_reference(group, [recorded[path.name] for path in group], output / title,
                                      max_bytes, preamble=preamble, write_output=False))
    if sum(item['byte_length'] for item in standalone_records) + sum(item['byte_length'] for item in plans) > max_bytes:
        raise ValueError('Complete eight startup attachments exceed max_bytes')
    # Fail before writing if either group destination aliases any original source.
    if any(Path(plan['path']).resolve() == source.resolve() for plan in plans for source in sources):
        raise ValueError('Startup reference destination cannot replace an original component')
    for plan in plans:
        _write_verified_reference(Path(plan['path']), plan.pop('_content'), max_bytes)
    physical_paths = [str(path) for path in separate] + [plan['path'] for plan in plans]
    hashes = {str(path): item['sha256'] for path, item in zip(separate, standalone_records)}
    hashes.update({plan['path']: plan['sha256'] for plan in plans})
    return {'paths': physical_paths, 'sha256_by_path': hashes,
            'component_manifest': [dict(item) for item in records], 'group_records': plans}


def read_bundle_components(path, record) -> dict[str, bytes]:
    """Recover and verify all original bytes using the recorded absolute offsets."""
    content = _read_bounded(Path(path), MAX_BUNDLE_BYTES)
    if _hash(content) != record.get('sha256'):
        raise ValueError('Reference bundle SHA-256 mismatch')
    start_marker = (MANIFEST_BEGIN + '\n```json\n').encode('utf-8')
    end_marker = ('\n```\n' + MANIFEST_END).encode('utf-8')
    try:
        start = content.index(start_marker) + len(start_marker)
        end = content.index(end_marker, start)
        embedded = json.loads(content[start:end].decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError('Reference bundle manifest is invalid') from error
    components = record.get('component_manifest')
    if not isinstance(components, list) or embedded != {'schema_version': '1.0', 'components': components}:
        raise ValueError('Recorded and embedded component manifests differ')
    _check_reference_names([item['name'] for item in components])
    recovered = {}
    for item in components:
        start, end = item.get('start_byte'), item.get('end_byte')
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(content):
            raise ValueError('Invalid component byte offsets')
        source = content[start:end]
        if len(source) != item.get('byte_length') or _hash(source) != item.get('sha256'):
            raise ValueError('Recovered component integrity mismatch: ' + item['name'])
        recovered[item['name']] = source
    return recovered
