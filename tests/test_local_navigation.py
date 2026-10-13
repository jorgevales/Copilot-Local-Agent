import asyncio
import errno
import hashlib
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from copilot_agent.local_navigation import (
    FilesystemAccessError, SessionNavigationGrant, SessionPathPolicy,
    filesystem_diagnostic,
)
from copilot_agent.policy import PathPolicy, PolicyError
from copilot_agent.tools import ToolRegistry, tool_path_policy


class LocalNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.allowed = self.root / 'configured'
        self.allowed.mkdir()
        self.other = self.root / 'other'
        self.other.mkdir()
        self.grant = SessionNavigationGrant()
        self.policy = SessionPathPolicy(PathPolicy([self.allowed]), self.grant)

    def test_confirmation_is_once_per_live_session_and_revocable(self):
        with self.assertRaises(FilesystemAccessError):
            self.policy.resolve(self.other)
        self.grant.confirm()
        for _ in range(3):
            self.assertEqual(self.policy.resolve(self.other, True), self.other.resolve())
        self.grant.revoke()
        with self.assertRaises(FilesystemAccessError):
            self.policy.resolve(self.other)
        self.assertFalse(SessionNavigationGrant().approved)

    def test_read_and_create_outside_old_configured_root(self):
        self.grant.confirm()
        target = self.policy.resolve(self.other / 'knowledge.txt')
        with target.open('x', encoding='utf-8') as stream:
            stream.write('verified example')
        self.assertEqual(self.policy.resolve(target, True).read_text(), 'verified example')

    def test_relative_path_uses_existing_configured_default(self):
        self.grant.confirm()
        self.assertEqual(self.policy.resolve('new.txt'), self.allowed.resolve() / 'new.txt')

    def test_isolated_proof_read_only_tools_use_only_the_bound_workspace(self):
        strict = PathPolicy([self.allowed])
        context = {
            'policy': strict,
            'local_navigation_grant': self.grant,
            'config': SimpleNamespace(_automation_test_mode=True),
        }
        for name in ('files.list', 'files.exists', 'files.metadata', 'files.read',
                     'files.hash', 'system.disk', 'files.transfer_to_copilot'):
            with self.subTest(tool=name):
                selected = tool_path_policy(name, context)
                self.assertIs(selected, strict)
                self.assertEqual(selected.resolve(self.allowed), self.allowed.resolve())
                with self.assertRaises(PolicyError):
                    selected.resolve(self.other, must_exist=True)

        # Proof-mode file operations stay inside the exact configured root.
        write_policy = tool_path_policy('files.create', context)
        self.assertIs(write_policy, strict)
        self.assertEqual(write_policy.resolve(self.allowed / 'new.txt'),
                         (self.allowed / 'new.txt').resolve())
        ordinary_context = {
            'policy': strict,
            'local_navigation_grant': self.grant,
            'config': SimpleNamespace(_automation_test_mode=False),
        }
        self.assertIsInstance(tool_path_policy('files.create', ordinary_context), SessionPathPolicy)
        self.assertFalse(self.grant.approved)
        self.assertEqual('user_approval', ToolRegistry().definition(
            'files.transfer_to_copilot')['approval_policy'])
        registry = ToolRegistry()
        evidence = self.allowed / 'evidence.txt'
        evidence.write_text('synthetic evidence', encoding='utf-8')
        transfer = {'files': [{'path': str(evidence),
                               'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}]}
        self.assertTrue(registry.validate_call('files.transfer_to_copilot', transfer, context)['valid'])
        outside_evidence = self.other / 'evidence.txt'
        outside_evidence.write_text('outside', encoding='utf-8')
        with self.assertRaises(PolicyError):
            registry.validate_call('files.transfer_to_copilot', {
                'files': [{'path': str(outside_evidence), 'sha256': '0' * 64}]}, context)

    def test_isolated_proof_file_creation_is_workspace_bound_and_still_approved(self):
        strict = PathPolicy([self.allowed])
        registry = ToolRegistry()
        context = {
            'policy': strict,
            'local_navigation_grant': self.grant,
            'config': SimpleNamespace(_automation_test_mode=True),
            'session_dir': str(self.allowed),
            'approved': False,
        }
        args = {'path': str(self.allowed / 'proof-output.txt'), 'text': 'locally verified'}

        denied = asyncio.run(registry.execute('files.create', args, context))
        self.assertFalse(denied['ok'])
        self.assertEqual(denied['error']['code'], 'policy_denied')
        self.assertFalse(Path(args['path']).exists())

        context['approved'] = True
        created = asyncio.run(registry.execute('files.create', args, context))
        self.assertTrue(created['ok'], created)
        self.assertEqual(Path(args['path']).read_text(encoding='utf-8'), 'locally verified')
        self.assertFalse(self.grant.approved)

        outside = self.other / 'escape.txt'
        escaped = asyncio.run(registry.execute('files.create', {
            'path': str(outside), 'text': 'outside proof root'}, context))
        self.assertFalse(escaped['ok'])
        self.assertEqual(escaped['error']['code'], 'policy_denied')
        self.assertFalse(outside.exists())

    def test_live_volume_is_probed_and_unavailable_is_actionable(self):
        self.grant.confirm()
        with patch('copilot_agent.local_navigation.os.name', 'nt'), patch.object(Path, 'stat', side_effect=FileNotFoundError('private location')):
            with self.assertRaises(FilesystemAccessError) as caught:
                self.policy.resolve(self.other)
        self.assertEqual(caught.exception.code, 'filesystem_location_unavailable')
        self.assertNotIn('private location', str(caught.exception))

    def test_permission_failure_preserves_os_boundary_without_filename(self):
        self.grant.confirm()
        with patch.object(Path, 'resolve', side_effect=PermissionError(errno.EACCES, 'denied', str(self.other))):
            with self.assertRaises(FilesystemAccessError) as caught:
                self.policy.resolve(self.other)
        self.assertEqual(caught.exception.code, 'filesystem_permission_denied')
        self.assertNotIn(str(self.other), str(caught.exception))

    def test_active_browser_profile_protection_remains(self):
        self.grant.confirm()
        self.policy.excluded_roots = (self.other.resolve(),)
        with self.assertRaises(FilesystemAccessError) as caught:
            self.policy.resolve(self.other / 'Cookies')
        self.assertEqual(caught.exception.code, 'filesystem_protected_profile')

    def test_ordinary_hardlink_navigation_is_allowed(self):
        self.grant.confirm()
        source = self.other / 'source.txt'
        source.write_text('same content')
        target = self.other / 'alias.txt'
        try:
            target.hardlink_to(source)
        except OSError:
            self.skipTest('Filesystem does not support hardlinks')
        self.assertEqual(self.policy.resolve(target, True).read_text(), 'same content')

    def test_error_categories_never_echo_private_paths(self):
        for error, code in [
            (FileNotFoundError('private'), 'filesystem_not_found'),
            (PermissionError('private'), 'filesystem_permission_denied'),
            (OSError(errno.ENOSPC, 'private'), 'filesystem_full'),
            (OSError(errno.EBUSY, 'private'), 'filesystem_locked'),
            (OSError(errno.ENETUNREACH, 'private'), 'filesystem_location_unavailable'),
        ]:
            with self.subTest(code=code):
                diagnostic = filesystem_diagnostic(error)
                self.assertEqual(diagnostic['code'], code)
                self.assertNotIn('private', diagnostic['message'])
