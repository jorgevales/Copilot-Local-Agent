"""Resolved-path and navigation boundaries shared by all local capabilities."""
from pathlib import Path
import ntpath
import os
import stat
from urllib.parse import urlsplit, urlunsplit


class PolicyError(ValueError):
    pass


# Microsoft MS-FSCC 2.1.2.1: Cloud Files tags are not name surrogates.
# https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/c8e77b37-3909-4fe6-a4ea-2b9d423b1ee4
CLOUD_REPARSE_TAGS=frozenset(0x9000001A+(variant<<12) for variant in range(16))
NAME_SURROGATE_BIT=0x20000000


def reject_path_redirection(path):
    """Allow known Cloud Files placeholders only when they retain the same path.

    Inspect raw parents before children so resolving a link cannot hide its tag.
    Reported unknown reparse points are denied without the name-surrogate bit.
    Windows/interpreter compatibility views can suppress cloud tag metadata.
    These checks do not provide OS isolation from concurrent local path changes.
    """
    raw=Path(path).expanduser().absolute()
    for item in reversed([raw,*raw.parents]):
        try: info=item.lstat()
        except FileNotFoundError: continue
        tag=getattr(info,"st_reparse_tag",0)
        attributes=getattr(info,"st_file_attributes",0)
        if stat.S_ISLNK(info.st_mode) or tag & NAME_SURROGATE_BIT:
            raise PolicyError("Symlink, junction or name-surrogate paths are forbidden")
        if tag or attributes & getattr(stat,"FILE_ATTRIBUTE_REPARSE_POINT",0x400):
            if tag not in CLOUD_REPARSE_TAGS:
                raise PolicyError("Unknown or unsupported reparse paths are forbidden")
            if item.resolve(strict=True)!=Path(os.path.abspath(item)):
                raise PolicyError("Cloud placeholder resolved to a different named path")


class PathPolicy:
    def __init__(self, roots, excluded_roots=(), mapped_s_root=None):
        self.roots = tuple(Path(p).expanduser().resolve() for p in roots)
        self.excluded_roots = tuple(Path(p).expanduser().resolve() for p in excluded_roots)
        self.mapped_s_root = Path(mapped_s_root).resolve() if mapped_s_root else None
        if not self.roots:
            raise PolicyError("At least one allowed root is required")

    def resolve(self, path, must_exist=False):
        if not isinstance(path, (str, Path)) or not str(path).strip():
            raise PolicyError("A nonempty path is required")
        original = str(path)
        if is_s_drive_path(original):
            # S: is a drive mapping, not a filesystem junction. Resolve its
            # current UNC identity before checking the configured roots.
            raw = (mapped_s_drive_root() if ntpath.normpath(original).casefold() == 's:\\'
                   else resolve_s_drive_output(original, must_exist=must_exist))
        else:
            raw = Path(path).expanduser()
        if not raw.is_absolute():
            raw = self.roots[0] / raw
        # Windows alternate streams and device paths are not filesystem capabilities.
        if any(":" in part for part in raw.parts[1:]) or str(raw).startswith(("\\\\?\\", "\\\\.\\")):
            raise PolicyError("Device paths and alternate data streams are forbidden")
        devices={"CON","PRN","AUX","NUL",*(f"COM{i}" for i in range(1,10)),*(f"LPT{i}" for i in range(1,10))}
        if any(part.split(".")[0].upper() in devices for part in raw.parts[1:]):
            raise PolicyError("Windows device names are forbidden")
        reject_path_redirection(raw)
        resolved = raw.resolve(strict=must_exist)
        if (self.mapped_s_root is not None
                and (resolved == self.mapped_s_root or self.mapped_s_root in resolved.parents)
                and mapped_s_drive_root().resolve() != self.mapped_s_root):
            raise PolicyError('The S: mapping changed since file roots were configured')
        if any(resolved==root or root in resolved.parents for root in self.excluded_roots):
            raise PolicyError("Protected profile or credential root is outside file capabilities")
        if not any(resolved == root or root in resolved.parents for root in self.roots):
            raise PolicyError("Resolved path escapes allowed roots")
        sensitive_directories = {".aws", ".ssh", ".azure", ".gnupg", ".kube", "edge_profile", "edge-profile"}
        parts=[part.casefold() for part in resolved.parts]
        windows_stores={"credentials","vault","protect","oneauth","identitycache","tokenbroker"}
        protected_windows_store=any(parent=="microsoft" and child in windows_stores for parent,child in zip(parts,parts[1:]))
        normalized_name=resolved.name.casefold().replace(" ","").replace("_","")
        browser_databases={"cookies","logindata","localstate","webdata"}
        browser_database=any(normalized_name==name or normalized_name in {name+"-journal",name+"-wal",name+"-shm"} for name in browser_databases)
        credential_names={"credentials", "credentials.json", "auth.json", "tokens.json", "id_rsa", "id_ed25519", ".env"}
        if any(part in sensitive_directories for part in parts) or protected_windows_store or browser_database or resolved.name.casefold() in credential_names or resolved.name.casefold().startswith(".env."):
            raise PolicyError("Credential stores are outside file capabilities")
        try:
            info=resolved.stat()
        except FileNotFoundError:
            if must_exist: raise
        else:
            if stat.S_ISREG(info.st_mode) and info.st_nlink>1:
                raise PolicyError("Files with hardlink aliases are outside file capabilities")
        return resolved


def is_s_drive_path(path) -> bool:
    """Recognize an absolute operator-facing S: path, never S:relative."""
    value = str(path)
    return ntpath.splitdrive(value)[0].casefold() == 's:' and ntpath.isabs(value)


