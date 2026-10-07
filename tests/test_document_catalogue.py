"""Large authorised collections stay retrievable within the hard upload budget."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from copilot_agent.policy import PathPolicy, PolicyError
from copilot_agent.web_documents import execute_documents


class CatalogueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='copilot_catalogue_'); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve(); self.policy=PathPolicy([self.root])
        self.context={'session_dir':str(self.root),'config':{'storage_dir':str(self.root),'allowed_roots':[str(self.root)]},
            'approved':True,'pending_file_attachments':[],'approved_attachment_hashes':{},
            'document_catalogues':{},'transferred_attachment_hashes':{},
            'remaining_attachment_capacity':10,'task_id':'authorised-task','customer_key':'scope-customer','tenant_id':'scope-tenant'}

    def collection(self,count,prefix='evidence',size=20):
        files=[]
        for index in range(count):
            path=self.root/(prefix+'-'+str(index).zfill(3)+'.txt')
            path.write_text(('observed information '+str(index)).ljust(size,' '),encoding='utf-8')
            files.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        return files

    async def call(self,name,args): return await execute_documents(name,args,self.context,self.policy)

    async def test_21_50_100_document_collections_are_deferred_without_loss(self):
        for count in (21,50,100):
            with self.subTest(count=count):
                self.context['pending_file_attachments'].clear(); self.context['approved_attachment_hashes'].clear()
                files=self.collection(count,prefix='collection'+str(count))
                result=await self.call('files.transfer_to_copilot',{'files':files})
                self.assertEqual(result['count'],10); self.assertEqual(result['available_count'],count)
                self.assertEqual(result['omitted_count'],count-9)
                self.assertEqual(len(self.context['pending_file_attachments']),10)
                index=result['index']; self.assertTrue(Path(index['path']).is_file())
                manifest=json.loads(Path(index['path']).read_text())
                self.assertEqual(len(manifest['records']),count)
                requested=manifest['records'][-1]['reference']
                found=await self.call('documents.find',{'catalogue_id':result['catalogue_id'],'references':[requested],'limit':1})
                self.assertEqual(found['records'][0]['reference'],requested)
                retrieved=await self.call('documents.retrieve',{'catalogue_id':result['catalogue_id'],'references':[requested]})
                self.assertEqual(retrieved['files'][0]['sha256'],files[-1]['sha256'])
                self.assertFalse(retrieved['delivery_verified'])
                self.assertTrue(all(Path(item['path']).exists() for item in files))

    async def test_requested_and_active_workflow_files_outrank_generic_files(self):
        files=self.collection(21)
        result=await self.call('files.transfer_to_copilot',{'files':files,
            'requested_paths':[files[-1]['path']],'active_paths':[files[-2]['path']]})
        selected=[record['path'] for record in result['files']]
        self.assertEqual(selected[:2],[files[-1]['path'],files[-2]['path']])
        self.assertEqual(result['count'],10)

    async def test_metadata_query_prioritises_relevant_files_without_reading_content(self):
        files=self.collection(30)
        files[-1]['label']='Annual income evidence'; files[-1]['tags']=['income','current']
        result=await self.call('files.transfer_to_copilot',{'files':files,'query':'annual income'})
        self.assertEqual(result['files'][0]['path'],files[-1]['path'])
        self.assertEqual(result['count'],10)

    async def test_dynamic_capacity_includes_existing_queue_and_index(self):
        existing=self.collection(1,prefix='already')
        await self.call('files.transfer_to_copilot',{'files':existing})
        self.context['remaining_attachment_capacity']=3
        result=await self.call('files.transfer_to_copilot',{'files':self.collection(50)})
        self.assertEqual(result['count'],3)
        self.assertEqual(result['files'][0]['path'],existing[0]['path'])
        self.assertTrue(result['files'][-1]['path'].endswith('.json'))
        self.assertEqual(result['remaining_capacity'],0)

    async def test_no_capacity_keeps_local_index_and_resolves_deferred_originals(self):
        self.context['remaining_attachment_capacity']=0
        files=self.collection(21)
        result=await self.call('files.transfer_to_copilot',{'files':files})
        self.assertEqual(result['count'],0); self.assertEqual(result['status'],'deferred')
        self.assertEqual(self.context['pending_file_attachments'],[])
        self.assertTrue(Path(result['index']['path']).exists())
        self.assertEqual(result['omitted_count'],21)

    async def test_duplicates_are_exact_hash_deduplicated_and_similar_files_are_kept(self):
        files=self.collection(21)
        Path(files[-1]['path']).write_bytes(Path(files[0]['path']).read_bytes())
        files[-1]['sha256']=files[0]['sha256']
        result=await self.call('files.transfer_to_copilot',{'files':files})
        self.assertEqual(len({record['sha256'] for record in result['files']}),result['count'])
        self.assertTrue(any(record['reason']=='duplicate_content' for record in result['omitted']))
        first=self.root/'report-v1.txt'; second=self.root/'report-v2.txt'
        first.write_text('different old evidence'); second.write_text('different current evidence')
        self.context['pending_file_attachments'].clear()
        result=await self.call('files.transfer_to_copilot',{'files':[
            {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in (first,second)]})
        self.assertEqual(result['count'],2); self.assertTrue(result['warnings'])
        self.assertFalse(result['warnings'][0]['content_identity_proven'])

    async def test_confirmed_history_avoids_reuploads_but_exact_user_request_can_retrieve_again(self):
        files=self.collection(2)
        self.context['transferred_attachment_hashes'][files[0]['sha256']]=1
        result=await self.call('files.transfer_to_copilot',{'files':files})
        self.assertEqual(result['count'],1)
        self.assertEqual(result['omitted'][0]['reason'],'already_transferred')
        self.context['pending_file_attachments'].clear()
        result=await self.call('files.transfer_to_copilot',{'files':files[:1],'requested_paths':[files[0]['path']]})
        self.assertEqual(result['count'],1)

    async def test_catalogue_scope_changed_or_file_tampered_is_denied(self):
        files=self.collection(1)
        catalogue=await self.call('documents.catalogue',{'files':files})
        reference=catalogue['records'][0]['reference']
        self.context['tenant_id']='other-tenant'
        with self.assertRaises(PolicyError): await self.call('documents.retrieve',{'catalogue_id':catalogue['catalogue_id'],'references':[reference]})
        self.context['tenant_id']='scope-tenant'
        self.context['site_namespace_id']='another-user-or-environment'
        with self.assertRaises(PolicyError): await self.call('documents.retrieve',{'catalogue_id':catalogue['catalogue_id'],'references':[reference]})
        self.context.pop('site_namespace_id')
        Path(files[0]['path']).write_text('tampered evidence')
        with self.assertRaises(PolicyError): await self.call('documents.retrieve',{'catalogue_id':catalogue['catalogue_id'],'references':[reference]})

    async def test_manifest_import_revalidates_hash_scope_and_all_references(self):
        files=self.collection(21)
        result=await self.call('files.transfer_to_copilot',{'files':files})
        index=result['index']
        self.context['document_catalogues'].clear(); self.context['task_id']='next-approved-task'
        imported=await self.call('documents.catalogue',{'manifest_path':index['path'],'manifest_sha256':index['sha256']})
        self.assertEqual(imported['count'],21)
        retrieved=await self.call('documents.retrieve',{'catalogue_id':imported['catalogue_id'],'references':[imported['records'][0]['reference']]})
        self.assertEqual(retrieved['files'][0]['sha256'],files[0]['sha256'])
        self.context['customer_key']='other-customer'
        with self.assertRaises(PolicyError): await self.call('documents.catalogue',{'manifest_path':index['path'],'manifest_sha256':index['sha256']})
        self.context['customer_key']='scope-customer'; Path(files[0]['path']).write_text('changed original')
        with self.assertRaises(PolicyError): await self.call('documents.catalogue',{'manifest_path':index['path'],'manifest_sha256':index['sha256']})

    async def test_manifest_contents_are_metadata_only_and_hash_tampering_is_denied(self):
        files=self.collection(21)
        private='CUSTOMER_DOCUMENT_CONTENT_SENTINEL'
        Path(files[0]['path']).write_text(private); files[0]['sha256']=hashlib.sha256(private.encode()).hexdigest()
        result=await self.call('files.transfer_to_copilot',{'files':files}); index=result['index']
        raw=Path(index['path']).read_text(); self.assertNotIn(private,raw)
        with self.assertRaises(PolicyError): await self.call('documents.catalogue',{'manifest_path':index['path'],'manifest_sha256':'0'*64})

    async def test_mixed_sizes_and_supported_files_keep_identity(self):
        small=self.collection(15,prefix='small',size=50)
        medium=self.collection(3,prefix='medium',size=10000)
        large=self.collection(3,prefix='large',size=100000)
        result=await self.call('files.transfer_to_copilot',{'files':small+medium+large,'active_paths':[large[-1]['path']]})
        self.assertEqual(result['count'],10); self.assertEqual(result['files'][0]['path'],large[-1]['path'])
        index=json.loads(Path(result['index']['path']).read_text())
        self.assertEqual(len(index['records']),21)
        self.assertGreater(max(record['size'] for record in index['records']),min(record['size'] for record in index['records']))


if __name__=='__main__': unittest.main()
