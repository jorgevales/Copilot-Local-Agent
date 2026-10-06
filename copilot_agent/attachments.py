"""Explicitly selected user-file queue, separate from local tool file roots."""
from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import zipfile
from pathlib import Path, PureWindowsPath

from .logging_utils import SENSITIVE
from .policy import PathPolicy, PolicyError, config_value, reject_path_redirection

MAX_USER_FILES=10
MAX_FILE_BYTES=20*1024*1024
TEXT_EXTENSIONS=frozenset({'.txt','.md','.json','.csv','.py','.js','.ts','.jsx','.tsx','.css','.html','.htm','.xml','.svg','.yaml','.yml','.toml','.ini','.cfg','.sql','.ps1','.bat','.cmd','.sh'})
OFFICE_EXTENSIONS=frozenset({'.docx','.xlsx','.pptx'})
SUPPORTED_EXTENSIONS=TEXT_EXTENSIONS|OFFICE_EXTENSIONS|{'.pdf','.png','.jpg','.jpeg','.webp','.bmp'}
NATIVE_UPLOAD_EXTENSIONS=frozenset({'.md','.txt','.json','.csv','.pdf','.docx','.xlsx','.pptx','.png','.jpg','.jpeg','.webp','.bmp'})


def upload_name(path):
    path=Path(path)
    if path.suffix.casefold()=='.zip':
        raise AttachmentError('ZIP files cannot be attached; select the extracted supported files')
    if path.suffix.casefold() not in SUPPORTED_EXTENSIONS:
        raise AttachmentError('Unsupported attachment upload type')
    return path.name if path.suffix.casefold() in NATIVE_UPLOAD_EXTENSIONS else path.name+'.txt'


class AttachmentError(PolicyError):
    pass


