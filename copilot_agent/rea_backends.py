"""Analysis adapters. Authority, admission and lifecycle stay in rea.py."""
from __future__ import annotations

from pathlib import Path


class NodeCliREABackend:
    name = 'node_cli'

    def __init__(self, config, policy=None):
        self.config, self.policy = config, policy

    def health(self):
        from .rea import _node_health
        return _node_health(self.config)

    async def _analyze(self, prepared, context):
        from .rea import _execute_node
        return await _execute_node(prepared['_name'], prepared['_arguments'], context, self.policy)

    inspect_page = _analyze
    analyze_capture = _analyze
    analyze_artifact = _analyze


class PythonNativeREABackend:
    name = 'python_native'

    def health(self):
        try:
            from .rea_python_capture import analyze_capture
            from .rea_python_page import inspect_page
            from .rea_python_artifacts import analyze_artifact
            import json, struct, zipfile
            if not all(callable(fn) for fn in (analyze_capture, inspect_page, analyze_artifact)):
                raise ValueError('Python analysis entry points missing')
            return {'available': True, 'status': 'available', 'backend': self.name,
                    'version': '1', 'verification': 'All three bundled analysis entry points and standard-library parsers import successfully.',
                    'limitations': ['Static heuristics and metadata are reported with explicit confidence and coverage; no deep decompilation is claimed.']}
        except (ImportError, OSError, ValueError, SyntaxError) as error:
            return {'available': False, 'status': 'unavailable', 'backend': self.name,
                    'reason': 'Bundled Python analysis validation failed: ' + type(error).__name__}

    async def inspect_page(self, prepared, context):
        from .rea_python_page import inspect_page
        return await inspect_page(context['_rea_owned_page'], prepared['_arguments'].get('observation_ms', 500),
                                  budget=context.get('_rea_budget'))

    async def analyze_capture(self, prepared, context):
        from .rea_python_capture import analyze_capture
        return analyze_capture(Path(prepared['snapshot']), prepared['_arguments']['format'], context.get('_rea_budget'))

    async def analyze_artifact(self, prepared, context):
        from .rea_python_artifacts import analyze_artifact
        return analyze_artifact(Path(prepared['snapshot']), prepared['_arguments']['kind'], context.get('_rea_budget'))
