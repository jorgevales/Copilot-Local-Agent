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

    def __init__(self, config=None):
        self.config = config

    def health(self):
        try:
            from . import rea_python_capture, rea_python_page, rea_python_artifacts, rea_python_readiness
            from .rea_readiness import cached_health, python_source_identity
            from .policy import config_value
            modules = (rea_python_capture, rea_python_page, rea_python_artifacts, rea_python_readiness)
            def identity():
                return ('python', str(config_value(self.config, 'root', '')),
                        python_source_identity([module.__file__ for module in modules]),
                        id(rea_python_capture.analyze_capture), id(rea_python_page.inspect_page),
                        id(rea_python_artifacts.analyze_artifact), id(rea_python_readiness.functional_checks),
                        id(rea_python_readiness.run_functional_checks))
            return cached_health(identity(), self._functional_health)
        except (ImportError, OSError, ValueError, SyntaxError) as error:
            return {'available': False, 'status': 'unavailable', 'backend': self.name,
                    'reason': 'Bundled Python source validation failed: ' + type(error).__name__}

    def _functional_health(self):
        try:
            from .rea_python_capture import analyze_capture
            from .rea_python_page import inspect_page
            from .rea_python_artifacts import analyze_artifact
            if not all(callable(fn) for fn in (analyze_capture, inspect_page, analyze_artifact)):
                raise ValueError('Python analysis entry points missing')
            from .rea_python_readiness import run_functional_checks
            from .policy import config_value
            checks = run_functional_checks(config_value(self.config, 'root', None))
            return {'available': True, 'status': 'available', 'backend': self.name,
                    'version': '1', 'verification': 'All bundled capabilities passed small functional fixture checks; no browser was launched and no target was contacted.',
                    'capability_checks': checks,
                    'limitations': ['Static heuristics and metadata are reported with explicit confidence and coverage; no deep decompilation is claimed.']}
        except (ImportError, OSError, ValueError, SyntaxError, RuntimeError, KeyError, TypeError, AssertionError) as error:
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
