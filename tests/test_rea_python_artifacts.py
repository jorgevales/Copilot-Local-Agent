"""Synthetic passive artifact coverage for the Python REA backend."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from copilot_agent.rea_python_artifacts import analyze_artifact


def managed_fixture():
    image = bytearray(4096)
    image[:2] = b'MZ'
    struct.pack_into('<I', image, 0x3c, 0x80)
    image[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', image, 0x84, 0x8664, 1)
    struct.pack_into('<H', image, 0x94, 240)
    struct.pack_into('<H', image, 0x98, 0x20b)
    struct.pack_into('<II', image, 0x98+112+14*8, 0x2000, 72)
    # One section: RVA 0x2000 at file offset 0x200.
    struct.pack_into('<IIII', image, 0x188+8, 0x1000, 0x2000, 0xe00, 0x200)
    struct.pack_into('<I', image, 0x200, 72)
    root = 0x280
    struct.pack_into('<II', image, 0x208, 0x2080, 0x500)
    image[root:root+4] = b'BSJB'
    struct.pack_into('<I', image, root+12, 4)
    image[root+16:root+20] = b'v4\0\0'
    struct.pack_into('<HH', image, root+20, 0, 2)
    struct.pack_into('<II', image, root+24, 0x80, 0x100)
    image[root+32:root+36] = b'#~\0\0'
    struct.pack_into('<II', image, root+36, 0x180, 0x100)
    image[root+44:root+56] = b'#Strings\0\0\0\0'
    table = root+0x80
    struct.pack_into('<Q', image, table+8, (1<<2)|(1<<6)|(1<<35))
    struct.pack_into('<III', image, table+24, 1, 1, 1)
    names = b'\0SampleType\0Example.App\0Run\0System.Runtime\0'
    image[root+0x180:root+0x180+len(names)] = names
    row = table+36
    struct.pack_into('<IHHHHH', image, row, 1, 1, 12, 0, 1, 1)
    row += 14
    struct.pack_into('<IHHHHH', image, row, 0, 0, 0, 24, 0, 1)
    row += 14
    struct.pack_into('<HHHHIHHHH', image, row, 1, 0, 0, 0, 0, 0, 28, 0, 0)
    return bytes(image)


class PythonArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def analyze(self, data, kind, name='artifact.bin'):
        path = self.root/name
        path.write_bytes(data)
        with patch('subprocess.Popen', side_effect=AssertionError('Target execution forbidden')):
            return analyze_artifact(path, kind)

    def test_javascript_import_exports_routes_and_safe_map(self):
        (self.root/'app.js').write_text('import React from "react"; export function load() { return fetch("https://example.invalid/api/users/123?token=TOPSECRET#secret"); } const password="PRIVATEVALUE"; //# sourceMappingURL=app.js.map', encoding='utf-8')
        (self.root/'app.js.map').write_text(json.dumps({'version':3,'sources':['C:\\private\\customer.js'],'names':['PRIVATEVALUE'],'sourcesContent':['token=TOPSECRET'],'mappings':'AAAA'}),encoding='utf-8')
        result = analyze_artifact(self.root,'javascript')
        findings = result['findings']
        self.assertEqual(findings['imports'][0]['module'],'react')
        self.assertEqual(findings['exports'][0]['name'],'load')
        self.assertEqual(findings['route_templates'][0]['route'],'/api/users/:segment')
        self.assertTrue(findings['source_maps'][0]['has_embedded_sources'])
        self.assertEqual(str(self.root/'app.js'), findings['inventory'][0]['path'])
        self.assertEqual(['C:\\private\\customer.js'], findings['source_maps'][0]['sources'])
        output = json.dumps(result)
        for private in ('TOPSECRET','PRIVATEVALUE','example.invalid','?token='):
            self.assertNotIn(private,output)
        self.assertEqual(result['status'],'partial')

    def test_source_map_coordinates_are_bounded_metadata_never_followed(self):
        source = 'https://user:password@example.invalid/private/app.ts?token=TOPSECRET#fragment'
        path = self.root/'app.js.map'
        path.write_text(json.dumps({'version':3,'sourceRoot':'S:\\Company\\Sources',
            'sources':[source] * 130,'names':[],'sourcesContent':['PRIVATEVALUE'],'mappings':''}),
            encoding='utf-8')
        result = analyze_artifact(path,'javascript')
        evidence = result['findings']['source_maps'][0]
        self.assertEqual('S:\\Company\\Sources', evidence['source_root'])
        self.assertEqual(128, len(evidence['sources']))
        self.assertEqual(2, evidence['sources_truncated'])
        self.assertEqual('https://example.invalid/private/app.ts', evidence['sources'][0])
        for secret in ('TOPSECRET', 'PRIVATEVALUE', 'user:password'):
            self.assertNotIn(secret, json.dumps(result))

    def test_unknown_import_hashed_and_dynamic_route_not_claimed(self):
        result=self.analyze(b'import x from "./customers/jane@example.invalid.js"; fetch(`/users/${id}`);','javascript','app.js')
        self.assertTrue(result['findings']['imports'][0]['module'].startswith('sha256:'))
        self.assertEqual(result['findings']['route_templates'],[])
        self.assertNotIn('jane',json.dumps(result))

    def test_managed_pe_cli_metadata_is_read(self):
        result=self.analyze(managed_fixture(),'managed')
        findings=result['findings']
        self.assertEqual(findings['file']['format'],'pe')
        self.assertEqual(findings['types'][0]['name'],'SampleType')
        self.assertEqual(findings['namespaces'],['Example.App'])
        self.assertEqual(findings['methods'][0]['name'],'Run')
        self.assertEqual(findings['assembly_references'][0]['name'],'System.Runtime')

    def test_malformed_managed_retains_useful_file_evidence(self):
        result=self.analyze(b'MZ'+b'\0'*100,'managed')
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['findings']['file']['format'],'pe')
        self.assertTrue(result['unknowns'])

    def test_go_build_and_stdlib_metadata_not_raw_strings(self):
        data=b'\x7fELF\x02'+b'\0'*16+b'\xff Go buildinf:'+bytes([8,2])+b'\0'*16+b'go1.24.2\0net/http.Client\0mod\texample.invalid/private/customer\tv1.0\0PRIVATEVALUE\0C:\\private\\build'
        result=self.analyze(data,'go')
        self.assertEqual(result['findings']['file']['format'],'elf')
        self.assertIn('1.24.2',result['findings']['go_versions'])
        self.assertIn('net/http',result['findings']['packages'])
        self.assertTrue(result['findings']['modules'])
        self.assertNotIn('customer',json.dumps(result))
        self.assertNotIn('PRIVATEVALUE',json.dumps(result))

    def test_rust_static_indicators_and_no_panic_payload(self):
        data=b'\x7fELF\x02\0panicked at PRIVATEVALUE\0C:\\private\\registry\\src\\tokio-abcdef1234\\src\\lib.rs:22\0std::panic::run\0rustc 1.80.0\0'
        result=self.analyze(data,'rust')
        self.assertIn('rust_panic',[item['kind'] for item in result['findings']['indicators']])
        self.assertIn('tokio',result['findings']['packages'])
        self.assertNotIn('PRIVATEVALUE',json.dumps(result))
        self.assertNotIn('C:\\private',json.dumps(result))

    def test_budget_callback_stops_analysis(self):
        path=self.root/'app.js'
        path.write_text('export const a=1;')
        with self.assertRaises(TimeoutError):
            analyze_artifact(path,'javascript',budget=lambda:(_ for _ in ()).throw(TimeoutError()))

    def test_unsupported_kind_and_tree_kinds_rejected(self):
        with self.assertRaises(ValueError): analyze_artifact(self.root,'unknown')
        with self.assertRaises(ValueError): analyze_artifact(self.root,'managed')

    def test_file_limit_enforced_before_unbounded_inventory(self):
        path=self.root/'app.js'
        path.write_bytes(b'x'*32)
        with patch('copilot_agent.rea_python_artifacts._MAX_BYTES',16):
            with self.assertRaises(ValueError): analyze_artifact(path,'javascript')

    def test_source_map_outside_paths_never_followed(self):
        result=self.analyze(json.dumps({'version':3,'sources':['../../outside.js'],'sourcesContent':['PRIVATEVALUE'],'names':[],'mappings':''}).encode(),'javascript','source.map')
        self.assertEqual(result['findings']['source_maps'][0]['sources_count'],1)
        self.assertEqual(['../../outside.js'], result['findings']['source_maps'][0]['sources'])
        self.assertNotIn('PRIVATEVALUE',json.dumps(result))


if __name__=='__main__': unittest.main()
