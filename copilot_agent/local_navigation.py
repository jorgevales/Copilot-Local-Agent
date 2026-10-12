"""Session-only local navigation authority and path-free filesystem diagnostics.

Normal user navigation follows filesystem links and live drive mappings. The
operating system and installed external safety controls remain authoritative.
The grant never authorizes execution or changes a tool's side-effect approval.
"""
from dataclasses import dataclass
import errno
import ntpath
import os
from pathlib import Path

from .policy import PathPolicy, PolicyError


class FilesystemAccessError(PolicyError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def filesystem_diagnostic(error):
    """Describe the failure without echoing OS exception filenames or paths."""
    if isinstance(error, FilesystemAccessError):
        return {'code': error.code, 'message': str(error)}
    winerror = getattr(error, 'winerror', None)
    if isinstance(error, PermissionError) or winerror == 5:
        return {'code': 'filesystem_permission_denied', 'message': 'The signed-in user or external safety control denied access. Check permissions for the selected location.'}
    if winerror in {15, 21, 53, 55, 64, 67, 1201, 1219, 1231, 2250} or getattr(error, 'errno', None) in {errno.ENODEV, errno.ENETUNREACH, errno.EHOSTUNREACH}:
        return {'code': 'filesystem_location_unavailable', 'message': 'The selected drive or network location is unavailable. Restore its mapping or connection in this user session and retry.'}
    if winerror in {32, 33} or getattr(error, 'errno', None) in {errno.EBUSY, errno.EAGAIN}:
        return {'code': 'filesystem_locked', 'message': 'Another process has locked the selected item. Release the lock or retry when it is available.'}
    if isinstance(error, FileNotFoundError):
        return {'code': 'filesystem_not_found', 'message': 'The selected item or parent does not exist. Refresh its parent listing and select an existing location.'}
    if isinstance(error, FileExistsError):
        return {'code': 'filesystem_already_exists', 'message': 'The destination already exists. Select a new destination; existing data was not replaced.'}
    if isinstance(error, NotADirectoryError):
        return {'code': 'filesystem_not_directory', 'message': 'A selected parent is a file. Select a directory and retry.'}
    if getattr(error, 'errno', None) == errno.ENOSPC:
        return {'code': 'filesystem_full', 'message': 'The selected storage has no available space. Free space or select another approved location.'}
    return {'code': 'filesystem_io_failed', 'message': 'Filesystem access failed. Check the selected location, connection, and user permissions before retrying.'}


@dataclass
class SessionNavigationGrant:
    """Fresh in-memory authority; restored run state never recreates consent."""
    approved: bool = False

    def confirm(self):
        self.approved = True

    def revoke(self):
        self.approved = False


class SessionPathPolicy(PathPolicy):
    def __init__(self, configured_policy, grant):
        # Retain configured default for relative paths and genuine profile
        # protection; do not cache a drive mapping across navigation calls.
        self.roots = configured_policy.roots
        self.excluded_roots = configured_policy.excluded_roots
        self.mapped_s_root = None
        self.grant = grant

    def resolve(self, path, must_exist=False):
        if self.grant.approved is not True:
            raise FilesystemAccessError('local_navigation_confirmation_required', 'Confirm local filesystem navigation once for this agent session.')
        if not isinstance(path, (str, Path)) or not str(path).strip():
            raise FilesystemAccessError('filesystem_invalid_path', 'Select a nonempty filesystem path.')
        value = str(path)
        if value.startswith(('\\\\?\\', '\\\\.\\')):
            raise FilesystemAccessError('filesystem_invalid_path', 'Select a normal filesystem location; device namespaces are not navigation targets.')
        raw = Path(value).expanduser()
        if not raw.is_absolute():
            if ntpath.splitdrive(value)[0]:
                raise FilesystemAccessError('filesystem_invalid_path', 'Use an absolute location for drive navigation.')
            raw = self.roots[0] / raw
        devices = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
        if any(':' in part or part.rstrip(' .').split('.')[0].upper() in devices for part in raw.parts[1:]):
            raise FilesystemAccessError('filesystem_invalid_path', 'Select a normal file or directory; alternate streams and device names are not navigation targets.')
        try:
            # Explicitly probe the live volume/share on every resolution. Do
            # not infer mapped-drive availability from configured roots.
            if os.name == 'nt':
                try:
                    Path(raw.anchor).stat()
                except FileNotFoundError as error:
                    raise FilesystemAccessError('filesystem_location_unavailable', 'The selected drive or share is unavailable in this user session. Restore its connection or mapping and retry.') from error
            resolved = raw.resolve(strict=must_exist)
            if any(resolved == root or root in resolved.parents for root in self.excluded_roots):
                raise FilesystemAccessError('filesystem_protected_profile', 'The active browser profile is protected. Select an ordinary user document location.')
            return resolved
        except OSError as error:
            diagnostic = filesystem_diagnostic(error)
            raise FilesystemAccessError(diagnostic['code'], diagnostic['message']) from error
