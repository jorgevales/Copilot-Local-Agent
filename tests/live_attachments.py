"""Opt-in real Copilot upload/readback acceptance; never execute delivered code.

Only the file-picker backend is injected. Browser submission/capture, source
validation, approval binding and upload staging use the production components.
Importing this module sends nothing. Fixtures/reports/screenshots are retained.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copilot_agent.attachments import AttachmentQueue
from copilot_agent.browser import BrowserAdapter
from copilot_agent.config import Config
from copilot_agent.file_picker import select_files
from copilot_agent.logging_utils import redact
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.persistence import write_json
from copilot_agent.policy import PathPolicy
from copilot_agent.state import SessionState,canonical_hash
from copilot_agent.tools import ToolRegistry


def require(condition,message):
    if not condition: raise AssertionError(message)


def file_record(path,cap):
    path=Path(path);size=path.stat().st_size
    require(path.is_file() and size<=cap,'Evidence file is not a bounded regular file')
    digest=hashlib.sha256();consumed=0
    with path.open('rb') as stream:
        while block:=stream.read(65536):
            consumed+=len(block)
            require(consumed<=cap,'Evidence file grew beyond its size cap')
            digest.update(block)
    return {'path':str(path),'name':path.name,'size':consumed,'sha256':digest.hexdigest()}


class RecordedBrowser:
    """Observe production exchanges without modifying their requests or replies."""
    def __init__(self,adapter,report,save,cap):
        self.adapter,self.report,self.save,self.cap=adapter,report,save,cap

    def __getattr__(self,name): return getattr(self.adapter,name)

    async def exchange(self,text,request_id,attachments=(),on_submitted=None):
        entry={'request_id':request_id,'kind':json.loads(text).get('kind'),'attachments':[file_record(path,self.cap) for path in attachments],'committed':False,'captured':False}
        self.report['actual_exchanges'].append(entry);self.save()
        def committed():
            entry['committed']=True
            outcome=on_submitted() if on_submitted is not None else None
            self.save()
            return outcome
        try:
            raw=await self.adapter.exchange(text,request_id,attachments=attachments,on_submitted=committed)
            entry['captured']=True;self.save()
            return raw
        except Exception as error:
            entry['error']=str(error);self.save();raise


async def run(args):
    if not args.live: raise SystemExit('Explicit --live is required; this harness uploads harmless synthetic files to Copilot.')
    config=Config.load(args.config)
    require(not config.created_sync_enabled,'Use a test config with Created monitoring disabled; this acceptance does not access Created folders')
    token=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    directory=config.runtime_dir/'acceptance'/('attachments-'+token)
    directory.mkdir(parents=True,exist_ok=False)
    report_path=Path(args.report).expanduser().absolute() if args.report else directory/'report.json'
    if args.report:
        require(config.storage_dir is not None,'An explicit report path requires selected OneDrive storage')
        PathPolicy([config.storage_dir],excluded_roots=[config.profile_dir]).resolve(report_path)
        require(not report_path.exists(),'Choose a new report path; an earlier report is retained')
    report={'status':'incomplete','directory':str(directory),'started_at':datetime.now(timezone.utc).isoformat(),'model_requested':args.model,'steps':[],'actual_exchanges':[],'approvals':[],'feedback':[],'limitations':['Native Windows file-picker interaction is not exercised: the picker backend returns explicit synthetic paths.','Internal Copilot computation is not observable. The request prohibits integrated execution; all local tool approvals are denied and any observed tool request fails this test. Production read-only tool policy remains in force.'],'created_folder_access':False,'code_execution_authorized':False}
    def save(): write_json(report_path,redact(report))
    def display(message):
        message=redact(str(message))
        actors=re.findall(r'^\[[^\]]+\] \[([^\]]+)\]',message,re.M)
        report['feedback'].append({'actors':list(dict.fromkeys(actors)),'message':message})
        print(message,flush=True)
    save()
    adapter=BrowserAdapter(config)
    browser=RecordedBrowser(adapter,report,save,config.max_attachment_bytes)
    engine=None;state=None
    sources={};expected={};approval_used=False
    def decide(preview):
        nonlocal approval_used
        plan=preview.get('complete_pending_plan',{})
        accepted=False
        local_call={'call_id':preview.get('current_call_id'),'name':'local_attachment','version':'1.0','arguments':plan}
        exact_call=preview.get('call_hash')==canonical_hash({'plan_hash':canonical_hash(plan),'call':local_call})
        if not approval_used and exact_call and set(plan)=={'action','upload_id','files','destination'} and plan.get('upload_id') and plan.get('action')=='attach_user_files' and plan.get('destination')==config.copilot_url:
            files=plan.get('files',[])
            actual={record.get('path'):{key:record.get(key) for key in ('name','size','sha256')} for record in files}
            accepted=len(files)==2 and actual==expected
        report['approvals'].append({'current_call_id':preview.get('current_call_id'),'plan_hash':preview.get('plan_hash'),'call_hash':preview.get('call_hash'),'decision':'once' if accepted else 'deny','complete_pending_plan':plan})
        if accepted: approval_used=True
        save()
        return 'once' if accepted else 'deny'
    try:
        inputs=config.workspace_dir/'acceptance-inputs'/uuid.uuid4().hex
        inputs=PathPolicy(config.allowed_roots,excluded_roots=[config.profile_dir]).resolve(inputs)
        inputs.mkdir(parents=True,exist_ok=False)
        sources={inputs/'context.txt':b'the project colour is cobalt-317\n',inputs/'context.py':b'# code-context-482\nprint("not executed")\n'}
        for path,content in sources.items():
            with path.open('xb') as stream: stream.write(content)
        state=SessionState(directory/'session')
        engine=Orchestrator(config,browser,ToolRegistry(),state,approval_decider=decide,display=display)
        engine.prompts.verify_guidance()
        initial=engine.prompts.initial_attachments()
        report['startup_documents']=[file_record(path,config.max_attachment_bytes) for path in initial]
        report['source_guidance_manifest']=state.data.get('guidance_manifest',[])
        report['startup_source_bundle_status']=state.data.get('guidance_bundle')
        save()
        require(len(initial)==8,'The strong eight-document startup is not ready; no live submission attempted')
        source_queue=engine.attachment_queue()
        require(isinstance(source_queue,AttachmentQueue),'Production attachment queue is unavailable')
        picker_options={}
        def picker_backend(**options):
            picker_options.update(options)
            return [str(path) for path in sources]
        selected=select_files(source_queue.account_root,picker_backend=picker_backend)
        records=source_queue.add(selected)
        require(set(source_queue.paths())==set(sources),'Picker/queue changed the explicitly selected sources')
        require(source_queue.verify()==records,'Pre-upload source verification failed')
        expected={record['path']:{key:record[key] for key in ('name','size','sha256')} for record in records}
        report['picker']={'mode':'injected backend through production select_files','options':picker_options,'selected_paths':[str(path) for path in selected]}
        report['selected_sources']=records
        save()
        await adapter.start()
        models=await adapter.discover_models()
        report['models_discovered']=models
        require(any(item['label']==args.model and item.get('enabled',True) for item in models),'Exact requested model is unavailable')
        await adapter.select_model(args.model)
        initialized=await engine.initialize()
        report['initialization_response']=initialized
        require(state.message_count==1,'Initialization required correction messages; first-shot readiness is blocked')
        require(len(report['actual_exchanges'])==1 and report['actual_exchanges'][0]['committed'],'First initialization submission was not uniquely committed')
        first=report['actual_exchanges'][0]['attachments']
        require(len(first)==8 and first==report['startup_documents'],'Actual initialization uploads differ from the eight verified documents')
        require(not state.data['calls'],'Initialization requested tools')
        report['steps'].append({'name':'first-shot eight-document real initialization','status':'passed','message_count':state.message_count,'actual_upload_count':len(first)})
        save()
        result=await engine.turn('Read both uploaded input files as request context. State the project colour from the text file and the distinct comment token from the Python source file. Use no local tools, Code Runner, integrated code execution or file creation. The source was uploaded as text with exact original bytes; read it without executing it. Return a final no-tool envelope.',attachments=source_queue.paths())
        report['readback_response']=result
        require(result.get('response_type')=='final' and result.get('completion_status')=='complete','Readback did not complete in a final envelope')
        reply=result.get('user_response','')
        require('cobalt-317' in reply and 'code-context-482' in reply,'Copilot did not read both file-only sentinels')
        require(approval_used and len(report['approvals'])==1 and report['approvals'][0]['decision']=='once','The exact attachment-only approval was not used once')
        require(not state.data['calls'],'A tool call was requested or executed during no-tool attachment readback')
        user_exchanges=[item for item in report['actual_exchanges'] if item['kind']=='user_turn']
        require(len(user_exchanges)==1 and user_exchanges[0]['committed'],'The user attachment request was not uniquely committed')
        uploads=user_exchanges[0]['attachments']
        require(len(uploads)==2,'The user turn did not upload exactly two selected files')
        by_name={item['name']:item for item in uploads}
        require(set(by_name)=={'context.txt','context.py.txt'},'Python source was not staged under the expected text filename')
        for source,original in sources.items():
            require(source.read_bytes()==original,'A selected source file changed')
            uploaded=by_name[source.name if source.suffix=='.txt' else source.name+'.txt']
            stage=Path(uploaded['path'])
            require(stage!=source and stage.is_relative_to(state.directory/'approved_uploads'),'User attachment was not an approved upload snapshot')
            require(stage.read_bytes()==original and uploaded['sha256']==hashlib.sha256(original).hexdigest(),'Staged upload bytes differ from reviewed source bytes')
        report['steps'].append({'name':'two-file live upload and file-only sentinel readback','status':'passed','actual_upload_count':len(uploads),'source_bytes_unchanged':True,'staging_bytes_exact':True,'tool_calls':0})
        report['status']='passed_with_documented_test_scope'
    except Exception as error:
        report['status']='blocked'
        report['steps'].append({'name':'attachment acceptance','status':'blocked','error':str(error)})
        print('LIVE_ATTACHMENTS_BLOCKED: '+str(error),flush=True)
    finally:
        if state is not None:
            report['message_count']=state.message_count
            report['tool_calls']=state.data['calls']
            report['pending_submission']=state.data.get('pending_submission')
        try:
            if adapter.page and not adapter.page.is_closed():
                screenshot=directory/'masked-final.png'
                await adapter.page.screenshot(path=str(screenshot),full_page=False,timeout=10000,mask=[adapter.page.locator('nav,aside,header,[role="navigation"],[data-testid*="sidebar" i],button[aria-label*="account" i]')])
                report['masked_screenshot']=str(screenshot)
        except Exception as error:
            report['limitations'].append('Masked screenshot unavailable: '+str(error))
        try:
            if engine is not None: await engine.close()
            else: await adapter.close()
        except Exception as error:
            report['limitations'].append('Owned browser cleanup failed: '+str(error));report['status']='blocked'
        report['feedback_actors']=sorted({actor for item in report['feedback'] for actor in item['actors']})
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        save()
        print('LIVE_ATTACHMENTS_REPORT: '+str(report_path),flush=True)
    return 0 if report['status']=='passed_with_documented_test_scope' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--model',required=True,help='Exact enabled UI model label; no fallback selection')
    parser.add_argument('--report',type=Path,help='New retained report path inside selected OneDrive storage')
    raise SystemExit(asyncio.run(run(parser.parse_args())))
