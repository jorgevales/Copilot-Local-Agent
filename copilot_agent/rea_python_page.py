"""Passive owned-page structure and network metadata without page content values."""
from __future__ import annotations

import asyncio
from collections import Counter
from urllib.parse import urlsplit

from .rea_python_capture import _tick, safe_url


# Deliberately independent of browser.inspect's richer collector: its labels,
# titles and arbitrary form identifiers are unsuitable for value-free REA output.
SNAPSHOT = r"""() => {
 const maxNodes=2000, tags={},roles={},types={}, navigation=[],forms=[],scripts=[];
 const allowedTags=new Set(['a','button','input','textarea','select','form','iframe','nav','main','section','canvas','video','audio','table','dialog','svg','script']);
 const allowedRoles=new Set(['button','link','textbox','checkbox','radio','combobox','listbox','option','menu','menuitem','navigation','main','dialog','tab','tabpanel','tree','grid','table','heading','alert','status','search']);
 const allowedTypes=new Set(['text','password','email','hidden','search','number','tel','url','submit','button','checkbox','radio','date','file','reset','range','color','time','datetime-local','month','week','image']);
 const roots=[document];let visited=0,shadowRoots=0,truncated=false;
 while(roots.length&&visited<maxNodes){const root=roots.shift();const walker=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT);let n;
  while((n=walker.nextNode())){if(visited>=maxNodes){truncated=true;break;}visited++;
   if(n.shadowRoot){roots.push(n.shadowRoot);shadowRoots++;}const tag=n.tagName.toLowerCase();
   if(allowedTags.has(tag))tags[tag]=(tags[tag]||0)+1;const role=n.getAttribute('role');if(allowedRoles.has(role))roles[role]=(roles[role]||0)+1;
   if(tag==='input'){const type=allowedTypes.has(n.type)?n.type:'other';types[type]=(types[type]||0)+1;}
   if(tag==='a'&&navigation.length<200&&n.href)navigation.push(n.href);
   if(tag==='form'&&forms.length<100)forms.push({action:n.action,method:['get','post','dialog'].includes(n.method)?n.method:'other',field_count:Math.min(n.elements.length,2000)});
   if(tag==='script'&&scripts.length<200)scripts.push({src:n.src||null,inline:!n.src,module:n.type==='module'});
  }
 }
 if(roots.length)truncated=true;
 const resources=performance.getEntriesByType('resource').slice(0,1000).map(r=>({url:r.name,kind:['fetch','xmlhttprequest','script','css','img','link','iframe','other','navigation'].includes(r.initiatorType)?r.initiatorType:'other',duration_ms:Math.round(r.duration),bytes:Number.isFinite(r.transferSize)?r.transferSize:0}));
 const framework_hints=[];
 if(document.querySelector('[data-reactroot]')||Object.prototype.hasOwnProperty.call(window,'__REACT_DEVTOOLS_GLOBAL_HOOK__'))framework_hints.push('React');
 if(document.querySelector('[data-v-app]'))framework_hints.push('Vue');if(document.querySelector('[ng-version]'))framework_hints.push('Angular');
 if(document.getElementById('__NEXT_DATA__'))framework_hints.push('Next');if(Object.prototype.hasOwnProperty.call(window,'__NUXT__'))framework_hints.push('Nuxt');
 return {url:location.href,ready_state:['loading','interactive','complete'].includes(document.readyState)?document.readyState:'unknown',dom:{visited_elements:visited,limit:maxNodes,truncated,tags,roles,input_types:types,open_shadow_roots:shadowRoots},forms,scripts,navigation,resources,framework_hints,resource_limit_reached:performance.getEntriesByType('resource').length>1000};
}"""


