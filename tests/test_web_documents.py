"""Native-browser document contracts with deterministic controlled artifacts."""
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from copilot_agent.policy import PathPolicy, PolicyError
from copilot_agent.web_documents import DOCUMENT_SPECS, DOCUMENT_EXAMPLES, execute_documents, validate_documents


class FakeDownload:
    def __init__(self, path, url, failure=None):
        self.artifact, self.url, self.reason = path, url, failure
        self.cancelled=False
    async def path(self): return str(self.artifact)
    async def failure(self): return self.reason
    async def cancel(self): self.cancelled=True


class Pending:
    def __init__(self, page): self.page=page
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    @property
    def value(self):
        async def result(): return self.page.item
        return result()


class Response:
    def __init__(self,url,headers,status=200): self.url,self.headers,self.status=url,headers,status
    async def all_headers(self): return self.headers


class FakePage:
    def __init__(self, context, primary=False):
        self.context=context; self.url='https://fixture.test/documents'; self.closed=False
        self.primary=primary; self.handlers={}; self.item=None
        self.links=[]; self.anchor_valid=True
    def is_closed(self): return self.closed
    async def evaluate(self, script, args=None):
        if 'params.keys' in script: return self.anchor_valid
        return {'links':list(self.links)}
    async def route(self, pattern, handler): self.route_handler=handler
    def on(self, event, handler): self.handlers[event]=handler
    def expect_download(self, **kwargs): return Pending(self)
    async def goto(self,url,**kwargs):
        self.context.navigations.append(url)
        if url not in self.context.browser._approved_web_downloads.get(self,set()): raise AssertionError('No exact scoped download grant')
        fixture=self.context.fixtures[url]
        self.url=url; path=self.context.root/('native-'+str(len(self.context.navigations)))
        path.write_bytes(fixture['data'])
        self.item=FakeDownload(path,fixture.get('event_url',url),fixture.get('failure'))
        self.context.downloads.append(self.item)
        headers={'content-type':fixture.get('mime','text/plain')}
        if 'length' in fixture: headers['content-length']=str(fixture['length'])
        if 'response' in self.handlers: self.handlers['response'](Response(url,headers,fixture.get('status',200)))
        if fixture.get('delay'): await asyncio.sleep(fixture['delay'])
    async def close(self): self.closed=True


class FakeContext:
    def __init__(self, root):
        self.root=root; self.pages=[]; self.fixtures={}; self.navigations=[]; self.downloads=[]
        self.peak=0
    async def new_page(self):
        self.browser._navigation_expected_new_pages=max(0,getattr(self.browser,'_navigation_expected_new_pages',1)-1)
        page=FakePage(self); self.pages.append(page)
        self.peak=max(self.peak,sum(not p.closed for p in self.pages))
        return page


class DocumentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='copilot_documents_'); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        native=self.root/'native'; native.mkdir()
        self.browser_context=FakeContext(native)
        self.page=FakePage(self.browser_context,True); self.browser_context.pages.append(self.page)
        self.browser=SimpleNamespace(tool_context=self.browser_context,tool_page=self.page,tool_domains={'fixture.test'})
        self.browser_context.browser=self.browser
        self.config={'storage_dir':str(self.root),'allowed_roots':[str(self.root)],'max_tool_tabs':4}
        self.context={'browser':self.browser,'config':self.config,'approved_domains':['fixture.test'],
            'approved':True,'session_dir':str(self.root),'pending_file_attachments':[],
            'approved_attachment_hashes':{},'task_id':'task-one','customer_key':'customer-scope-one'}
        self.policy=PathPolicy([self.root])
    def fixture(self,path,data=b'hello document',mime='text/plain',**fields):
        raw='https://fixture.test/'+path
        key=len(self.page.links)+1
        self.page.links.append({'key':key,'href':raw,'download':None,'label':'Document '+str(key)})
        self.browser_context.fixtures[raw]={'data':data,'mime':mime,**fields}
        return raw
    async def discover(self):
        result=await execute_documents('browser.documents',{},self.context,self.policy)
        return result['documents']
    async def batch(self,docs=None,**args):
        if docs is None: docs=await self.discover()
        items=[{'document_id':doc['document_id']} for doc in docs]
        return await execute_documents('browser.download_batch',{'documents':items,
            'destination':str(self.root/'downloaded'),'rate_limit_ms':100,**args},self.context,self.policy)

    async def test_discovery_deduplicates_and_never_exposes_query(self):
        raw=self.fixture('report.pdf?signature=PRIVATE_SIGNATURE',b'%PDF-1.4\n%%EOF','application/pdf')
        self.page.links.append({'key':2,'href':raw,'download':None,'label':'Duplicate'})
        self.page.links.extend([{'key':3,'href':'https://elsewhere.test/customer.pdf','download':None},
            {'key':4,'href':'javascript:alert(1)','download':'report.pdf'},
            {'key':5,'href':'https://fixture.test/run.exe','download':'run.exe'}])
        docs=await self.discover()
        self.assertEqual(len(docs),1); self.assertEqual(docs[0]['duplicate_count'],1)
        self.assertNotIn('PRIVATE_SIGNATURE',json.dumps(docs))
        self.assertEqual(self.browser_context.navigations,[])

    async def test_native_batch_hash_manifest_transfer_and_scoped_cleanup(self):
        self.fixture('first.pdf?token=DO_NOT_RETAIN',b'%PDF-1.4\nhello\n%%EOF','application/pdf')
        self.fixture('second.txt',b'second content')
        report=await self.batch(concurrency=2)
        self.assertEqual(report['status'],'verified'); self.assertEqual(report['summary']['success'],2)
        self.assertFalse(report['side_effects_uncertain'])
        self.assertLessEqual(self.browser_context.peak,3)
        self.assertFalse(self.page.closed); self.assertTrue(all(p.closed for p in self.browser_context.pages[1:]))
        self.assertEqual(self.browser._approved_web_downloads,{})
        raw=Path(report['manifest_path']).read_text()
        self.assertNotIn('DO_NOT_RETAIN',raw)
        files=[{'path':r['path'],'sha256':r['sha256']} for r in report['files']]
        files.append({'path':report['manifest_path'],'sha256':report['manifest_sha256']})
        transferred=await execute_documents('files.transfer_to_copilot',{'files':files},self.context,self.policy)
        self.assertEqual(transferred['status'],'queued'); self.assertFalse(transferred['delivery_verified'])
        self.assertEqual(len(self.context['pending_file_attachments']),3)
        self.assertEqual(self.context['approved_attachment_hashes'][report['manifest_path']],report['manifest_sha256'])

    async def test_download_requires_approval_without_side_effects(self):
        self.fixture('one.txt'); docs=await self.discover(); self.context['approved']=False
        with self.assertRaises(PolicyError): await self.batch(docs)
        self.assertEqual(self.browser_context.navigations,[])
        self.assertFalse((self.root/'downloaded').exists())

    async def test_changed_source_and_cross_customer_identity_refused(self):
        self.fixture('one.txt'); docs=await self.discover()
        self.context['customer_key']='another-customer'
        report=await self.batch(docs)
        self.assertEqual(report['status'],'failed'); self.assertEqual(self.browser_context.navigations,[])
        self.context['customer_key']='customer-scope-one'; self.page.anchor_valid=False
        report=await self.batch(docs)
        self.assertEqual(report['status'],'failed'); self.assertEqual(self.browser_context.navigations,[])

    async def test_changed_source_route_cannot_reuse_ticket(self):
        self.fixture('one.txt'); docs=await self.discover(); self.page.url='https://fixture.test/other-customer'
        report=await self.batch(docs)
        self.assertEqual(report['status'],'failed'); self.assertEqual(self.browser_context.navigations,[])

    async def test_documents_inherit_bound_navigation_scope_and_reject_rebind(self):
        self.context.pop('task_id'); self.context.pop('customer_key')
        tab={'page':self.page,'task_id':'planned-task','customer_key':'planned-customer'}
        self.browser._navigation_state={'tabs':{'tab-1':tab}}
        self.fixture('bound.txt')
        with self.assertRaises(PolicyError): await self.discover()
        self.context['customer_key']='planned-customer'; docs=await self.discover()
        ticket=self.context['web_document_tickets'][docs[0]['document_id']]
        self.assertEqual(ticket['task_id'],'planned-task'); self.assertEqual(ticket['customer_key'],'planned-customer')
        tab['customer_key']='different-customer'
        report=await self.batch(docs)
        self.assertEqual(report['status'],'failed'); self.assertEqual(self.browser_context.navigations,[])

    async def test_integrity_failures_preserve_outputs_and_report_failure(self):
        self.fixture('corrupt.pdf',b'not a PDF','application/pdf')
        report=await self.batch()
        self.assertEqual(report['status'],'failed'); entry=report['files'][0]
        self.assertTrue(Path(entry['partial_path']).exists())
        self.assertNotIn('sha256',entry); self.assertTrue(self.browser_context.downloads[0].cancelled)
        self.assertFalse(report['side_effects_uncertain'])

    async def test_response_mime_cannot_disguise_authentication_page(self):
        self.fixture('auth.pdf',b'%PDF-1.4\n%%EOF','text/html')
        report=await self.batch()
        self.assertEqual(report['status'],'failed')
        self.assertIn('HTML',report['files'][0]['error']['message'])

    async def test_response_mime_must_agree_with_extension(self):
        self.fixture('report.pdf',b'%PDF-1.4\n%%EOF','image/png')
        self.assertEqual((await self.batch())['status'],'failed')

    async def test_limits_include_aggregate_and_declared_length(self):
        self.fixture('one.txt',b'12345'); self.fixture('two.txt',b'67890')
        report=await self.batch(max_total_bytes=6,concurrency=1)
        self.assertEqual(report['status'],'partial'); self.assertEqual(report['summary']['retained_bytes'],5)
        self.assertLessEqual(sum(p.stat().st_size for p in (self.root/'downloaded').glob('*.txt')),6)
        self.fixture('too-large.txt',b'1234',length=200)
        docs=await self.discover()
        report=await self.batch([docs[-1]],max_file_bytes=10)
        self.assertEqual(report['status'],'failed'); self.assertNotIn('partial_path',report['files'][0])

    async def test_completed_length_mismatch_and_redirect_event_rejected(self):
        self.fixture('truncated.txt',b'hello',length=10)
        report=await self.batch(); self.assertEqual(report['status'],'failed')
        self.fixture('redirect.txt',event_url='https://other.test/redirect.txt')
        docs=await self.discover(); report=await self.batch([docs[-1]])
        self.assertEqual(report['status'],'failed'); self.assertIn('exact observed',report['files'][0]['error']['message'])

    async def test_resume_requires_exact_manifest_hash_and_integrity(self):
        self.fixture('one.txt'); docs=await self.discover()
        first=await self.batch(docs)
        second=await self.batch(docs,resume_manifest=first['manifest_path'],resume_manifest_sha256=first['manifest_sha256'])
        self.assertEqual(second['status'],'verified'); self.assertEqual(second['files'][0]['reason'],'verified_resume')
        self.assertEqual(len(self.browser_context.navigations),1)
        Path(first['files'][0]['path']).write_bytes(b'tampered')
        third=await self.batch(docs,resume_manifest=first['manifest_path'],resume_manifest_sha256=first['manifest_sha256'])
        self.assertEqual(third['status'],'failed'); self.assertEqual(len(self.browser_context.navigations),1)
        self.assertEqual(Path(first['files'][0]['path']).read_bytes(),b'tampered')

    async def test_forged_or_modified_resume_manifest_cannot_claim_source_provenance(self):
        self.fixture('one.txt'); docs=await self.discover(); first=await self.batch(docs)
        original=Path(first['manifest_path']); forged=self.root/'forged-manifest.json'
        forged.write_bytes(original.read_bytes())
        with self.assertRaises(PolicyError): await self.batch(docs,resume_manifest=str(forged),resume_manifest_sha256=first['manifest_sha256'])
        decoded=json.loads(original.read_text()); decoded['files'][0]['sha256']='0'*64
        original.write_text(json.dumps(decoded)); digest=hashlib.sha256(original.read_bytes()).hexdigest()
        with self.assertRaises(PolicyError): await self.batch(docs,resume_manifest=str(original),resume_manifest_sha256=digest)
        self.assertEqual(len(self.browser_context.navigations),1)

    async def test_same_content_and_duplicate_input_have_deterministic_manifest(self):
        self.fixture('one.txt',b'same'); self.fixture('two.txt',b'same')
        docs=await self.discover(); report=await self.batch([docs[0],docs[0],docs[1]])
        self.assertEqual(report['status'],'verified')
        self.assertEqual([r['status'] for r in report['files']],['success','skipped','skipped'])
        self.assertEqual(report['files'][1]['reason'],'duplicate_link')
        self.assertEqual(report['files'][2]['reason'],'duplicate_content_preserved')

    async def test_uncertain_failures_never_retry_but_known_reset_does(self):
        self.fixture('one.txt',failure='net::ERR_FAILED')
        report=await self.batch(retries=2)
        self.assertEqual(report['files'][0]['attempts'],1)
        self.fixture('two.txt',failure='net::ERR_CONNECTION_RESET')
        docs=await self.discover(); report=await self.batch([docs[-1]],retries=2)
        self.assertEqual(report['files'][0]['attempts'],3)
        self.assertEqual(report['status'],'failed')

    async def test_cancellation_preserves_manifest_and_primary_page(self):
        self.fixture('slow.txt',delay=1)
        docs=await self.discover(); job=asyncio.create_task(self.batch(docs))
        await asyncio.sleep(.05); job.cancel(); report=await job
        self.assertEqual(report['status'],'cancelled')
        self.assertTrue(report['side_effects_uncertain'])
        self.assertTrue(Path(report['manifest_path']).exists()); self.assertFalse(self.page.closed)
        self.assertEqual(self.browser._approved_web_downloads,{})

    async def test_tab_cap_is_respected(self):
        self.config['max_tool_tabs']=1; self.fixture('one.txt')
        report=await self.batch(); self.assertEqual(report['status'],'failed')
        self.assertEqual(len(self.browser_context.pages),1)

    async def test_transfer_changed_hash_secrets_zip_and_queue_atomicity(self):
        good=self.root/'good.txt'; good.write_text('safe context')
        args={'files':[{'path':str(good),'sha256':'0'*64}]}
        with self.assertRaises(PolicyError): await execute_documents('files.transfer_to_copilot',args,self.context,self.policy)
        self.assertEqual(self.context['pending_file_attachments'],[])
        secret=self.root/'secret.txt'; secret.write_text('api_key=FAKE_PRIVATE_VALUE')
        args={'files':[{'path':str(secret),'sha256':hashlib.sha256(secret.read_bytes()).hexdigest()}]}
        result=await execute_documents('files.transfer_to_copilot',args,self.context,self.policy)
        self.assertEqual(result['count'],0); self.assertEqual(result['omitted_count'],1)
        zipped=self.root/'package.zip'; zipped.write_bytes(b'PK\x03\x04test')
        args={'files':[{'path':str(zipped),'sha256':hashlib.sha256(zipped.read_bytes()).hexdigest()}]}
        result=await execute_documents('files.transfer_to_copilot',args,self.context,self.policy)
        self.assertEqual(result['count'],0); self.assertEqual(result['omitted_count'],1)
        self.assertEqual(self.context['approved_attachment_hashes'],{})

    async def test_destination_escape_and_profile_path_denied(self):
        self.fixture('one.txt'); docs=await self.discover()
        with self.assertRaises(PolicyError): await self.batch(docs,destination=str(self.root.parent/'outside'))
        self.assertEqual(self.browser_context.navigations,[])


