"""Explicit visible test of :new's production lifecycle; synthetic no-tool turns."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copilot_agent.app import start_new_session
from copilot_agent.browser import BrowserAdapter, model_rank
from copilot_agent.config import Config
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.persistence import write_json
from copilot_agent.state import SessionState
from copilot_agent.tools import ToolRegistry


async def run(args):
    if not args.live:
        raise SystemExit('Explicit --live required: synthetic messages and guidance uploads use the real UI.')
    config=Config.load(args.config)
    token=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]
    directory=config.runtime_dir/'acceptance'/('new-session-'+token)
    directory.mkdir(parents=True)
    report={'mode':'real visible independent-session UI test','steps':[],'status':'incomplete'}
    browser=BrowserAdapter(config)
    engine=None
    try:
        await browser.start()
        models=await browser.discover_models()
        model=(args.model if args.model else next(item for item in model_rank(models) if item.get('enabled', True))['label'])
        assert any(item['label']==model and item.get('enabled',True) for item in models)
        report['selected_model']=model
        await browser.select_model(model)
        old_state=SessionState(directory/'previous-session')
        engine=Orchestrator(config,browser,ToolRegistry(),old_state,approval_decider=lambda preview:'deny')
        await engine.initialize()
        await engine.turn('Synthetic independent-session test, old topic: say Previous session in a final no-tool envelope.')
        old_url=browser.page.url
        old_id=old_state.session_id
        old_count=old_state.message_count
        report['steps'].append({'name':'previous UI conversation','status':'passed','session_id':old_id,'url':old_url,'message_count':old_count})
        write_json(directory/'report.json',report)
        print('LIVE_NEW_SESSION: invoking production :new lifecycle',flush=True)
        engine=await start_new_session(config,engine,model)
        browser=engine.browser
        engine.approvals.decide=lambda preview:'deny'
        fresh=engine.state
        new_url=browser.page.url
        assert old_url!=new_url and '/conversation/' in new_url
        assert fresh.session_id!=old_id
        initialization_sends=[item for item in fresh.data['messages'] if item['role']=='copilot_outbound']
        assert fresh.message_count==len(initialization_sends)
        assert json.loads(initialization_sends[0]['content'])['kind']=='initialize'
        assert all(json.loads(item['content'])['kind']=='correction' for item in initialization_sends[1:])
        assert old_state.data['status']=='closed' and old_state.path.exists()
        assert all(not fresh.data[key] for key in ('requirements','decisions','calls','approvals','unresolved_questions'))
        assert not engine.findings.data['findings']
        outbound=next(item['content'] for item in fresh.data['messages'] if item['role']=='copilot_outbound')
        assert 'old topic' not in outbound and old_id not in outbound
        assert len(fresh.data['attachments'])==8
        assert len(fresh.data['guidance_bundle']['component_manifest'])==10
        report['steps'].append({'name':'fresh independent chat and authoritative state','status':'passed','session_id':fresh.session_id,'url':new_url,'session_directory':str(fresh.directory),'initialization_count':fresh.message_count,'guidance_attachments':len(fresh.data['attachments']),'old_context_excluded':True})
        result=await engine.turn('Synthetic new topic: say Fresh independent session in a final no-tool envelope.')
        assert result['response_type']=='final' and not fresh.data['calls']
        report['steps'].append({'name':'new topic response','status':'passed','user_response':result['user_response'],'message_count':fresh.message_count})
        result=await engine.turn('Synthetic verbose-feedback acceptance: request system.versions exactly once, then report its actual Python version. Explain your concise public decision summary and verification plan. Do not request hidden reasoning or any other tool.')
        assert result['response_type']=='final'
        assert len(fresh.data['calls'])==1 and next(iter(fresh.data['calls'].values()))['request']['name']=='system.versions'
        events=[json.loads(line) for line in (fresh.directory/'events.jsonl').read_text().splitlines()]
        feedback=[event for event in events if event['event']=='feedback']
        actors={event['actor'] for event in feedback}
        previews=[event for event in feedback if event.get('validated') is False]
        assert previews and {'Copilot (Agent)','Orchestrator','System','Tool/system.versions'}.issubset(actors)
        report['steps'].append({'name':'live public previews and attributed tool activity','status':'passed','actors':sorted(actors),
                              'public_preview_events':len(previews),'previews_during_generation':sum(event.get('generation_stopped') is False for event in previews),
                              'script_execution':False,'OneDrive_created_access':False})
        await browser.page.screenshot(path=str(directory/'new-chat.png'),mask=[browser.page.locator('nav,aside,header,[role="navigation"],[data-testid*="sidebar" i],button[aria-label*="account" i]')])
        report['status']='passed'
    except Exception as exc:
        report['steps'].append({'name':'independent session acceptance','status':'blocked','error':str(exc)})
    finally:
        if engine:
            await engine.close()
        else:
            await browser.close()
        report['steps'].append({'name':'owned session clean exit','status':'passed'})
        write_json(directory/'report.json',report)
        print('LIVE_NEW_SESSION_REPORT: '+str(directory/'report.json'),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--model',help='Exact discovered available UI label for this synthetic test.')
    asyncio.run(run(parser.parse_args()))
