"""Versioned local capabilities. Browser tools use a separate owned tool page."""
import asyncio
import hashlib
import json
import platform
import shutil
import sys
import uuid
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .policy import PathPolicy, URLPolicy, PolicyError, config_value
from .code_runner import CodeRunner, REQUIRED, FIELDS
from .sync import CreatedSync
from .logging_utils import redact
from .archives import ArchiveService, inspect_zip, ArchiveError
from .downloads import DownloadError


def obj(properties, required=None):
    return {"type":"object", "properties":properties, "required":list(properties if required is None else required), "additionalProperties":False}

S = {"type":"string", "maxLength":4096}
N = {"type":"integer", "minimum":0,"maximum":10000}
PATH = {"path": S}
STRUCTURE_SCRIPT = r"""() => {
  const escape = value => CSS.escape(String(value));
  const quoted = value => '"' + escape(value) + '"';
  const unique = selector => { try { return document.querySelectorAll(selector).length === 1; } catch (_) { return false; } };
  const selectorFor = element => {
    if (element.id) { const selector='#'+escape(element.id); if(unique(selector)) return selector; }
    for(const attribute of ['data-testid','data-test-id','name']) {
      const value=element.getAttribute(attribute);
      if(value) { const selector=element.tagName.toLowerCase()+'['+attribute+'='+quoted(value)+']'; if(unique(selector)) return selector; }
    }
    const parts=[];
    for(let node=element; node && node.nodeType===1; node=node.parentElement) {
      const tag=node.tagName.toLowerCase();
      const siblings=node.parentElement?[...node.parentElement.children].filter(item=>item.tagName===node.tagName):[node];
      parts.unshift(tag+':nth-of-type('+(siblings.indexOf(node)+1)+')');
    }
    return parts.join(' > ');
  };
  const textOf = element => /^(input|textarea)$/i.test(element.tagName) || element.isContentEditable ? '' : String(element.innerText||'').trim().slice(0,200);
  const inferredRole = element => {
    if(element.getAttribute('role')) return element.getAttribute('role');
    const tag=element.tagName.toLowerCase(), type=(element.getAttribute('type')||'').toLowerCase();
    if(tag==='a') return 'link'; if(tag==='button') return 'button';
    if(tag==='select') return 'combobox'; if(tag==='textarea') return 'textbox';
    if(tag==='input') return ({checkbox:'checkbox',radio:'radio',number:'spinbutton',button:'button',submit:'button',reset:'button'})[type]||'textbox';
    return null;
  };
  return [...document.querySelectorAll('a,button,input,textarea,select,[role=button],[role=link],[role=textbox],[contenteditable=true]')]
    .filter(element=>element.getClientRects().length && getComputedStyle(element).visibility!=='hidden' && getComputedStyle(element).display!=='none')
    .slice(0,100).map(element=>{
      const attributes={};
      for(const key of ['id','name','data-testid','data-test-id']) { const value=element.getAttribute(key); if(value) attributes[key]=value.slice(0,250); }
      let href=null;
      if(element.tagName.toLowerCase()==='a' && element.getAttribute('href')!==null) { try { const url=new URL(element.getAttribute('href'),document.baseURI); if(['https:','http:'].includes(url.protocol)) href=url.protocol+'//'+url.host+url.pathname; } catch (_) {} }
      const labelNodes=element.getAttribute('aria-labelledby')?.split(/\s+/).map(id=>document.getElementById(id)).filter(Boolean)||[];
      const label=element.getAttribute('aria-label') || [...(element.labels||[]),...labelNodes].map(node=>node.innerText||'').join(' ').trim() || textOf(element);
      return {tag:element.tagName.toLowerCase(),type:element.getAttribute('type'),role:inferredRole(element),label:String(label).slice(0,200),text:textOf(element),attributes,
        visible:true,enabled:!element.matches(':disabled') && element.getAttribute('aria-disabled')!=='true',selector:selectorFor(element),href};
    });
}"""
CODE_RUNNER_PROPERTIES = {
    "script": {"type":"string", "maxLength":50000},
    "purpose": {"type":"string", "maxLength":4000},
    "language": {"type":"string", "maxLength":64},
    "working_directory": S,
    "read_paths": {"type":"array", "items":S, "maxItems":100},
    "create_paths": {"type":"array", "items":S, "maxItems":100},
    "modify_paths": {"type":"array", "items":S, "maxItems":100},
    "expected_outputs": {"type":"array", "items":S, "maxItems":100},
    "commands": {"type":"array", "items":S, "maxItems":100},
    "network_destinations": {"type":"array", "items":S, "maxItems":100},
    "permissions": {"type":"array", "items":S, "maxItems":100},
    "risk_summary": {"type":"string", "maxLength":4000},
    "recovery_notes": {"type":"string", "maxLength":4000},
    "source_path": S,
    "source_sha256": {"type":"string", "maxLength":64},
    "interpreter": S,
    "arguments": {"type":"array", "items":S, "maxItems":100},
    "imports": {"type":"array", "items":S, "maxItems":100},
    "timeout_seconds": {"type":"integer", "minimum":1, "maximum":30},
    "max_output_chars": {"type":"integer", "minimum":1, "maximum":12000},
    "expected_effects": {"type":"array", "items":S, "maxItems":100},
    "subprocesses": {"type":"array", "maxItems":20, "items":obj({
        "executable":S, "arguments":{"type":"array", "items":S, "maxItems":100},
        "persistent":{"type":"boolean"}, "purpose":{"type":"string", "maxLength":1000}})},
    "viewer_windows": {"type":"array", "maxItems":12, "items":obj({
        "title":{"type":"string", "maxLength":200}, "image_path":S,
        "display_index":{"type":"integer", "minimum":1, "maximum":32}})},
}
SPECS = {
    "files.list": (obj(PATH), "read_only", "List up to 200 immediate children inside allowed roots."),
    "files.exists": (obj(PATH), "read_only", "Check a path inside allowed roots."),
    "files.read": (obj({"path":S,"max_chars":N},["path"]), "read_only", "Read bounded UTF-8 text; binary or oversized reads fail."),
    "files.create": (obj({"path":S,"text":{"type":"string","maxLength":100000}}), "user_approval", "Create a new UTF-8 file exclusively. Never overwrite."),
    "files.append": (obj({"path":S,"text":{"type":"string","maxLength":100000}}), "user_approval", "Append text to an existing file after explicit approval; preserves prior content."),
    "files.copy": (obj({"source":S,"destination":S}), "user_approval", "Copy one bounded file to a new exclusive destination."),
    "files.metadata": (obj(PATH), "read_only", "Read size, modification time and type."),
    "files.hash": (obj(PATH), "read_only", "Calculate SHA-256 for a file up to 20 MB."),
    "files.mkdir": (obj(PATH), "user_approval", "Create a new directory with an existing allowed parent."),
    "system.versions": (obj({}), "read_only", "Read the exact current Python executable/version, operating system version and selected package versions; no environment variables."),
    "system.disk": (obj(PATH), "read_only", "Read filesystem capacity for an allowed path."),
    "system.processes": (obj({}), "read_only", "Report this agent PID and the explicitly launched owned Edge PID when available; no wider process or command-line inventory."),
    "browser.open": (obj({"url":S}), "user_approval", "After explicit approval, navigate the owned tool tab to an HTTPS website and authorize that hostname plus its subdomains for this session."),
    "browser.back": (obj({}), "user_approval", "Navigate backward only if the target history URL passes policy."),
    "browser.forward": (obj({}), "user_approval", "Navigate forward only if the target history URL passes policy."),
    "browser.info": (obj({}), "read_only", "Read tool-tab URL and title."),
    "browser.read": (obj({}), "read_only", "Read bounded visible body text from the owned tool tab."),
    "browser.structure": (obj({}), "read_only", "Read visible control roles, labels, text, stable attributes, enabled state and unique CSS selectors; exclude input values and URL queries."),
    "browser.click": (obj({"selector":S}), "user_approval", "Click one visible selector on the owned tool tab. May change third-party state."),
    "browser.fill": (obj({"selector":S,"text":{"type":"string","maxLength":10000}}), "user_approval", "Fill one ordinary text field; password fields are forbidden."),
    "browser.scroll": (obj({"pixels":{"type":"integer","minimum":-10000,"maximum":10000}}), "user_approval", "Scroll the owned tool page."),
    "browser.screenshot": (obj({}), "user_approval", "Save a screenshot of the owned tool tab to a unique session file."),
    "browser.errors": (obj({}), "read_only", "Report captured tool-page console errors if the browser adapter supplies them."),
    "browser.downloads": (obj({}), "read_only", "Report observed tool-page download events; absence is not delivery proof."),
    "ocr.image": (obj(PATH), "user_approval", "Check a local image; OCR requires an explicitly available integrated image capability."),
    "created.snapshot": (obj({}), "read_only", "When explicitly enabled, record a baseline of the configured OneDrive Copilot Created files. Otherwise report disabled without filesystem access."),
    "created.wait": (obj({"baseline_id":S,"pattern":S,"expected_names":{"type":"array","items":S,"maxItems":100}},[]), "read_only", "When explicitly enabled, wait for stable readable new or changed local OneDrive Created files. Report disabled without filesystem access otherwise."),
    "copilot.download": (obj({"expected_name":S,"link_text":S,"expected_sha256":S},["expected_name"]), "user_approval", "Download one real file link in this exact Copilot response. Inspect Edge download settings first; save and verify an exclusive local artifact. Plaintext and sandbox links are not delivery."),
    "archives.inspect": (obj(PATH), "read_only", "Inspect a bounded ZIP manifest, archive SHA-256 and native Office container type without extracting."),
    "archives.extract": (obj({"path":S,"destination":S,"expected_files":{"type":"array","items":S,"maxItems":1000},"expected_sha256":S},["path","destination","expected_sha256"]), "user_approval", "Extract a reviewed SHA-256-bound ZIP exclusively inside allowed roots; preflight paths and verify all files without executing code. Preserve original and partial outputs."),
    "code_runner": (obj(CODE_RUNNER_PROPERTIES, sorted(REQUIRED)), "immutable_plan_approval", "Run reviewed code. python_subset remains the default restricted evaluator. local_python is available only for an exact explicitly approved host-Python plan binding script bytes/hash, interpreter, arguments, imports, file/network/process/desktop scope, limits, effects and verification."),
}


