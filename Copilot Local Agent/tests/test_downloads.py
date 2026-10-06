"""Offline event/approval contracts; retained fixtures, no cleanup or live UI."""
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid

from copilot_agent.downloads import DownloadError, DownloadService, validate_download_args
from copilot_agent.policy import PathPolicy


class FakeSettingsPage:
    def __init__(self, context):
        self.context = context
        self.closed = False
    async def goto(self, url, **kwargs):
        self.context.urls.append(url)
    async def evaluate(self, script):
        return {'paths':[str(self.context.directory)],
                'toggles':[{'label':'Ask me what to do with each download','pref_key':'download.prompt_for_download','checked':self.context.prompt}]}
    async def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, directory):
        self.directory, self.prompt = directory, False
        self.pages, self.urls = [], []
    async def new_page(self):
        page = FakeSettingsPage(self)
        self.pages.append(page)
        return page


class FakeDownload:
    def __init__(self, directory, name, data, url):
        self.suggested_filename, self.data, self.url = name, data, url
        directory.mkdir(parents=True, exist_ok=True)
        self.original = directory / ('native-'+uuid.uuid4().hex+'-'+name)
        self.original.write_bytes(data)
        self.saved = []
    async def path(self):
        return str(self.original)
    async def save_as(self, path):
        with Path(path).open('xb') as handle:
            handle.write(self.data)
        self.saved.append(path)
    async def failure(self):
        return None


class Pending:
    def __init__(self, page):
        self.page = page
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False
    @property
    def value(self):
        async def result():
            return self.page.item
        return result()


class FakeAnchor:
    def __init__(self, page):
        self.page, self.clicks = page, 0
    async def evaluate(self, script):
        return self.page.links[0]['href']
    async def click(self, **kwargs):
        self.clicks += 1


class FakeLocator:
    def __init__(self, page):
        self.page = page
    def nth(self, index):
        return self
    async def element_handle(self):
        return self.page.anchor


class FakePage:
    def __init__(self, item):
        self.item = item
        self.url = 'https://m365.cloud.microsoft/chat/conversation/synthetic-readonly'
        self.links = [{'key':3,'index':0,'href':item.url,'raw_href':item.url,'label':'Download report','enabled':True}]
        self.error = None
        self.anchor = FakeAnchor(self)
    async def evaluate(self, script, args=None):
        if self.error:
            return {'error':self.error}
        return {'user_key':1,'assistant_key':2,'links':copy.deepcopy(self.links)}
    def locator(self, selector):
        return FakeLocator(self)
    def expect_download(self, **kwargs):
        return Pending(self)


