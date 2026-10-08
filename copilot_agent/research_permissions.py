"""Independent per-user consent store and bounded, locally enforced research tools."""
from __future__ import annotations
import asyncio
from copy import deepcopy
from datetime import date, datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import urljoin, urlsplit

from .logging_utils import EventLog, now
from .persistence import write_json
from .policy import PolicyError, PathPolicy, reject_path_redirection
from .protocol import validate_schema
from .site_knowledge import BIND, _current_origin, _origin, _session, _hash, _scope
from .web_navigation import LOCATOR, _boundary, _resolve, _candidates, _consequential_control, get_navigation_page

POLICY_VERSION = 'research-1'
LOCK = threading.RLock()
CAPABILITIES = ('navigation', 'customer_search', 'list_results', 'read_names', 'read_identifiers',
    'confirm_identifiers', 'open_profiles', 'read_interested_parties', 'read_linked_accounts',
    'open_document_libraries', 'document_metadata', 'open_documents', 'count_documents',
    'structured_summaries', 'autonomous_discovery')
PROHIBITED = ['create/edit/delete records', 'change personal/contact/banking data',
    'create/close accounts', 'upload/delete documents', 'generate correspondence',
    'authorise transactions', 'change users/roles', 'download documents', 'bulk export']
DATA = ('name', 'identifier', 'identifier_type', 'interested_parties', 'linked_accounts', 'document_metadata', 'summary')

def obj(properties, required=None):
    return {'type':'object', 'properties':properties, 'required':list(properties) if required is None else required, 'additionalProperties':False}
S = {'type':'string','minLength':1,'maxLength':300}
ID = {'type':'string','pattern':'^[a-f0-9]{64}$','maxLength':64}
def bound(maximum): return {'type':'integer','minimum':1,'maximum':maximum}
LIMITS = obj({'max_result_rows':bound(100),'max_customers':bound(50),'max_fields':bound(20),
    'max_documents':bound(100),'max_searches':bound(50),'max_date_range_days':bound(366),
    'allowed_search_criteria':{'type':'array','items':S,'minItems':1,'maxItems':20,'uniqueItems':True},
    'allow_names_in_output':{'type':'boolean'},'allow_identifiers_in_output':{'type':'boolean'}})
CHECK = obj({'kind':{'type':'string','enum':['tenant','environment','user','application']},
             'locator':LOCATOR,'expected':S})
GRANT = obj({**BIND['properties'], 'purpose':S, 'application_identity':S,
    'capabilities':{'type':'array','items':{'type':'string','enum':list(CAPABILITIES)},'minItems':1,'maxItems':len(CAPABILITIES),'uniqueItems':True},
    'limits':LIMITS, 'identity_checks':{'type':'array','items':CHECK,'maxItems':4},
    'expiry_days':{'type':['integer','null'],'minimum':1,'maximum':365}},
    [*BIND['required'],'purpose','capabilities','limits','identity_checks'])
FIELD = obj({'name':S,'category':{'type':'string','enum':list(DATA)},'locator':LOCATOR})
OPERATIONS = {'navigate':'navigation','search':'customer_search','list_results':'list_results',
    'open_profile':'open_profiles','read_fields':'structured_summaries','confirm_identifiers':'confirm_identifiers',
    'read_interested_parties':'read_interested_parties','read_linked_accounts':'read_linked_accounts',
    'open_document_library':'open_document_libraries','document_metadata':'document_metadata',
    'open_document':'open_documents','count_documents':'count_documents','summary':'structured_summaries'}
PERFORM = obj({'grant_id':ID, 'operation':{'type':'string','enum':list(OPERATIONS)}, 'tab_id':S,
    'locator':LOCATOR, 'submit':LOCATOR, 'customer_reference':S,
    'criteria':{'type':'array','items':obj({'field':S,'locator':LOCATOR,'value':S}),'maxItems':20},
    'fields':{'type':'array','items':FIELD,'maxItems':20},
    'identity':{'type':'array','items':obj({'locator':LOCATOR,'expected':S}),'maxItems':5},
    'date_from':{'type':'string','maxLength':10}, 'date_to':{'type':'string','maxLength':10}}, ['grant_id','operation'])
EDIT = obj({'grant_id':ID,'purpose':S,'capabilities':GRANT['properties']['capabilities'],'limits':LIMITS,
            'expiry_days':GRANT['properties']['expiry_days']}, ['grant_id'])
