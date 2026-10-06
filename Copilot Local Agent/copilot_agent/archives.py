"""Bounded, create-only ZIP inspection/extraction with retained verification evidence."""
from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import stat
import unicodedata
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from .policy import PathPolicy, PolicyError, reject_path_redirection


DEFAULT_LIMITS = {"max_entries":2000,"max_total_bytes":100*1024*1024,"max_file_bytes":20*1024*1024,"max_archive_bytes":50*1024*1024,"max_ratio":200,"max_name_chars":240,"max_python_bytes":1024*1024,"max_xml_bytes":2*1024*1024}
OFFICE_PARTS={"docx":"word/document.xml","xlsx":"xl/workbook.xml","pptx":"ppt/presentation.xml"}
OFFICE_NAMESPACES={"docx":"wordprocessingml","xlsx":"spreadsheetml","pptx":"presentationml"}
OFFICE_ROOTS={"docx":"document","xlsx":"workbook","pptx":"presentation"}
OFFICE_CONTENT_TYPES={"docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml","xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml","pptx":"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"}
# Main-part mappings follow Microsoft's Open XML SDK package features:
# https://github.com/dotnet/Open-XML-SDK/tree/main/src/DocumentFormat.OpenXml/Packaging
VARIANT_TYPES={
    "docm":("docx","application/vnd.ms-word.document.macroEnabled.main+xml"),
    "dotx":("docx","application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"),
    "dotm":("docx","application/vnd.ms-word.template.macroEnabledTemplate.main+xml"),
    "xlsm":("xlsx","application/vnd.ms-excel.sheet.macroEnabled.main+xml"),
    "xltx":("xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml"),
    "xltm":("xlsx","application/vnd.ms-excel.template.macroEnabled.main+xml"),
    "xlam":("xlsx","application/vnd.ms-excel.addin.macroEnabled.main+xml"),
    "pptm":("pptx","application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml"),
    "potx":("pptx","application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"),
    "potm":("pptx","application/vnd.ms-powerpoint.template.macroEnabled.main+xml"),
    "ppsx":("pptx","application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml"),
    "ppsm":("pptx","application/vnd.ms-powerpoint.slideshow.macroEnabled.main+xml"),
    "ppam":("pptx","application/vnd.ms-powerpoint.addin.macroEnabled.main+xml"),
}
for _extension,(_family,_content_type) in VARIANT_TYPES.items():
    OFFICE_PARTS[_extension]=OFFICE_PARTS[_family]
    OFFICE_NAMESPACES[_extension]=OFFICE_NAMESPACES[_family]
    OFFICE_ROOTS[_extension]=OFFICE_ROOTS[_family]
    OFFICE_CONTENT_TYPES[_extension]=_content_type
LEGACY_OFFICE={"doc","dot","xls","xlt","xla","ppt","pot","pps"}
TEXT_EXTENSIONS={"txt","md","csv","json","js","ts","tsx","jsx","html","htm","css","toml","ini","yaml","yml","xml","svg","ps1","cmd","bat","sh","cfg"}


def _reject_links(path):
    """Reject file hardlinks and directory redirection, allowing cloud placeholders."""
    current=Path(path).absolute()
    try: reject_path_redirection(current)
    except PolicyError as error: raise ArchiveError(str(error)) from error
    if current.is_file() and current.stat().st_nlink>1:
        raise ArchiveError("Hardlinked archive/output files are forbidden")


class ArchiveError(ValueError):
    pass


def _limits(values):
    result=dict(DEFAULT_LIMITS)
    for key,value in (values or {}).items():
        if key not in result or type(value) not in (int,float) or not 0<value<=DEFAULT_LIMITS[key]:
            raise ArchiveError("Archive limits may only lower known positive caps")
        result[key]=value
    return result