class ArgumentsTests(unittest.TestCase):
    def test_unsafe_names_and_direct_urls_rejected(self):
        for name in ('../x.zip','C:\\x.zip','x:y.txt','x/other.txt','CON.txt','COM¹.txt','NUL','report.',' report.zip','x\n.zip','..'):
            with self.assertRaises(DownloadError, msg=name):
                validate_download_args({'expected_name':name})
        with self.assertRaises(DownloadError):
            validate_download_args({'expected_name':'good.zip','url':'https://example.com'})
        self.assertEqual(validate_download_args({'expected_name':'good.zip'}), {'expected_name':'good.zip'})


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(os.environ.get('COPILOT_TEST_ROOT', str(Path(__file__).resolve().parents[1] / 'runtime' / 'tests'))) / ('downloads-'+uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.storage = self.root / 'onedrive-selected'
        self.storage.mkdir()
        self.default = self.root / 'fake-configured-downloads'
        url = 'https://eu-prod.asyncgw.teams.microsoft.com/objects/report?signature=SECRET_SIGNED_VALUE'
        self.item = FakeDownload(self.default, 'report.zip', b'PK\x03\x04synthetic-zip-header-test', url)
        self.page = FakePage(self.item)
        self.context = FakeContext(self.default)
        self.browser = SimpleNamespace(page=self.page,context=self.context,
                                       last_submission={'request_id':'req-current','user_key':1,'committed':True})
        self.config = SimpleNamespace(storage_dir=self.storage,download_timeout=1,max_download_bytes=2000)
        self.service = DownloadService(self.browser,self.config,PathPolicy([self.root]),self.root / 'session')
        self.service.feedback = lambda message:None

    async def test_event_backed_save_hash_and_original_retention(self):
        args = {'expected_name':'report.zip','expected_sha256':hashlib.sha256(self.item.data).hexdigest()}
        binding = await self.service.prepare(args,'req-current')
        self.assertNotIn('SECRET_SIGNED_VALUE', json.dumps(binding))
        self.assertTrue(Path(binding['destination']).is_relative_to(self.storage))
        self.assertEqual(binding['settings']['configured_directory'],str(self.default))
        self.assertTrue(all(url=='edge://settings/downloads' for url in self.context.urls))
        self.assertTrue(all(page.closed for page in self.context.pages))
        result = await self.service.download(args,binding)
        self.assertEqual(result['status'],'verified')
        self.assertEqual(result['sha256'],args['expected_sha256'])
        self.assertTrue(Path(result['path']).is_file())
        self.assertTrue(self.item.original.is_file())
        self.assertTrue(result['default_directory_save_proven'])
        self.assertEqual(self.page.anchor.clicks,1)
        with self.assertRaises(DownloadError):
            await self.service.download(args,binding)
        self.assertEqual(self.page.anchor.clicks,1)

    async def test_binding_tamper_blocked_before_click(self):
        args = {'expected_name':'report.zip'}
        binding = await self.service.prepare(args,'req-current')
        binding['destination'] = str(self.root / 'changed.zip')
        with self.assertRaises(DownloadError) as caught:
            await self.service.download(args,binding)
        self.assertFalse(caught.exception.side_effects_uncertain)
        self.assertEqual(self.page.anchor.clicks,0)

    async def test_wrong_hash_preserves_file_and_stops_after_click(self):
        args = {'expected_name':'report.zip','expected_sha256':'0'*64}
        binding = await self.service.prepare(args,'req-current')
        with self.assertRaises(DownloadError) as caught:
            await self.service.download(args,binding)
        self.assertEqual(caught.exception.code,'hash_mismatch')
        self.assertTrue(caught.exception.side_effects_uncertain)
        self.assertTrue(Path(binding['destination']).is_file())
        self.assertTrue(self.item.original.exists())

    async def test_inert_sandbox_and_foreign_anchors_rejected(self):
        for href in ('sandbox:/mnt/data/report.zip','https://evil.example/report.zip',self.item.url):
            self.page.links[0]['href'] = href
            self.page.links[0]['raw_href'] = '#' if href == self.item.url else href
            with self.assertRaises(DownloadError):
                await self.service.prepare({'expected_name':'report.zip'},'req-current')
        self.assertEqual(self.page.anchor.clicks,0)

    async def test_missing_plaintext_and_ambiguous_anchors_rejected(self):
        self.page.links = []
        with self.assertRaises(DownloadError):
            await self.service.prepare({'expected_name':'report.zip'},'req-current')
        self.page.links = [dict(key=3,index=0,href=self.item.url,raw_href=self.item.url,label='A'),
                           dict(key=4,index=1,href=self.item.url,raw_href=self.item.url,label='B')]
        with self.assertRaises(DownloadError):
            await self.service.prepare({'expected_name':'report.zip'},'req-current')

    async def test_prompt_setting_honored_then_completed_native_artifact_copied(self):
        self.context.prompt = True
        args = {'expected_name':'report.zip'}
        binding = await self.service.prepare(args,'req-current')
        feedback = []
        self.service.feedback = feedback.append
        result = await self.service.download(args,binding)
        self.assertEqual(result['status'],'downloaded')
        self.assertEqual(self.page.anchor.clicks,1)
        self.assertTrue(feedback)
        self.assertEqual(self.item.saved,[])
        self.assertIn('exclusive copy',result['save_method'])

    async def test_pending_native_prompt_never_bypassed_with_save_as(self):
        self.context.prompt = True
        self.service.feedback = lambda message:None
        async def unavailable():
            raise RuntimeError('native prompt unfinished')
        self.item.path = unavailable
        args = {'expected_name':'report.zip'}
        binding = await self.service.prepare(args,'req-current')
        with self.assertRaises(DownloadError) as caught:
            await self.service.download(args,binding)
        self.assertEqual(caught.exception.code,'native_completion_required')
        self.assertTrue(caught.exception.side_effects_uncertain)
        self.assertEqual(self.item.saved,[])
        self.assertFalse(Path(binding['destination']).exists())

    async def test_changed_href_or_source_requires_new_preview(self):
        args = {'expected_name':'report.zip'}
        binding = await self.service.prepare(args,'req-current')
        self.page.links[0]['href'] += 'changed'
        with self.assertRaises(DownloadError):
            await self.service.download(args,binding)
        self.assertEqual(self.page.anchor.clicks,0)
        self.browser.last_submission['request_id'] = 'different'
        with self.assertRaises(DownloadError):
            await self.service.download(args,binding)

    async def test_wrong_filename_never_verified(self):
        args = {'expected_name':'report.zip'}
        binding = await self.service.prepare(args,'req-current')
        self.item.suggested_filename = 'wrong.zip'
        with self.assertRaises(DownloadError) as caught:
            await self.service.download(args,binding)
        self.assertEqual(caught.exception.code,'filename_mismatch')
        self.assertTrue(caught.exception.side_effects_uncertain)
        self.assertFalse(Path(binding['destination']).exists())

    async def test_invalid_zip_header_retained_and_rejected(self):
        self.item.data = b'not a zip archive'
        self.item.original.write_bytes(self.item.data)
        args = {'expected_name':'report.zip'}
        binding = await self.service.prepare(args,'req-current')
        with self.assertRaises(DownloadError) as caught:
            await self.service.download(args,binding)
        self.assertEqual(caught.exception.code,'archive_invalid')
        self.assertTrue(caught.exception.side_effects_uncertain)
        self.assertEqual(Path(binding['destination']).read_bytes(),self.item.data)
        self.assertTrue(self.item.original.exists())

    async def test_oversized_original_is_preserved_without_staging_copy(self):
        self.config.max_download_bytes = 4
        args = {'expected_name':'report.zip'}
        binding = await self.service.prepare(args,'req-current')
        with self.assertRaises(DownloadError) as caught:
            await self.service.download(args,binding)
        self.assertEqual(caught.exception.code,'size_exceeded')
        self.assertTrue(caught.exception.side_effects_uncertain)
        self.assertTrue(self.item.original.exists())
        self.assertFalse(Path(binding['destination']).exists())

    async def test_existing_destination_never_overwritten_or_clicked(self):
        args = {'expected_name':'report.zip'}
        binding = await self.service.prepare(args,'req-current')
        destination = Path(binding['destination'])
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b'preserve this existing artifact')
        with self.assertRaises(DownloadError) as caught:
            await self.service.download(args,binding)
        self.assertEqual(caught.exception.code,'destination_changed')
        self.assertFalse(caught.exception.side_effects_uncertain)
        self.assertEqual(self.page.anchor.clicks,0)
        self.assertEqual(destination.read_bytes(),b'preserve this existing artifact')

    async def test_changed_settings_require_fresh_approval(self):
        args = {'expected_name':'report.zip'}
        binding = await self.service.prepare(args,'req-current')
        self.context.prompt = True
        with self.assertRaises(DownloadError) as caught:
            await self.service.download(args,binding)
        self.assertEqual(caught.exception.code,'settings_changed')
        self.assertFalse(caught.exception.side_effects_uncertain)
        self.assertEqual(self.page.anchor.clicks,0)

    async def test_uncommitted_source_rejected(self):
        del self.browser.last_submission['committed']
        with self.assertRaises(DownloadError) as caught:
            await self.service.prepare({'expected_name':'report.zip'},'req-current')
        self.assertEqual(caught.exception.code,'stale_source')

    async def test_python_delivery_is_verified_without_execution(self):
        self.item.suggested_filename = 'safe.py'
        sentinel = self.storage / 'must-not-be-created.txt'
        self.item.data = ('from pathlib import Path\nPath('+repr(str(sentinel))+').write_text("executed")\n').encode()
        self.item.original.write_bytes(self.item.data)
        args = {'expected_name':'safe.py'}
        binding = await self.service.prepare(args,'req-current')
        result = await self.service.download(args,binding)
        self.assertEqual(result['artifact_validation']['python_syntax'],'passed_without_execution')
        self.assertFalse(sentinel.exists())
        self.assertTrue(self.item.original.exists())

    async def test_invalid_json_artifact_is_retained_and_rejected(self):
        self.item.suggested_filename = 'bad.json'
        self.item.data = b'{"key":1,"key":2}'
        self.item.original.write_bytes(self.item.data)
        args = {'expected_name':'bad.json'}
        binding = await self.service.prepare(args,'req-current')
        with self.assertRaises(DownloadError) as caught:
            await self.service.download(args,binding)
        self.assertEqual(caught.exception.code,'artifact_invalid')
        self.assertTrue(caught.exception.side_effects_uncertain)
        self.assertEqual(Path(binding['destination']).read_bytes(),self.item.data)
        self.assertTrue(self.item.original.exists())

    async def test_known_no_prompt_cdp_path_unavailable_uses_event_save_as(self):
        async def unsupported():
            raise RuntimeError('Path unavailable with remote CDP')
        self.item.path = unsupported
        args = {'expected_name':'report.zip'}
        binding = await self.service.prepare(args,'req-current')
        result = await self.service.download(args,binding)
        self.assertEqual(self.item.saved,[binding['destination']])
        self.assertFalse(result['default_directory_save_proven'])
        self.assertEqual(result['original_browser_artifact'],{'path':None,'retained':False})

    def native_blob(self, href=None, download='report.zip'):
        self.item.url = href or 'blob:https://m365.cloud.microsoft/523e6188-332c-4563-82db-544e3beaddc7'
        self.page.links[0].update(href=self.item.url,raw_href=self.item.url,download=download)

    async def test_observed_same_origin_native_blob_event_verified(self):
        self.native_blob()
        args = {'expected_name':'report.zip'}
        binding = await self.service.prepare(args,'req-current')
        self.assertEqual(binding['source_scheme'],'blob')
        self.assertEqual(binding['source_host'],'m365.cloud.microsoft')
        self.assertNotIn('blob:',json.dumps(binding))
        report = await self.service.download(args,binding)
        self.assertTrue(report['download_event_observed'])
        self.assertEqual(self.page.anchor.clicks,1)
        self.assertTrue(Path(report['path']).is_file())

    async def test_native_blob_origin_uuid_and_download_name_are_mandatory(self):
        for href, name in (
            ('blob:https://evil.example/523e6188-332c-4563-82db-544e3beaddc7','report.zip'),
            ('blob:null/523e6188-332c-4563-82db-544e3beaddc7','report.zip'),
            ('blob:https://m365.cloud.microsoft/not-a-generated-uuid','report.zip'),
            ('blob:https://m365.cloud.microsoft/523e6188-332c-4563-82db-544e3beaddc7?token=unsafe','report.zip'),
            ('blob:https://m365.cloud.microsoft/523e6188-332c-4563-82db-544e3beaddc7',None),
            ('blob:https://m365.cloud.microsoft/523e6188-332c-4563-82db-544e3beaddc7','different.zip')):
            self.native_blob(href,name)
            with self.assertRaises(DownloadError) as caught:
                await self.service.prepare({'expected_name':'report.zip'},'req-current')
            self.assertEqual(caught.exception.code,'unsupported_link')
        self.assertEqual(self.page.anchor.clicks,0)
        self.assertTrue(self.context.pages)
        self.assertTrue(all(page.closed for page in self.context.pages))

    async def test_native_blob_download_attribute_change_blocks_before_click(self):
        self.native_blob()
        args = {'expected_name':'report.zip'}
        binding = await self.service.prepare(args,'req-current')
        self.page.links[0]['download']='changed.zip'
        with self.assertRaises(DownloadError) as caught:
            await self.service.download(args,binding)
        self.assertFalse(caught.exception.side_effects_uncertain)
        self.assertEqual(self.page.anchor.clicks,0)

    async def test_native_blob_event_must_match_exact_approved_artifact(self):
        self.native_blob()
        args = {'expected_name':'report.zip'}
        binding = await self.service.prepare(args,'req-current')
        self.item.url='blob:https://m365.cloud.microsoft/623e6188-332c-4563-82db-544e3beaddc7'
        with self.assertRaises(DownloadError) as caught:
            await self.service.download(args,binding)
        self.assertEqual(caught.exception.code,'event_source_mismatch')
        self.assertTrue(caught.exception.side_effects_uncertain)
        self.assertFalse(Path(binding['destination']).exists())


if __name__=='__main__':
    unittest.main()
