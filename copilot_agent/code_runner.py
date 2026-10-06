"""A constrained Python interpreter, never host exec or an OS sandbox claim."""
import ast
import codecs
import hashlib
import io
import json
import math
import operator
import os
import re
import stat
import sys
import time
import tokenize
from pathlib import Path
from urllib.parse import urlsplit

from .policy import PathPolicy, PolicyError

BASE_FIELDS = {"script", "purpose", "language", "working_directory", "read_paths", "create_paths", "expected_outputs", "commands", "subprocesses", "network_destinations", "permissions", "risk_summary", "recovery_notes", "source_path", "source_sha256"}
LOCAL_FIELDS = {"interpreter", "arguments", "imports", "modify_paths", "timeout_seconds", "max_output_chars", "expected_effects", "viewer_windows"}
FIELDS = BASE_FIELDS | LOCAL_FIELDS
REQUIRED = BASE_FIELDS - {"subprocesses", "source_path", "source_sha256"}
OPTIONAL = FIELDS - REQUIRED
LOCAL_REQUIRED = {"interpreter", "arguments", "imports", "modify_paths", "timeout_seconds", "max_output_chars", "expected_effects", "viewer_windows"}
MAX_SOURCE_BYTES = 200000
CALLS = {"print", "range", "len", "str", "int", "sum", "min", "max", "sorted", "read_file", "write_file"}
NODES = (ast.Module, ast.Expr, ast.Assign, ast.If, ast.For, ast.Pass, ast.Constant, ast.Name, ast.Load, ast.Store,
         ast.List, ast.Tuple, ast.Dict, ast.Subscript, ast.Slice, ast.Call, ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp,
         ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or,
         ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)


