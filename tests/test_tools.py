import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from copilot_agent.tools import ToolRegistry, validate
from copilot_agent.tools import STRUCTURE_SCRIPT
from copilot_agent.policy import PathPolicy, URLPolicy, PolicyError
from copilot_agent.policy import resolve_s_drive_output
from copilot_agent.state import SessionState
from copilot_agent.config import Config


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix="copilot_tools_test_"))
        self.registry=ToolRegistry()
        self.context={"config":{"allowed_roots":[str(self.root)],"allowed_domains":["example.com"]},"session_dir":str(self.root)}

    def run_tool(self,name,args): return asyncio.run(self.registry.execute(name,args,self.context))

    def test_mapped_s_share_is_an_optional_permitted_root(self):
        share = self.root / 'mapped-share'
        share.mkdir()
        config = Config(root=self.root, allowed_roots=['workspace'])
        with patch('copilot_agent.config.mapped_s_drive_root', return_value=share):
            config.validate()
            config.validate()
        expected = [str((self.root / 'workspace').resolve())]
        expected.append(str(share))
        self.assertEqual(config.allowed_roots, expected)
        self.assertEqual(config._auto_s_drive_root, str(share))
        with patch('copilot_agent.config.mapped_s_drive_root', side_effect=PolicyError('unmapped')):
            config.validate()
        self.assertEqual(config.allowed_roots, expected[:-1])

    @unittest.skipUnless(os.name == 'nt', 'Windows C: drive scope')
    def test_local_c_drive_is_never_an_agent_write_target(self):
        config = Config(root=self.root, allowed_roots=['workspace'])
        config.validate()
        outside = self.root / 'other-folder'
        outside.mkdir()
        self.context['config'] = config
        args = {'path': str(outside / 'report.md'), 'text': 'Local report.'}
        with self.assertRaises(PolicyError):
            self.registry.validate_call('files.create', args, self.context)
        self.assertFalse((outside / 'report.md').exists())

    def test_mapped_s_root_allows_read_and_approved_create(self):
        share = self.root / 'mapped-share'
        share.mkdir()
        existing = share / 'existing.md'
        existing.write_text('From S.', encoding='utf-8')
        self.context['config']['allowed_roots'].append(str(share))
        self.context['config']['_auto_s_drive_root'] = str(share)
        args = {'path': r'S:\new.md', 'text': 'Saved to S.'}
        with patch('copilot_agent.policy.mapped_s_drive_root', return_value=share), \
             patch('copilot_agent.policy.resolve_s_drive_output', side_effect=lambda path, **kw: share / Path(path).name), \
             patch('copilot_agent.tools.resolve_s_drive_output', side_effect=lambda path, **kw: share / Path(path).name):
            read = self.run_tool('files.read', {'path': r'S:\existing.md'})
            self.assertEqual(read['result']['text'], 'From S.')
            prepared = self.registry.validate_call('files.create', args, self.context)
            self.assertEqual(prepared['s_drive_destination'], str(share / 'new.md'))
            self.context.update(approved=True, s_drive_destination=prepared['s_drive_destination'])
            created = self.run_tool('files.create', args)
            self.assertTrue(created['ok'])
            self.assertEqual((share / 'new.md').read_text(encoding='utf-8'), 'Saved to S.')

    def test_approval_and_create_only(self):
        args={"path":"new.txt","text":"original"}
        self.assertFalse(self.run_tool("files.create",args)["ok"])
        self.assertFalse((self.root/"new.txt").exists())
        self.context["approved"]=True
        self.assertFalse(self.run_tool("files.create",args)["ok"])
        self.assertFalse((self.root/"new.txt").exists())
        crlf = {'path': 'windows-lines.md', 'text': 'First\r\nSecond\r\n'}
        self.assertFalse(self.run_tool('files.create', crlf)['ok'])
        self.assertFalse((self.root / 'windows-lines.md').exists())

    def test_exact_s_output_is_bound_to_approved_unc_identity(self):
        folder = self.root / 'simulated-share'
        folder.mkdir()
        target = folder / 'report.md'
        args = {'path': r'S:\Reports\report.md', 'text': 'Verified findings.\n'}
        with patch('copilot_agent.tools.resolve_s_drive_output', return_value=target):
            prepared = self.registry.validate_call('files.create', args, self.context)
            self.assertEqual(str(target), prepared['s_drive_destination'])
            self.context['approved'] = True
            self.assertFalse(self.run_tool('files.create', args)['ok'])
            self.assertFalse(target.exists())
            self.context['s_drive_destination'] = prepared['s_drive_destination']
            result = self.run_tool('files.create', args)
        self.assertTrue(result['ok'])
        self.assertTrue(result['result']['verified'])
        self.assertEqual(args['text'], target.read_text(encoding='utf-8'))

    def test_s_mapping_change_after_approval_prevents_creation(self):
        first = self.root / 'first'
        second = self.root / 'second'
        first.mkdir(); second.mkdir()
        args = {'path': r'S:\Reports\report.md', 'text': 'No misplaced output.'}
        self.context.update(approved=True, s_drive_destination=str(first / 'report.md'))
        with patch('copilot_agent.tools.resolve_s_drive_output', return_value=second / 'report.md'):
            result = self.run_tool('files.create', args)
        self.assertFalse(result['ok'])
        self.assertFalse(result['result']['side_effects_uncertain'])
        self.assertFalse((first / 'report.md').exists())
        self.assertFalse((second / 'report.md').exists())

    def test_copy_to_approved_s_destination(self):
        source = self.root / 'source.md'
        source.write_text('Reviewed export.', encoding='utf-8')
        folder = self.root / 'simulated-share'
        folder.mkdir()
        target = folder / 'export.md'
        args = {'source': 'source.md', 'destination': r'S:\Exports\export.md'}
        self.context.update(approved=True, s_drive_destination=str(target))
        with patch('copilot_agent.tools.resolve_s_drive_output', return_value=target):
            result = self.run_tool('files.copy', args)
        self.assertTrue(result['ok'])
        self.assertEqual(source.read_bytes(), target.read_bytes())

    def test_s_resolver_accepts_only_live_mapped_share_identity(self):
        import os
        if os.name != 'nt':
            self.skipTest('Windows mapped-drive identity')
        class CheckedPolicy:
            def __init__(self, roots, excluded_roots=()):
                self.assert_root = roots[0]
            def resolve(self, path, must_exist=False):
                self_root = self.assert_root
                if self_root != r'\\server\share':
                    raise AssertionError(self_root)
                return path
        observed = {
            'S:\\': r'\\server\share',
            r'S:\Reports': r'\\server\share\Reports',
            r'\\server\share\Reports': r'\\server\share\Reports',
            r'\\other\share\Reports': r'\\other\share\Reports',
        }
        def final(value, strict=True):
            return observed[value]
        with patch('copilot_agent.policy.os.path.realpath', side_effect=final), \
             patch('copilot_agent.policy.reject_path_redirection'), \
             patch('copilot_agent.policy.PathPolicy', CheckedPolicy):
            self.assertEqual(str(resolve_s_drive_output(r'S:\Reports\report.md')),
                             r'\\server\share\reports\report.md')
            self.assertEqual(str(resolve_s_drive_output(r'\\server\share\Reports\report.md')),
                             r'\\server\share\reports\report.md')
            with self.assertRaises(PolicyError):
                resolve_s_drive_output(r'\\other\share\Reports\report.md')
            with self.assertRaises(PolicyError):
                resolve_s_drive_output(r'S:relative.md')

    def test_quarantine_requires_approval_and_retains_unknown_outcome(self):
        state = SessionState(self.root / 'session')
        uncertain = {'call_id': 'prior-save', 'name': 'site_knowledge.save', 'version': '1.0',
                     'arguments': {'origin': 'https://example.com'}}
        state.begin_call(uncertain)
        state.finish_call('prior-save', {'ok': False, 'error': {'code': 'timeout'}})
        self.context['session_state'] = state
        denied = self.run_tool('operation.quarantine', {'call_id': 'prior-save'})
        self.assertFalse(denied['ok'])
        self.assertEqual('uncertain', state.data['calls']['prior-save']['status'])
        self.context['approved'] = True
        result = self.run_tool('operation.quarantine', {'call_id': 'prior-save'})
        self.assertTrue(result['ok'])
        self.assertFalse(result['result']['completion_credited'])
        self.assertEqual('abandoned_unverifiable', state.data['calls']['prior-save']['status'])

    def test_path_escape_and_unsupported_arguments(self):
        self.assertFalse(self.run_tool("files.read",{"path":"../outside.txt"})["ok"])
        self.assertFalse(self.run_tool("files.exists",{"path":"x","extra":True})["ok"])
        self.assertFalse(self.run_tool("unknown",{})["ok"])

    def test_hash_and_copy(self):
        self.context["approved"]=True
        self.assertFalse(self.run_tool("files.create",{"path":"source.txt","text":"abc"})['ok'])
        self.assertFalse(self.run_tool("files.copy",{"source":"source.txt","destination":"copy.txt"})["ok"])

    def test_catalog_examples_validate(self):
        for definition in self.registry.definitions():
            for example in definition["examples"]: validate(example["arguments"],definition["input_schema"])
            self.assertIn("approval_policy",definition)
            for key in ["intended_use","preconditions","risk_level","timeout","output_size_limit","error_codes","output_schema"]:
                self.assertIn(key,definition)

    def test_urls(self):
        policy=URLPolicy(["example.com"])
        self.assertEqual(policy.resolve("https://example.com/x"),"https://example.com/x")
        self.assertEqual(policy.resolve("https://deep.sub.example.com/x"),"https://deep.sub.example.com/x")
        self.assertEqual(URLPolicy.website_domain("https://any-site.test/start"), "any-site.test")
        self.registry.validate_call("browser.open", {"url":"https://new-site.test/start"}, self.context)
        for url in ["http://example.com", "https://notexample.com", "https://user:password@example.com", "file:///x", "https://example.com:444"]:
            with self.assertRaises((PolicyError,ValueError)): policy.resolve(url)

    def test_preflight_is_side_effect_free(self):
        with self.assertRaises(PolicyError):
            self.registry.validate_call("files.create",{"path":"planned.txt","text":"test"},self.context)
        self.assertFalse((self.root/"planned.txt").exists())
        with self.assertRaises(PolicyError): self.registry.validate_call("files.create",{"path":"../escape.txt","text":"test"},self.context)

    def test_result_redaction_and_total_limit(self):
        result=self.registry._limit({"ok":True,"tool":"synthetic","result":{"text":"api_key=abc123 " + "x"*20000}},self.context)
        import json
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False)),12000)
        self.assertNotIn("abc123",json.dumps(result))
        retained=Path(result["result"]["retained_result"]).read_text(encoding="utf-8")
        self.assertNotIn("abc123",retained)

    def test_created_baseline_and_image_queue(self):
        self.context["config"]["created_dir"]=str(self.root)
        self.context["config"]["created_sync_enabled"]=True
        snapshot=self.run_tool("created.snapshot",{})
        self.assertTrue(snapshot["ok"])
        self.assertIn(snapshot["result"]["baseline_id"],self.context["created_snapshots"])
        self.assertFalse(self.run_tool("created.wait",{"baseline_id":"unknown"})["ok"])
        class Browser:
            async def attach_files(self,paths): raise AssertionError("Must queue rather than upload immediately")
        self.context["browser"]=Browser()
        self.context["approved"]=True
        (self.root/"test.png").write_bytes(b"\x89PNG\r\n\x1a\n"+b"synthetic header")
        result=self.run_tool("ocr.image",{"path":"test.png"})
        self.assertEqual(result["result"]["status"],"pending_attachment_for_analysis")
        self.assertEqual(self.context["pending_image_attachments"],[str((self.root/"test.png").resolve())])

    def test_output_validation_and_url_scrubbing(self):
        from copilot_agent.protocol import validate_schema
        for name,args in [("system.versions",{}),("files.exists",{"path":"absent.txt"}),("files.read",{"path":"absent.txt"})]:
            result=self.run_tool(name,args)
            self.assertEqual(validate_schema(result,self.registry.definition(name)["output_schema"]),[])
        result=self.registry._limit({"ok":True,"tool":"browser.info","result":{"url":"https://example.com/?token=SECRET#private","title":"test"}},self.context)
        self.assertEqual(result["result"]["url"],"https://example.com/")
        self.assertEqual(self.registry.definition("created.wait")["timeout"],300)

    def test_alias_append_and_device_paths_denied(self):
        import os
        original=self.root/"original.txt"
        alias=self.root/"alias.txt"
        original.write_text("unchanged")
        try: os.link(original,alias)
        except OSError: self.skipTest("Hardlink creation unavailable")
        self.context["approved"]=True
        self.assertFalse(self.run_tool("files.append",{"path":"alias.txt","text":"change"})["ok"])
        self.assertEqual(original.read_text(),"unchanged")
        for name in ["NUL","CON.txt","ordinary.txt:secret"]:
            self.assertFalse(self.run_tool("files.exists",{"path":name})["ok"])

    def test_structure_schema_and_safe_extraction_contract(self):
        from copilot_agent.protocol import validate_schema
        control={"tag":"button","type":"submit","role":"button","label":"Save","text":"Save","attributes":{"id":"save-button","data-testid":"save"},"visible":True,"enabled":True,"selector":"#save-button","href":None}
        result=self.registry._limit({"ok":True,"tool":"browser.structure","result":{"controls":[control]}},self.context)
        schema=self.registry.definition("browser.structure")["output_schema"]
        self.assertEqual(validate_schema(result,schema),[])
        self.assertTrue(validate_schema({"ok":True,"tool":"browser.structure","result":{"controls":[{**control,"attributes":{"value":"secret"}}]}},schema))
        self.assertTrue(validate_schema({"ok":True,"tool":"browser.structure","result":{"controls":[{**control,"enabled":"yes"}]}},schema))
        for source in ["CSS.escape", "querySelectorAll(selector).length === 1", "nth-of-type", "element.isContentEditable", "url.pathname"]:
            self.assertIn(source,STRUCTURE_SCRIPT)
        self.assertNotIn("element.value",STRUCTURE_SCRIPT)
        self.assertNotIn("url.search",STRUCTURE_SCRIPT)

    def test_owned_process_scope(self):
        class Process:
            pid=4321
            def poll(self): return None
        class Browser: _launched_process=Process()
        self.context["browser"]=Browser()
        result=self.run_tool("system.processes",{})
        self.assertEqual(result["result"]["processes"][-1]["pid"],4321)
        self.assertEqual(len(result["result"]["processes"]),2)

    def test_structure_javascript_on_pure_dom_fixture(self):
        # Optional test-only JS runtime: no browser, network, or production Node dependency.
        import json
        import shutil
        import subprocess
        node=shutil.which("node")
        if not node: self.skipTest("Optional test-only JavaScript runtime unavailable")
        fixture=r"""
        const element=(tag,attrs={},text='')=>({tagName:tag.toUpperCase(),nodeType:1,id:attrs.id||'',children:[],parentElement:null,innerText:text,isContentEditable:false,labels:[],getAttribute:name=>attrs[name]??null,getClientRects:()=>[{}],matches:selector=>selector===':disabled'&&attrs.disabled===true});
        const html=element('html'),body=element('body'); html.children=[body];body.parentElement=html;
        const save=element('button',{id:'save:button',type:'submit'},'Save');
        const plain=element('button',{disabled:true},'Disabled');
        const password=element('input',{name:'password',type:'password'},'SECRET');password.value='SECRET';password.labels=[{innerText:'Password'}];
        const link=element('a',{href:'https://user:secret@example.com/report?token=SECRET#private'},'Report');
        body.children=[save,plain,password,link];for(const item of body.children)item.parentElement=body;
        globalThis.CSS={escape:value=>String(value).replace(/[^A-Za-z0-9_-]/g,c=>'\\'+c)};
        globalThis.getComputedStyle=()=>({visibility:'visible',display:'block'});
        const known=new Map([['#save\\:button',[save]],['input[name="password"]',[password]],['html:nth-of-type(1) > body:nth-of-type(1) > button:nth-of-type(2)',[plain]],['html:nth-of-type(1) > body:nth-of-type(1) > a:nth-of-type(1)',[link]]]);
        globalThis.document={baseURI:'https://example.com/',getElementById:()=>null,querySelectorAll:selector=>selector.startsWith('a,button,input')?body.children:(known.get(selector)||[])};
        """
        script=fixture+"\nconsole.log(JSON.stringify(("+STRUCTURE_SCRIPT+")()));"
        result=subprocess.run([node,"-e",script],capture_output=True,text=True,timeout=10,check=True)
        controls=json.loads(result.stdout)
        self.assertEqual(controls[0]["selector"],"#save\\:button")
        self.assertFalse(controls[1]["enabled"])
        self.assertIn("nth-of-type(2)",controls[1]["selector"])
        self.assertEqual(controls[2]["text"],"")
        self.assertEqual(controls[2]["label"],"Password")
        self.assertEqual(controls[3]["href"],"https://example.com/report")
        self.assertNotIn("SECRET",json.dumps(controls))
        from copilot_agent.protocol import validate_schema
        self.assertEqual(validate_schema({"ok":True,"tool":"browser.structure","result":{"controls":controls}},self.registry.definition("browser.structure")["output_schema"]),[])

    def test_browser_and_credential_stores_excluded_from_broad_root(self):
        # Resolve only synthetic nonexistent paths; never inspect real credentials.
        policy=PathPolicy([self.root])
        for relative in ["demo/edge_profile/Default/Network/Cookies", "demo/edge-profile/Default/page.txt", "ordinary/Cookies", "ordinary/Cookies-wal", "ordinary/Login Data", "ordinary/Local State", "ordinary/Web Data", "ordinary/auth.json", "ordinary/tokens.json", "AppData/Microsoft/Credentials/item", "AppData/Microsoft/Vault/item", "AppData/Microsoft/Protect/item", ".kube/config"]:
            with self.assertRaises(PolicyError,msg=relative): policy.resolve(relative)
        self.assertEqual(policy.resolve("ordinary/settings.json"),(self.root/"ordinary/settings.json").resolve())
        custom_profile=self.root/"custom-browser-location"
        excluded=PathPolicy([self.root],excluded_roots=[custom_profile])
        with self.assertRaises(PolicyError): excluded.resolve(custom_profile/"Default"/"arbitrary.txt")
        self.context["config"]["profile_dir"]=str(custom_profile)
        self.assertFalse(self.run_tool("files.exists",{"path":str(custom_profile/"Default"/"arbitrary.txt")})["ok"])

    def test_hardlinked_outside_fixture_cannot_be_read_hashed_or_copied(self):
        import os
        outside=Path(tempfile.mkdtemp(prefix="copilot_hardlink_outside_test_"))
        source=outside/"harmless_fixture.txt"
        source.write_text("Synthetic harmless fixture")
        alias=self.root/"inside_alias.txt"
        try: os.link(source,alias)
        except OSError: self.skipTest("Hardlink creation unavailable")
        self.context["approved"]=True
        for name,args in [("files.read",{"path":str(alias)}),("files.hash",{"path":str(alias)}),("files.copy",{"source":str(alias),"destination":"copied.txt"})]:
            result=self.run_tool(name,args)
            self.assertFalse(result["ok"],name)
            self.assertEqual(result["error"]["code"],"policy_denied")
        self.assertFalse((self.root/"copied.txt").exists())
        with self.assertRaises(PolicyError): PathPolicy([self.root]).resolve(alias,True)

    def test_symlink_escape(self):
        outside=Path(tempfile.mkdtemp(prefix="copilot_outside_test_"))
        link=self.root/"escape"
        try: link.symlink_to(outside,target_is_directory=True)
        except OSError: self.skipTest("Symlink privilege unavailable")
        with self.assertRaises(PolicyError): PathPolicy([self.root]).resolve(link/"x")
