"""Paired structural/visual evidence and explicit JavaScript on owned website tabs."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import time
import uuid

from .persistence import io_path, write_json
from .policy import PolicyError
from .web_navigation import get_navigation_page, _install_origin_guard


def _schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


INSPECTION_SPECS = {
    'browser.inspect': (_schema({
        'tab_id': {'type': 'string', 'maxLength': 100},
        'max_nodes': {'type': 'integer', 'minimum': 1, 'maximum': 2000},
        'full_page': {'type': 'boolean'},
    }), 'user_approval', 'Inspect an owned website tab: DOM, shadow DOM, control coordinates, forms, scripts, observed API/resource metadata and screenshot run concurrently. Automatically attach the screenshot to the next Copilot exchange; complete structure uses the existing large-result file transport. Resource evidence describes observed client/backend interfaces, not server source.'),
    'browser.javascript': (_schema({
        'tab_id': {'type': 'string', 'maxLength': 100},
        'expression': {'type': 'string', 'minLength': 1, 'maxLength': 50000},
        'argument': {},
        'timeout_ms': {'type': 'integer', 'minimum': 100, 'maximum': 30000},
    }, ('expression',)), 'user_approval', 'Evaluate an explicit JavaScript expression/function with an optional JSON argument in an owned website tab. Supports DOM/shadow DOM queries, app-state inspection and SPA navigation. Session approval applies; ordinary login stays manual. Returned values are evidence, not completion proof. Timeout/errors can leave uncertain effects; inspect/reconcile before replay.'),
}


SNAPSHOT = r"""({maxNodes}) => {
 const clean=value=>{try{const u=new URL(value,location.href);return ['http:','https:'].includes(u.protocol)?u.origin+u.pathname:null;}catch(_){return null;}};
 const nodes=[], roots=[document]; let seen=0;
 const visible=n=>!!n.getClientRects().length&&getComputedStyle(n).visibility!=='hidden';
 const selector=n=>{if(n.id)return '#'+CSS.escape(n.id);if(n.getAttribute('data-testid'))return '[data-testid='+JSON.stringify(n.getAttribute('data-testid'))+']';const parts=[];for(let p=n;p&&parts.length<12;p=p.parentElement){const tag=p.tagName.toLowerCase(),siblings=p.parentElement?[...p.parentElement.children].filter(s=>s.tagName===p.tagName):[p];parts.unshift(tag+':nth-of-type('+(siblings.indexOf(p)+1)+')');}return parts.join(' > ');};
 while(roots.length&&nodes.length<maxNodes){
  const root=roots.shift();
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT); let n;
  while((n=walker.nextNode())&&nodes.length<maxNodes){
   seen++; if(n.shadowRoot)roots.push(n.shadowRoot);
   if(!visible(n)||!n.matches('a,button,input,textarea,select,form,iframe,[role],[onclick],[tabindex],h1,h2,h3,nav,main,section,canvas'))continue;
   const r=n.getBoundingClientRect(), tag=n.tagName.toLowerCase();
   const secret=n.matches('input[type=password],input[type=hidden],[autocomplete=current-password],[autocomplete=new-password]');
   nodes.push({tag,role:n.getAttribute('role'),selector:selector(n),shadow:root!==document,
    label:secret?'[credential control]':String(n.getAttribute('aria-label')||n.labels?.[0]?.innerText||(/^(input|textarea|select)$/.test(tag)?'':n.innerText)||'').slice(0,300),
    type:n.getAttribute('type'),disabled:n.matches(':disabled')||n.getAttribute('aria-disabled')==='true',
    href:(n.getAttribute('href')||n.getAttribute('src'))?clean(n.getAttribute('href')||n.getAttribute('src')):null,
    box:{x:r.x,y:r.y,width:r.width,height:r.height}});
  }
 }
 const resources=performance.getEntriesByType('resource').map(r=>({url:clean(r.name),kind:r.initiatorType,duration_ms:Math.round(r.duration),bytes:r.transferSize}));
 const frameworks=['React','Vue','Angular','Next','Nuxt'].filter(n=>({React:!!document.querySelector('[data-reactroot]')||!!window.__REACT_DEVTOOLS_GLOBAL_HOOK__,Vue:!!document.querySelector('[data-v-app]'),Angular:!!document.querySelector('[ng-version]'),Next:!!document.getElementById('__NEXT_DATA__'),Nuxt:!!window.__NUXT__})[n]);
 return {url:clean(location.href),title:document.title,ready_state:document.readyState,
  viewport:{width:innerWidth,height:innerHeight,scroll_x:scrollX,scroll_y:scrollY,device_pixel_ratio:devicePixelRatio},
  dom:{nodes,visited_elements:seen,node_limit:maxNodes,limit_reached:nodes.length>=maxNodes,open_shadow_roots_only:true},
  application:{framework_hints:frameworks,
   forms:[...document.forms].map(f=>({id:f.id,action:clean(f.action),method:f.method,fields:[...f.elements].map(n=>({name:n.name,type:n.type,required:n.required}))})),
   scripts:[...document.scripts].map(s=>({src:s.src?clean(s.src):null,id:s.id,type:s.type,inline:!s.src})),
   resources:resources.filter(r=>r.url),api_candidates:resources.filter(r=>r.url&&['fetch','xmlhttprequest'].includes(r.kind)),
   limitation:'Observed browser interfaces and resource timing only; no server implementation, request bodies, cookies or storage captured.'}};
}"""


async def execute_inspection(name, args, context):
    if not context.get('approved'):
        raise PolicyError('Browser inspection/JavaScript needs the current execution authorization')
    page = get_navigation_page(context, args.get('tab_id'))
    await _install_origin_guard(page, context, page.url)
    before = page.url
    if name == 'browser.javascript':
        try:
            value = await asyncio.wait_for(page.evaluate(args['expression'], args.get('argument')),
                                           args.get('timeout_ms', 10000) / 1000)
        except Exception as error:
            return {'status': 'uncertain', 'side_effects_uncertain': True,
                    'tab_id': args.get('tab_id', 'tab-1'),
                    'error': {'code': 'operation_failed', 'message': str(error)[:3000] or type(error).__name__},
                    'next_action': 'Inspect the live DOM/screenshot and actual effects before retrying JavaScript.'}
        return {'status': 'evaluated', 'value': value, 'url_before': before, 'url_after': page.url,
                'tab_id': args.get('tab_id', 'tab-1'), 'side_effects_uncertain': False,
                'verification': 'JavaScript returned; verify the requested outcome independently.'}

    started = time.time()
    folder = Path(context['session_dir']) / 'browser_inspections'
    token = uuid.uuid4().hex
    png, document = folder / (token + '.png'), folder / (token + '.json')
    # Independent observations share one tab; never interleave a navigation/action here.
    structure, screenshot = await asyncio.gather(
        asyncio.wait_for(page.evaluate(SNAPSHOT, {'maxNodes': args.get('max_nodes', 300)}), 15),
        page.screenshot(type='png', full_page=args.get('full_page', False), timeout=15000,
                        mask=[page.locator('input[type=password],[autocomplete=current-password],[autocomplete=new-password]')]),
        return_exceptions=True)
    result = {'status': 'observed', 'tab_id': args.get('tab_id', 'tab-1'),
              'capture_started_at': started, 'capture_finished_at': time.time(),
              'same_url_during_capture': before == page.url, 'parallel_capture': True, 'side_effects_uncertain': False,
              'consistency': 'Concurrent observations, not an atomic snapshot. Reinspect if URL/layout changed.',
              'gaps': []}
    if before != page.url:
        result['gaps'].append('The page navigated during capture; repeat paired inspection on the settled page.')
    if isinstance(structure, BaseException):
        result['gaps'].append('Structural inspection failed: ' + type(structure).__name__)
    else:
        result['structure'] = structure
    if isinstance(screenshot, BaseException):
        result['gaps'].append('Screenshot failed: ' + type(screenshot).__name__)
    else:
        target = io_path(png)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(screenshot)
        result['screenshot'] = {'path': str(png), 'sha256': hashlib.sha256(screenshot).hexdigest(),
                                'bytes': len(screenshot), 'coordinate_space': 'DOM boxes are viewport CSS pixels'}
        pending = context.setdefault('pending_image_attachments', [])
        if len(pending) < 10:
            pending.append(str(png))
            result['screenshot']['queued_for_copilot'] = True
        else:
            result['screenshot']['queued_for_copilot'] = False
            result['gaps'].append('Screenshot saved; attach on a later exchange because the image queue is full.')
    if result['gaps']:
        result['status'] = 'partial'
    result['artifact_path'] = str(document)
    write_json(document, result)
    return result