class ShapeTests(unittest.TestCase):
    def test_catalogue_examples_are_strongly_typed(self):
        from copilot_agent.protocol import validate_schema
        for name,args in DOCUMENT_EXAMPLES.items():
            self.assertEqual(validate_schema(args,DOCUMENT_SPECS[name][0]),[],name)
            validate_documents(name,args)
    def test_strict_bounded_arguments(self):
        cases=[('browser.download_batch',{'documents':[],'destination':'x'}),
            ('browser.download_batch',{'documents':[{'document_id':'id','url':'https://example.test/doc.pdf'}],'destination':'x'}),
            ('browser.download_batch',{'documents':[{'document_id':'id'}],'destination':'x','concurrency':True}),
            ('browser.download_batch',{'documents':[{'document_id':'id','expected_sha256':'bad'}],'destination':'x'}),
            ('files.transfer_to_copilot',{'files':[{'path':'x','sha256':'0'*64}]*1001})]
        for name,args in cases:
            with self.assertRaises(ValueError,msg=str(args)): validate_documents(name,args)
        self.assertEqual(DOCUMENT_SPECS['browser.documents'][1],'read_only')
        self.assertEqual(DOCUMENT_SPECS['browser.download_batch'][1],'user_approval')


if __name__=='__main__': unittest.main()
