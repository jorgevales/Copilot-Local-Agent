import hashlib
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from copilot_agent.attachments import AttachmentQueue,AttachmentError,upload_name,TEXT_EXTENSIONS,SUPPORTED_EXTENSIONS,MAX_USER_FILES
from copilot_agent.policy import PolicyError


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='copilot_attachment_test_')).resolve()
        self.account=self.root/'account';self.account.mkdir()
        self.storage=self.account/'agent';self.storage.mkdir()
        self.config=SimpleNamespace(storage_dir=self.storage,profile_dir=self.storage/'runtime/profile',max_attachment_bytes=20*1024*1024,allowed_roots=[str(self.storage/'workspace')])
        self.queue=AttachmentQueue(self.config,account_root=self.account)

    def file(self,name,content='synthetic safe attachment',root=None):
        path=(root or self.account)/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content if isinstance(content,bytes) else content.encode('utf-8'))
        return path

    def test_selected_account_sources_queue_hash_and_remove_do_not_delete(self):
        outside_tools=self.file('documents/result.txt')
        code=self.file('sources/main.py',"print('not executed')\n")
        records=self.queue.add([outside_tools,code])
        self.assertEqual(len(records),2)
        self.assertEqual(records[0]['sha256'],hashlib.sha256(outside_tools.read_bytes()).hexdigest())
        self.assertEqual(records[1]['upload_name'],'main.py.txt')
        self.assertTrue(records[1]['requires_text_conversion'])
        self.assertEqual(self.config.allowed_roots,[str(self.storage/'workspace')])
        self.assertEqual(self.queue.paths(),[outside_tools,code])
        self.assertEqual(self.queue.verify(),records)
        records[0]['sha256']='untrusted mutation'
        self.assertNotEqual(self.queue.records()[0]['sha256'],'untrusted mutation')
        removed=self.queue.remove(1)
        self.assertEqual(removed['path'],str(outside_tools));self.assertTrue(outside_tools.exists())
        self.queue.clear();self.assertEqual(self.queue.paths(),[]);self.assertTrue(code.exists())

    def test_duplicate_paths_and_case_basename_upload_collisions(self):
        code=self.file('one/main.py');self.queue.add([code,code])
        self.assertEqual(len(self.queue.records()),1)
        for path in [self.file('two/main.py'),self.file('three/main.py.txt')]:
            with self.assertRaisesRegex(AttachmentError,'same filename'): self.queue.add([path])
        self.assertEqual(len(self.queue.records()),1)

    def test_add_transactional_on_later_failure_and_count_cap(self):
        initial=self.file('initial.txt');self.queue.add([initial])
        good=self.file('good.txt');bad=self.file('bad.exe',b'synthetic')
        with self.assertRaises(AttachmentError): self.queue.add([good,bad])
        self.assertEqual(self.queue.paths(),[initial])
        self.assertEqual(MAX_USER_FILES,10)
        paths=[self.file(f'safe{number}.txt') for number in range(MAX_USER_FILES)]
        with self.assertRaisesRegex(AttachmentError,str(MAX_USER_FILES)): self.queue.add(paths)
        self.assertEqual(self.queue.paths(),[initial])
        self.queue.add(paths[:MAX_USER_FILES-1]);self.assertEqual(len(self.queue.records()),MAX_USER_FILES)
        self.queue.add([initial]);self.assertEqual(len(self.queue.records()),MAX_USER_FILES)

    def test_zip_packages_disguises_and_native_office_container(self):
        memory=io.BytesIO()
        with zipfile.ZipFile(memory,'w') as archive: archive.writestr('result.txt','synthetic')
        for name in ['package.zip','disguised.txt','disguised.pdf','disguised.docx']:
            path=self.file(name,memory.getvalue())
            with self.assertRaises(AttachmentError): self.queue.add([path])
        office=io.BytesIO()
        with zipfile.ZipFile(office,'w') as archive:
            archive.writestr('[Content_Types].xml','synthetic container declaration')
            archive.writestr('word/document.xml','synthetic document part')
        native=self.file('user.docx',office.getvalue())
        self.queue.add([native]);self.assertEqual(self.queue.paths(),[native])

    def test_credentials_runtime_profile_and_outside_sources_rejected(self):
        for path in [self.file('runtime/events.txt',root=self.storage),self.file('runtime/profile/readme.txt',root=self.storage),self.file('Cookies'),self.file('.aws/config.txt'),self.file('Microsoft/Credentials/password.txt'),self.file('outside.txt',root=self.root)]:
            with self.assertRaises(AttachmentError): self.queue.add([path])
        self.assertEqual(self.queue.records(),[])
        for index,text in enumerate(['api_key = syntheticvalue','Bearer syntheticvalue','{"access_token":"syntheticvalue"}','-----BEGIN RSA PRIVATE KEY-----']):
            with self.assertRaises(AttachmentError): self.queue.add([self.file(f'secret{index}.txt',text)])

    def test_changed_bytes_missing_files_and_size_are_rejected(self):
        data=self.file('change.txt','first');self.queue.add([data])
        data.write_text('other',encoding='utf-8')
        with self.assertRaisesRegex(AttachmentError,'changed'): self.queue.verify()
        small=AttachmentQueue(SimpleNamespace(storage_dir=self.storage,max_attachment_bytes=3))
        with self.assertRaisesRegex(AttachmentError,'size limit'): small.add([self.file('big.txt','four',root=self.storage)])
        with self.assertRaises(AttachmentError): self.queue.add([self.account/'missing.txt'])
        with self.assertRaises(AttachmentError): self.queue.add([self.account])
        with self.assertRaises(AttachmentError): self.queue.add([self.file('invalid.txt',b'\xff')])
        with self.assertRaises(AttachmentError): self.queue.add([self.file('null.txt',b'safe\x00text')])

    def test_hardlinks_and_raw_redirection_are_denied(self):
        original=self.file('original.txt');alias=self.account/'alias.txt'
        try: os.link(original,alias)
        except OSError: self.skipTest('Hardlink creation unavailable')
        with self.assertRaises(AttachmentError): self.queue.add([alias])
        safe=self.file('safe.txt')
        with patch('copilot_agent.attachments.reject_path_redirection',side_effect=PolicyError('Synthetic junction')):
            with self.assertRaises(AttachmentError): self.queue.add([safe])

    def test_index_validation_fallback_and_upload_names(self):
        for index in [0,-1,1,True,'1']:
            with self.assertRaises(AttachmentError): self.queue.remove(index)
        default=AttachmentQueue(self.config);self.assertEqual(default.account_root,self.storage)
        fixture=AttachmentQueue({'allowed_roots':[str(self.account)]})
        self.assertEqual(fixture.account_root,self.account)
        self.assertEqual(upload_name('code.py'),'code.py.txt')
        self.assertEqual(upload_name('original.md'),'original.md')
        self.assertIn('.py',TEXT_EXTENSIONS);self.assertIn('.pdf',SUPPORTED_EXTENSIONS)
        with self.assertRaises(AttachmentError): self.queue.add(['S:relative.txt'])