def _final_s_path(value):
    try:
        resolved = os.path.realpath(value, strict=True)
    except (OSError, ValueError) as error:
        raise PolicyError('The mapped S: share or selected path is unavailable') from error
    if resolved.casefold().startswith('\\\\?\\unc\\'):
        resolved = '\\\\' + resolved[8:]
    elif resolved.startswith('\\\\?\\'):
        resolved = resolved[4:]
    return ntpath.normcase(ntpath.normpath(resolved)).rstrip('\\')


def mapped_s_drive_root():
    """Return the share currently mapped as S:, or fail closed."""
    if os.name != 'nt':
        raise PolicyError('S: is available only on Windows')
    try:
        share = _final_s_path('S:\\')
    except PolicyError:
        share = _mapped_s_provider_root()
    if not share.startswith('\\\\'):
        raise PolicyError('S: must currently resolve to a UNC share')
    return Path(share)


def _mapped_s_provider_root():
    """Read the same current mapping providers used by the launcher.

    Commands are fixed, read-only, bounded and hidden. Only a live provider's
    UNC destination is accepted, and its final directory must be accessible.
    No saved mapping, guessed share or local directory is a fallback.
    """
    import json
    import subprocess
    script = """
$ErrorActionPreference='Continue'
$candidates=@()
$drive=Get-PSDrive -Name S -ErrorAction SilentlyContinue
if ($drive -and $drive.DisplayRoot -like '\\\\*') { $candidates += [string]$drive.DisplayRoot }
$disk=Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='S:'\" -ErrorAction SilentlyContinue
if ($disk -and $disk.ProviderName -like '\\\\*') { $candidates += [string]$disk.ProviderName }
$map=Get-SmbMapping -LocalPath 'S:' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($map -and $map.RemotePath -like '\\\\*') { $candidates += [string]$map.RemotePath }
ConvertTo-Json -Compress -InputObject @($candidates | Select-Object -Unique)
"""
    try:
        result = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, text=True, timeout=10,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        values = json.loads(result.stdout) if result.returncode == 0 and len(result.stdout) <= 8192 else None
        if type(values) is not list or not 1 <= len(values) <= 3:
            raise ValueError()
        for value in values:
            if (type(value) is not str or not value.startswith('\\\\')
                    or value.startswith(('\\\\?\\', '\\\\.\\')) or not ntpath.isabs(value)):
                continue
            try:
                share = _final_s_path(value)
                if not share.startswith('\\\\') or not Path(share).is_dir():
                    continue
                reject_path_redirection(Path(share))
                return share
            except (PolicyError, OSError, ValueError):
                continue
        raise ValueError()
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise PolicyError('The live S: mapping and its provider UNC fallbacks are unavailable') from error


def resolve_s_drive_output(path, excluded_roots=(), *, must_exist=False):
    """Bind a proposed output to the live UNC identity of mapped S:."""
    value = str(path)
    if os.name != 'nt' or not value or value != value.strip() or value.startswith(('\\\\?\\', '\\\\.\\')):
        raise PolicyError('An absolute S: path or its live UNC share is required')
    raw = ntpath.normpath(value.replace('/', '\\'))
    if not (is_s_drive_path(raw) or raw.startswith('\\\\')):
        raise PolicyError('The output must be on S: or its currently mapped UNC share')
    name = ntpath.basename(raw)
    if not name or name in {'.', '..'}:
        raise PolicyError('Select a file or directory inside the mapped S: share')
    share = ntpath.normpath(str(mapped_s_drive_root())).rstrip('\\')
    parent_raw = ntpath.dirname(raw)
    # The drive mapping itself can redirect to UNC. Inspect the equivalent UNC
    # child chain, where a junction inside the share cannot hide behind S:.
    checked_parent = (ntpath.join(share, ntpath.relpath(parent_raw, 'S:\\'))
                      if is_s_drive_path(raw) else parent_raw)
    reject_path_redirection(Path(checked_parent))
    try:
        parent = _final_s_path(parent_raw)
    except PolicyError:
        if not is_s_drive_path(raw):
            raise
        parent = _final_s_path(checked_parent)
    if parent != share and not parent.startswith(share + '\\'):
        raise PolicyError('The destination is outside the share currently mapped to S:')
    target = Path(parent) / name
    return PathPolicy([share], excluded_roots=excluded_roots).resolve(target, must_exist=must_exist)


class URLPolicy:
    def __init__(self, domains):
        self.domains = {str(d).lower().rstrip(".") for d in domains}

    def resolve(self, url):
        if not isinstance(url, str) or len(url) > 4096:
            raise PolicyError("Invalid URL")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise PolicyError("Only HTTPS URLs without embedded credentials are allowed")
        hostname = parsed.hostname.lower().rstrip(".")
        if not any(hostname == domain or hostname.endswith("." + domain) for domain in self.domains):
            raise PolicyError("Domain is outside the approved website and subdomain scope")
        if parsed.port not in (None, 443):
            raise PolicyError("Only the HTTPS default port is allowed")
        return urlunsplit(parsed)

    @staticmethod
    def website_domain(url):
        """Validate a proposed HTTPS navigation and return its approval scope."""
        parsed = urlsplit(url)
        if (not isinstance(url, str) or len(url) > 4096 or parsed.scheme != "https"
                or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise PolicyError("Only HTTPS URLs without embedded credentials on the default port are allowed")
        return parsed.hostname.lower().rstrip(".")


def config_value(config, key, default=None):
    return config.get(key, default) if isinstance(config, dict) else getattr(config, key, default)