class CodeRunner:
    def __init__(self, policy, session_dir, limits=None):
        self.policy = policy if isinstance(policy, PathPolicy) else PathPolicy(policy)
        self.session_dir = Path(session_dir).resolve()
        limits = limits or {}
        self.max_steps = min(100000, int(limits.get("max_steps", 10000)))
        self.max_output = min(12000, int(limits.get("max_output_chars", 12000)))
        self.max_seconds = min(30, float(limits.get("tool_timeout", 10)))

    def _plan(self, args):
        if not isinstance(args, dict) or set(args) - FIELDS or REQUIRED - set(args):
            raise ValueError("Code plan has missing or unsupported fields")
        if args["language"] not in {"python_subset", "local_python"}:
            raise ValueError("language must be python_subset or local_python")
        if not isinstance(args["script"], str) or len(args["script"]) > 50000:
            raise ValueError("Script must be text of at most 50000 characters")
        if ("source_path" in args) != ("source_sha256" in args):
            raise PolicyError("source_path and source_sha256 must be supplied together")
        if "source_path" in args:
            if not isinstance(args["source_path"], str) or not args["source_path"].strip() or len(args["source_path"]) > 4000:
                raise PolicyError("Invalid source_path")
            if not isinstance(args["source_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", args["source_sha256"]):
                raise PolicyError("source_sha256 must be a lowercase SHA-256")
        for key in ("purpose", "risk_summary", "recovery_notes", "working_directory"):
            if not isinstance(args[key], str) or not args[key].strip() or len(args[key]) > 4000:
                raise ValueError(f"Invalid {key}")
        for key in ("read_paths", "create_paths", "expected_outputs", "commands", "network_destinations", "permissions"):
            values = args.get(key, [])
            if not isinstance(values, list) or len(values) > 100 or any(not isinstance(v, str) for v in values):
                raise ValueError(f"Invalid {key}")
        plan = dict(args)
        plan["subprocesses"] = args.get("subprocesses", [])
        plan["working_directory"] = str(self.policy.resolve(args["working_directory"], True))
        if not Path(plan["working_directory"]).is_dir():
            raise PolicyError("Working directory must be an existing directory")
        path_keys = ["read_paths", "create_paths", "expected_outputs"]
        if args["language"] == "local_python":
            missing = LOCAL_REQUIRED - set(args)
            if missing:
                raise ValueError("local_python requires fields: " + ", ".join(sorted(missing)))
            path_keys.append("modify_paths")
        elif set(args) & LOCAL_FIELDS:
            raise PolicyError("local_python-only fields cannot be added to a python_subset plan")
        for key in path_keys:
            plan[key] = [str(self.policy.resolve(Path(plan["working_directory"]) / p)) for p in args[key]]
            if len(plan[key]) != len(set(plan[key])):
                raise PolicyError(f"Duplicate {key}")
        permitted_outputs = set(plan["create_paths"]) | set(plan.get("modify_paths", []))
        if not set(plan["expected_outputs"]).issubset(permitted_outputs):
            raise PolicyError("Expected outputs must be declared creates or modifications")
        if plan["read_paths"] and "read_files" not in plan["permissions"]:
            raise PolicyError("Read permission missing")
        if plan["create_paths"] and "create_files" not in plan["permissions"]:
            raise PolicyError("Create permission missing")
        if set(plan["read_paths"]) & permitted_outputs or set(plan["create_paths"]) & set(plan.get("modify_paths", [])):
            raise PolicyError("Read, create and modify paths may not overlap")
        if "source_path" in args:
            raw_source = Path(plan["working_directory"]) / args["source_path"]
            plan["source_path"] = str(self.policy.resolve(raw_source, True))
            if plan["source_path"] not in plan["read_paths"] or "read_files" not in plan["permissions"]:
                raise PolicyError("Source file must be declared in read_paths with read_files permission")
            self._verify_source(plan, raw_source)
        if args["language"] == "python_subset":
            if args["commands"] or args.get("subprocesses") or args["network_destinations"]:
                raise PolicyError("The restricted interpreter has no subprocess or network capability")
            if set(args["permissions"]) - {"read_files", "create_files"}:
                raise PolicyError("Unsupported python_subset permission")
            return plan
        return self._local_plan(plan)

    def _local_plan(self, plan):
        if plan["commands"]:
            raise PolicyError("Shell command strings are unavailable; declare exact managed subprocess argument vectors")
        interpreter = Path(plan["interpreter"]).expanduser()
        if not interpreter.is_absolute() or interpreter.resolve() != Path(sys.executable).resolve() or not interpreter.is_file():
            raise PolicyError("local_python must use the agent's exact current Python interpreter")
        plan["interpreter"] = str(interpreter.resolve())
        for key, maximum in (("arguments", 100), ("imports", 100), ("expected_effects", 100)):
            values = plan[key]
            if not isinstance(values, list) or len(values) > maximum or any(not isinstance(value, str) or not value or len(value) > 1000 or "\0" in value for value in values):
                raise ValueError("Invalid " + key)
            if len(values) != len(set(values)):
                raise PolicyError("Duplicate " + key)
        if not plan["expected_effects"]:
            raise PolicyError("local_python requires at least one explicit expected effect")
        if any(not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", value) for value in plan["imports"]):
            raise ValueError("Declared imports must be exact Python module names")
        for key in ("timeout_seconds", "max_output_chars"):
            if type(plan[key]) is not int:
                raise ValueError(key + " must be an integer")
        if not 1 <= plan["timeout_seconds"] <= int(self.max_seconds):
            raise PolicyError("timeout_seconds exceeds the configured Code Runner limit")
        if not 1 <= plan["max_output_chars"] <= self.max_output:
            raise PolicyError("max_output_chars exceeds the configured Code Runner limit")
        for path in plan["read_paths"] + plan["modify_paths"]:
            if not Path(path).exists():
                raise PolicyError("Approved read/modify path must already exist: " + path)
        for path in plan["create_paths"]:
            target = Path(path)
            if target.exists() or not target.parent.is_dir():
                raise PolicyError("Approved create path must be new with an existing parent: " + path)
        supported_permissions = {"read_files", "create_files", "modify_files", "network", "subprocesses",
                                 "desktop_capture", "window_management", "persistent_processes"}
        if set(plan["permissions"]) - supported_permissions:
            raise PolicyError("Unsupported local_python permission")
        if plan["modify_paths"] and "modify_files" not in plan["permissions"]:
            raise PolicyError("Modify permission missing")
        destinations = []
        for value in plan["network_destinations"]:
            parsed = urlsplit(value)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or
                    parsed.port not in (None, 443) or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
                raise PolicyError("Network destinations must be exact HTTPS hosts on port 443")
            destinations.append("https://" + parsed.hostname.casefold())
        if len(destinations) != len(set(destinations)):
            raise PolicyError("Duplicate network destination")
        plan["network_destinations"] = destinations
        if destinations and "network" not in plan["permissions"]:
            raise PolicyError("Network permission missing")
        processes = plan["subprocesses"]
        if not isinstance(processes, list) or len(processes) > 20:
            raise ValueError("Invalid subprocesses")
        normalized = []
        for item in processes:
            if not isinstance(item, dict) or set(item) != {"executable", "arguments", "persistent", "purpose"}:
                raise ValueError("Each subprocess requires executable, arguments, persistent and purpose")
            executable = Path(item["executable"]).expanduser()
            arguments = item["arguments"]
            if (not executable.is_absolute() or not executable.is_file() or not isinstance(arguments, list)
                    or len(arguments) > 100 or any(not isinstance(value, str) or len(value) > 4000 or "\0" in value for value in arguments)
                    or type(item["persistent"]) is not bool or not isinstance(item["purpose"], str)
                    or not item["purpose"].strip() or len(item["purpose"]) > 1000):
                raise PolicyError("Invalid managed subprocess specification")
            normalized.append({"executable": str(executable.resolve()), "arguments": arguments,
                               "persistent": item["persistent"], "purpose": item["purpose"]})
        plan["subprocesses"] = normalized
        if normalized and "subprocesses" not in plan["permissions"]:
            raise PolicyError("Managed subprocess permission missing")
        if any(item["persistent"] for item in normalized) and "persistent_processes" not in plan["permissions"]:
            raise PolicyError("Persistent process permission missing")
        viewers = plan["viewer_windows"]
        if not isinstance(viewers, list) or len(viewers) > 12:
            raise ValueError("Invalid viewer_windows")
        normalized_viewers = []
        for item in viewers:
            if not isinstance(item, dict) or set(item) != {"title", "image_path", "display_index"}:
                raise ValueError("Each viewer requires title, image_path and display_index")
            if (not isinstance(item["title"], str) or not item["title"].strip() or len(item["title"]) > 200
                    or any(ord(char) < 32 for char in item["title"]) or type(item["display_index"]) is not int
                    or not 1 <= item["display_index"] <= 32):
                raise ValueError("Invalid viewer window declaration")
            image = str(self.policy.resolve(Path(plan["working_directory"]) / item["image_path"]))
            if image not in plan["expected_outputs"] or Path(image).suffix.casefold() != ".png":
                raise PolicyError("Viewer images must be declared expected PNG outputs")
            normalized_viewers.append({"title": item["title"], "image_path": image,
                                       "display_index": item["display_index"]})
        if len({item["title"] for item in normalized_viewers}) != len(normalized_viewers):
            raise PolicyError("Viewer titles must be unique for independent verification")
        if normalized_viewers and not {"window_management", "persistent_processes"}.issubset(plan["permissions"]):
            raise PolicyError("Persistent viewer windows require window_management and persistent_processes permissions")
        plan["viewer_windows"] = normalized_viewers
        return plan

    def _verify_source(self, plan, raw_source=None):
        """Read only approved UTF-8 source bytes; never execute the source file."""
        if "source_path" not in plan:
            return None
        raw_source = Path(raw_source if raw_source is not None else plan["source_path"])
        # PathPolicy inspects the un-resolved path and every parent before opening,
        # including redirecting links, protected roots and hardlink aliases.
        source = self.policy.resolve(raw_source, True)
        if str(source) != plan["source_path"] or source.suffix.casefold() != ".py":
            raise PolicyError("Bound source must be the exact allowed .py file")
        before = source.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SOURCE_BYTES:
            raise PolicyError("Bound source must be a regular file of at most 200000 bytes")
        with source.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink > 1:
                raise PolicyError("Bound source is not a regular unaliased file")
            data = stream.read(MAX_SOURCE_BYTES + 1)
            finished = os.fstat(stream.fileno())
        checked = self.policy.resolve(raw_source, True)
        after = checked.stat()
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if (checked != source or len(data) > MAX_SOURCE_BYTES or len(data) != before.st_size
                or any(identity(info) != identity(before) for info in (opened, finished, after))):
            raise PolicyError("Bound source changed while being verified")
        digest = hashlib.sha256(data).hexdigest()
        if digest != plan["source_sha256"]:
            raise PolicyError("Bound source SHA-256 differs from the reviewed artifact")
        if data != plan["script"].encode("utf-8"):
            raise PolicyError("Script bytes must exactly match the bound source file")
        if data.startswith(codecs.BOM_UTF8):
            raise PolicyError("UTF-8 BOM source is unsupported; source bytes cannot be changed silently")
        try:
            data.decode("utf-8", errors="strict")
            encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
            if codecs.lookup(encoding).name != "utf-8":
                raise PolicyError("Bound source encoding metadata must declare UTF-8")
        except (UnicodeError, SyntaxError, LookupError) as error:
            raise PolicyError("Bound source must be valid UTF-8 Python text") from error
        return {"path": str(source), "sha256": digest, "size": len(data), "exact_script_bytes": True}

    def validate(self, args):
        plan = self._plan(args)
        tree = ast.parse(plan["script"], mode="exec")
        if plan["language"] == "local_python":
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.level or not node.module or any(alias.name == "*" for alias in node.names):
                        raise PolicyError("Relative and wildcard imports are unavailable")
                    imported.add(node.module)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "compile", "__import__"}:
                    raise PolicyError("Dynamic code and dynamic imports are unavailable")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"getattr", "setattr", "delattr", "globals", "locals", "vars"}:
                    raise PolicyError("Dynamic reflection is unavailable")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"eval", "exec", "compile", "__import__", "import_module", "run_path", "run_module"}:
                    raise PolicyError("Dynamic code and dynamic imports are unavailable")
                elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                    raise PolicyError("Dunder reflection is unavailable")
                elif isinstance(node, ast.Name) and node.id.startswith("__"):
                    raise PolicyError("Dunder reflection is unavailable")
            if not imported.issubset(set(plan["imports"])):
                raise PolicyError("Script contains an undeclared import: " + ", ".join(sorted(imported - set(plan["imports"]))))
            if imported.intersection({"keyring", "winreg", "builtins", "importlib", "runpy", "marshal"}):
                raise PolicyError("Credential, registry and dynamic-loader imports are unavailable")
            if "subprocess" in imported and "subprocesses" not in plan["permissions"]:
                raise PolicyError("subprocess import requires managed subprocess permission")
            native = {name for name in imported if name.split(".", 1)[0] in {"ctypes", "win32api", "win32con", "win32gui", "win32ui", "win32process", "mss", "PIL"}}
            if native and not set(plan["permissions"]).intersection({"desktop_capture", "window_management"}):
                raise PolicyError("Native desktop imports require a declared desktop permission")
            if "copilot_agent.desktop" in imported and "desktop_capture" not in plan["permissions"]:
                raise PolicyError("Desktop capture helper requires desktop_capture permission")
            return plan
        for node in ast.walk(tree):
            if not isinstance(node, NODES):
                raise PolicyError(f"Unsupported Python syntax: {type(node).__name__}")
            if isinstance(node, ast.Name) and (node.id.startswith("_") or node.id in {"True", "False", "None"}):
                raise PolicyError("Reserved variable name")
            if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in CALLS or node.keywords):
                raise PolicyError("Only declared capability calls without keywords are supported")
            if isinstance(node, ast.Assign) and (len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name)):
                raise PolicyError("Assignments require one plain variable")
            if isinstance(node, ast.For) and (not isinstance(node.target, ast.Name) or node.orelse):
                raise PolicyError("For loops require a plain variable and no else clause")
        return plan

    def prepare(self, args):
        plan = self.validate(args)
        binding = None
        if plan["language"] == "local_python":
            from .local_python_runner import runtime_binding
            binding = runtime_binding(plan)
        canonical = json.dumps({"plan": plan, "runtime_binding": binding}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        scripts = self.session_dir / "code_proposals"
        scripts.mkdir(parents=True, exist_ok=True)
        script_path = scripts / (digest + ".py")
        if script_path.exists():
            if script_path.read_bytes().decode("utf-8") != plan["script"]:
                raise PolicyError("Stored proposal integrity mismatch")
        else:
            with script_path.open("x", encoding="utf-8", newline="") as stream:
                stream.write(plan["script"])
        prepared = {"proposal_hash": digest,"script_sha256":hashlib.sha256(plan["script"].encode("utf-8")).hexdigest(), "plan": plan, "script_path": str(script_path),
                    "static_verdict": "accepted_python_subset" if plan["language"] == "python_subset" else "accepted_local_python_for_explicit_approval",
                    "limitations": ("No imports, attributes, host exec, shell or network; create-only files" if plan["language"] == "python_subset" else
                                    "Approved host Python with defense-in-depth policy hooks; not an OS security sandbox. No deletion, shell, credentials or silent privilege escalation.")}
        if binding is not None:
            prepared["runtime_binding"] = binding
        if "source_path" in plan:
            prepared["source_verification"] = {"path": plan["source_path"], "sha256": plan["source_sha256"],
                                               "size": len(plan["script"].encode("utf-8")), "exact_script_bytes": True}
        return prepared

    def run(self, args, approved_hash, **kwargs):
        prepared = self.prepare(args)
        if not approved_hash or approved_hash != prepared["proposal_hash"]:
            raise PolicyError("Approval does not match the complete immutable proposal")
        if prepared["plan"]["language"] == "local_python":
            import asyncio
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(self.run_async(args, approved_hash, **kwargs))
            raise RuntimeError("Use run_async for local_python inside an active event loop")
        self.plan = prepared["plan"]
        self.source_verification = self._verify_source(self.plan)
        self.env = {}
        self.output = []
        self.created = []
        self.steps = 0
        self.started = time.monotonic()
        try:
            for node in ast.parse(self.plan["script"]).body:
                self._statement(node)
            missing = [p for p in self.plan["expected_outputs"] if p not in self.created]
            return self._result("failed" if missing else "completed", approved_hash, missing_outputs=missing)
        except Exception as error:
            return self._result("failed", approved_hash, error=str(error))

    async def run_async(self, args, approved_hash, **kwargs):
        prepared = self.prepare(args)
        if not approved_hash or approved_hash != prepared["proposal_hash"]:
            raise PolicyError("Approval does not match the complete immutable proposal")
        if prepared["plan"]["language"] == "python_subset":
            return self.run(args, approved_hash)
        self._verify_source(prepared["plan"])
        from .local_python_runner import execute_local_python
        return await execute_local_python(prepared["plan"], prepared, self.session_dir,
                                          kwargs.get("process_registry"))

    def _result(self, status, digest, **details):
        outputs=[]
        for path in self.created:
            try:
                data=Path(path).read_bytes()
                outputs.append({"path":path,"size":len(data),"sha256":hashlib.sha256(data).hexdigest(),"readable":True,"expected":path in self.plan["expected_outputs"]})
            except OSError as error:
                outputs.append({"path":path,"readable":False,"error":str(error)})
        stdout="".join(self.output)
        source_details = {"source_verification": self.source_verification} if self.source_verification is not None else {}
        return {"status":status,"proposal_hash":digest,"script_sha256":hashlib.sha256(self.plan["script"].encode("utf-8")).hexdigest(),"output":stdout,"stdout":stdout,"stderr":details.get("error", ""),"exit_code":0 if status=="completed" else 1,"duration_seconds":round(time.monotonic()-self.started,4),"created_paths":self.created,"outputs":outputs,"steps":self.steps,**source_details,**details}

    def _tick(self):
        self.steps += 1
        if self.steps > self.max_steps or time.monotonic() - self.started > self.max_seconds:
            raise PolicyError("Execution step/time limit exceeded")

    def _bound(self, value):
        pending = [(value, 0)]
        budget = 20000
        while pending:
            item, depth = pending.pop()
            budget -= 1
            if isinstance(item,str): budget -= len(item)
            elif isinstance(item,int): budget -= item.bit_length() // 8
            if budget < 0 or depth > 50: raise PolicyError("Aggregate value limit exceeded")
            if isinstance(item, int) and item.bit_length() > 10000: raise PolicyError("Integer size limit exceeded")
            if isinstance(item, float) and not math.isfinite(item): raise PolicyError("Nonfinite numbers are unsupported")
            if isinstance(item, (str, list, tuple, dict, range)) and len(item) > 10000: raise PolicyError("Value size limit exceeded")
            if isinstance(item, (list, tuple)):
                pending.extend((child,depth+1) for child in item)
            elif isinstance(item, dict):
                pending.extend((child,depth+1) for pair in item.items() for child in pair)
        return value

    def _statement(self, node):
        self._tick()
        if isinstance(node, ast.Expr): self._eval(node.value)
        elif isinstance(node, ast.Assign): self.env[node.targets[0].id] = self._eval(node.value)
        elif isinstance(node, ast.If):
            for child in node.body if self._eval(node.test) else node.orelse: self._statement(child)
        elif isinstance(node, ast.For):
            values = self._eval(node.iter)
            for value in values:
                self._tick()
                self.env[node.target.id] = value
                for child in node.body: self._statement(child)

    def _eval(self, node):
        self._tick()
        if isinstance(node, ast.Constant): return self._bound(node.value)
        if isinstance(node, ast.Name): return self.env[node.id]
        if isinstance(node, (ast.List, ast.Tuple)):
            values = [self._eval(n) for n in node.elts]
            return self._bound(tuple(values) if isinstance(node, ast.Tuple) else values)
        if isinstance(node, ast.Dict): return self._bound({self._eval(k): self._eval(v) for k,v in zip(node.keys,node.values)})
        if isinstance(node, ast.Slice): return slice(*(self._eval(v) if v is not None else None for v in (node.lower,node.upper,node.step)))
        if isinstance(node, ast.Subscript): return self._bound(self._eval(node.value)[self._eval(node.slice)])
        if isinstance(node, ast.UnaryOp):
            return self._bound({ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}[type(node.op)](self._eval(node.operand)))
        if isinstance(node, ast.BoolOp):
            value = self._eval(node.values[0])
            for item in node.values[1:]:
                if isinstance(node.op, ast.And) and not value or isinstance(node.op, ast.Or) and value: break
                value = self._eval(item)
            return value
        if isinstance(node, ast.BinOp):
            left, right = self._eval(node.left), self._eval(node.right)
            if isinstance(node.op, ast.Mult) and ((isinstance(left, (str,list,tuple)) and isinstance(right,int) and len(left)*right > 10000) or (isinstance(right,(str,list,tuple)) and isinstance(left,int) and len(right)*left > 10000)):
                raise PolicyError("Multiplication exceeds value limit")
            functions = {ast.Add:operator.add, ast.Sub:operator.sub, ast.Mult:operator.mul, ast.Div:operator.truediv, ast.FloorDiv:operator.floordiv, ast.Mod:operator.mod}
            if isinstance(node.op, ast.Mod) and isinstance(left,str): raise PolicyError("String formatting is unsupported")
            return self._bound(functions[type(node.op)](left,right))
        if isinstance(node, ast.Compare):
            left = self._eval(node.left)
            functions = {ast.Eq:operator.eq, ast.NotEq:operator.ne, ast.Lt:operator.lt, ast.LtE:operator.le, ast.Gt:operator.gt, ast.GtE:operator.ge, ast.In:lambda a,b:a in b, ast.NotIn:lambda a,b:a not in b}
            for operation,item in zip(node.ops,node.comparators):
                right = self._eval(item)
                if not functions[type(operation)](left,right): return False
                left=right
            return True
        if isinstance(node, ast.Call): return self._call(node.func.id, [self._eval(n) for n in node.args])
        raise PolicyError("Unsupported expression")

    def _call(self, name, values):
        if name == "print":
            text = " ".join(str(v) for v in values) + "\n"
            if sum(map(len,self.output)) + len(text) > self.max_output: raise PolicyError("Output limit exceeded")
            self.output.append(text)
            return None
        if name in {"read_file", "write_file"}:
            if len(values) != (1 if name == "read_file" else 2) or not isinstance(values[0],str): raise PolicyError("Invalid file capability arguments")
            path = self.policy.resolve(Path(self.plan["working_directory"]) / values[0])
            key = "read_paths" if name == "read_file" else "create_paths"
            if str(path) not in self.plan[key]: raise PolicyError("File path was not declared in approved plan")
            if name == "read_file":
                if path.stat().st_size > 40000: raise PolicyError("Read size limit exceeded")
                return self._bound(path.read_text(encoding="utf-8"))
            text = values[1]
            if not isinstance(text,str) or len(text) > 10000: raise PolicyError("Write must be bounded text")
            with path.open("x",encoding="utf-8") as stream: stream.write(text)
            self.created.append(str(path))
            return str(path)
        functions = {"range":range,"len":len,"str":str,"int":int,"sum":sum,"min":min,"max":max,"sorted":sorted}
        return self._bound(functions[name](*values))
