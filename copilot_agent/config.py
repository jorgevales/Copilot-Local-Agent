from __future__ import annotations
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from .storage import discover_onedrive_accounts, profile_directory, saved_storage_choice, validate_storage_directory

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def documents_directory() -> Path:
    """Resolve the Windows known Documents folder, with portable fallbacks."""
    if os.name == 'nt':
        try:
            import ctypes
            buffer = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0:
                return Path(buffer.value)
        except (AttributeError, OSError):
            pass
    return Path.home() / 'Documents'


@dataclass
class Config:
    root: Path = PROJECT_ROOT
    storage_dir: Path | None = None
    copilot_url: str = 'https://m365.cloud.microsoft/chat'
    debug_port: int = 9443
    profile_dir: Path | None = None
    edge_executable: str = ''
    attach_existing: bool = False
    visible: bool = True
    startup_timeout: float = 60
    response_timeout: float = 180
    poll_interval: float = .5
    capture_stable_samples: int = 3
    max_capture_chars: int = 100000
    max_corrections: int = 2
    max_tool_rounds: int = 12
    max_context_chars: int = 16000
    max_output_chars: int = 12000
    tool_timeout: float = 30
    sync_timeout: float = 120
    sync_poll_interval: float = .5
    allowed_roots: list[str] = field(default_factory=lambda: ['workspace', 'deliveries'])
    allowed_domains: list[str] = field(default_factory=lambda: ['example.com'])
    created_dir: Path | None = None
    created_sync_enabled: bool = False
    model: str = ''
    max_attachment_bytes: int = 20 * 1024 * 1024
    download_timeout: float = 90
    max_download_bytes: int = 20 * 1024 * 1024
    max_delivery_retries: int = 3
    copilot_download_hosts: list[str] = field(default_factory=lambda: ['eu-prod.asyncgw.teams.microsoft.com', 'm365.cloud.microsoft'])

    @property
    def runtime_dir(self) -> Path:
        # Explicit custom roots support retained, isolated test/development fixtures.
        return (Path(self.storage_dir) if self.storage_dir is not None else Path(self.root)) / 'runtime'

    @property
    def workspace_dir(self) -> Path:
        return (Path(self.storage_dir) if self.storage_dir is not None else Path(self.root)) / 'workspace'

    def select_storage(self, directory: Path):
        accounts = getattr(self, '_storage_candidates', None) or discover_onedrive_accounts()
        self.storage_dir = validate_storage_directory(Path(directory), accounts)
        if not getattr(self, '_profile_explicit', False):
            self.profile_dir = None
        elif getattr(self, '_configured_profile_dir', None) is not None:
            self.profile_dir = self._configured_profile_dir
        self.allowed_roots = list(getattr(self, '_configured_allowed_roots', ['workspace', 'deliveries']))
        self.validate()

    @classmethod
    def load(cls, path: Path | None = None) -> 'Config':
        cfg = cls()
        data = {}
        if path and Path(path).exists():
            data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            unknown = set(data) - set(asdict(cfg))
            if unknown:
                raise ValueError('Unknown configuration fields: ' + ', '.join(sorted(unknown)))
            for key, value in data.items():
                if key in {'root', 'storage_dir', 'profile_dir', 'created_dir'}:
                    if value is not None:
                        value = Path(value).expanduser()
                        if key == 'root' and not value.is_absolute():
                            value = PROJECT_ROOT / value
                setattr(cfg, key, value)
        cfg._profile_explicit = bool(data.get('profile_dir'))
        cfg._configured_profile_dir = Path(data['profile_dir']) if data.get('profile_dir') else None
        cfg._configured_allowed_roots = list(data.get('allowed_roots', ['workspace', 'deliveries']))
        cfg._storage_candidates = discover_onedrive_accounts()
        if cfg.storage_dir is None:
            cfg.storage_dir = saved_storage_choice(cfg._storage_candidates)
        if cfg.storage_dir is not None:
            cfg.storage_dir = validate_storage_directory(cfg.storage_dir, cfg._storage_candidates)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if type(self.debug_port) is not int or not 1024 <= self.debug_port <= 65535:
            raise ValueError('debug_port must be an integer from 1024 to 65535')
        for key in ('visible', 'attach_existing', 'created_sync_enabled'):
            if type(getattr(self, key)) is not bool:
                raise ValueError(key + ' must be boolean')
        for key in ('startup_timeout', 'response_timeout', 'poll_interval', 'tool_timeout', 'sync_timeout', 'sync_poll_interval', 'download_timeout'):
            if type(getattr(self, key)) not in (int, float) or not 0 < getattr(self, key) <= 3600:
                raise ValueError(key + ' must be positive and at most 3600')
        for key in ('capture_stable_samples', 'max_capture_chars', 'max_tool_rounds', 'max_context_chars', 'max_output_chars', 'max_attachment_bytes', 'max_download_bytes'):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(key + ' must be a positive integer')
        if type(self.max_corrections) is not int or not 0 <= self.max_corrections <= 10:
            raise ValueError('max_corrections must be from 0 to 10')
        if type(self.max_delivery_retries) is not int or not 0 <= self.max_delivery_retries <= 5:
            raise ValueError('max_delivery_retries must be from 0 to 5')
        if not isinstance(self.copilot_download_hosts, list) or not self.copilot_download_hosts or not all(isinstance(h, str) and h and all(c.isalnum() or c in '.-' for c in h) for h in self.copilot_download_hosts):
            raise ValueError('copilot_download_hosts must contain exact hostnames')
        if not isinstance(self.allowed_roots, list) or not self.allowed_roots or not all(isinstance(p, str) and p for p in self.allowed_roots):
            raise ValueError('allowed_roots must contain directory paths')
        if not isinstance(self.allowed_domains, list) or not all(isinstance(p, str) and p for p in self.allowed_domains):
            raise ValueError('allowed_domains must be a list of domain names')
        self.root = Path(self.root).resolve()
        self.storage_dir = Path(self.storage_dir).expanduser().resolve() if self.storage_dir is not None else None
        base = self.storage_dir if self.storage_dir is not None else self.root
        if self.profile_dir is None:
            self.profile_dir = profile_directory(base).resolve()
        else:
            profile = Path(self.profile_dir)
            self.profile_dir = (base / profile).resolve() if not profile.is_absolute() else profile.resolve()
        if self.created_sync_enabled and not self.created_dir:
            raise ValueError('created_sync_enabled requires an explicit OneDrive Documents/Copilot/Created path')
        # Pure path construction: disabled sync must not probe any OneDrive folder.
        self.created_dir = Path(self.created_dir).absolute() if self.created_dir else None
        self.allowed_roots = [str((base / p).resolve()) if not Path(p).is_absolute() else str(Path(p).resolve()) for p in self.allowed_roots]

    def as_dict(self) -> dict:
        data = asdict(self)
        for key in ('root', 'storage_dir', 'profile_dir', 'created_dir'):
            data[key] = str(data[key]) if data[key] is not None else None
        return data
