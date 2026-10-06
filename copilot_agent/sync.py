"""Observe new local outputs without treating cloud previews as delivery."""
import asyncio
import fnmatch
import time
from pathlib import Path


class CreatedSync:
    def __init__(self, directory, stable_seconds=0.5, poll_interval=0.2, max_candidates=1000):
        self.directory = Path(directory).resolve()
        self.stable_seconds = max(0.05, stable_seconds)
        self.poll_interval = max(0.05, poll_interval)
        self.max_candidates = max_candidates

    def baseline(self):
        if not self.directory.is_dir():
            return {}
        result = {}
        for path in self.directory.iterdir():
            if path.is_file() and not path.is_symlink():
                try: info = path.stat()
                except OSError: continue
                result[path.name] = (info.st_size, info.st_mtime_ns)
                if len(result) > self.max_candidates:
                    raise ValueError("Created directory exceeds candidate enumeration limit")
        return result

    async def poll(self, baseline, pattern="*", timeout=30, expected_names=None):
        if not self.directory.is_dir():
            return {"status": "missing_directory", "files": []}
        if not isinstance(pattern, str) or "/" in pattern or "\\" in pattern:
            raise ValueError("Pattern must match filenames only")
        expected = set(expected_names or [])
        if any(Path(name).name != name for name in expected):
            raise ValueError("Expected names must be plain filenames")
        deadline = time.monotonic() + min(300, max(0.05, timeout))
        seen = {}
        while time.monotonic() < deadline:
            try: current = self.baseline()
            except ValueError as error: return {"status":"candidate_limit", "files":[], "reason":str(error)}
            candidates = []
            changed_names = set()
            for name, fingerprint in current.items():
                if baseline.get(name) == fingerprint or not fnmatch.fnmatchcase(name, pattern):
                    continue
                if expected and name not in expected:
                    continue
                changed_names.add(name)
                previous, since = seen.get(name, (None, time.monotonic()))
                if previous != fingerprint:
                    seen[name] = (fingerprint, time.monotonic())
                    continue
                if time.monotonic() - since < self.stable_seconds:
                    continue
                path = self.directory / name
                try:
                    if path.is_symlink() or path.resolve().parent != self.directory:
                        continue
                    with path.open("rb") as stream:
                        stream.read(1)
                    info = path.stat()
                    if (info.st_size, info.st_mtime_ns) != fingerprint:
                        continue
                except OSError:
                    continue
                candidates.append({"name": name, "path": str(path), "size": fingerprint[0], "mtime_ns": fingerprint[1]})
            if candidates:
                if not expected and len(changed_names)>1:
                    return {"status":"ambiguous","files":candidates,"candidate_names":sorted(changed_names)}
                names = {item["name"] for item in candidates}
                if expected and names != expected:
                    await asyncio.sleep(self.poll_interval)
                    continue
                return {"status": "ambiguous" if not expected and len(candidates) > 1 else "synchronized", "files": candidates}
            await asyncio.sleep(self.poll_interval)
        return {"status": "timeout", "files": []}


def snapshot(directory):
    return CreatedSync(directory).baseline()