def validate(value, schema):
    kind = schema.get("type")
    expected = {"object":dict,"string":str,"integer":int,"array":list,"boolean":bool}.get(kind)
    if expected and (not isinstance(value,expected) or kind == "integer" and isinstance(value,bool)):
        raise ValueError(f"Expected {kind}")
    if kind == "object":
        if set(value)-set(schema["properties"]) or set(schema["required"])-set(value): raise ValueError("Missing or unsupported arguments")
        for key,item in value.items(): validate(item,schema["properties"][key])
    elif kind in {"string","array"}:
        if len(value)>schema.get("maxLength",schema.get("maxItems",100000)): raise ValueError("Argument length exceeds limit")
        if kind == "array":
            for item in value: validate(item,schema["items"])
    elif kind == "integer" and not schema.get("minimum",0)<=value<=schema.get("maximum",10000): raise ValueError("Number outside limits")


def configured_path_policy(config, session_dir):
    profile=config_value(config,"profile_dir")
    return PathPolicy(config_value(config,"allowed_roots",[session_dir]),excluded_roots=[profile] if profile else [])


class ToolRegistry:
    def definitions(self):
        return [self.definition(name) for name in SPECS]

    def definition(self, name):
        if name not in SPECS: raise ValueError("Unknown tool")
        schema,approval,description = SPECS[name]
        examples = [{"arguments": {k: (0 if v.get("type")=="integer" else [] if v.get("type")=="array" else "example.txt") for k,v in schema["properties"].items() if k in schema["required"]}}]
        if name == "code_runner":
            examples = [{"arguments":{"script":"print('reviewed computation')","purpose":"Compute a bounded result","language":"python_subset","working_directory":".","read_paths":[],"create_paths":[],"expected_outputs":[],"commands":[],"network_destinations":[],"permissions":[],"risk_summary":"No external side effects","recovery_notes":"Review failure output before retry"}}]
        if name == "browser.open": examples = [{"arguments":{"url":"https://example.com/"}}]
        if name == "copilot.download": examples = [{"arguments":{"expected_name":"package.zip"}}]
        if name == "archives.extract": examples = [{"arguments":{"path":"package.zip","destination":"delivered-project","expected_sha256":"0"*64,"expected_files":["README.md"]}}]
        errors=["invalid_arguments","policy_denied","unavailable","operation_failed","timeout"]
        result_schema={"type":"object"}
        if name=="browser.structure":
            control_schema={"type":"object","properties":{
                "tag":{"type":"string"},"type":{"type":["string","null"]},"role":{"type":["string","null"]},"label":{"type":"string","maxLength":200},"text":{"type":"string","maxLength":200},
                "attributes":{"type":"object","properties":{key:{"type":"string","maxLength":250} for key in ("id","name","data-testid","data-test-id")},"additionalProperties":False},
                "visible":{"type":"boolean","const":True},"enabled":{"type":"boolean"},"selector":{"type":"string"},"href":{"type":["string","null"]}},
                "required":["tag","type","role","label","text","attributes","visible","enabled","selector","href"],"additionalProperties":False}
            result_schema={"anyOf":[{"type":"object","properties":{"controls":{"type":"array","items":control_schema,"maxItems":100}},"required":["controls"],"additionalProperties":False},{"type":"object","properties":{"truncated":{"const":True},"retained_result":{"type":"string"}},"required":["truncated","retained_result"]}]}
        timeout = 300 if name in {"created.wait", "copilot.download"} else 30
        return {"name":name,"version":"1.0","description":description,"intended_use":description,"preconditions":["Current validated tool call", "Configured filesystem/domain boundaries", "Explicit user grant for side effects" if approval!="read_only" else "Read-only operation"],"risk_level":"low" if approval=="read_only" else "moderate","timeout":timeout,"output_size_limit":12000,"error_codes":errors,"input_schema":schema,
                "output_schema":{"type":"object","properties":{"ok":{"type":"boolean"},"tool":{"type":"string"},"result":result_schema,"error":{"type":"object","properties":{"code":{"type":"string"},"message":{"type":"string"}},"required":["code","message"],"additionalProperties":False}},"required":["ok","tool"],"additionalProperties":False},"approval_policy":approval,
                "side_effects":[] if approval=="read_only" else ["filesystem creation or append" if name.startswith(("files.", "archives.")) or name in {"code_runner", "copilot.download"} else "browser interaction or screenshot"],
                "limits":{"timeout_seconds":timeout,"output_chars":12000,"file_bytes":20971520},
                "errors":errors,
                "examples":examples}

    def validate_input(self, name, args):
        validate(args,self.definition(name)["input_schema"])

    def validate_call(self, name, args, context):
        """Preflight a complete envelope without performing a capability."""
        self.validate_input(name,args)
        config=context.get("config",{})
        policy=context.get("policy") or configured_path_policy(config,context["session_dir"])
        if name.startswith("files.") or name in {"system.disk","ocr.image"}:
            keys=("source","destination") if name=="files.copy" else ("path",)
            resolved={key:policy.resolve(args[key]) for key in keys}
            creates=("destination",) if name=="files.copy" else ("path",) if name in {"files.create","files.mkdir"} else ()
            for key in creates:
                if resolved[key].exists(): raise PolicyError("Create destination already exists")
                if not resolved[key].parent.is_dir(): raise PolicyError("Create destination parent must exist")
        if name=="browser.open": URLPolicy.website_domain(args["url"])
        if name=="code_runner":
            CodeRunner(policy, context["session_dir"],
                       {"tool_timeout":config_value(config,"tool_timeout",10),
                        "max_output_chars":config_value(config,"max_output_chars",12000)}).validate(args)
        if name=="copilot.download":
            from .downloads import validate_download_args
            try: validate_download_args(args)
            except DownloadError as error: raise ValueError(str(error)) from error
        if name.startswith("archives."):
            source=policy.resolve(args["path"],True)
            if name=="archives.extract":
                destination=policy.resolve(args["destination"])
                storage=config_value(config,"storage_dir")
                if storage is None: raise PolicyError("Choose your OneDrive storage before ZIP extraction")
                try: destination.relative_to(Path(storage).resolve())
                except ValueError: raise PolicyError("ZIP extraction must stay inside your selected OneDrive storage")
                manifest=inspect_zip(source)
                if args["expected_sha256"] != manifest["archive_sha256"]: raise PolicyError("Archive does not match reviewed SHA-256")
                if manifest.get("office"): raise PolicyError("This is a native Office container; request an outer ZIP containing the Office file, not its internal XML.")
                members={entry['path'] for entry in manifest['entries'] if not entry['directory']}
                if not set(args.get('expected_files', [])).issubset(members): raise PolicyError("Expected files are absent from the inspected ZIP")
        if name=="created.wait":
            for filename in args.get("expected_names",[]):
                if Path(filename).name!=filename or "/" in filename or "\\" in filename: raise ValueError("Expected output names must be plain filenames")
            pattern=args.get("pattern","*")
            if len(pattern)>256 or "/" in pattern or "\\" in pattern: raise ValueError("Created pattern must match filenames only")
        return {"valid":True}

    def _limit(self, value, context):
        value=redact(json.loads(json.dumps(value,ensure_ascii=False,default=str)))
        def scrub_urls(item):
            if isinstance(item,list): return [scrub_urls(child) for child in item]
            if isinstance(item,dict):
                output={}
                for key,child in item.items():
                    if key=="url" and isinstance(child,str):
                        parsed=urlsplit(child)
                        child=urlunsplit((parsed.scheme,parsed.hostname or "",parsed.path,"",""))
                    output[key]=scrub_urls(child)
                return output
            return item
        value=scrub_urls(value)
        if value.get("tool") in SPECS:
            from .protocol import validate_schema
            errors=validate_schema(value,self.definition(value["tool"])["output_schema"])
            if errors: raise ValueError("Tool result violates output schema: " + "; ".join(errors[:3]))
        limit=min(12000,max(1000,config_value(context.get("config",{}),"max_output_chars",12000)))
        encoded=json.dumps(value,ensure_ascii=False,default=str)
        if len(encoded)<=limit: return value
        folder=Path(context["session_dir"])/"tool_results"
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/(uuid.uuid4().hex+".json")
        with path.open("x",encoding="utf-8") as stream: stream.write(encoded)
        preview=encoded[:limit//2]
        bounded={"ok":value.get("ok",False),"tool":value.get("tool",""),"result":{"status":value.get("result",{}).get("status","output_truncated"),"truncated":True,"preview":preview,"retained_result":str(path),"sha256":hashlib.sha256(encoded.encode()).hexdigest()}}
        if value.get('tool') == 'archives.extract':
            report=value.get('result',{})
            bounded['result']['verification_summary']={key:report[key] for key in ('archive','archive_sha256','destination','report_path') if key in report}
            bounded['result']['verification_summary']['verified_file_count']=len(report.get('verified_files',[]))
            bounded['result']['verification_summary']['expected_file_count']=len(report.get('expected_files',[]))
            if len(json.dumps(bounded['result']['verification_summary'])) > min(limit//3,3000):
                bounded['result']['verification_summary']={key:value for key,value in bounded['result']['verification_summary'].items() if key in {'archive_sha256','verified_file_count','expected_file_count'}}
        while len(json.dumps(bounded,ensure_ascii=False))>limit and bounded["result"]["preview"]:
            bounded["result"]["preview"]=bounded["result"]["preview"][:len(bounded["result"]["preview"])//2]
        return bounded

    async def execute(self, name, args, context):
        try:
            definition=self.definition(name)
            self.validate_call(name,args,context)
            if definition["approval_policy"]!="read_only" and context.get("approved") is not True:
                raise PolicyError("Explicit local approval is required")
            config=context.get("config",{})
            roots=config_value(config,"allowed_roots",[context["session_dir"]])
            policy=context.get("policy") or configured_path_policy(config,context["session_dir"])
            timeout=min(30,config_value(config,"tool_timeout",30))
            if name=="created.wait": timeout=min(300,config_value(config,"sync_timeout",120))+1
            if name=="copilot.download": timeout=min(295,config_value(config,"download_timeout",90))+1
            result=await asyncio.wait_for(self._execute(name,args,context,policy),timeout=timeout)
            if name=="code_runner" and result.get("status")!="completed":
                code = "cancelled" if result.get("status") == "cancelled" else "operation_failed"
                return self._limit({"ok":False,"tool":name,"result":result,"error":{"code":code,"message":result.get("error","Expected output was not produced")}},context)
            if name=="ocr.image" and result.get("status")=="unavailable":
                return self._limit({"ok":False,"tool":name,"result":result,"error":{"code":"unavailable","message":result["reason"]}},context)
            if name in {"archives.extract", "copilot.download"} and result.get("status") not in {"verified", "verified_with_limitations", "downloaded"}:
                return self._limit({"ok":False,"tool":name,"result":result,"error":{"code":"operation_failed","message":"Delivery verification failed; inspect retained outputs before retry."}},context)
            return self._limit({"ok":True,"tool":name,"result":result},context)
        except DownloadError as error:
            return redact({"ok":False,"tool":name,"result":{"status":"uncertain" if error.side_effects_uncertain else "not_started","side_effects_uncertain":error.side_effects_uncertain},"error":{"code":error.code,"message":str(error)}})
        except PolicyError as error: return redact({"ok":False,"tool":name,"error":{"code":"policy_denied","message":str(error)}})
        except (ValueError,TypeError) as error: return redact({"ok":False,"tool":name,"error":{"code":"invalid_arguments","message":str(error)}})
        except asyncio.TimeoutError: return {"ok":False,"tool":name,"error":{"code":"timeout","message":"Local operation timed out; inspect partial effects before retrying"}}
        except Exception as error: return redact({"ok":False,"tool":name,"error":{"code":"operation_failed","message":str(error)[:1000]}})

    async def _execute(self,name,args,context,policy):
        config=context.get("config",{})
        if name=="copilot.download":
            return await context["download_service"].download(args,context["download_binding"])
        if name=="archives.inspect": return ArchiveService(policy,context["session_dir"]).inspect(args)
        if name=="archives.extract": return ArchiveService(policy,context["session_dir"]).extract(args,approved=context.get("approved",False))
        if name.startswith("files."):
            if name=="files.copy":
                source=policy.resolve(args["source"],True); target=policy.resolve(args["destination"])
                if not source.is_file() or source.stat().st_size>20971520: raise PolicyError("Copy source must be a file of at most 20 MB")
                with source.open("rb") as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming,outgoing,65536)
                return {"path":str(target),"size":target.stat().st_size}
            path=policy.resolve(args["path"])
            if name=="files.exists": return {"exists":path.exists(),"path":str(path)}
            if name=="files.mkdir": path.mkdir(exist_ok=False); return {"path":str(path)}
            if name=="files.create":
                with path.open("x",encoding="utf-8") as stream: stream.write(args["text"])
                return {"path":str(path),"size":path.stat().st_size}
            if name=="files.append":
                if not path.is_file(): raise PolicyError("Append requires an existing regular file")
                if path.stat().st_size>20971520 or path.stat().st_nlink>1: raise PolicyError("Append requires a bounded file without hardlink aliases")
                path.read_text(encoding="utf-8")
                with path.open("a",encoding="utf-8") as stream: stream.write(args["text"])
                return {"path":str(path),"size":path.stat().st_size}
            if name=="files.list":
                entries=[]
                for item in path.iterdir():
                    try: checked=policy.resolve(item)
                    except (PolicyError,OSError): continue
                    entries.append({"name":item.name,"directory":checked.is_dir()})
                    if len(entries)>=200: break
                return {"entries":entries,"limit":200}
            info=path.stat()
            if name=="files.metadata": return {"path":str(path),"size":info.st_size,"mtime_ns":info.st_mtime_ns,"directory":path.is_dir()}
            if name=="files.read":
                if info.st_size>40000: raise PolicyError("Text read exceeds 40000-byte limit")
                limit=min(10000,args.get("max_chars",10000))
                text=path.read_text(encoding="utf-8")
                return {"text":text[:limit],"truncated":len(text)>limit}
            if name=="files.hash":
                if not path.is_file(): raise PolicyError("Hash requires a regular file")
                if info.st_size>20971520: raise PolicyError("Hash size limit exceeded")
                digest=hashlib.sha256()
                with path.open("rb") as stream:
                    while block:=stream.read(65536): digest.update(block)
                return {"sha256":digest.hexdigest(),"size":info.st_size}
        if name=="system.versions":
            packages={}
            for package in ("playwright",):
                try: packages[package]=version(package)
                except PackageNotFoundError: packages[package]="not_installed"
            adapter=context.get("browser")
            browser=getattr(adapter,"browser",None)
            return {"python":platform.python_version(),"python_executable":str(Path(sys.executable).resolve()),
                    "system":platform.system(),"release":platform.release(),"packages":packages,
                    "browser":getattr(browser,"version","unavailable")}
        if name=="system.disk":
            usage=shutil.disk_usage(policy.resolve(args["path"],True)); return dict(zip(("total","used","free"),usage))
        if name=="system.processes":
            import os
            processes=[{"pid":os.getpid(),"name":"Copilot Local Agent","python":platform.python_version()}]
            owned=getattr(context.get("browser"),"_launched_process",None)
            if owned is not None and isinstance(getattr(owned,"pid",None),int):
                processes.append({"pid":owned.pid,"name":"Owned Microsoft Edge launcher","running":owned.poll() is None})
            return {"processes":processes,"scope":"current agent and explicitly launched owned Edge only"}
        if name=="code_runner":
            runner=CodeRunner(policy,context["session_dir"],{"tool_timeout":config_value(config,"tool_timeout",10),"max_output_chars":config_value(config,"max_output_chars",12000)})
            return await runner.run_async(args,context.get("approved_hash"),process_registry=context.get("process_registry"))
        if name=="ocr.image":
            path=policy.resolve(args["path"],True)
            if path.suffix.lower() not in {".png",".jpg",".jpeg",".webp",".bmp"}: raise ValueError("Expected supported image")
            if not path.is_file() or path.stat().st_size>min(20971520,config_value(config,"max_attachment_bytes",20971520)): raise PolicyError("Image exceeds the approved attachment limit")
            with path.open("rb") as stream: header=stream.read(16)
            if not (header.startswith((b"\x89PNG\r\n\x1a\n",b"\xff\xd8\xff",b"BM")) or header.startswith(b"RIFF") and header[8:12]==b"WEBP"): raise ValueError("File header is not a supported image")
            if context.get("browser") is not None and callable(getattr(context["browser"],"attach_files",None)):
                pending=context.setdefault("pending_image_attachments",[])
                if str(path) not in pending: pending.append(str(path))
                return {"status":"pending_attachment_for_analysis","path":str(path),"followup":"Attach this approved image on the next Copilot submission, then analyze visible text. Upload and OCR are not yet observed."}
            return {"status":"unavailable","path":str(path),"reason":"No local OCR engine is configured. Attach this approved image to Copilot for supported image analysis."}
        if name.startswith("created."):
            if not config_value(config,"created_sync_enabled",False):
                return {"status":"disabled","files":[],"reason":"OneDrive Created monitoring is disabled until explicitly configured for the live run."}
            directory=config_value(config,"created_dir")
            if not directory: return {"status":"missing_directory","files":[]}
            watcher=CreatedSync(directory,poll_interval=config_value(config,"sync_poll_interval",.5))
            if name=="created.snapshot":
                baseline=watcher.baseline(); token=uuid.uuid4().hex
                snapshots=context.setdefault("created_snapshots",{})
                if len(snapshots)>=50: raise PolicyError("Created snapshot limit reached")
                snapshots[token]=baseline
                return {"status":"captured" if watcher.directory.is_dir() else "missing_directory","baseline_id":token,"file_count":len(baseline)}
            token=args.get("baseline_id")
            baseline=context.get("created_snapshots",{}).get(token) if token else context.get("created_baseline")
            if baseline is None: raise PolicyError("A baseline recorded before file creation is required")
            return await watcher.poll(baseline,pattern=args.get("pattern","*"),expected_names=args.get("expected_names"),timeout=config_value(config,"sync_timeout",120))
        if name.startswith("browser."):
            browser=context.get("browser")
            page=getattr(browser,"tool_page",None)
            if page is None or page.is_closed(): raise PolicyError("Owned tool page is unavailable")
            if page is getattr(browser,"page",None) or page is getattr(browser,"chat_page",None): raise PolicyError("Copilot control page cannot be a tool page")
            urls=URLPolicy([*config_value(config,"allowed_domains",[]), *context.get("approved_domains",[])])
            # Request-time enforcement also blocks redirects, subresources and
            # fetches to unapproved destinations before network access occurs.
            async def guard(route):
                try: urls.resolve(route.request.url)
                except (PolicyError,ValueError): await route.abort("blockedbyclient")
                else: await route.continue_()
            previous=getattr(browser,"_tool_policy_route",None)
            if previous is not None: await page.unroute("**/*",previous)
            await page.route("**/*",guard)
            browser._tool_policy_route=guard
            if name=="browser.open":
                url=urls.resolve(args["url"]); await page.goto(url,wait_until="domcontentloaded",timeout=20000)
                urls.resolve(page.url)
                return {"url":page.url,"title":await page.title()}
            if page.url!="about:blank": urls.resolve(page.url)
            if name in {"browser.back","browser.forward"}:
                session=await page.context.new_cdp_session(page)
                try: history=await session.send("Page.getNavigationHistory")
                finally: await session.detach()
                index=history["currentIndex"]+(-1 if name.endswith("back") else 1)
                if not 0<=index<len(history["entries"]): return {"status":"no_history"}
                urls.resolve(history["entries"][index]["url"])
                await (page.go_back if name.endswith("back") else page.go_forward)(wait_until="domcontentloaded",timeout=20000)
                urls.resolve(page.url)
                return {"url":page.url}
            if name=="browser.info": return {"url":page.url,"title":await page.title()}
            if name=="browser.read": return {"text":(await page.locator("body").inner_text(timeout=5000))[:10000]}
            if name=="browser.structure":
                return {"controls":await page.evaluate(STRUCTURE_SCRIPT)}
            if name in {"browser.click","browser.fill"}:
                locator=page.locator(args["selector"])
                if await locator.count()!=1: raise PolicyError("Selector must identify exactly one element")
                if name=="browser.fill":
                    if (await locator.get_attribute("type") or "").lower()=="password": raise PolicyError("Password input is forbidden")
                    await locator.fill(args["text"],timeout=5000)
                else: await locator.click(timeout=5000)
                if page.url!="about:blank": urls.resolve(page.url)
                return {"status":"performed","url":page.url}
            if name=="browser.scroll": await page.evaluate("pixels=>window.scrollBy(0,pixels)",args["pixels"]); return {"status":"performed"}
            if name=="browser.screenshot":
                folder=Path(context["session_dir"])/"screenshots"; folder.mkdir(parents=True,exist_ok=True)
                target=folder/(uuid.uuid4().hex+".png")
                await page.screenshot(path=str(target),full_page=False,timeout=10000,
                    mask=[page.locator("input,textarea,[contenteditable='true'],button[aria-label*='account' i],button[aria-label*='profile' i]")])
                return {"path":str(target)}
            if name in {"browser.errors","browser.downloads"}:
                key="tool_errors" if name.endswith("errors") else "tool_downloads"
                values=getattr(browser,key,None)
                return {"status":"observed" if values is not None else "unavailable","events":list(values or [])[-20:]}
        raise ValueError("Unknown capability")


def definitions(): return ToolRegistry().definitions()


async def execute(name,args,context): return await ToolRegistry().execute(name,args,context)
