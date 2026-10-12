import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from copilot_agent.local_navigation import (
    FilesystemAccessError, SessionNavigationGrant, SessionPathPolicy,
    filesystem_diagnostic,
)
from copilot_agent.policy import PathPolicy


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
