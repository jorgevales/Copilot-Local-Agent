"""Source-backed usage instructions supplied before a model constructs REA calls.

Public argument schemas remain owned by rea.REA_SPECS. Upstream references are
the inspected rea-agents 6.5.0 distribution/source, not the broader MCP surface.
"""
from __future__ import annotations

import copy

from .config import Config
from .policy import config_value


SOURCES = {
    'version': 'rea-agents 6.5.0',
    'source_revision': 'd7651b6a0dde6cfe658144cc52794ae6aaf23306',
    'upstream': [
        'docs/browser-observation.md', 'docs/web-network-captures.md',
        'docs/managed-code-analysis.md', 'docs/go-binaries.md',
        'docs/rust-binaries.md', 'docs/javascript-artifact-reconstruction.md',
        'docs/cli.md', 'src/cliOutput.ts',
    ],
    'local_contract': ['copilot_agent/rea.py:REA_SPECS',
                       'copilot_agent/rea_python_page.py:SNAPSHOT'],
}


def rea_usage_guidance(config=None):
    """Return JSON-safe guidance without probing Node, files, browser or network."""
    from .rea import REA_SPECS

    defaults = Config()
    added_defaults = {'rea_max_transport_bytes': 32 * 1024 * 1024,
                      'rea_fallback_timeout_seconds': 15}
    value = lambda name: config_value(config or {}, name, getattr(defaults, name, added_defaults.get(name)))
    methods = {
        'rea.inspect_page': {
            'purpose': 'Passive structural, accessibility and bounded network observation of one already owned approved browser page; no navigation or login.',
            'parameters': {'tab_id': 'Optional existing owned tab ID, 1..100 characters; omitted selects the existing default owned tab.',
                           'observation_ms': 'Optional integer 0..3000 milliseconds, default 500. Zero captures current state without an additional observation wait.'},
            'prerequisites': ['An already open owned HTTP(S) tab in approved scope and its orchestrator-managed loopback CDP browser connection.',
                              'Use a tab ID from current browser evidence. The orchestrator resolves and verifies the matching CDP target; do not supply a URL, endpoint or target ID.'],
            'example': {'arguments': {'observation_ms': 0},
                        'condition': 'Valid only when the default owned tab is already present and approved.'},
            'upstream_command': 'inspect-web-page',
            'not_accepted': ['max_nodes', 'path', 'cdp_endpoint', 'target_id', 'include_script_sources'],
        },
        'rea.analyze_capture': {
            'purpose': 'Inspect retained HAR 1.2 or Fiddler Everywhere SAZ evidence offline; never fetch or replay recorded requests.',
            'parameters': {'path': 'Required existing approved file path, 1..4096 characters.',
                           'format': 'Required exact enum: har or saz.'},
            'prerequisites': ['First obtain an actual retained capture from browser/capture evidence or an approved file listing.',
                              'A URL or guessed/nonexistent filename is not a capture. HAR must contain a valid HAR 1.2 log; SAZ must be a supported native session archive.'],
            'example': {'arguments': {'path': '<EXISTING_APPROVED_CAPTURE_PATH>', 'format': 'har'},
                        'condition': 'Template only: replace the placeholder with the exact existing HAR path returned by an earlier tool; never send this placeholder.'},
            'upstream_command': 'inspect-web-network-capture',
            'not_accepted': ['record_ordinals', 'detail', 'url', 'capture_path'],
        },
        'rea.analyze_artifact': {
            'purpose': 'Read static metadata from a selected approved artifact without loading or executing its target code.',
            'parameters': {'path': 'Required existing approved file or JavaScript application-directory path, 1..4096 characters.',
                           'kind': 'Required exact enum: managed, go, rust or javascript.'},
            'supported_inputs': {'managed': 'PE/CLI .NET assembly; not general native code, NativeAOT, IL2CPP or arbitrary single-file hosts.',
                                 'go': 'Executable/library with supported Go build metadata (ELF, PE or thin Mach-O). Missing metadata is not proof of no dependencies.',
                                 'rust': 'Supported executable/library with cargo-auditable dependency metadata. Missing .dep-v0 is not proof of no dependencies.',
                                 'javascript': 'For the upstream Node backend use an extracted JavaScript/Electron application directory or .asar; do not assume a lone .js file is a supported application.'},
            'prerequisites': ['Select an existing authorized artifact from prior tool evidence; classify its contents rather than trusting the filename extension.',
                              'The orchestrator verifies original bytes, snapshots them into suitable scratch storage and checks for changes after analysis. No target execution or native decompiler is exposed.'],
            'example': {'arguments': {'path': '<EXISTING_APPROVED_APPLICATION_DIRECTORY>', 'kind': 'javascript'},
                        'condition': 'Template only: replace with an existing approved application directory observed by a previous tool.'},
            'upstream_commands': {'managed': 'inspect-managed-artifact', 'go': 'inspect-go-binary',
                                  'rust': 'inspect-rust-binary', 'javascript': 'analyze-javascript-application'},
            'not_accepted': ['provider', 'format', 'integrity_policy', 'command', 'arguments'],
        },
    }
    for name, method in methods.items():
        method['input_schema'] = copy.deepcopy(REA_SPECS[name][0])
    return {
        'authority': copy.deepcopy(SOURCES),
        'before_request': [
            'Use these local ToolRegistry methods and their exact input_schema; upstream CLI/MCP options are not automatically local parameters.',
            'Send only schema fields. Never invent an input path or target, and never add max_nodes or observation_ms=5000.',
            'Read current catalogue availability/backend and limits before selecting a tool. When the user requests upstream REA, success must identify backend=node_cli.',
        ],
        'methods': methods,
        'backend_rules': {
            'configured': value('rea_backend'),
            'auto': 'Prefer validated node_cli; python_native may supply useful fallback evidence when upstream cannot complete safely. Always identify fallback/degradation and the prior Node failure; this does not satisfy upstream Node success.',
            'node_cli': 'Require the actual installed upstream REA CLI. No Python substitution.',
            'python_native': 'Explicit bundled passive/static fallback only; not the upstream REA Node implementation.',
            'unsafe_cleanup': 'Do not start another backend or repeat analysis when cleanup or page/input ownership is uncertain.',
        },
        'limits': {
            'readiness_timeout_seconds': value('rea_node_readiness_timeout_seconds'),
            'analysis_timeout_seconds': value('rea_timeout_seconds'),
            'analysis_timeout_max_seconds': 1800,
            'node_old_space_heap_mib': 1024,
            'fallback_timeout_seconds': value('rea_fallback_timeout_seconds'),
            'readiness_budget': 'Separate shared budget for readiness probes; cached verified readiness is reused. Observation wait is only part of analysis time, not the process deadline.',
            'fallback_budget': 'Node receives its full analysis allowance. A permitted fallback has its own bounded allowance; its evidence remains explicitly degraded.',
            'input_bytes': value('rea_max_input_bytes'),
            'output_bytes': value('rea_max_output_bytes'),
            'transport_bytes': value('rea_max_transport_bytes'),
            'large_evidence': 'Transport allowance and model-facing output allowance are separate. A complete sanitized Node observation may be retained as a bounded evidence artifact while the model receives its compact projection and artifact reference. Do not parse truncated JSON or infer that projection truncation means Node failed.',
            'parallel_calls': value('rea_max_parallel'),
            'javascript_inventory_entries': 2000,
            'javascript_node_heap_mib': 256,
            'javascript_semantic_nodes': 10000,
            'javascript_semantic_nodes_per_file': 3000,
            'python_page': {'dom_elements': 2000, 'configurable': False,
                            'reason': 'Intentional fixed passive fallback resource ceiling; max_nodes is not a request parameter. It is not an upstream REA DOM limit.',
                            'resources': 1000, 'response_events': 500, 'frames': 100,
                            'navigation_routes': 200, 'scripts': 200, 'forms': 100,
                            'overflow': 'truncated=true and coverage_complete=false; retain verified partial findings but never claim full-page coverage.'},
        },
        'status_meanings': {
            'completed': 'A verified observation completed within declared coverage; inspect limitations/unknowns. Process exit 0 alone does not prove complete coverage.',
            'partial': 'Some bounded findings exist and coverage has gaps. Reuse only when observation_verified=true and no error or uncertainty; coverage_complete remains false.',
            'not_started': 'Preflight, argument, scope or input validation prevented execution; fix the stated prerequisite rather than treating this as an upstream defect.',
            'unavailable': 'The selected backend or required runtime capability is not usable; inspect backend-specific readiness diagnostics.',
            'timeout': 'A stage exhausted its deadline; distinguish readiness/startup from analysis using diagnostics. Do not infer missing runtime or bad credentials.',
            'output_limit': 'Output exceeded a configured bound; not a timeout. Truncated JSON is not a complete parseable observation.',
            'failed': 'Invocation, process or output processing failed; inspect error code, stage, exit code and bounded diagnostics.',
            'cancelled': 'The operation was cancelled; inspect cleanup confirmation before retrying.',
            'uncertain': 'Execution effects or cleanup could not be verified; stop automatic retry/fallback until reconciled.',
            'fallback_condition': 'degraded=true/fallback_used=true marks fallback, not a replacement status enum. Report backend, intended_backend_succeeded=false and prior_backend_attempt; never describe it as Node REA success.',
        },
        'upstream_output': {
            'supported': ['--json', '--full-output', '--filter-output <comma-delimited paths/slices>'],
            'unsupported_assumptions': ['--fields', '--compact', '--out'],
            'structured_output': 'Do not combine --json with --token-limit/--token-offset; upstream rejects token windows because they cannot preserve structured output.',
            'retention': 'Upstream docs recommend saving complete JSON and inspect-analysis-view for summary/pages of large application or capture evidence. A filter must retain required Evidence identity/status/coverage fields; never guess a filter that discards them.',
            'access': 'CLI flags are adapter-owned implementation details. Copilot must not pass them as local ToolRegistry arguments or launch an arbitrary shell to bypass the adapter.',
        },
        'manual_comparison': {
            'invocation': ['<NODE_ROOT>\\node.exe', '<REA_RUNTIME_ROOT>\\scripts\\rea.mjs',
                           'inspect-web-page', '<LOOPBACK_CDP_ENDPOINT>', '<VERIFIED_TARGET_ID>',
                           '--allowed-origins', '<APPROVED_EXACT_ORIGIN>', '--observation-ms', '0', '--json', '--full-output'],
            'prerequisites': 'Operator diagnostic template only; use the already verified endpoint/target/origin from the owned browser, not fabricated IDs. Compare with the adapter-generated sanitized argument array.',
            'observed_live_result': 'User-reported REA 6.5.0 / Node 24.22.0 inspection at observation-ms=0 returned valid Evidence, exit 0, 4,008,122 stdout bytes and no stderr. This is live-agent supplied evidence, not a local reproduction.',
        },
    }