PERMISSION_SPECS = {
    'permissions.grant':(GRANT,'user_approval','Create permanent-until-revoked, website/tenant/environment/Windows-user scoped read consent. Review capabilities, limits and identity checks. Never authorises writes, downloads or exports.'),
    'permissions.list':(obj({}),'read_only','List this Windows user\'s durable research grants and management state; no customer data.'),
    'permissions.activate':(obj({'grant_id':ID}),'read_only','Verify a durable grant against the current owned origin and live identity checks; restore its exact namespace without renewed research consent. Without checks, a fresh user-reviewed namespace binding is required.'),
    'permissions.pause':(obj({'grant_id':ID}),'read_only','Immediately pause a research grant; no browser effect.'),
    'permissions.revoke':(obj({'grant_id':ID}),'read_only','Immediately revoke a research grant; its audit record is retained.'),
    'permissions.edit':(EDIT,'user_approval','Review and replace purpose, capabilities or limits of this exact grant. Scope changes require a new grant.'),
    'permissions.renew':(obj({'grant_id':ID}),'user_approval','Review this grant again before renewing/resuming it under the installed policy.'),
    'research.perform':(PERFORM,'read_only','Execute one bounded customer research operation under an active matching durable grant. Search, open profiles, inspect approved fields/libraries and read metadata. Never download, export or mutate records. Each live action rechecks revocation and scope; limits are per session.')}

def directory(context):
    value = context.get('permission_directory')
    if value is None:
        local = os.environ.get('LOCALAPPDATA')
        if not local: raise PolicyError('Per-user local permission storage is unavailable')
        value = Path(local)/'CopilotLocalAgent'/'permission-grants'
    path = Path(value).absolute()
    reject_path_redirection(path)
    return path

def user_identity(context):
    return _hash(context.get('permission_user_identity') or (os.environ.get('USERDOMAIN','')+'\\'+getpass.getuser()))

def audit(context, event, grant_id, **details):
    EventLog(directory(context)/'events.jsonl').write(event, grant_id=grant_id, **details)

def load(context, grant_id):
    if not re.fullmatch('[a-f0-9]{64}',grant_id): raise ValueError('Invalid grant ID')
    path = PathPolicy([directory(context)]).resolve(directory(context)/(grant_id+'.json'), True)
    if path.stat().st_size > 65536: raise PolicyError('Grant record exceeds its storage limit')
    record = json.loads(path.read_text(encoding='utf-8'))
    digest = record.pop('integrity_sha256',None)
    if digest != _hash(record) or record.get('grant_id') != grant_id or record.get('windows_user_sha256') != user_identity(context):
        raise PolicyError('Grant integrity or Windows-user binding failed')
    record['integrity_sha256']=digest
    return record

def save(context, record):
    record = deepcopy(record)
    record.pop('integrity_sha256',None)
    record['integrity_sha256']=_hash(record)
    path = directory(context)
    path.mkdir(parents=True,exist_ok=True)
    reject_path_redirection(path)
    write_json(PathPolicy([path]).resolve(path/(record['grant_id']+'.json')),record)
    return record

def list_grants(context):
    path = directory(context)
    if not path.exists(): return []
    records=[]
    for file in sorted(path.glob('*.json'))[:200]:
        try: records.append(load(context,file.stem))
        except (ValueError,PolicyError,OSError): continue
    return records

def active(context, grant_id):
    record=load(context,grant_id)
    if record['state']!='active' or record['policy_version']!=POLICY_VERSION:
        raise PolicyError('Grant is paused, revoked or requires policy revalidation')
    if record.get('expires_at') and datetime.fromisoformat(record['expires_at']) <= datetime.now(timezone.utc):
        raise PolicyError('Grant has expired; renew it through local approval')
    return record

def prepare_permissions(name,args,context):
    errors=validate_schema(args,PERMISSION_SPECS[name][0])
    if errors: raise ValueError('; '.join(errors[:4]))
    if name=='permissions.grant':
        scope_args={key:args[key] for key in BIND['required']}
        scope=_scope('site_knowledge.bind',scope_args,context)
        if args.get('application_identity') and not any(check['kind']=='application' and check['expected']==args['application_identity'] for check in args['identity_checks']):
            raise PolicyError('A declared application identity requires its matching live identity check')
        return {'scope':scope,'purpose':args['purpose'],'capabilities':args['capabilities'],
                'limits':args['limits'],'identity_checks':args['identity_checks'],
                'application_identity':args.get('application_identity','not-specified'),
                'expiry_days':args.get('expiry_days'),'prohibited_actions':PROHIBITED,
                'policy_version':POLICY_VERSION,'windows_user_sha256':user_identity(context),
                'consent':'Durable bounded research only. No write, download or export permission.'}
    if name in {'permissions.edit','permissions.renew'}:
        record=load(context,args['grant_id'])
        if record['state']=='revoked': raise PolicyError('Revoked grants cannot be revived; create a new grant')
        proposal={key:deepcopy(record[key]) for key in ('scope','purpose','capabilities','limits','identity_checks','application_identity','expiry_days','windows_user_sha256')}
        for key in ('purpose','capabilities','limits','expiry_days'):
            if key in args: proposal[key]=deepcopy(args[key])
        proposal.update(grant_id=args['grant_id'],previous_revision=record['revision'],policy_version=POLICY_VERSION,
                        prohibited_actions=PROHIBITED,consent='Review this durable read-only grant again.')
        return proposal
    return None

