"""Read-only verification/reporting recovery for an already completed execution.

Preserve the original report and consumed grant. Never prepare or execute source
again. Only a fresh compact execution receipt may be uploaded to a new real UI
conversation, with an exact one-use attachment approval.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copilot_agent.browser import BrowserAdapter
from copilot_agent.config import Config
from copilot_agent.logging_utils import redact
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.persistence import write_json
from copilot_agent.policy import PathPolicy,PolicyError
from copilot_agent.state import SessionState,canonical_hash
from copilot_agent.tools import ToolRegistry


def require(condition,message):
    if not condition: raise AssertionError(message)


def bounded_bytes(policy,path,cap=20*1024*1024):
    path=policy.resolve(path,True)
    require(path.is_file() and path.stat().st_size<=cap,'Evidence is not a bounded regular file')
    with path.open('rb') as stream: data=stream.read(cap+1)
    require(len(data)<=cap,'Evidence grew beyond its size cap')
    return path,data


def load_json(policy,path):
    path,data=bounded_bytes(policy,path)
    def unique(items):
        result={}
        for key,value in items:
            require(key not in result,'Duplicate keys in retained evidence')
            result[key]=value
        return result
    return path,json.loads(data.decode('utf-8'),object_pairs_hook=unique),data


def verify_completed_report(config,path):
    policy=PathPolicy([config.storage_dir],excluded_roots=[config.profile_dir])
    report_path,old,old_bytes=load_json(policy,path)
    require(old.get('status')=='blocked','Recovery is only for the retained blocked reporting result')
    calls=old.get('all_calls',{})
    require(isinstance(calls,dict),'Original report is missing actual persisted call records')
    executions=[call for call in calls.values() if call.get('request',{}).get('name')=='code_runner']
    require(len(executions)==1,'Original report does not have exactly one Code Runner execution')
    call=executions[0]
    require(call.get('result',{}).get('ok'),'Original Code Runner call was not successful')
    outcome=call['result']['result']
    require(outcome.get('status')=='completed' and outcome.get('stdout')=='download-run-test\n' and outcome.get('stderr')=='' and outcome.get('exit_code')==0,'Original execution output/exit evidence does not prove the completed synthetic run')
    require(not outcome.get('created_paths') and not outcome.get('outputs'),'Original print-only execution created unexpected outputs')
    pending_path,pending,_=load_json(policy,old['pending_approval_path'])
    prepared=pending['prepared_proposal'];plan=prepared['plan']
    source,source_bytes=bounded_bytes(policy,plan['source_path'],1024)
    source_hash=hashlib.sha256(source_bytes).hexdigest()
    require(source_bytes==plan['script'].encode('utf-8'),'Downloaded bytes differ from the approved script')
    require(ast.dump(ast.parse(source_bytes.decode('utf-8')),include_attributes=False)==ast.dump(ast.parse("print('download-run-test')\n"),include_attributes=False),'Original source is not the exact harmless single print statement')
    source_verification={'path':str(source),'sha256':source_hash,'size':len(source_bytes),'exact_script_bytes':True}
    require(outcome.get('source_verification')==source_verification and prepared.get('source_verification')==source_verification,'Saved preparation/runtime source verification differs from the actual preserved source')
    require(outcome.get('script_sha256')==source_hash and prepared['script_sha256']==source_hash and plan['source_sha256']==source_hash,'Source hashes do not agree')
    proposal_hash=hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()
    require(prepared['proposal_hash']==proposal_hash and outcome['proposal_hash']==proposal_hash,'Complete immutable proposal hashes differ')
    require(call['request']['arguments']['script'].encode('utf-8')==source_bytes,'Actual executed call used different script bytes')
    require(plan['read_paths']==[str(source)] and plan['permissions']==['read_files'] and all(not plan.get(key) for key in ('create_paths','expected_outputs','commands','subprocesses','network_destinations')),'Original declared scope differs from one source verification read and no external side effects')
    _,proposal_bytes=bounded_bytes(policy,prepared['script_path'],1024)
    require(proposal_bytes==source_bytes,'Retained immutable proposal file differs from the downloaded source')
    ledger_path,ledger,_=load_json(policy,pending['decision_file'])
    expected=dict(pending['approval_ledger_template'],decision='once')
    require(ledger==expected,'Consumed approval ledger differs from the exact explicit once template')
    require(ledger['proposal_hash']==proposal_hash and ledger['script_sha256']==source_hash and ledger['download_sha256']==source_hash and ledger['download_path']==str(source),'Consumed grant does not match actual source/proposal hashes')
    require(old.get('external_approval_observed')==ledger and old.get('code_execution_approved') is True,'Original report lacks matching explicit external approval evidence')
    approved=[item for item in old.get('approvals',[]) if item.get('name')=='code_runner' and item.get('decision')=='once']
    require(len(approved)==1,'Original execution did not have one exact once approval')
    receipt={'schema_version':'1.0','purpose':'Report an already completed execution; no new execution or grant is authorized','prior_overall_reporting_status':old['status'],'actual_local_execution_status':'completed','interpreter':'python_subset (restricted interpreter; no host Python or subprocess)','artifact':{'name':source.name,'sha256':source_hash,'size':len(source_bytes),'exact_script_bytes_verified':True,'preserved_source_verified':True},'proposal_hash':proposal_hash,'explicit_user_once_approval_verified_locally':True,'approval_already_consumed':True,'stdout':outcome['stdout'],'stderr':outcome['stderr'],'exit_code':outcome['exit_code'],'duration_seconds':outcome.get('duration_seconds'),'created_files':[],'new_execution_authorized':False}
    return receipt,{'old_report_path':str(report_path),'old_report_sha256':hashlib.sha256(old_bytes).hexdigest(),'pending_proposal_path':str(pending_path),'consumed_ledger_path':str(ledger_path),'source_path':str(source),'source_sha256':source_hash,'original_reporting_status':old['status']}


class NoExecutionRegistry(ToolRegistry):
    async def execute(self,name,args,context):
        raise PolicyError('Reporting recovery permits no tool execution and cannot reuse a consumed execution approval')


async def run(args):
    if not args.live: raise SystemExit('Explicit --live is required: this harness uploads one verified completed-execution receipt, never source execution.')
    config=Config.load(args.config)
    require(config.storage_dir is not None and not config.created_sync_enabled,'Use selected OneDrive storage with Created monitoring disabled')
    token=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    directory=config.runtime_dir/'acceptance'/('completed-run-recovery-'+token)
    directory.mkdir(parents=True,exist_ok=False)
    report_path=directory/'report.json'
    report={'status':'incomplete','directory':str(directory),'started_at':datetime.now(timezone.utc).isoformat(),'model_requested':args.model,'steps':[],'approvals':[],'feedback':[],'second_execution_authorized':False,'limitations':['Local execution is forbidden by a harness registry guard while the production tool catalogue and schemas remain intact.']}
    def save(): write_json(report_path,redact(report))
    def display(message):
        message=redact(str(message));report['feedback'].append(message);print(message,flush=True)
    save()
    adapter=BrowserAdapter(config);engine=None;state=None;approved_once=False;receipt_record=None;verified=None
    def decide(preview):
        nonlocal approved_once
        plan=preview.get('complete_pending_plan',{})
        exact_call={'call_id':preview.get('current_call_id'),'name':'local_attachment','version':'1.0','arguments':plan}
        call_matches=preview.get('call_hash')==canonical_hash({'plan_hash':canonical_hash(plan),'call':exact_call})
        files=plan.get('files',[])
        accepted=not approved_once and receipt_record is not None and call_matches and set(plan)=={'action','upload_id','files','destination'} and plan.get('action')=='attach_user_files' and plan.get('destination')==config.copilot_url and len(files)==1 and all(files[0].get(key)==receipt_record[key] for key in ('path','name','size','sha256'))
        if accepted: approved_once=True
        report['approvals'].append({'decision':'once' if accepted else 'deny','plan_hash':preview.get('plan_hash'),'call_hash':preview.get('call_hash'),'scope':'one compact receipt attachment only; never source execution','complete_pending_plan':plan});save()
        return 'once' if accepted else 'deny'
    try:
        receipt,verified=verify_completed_report(config,args.execution_report)
        report['prior_execution_evidence']=verified;report['prior_execution_receipt']=receipt
        receipt_dir=PathPolicy(config.allowed_roots,excluded_roots=[config.profile_dir]).resolve(config.workspace_dir/'acceptance-recovery'/uuid.uuid4().hex)
        receipt_dir.mkdir(parents=True,exist_ok=False)
        receipt_path=receipt_dir/'actual-execution-report.json'
        with receipt_path.open('x',encoding='utf-8',newline='\n') as stream: json.dump(receipt,stream,ensure_ascii=False,indent=2)
        state=SessionState(directory/'session')
        engine=Orchestrator(config,adapter,NoExecutionRegistry(),state,approval_decider=decide,display=display)
        engine.prompts.verify_guidance();startup=engine.prompts.initial_attachments()
        require(len(startup)==8,'Eight-document startup is not ready; no UI send attempted')
        report['startup_documents']=[{'name':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in startup]
        queue=engine.attachment_queue();receipt_record=queue.add([receipt_path])[0]
        report['new_compact_receipt']=receipt_record;save()
        await adapter.start()
        models=await adapter.discover_models();report['models_discovered']=models
        require(any(item['label']==args.model and item.get('enabled',True) for item in models),'Exact requested model is unavailable')
        await adapter.select_model(args.model)
        report['initialization_response']=await engine.initialize()
        require(state.message_count==1 and not state.data['calls'],'Fresh eight-document initialization was not first-shot readiness without tools')
        response=await engine.turn('Report the already completed execution from the attached actual local report. Include stdout download-run-test and exit 0, and state that it used the restricted interpreter. Do not request tools or a new download; do not execute the source again. The earlier once grant is consumed. This is a read-only reporting recovery, not a request to generate or deliver a file.',attachments=queue.paths())
        report['recovery_response']=response
        require(response.get('response_type')=='final' and response.get('completion_status')=='complete','Read-only execution report did not complete in a final envelope')
        reply=response.get('user_response','')
        require('download-run-test' in reply and ('exit' in reply.casefold()) and '0' in reply and any(word in reply.casefold() for word in ('restricted','subset')),'Recovered final reply omitted stdout, exit0 or restricted-interpreter scope')
        require(approved_once and len(report['approvals'])==1 and report['approvals'][0]['decision']=='once','Exactly one receipt attachment approval was not observed')
        require(not state.data['calls'],'Fresh reporting recovery requested tools; no successful recovery claim')
        source=Path(verified['source_path'])
        require(hashlib.sha256(source.read_bytes()).hexdigest()==verified['source_sha256'],'Already executed source changed during reporting recovery')
        require(hashlib.sha256(Path(verified['old_report_path']).read_bytes()).hexdigest()==verified['old_report_sha256'],'Original blocked report changed during recovery')
        report['steps'].append({'name':'prior execution and consumed approval verified without rerun','status':'passed'})
        report['steps'].append({'name':'fresh real UI final reports prior actual stdout and exit0','status':'passed','fresh_tool_calls':0,'second_execution':False})
        report['status']='passed_with_reporting_recovery'
    except Exception as error:
        report['status']='blocked';report['steps'].append({'name':'read-only completed-execution reporting recovery','status':'blocked','error':str(error)})
        print('LIVE_COMPLETED_RUN_RECOVERY_BLOCKED: '+str(error),flush=True)
    finally:
        if state is not None:
            report['message_count']=state.message_count;report['fresh_calls']=state.data['calls'];report['pending_submission']=state.data.get('pending_submission')
        try:
            if adapter.page and not adapter.page.is_closed():
                screenshot=directory/'masked-final.png'
                await adapter.page.screenshot(path=str(screenshot),full_page=False,timeout=10000,mask=[adapter.page.locator('nav,aside,header,[role="navigation"],[data-testid*="sidebar" i],button[aria-label*="account" i]')])
                report['masked_screenshot']=str(screenshot)
        except Exception as error: report['limitations'].append('Masked screenshot unavailable: '+str(error))
        try:
            if engine is not None: await engine.close()
            else: await adapter.close()
        except Exception as error: report['limitations'].append('Owned browser cleanup failed: '+str(error));report['status']='blocked'
        report['finished_at']=datetime.now(timezone.utc).isoformat();save()
        print('LIVE_COMPLETED_RUN_RECOVERY_REPORT: '+str(report_path),flush=True)
    return 0 if report['status']=='passed_with_reporting_recovery' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--model',required=True,help='Exact enabled UI model label')
    parser.add_argument('--execution-report',type=Path,required=True,help='Preserved blocked report containing the one already completed source-bound run')
    raise SystemExit(asyncio.run(run(parser.parse_args())))
