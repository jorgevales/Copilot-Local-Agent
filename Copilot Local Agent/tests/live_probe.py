"""Explicitly gated visible picker-only probe: no uploads or chat sends."""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from copilot_agent.config import Config
from copilot_agent.browser import BrowserAdapter, model_rank
from copilot_agent.browser import composer_comparison
from copilot_agent.browser import _MESSAGE_SNAPSHOT, fresh_assistant
from copilot_agent.reused_browser import PICKER_SELECTOR


async def run(args):
    if not args.live:
        raise ValueError('This probe requires explicit --live. It opens visible Edge and changes the model picker only.')
    cfg = Config(root=ROOT, attach_existing=True, debug_port=args.port,
                 profile_dir=Path(args.profile), startup_timeout=args.startup_timeout)
    cfg.validate()
    adapter = BrowserAdapter(cfg)
    token = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    directory = ROOT / 'runtime' / 'acceptance' / ('picker-' + token)
    directory.mkdir(parents=True, exist_ok=True)
    report = {'test': 'visible_picker_only', 'started_at': datetime.now(timezone.utc).isoformat(),
              'no_messages_or_uploads': True, 'status': 'blocked'}
    try:
        await adapter.start()
        if args.latest_initialization:
            links = await adapter._evaluate(r"""() => [...document.querySelectorAll('a[href]')]
              .filter(n=>/^Initialize Continuous Conversation(?:\s|$)/i.test((n.innerText||n.getAttribute('aria-label')||'').trim()))
              .map(n=>n.href).filter(u=>u.startsWith('https://m365.cloud.microsoft/chat/conversation/'))""")
            report['initialization_candidate_count'] = len(set(links))
            for url in list(dict.fromkeys(links))[:5]:
                await adapter.page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await adapter.page.wait_for_timeout(2500)
                nodes = await adapter._evaluate(_MESSAGE_SNAPSHOT)
                if any(item['role']=='user' and args.request_id in item['text'] for item in nodes):
                    args.conversation = adapter.page.url
                    report['authorized_conversation_url'] = args.conversation
                    break
            if not args.conversation:
                raise ValueError('Could not safely identify the authorized initialization conversation by its exact request ID.')
        if args.conversation:
            from urllib.parse import urlparse
            from copilot_agent.protocol import parse_response
            from copilot_agent.tools import ToolRegistry
            url = urlparse(args.conversation)
            if url.scheme != 'https' or url.hostname != 'm365.cloud.microsoft' or not url.path.startswith('/chat/conversation/'):
                raise ValueError('Read-only inspection is limited to the authorized Copilot conversation URL.')
            await adapter.page.goto(args.conversation, wait_until='domcontentloaded', timeout=30000)
            await adapter.page.wait_for_timeout(4000)
            report['code_editor_observations'] = []
            for attempt in range(20):
                observation = await adapter._evaluate(r"""() => [...document.querySelectorAll('[data-testid="markdown-reply"] [role="group"][aria-label="Code Preview"]')].map(group=>({
                  editors:[...group.querySelectorAll('[role="textbox"][aria-label="Code editor"]')].map(editor=>({
                    inner_text:editor.innerText, text_content:editor.textContent, visible:!!editor.getClientRects().length,
                    children:[...editor.children].map(child=>({tag:child.tagName,text:child.textContent})).slice(0,100)})),
                  group_length:(group.innerText||group.textContent||'').length}))""")
                report['code_editor_observations'].append(observation)
                if any(editor.get('inner_text') or editor.get('text_content') for group in observation for editor in group['editors']):
                    break
                await asyncio.sleep(.5)
            messages = await adapter._evaluate(_MESSAGE_SNAPSHOT)
            report['synthetic_code_dom_shape'] = await adapter._evaluate(r"""requestId => {
              const root=[...document.querySelectorAll('[data-testid="markdown-reply"]')].find(n=>(n.innerText||n.textContent||'').includes(requestId));
              const ui=new Set(['JSON','Copy','Copy code','Show more lines','Show less lines']);
              const shape=(n,depth)=>{
                if(depth<0)return {truncated:true};
                if(n.nodeType===Node.TEXT_NODE){const t=(n.textContent||'').trim();return {text:ui.has(t)?t:t.startsWith('<<<COPILOT_AGENT_V1')?'marker':t?'[payload-text]':'',length:t.length};}
                if(n.nodeType!==Node.ELEMENT_NODE)return {};
                const attrs={};for(const key of ['data-testid','data-test-id','role','class','aria-label'])if(n.hasAttribute(key))attrs[key]=n.getAttribute(key).slice(0,250);
                return {tag:n.tagName,attrs,children:[...n.childNodes].slice(0,80).map(c=>shape(c,depth-1))};
              };
              return root?shape(root,14):null;
            }""", args.request_id)
            report['synthetic_source_candidates'] = await adapter._evaluate(r"""requestId => {
              const result=[];
              const visit=(value,depth,seen)=>{
                if(typeof value==='string') {if(value.includes(requestId)&&value.includes('<<<COPILOT_AGENT_V1_BEGIN>>>')&&value.includes('<<<COPILOT_AGENT_V1_END>>>')) result.push(value); return;}
                if(!value||typeof value!=='object'||depth<0||seen.has(value))return;
                seen.add(value);
                if(Array.isArray(value)){for(const v of value.slice(0,30))visit(v,depth-1,seen);return;}
                for(const key of ['children','props','content','markdown','text','source','message'])if(Object.prototype.hasOwnProperty.call(value,key))visit(value[key],depth-1,seen);
              };
              for(const node of document.querySelectorAll('[data-testid="markdown-reply"]')) {
                if(!(node.innerText||node.textContent||'').includes(requestId))continue;
                const root=node.closest('[data-testid="copilot-message-reply-div"],[data-testid="copilot-message-div"],[data-testid="lastChatMessage"],.fai-CopilotMessage__content')||node;
                const key=Object.keys(node).find(k=>k.startsWith('__reactFiber$'));
                let fiber=key&&node[key];
                for(let i=0;fiber&&i<16;i++,fiber=fiber.return){
                  if(fiber.stateNode instanceof Element&&!root.contains(fiber.stateNode))break;
                  visit(fiber.memoizedProps,5,new Set());
                }
              }
              return [...new Set(result)].slice(0,5);
            }""", args.request_id)
            for index, source in enumerate(report.pop('synthetic_source_candidates')):
                (directory / f'synthetic-source-{index}.txt').write_text(source, encoding='utf-8')
                report.setdefault('source_metrics', []).append({'length':len(source), 'escaped_windows_prefix':r'C:\\Users' in source})
            report['conversation_metadata'] = [{key:item[key] for key in ('key','order','role')} | {'length':len(item['text']), 'contains_request':args.request_id in item['text']} for item in messages]
            text = fresh_assistant(messages, {}, 13, args.request_id)
            report['candidate_length'] = len(text)
            (directory / 'synthetic-candidate.txt').write_text(text, encoding='utf-8')
            try:
                response = parse_response(text, args.session_id, args.request_id, ToolRegistry())
                report['candidate_protocol'] = {'valid':True, 'response_type':response['response_type'], 'tool_names':[item['name'] for item in response['tool_requests']]}
            except Exception as exc:
                report['candidate_protocol'] = {'valid':False, 'error':str(exc)[:1000]}
            report['status'] = 'passed' if text else 'blocked'
            print(json.dumps({'status':report['status'],'evidence':str(directory/'evidence.json'), 'candidate_protocol':report['candidate_protocol'], 'source_metrics':report.get('source_metrics', [])}, indent=2))
            return 0 if text else 1
        if args.code_dom:
            import html
            from copilot_agent.protocol import BEGIN, END
            payload = {'request_id':'synthetic-code-dom', 'path':r'C:\synthetic\workspace', 'script':"print('approval-test')", 'literal':'Show more lines','label':'JSON'}
            sample = (ROOT / 'tests' / 'fixtures' / 'code_preview.html').read_text(encoding='utf-8')
            await adapter.tool_page.set_content(sample)
            messages = await adapter.tool_page.evaluate(_MESSAGE_SNAPSHOT)
            candidate = fresh_assistant(messages, {}, -1, 'synthetic-code-dom')
            extracted = candidate[candidate.index(BEGIN)+len(BEGIN):candidate.index(END)].strip()
            report['code_dom'] = {'literal_json_preserved':json.loads(extracted)==payload,
                                   'backslashes_preserved':r'C:\\synthetic\\workspace' in extracted,
                                   'copy_chrome_excluded':'Copy code' not in candidate}
            if not all(report['code_dom'].values()):
                raise ValueError('Synthetic code-block DOM extraction did not preserve literal JSON.')
            payload.update(literal='Show more lines', label='JSON')
            wire=json.dumps(payload, indent=2)
            def editor_sample(content):
                return ('<div data-testid="chatQuestion">synthetic-code-dom</div>'
                  '<div data-testid="markdown-reply"><p>'+html.escape(BEGIN)+'</p>'
                  '<div role="group" aria-label="Code Preview"><div aria-label="JSON">JSON</div>'
                  '<button aria-label="Copy code">Copy code</button><div role="textbox" aria-label="Code editor">'+content+
                  '</div><button>Show more lines</button></div><p>'+html.escape(END)+'</p></div>')
            await adapter.tool_page.set_content(editor_sample(''))
            pending=await adapter.tool_page.evaluate(_MESSAGE_SNAPSHOT)
            require_empty=not fresh_assistant(pending, {}, -1, 'synthetic-code-dom')
            await adapter.tool_page.set_content(editor_sample(html.escape(wire)))
            rendered=await adapter.tool_page.evaluate(_MESSAGE_SNAPSHOT)
            candidate=fresh_assistant(rendered, {}, -1, 'synthetic-code-dom')
            extracted=candidate[candidate.index(BEGIN)+len(BEGIN):candidate.index(END)].strip()
            report['scriptor_dom']={'unhydrated_rejected':require_empty, 'exact_literals_preserved':json.loads(extracted)==payload,
                                    'chrome_excluded':extracted.startswith('{') and extracted.endswith('}')}
            if not all(report['scriptor_dom'].values()):
                raise ValueError('Observed-shaped Code Preview fixture failed literal/hydration capture checks.')
        if args.inspect:
            await adapter._open_picker()
            await adapter.page.wait_for_timeout(1200)
            report['picker_dom'] = await adapter._evaluate(r"""() => ({
              radios:[...document.querySelectorAll('[role="menuitemradio"],[role="radio"]')].map(n=>({label:(n.innerText||'').slice(0,200),visible:!!(n.offsetWidth||n.offsetHeight),role:n.getAttribute('role')})),
              triggers:[...document.querySelectorAll('[data-testid*="gptSubMenu"],[data-test-id*="gptSubMenu"]')].map(n=>({tag:n.tagName,id:n.getAttribute('data-testid')||n.getAttribute('data-test-id'),visible:!!(n.offsetWidth||n.offsetHeight)})),
              menus:[...document.querySelectorAll('[role="menu"]')].map(n=>({text:(n.innerText||'').slice(0,2000),visible:!!(n.offsetWidth||n.offsetHeight)})),
              picker:[...document.querySelectorAll('#gptModeSwitcher,button[aria-label*="Model Selector" i]')].map(n=>({tag:n.tagName,text:(n.innerText||'').slice(0,200),expanded:n.getAttribute('aria-expanded')}))})""")
            print(json.dumps(report['picker_dom'], indent=2))
            await adapter.page.keyboard.press('Escape')
        discovered = await adapter.discover_models()
        report['models'] = [{key: item[key] for key in ('label','provider','enabled','checked')} for item in discovered]
        enabled = [item for item in model_rank(discovered) if item['enabled']]
        if args.model:
            selected = args.model
        else:
            gpt = [item for item in enabled if 'gpt' in item['label'].lower()]
            if not gpt:
                raise ValueError('No enabled GPT models discovered. Specify --model with an exact discovered provider label; cross-provider ranking requires user choice.')
            selected = gpt[0]['label']
        chosen = await adapter.select_model(selected)
        report['selected'] = {key: chosen[key] for key in ('label','provider','enabled')}
        report['selection_verified_checked_radio'] = adapter.model_label == selected
        # Retain only the picker control crop: no account names or conversation metadata.
        picker = await adapter._visible(PICKER_SELECTOR)
        if picker is not None:
            await picker.screenshot(path=str(directory / 'selected-model.png'), timeout=5000)
            report['screenshot'] = 'selected-model.png'
        report['tool_context_isolated'] = adapter.tool_page.context != adapter.page.context
        if args.wire_probe:
            request_id = uuid.uuid4().hex
            session_id = uuid.uuid4().hex
            report['test'] = 'one_authorized_synthetic_fenced_wire_probe'
            report['no_messages_or_uploads'] = False
            report['uploads'] = 0
            report['request_id'], report['session_id'] = request_id, session_id
            payload = {'protocol_version':'1.0','session_id':session_id,'request_id':request_id,
                       'path':r'C:\synthetic\workspace','literal':'Show more lines','label':'JSON'}
            instruction = {'request_id':request_id, 'instruction':'Synthetic read-only UI transport test. Return exactly <<<COPILOT_AGENT_V1_BEGIN>>> on its own line, one fenced json code block containing the exact payload below, then <<<COPILOT_AGENT_V1_END>>> on its own line. Do not call tools, request execution, or change any files. Preserve literal strings and JSON backslashes.', 'payload':payload}
            def commit():
                report['copilot_message_count'] = 1
            text = await adapter.exchange(json.dumps(instruction), request_id, on_submitted=commit)
            report['authorized_conversation_url'] = adapter.page.url
            (directory/'synthetic-candidate.txt').write_text(text,encoding='utf-8')
            report['synthetic_code_dom_shape'] = await adapter._evaluate(r"""requestId => {
              const root=[...document.querySelectorAll('[data-testid="markdown-reply"]')].find(n=>(n.innerText||n.textContent||'').includes(requestId));
              const ui=new Set(['JSON','Copy','Copy code','Show more lines','Show less lines']);
              const shape=(n,depth)=>{
                if(depth<0)return {truncated:true};
                if(n.nodeType===Node.TEXT_NODE){const t=(n.textContent||'').trim();return {text:ui.has(t)?t:t.startsWith('<<<COPILOT_AGENT_V1')?'marker':t?'[payload-text]':'',length:t.length};}
                if(n.nodeType!==Node.ELEMENT_NODE)return {};
                const attrs={};for(const key of ['data-testid','data-test-id','role','class','aria-label'])if(n.hasAttribute(key))attrs[key]=n.getAttribute(key).slice(0,250);
                return {tag:n.tagName,attrs,children:[...n.childNodes].slice(0,80).map(c=>shape(c,depth-1))};
              };
              return root?shape(root,16):null;
            }""", request_id)
            report['status'] = 'passed'
        if args.composer:
            from copilot_agent.state import SessionState
            from copilot_agent.tools import ToolRegistry
            from copilot_agent.findings import Findings
            from copilot_agent.prompts import PromptBuilder
            state = SessionState(directory / 'synthetic-session')
            registry = ToolRegistry()
            builder = PromptBuilder(cfg, registry, state, Findings(state.directory))
            text, _ = builder.build('initialize', 'Synthetic no-send composer preservation check.', uuid.uuid4().hex)
            editor = await adapter._editor()
            await editor.fill(text, timeout=5000)
            values = await editor.evaluate("n => ({value:n.value, innerText:n.innerText, textContent:n.textContent})")
            report['composer'] = {name: composer_comparison(text, value) for name,value in values.items() if isinstance(value,str)}
            report['synthetic_editor_suffix'] = {name:[f'U+{ord(char):04X}' for char in value[-12:]] for name,value in values.items() if isinstance(value,str)}
            report['synthetic_editor_tail_dom'] = await editor.evaluate("n => n.outerHTML.slice(-350)")
            actual = await adapter._editor_text(editor)
            report['composer_normalized'] = composer_comparison(text, actual)
            report['composer_preserved'] = composer_comparison(text, actual)['matches']
            if not report['composer_preserved']:
                raise ValueError('Synthetic initialization JSON did not preserve literal values in the editor.')
        report['status'] = 'passed'
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        # Error messages from this adapter are human-safe; do not dump UI/account contents.
        report['error'] = str(exc)[:600]
    finally:
        await adapter.close()
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        (directory / 'evidence.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'status':report['status'], 'evidence':str(directory / 'evidence.json'),
                      'selected': report.get('selected'), 'error':report.get('error')}, indent=2))
    return 0 if report['status'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--port', type=int, default=9333)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--model')
    parser.add_argument('--inspect', action='store_true', help='Record model-menu-only DOM metadata; no account metadata.')
    parser.add_argument('--composer', action='store_true', help='Fill synthetic initialization JSON and verify preservation without sending or uploading.')
    parser.add_argument('--conversation', help='Read-only inspect an explicitly authorized synthetic Copilot conversation.')
    parser.add_argument('--session-id')
    parser.add_argument('--request-id')
    parser.add_argument('--code-dom', action='store_true', help='Verify literal fenced-code DOM extraction on an owned local tool page, with no requests/sends.')
    parser.add_argument('--latest-initialization', action='store_true', help='Identify only an initialization-title history link verified by the supplied synthetic request ID.')
    parser.add_argument('--wire-probe', action='store_true', help='Explicitly authorized one-message synthetic fenced-wire test, no uploads or tools/code execution.')
    parser.add_argument('--startup-timeout', type=float, default=45)
    return asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    raise SystemExit(main())
