"""Resolved-path and navigation boundaries shared by all local capabilities."""
from pathlib import Path
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
    def __init__(self, roots, excluded_roots=()):
        self.roots = tuple(Path(p).expanduser().resolve() for p in roots)
        self.excluded_roots = tuple(Path(p).expanduser().resolve() for p in excluded_roots)
        if not self.roots:
            raise PolicyError("At least one allowed root is required")

    def resolve(self, path, must_exist=False):
        if not isinstance(path, (str, Path)) or not str(path).strip():
            raise PolicyError("A nonempty path is required")
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
