"""Bounded standard-library static artifact analysis; targets are never executed.

The caller owns approved input staging, aggregate bounds, cancellation, redaction
and persistence. This module returns structural evidence only, never raw strings.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
from urllib.parse import urlsplit

_MAX_BYTES = 20 * 1024 * 1024
_MAX_FILES = 2000
_MAX_ITEMS = 128
_SYMBOL = re.compile(r"^[A-Za-z_$<>][A-Za-z0-9_.$<>`:+-]{0,159}$")
_SENSITIVE = re.compile(r"(?i)(?:token|secret|password|credential|cookie|authorization|api[_-]?key)")
_KNOWN_PACKAGES = frozenset({'react', 'react-dom', 'next', 'vue', 'nuxt', 'angular', '@angular/core', 'express', 'koa', 'fastify', 'electron', 'axios', 'webpack', 'vite', 'svelte', 'jquery', 'lodash', 'typescript', 'react-router', 'react-router-dom'})
_ROUTE_WORDS = frozenset({'api', 'v1', 'v2', 'v3', 'v4', 'users', 'user', 'customers', 'customer', 'accounts', 'account', 'items', 'item', 'products', 'orders', 'order', 'search', 'health', 'status', 'login', 'logout', 'auth', 'oauth', 'token', 'session', 'sessions', 'admin', 'settings', 'config', 'graphql', 'rest', 'assets', 'static', 'public', 'private', 'index', 'home', 'dashboard', 'reports', 'report', 'files', 'file', 'download', 'upload', 'documents', 'document'})


def _check(budget):
    if budget is not None:
        budget()


def _symbol(value):
    return value if _SYMBOL.fullmatch(value or '') and not _SENSITIVE.search(value) else None


def _digest(value):
    return hashlib.sha256(value.encode('utf-8', 'replace')).hexdigest()[:16]


def _route(value):
    """A route shape, never an origin, query, identifier, or credential value."""
    if '\\' in value or len(value) > 4096:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme and parsed.scheme not in ('http', 'https', 'ws', 'wss'):
            return None
        path = parsed.path
    except ValueError:
        return None
    if not path.startswith('/'):
        return None
    parts = [p for p in path.split('/') if p]
    if len(parts) > 24:
        return None
    return '/' + '/'.join(p.lower() if p.lower() in _ROUTE_WORDS else ':segment' for p in parts)


def _binary_metadata(data):
    result = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'format': 'unknown'}
    if data.startswith(b'MZ'):
        result['format'] = 'pe'
        try:
            pe = struct.unpack_from('<I', data, 0x3c)[0]
            if data[pe:pe + 4] == b'PE\0\0':
                machine, sections = struct.unpack_from('<HH', data, pe + 4)
                result.update(machine={0x14c: 'x86', 0x8664: 'x64', 0xaa64: 'arm64'}.get(machine, 'other'), sections=sections)
        except (struct.error, IndexError):
            result['header_incomplete'] = True
    elif data.startswith(b'\x7fELF'):
        result.update(format='elf', bits={1: 32, 2: 64}.get(data[4] if len(data) > 4 else 0, 0))
    elif data[:4] in (b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe'):
        result['format'] = 'macho'
    return result


def _strings(data, budget):
    # Iterate; never return the binary's arbitrary string pool.
    for i, match in enumerate(re.finditer(rb'[\t\x20-\x7e]{6,1024}', data)):
        if i % 128 == 0:
            _check(budget)
        yield match.start(), match.group().decode('ascii')


def _javascript(files, budget):
    findings = {'inventory': [], 'imports': [], 'exports': [], 'route_templates': [], 'frameworks': [], 'build_indicators': [], 'source_maps': []}
    imports, exports, routes, frameworks, builds = set(), set(), set(), set(), set()
    unknowns = []
    total = 0
    # Conservative tokenizer separates comments, quoted literals and identifiers.
    token = re.compile(r'(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|(?P<string>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`)|(?P<word>[A-Za-z_$][A-Za-z0-9_$]*)|(?P<punct>[^\s])')
    for index, path in enumerate(files):
        _check(budget)
        data = path.read_bytes()
        total += len(data)
        if total > _MAX_BYTES:
            raise ValueError('Artifact exceeds the static analysis input limit')
        location = 'file:' + str(index)
        findings['inventory'].append({'location': location, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'kind': 'source_map' if path.suffix.lower() == '.map' else 'javascript' if path.suffix.lower() in ('.js', '.mjs', '.cjs', '.jsx', '.ts', '.tsx') else 'other'})
        if path.suffix.lower() == '.map':
            try:
                value = json.loads(data)
                if not isinstance(value, dict) or value.get('version') != 3:
                    raise ValueError('Unsupported source map')
                sources = value.get('sources', [])
                names = value.get('names', [])
                if not isinstance(sources, list) or not isinstance(names, list):
                    raise ValueError('Malformed source map')
                findings['source_maps'].append({'location': location, 'version': 3, 'sources_count': len(sources), 'names_count': len(names), 'has_embedded_sources': bool(value.get('sourcesContent')), 'mappings_characters': len(value.get('mappings', '')) if isinstance(value.get('mappings'), str) else 0})
            except (ValueError, UnicodeError):
                unknowns.append({'location': location, 'reason': 'Source map is malformed or unsupported'})
            continue
        if path.name in ('package.json', 'webpack.config.js', 'vite.config.js', 'vite.config.ts', 'tsconfig.json', 'next.config.js', 'next.config.mjs'):
            builds.add(path.name)
        if path.name == 'package.json':
            try:
                package = json.loads(data)
                for field in ('dependencies', 'devDependencies', 'peerDependencies'):
                    dependencies = package.get(field, {}) if isinstance(package, dict) else {}
                    if isinstance(dependencies, dict):
                        frameworks.update(name for name in dependencies if name in _KNOWN_PACKAGES)
            except (ValueError, UnicodeError):
                unknowns.append({'location': location, 'reason': 'Package metadata is unreadable'})
            continue
        if path.suffix.lower() not in ('.js', '.mjs', '.cjs', '.jsx', '.ts', '.tsx'):
            continue
        source = data.decode('utf-8', 'replace')
        previous = []
        count = 0
        for match in token.finditer(source):
            count += 1
            if count % 512 == 0:
                _check(budget)
            if match.lastgroup == 'comment':
                if 'sourceMappingURL=' in match.group():
                    builds.add('sourceMappingURL_reference')
                continue
            current = match.group()
            if match.lastgroup == 'string':
                literal = current[1:-1]
                # Escaped/dynamic literals are not decoded or treated as exact values.
                if '\\' not in literal and '${' not in literal:
                    if previous and (previous[-1] in ('from', 'import') or (len(previous) > 1 and previous[-2:] in (['require', '('], ['import', '(']))):
                        source_kind = 'relative' if literal.startswith('.') else 'package' if not literal.startswith(('/', 'http:', 'https:')) else 'other'
                        module = literal if literal in _KNOWN_PACKAGES else 'sha256:' + _digest(literal)
                        imports.add((module, source_kind, location))
                        if literal in _KNOWN_PACKAGES:
                            frameworks.add(literal)
                    # Only route-bearing calls/assignments, not arbitrary strings.
                    if any(word in ('fetch', 'route', 'get', 'post', 'put', 'patch', 'delete', 'url', 'path', 'endpoint') for word in previous[-5:]):
                        route = _route(literal)
                        if route:
                            routes.add((route, location))
            if match.lastgroup == 'word' and len(previous) >= 1:
                if previous[-1] == 'export' and current == 'default':
                    exports.add(('default', location))
                if len(previous) >= 2 and previous[-2:] == ['exports', '.']:
                    symbol = _symbol(current)
                    if symbol:
                        exports.add((symbol, location))
                if previous[-1] == 'export' and current not in ('default', 'const', 'let', 'var', 'function', 'class', 'async'):
                    symbol = _symbol(current)
                    if symbol:
                        exports.add((symbol, location))
                if len(previous) >= 2 and previous[-2] == 'export' and previous[-1] in ('function', 'class', 'const', 'let', 'var'):
                    symbol = _symbol(current)
                    if symbol:
                        exports.add((symbol, location))
            previous = (previous + [current])[-6:]
        if count > 500000:
            unknowns.append({'location': location, 'reason': 'Large token inventory; only bounded finding lists retained'})
    if not any(item['kind'] in ('javascript', 'source_map') for item in findings['inventory']):
        unknowns.append('No supported JavaScript source or source-map files were observed; binary bundles require a dedicated archive reader.')
    findings['imports'] = [{'module': a, 'source_kind': b, 'location': c} for a, b, c in sorted(imports)[:_MAX_ITEMS]]
    findings['exports'] = [{'name': a, 'location': b} for a, b in sorted(exports)[:_MAX_ITEMS]]
    findings['route_templates'] = [{'route': a, 'location': b} for a, b in sorted(routes)[:_MAX_ITEMS]]
    findings['frameworks'] = sorted(frameworks)
    findings['build_indicators'] = sorted(builds)
    findings['inventory'] = findings['inventory'][:_MAX_FILES]
    findings['truncated_findings'] = max(0, len(imports) - _MAX_ITEMS) + max(0, len(exports) - _MAX_ITEMS) + max(0, len(routes) - _MAX_ITEMS)
    return {'status': 'partial', 'findings': findings, 'confidence': 'derived', 'unknowns': unknowns, 'limitations': ['Conservative tokenizer; no JavaScript execution, complete AST, data flow, dynamic imports resolution or bundled-code deobfuscation.', 'Source maps are summarized in place; source paths and embedded source contents are never followed or emitted.', 'Unknown module names are hashed; endpoint identifiers, hosts, query strings and fragments are omitted.'], 'locations': [item['location'] for item in findings['inventory']]}


# ECMA-335 II.22 metadata table column schemas. Integers are fixed byte widths,
# tuples are table-index references, and coded indexes list tag bits and tables.
_CODED = {
 'ResolutionScope': (2, (0, 26, 35, 1)), 'TypeDefOrRef': (2, (2, 1, 27)),
 'HasConstant': (2, (4, 8, 23)), 'HasCustomAttribute': (5, (6, 4, 1, 2, 8, 9, 10, 0, 14, 23, 20, 17, 26, 27, 32, 35, 38, 39, 40, 42, 44)),
 'HasFieldMarshal': (1, (4, 8)), 'HasDeclSecurity': (2, (2, 6, 32)), 'MemberRefParent': (3, (2, 1, 26, 6, 27)),
 'HasSemantics': (1, (20, 23)), 'MethodDefOrRef': (1, (6, 10)), 'MemberForwarded': (1, (4, 6)),
 'Implementation': (2, (38, 35, 39)), 'CustomAttributeType': (3, (6, 10)), 'TypeOrMethodDef': (1, (2, 6)),
}
_TABLES = {
0: (2,'s','g','g','g'), 1: ('ResolutionScope','s','s'), 2:(4,'s','s','TypeDefOrRef',(4,),(6,)),
3:((4,),),4:(2,'s','b'),5:((6,),),6:(4,2,2,'s','b',(8,)),7:((8,),),8:(2,2,'s'),
9:((2,),'TypeDefOrRef'),10:('MemberRefParent','s','b'),11:(2,'HasConstant','b'),12:('HasCustomAttribute','CustomAttributeType','b'),13:('HasFieldMarshal','b'),14:(2,'HasDeclSecurity','b'),15:(2,4,(2,)),16:(4,(4,)),17:('b',),18:((2,),(20,)),19:((20,),),20:(2,'s','TypeDefOrRef'),21:((2,),(23,)),22:((23,),),23:(2,'s','b'),24:(2,(6,),'HasSemantics'),25:((2,),'MethodDefOrRef','MethodDefOrRef'),26:('s',),27:('b',),28:(2,'MemberForwarded','s',(26,)),29:(4,(4,)),30:(4,4),31:(4,),32:(4,2,2,2,2,4,'b','s','s'),33:(4,),34:(4,4,4),35:(2,2,2,2,4,'b','s','s','b'),36:(4,(35,)),37:(4,4,4,(35,)),38:(4,'s','b'),39:(4,4,'s','s','Implementation'),40:(4,4,'s','Implementation'),41:((2,),(2,)),42:(2,2,'TypeOrMethodDef','s'),43:('MethodDefOrRef','b'),44:((42,),'TypeDefOrRef')}


def _managed(data, budget):
    findings = {'file': _binary_metadata(data), 'assembly_references': [], 'assemblies': [], 'namespaces': [], 'types': [], 'methods': [], 'metadata_tables': {}}
    locations = []
    try:
        if data[:2] != b'MZ':
            raise ValueError('Input is not a PE image')
        pe = struct.unpack_from('<I', data, 0x3c)[0]
        if data[pe:pe+4] != b'PE\0\0':
            raise ValueError('PE signature is invalid')
        sections, optional_size = struct.unpack_from('<H', data, pe+6)[0], struct.unpack_from('<H', data, pe+20)[0]
        if sections > 96:
            raise ValueError('PE section count exceeds the supported limit')
        opt = pe + 24
        magic = struct.unpack_from('<H', data, opt)[0]
        directory = opt + (96 if magic == 0x10b else 112 if magic == 0x20b else 0)
        if directory == opt:
            raise ValueError('Unsupported PE optional header')
        cli_rva = struct.unpack_from('<I', data, directory + 14*8)[0]
        section_start = opt + optional_size
        def offset(rva):
            for n in range(sections):
                base = section_start + 40*n
                virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from('<IIII', data, base+8)
                if virtual_address <= rva < virtual_address + max(virtual_size, raw_size):
                    delta = rva - virtual_address
                    if delta >= raw_size or raw_pointer + delta >= len(data):
                        raise ValueError('Metadata RVA exceeds retained image bytes')
                    return raw_pointer + delta
            raise ValueError('Metadata RVA has no file-backed section')
        cli = offset(cli_rva)
        metadata_rva, metadata_size = struct.unpack_from('<II', data, cli+8)
        root = offset(metadata_rva)
        if metadata_size > len(data) - root or data[root:root+4] != b'BSJB':
            raise ValueError('CLI metadata root is malformed')
        end = root + metadata_size
        version_size = struct.unpack_from('<I', data, root+12)[0]
        cursor = root + ((16 + version_size + 3) & ~3)
        stream_count = struct.unpack_from('<H', data, cursor+2)[0]
        cursor += 4
        if stream_count > 32:
            raise ValueError('CLI stream count exceeds the supported limit')
        streams = {}
        for _ in range(stream_count):
            relative, size = struct.unpack_from('<II', data, cursor)
            name_end = data.find(b'\0', cursor+8, min(cursor+40, end))
            if name_end < 0:
                raise ValueError('Unterminated metadata stream name')
            name = data[cursor+8:name_end].decode('ascii')
            cursor = (name_end + 4) & ~3
            start = root + relative
            if start < root or start + size > end or name in streams:
                raise ValueError('Metadata stream bounds are invalid')
            streams[name] = (start, size)
        table_start, table_size = streams.get('#~', streams.get('#-', (0,0)))
        string_start, string_size = streams.get('#Strings', (0,0))
        if not table_start or table_size < 24 or not string_start:
            raise ValueError('Required CLI metadata streams are missing')
        heaps = data[table_start+6]
        valid = struct.unpack_from('<Q', data, table_start+8)[0]
        cursor = table_start + 24
        rows = {}
        for table in range(64):
            if valid & (1 << table):
                rows[table] = struct.unpack_from('<I', data, cursor)[0]
                cursor += 4
        def width(column):
            if isinstance(column, int): return column
            if isinstance(column, tuple): return 4 if rows.get(column[0], 0) >= 65536 else 2
            if column in ('s', 'g', 'b'):
                return 4 if heaps & {'s':1,'g':2,'b':4}[column] else 2
            bits, targets = _CODED[column]
            return 4 if max((rows.get(t,0) for t in targets), default=0) >= (1 << (16-bits)) else 2
        def text(index):
            if not 0 < index < string_size:
                return None
            position = string_start + index
            stop = data.find(b'\0', position, min(position+161, string_start+string_size))
            if stop < 0: return None
            return _symbol(data[position:stop].decode('utf-8', 'replace'))
        namespaces = set()
        for table, count in sorted(rows.items()):
            _check(budget)
            if table not in _TABLES:
                raise ValueError('Unsupported CLI metadata table')
            widths = [width(c) for c in _TABLES[table]]
            row_size = sum(widths)
            table_end = cursor + count*row_size
            if table_end > table_start+table_size:
                raise ValueError('CLI table exceeds its metadata stream')
            findings['metadata_tables'][str(table)] = count
            if table in (1, 2, 6, 32, 35) and count > _MAX_ITEMS:
                findings['metadata_rows_omitted'] = findings.get('metadata_rows_omitted', 0) + count - _MAX_ITEMS
            if table in (1,2,6,32,35):
                for row in range(min(count, _MAX_ITEMS)):
                    _check(budget)
                    values, position = [], cursor + row*row_size
                    for size in widths:
                        values.append(int.from_bytes(data[position:position+size], 'little'))
                        position += size
                    location = f'file:0#metadata-table:{table}/row:{row+1}'
                    if table == 2:
                        name, namespace = text(values[1]), text(values[2])
                        if name:
                            findings['types'].append({'name':name, 'namespace':namespace, 'location':location})
                        if namespace: namespaces.add(namespace)
                    elif table == 6:
                        name = text(values[3])
                        if name: findings['methods'].append({'name':name, 'location':location})
                    elif table in (32,35):
                        index = 7 if table == 32 else 6
                        name = text(values[index])
                        if name:
                            findings['assemblies' if table==32 else 'assembly_references'].append({'name':name,'location':location})
                    locations.append(location)
            cursor = table_end
        findings['namespaces'] = sorted(namespaces)[:_MAX_ITEMS]
        return {'status':'partial','findings':findings,'confidence':'observed','unknowns':['Method bodies, external dependencies and runtime behavior were not analyzed.'],'limitations':['Bounded ECMA-335 metadata inspection only; no execution or deep decompilation.','Symbol names with sensitive markers or unsupported characters are omitted.'],'locations':locations[:_MAX_ITEMS*4]}
    except (ValueError, struct.error, IndexError, UnicodeError) as error:
        return {'status':'partial','findings':findings,'confidence':'observed','unknowns':[str(error) if isinstance(error, ValueError) else 'PE/CLI metadata is truncated or malformed.'],'limitations':['Only safely readable static file and metadata evidence is returned; no execution or deep decompilation.'],'locations':locations[:_MAX_ITEMS*4]}


def _native(data, kind, budget):
    findings = {'file': _binary_metadata(data), 'indicators': [], 'modules': [], 'packages': [], 'string_evidence': {'scanned_printable_strings':0, 'retained_raw_strings':0}}
    locations = []
    modules, packages = set(), set()
    counters = Counter()
    if kind == 'go':
        marker = data.find(b'\xff Go buildinf:')
        if marker >= 0:
            findings['indicators'].append({'kind':'go_build_info_header','location':f'file:0#offset:{marker}'})
            if marker+32 <= len(data):
                findings['build_info'] = {'pointer_size':data[marker+14], 'inline_strings':bool(data[marker+15]&2), 'big_endian':bool(data[marker+15]&1)}
        if b'Go build ID:' in data:
            counters['build_id_marker'] += 1
    for position, value in _strings(data, budget):
        findings['string_evidence']['scanned_printable_strings'] += 1
        if kind == 'go':
            for version in re.findall(r'\bgo(1\.[0-9]{1,3}(?:\.[0-9]{1,3})?)\b', value):
                findings.setdefault('go_versions', [])
                if version not in findings['go_versions'] and len(findings['go_versions']) < 8:
                    findings['go_versions'].append(version)
            if '\tmod\t' in value or value.startswith('mod\t'):
                counters['module_record'] += 1
            if 'runtime.' in value:
                counters['runtime_symbol'] += 1
            if 'go.buildid' in value:
                counters['build_id_section'] += 1
            # Only standard-library package evidence is disclosed. Nonstandard
            # package/module strings get irreversible structural fingerprints.
            for package in re.findall(r'(?<![A-Za-z0-9_])((?:net/http|crypto/tls|encoding/json|database/sql|runtime|reflect|context|sync|fmt|os|strings|bytes))(?:[./][A-Za-z_][A-Za-z0-9_]*)?', value):
                packages.add(package)
            if value.startswith(('path\t','mod\t','dep\t')):
                fields = value.split('\t')
                if len(fields)>1 and fields[1] and len(modules)<_MAX_ITEMS:
                    modules.add(_digest(fields[1]))
        else:
            for indicator, needle in (('rust_panic','panicked at'),('rust_panic','rust_begin_unwind'),('rust_std','std::'),('rust_core','core::'),('rust_alloc','alloc::'),('cargo_registry_path','registry/src/'),('cargo_registry_path','registry\\src\\'),('rust_source_path','.rs:')):
                if needle in value:
                    counters[indicator] += 1
                    if len(locations)<_MAX_ITEMS:
                        locations.append(f'file:0#offset:{position}')
            # Recognize standard crate families only; arbitrary symbol/string
            # contents can include customer or build-machine identifiers.
            for crate in ('std','core','alloc','tokio','serde','serde_json','reqwest','hyper','clap'):
                if re.search(r'(?<![A-Za-z0-9_])'+crate+r'(?:::|-[0-9a-f]{6,}|/[0-9])', value):
                    packages.add(crate)
            for version in re.findall(r'\brustc (1\.[0-9]{1,3}\.[0-9]{1,3})\b',value):
                findings.setdefault('rustc_versions', [])
                if version not in findings['rustc_versions'] and len(findings['rustc_versions'])<8:
                    findings['rustc_versions'].append(version)
    findings['indicators'].extend({'kind':name,'count':count} for name,count in sorted(counters.items()))
    findings['modules'] = [{'identity_sha256_prefix':identity} for identity in sorted(modules)]
    findings['packages'] = sorted(packages)[:_MAX_ITEMS]
    return {'status':'partial','findings':findings,'confidence':'derived','unknowns':['Compiler/linker stripping may remove evidence; absent markers do not prove a different source language.','Machine-code control flow, complete dependency versions and runtime behavior were not analyzed.'],'limitations':['Bounded static executable headers and recognized compiler/package markers only; no target execution or deep decompilation.','Arbitrary binary strings, build paths, module identifiers and panic messages are never returned.'],'locations':locations}


def analyze_artifact(path: Path, kind: str, budget=None) -> dict:
    """Analyze a staged approved artifact without executing or modifying it."""
    path = Path(path)
    if kind not in ('javascript','managed','go','rust'):
        raise ValueError('Unsupported static artifact kind')
    _check(budget)
    if path.is_symlink():
        raise ValueError('Linked artifacts are not supported')
    if path.is_dir():
        if kind != 'javascript':
            raise ValueError('This artifact kind requires a regular file')
        files = []
        total = 0
        entries = 0
        for child in path.rglob('*'):
            _check(budget)
            entries += 1
            if entries > _MAX_FILES:
                raise ValueError('Artifact tree exceeds the entry limit')
            if child.is_symlink():
                raise ValueError('Linked source-tree members are not supported')
            if child.is_file():
                files.append(child)
                if len(files)>_MAX_FILES:
                    raise ValueError('Artifact tree exceeds the file limit')
                total += child.stat().st_size
                if total>_MAX_BYTES:
                    raise ValueError('Artifact tree exceeds the input limit')
        files.sort(key=lambda item:item.relative_to(path).as_posix())
    else:
        if not path.is_file():
            raise ValueError('Artifact is not a regular file')
        if path.stat().st_size>_MAX_BYTES:
            raise ValueError('Artifact exceeds the input limit')
        files = [path]
    if kind == 'javascript':
        return _javascript(files,budget)
    data = path.read_bytes()
    if len(data)>_MAX_BYTES:
        raise ValueError('Artifact exceeds the input limit')
    _check(budget)
    return _managed(data,budget) if kind=='managed' else _native(data,kind,budget)
