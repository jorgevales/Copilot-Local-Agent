"""Regenerate the exact registered research catalogue without machine state."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from copilot_agent.tools import (ToolRegistry, NAVIGATION_SPECS, INSPECTION_SPECS,
    DOCUMENT_SPECS, KNOWLEDGE_SPECS, DISCOVERY_SPECS, DISCOVERY_KNOWLEDGE_SPECS,
    OPERATION_SPECS, PERMISSION_SPECS, REA_SPECS, AUTH_SPECS, ROUTING_SPECS)


def family(name):
    for names, module, target, strength in (
        (REA_SPECS, 'rea.py', 'owned page or approved static artifact', 'broad passive technical evidence'),
        (AUTH_SPECS, 'browser_auth.py', 'owned approved website', 'one prefilled login-button click'),
        (ROUTING_SPECS, 'research_routing.py', 'approved research target', 'deterministic selection without execution'),
        (NAVIGATION_SPECS, 'web_navigation.py', 'owned tab and verified task identity', 'narrow browser navigation and semantic observation'),
        (INSPECTION_SPECS, 'browser_inspection.py', 'owned approved tab', 'DOM/app/visual evidence and explicit JavaScript'),
        (DOCUMENT_SPECS, 'web_documents.py / document_catalogue.py', 'owned page or selected document', 'observed document discovery and identity'),
        (KNOWLEDGE_SPECS, 'site_knowledge.py', 'bound site namespace', 'verified reusable navigation methods'),
        (DISCOVERY_SPECS, 'discovery_engine.py', 'approved public static manifest', 'bounded public route graph'),
        (DISCOVERY_KNOWLEDGE_SPECS, 'discovery_knowledge.py', 'bound public evidence namespace', 'independent trust and versioned public routes'),
        (OPERATION_SPECS, 'web_operations.py', 'approved public GET', 'API Anything-inspired verified operation reuse'),
        (PERMISSION_SPECS, 'research_permissions.py', 'approved tenant/user research scope', 'durable separately scoped research permissions'),
    ):
        if name in names:
            return module, target, strength
    if name.startswith('crawl4ai.'):
        return 'local_crawler.py', 'approved owned-browser websites / retained task evidence', 'structured rendering, crawling and content extraction'
    if name.startswith('knowledge.'):
        return 'knowledge_notes.py', 'canonical knowledge root/site folder', 'compact sanitized reusable notes'
    if name == 'browser.discover':
        return 'site_discovery.py', 'owned approved page', 'resumable broad navigation campaign'
    if name.startswith('browser.'):
        return 'tools.py / reconciliation.py / screenshot_evidence.py', 'owned approved page', 'narrow browser observation, effects or recovery'
    if name.startswith('files.') or name.startswith('system.'):
        return 'tools.py / local_navigation.py', 'configured or exact session-approved paths', 'deterministic file/system observation or separately approved write'
    return 'tools.py (dispatch; specialized module in source)', 'configured approved resource', 'specialized registered capability'


def main():
    tools = []
    for definition in ToolRegistry({'rea_enabled': False}).definitions():
        definition.pop('availability', None)
        module, target, strength = family(definition['name'])
        tools.append({'implementation': 'copilot_agent/' + module, 'target_types': target,
                      'specialized_strength': strength,
                      'ownership': 'existing orchestrator, path/target policy and owned-browser rules',
                      'evidence': 'existing session result/provenance; knowledge tools use the S-backed ledger',
                      'failure': 'typed error and explicit partial/uncertain outcome; no completion inferred',
                      'rea_relationship': 'primary supported passive investigation' if definition['name'].startswith('rea.') else 'complements REA or supplies a specialized/healthy fallback',
                      **definition})
    output = {'source': 'copilot_agent.tools.ToolRegistry', 'schema_version': 1,
              'machine_state_excluded': True, 'tools': tools}
    destination = ROOT / 'docs' / 'RESEARCH_TOOL_INVENTORY.json'
    destination.write_text(json.dumps(output, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
    print(f'{len(tools)} registered tools inventoried')


if __name__ == '__main__':
    main()
