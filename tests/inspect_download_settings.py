"""Explicit read-only inspection of this authorized Edge profile's download UI."""
import argparse, asyncio, json, sys
from datetime import datetime, timezone
from pathlib import Path
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copilot_agent.browser import BrowserAdapter
from copilot_agent.config import Config
from copilot_agent.persistence import write_json


async def run(args):
    if not args.live: raise SystemExit('Explicit --live required; read-only download settings inspection.')
    cfg=Config.load(args.config)
    adapter=BrowserAdapter(cfg)
    page=None
    folder=cfg.root/'runtime'/'acceptance'/('downloads-settings-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6])
    folder.mkdir(parents=True)
    try:
        await adapter.start()
        page=await adapter.context.new_page()
        await page.goto('edge://settings/downloads',wait_until='domcontentloaded',timeout=30000)
        await page.wait_for_timeout(5000)
        data=await page.evaluate(r"""() => {
          const roots=[document]; const nodes=[];
          for(let index=0;index<roots.length&&index<100;index++) {
            for(const n of roots[index].querySelectorAll('*')) { if(n.shadowRoot)roots.push(n.shadowRoot); nodes.push(n); }
          }
          const visible=n=>!!(n.offsetWidth||n.offsetHeight||n.getClientRects().length);
          return {url:location.href,text:nodes.filter(n=>visible(n)&&n.children.length===0&&!n.matches('style,script,svg,path')).map(n=>n.textContent||'').join('\n').slice(0,16000),
            structure:nodes.filter(n=>n.localName?.includes('settings')||n.id?.toLowerCase().includes('download')).map(n=>({tag:n.tagName,id:n.id})).slice(0,100),
            controls:nodes.filter(n=>visible(n)&&(n.matches('input,button,[role="switch"],[role="textbox"]')||n.id?.toLowerCase().includes('download')))
              .map(n=>({tag:n.tagName,id:n.id,label:n.getAttribute('aria-label'),role:n.getAttribute('role'),type:n.getAttribute('type'),value:n.value,
                       text:(n.innerText||'').slice(0,300),checked:n.getAttribute('aria-checked'),disabled:n.disabled})).slice(0,100)};
        }""")
        write_json(folder/'evidence.json',data)
        print(json.dumps({'evidence':str(folder/'evidence.json'),'settings':data},indent=2),flush=True)
    finally:
        if page: await page.close()
        await adapter.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--config',type=Path,required=True)
    asyncio.run(run(parser.parse_args()))