def manage(context, grant_id, action):
    if action not in {'pause','revoke'}: raise ValueError('Unknown permission-management action')
    with LOCK:
        record=load(context,grant_id)
        if record['state']=='revoked' and action=='pause': raise PolicyError('A revoked grant cannot be paused')
        record.update(state='paused' if action=='pause' else 'revoked',revision=record['revision']+1,updated_at=now())
        save(context,record)
        audit(context,'grant_'+action,grant_id,revision=record['revision'])
    return {'status':record['state'],'grant_id':grant_id}

async def verify_scope(context,record,tab_id=None):
    if record['scope']['origin'] != _current_origin(context): raise PolicyError('Grant cannot cross website origins')
    page=get_navigation_page(context,tab_id)
    await _boundary(page,context)
    checks=record['identity_checks']
    if checks:
        for check in checks:
            locator,_,_=await _resolve(page,check['locator'],context)
            if (await locator.inner_text(timeout=2000)).strip()!=check['expected']:
                raise PolicyError('Live tenant/environment/user/application identity differs from this grant')
    kinds={check['kind'] for check in checks}
    required={'tenant','environment','user'} | ({'application'} if record['application_identity']!='not-specified' else set())
    if not required <= kinds:
        reviewed=context.get('permission_reviewed') or {}
        if context.get('approved') is True and reviewed.get('scope')==record['scope']:
            return page
        scope=_scope('site_knowledge.retrieve',{'origin':record['scope']['origin']},context)
        if scope!=record['scope']: raise PolicyError('Grant does not match the locally reviewed tenant/environment/user namespace')
    return page

async def collection(page,strategy,context):
    candidates=await _candidates(page,strategy,context)
    for _,locator in candidates:
        if await locator.count(): return locator
    raise PolicyError('No matching research rows or documents were observed')

def bind_namespace(context,record):
    context.setdefault('site_knowledge_bindings',{})[record['scope']['origin']]={
        'scope':deepcopy(record['scope']),'session':_session(context),
        'approval_hash':record['approval_hash'],'review_sha256':_hash(record['scope'])}
    context.setdefault('active_research_grants',{})[record['scope']['origin']]=record['grant_id']

async def execute_permissions(name,args,context):
    if name=='permissions.list': return {'grants':list_grants(context),'policy_version':POLICY_VERSION}
    if name in {'permissions.pause','permissions.revoke'}: return manage(context,args['grant_id'],name.split('.')[1])
    if name=='permissions.activate':
        record=active(context,args['grant_id']); await verify_scope(context,record); bind_namespace(context,record)
        audit(context,'grant_activated',record['grant_id'])
        return {'status':'active','grant_id':record['grant_id'],'scope':record['scope'],'capabilities':record['capabilities'],'limits':record['limits']}
    if name=='research.perform':
        try: return await perform(args,context)
        except Exception:
            audit(context,'research_blocked',args['grant_id'],operation=args['operation'],effects_started=context.get('research_effects_started',False))
            raise
    prepared=prepare_permissions(name,args,context)
    if (context.get('approved') is not True or not context.get('approval_hash')
            or context.get('permission_reviewed')!=prepared): raise PolicyError('Exact local permission approval is required')
    if name=='permissions.grant':
        record={key:deepcopy(prepared[key]) for key in ('scope','purpose','capabilities','limits','identity_checks','application_identity','expiry_days','windows_user_sha256')}
        record.update(grant_id=_hash([record['scope'],record['purpose'],record['windows_user_sha256']]),created_at=now(),revision=1,last_use=None)
        if (directory(context)/(record['grant_id']+'.json')).exists():
            old=load(context,record['grant_id']); record['revision']=old['revision']+1
        # This exact creation approval is also authority to select the declared namespace.
        if record['identity_checks']:
            await verify_scope(context,record)
    else:
        record=load(context,args['grant_id'])
        for key in ('purpose','capabilities','limits','expiry_days'): record[key]=deepcopy(prepared[key])
        record['revision']+=1
    from datetime import timedelta
    record.update(state='active',policy_version=POLICY_VERSION,approval_hash=context['approval_hash'],updated_at=now(),
        expires_at=(datetime.now(timezone.utc)+timedelta(days=record['expiry_days'])).isoformat() if record['expiry_days'] else None,
        expiry_mode='fixed' if record['expiry_days'] else 'until_revoked',prohibited_actions=PROHIBITED)
    with LOCK:
        if name != 'permissions.grant' and load(context,record['grant_id'])['revision'] != prepared['previous_revision']:
            raise PolicyError('Grant changed during approval; review it again')
        save(context,record)
        audit(context,'grant_reviewed',record['grant_id'],revision=record['revision'])
    bind_namespace(context,record)
    return {'status':'granted','grant_id':record['grant_id'],'revision':record['revision'],'expiry_mode':record['expiry_mode'],
            'scope':record['scope'],'capabilities':record['capabilities'],'limits':record['limits']}

