"""A pasted portable Node path finishes REA setup without further questions."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location(
    'setup_rea_interactive', Path(__file__).resolve().parents[1] / 'bootstrap' / 'setup_rea.py')
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class NodeSetupInteractiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.portable = self.root / 'portable node' / 'node-v24.13.0-win-x64'
        self.portable.mkdir(parents=True)
        self.node = self.portable / 'node.exe'
        self.node.write_bytes(b'fixture executable; subprocess is mocked')

    def ready_runtime(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        validate = stack.enter_context(patch.object(helper, 'validate_runtime', return_value=True))
        npm = stack.enter_context(patch.object(helper, 'find_npm'))
        archive = stack.enter_context(patch.object(helper, 'archive_bytes'))
        stack.enter_context(patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(
            returncode=0, stdout='v24.13.0\n', stderr='')))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        return validate, npm, archive

    def test_forced_prompt_persists_selected_node_and_finishes_without_network(self):
        settings = self.root / 'config.local.json'
        settings.write_text(json.dumps({'allowed_domains': ['example.test'], 'rea_timeout_seconds': 35}))
        validate, npm, archive = self.ready_runtime()
        answer = Mock(return_value=str(self.node))
        result = helper.provision(self.root, environ={}, prompt_for_node=True, input_fn=answer)
        self.assertTrue(result['available'])
        self.assertTrue(result['reused'])
        self.assertEqual(1, answer.call_count)
        saved = json.loads(settings.read_text(encoding='utf-8-sig'))
        self.assertEqual(str(self.node), saved['rea_node_executable'])
        self.assertEqual(['example.test'], saved['allowed_domains'])
        self.assertEqual(35, saved['rea_timeout_seconds'])
        self.assertEqual(str(self.node), validate.call_args.args[2]['COPILOT_REA_NODE'])
        npm.assert_not_called()
        archive.assert_not_called()

    def test_invalid_path_prompts_again_then_completes_with_one_valid_selection(self):
        self.ready_runtime()
        answer = Mock(side_effect=[str(self.root / 'missing' / 'node.exe'), str(self.node)])
        result = helper.provision(self.root, environ={}, prompt_for_node=True, input_fn=answer)
        self.assertTrue(result['available'])
        self.assertEqual(2, answer.call_count)
        settings = json.loads((self.root / 'config.local.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(str(self.node), settings['rea_node_executable'])

    def test_blank_prompt_stops_with_clear_failure_and_no_partial_configuration(self):
        _, npm, archive = self.ready_runtime()
        answer = Mock(return_value='')
        with patch.object(helper, 'find_node', side_effect=RuntimeError('No detected Node')):
            with self.assertRaisesRegex(RuntimeError, '(?i)node|skip|cancel'):
                helper.provision(self.root, environ={}, prompt_for_node=True, input_fn=answer)
        self.assertEqual(1, answer.call_count)
        self.assertFalse((self.root / 'config.local.json').exists())
        npm.assert_not_called()
        archive.assert_not_called()

    def test_explicit_quoted_portable_folder_resolves_native_executable_without_prompt(self):
        self.ready_runtime()
        answer = Mock(side_effect=AssertionError('Explicit Node paths must not prompt'))
        result = helper.provision(self.root, environ={}, node_path='"' + str(self.portable) + '"',
                                  input_fn=answer)
        self.assertTrue(result['available'])
        answer.assert_not_called()
        saved = json.loads((self.root / 'config.local.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(str(self.node), saved['rea_node_executable'])

    def test_explicit_config_is_updated_without_overwriting_default_config(self):
        self.ready_runtime()
        default = self.root / 'config.local.json'
        original = '{"rea_enabled": false}'
        default.write_text(original)
        selected = self.root / 'chosen.json'
        selected.write_text('{"rea_timeout_seconds": 40, "rea_enabled": true}')
        result = helper.provision(self.root, environ={}, config_path=selected, node_path=str(self.node))
        self.assertTrue(result['available'])
        saved = json.loads(selected.read_text(encoding='utf-8-sig'))
        self.assertEqual(str(self.node), saved['rea_node_executable'])
        self.assertEqual(40, saved['rea_timeout_seconds'])
        self.assertEqual(original, default.read_text())

    def test_noninteractive_missing_node_does_not_wait_for_input(self):
        self.ready_runtime()
        answer = Mock(side_effect=AssertionError('Noninteractive setup must not wait for input'))
        with patch.object(helper, 'find_node', side_effect=RuntimeError('Compatible native Node not found')):
            with self.assertRaisesRegex(RuntimeError, '(?i)node'):
                helper.provision(self.root, environ={}, prompt_for_node=False, input_fn=answer)
        answer.assert_not_called()

    def test_default_config_load_uses_the_persisted_node_selection(self):
        from copilot_agent import config
        self.ready_runtime()
        helper.provision(self.root, environ={}, node_path=str(self.node))
        with patch.object(config, 'PROJECT_ROOT', self.root), \
             patch.object(config, 'default_local_storage', return_value=self.root / 'storage'), \
             patch.object(config.Config, 'validate'):
            loaded = config.Config.load()
        self.assertEqual(str(self.node), loaded.rea_node_executable)


if __name__ == '__main__':
    unittest.main()