async def inspect_page(page, observation_ms: int = 500, budget=None) -> dict:
    """Only observe the supplied page; no browser creation, navigation or mutation."""
    _tick(budget)
    if not isinstance(observation_ms, int) or isinstance(observation_ms, bool) or not 0 <= observation_ms <= 3000:
        raise ValueError('Page observation bound must be 0..3000 milliseconds')
    before = page.url
    network, unknowns = [], []
    response_count = 0

    def response_seen(response):
        nonlocal response_count
        response_count += 1
        if len(network) >= 500:
            return
        try:
            request = response.request
            url = safe_url(response.url)
            if url:
                method = request.method
                kind = request.resource_type
                status = response.status
                network.append({'route': url, 'method': method if method in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD') else 'OTHER',
                                'resource_type': kind if kind in ('document', 'stylesheet', 'image', 'media', 'font', 'script', 'xhr', 'fetch', 'websocket', 'other') else 'other',
                                'status_class': str(status // 100) + 'xx' if isinstance(status, int) and 100 <= status <= 599 else 'unknown'})
        except Exception:
            # Response metadata may disappear if a page closes. Never retain the exception.
            return

    attached = False
    try:
        if callable(getattr(page, 'on', None)):
            page.on('response', response_seen)
            attached = True
        else:
            unknowns.append('Response event metadata is unavailable for this page adapter.')
        structure = await asyncio.wait_for(page.evaluate(SNAPSHOT), 10)
        if observation_ms:
            await asyncio.sleep(observation_ms / 1000)
        _tick(budget)
    finally:
        if attached:
            try:
                page.remove_listener('response', response_seen)
            except Exception:
                raise RuntimeError('REA page response listener cleanup could not be confirmed') from None
    if not isinstance(structure, dict) or not isinstance(structure.get('dom'), dict):
        raise ValueError('Owned page did not return a usable structural observation')
    # Every string returned by the document is validated before retaining it.
    tags = {'a', 'button', 'input', 'textarea', 'select', 'form', 'iframe', 'nav', 'main', 'section', 'canvas', 'video', 'audio', 'table', 'dialog', 'svg', 'script'}
    roles = {'button', 'link', 'textbox', 'checkbox', 'radio', 'combobox', 'listbox', 'option', 'menu', 'menuitem', 'navigation', 'main', 'dialog', 'tab', 'tabpanel', 'tree', 'grid', 'table', 'heading', 'alert', 'status', 'search'}
    types = {'text', 'password', 'email', 'hidden', 'search', 'number', 'tel', 'url', 'submit', 'button', 'checkbox', 'radio', 'date', 'file', 'reset', 'range', 'color', 'time', 'datetime-local', 'month', 'week', 'image', 'other'}
    dom = structure['dom']
    counts = lambda value, allowed: {key: min(count, 2000) for key, count in value.items() if key in allowed and isinstance(count, int) and 0 <= count <= 100000} if isinstance(value, dict) else {}
    dom_result = {'tag_counts': counts(dom.get('tags'), tags), 'role_counts': counts(dom.get('roles'), roles), 'input_type_counts': counts(dom.get('input_types'), types),
                  'visited_elements': dom.get('visited_elements') if isinstance(dom.get('visited_elements'), int) and 0 <= dom['visited_elements'] <= 2000 else 0,
                  'node_limit': 2000, 'truncated': bool(dom.get('truncated')), 'open_shadow_roots_only': True}
    resources = []
    for item in structure.get('resources', [])[:1000]:
        _tick(budget)
        if not isinstance(item, dict):
            continue
        url = safe_url(item.get('url'))
        if url:
            kind = item.get('kind')
            duration = item.get('duration_ms')
            resources.append({'route': url, 'kind': kind if kind in ('fetch', 'xmlhttprequest', 'script', 'css', 'img', 'link', 'iframe', 'other', 'navigation') else 'other',
                              'duration_ms': duration if isinstance(duration, int) and 0 <= duration <= 86400000 else None})
    scripts = [{'route': safe_url(item.get('src')), 'inline': bool(item.get('inline')), 'module': bool(item.get('module'))}
               for item in structure.get('scripts', [])[:200] if isinstance(item, dict)]
    forms = [{'action': safe_url(item.get('action')), 'method': item.get('method') if item.get('method') in ('get', 'post', 'dialog') else 'other',
              'field_count': item.get('field_count') if isinstance(item.get('field_count'), int) and 0 <= item['field_count'] <= 2000 else 0}
             for item in structure.get('forms', [])[:100] if isinstance(item, dict)]
    navigation = list(dict.fromkeys(value for item in structure.get('navigation', [])[:200] if (value := safe_url(item))))
    frame_origins = Counter()
    frames = getattr(page, 'frames', [])
    for frame in frames[:100]:
        url = safe_url(frame.url)
        if url:
            parsed = urlsplit(url)
            frame_origins[parsed.scheme + '://' + parsed.netloc] += 1
    if not network:
        unknowns.append('No completed response was observed during the bounded window; prior request methods/statuses are unavailable.')
    if before != page.url:
        unknowns.append('The page navigated independently during observation; evidence is not an atomic snapshot.')
    if dom_result['truncated'] or structure.get('resource_limit_reached') or response_count > 500 or len(frames) > 100:
        unknowns.append('At least one document, resource, response or frame observation limit was reached.')
    return {'status': 'partial', 'confidence': 'observed', 'findings': {
                'url': safe_url(structure.get('url')), 'origin_classification': 'http_or_https' if safe_url(structure.get('url')) else 'unsupported_or_opaque',
                'ready_state': structure.get('ready_state') if structure.get('ready_state') in ('loading', 'interactive', 'complete') else 'unknown',
                'dom': dom_result, 'frames': {'observed_count': min(len(frames), 100), 'origins': dict(frame_origins)},
                'forms': forms, 'navigation_routes': navigation, 'scripts': scripts, 'resources': resources,
                'network_responses': network, 'framework_hints': [item for item in structure.get('framework_hints', []) if item in ('React', 'Vue', 'Angular', 'Next', 'Nuxt')],
                'observation_ms': observation_ms}, 'unknowns': unknowns,
            'limitations': ['Passive structural evidence only; framework hints are not proof of framework version.',
                            'No page text, labels, field names/values, headers, payloads, cookies, storage or script source is collected.',
                            'Closed shadow roots, inaccessible frame documents and server implementation are not inspected.',
                            'Routes are conservative templates; no explicit network request or page mutation is performed.'],
            'locations': ['owned_page.document', 'owned_page.performance', 'owned_page.response_events']}