async def guard_customer_read(context,capability='structured_summaries'):
    origin=_current_origin(context)
    grant_id=context.get('active_research_grants',{}).get(origin)
    if not grant_id: raise PolicyError('Customer research requires a matching explicit grant; request permissions.grant or permissions.activate')
    record=active(context,grant_id)
    await verify_scope(context,record)
    if capability not in record['capabilities']: raise PolicyError('This research capability is not granted')
    return record

async def perform(args,context):
    record=active(context,args['grant_id'])
    page=await verify_scope(context,record,args.get('tab_id'))
    operation=args['operation']; capability=OPERATIONS[operation]
    if capability not in record['capabilities']: raise PolicyError('Requested research capability is not granted')
    limits=record['limits']
    usage=context.setdefault('research_usage',{}).setdefault(record['grant_id'],{'searches':0,'customers':0,'documents':0})
    async def checkpoint():
        current=active(context,record['grant_id'])
        if current['revision']!=record['revision']: raise PolicyError('Grant changed while the action was running')
        await verify_scope(context,current,args.get('tab_id'))
    async def reserve(kind,maximum):
        await checkpoint()
        if usage[kind]>=maximum: raise PolicyError('Approved '+kind+' limit reached')
        usage[kind]+=1
    if operation=='search':
        criteria=args.get('criteria',[])
        if not criteria or len(criteria)>limits['max_fields']: raise PolicyError('Provide bounded approved search criteria')
        if any(item['field'] not in limits['allowed_search_criteria'] for item in criteria): raise PolicyError('Search criterion is not approved')
        if not args.get('customer_reference') and 'autonomous_discovery' not in record['capabilities']:
            raise PolicyError('Autonomous customer discovery was not granted')
        if 'autonomous_discovery' not in record['capabilities'] and (
                args['customer_reference'] not in context.get('research_user_request','')
                or not any(args['customer_reference']==item['value'] for item in criteria)):
            raise PolicyError('Search must use the customer reference explicitly supplied in the current user request')
        if bool(args.get('date_from'))!=bool(args.get('date_to')): raise PolicyError('Both date-range bounds are required')
        if args.get('date_from'):
            span=(date.fromisoformat(args['date_to'])-date.fromisoformat(args['date_from'])).days
            if span<0 or span>limits['max_date_range_days']: raise PolicyError('Search date range exceeds the grant')
        submit,_,_=await _resolve(page,args['submit'],context)
        label=(await submit.inner_text(timeout=1000)).strip() or await submit.get_attribute('aria-label') or ''
        if not re.search(r'\b(search|find|filter|lookup)\b',label,re.I) or await _consequential_control(submit,'click'):
            raise PolicyError('Research can submit only a verified search control; consequential controls need exact approval')
        handle=await submit.element_handle()
        resolved=[]
        for item in criteria:
            field,_,_=await _resolve(page,item['locator'],context)
            kind=(await field.get_attribute('type') or 'text').lower()
            if kind not in {'text','search','number','email','tel','date'}: raise PolicyError('Unsupported read-research search field')
            if kind=='date' and (not args.get('date_from') or not date.fromisoformat(args['date_from']) <= date.fromisoformat(item['value']) <= date.fromisoformat(args['date_to'])):
                raise PolicyError('Actual search date values must fit the approved bounded date range')
            if not await field.evaluate('(n,s)=>(n.form||n.closest("form"))===(s.form||s.closest("form"))',handle):
                raise PolicyError('Search fields must belong to the verified search form')
            resolved.append((field,item['value']))
        await reserve('searches',limits['max_searches'])
        for field,value in resolved:
            await checkpoint(); context['research_effects_started']=True; await field.fill(value,timeout=3000)
        await checkpoint(); await submit.click(timeout=5000)
        result={'status':'searched','criteria_count':len(criteria)}
    elif operation in {'navigate','open_profile','open_document_library','open_document'}:
        locator,_,_=await _resolve(page,args['locator'],context)
        href=await locator.get_attribute('href')
        if not href or await locator.get_attribute('download') is not None or await _consequential_control(locator,'click'):
            raise PolicyError('Read consent opens only observed navigation links; download or consequential buttons need exact approval')
        url=urljoin(page.url,href)
        if _origin('https://'+(urlsplit(url).hostname or ''))!=record['scope']['origin'] or urlsplit(url).scheme!='https':
            raise PolicyError('Research cannot navigate to another origin')
        if operation=='open_profile':
            if not args.get('customer_reference') and 'autonomous_discovery' not in record['capabilities']:
                raise PolicyError('Autonomous customer selection was not granted')
            if 'autonomous_discovery' not in record['capabilities'] and args['customer_reference'] not in context.get('research_user_request',''):
                raise PolicyError('Customer selection must match the current user request')
            if not args.get('identity'): raise PolicyError('Opening a customer profile requires an exact observed identity check')
            await reserve('customers',limits['max_customers'])
        if operation=='open_document': await reserve('documents',limits['max_documents'])
        await checkpoint(); context['research_effects_started']=True; await page.goto(url,wait_until='domcontentloaded',timeout=10000)
        for check in args.get('identity',[]):
            item,_,_=await _resolve(page,check['locator'],context)
            if (await item.inner_text(timeout=2000)).strip()!=check['expected']: raise PolicyError('Opened customer identity did not match; stop research')
        result={'status':'opened','identity_verified':bool(args.get('identity'))}
    elif operation=='count_documents':
        locator=await collection(page,args['locator'],context)
        result={'status':'observed','count':min(await locator.count(),limits['max_documents'])}
    else:
        fields=args.get('fields',[])
        if not fields or len(fields)>limits['max_fields']: raise PolicyError('Requested fields exceed the approved field limit')
        for item in fields:
            required={'name':'read_names','identifier':'read_identifiers','identifier_type':'confirm_identifiers',
                'interested_parties':'read_interested_parties','linked_accounts':'read_linked_accounts',
                'document_metadata':'document_metadata','summary':'structured_summaries'}[item['category']]
            if required not in record['capabilities']: raise PolicyError('Requested data category was not granted')
        rows=[page]
        if operation in {'list_results','document_metadata'} and args.get('locator'):
            selected=await collection(page,args['locator'],context)
            cap=limits['max_result_rows'] if operation=='list_results' else limits['max_documents']
            rows=[selected.nth(index) for index in range(min(await selected.count(),cap))]
        facts=[]
        for row in rows:
            await checkpoint()
            if operation=='document_metadata': await reserve('documents',limits['max_documents'])
            item_values={}
            for field in fields:
                category=field['category']
                withheld=(category=='name' and not limits['allow_names_in_output'] or
                    category in {'identifier','linked_accounts'} and not limits['allow_identifiers_in_output'] or
                    category=='interested_parties' and not (limits['allow_names_in_output'] and limits['allow_identifiers_in_output']) or
                    category in {'summary','document_metadata'} and not (limits['allow_names_in_output'] and limits['allow_identifiers_in_output']))
                if withheld: item_values[field['name']]='[withheld by grant]'; continue
                locator=await collection(row,field['locator'],context)
                if await locator.count()!=1: raise PolicyError('Research field must identify one control per row')
                if await locator.evaluate('n=>["INPUT","TEXTAREA"].includes(n.tagName)||n.isContentEditable'):
                    raise PolicyError('Customer reads cannot expose editable field values')
                item_values[field['name']]=(await locator.inner_text(timeout=2000)).strip()[:500]
            facts.append(item_values)
        result={'status':'observed','rows':facts,'row_count':len(facts)}
    await checkpoint()
    with LOCK:
        latest=active(context,record['grant_id'])
        if latest['revision']!=record['revision']: raise PolicyError('Grant changed before result delivery')
        latest['last_use']=now(); save(context,latest)
        audit(context,'research_'+operation,record['grant_id'],usage=usage,result_sha256=_hash(result))
    bind_namespace(context,record)
    context.setdefault('research_context',{})['active']=True
    return result | {'grant_id':record['grant_id'],'persistence':'customer_content_ephemeral_only','usage':deepcopy(usage)}
