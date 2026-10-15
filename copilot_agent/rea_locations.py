"""Bounded discovery of existing REA repositories and portable Node tooling."""
from pathlib import Path

from .node_runtime import node_path_candidates


def _tools_roots(node_paths):
    roots = []
    for value in node_paths:
        try:
            for node in node_path_candidates(value):
                root = node.parent.parent
                if root not in roots:
                    roots.append(root)
        except (OSError, ValueError):
            continue
    return roots


def existing_runtime_candidates(project, node_paths=()):
    """Return known sibling/global layouts; callers must verify each runtime.

    These are reuse candidates, never installation destinations. Node aliases
    use the same S:/UNC normalization as the existing portable Node resolver.
    """
    candidates = [root / 'npm-data' / 'global' / 'node_modules' / 'rea-agents'
                  for root in _tools_roots(node_paths)]
    candidates.append(Path(project).parent / 'REA')
    return list(dict.fromkeys(candidates))


def npm_cache_candidates(node_paths=()):
    """Locate the existing portable npm cache without reading npmrc/secrets."""
    return [root / 'npm-data' / 'cache' for root in _tools_roots(node_paths)]
