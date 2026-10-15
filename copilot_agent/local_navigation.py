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


def prepare_session_path_extension(args, context):
    """Validate one reachable user-selected file or directory before approval."""
    base = context.get('path_policy')
    state = context.get('session_state')
    if not isinstance(base, PathPolicy) or state is None:
        raise PolicyError('A current agent session and configured file policy are required')
    if not isinstance(args.get('reason'), str) or not args['reason'].strip():
        raise PolicyError('A user-provided reason is required for the requested path extension')
    candidate = Path(args['path']).expanduser()
    if not candidate.is_absolute():
        raise PolicyError('A path extension requires an absolute existing location')
    probe = PathPolicy([candidate], excluded_roots=base.excluded_roots,
                       mapped_s_root=base.mapped_s_root)
    resolved = probe.resolve(candidate, must_exist=True)
    if resolved == Path(resolved.anchor):
        raise PolicyError('Drive or share roots cannot be granted as file access extensions')
    if any(resolved == excluded or resolved in excluded.parents
           for excluded in base.excluded_roots):
        raise PolicyError('A path extension cannot include a protected profile or credential root')
    info = resolved.stat()
    kind = 'directory' if resolved.is_dir() else 'file' if resolved.is_file() else None
    if kind is None or kind != args['scope']:
        raise PolicyError('The selected scope must match an existing regular file or directory')
    if kind == 'file' and info.st_nlink > 1:
        raise PolicyError('Files with hardlink aliases cannot be extended')
    if any(resolved == root or root in resolved.parents for root in base.roots):
        raise PolicyError('The selected location is already inside the configured file roots')
    return {'path': str(resolved), 'scope': kind, 'kind': kind, 'reason': args['reason'].strip()[:2000],
            'session_id': state.session_id, 'device': info.st_dev, 'inode': info.st_ino,
            'approved_operations': ['read', 'create', 'replace'],
            'extension_scope': 'exact file only' if kind == 'file' else 'selected directory and descendants'}


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


class SessionFileAccessPolicy(PathPolicy):
    """Read/edit ordinary accessible paths without per-directory grants."""
    def __init__(self, configured_policy, enabled):
        self.configured_policy = configured_policy
        self.enabled = enabled
        self.roots = configured_policy.roots
        self.excluded_roots = configured_policy.excluded_roots
        self.mapped_s_root = configured_policy.mapped_s_root

    def resolve(self, path, must_exist=False):
        if not self.enabled():
            return self.configured_policy.resolve(path, must_exist=must_exist)
        raw = Path(path).expanduser()
        if not raw.is_absolute():
            raw = self.roots[0] / raw
        return PathPolicy([raw.anchor], excluded_roots=self.excluded_roots).resolve(raw, must_exist=must_exist)


class SessionPathPolicy(PathPolicy):
    def __init__(self, configured_policy, grant):
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


class SessionPathExtensionPolicy(PathPolicy):
    """Configured roots plus individually approved, session-only exact roots."""
    def __init__(self, configured_policy, grants, session_id):
        self.configured_policy = configured_policy
        self.grants = grants
        self.session_id = session_id
        self.roots = configured_policy.roots
        self.excluded_roots = configured_policy.excluded_roots
        self.mapped_s_root = configured_policy.mapped_s_root

    def is_extended(self, path):
        try:
            candidate = Path(path).expanduser().resolve()
        except (OSError, ValueError):
            return False
        return any(self._contains(grant, candidate) for grant in self.grants
                   if grant.get('session_id') == self.session_id)

    def require_operation(self, path, operation):
        candidate = Path(path).expanduser().resolve()
        matches = [grant for grant in self.grants
                   if grant.get('session_id') == self.session_id and self._contains(grant, candidate)]
        if matches and not any(operation in grant.get('approved_operations', []) for grant in matches):
            raise PolicyError('This session path extension does not approve the requested file operation')

    @staticmethod
    def _contains(grant, candidate):
        root = Path(grant['path'])
        return candidate == root if grant['kind'] == 'file' else candidate == root or root in candidate.parents

    def resolve_internal_replace_temp(self, target, temporary):
        """Resolve a generated sibling staging file for an exact-file grant.

        This deliberately does not broaden normal path resolution: only the
        replace implementation can call it, and only for an unpredictable,
        agent-generated temporary name next to the exact granted file.
        """
        target = Path(target).resolve()
        temporary = Path(temporary).absolute()
        for grant in self.grants:
            root = Path(grant.get('path', ''))
            if (grant.get('session_id') != self.session_id or grant.get('kind') != 'file'
                    or grant.get('approved_operations') is None or target != root):
                continue
            try:
                info = root.stat()
                if (info.st_dev, info.st_ino) != (grant.get('device'), grant.get('inode')):
                    continue
                if temporary.parent.resolve() != root.parent.resolve():
                    continue
                prefix = '.' + root.name + '.replace-'
                if (not temporary.name.startswith(prefix) or not temporary.name.endswith('.tmp')
                        or len(temporary.name) != len(prefix) + 32 + 4):
                    continue
                return temporary
            except (OSError, ValueError):
                continue
        raise PolicyError('Internal replacement staging is outside the approved exact-file scope')

    def resolve(self, path, must_exist=False):
        try:
            return self.configured_policy.resolve(path, must_exist=must_exist)
        except PolicyError as base_error:
            for grant in self.grants:
                if grant.get('session_id') != self.session_id:
                    continue
                root = Path(grant.get('path', ''))
                try:
                    extended = PathPolicy([root], excluded_roots=self.excluded_roots,
                                           mapped_s_root=self.mapped_s_root)
                    candidate = extended.resolve(path, must_exist=must_exist)
                    if not self._contains(grant, candidate):
                        continue
                    info = root.stat()
                    if (info.st_dev, info.st_ino) != (grant.get('device'), grant.get('inode')):
                        continue
                    if grant['kind'] == 'file' and candidate != root:
                        continue
                    return candidate
                except (PolicyError, OSError, ValueError, KeyError):
                    continue
            raise base_error
