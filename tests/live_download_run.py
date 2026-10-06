"""Real UI download, then exact-byte Python-subset execution after user approval.

Run only with --live, an authorized dedicated config and an exact UI model.
The harness never writes an approving ledger. A supervising agent must obtain
explicit user permission before creating the matching one-use approval JSON.
Importing this module performs no browser actions or generated-code execution.
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
import time
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copilot_agent.archives import verify_delivered_file
from copilot_agent.browser import BrowserAdapter
from copilot_agent.code_runner import CodeRunner
from copilot_agent.config import Config
from copilot_agent.logging_utils import redact
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.persistence import write_json
from copilot_agent.policy import PathPolicy
from copilot_agent.state import SessionState
from copilot_agent.tools import ToolRegistry


EXPECTED_NAME='synthetic-download-run.py'
EXPECTED_STDOUT='download-run-test\n'


def require(condition,message):
    if not condition: raise AssertionError(message)


def validate_print_only(script):
    tree=ast.parse(script)
    wanted=ast.parse("print('download-run-test')\n")
    require(ast.dump(tree,include_attributes=False)==ast.dump(wanted,include_attributes=False),'The actual downloaded source is not the authorized single synthetic print statement')


def read_approval(path,expected):
    require(path.is_file() and path.stat().st_size<=65536,'Approval ledger must be a bounded regular JSON file')
    def unique_pairs(pairs):
        value={}
        for key,item in pairs:
            require(key not in value,'Approval ledger has duplicate keys')
            value[key]=item
        return value
    with path.open('r',encoding='utf-8') as stream:
        value=json.loads(stream.read(65537),object_pairs_hook=unique_pairs)
    require(value==dict(expected,decision='once'),'Approval ledger does not match the exact nonce, source and immutable proposal, or is not an explicit once grant')
    return value


async def wait_for_approval(path,expected,timeout,report,save):
    deadline=time.monotonic()+timeout;next_update=0
    while time.monotonic()<deadline:
        if path.exists():
            value=read_approval(path,expected)
            report['external_approval_observed']=value;save()
            return value
        if time.monotonic()>=next_update:
            print('AWAITING_EXPLICIT_USER_ONCE: '+str(path)+'; no Code Runner execution has been approved or started.',flush=True)
            next_update=time.monotonic()+30
        await asyncio.sleep(1)
    raise TimeoutError('Explicit matching user approval did not arrive before the bounded wait; no Code Runner execution was authorized')


async def run(args):
    if not args.live: raise SystemExit('Explicit --live is required: this harness requests a real synthetic file download and pauses for exact execution approval.')
    require(0<args.approval_timeout<=900,'Approval timeout must be positive and at most 900 seconds')
    config=Config.load(args.config)
    require(not config.created_sync_enabled,'Use a test config with Created monitoring disabled')
    require(config.storage_dir is not None,'Choose validated per-user OneDrive storage before this download test')
    evidence_root=PathPolicy([config.storage_dir],excluded_roots=[config.profile_dir])
    token=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    directory=evidence_root.resolve(config.runtime_dir/'acceptance'/('download-run-'+token))
    directory.mkdir(parents=True,exist_ok=False)
    report_path=directory/'report.json'
    approval_path=evidence_root.resolve(args.approval) if args.approval else directory/('decision-'+uuid.uuid4().hex+'.json')
    require(not approval_path.exists(),'Choose a fresh approval-ledger path; preexisting approval cannot authorize this new test')
    pending_path=directory/'pending-approval.json'
    report={'status':'incomplete','started_at':datetime.now(timezone.utc).isoformat(),'directory':str(directory),'model_requested':args.model,'steps':[],'approvals':[],'feedback':[],'execution_started':False,'code_execution_approved':False,'created_folder_access':False,'limitations':['Execution uses the declared Python-subset interpreter, not host Python, shell or subprocess execution.','Internal Copilot computation is not observable; it is instructed to create the artifact without executing it.']}
    def save(): write_json(report_path,redact(report))
    def display(message):
        message=redact(str(message));report['feedback'].append(message)
        print(message,flush=True)
    save()
    adapter=BrowserAdapter(config);state=None;engine=None
    phase='download';download_granted=False;code_granted=False
    source_path=None;source_bytes=None;proposal=None;approval_expected=None
    async def decide(preview):
        nonlocal download_granted,code_granted
        plan=preview.get('complete_pending_plan',{})
        calls=plan.get('tool_requests',[])
        current=next((call for call in calls if call.get('call_id')==preview.get('current_call_id')),None)
        prepared=preview.get('prepared_code') or {}
        accepted=False;reason='Scope not explicitly authorized by this harness'
        if current and len(calls)==1 and phase=='download' and not download_granted and current.get('name')=='copilot.download':
            arguments=current.get('arguments',{})
            destination=Path(prepared.get('destination',''))
            if arguments.get('expected_name')==EXPECTED_NAME and set(arguments).issubset({'expected_name','link_text'}) and destination.name==EXPECTED_NAME:
                checked=evidence_root.resolve(destination)
                if checked.is_relative_to(config.storage_dir/'deliveries'):
                    accepted=True;download_granted=True;reason='One actual UI download of the exact harmless synthetic filename to reviewed OneDrive staging'
        elif current and len(calls)==1 and phase=='run' and not code_granted and current.get('name')=='code_runner':
            arguments=current.get('arguments',{})
            same_proposal=proposal is not None and prepared.get('proposal_hash')==proposal['proposal_hash'] and prepared.get('script_sha256')==proposal['script_sha256'] and prepared.get('plan')==proposal['plan']
            same_source=source_path is not None and source_path.read_bytes()==source_bytes and arguments.get('script','').encode('utf-8')==source_bytes
            if same_proposal and same_source and approval_expected is not None:
                checked=evidence_root.resolve(approval_path,True)
                read_approval(checked,approval_expected)
                accepted=True;code_granted=True;report['code_execution_approved']=True
                reason='External explicit user once grant matches actual downloaded bytes and complete immutable Python-subset proposal'
        report['approvals'].append({'current_call_id':preview.get('current_call_id'),'name':current.get('name') if current else None,'decision':'once' if accepted else 'deny','reason':reason,'preview':preview})
        save()
        return 'once' if accepted else 'deny'
    try:
        state=SessionState(directory/'session')
        engine=Orchestrator(config,adapter,ToolRegistry(),state,approval_decider=decide,display=display)
        runner_properties=engine.registry.definition('code_runner')['input_schema'].get('properties',{})
        require({'source_path','source_sha256'}.issubset(runner_properties),'The production source-bound Code Runner tool contract is not ready; no UI send attempted')
        engine.prompts.verify_guidance()
        startup=engine.prompts.initial_attachments()
        report['startup_documents']=[{'path':str(path),'name':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in startup]
        report['source_guidance_manifest']=state.data.get('guidance_manifest',[])
        require(len(startup)==8,'The strong eight-document guidance startup is not ready; no UI send attempted')
        save()
        await adapter.start()
        models=await adapter.discover_models();report['models_discovered']=models
        require(any(item['label']==args.model and item.get('enabled',True) for item in models),'Exact requested UI model is unavailable')
        await adapter.select_model(args.model)
        initialization=await engine.initialize()
        report['initialization_response']=initialization
        require(state.message_count==1 and not state.data['calls'],'Initialization was not first-shot readiness without tools')
        report['steps'].append({'name':'first-shot strong eight-document initialization','status':'passed'})
        before=set(state.data['calls'])
        response=await engine.turn('Create a harmless Python source file named '+EXPECTED_NAME+' containing exactly the single statement print(\'download-run-test\') followed by a newline. Create the downloadable artifact without executing the source. Provide its actual clickable UI download link after the END marker, outside the JSON. Request copilot.download with expected_name '+EXPECTED_NAME+' in that SAME response. Download this source file only; no Code Runner, local source-file creation, ZIP fallback or other tool calls are authorized in this phase. After the actual download result, give an honest final response.')
        calls=[call for key,call in state.data['calls'].items() if key not in before]
        report['download_response']=response;report['download_calls']=calls
        require(len(calls)==1 and calls[0]['request']['name']=='copilot.download' and calls[0].get('result',{}).get('ok'),'A single actual successful UI download was not observed')
        download=calls[0]['result']['result']
        source_path=engine.policy.resolve(download['path'],True)
        require(source_path.name==EXPECTED_NAME and source_path.is_relative_to(config.storage_dir/'deliveries'),'Downloaded source is outside the exact approved OneDrive delivery location')
        verified=verify_delivered_file(source_path,{'max_file_bytes':1024})
        require(verified['sha256']==download['sha256'] and verified.get('python_syntax')=='passed_without_execution','Actual downloaded source hash/static syntax verification failed')
        source_bytes=source_path.read_bytes();script=source_bytes.decode('utf-8')
        require(hashlib.sha256(source_bytes).hexdigest()==verified['sha256'],'Downloaded source changed before preparation')
        validate_print_only(script)
        work=engine.policy.resolve(config.workspace_dir/'acceptance-execution'/uuid.uuid4().hex)
        work.mkdir(parents=True,exist_ok=False)
        code_arguments={'script':script,'purpose':'Execute only the exact downloaded harmless synthetic print statement after explicit user once approval','language':'python_subset','working_directory':str(work),'source_path':str(source_path),'source_sha256':verified['sha256'],'read_paths':[str(source_path)],'create_paths':[],'expected_outputs':[],'commands':[],'subprocesses':[],'network_destinations':[],'permissions':['read_files'],'risk_summary':'Read only the one declared downloaded source artifact to verify its exact bytes/hash, then bounded terminal output. No file writes, imports, subprocesses, shell commands or network destinations. Expected stdout is download-run-test followed by a newline.','recovery_notes':'No external changes to roll back; preserve the downloaded source, immutable proposal, approval ledger and execution report.'}
        proposal=CodeRunner(engine.policy,state.directory).prepare(code_arguments)
        require(proposal['plan'].get('source_path')==str(source_path) and proposal['plan'].get('source_sha256')==verified['sha256'],'Production preparation did not bind the downloaded artifact source')
        source_verification={'path':str(source_path),'sha256':verified['sha256'],'size':len(source_bytes),'exact_script_bytes':True}
        require(proposal.get('source_verification')==source_verification,'Production preparation lacks exact raw downloaded-artifact verification evidence')
        require(Path(proposal['script_path']).read_bytes()==source_bytes and proposal['script_sha256']==verified['sha256'],'Prepared proposal does not preserve the exact downloaded bytes')
        approval_expected={'nonce':uuid.uuid4().hex,'proposal_hash':proposal['proposal_hash'],'script_sha256':proposal['script_sha256'],'download_sha256':verified['sha256'],'download_path':str(source_path)}
        pending={'status':'awaiting_explicit_user_once','download':download,'download_static_verification':verified,'script':script,'code_arguments':code_arguments,'prepared_proposal':proposal,'expected_stdout':EXPECTED_STDOUT,'expected_exit_code':0,'decision_file':str(approval_path),'approval_ledger_template':dict(approval_expected,decision='pending'),'approval_instructions':'The supervising agent must present this exact script and scope and obtain explicit user Allow once. Only then write the template fields unchanged with decision set to once. This harness never creates an approving ledger. No host Python or shell execution is requested.'}
        write_json(pending_path,pending)
        report['steps'].append({'name':'real UI source download and immutable no-side-effect proposal preparation','status':'passed','download_path':str(source_path),'script_sha256':verified['sha256'],'proposal_hash':proposal['proposal_hash']})
        report['pending_approval_path']=str(pending_path);report['decision_file']=str(approval_path);report['status']='awaiting_explicit_user_approval';save()
        print('PENDING_USER_APPROVAL: '+str(pending_path),flush=True)
        await wait_for_approval(approval_path,approval_expected,args.approval_timeout,report,save)
        require(source_path.read_bytes()==source_bytes,'Downloaded source changed after approval; execution remains denied')
        phase='run';before=set(state.data['calls'])
        run_request=('Request exactly one code_runner call using the complete immutable arguments below. They bind source_path/source_sha256 to the exact actual downloaded '+EXPECTED_NAME+' bytes; do not rewrite, normalize or replace them. The only declared read is that same source artifact for verification. Execution still requires the orchestrator\'s matching explicit user once approval. No other tools, files, imports, network, subprocesses or integrated execution are authorized. After the actual tool outcome report its real stdout and exit code in a final envelope. Arguments:\n'+json.dumps(code_arguments,ensure_ascii=False))
        result=await engine.turn(run_request)
        executed=[call for key,call in state.data['calls'].items() if key not in before]
        report['execution_response']=result;report['execution_calls']=executed
        require(code_granted and len(executed)==1 and executed[0]['request']['name']=='code_runner' and executed[0].get('result',{}).get('ok'),'One explicitly approved exact Code Runner execution did not complete')
        outcome=executed[0]['result']['result']
        report['execution_started']=True
        require(outcome.get('proposal_hash')==proposal['proposal_hash'] and outcome.get('script_sha256')==verified['sha256'],'Execution hashes differ from the approved downloaded source/proposal')
        require(outcome.get('source_verification')==source_verification,'Runtime did not prove the same declared source artifact and exact script bytes')
        require(outcome.get('status')=='completed' and outcome.get('stdout')==EXPECTED_STDOUT and outcome.get('stderr')=='' and outcome.get('exit_code')==0,'Execution result differs from the exact bounded print output')
        require(not outcome.get('created_paths') and not outcome.get('outputs'),'The print-only proposal created files')
        require(source_path.read_bytes()==source_bytes,'Original downloaded source was changed')
        require(result.get('completion_status')=='complete','Copilot did not acknowledge the actual completed tool outcome')
        report['steps'].append({'name':'external user once approval and exact downloaded-source Python-subset execution','status':'passed','outcome':outcome,'downloaded_bytes_preserved':True})
        report['status']='passed'
    except Exception as error:
        report['status']='blocked';report['steps'].append({'name':'download then approval-bound run acceptance','status':'blocked','error':str(error)})
        print('LIVE_DOWNLOAD_RUN_BLOCKED: '+str(error),flush=True)
    finally:
        if state is not None:
            report['message_count']=state.message_count;report['all_calls']=state.data['calls'];report['pending_submission']=state.data.get('pending_submission')
            report['execution_started']=any(call['request']['name']=='code_runner' and call.get('result',{}).get('ok') for call in state.data['calls'].values())
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
        print('LIVE_DOWNLOAD_RUN_REPORT: '+str(report_path),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--model',required=True,help='Exact enabled UI model label')
    parser.add_argument('--approval',type=Path,help='Fresh external one-use approval JSON path within selected OneDrive storage')
    parser.add_argument('--approval-timeout',type=float,default=600,help='Bounded async approval wait in seconds, at most900')
    raise SystemExit(asyncio.run(run(parser.parse_args())))