class AttachmentQueue:
    """Validate only selected sources; caller validates the discovered account root.

    No queue operation deletes or alters files. Verification is not OS isolation
    from another local process changing paths or bytes during upload.
    """
    def __init__(self,config,account_root=None):
        self.config=config
        root=account_root if account_root is not None else config_value(config,'storage_dir')
        if root is None:
            configured=config_value(config,'allowed_roots',[])
            root=configured[0] if configured else None
        if root is None: raise AttachmentError('Select your OneDrive account before adding files')
        self.account_root=Path(root).expanduser().resolve(strict=True)
        if not self.account_root.is_dir(): raise AttachmentError('Attachment account root must be a directory')
        roots=[self.account_root]
        if os.name=='nt': roots.append(Path('S:/'))
        excluded=[]
        for value in [config_value(config,'profile_dir'),config_value(config,'runtime_dir')]:
            if value is not None: excluded.append(Path(value))
        storage=config_value(config,'storage_dir')
        if storage is not None: excluded.append(Path(storage)/'runtime')
        self.policy=PathPolicy(roots,excluded_roots=excluded)
        cap=config_value(config,'max_attachment_bytes',MAX_FILE_BYTES)
        if type(cap) is not int or cap<1: raise AttachmentError('Attachment size cap must be positive')
        self.max_bytes=min(cap,MAX_FILE_BYTES)
        self._records=[]

    @staticmethod
    def _key(path):
        return str(path).casefold()

    def _resolve(self,path):
        try: return self._resolve_source(path)
        except (PolicyError,OSError) as error:
            raise AttachmentError(str(error)) from error

    def _resolve_source(self,path):
        if not isinstance(path,(str,Path)) or not str(path).strip(): raise AttachmentError('Select a nonempty file path')
        raw=Path(path).expanduser()
        # A drive-relative S:foo path is not an explicit selected file.
        windows=PureWindowsPath(str(path))
        if windows.drive.casefold()=='s:' and (os.name!='nt' or not windows.is_absolute()):
            raise AttachmentError('Shared-drive attachments require an absolute existing Windows S: path')
        if not raw.is_absolute(): raw=self.account_root/raw
        reject_path_redirection(raw)
        resolved=self.policy.resolve(raw,must_exist=True)
        if resolved.drive.casefold()=='s:' and raw.drive.casefold()!='s:':
            raise AttachmentError('Shared-drive source must be selected directly on S:')
        return resolved

    def _record(self,path):
        resolved=self._resolve(path)
        info=resolved.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink>1:
            raise AttachmentError('Attachment must be a regular file without hardlink aliases')
        extension=resolved.suffix.casefold()
        if extension=='.zip': raise AttachmentError('ZIP files cannot be attached; select the extracted supported files')
        if extension not in SUPPORTED_EXTENSIONS: raise AttachmentError('Unsupported attachment type: '+extension)
        if info.st_size>self.max_bytes: raise AttachmentError('Attachment exceeds the '+str(self.max_bytes)+' byte size limit')
        content=bytearray()
        with resolved.open('rb') as source:
            while block:=source.read(min(65536,self.max_bytes+1-len(content))):
                content.extend(block)
                if len(content)>self.max_bytes: raise AttachmentError('Attachment grew beyond its size limit')
        if len(content)!=info.st_size: raise AttachmentError('Attachment changed while being read')
        if extension in TEXT_EXTENSIONS:
            try: text=content.decode('utf-8-sig')
            except UnicodeError as error: raise AttachmentError('Text/code attachments must be readable UTF-8') from error
            if '\x00' in text: raise AttachmentError('Text attachment contains binary NUL bytes')
            quoted_credentials=re.search(r'(?i)["\'](?:password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret)["\']\s*[:=]\s*["\']?[^\s,;}]+',text)
            if SENSITIVE.search(text) or quoted_credentials or 'PRIVATE KEY-----' in text:
                raise AttachmentError('Credential-like text cannot be attached')
        if zipfile.is_zipfile(io.BytesIO(content)):
            if extension not in OFFICE_EXTENSIONS:
                raise AttachmentError('ZIP content cannot be attached under another extension')
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names=set(archive.namelist())
            main={'.docx':'word/document.xml','.xlsx':'xl/workbook.xml','.pptx':'ppt/presentation.xml'}[extension]
            if not {'[Content_Types].xml',main}.issubset(names):
                raise AttachmentError('ZIP package lacks the selected native Office container parts')
        elif extension in OFFICE_EXTENSIONS:
            raise AttachmentError('Office attachment is not a valid native Office container')
        checked=self._resolve(resolved)
        after=checked.stat()
        if checked!=resolved or after.st_size!=info.st_size or after.st_mtime_ns!=info.st_mtime_ns:
            raise AttachmentError('Attachment changed during validation')
        return {'path':str(resolved),'name':resolved.name,'upload_name':upload_name(resolved),'size':len(content),'sha256':hashlib.sha256(content).hexdigest(),'extension':extension,'kind':'code' if extension=='.py' else 'text' if extension in TEXT_EXTENSIONS else 'document' if extension in OFFICE_EXTENSIONS or extension=='.pdf' else 'image','requires_text_conversion':extension not in NATIVE_UPLOAD_EXTENSIONS}

    def add(self,paths):
        if not isinstance(paths,(list,tuple)) or not paths: raise AttachmentError('Select one or more files')
        proposed=[dict(record) for record in self._records]
        by_path={self._key(item['path']):item for item in proposed}
        by_name={item['upload_name'].casefold():item for item in proposed}
        source_names={item['name'].casefold() for item in proposed}
        for path in paths:
            resolved=self._resolve(path);key=self._key(resolved)
            if key in by_path: continue
            if upload_name(resolved).casefold() in by_name or resolved.name.casefold() in source_names:
                raise AttachmentError('Two attachments have the same filename: '+resolved.name+'. Rename one before selecting both.')
            if len(proposed)>=MAX_USER_FILES:
                raise AttachmentError('At most '+str(MAX_USER_FILES)+' user files can be queued; '+str(20-MAX_USER_FILES)+' attachment slots are reserved for startup guidance, findings and context')
            record=self._record(resolved)
            proposed.append(record);by_path[key]=record;by_name[record['upload_name'].casefold()]=record;source_names.add(record['name'].casefold())
        self._records=proposed
        return self.records()

    def records(self):
        return [dict(record) for record in self._records]

    def paths(self):
        return [Path(record['path']) for record in self._records]

    def remove(self,index1based):
        if type(index1based) is not int or not 1<=index1based<=len(self._records):
            raise AttachmentError('Attachment index must be between 1 and '+str(len(self._records)))
        return dict(self._records.pop(index1based-1))

    def clear(self):
        self._records=[]

    def verify(self):
        current=[]
        for record in self._records:
            checked=self._record(record['path'])
            if any(checked[key]!=record[key] for key in ('path','size','sha256','extension')):
                raise AttachmentError('Queued attachment changed; remove and select it again: '+record['name'])
            current.append(checked)
        return current