def _relative(name,limits):
    if not isinstance(name,str) or not name or len(name)>limits["max_name_chars"] or any(ord(c)<32 or ord(c)==127 for c in name):
        raise ArchiveError("Invalid or oversized archive member name")
    normalized=name.replace("\\","/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:",normalized):
        raise ArchiveError("Absolute member paths are forbidden")
    parts=normalized.rstrip("/").split("/")
    devices={"CON","PRN","AUX","NUL",*(f"COM{i}" for i in range(1,10)),*(f"LPT{i}" for i in range(1,10))}
    for part in parts:
        if part in {"",".",".."} or ":" in part or part.endswith((" ",".")) or part.split(".")[0].upper() in devices:
            raise ArchiveError("Unsafe member path component")
    if len(parts)>30:
        raise ArchiveError("Archive path depth exceeds limit")
    return "/".join(parts)


def _digest(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block:=stream.read(65536): digest.update(block)
    return digest.hexdigest()


def _entries(archive,limits):
    infos=archive.infolist()
    if len(infos)>limits["max_entries"]:
        raise ArchiveError("Archive entry count exceeds limit")
    entries=[]; names={}; aliases={}; total=0
    for info in infos:
        relative=_relative(info.orig_filename,limits)
        key=unicodedata.normalize("NFC",relative).casefold()
        if key in names:
            raise ArchiveError("Duplicate or case/Unicode-aliased archive member")
        parts=PurePosixPath(relative).parts
        for length in range(1,len(parts)+1):
            prefix="/".join(parts[:length]); alias=unicodedata.normalize("NFC",prefix).casefold()
            if alias in aliases and aliases[alias]!=prefix:
                raise ArchiveError("Case/Unicode-aliased archive path components")
            aliases[alias]=prefix
        if info.flag_bits & 1:
            raise ArchiveError("Encrypted archives are unsupported")
        if info.compress_type not in {zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED}:
            raise ArchiveError("Unsupported ZIP compression method")
        mode=info.external_attr>>16
        kind=stat.S_IFMT(mode)
        if kind not in {0,stat.S_IFREG,stat.S_IFDIR} or info.external_attr & 0x400:
            raise ArchiveError("Symlink, reparse or special archive entries are forbidden")
        if kind==stat.S_IFDIR and not info.is_dir() or kind==stat.S_IFREG and info.is_dir():
            raise ArchiveError("Inconsistent archive member type")
        if info.file_size>limits["max_file_bytes"]:
            raise ArchiveError("Archive member exceeds per-file limit")
        if info.is_dir() and info.file_size:
            raise ArchiveError("Directory entry unexpectedly contains data")
        ratio=info.file_size/max(1,info.compress_size)
        if ratio>limits["max_ratio"]:
            raise ArchiveError("Archive member exceeds compression ratio limit")
        total+=info.file_size
        if total>limits["max_total_bytes"]:
            raise ArchiveError("Archive total expanded size exceeds limit")
        entry={"path":relative,"directory":info.is_dir(),"size":info.file_size,"compressed_size":info.compress_size,"crc32":f"{info.CRC:08x}"}
        entries.append(entry); names[key]=entry
    for entry in entries:
        parents=PurePosixPath(entry["path"]).parents
        for parent in parents:
            other=names.get(unicodedata.normalize("NFC",str(parent)).casefold())
            if other and not other["directory"]:
                raise ArchiveError("An archive file is also used as a parent directory")
    return entries,total


def _office(archive,entries,limits):
    names={entry["path"] for entry in entries if not entry["directory"]}
    parts={part for part in OFFICE_PARTS.values() if part in names}
    if "xl/workbook.bin" in names: parts.add("xl/workbook.bin")
    if not parts:
        return None
    if len(parts)!=1 or "[Content_Types].xml" not in names:
        raise ArchiveError("Office ZIP is missing an unambiguous content-type/main-part structure")
    part=next(iter(parts)); kind=None
    for name in ("[Content_Types].xml",part):
        info=archive.getinfo(name)
        if name=="xl/workbook.bin": continue
        if info.file_size>limits["max_xml_bytes"]:
            raise ArchiveError("Office validation XML exceeds limit")
        data=archive.read(name)
        declaration_probe=data.replace(b"\x00",b"").upper()
        if b"<!DOCTYPE" in declaration_probe or b"<!ENTITY" in declaration_probe:
            raise ArchiveError("XML document/entity declarations are unsupported")
        try: root=ElementTree.fromstring(data)
        except ElementTree.ParseError as error: raise ArchiveError("Office XML is malformed") from error
        if name=="[Content_Types].xml":
            namespace="{http://schemas.openxmlformats.org/package/2006/content-types}"
            declared=[child.attrib.get("ContentType") for child in root if child.tag==namespace+"Override" and child.attrib.get("PartName")=="/"+part]
            if root.tag!=namespace+"Types" or len(declared)!=1:
                raise ArchiveError("Office content types do not declare the main part")
            kinds=[extension for extension,mime in OFFICE_CONTENT_TYPES.items() if mime==declared[0] and OFFICE_PARTS[extension]==part]
            if part=="xl/workbook.bin" and declared[0]=="application/vnd.ms-excel.sheet.binary.macroEnabled.main": kind="xlsb"
            elif len(kinds)==1: kind=kinds[0]
            else: raise ArchiveError("Office main-part content type is unsupported or inconsistent")
        else:
            supported={"{http://schemas.openxmlformats.org/"+OFFICE_NAMESPACES[kind]+"/2006/main}"+OFFICE_ROOTS[kind],"{http://purl.oclc.org/ooxml/"+OFFICE_NAMESPACES[kind]+"/main}"+OFFICE_ROOTS[kind]}
            if root.tag not in supported: raise ArchiveError("Office main part has an unexpected root namespace/type")
    active=kind=="xlsb" or "macroEnabled" in OFFICE_CONTENT_TYPES.get(kind,"") or any(name.casefold().endswith("vbaproject.bin") for name in names)
    return {"office_type":kind,"suggested_extension":"."+kind,"active_content":active,"structural_validation":"structural_unverified" if kind=="xlsb" else "passed","limitations":"Binary workbook semantics are not parsed; container declaration checked" if kind=="xlsb" else "Container and main XML validated; not a full Office rendering, macro safety or semantic validation"}


def inspect_zip(path,limits=None):
    limits=_limits(limits); _reject_links(path); path=Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size>limits["max_archive_bytes"]:
        raise ArchiveError("Archive must be a bounded regular file")
    try:
        with zipfile.ZipFile(path) as archive:
            entries,total=_entries(archive,limits)
            office=_office(archive,entries,limits)
    except zipfile.BadZipFile as error:
        raise ArchiveError("Invalid ZIP archive") from error
    return {"archive":str(path),"archive_sha256":_digest(path),"archive_bytes":path.stat().st_size,"entry_count":len(entries),"total_uncompressed_bytes":total,"entries":entries,"office":office,"limits":limits}


def _target(root,relative):
    raw=root.joinpath(*PurePosixPath(relative).parts)
    current=raw
    while current!=root:
        if current.is_symlink(): raise ArchiveError("Destination path has a symlink component")
        current=current.parent
    target=raw.resolve()
    if root not in target.parents:
        raise ArchiveError("Resolved extraction target escapes destination")
    _reject_links(raw)
    return target


def _verify(path,limits):
    _reject_links(path)
    evidence={"path":str(path),"size":path.stat().st_size,"sha256":_digest(path),"readable":True}
    extension=path.suffix.lower().lstrip(".")
    if extension in OFFICE_PARTS or extension=="xlsb":
        nested=inspect_zip(path,limits)
        if not nested["office"] or nested["office"]["office_type"]!=extension:
            raise ArchiveError("Extracted Office file does not match its extension")
        evidence["office"]=nested["office"]
    elif extension in LEGACY_OFFICE:
        with path.open("rb") as stream: header=stream.read(8)
        if header!=b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise ArchiveError("Legacy Office extension lacks an OLE compound-file signature")
        evidence["office"]={"office_type":extension,"structural_validation":"structural_unverified","signature":"OLE compound file","active_content":"unknown","limitations":"Signature/readability/hash checked; legacy streams, document semantics and macros are not parsed"}
    elif extension=="py":
        if evidence["size"]>limits["max_python_bytes"]:
            raise ArchiveError("Python syntax verification exceeds size cap")
        try:
            tree=ast.parse(path.read_text(encoding="utf-8-sig"),filename=str(path))
            if sum(1 for _ in ast.walk(tree))>100000:
                raise ArchiveError("Python syntax tree exceeds verification cap")
        except (SyntaxError,UnicodeError,RecursionError) as error:
            raise ArchiveError("Extracted Python file failed syntax validation") from error
        evidence["python_syntax"]="passed_without_execution"
    elif extension in TEXT_EXTENSIONS or path.name in {"LICENSE","README",".gitignore"}:
        try:
            text=path.read_text(encoding="utf-8-sig")
            if "\x00" in text: raise UnicodeError("NUL byte in expected text")
            evidence["text_encoding"]="utf-8"
            if extension=="json":
                def pairs(items):
                    result={}
                    for key,value in items:
                        if key in result: raise ValueError("Duplicate JSON key")
                        result[key]=value
                    return result
                decoded=json.loads(text,object_pairs_hook=pairs,parse_constant=lambda value:(_ for _ in ()).throw(ValueError("Nonfinite JSON number")))
                pending=[decoded]
                while pending:
                    value=pending.pop()
                    if isinstance(value,float) and not math.isfinite(value): raise ValueError("Nonfinite JSON number")
                    if isinstance(value,dict): pending.extend(value.values())
                    elif isinstance(value,list): pending.extend(value)
                evidence["json_syntax"]="passed"
        except (UnicodeError,ValueError,RecursionError) as error:
            raise ArchiveError("Extracted text/JSON validation failed: "+str(error)) from error
    return evidence


def verify_delivered_file(path,limits=None):
    """Return bounded static readability/hash/type evidence; never execute content.

    The caller must enforce its own PathPolicy before using this standalone
    utility. Raw links are checked before resolution, including parent links.
    """
    limits=_limits(limits)
    raw=Path(path).expanduser()
    _reject_links(raw)
    resolved=raw.resolve(strict=True)
    details=resolved.stat()
    if not stat.S_ISREG(details.st_mode) or details.st_nlink>1 or details.st_size>limits["max_file_bytes"]:
        raise ArchiveError("Delivered file must be a bounded regular file without hardlinks")
    evidence=_verify(resolved,limits)
    _reject_links(raw)
    if resolved.stat().st_size!=details.st_size or _digest(resolved)!=evidence["sha256"]:
        raise ArchiveError("Delivered file changed during static verification")
    return evidence


verify_file=verify_delivered_file


def extract_zip(path,destination,expected_files=(),limits=None):
    limits=_limits(limits); manifest=inspect_zip(path,limits)
    _reject_links(destination); root=Path(destination).expanduser().resolve()
    if not isinstance(expected_files,(list,tuple)) or len(expected_files)>limits["max_entries"]: raise ArchiveError("Expected files must be a bounded list of relative paths")
    expected=[_relative(name,limits) for name in expected_files]
    if len(expected)!=len(set(name.casefold() for name in expected)):
        raise ArchiveError("Expected files have duplicate aliases")
    file_names={entry["path"] for entry in manifest["entries"] if not entry["directory"]}
    if not set(expected).issubset(file_names):
        raise ArchiveError("An expected file is absent from the archive")
    if root.exists() and not root.is_dir():
        raise ArchiveError("Extraction destination is not a directory")
    # Complete path/collision review occurs before creating the destination.
    targets={entry["path"]:_target(root,entry["path"]) for entry in manifest["entries"]}
    for entry in manifest["entries"]:
        target=targets[entry["path"]]
        if target.exists() and (not entry["directory"] or not target.is_dir()):
            raise ArchiveError("Extraction would overwrite an existing path")
        for parent in target.parents:
            if parent==root: break
            if parent.exists() and not parent.is_dir(): raise ArchiveError("Extraction parent is not a directory")
    report={"status":"extracting","archive":manifest["archive"],"archive_sha256":manifest["archive_sha256"],"destination":str(root),"created_files":[],"created_directories":[],"verified_files":[],"expected_files":expected,"errors":[],"filesystem_assumptions":"Paths/links are rechecked around create-only writes. This does not provide OS isolation against a malicious local process racing filesystem changes."}
    def directory(target):
        _reject_links(target)
        pending=[]; current=target
        while not current.exists(): pending.append(current); current=current.parent
        for item in reversed(pending):
            _reject_links(item.parent)
            item.mkdir(exist_ok=False); report["created_directories"].append(str(item))
            _reject_links(item)
    try:
        directory(root)
        if _digest(path)!=manifest["archive_sha256"]: raise ArchiveError("Archive changed after inspection")
        with zipfile.ZipFile(path) as archive:
            for info,entry in zip(archive.infolist(),manifest["entries"]):
                target=_target(root,entry["path"])
                if entry["directory"]: directory(target); continue
                directory(target.parent)
                target=_target(root,entry["path"])
                with archive.open(info) as source,target.open("xb") as output:
                    report["created_files"].append(str(target))
                    count=0
                    while block:=source.read(65536):
                        count+=len(block)
                        if count>entry["size"] or count>limits["max_file_bytes"]: raise ArchiveError("Member exceeded inspected size while decompressing")
                        output.write(block)
                if count!=entry["size"]: raise ArchiveError("Extracted member size differs from manifest")
                evidence=_verify(target,limits); evidence["relative_path"]=entry["path"]; evidence["expected"]=entry["path"] in expected
                report["verified_files"].append(evidence)
        if _digest(path)!=manifest["archive_sha256"]: raise ArchiveError("Archive changed during extraction")
        report["limitations"]=[entry["office"]["limitations"] for entry in report["verified_files"] if entry.get("office",{}).get("structural_validation")=="structural_unverified"]
        report["status"]="verified_with_limitations" if report["limitations"] else "verified"
    except Exception as error:
        report["status"]="partial_failure" if report["created_files"] or report["created_directories"] else "failed"
        report["errors"].append(str(error))
    verified={entry["relative_path"]:entry for entry in report["verified_files"]}
    report["expected_verification"]={}
    for name in expected:
        if name in verified:
            report["expected_verification"][name]={"status":"verified",**verified[name]}
        else:
            report["expected_verification"][name]={"status":"not_verified","path":str(targets[name]),"exists":targets[name].exists()}
    return report


class ArchiveService:
    def __init__(self,policy,session_dir,limits=None):
        if not isinstance(policy,PathPolicy): raise TypeError("An explicit PathPolicy is required")
        self.policy=policy; self.session_dir=Path(session_dir); self.limits=_limits(limits)

    def inspect(self,args):
        if not isinstance(args,dict) or set(args)!={"path"}: raise ArchiveError("Inspect requires only path")
        raw=Path(args["path"]).expanduser()
        if not raw.is_absolute(): raw=self.policy.roots[0]/raw
        _reject_links(raw)
        return inspect_zip(self.policy.resolve(args["path"],True),self.limits)

    def extract(self,args,approved=False):
        if not isinstance(args,dict) or set(args)-{"path","destination","expected_files","expected_sha256"} or not {"path","destination"}.issubset(args): raise ArchiveError("Invalid extraction arguments")
        if approved is not True: raise PolicyError("Extraction requires explicit local approval")
        for key in ("path","destination"):
            raw=Path(args[key]).expanduser()
            if not raw.is_absolute(): raw=self.policy.roots[0]/raw
            _reject_links(raw)
        source=self.policy.resolve(args["path"],True); destination=self.policy.resolve(args["destination"])
        manifest=inspect_zip(source,self.limits)
        expected_hash=args.get("expected_sha256")
        if expected_hash is not None and (not isinstance(expected_hash,str) or not re.fullmatch(r"[0-9a-f]{64}",expected_hash) or expected_hash!=manifest["archive_sha256"]): raise PolicyError("Archive no longer matches the reviewed hash")
        for entry in manifest["entries"]: self.policy.resolve(destination.joinpath(*PurePosixPath(entry["path"]).parts))
        report=extract_zip(source,destination,args.get("expected_files",()),self.limits)
        folder=self.session_dir/"archive_reports"; folder.mkdir(parents=True,exist_ok=True)
        artifact=folder/(uuid.uuid4().hex+".json")
        with artifact.open("x",encoding="utf-8") as stream: json.dump(report,stream,ensure_ascii=False,indent=2)
        report["report_path"]=str(artifact)
        return report
