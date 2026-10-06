"""Picker options and cancellation contracts without opening desktop windows."""
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from copilot_agent.file_picker import FILE_TYPES, SUPPORTED_EXTENSIONS, select_files
from copilot_agent.attachments import SUPPORTED_EXTENSIONS as QUEUE_SUPPORTED_EXTENSIONS


class FilePickerTests(unittest.TestCase):
    def test_native_multiselect_options_and_initial_directory(self):
        backend = Mock(return_value=(str(Path.cwd() / 'one.py'), str(Path.cwd() / 'two.pdf')))
        result = select_files(Path.cwd(), picker_backend=backend)
        self.assertEqual(result,[Path.cwd() / 'one.py',Path.cwd() / 'two.pdf'])
        self.assertEqual(backend.call_args.kwargs,{
            'title':'Choose files to attach to Copilot', 'filetypes':FILE_TYPES,
            'multiple':True, 'initialdir':str(Path.cwd())})

    def test_default_directory_uses_native_default(self):
        backend = Mock(return_value=())
        self.assertEqual(select_files(picker_backend=backend),[])
        self.assertNotIn('initialdir',backend.call_args.kwargs)

    def test_cancellation_is_empty_without_fallback(self):
        for cancelled in ('', (), [], None):
            backend = Mock(return_value=cancelled)
            self.assertEqual(select_files(picker_backend=backend),[])
            backend.assert_called_once()

    def test_paths_deduplicated_in_first_selection_order(self):
        first = Path.cwd() / 'one.py'
        second = Path.cwd() / 'two.txt'
        backend = lambda **options:(str(first),str(second),str(first.parent / '.' / first.name),str(first))
        self.assertEqual(select_files(picker_backend=backend),[first,second])

    @unittest.skipUnless(os.name=='nt','Windows case-insensitive path aliases')
    def test_windows_case_aliases_deduplicated(self):
        path = Path.cwd() / 'One.PY'
        self.assertEqual(select_files(picker_backend=lambda **options:(str(path),str(path).upper())),[path])

    def test_zip_absent_from_all_filters_and_manual_zip_rejected(self):
        self.assertNotIn('.zip',SUPPORTED_EXTENSIONS)
        self.assertTrue(all('*.zip' not in pattern.lower() and pattern != '*' for _,pattern in FILE_TYPES))
        self.assertIn('.py',SUPPORTED_EXTENSIONS)
        self.assertIn('*.py',FILE_TYPES[0][1])
        for name in ('archive.zip','ARCHIVE.ZIP'):
            with self.assertRaisesRegex(RuntimeError,'ZIP archives cannot be attached'):
                select_files(picker_backend=lambda **options:[name])

    def test_picker_filters_match_attachment_queue_exactly(self):
        self.assertEqual(SUPPORTED_EXTENSIONS,QUEUE_SUPPORTED_EXTENSIONS)
        offered = {pattern[1:] for _,patterns in FILE_TYPES for pattern in patterns.split()}
        self.assertEqual(offered,QUEUE_SUPPORTED_EXTENSIONS)

    def test_backend_failure_is_clear_and_never_silent(self):
        backend = Mock(side_effect=OSError('GUI unavailable'))
        with self.assertRaisesRegex(RuntimeError,'file picker failed'):
            select_files(picker_backend=backend)
        backend.assert_called_once()

    def test_native_backend_unavailable_error_propagates(self):
        with patch('copilot_agent.file_picker._native_picker',side_effect=RuntimeError('native picker unavailable')):
            with self.assertRaisesRegex(RuntimeError,'native picker unavailable'):
                select_files()

    def test_invalid_selection_fails_explicitly(self):
        for value in ([None],['bad\x00path.py']):
            with self.assertRaisesRegex(RuntimeError,'invalid file selection'):
                select_files(picker_backend=lambda **options:value)


if __name__=='__main__':
    unittest.main()
