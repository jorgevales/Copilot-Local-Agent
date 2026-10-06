import hashlib
import io
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from copilot_agent.archives import ArchiveError,ArchiveService,inspect_zip,extract_zip,verify_delivered_file,verify_file,OFFICE_CONTENT_TYPES,OFFICE_PARTS,OFFICE_NAMESPACES,OFFICE_ROOTS,_reject_links
from copilot_agent.policy import PathPolicy,PolicyError,CLOUD_REPARSE_TAGS


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix="copilot_archive_test_")).resolve()

    def archive(self,name,members,compression=zipfile.ZIP_STORED):
        path=self.root/name
        with zipfile.ZipFile(path,"w",compression=compression) as archive:
            for key,value in members: archive.writestr(key,value)
        return path

    def office_bytes(self,kind="xlsx"):
        part,namespace,root=OFFICE_PARTS[kind],OFFICE_NAMESPACES[kind],OFFICE_ROOTS[kind]
        memory=io.BytesIO()
        with zipfile.ZipFile(memory,"w") as archive:
            archive.writestr("[Content_Types].xml",'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/'+part+'" ContentType="'+OFFICE_CONTENT_TYPES[kind]+'"/></Types>')
            archive.writestr(part,'<'+root+' xmlns="http://schemas.openxmlformats.org/'+namespace+'/2006/main"/>')
        return memory.getvalue()

    def test_coding_package_create_only_verified(self):
        package=self.archive("package.zip",[("src/main.py","print('synthetic')\n"),("README.md","Synthetic retained package")])
        manifest=inspect_zip(package)
        self.assertEqual(manifest["entry_count"],2)
        self.assertEqual(manifest["archive_sha256"],hashlib.sha256(package.read_bytes()).hexdigest())
        report=extract_zip(package,self.root/"output",expected_files=["src/main.py","README.md"])
        self.assertEqual(report["status"],"verified")
        self.assertEqual(report["expected_verification"]["src/main.py"]["python_syntax"],"passed_without_execution")
        self.assertTrue(package.exists())
        original=(self.root/"output/README.md").read_bytes()
        with self.assertRaises(ArchiveError): extract_zip(package,self.root/"output")
        self.assertEqual((self.root/"output/README.md").read_bytes(),original)

    def test_direct_verification_is_static_and_bounded(self):
        marker=self.root/"must_not_execute.txt"
        source=self.root/"delivered.py"
        source.write_text("from pathlib import Path\nPath("+repr(str(marker))+").write_text('executed')\n",encoding="utf-8")
        evidence=verify_delivered_file(source)
        self.assertEqual(evidence["python_syntax"],"passed_without_execution")
        self.assertEqual(evidence["sha256"],hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertFalse(marker.exists())
        data=self.root/"delivered.json"
        data.write_text('{"ready":true}',encoding="utf-8")
        self.assertEqual(verify_file(data)["json_syntax"],"passed")
        with self.assertRaises(ArchiveError): verify_file(data,{"max_file_bytes":1})
        invalid=self.root/"invalid_direct.json"
        invalid.write_text('{"same":1,"same":2}',encoding="utf-8")
        with self.assertRaises(ArchiveError): verify_file(invalid)
        self.assertTrue(invalid.exists())
        with self.assertRaises(ArchiveError): verify_file(self.root)

    def test_unsafe_member_names_rejected_before_writes(self):
        names=["../escape.txt","/absolute.txt","C:/absolute.txt","a/../../escape.txt","a\\..\\escape.txt","stream.txt:secret","CON.txt","folder./file.txt","a//file.txt"]
        for index,name in enumerate(names):
            package=self.archive(f"unsafe{index}.zip",[(name,"synthetic")])
            destination=self.root/f"rejected{index}"
            with self.assertRaises(ArchiveError,msg=name): extract_zip(package,destination)
            self.assertFalse(destination.exists())

    def test_duplicate_case_and_file_parent_conflicts(self):
        for index,members in enumerate([[('A.txt','one'),('a.txt','two')],[('parent','one'),('parent/child.txt','two')],[('Folder/one.txt','one'),('folder/two.txt','two')]]):
            with self.assertRaises(ArchiveError): inspect_zip(self.archive(f"conflict{index}.zip",members))

    def test_symlink_special_entries_and_limits(self):
        for index,mode in enumerate([stat.S_IFLNK|0o777,stat.S_IFIFO|0o644]):
            info=zipfile.ZipInfo("special");info.create_system=3;info.external_attr=mode<<16
            with self.assertRaises(ArchiveError): inspect_zip(self.archive(f"special{index}.zip",[(info,"target")]))
        package=self.archive("sizes.zip",[("one.txt","123456"),("two.txt","123456")])
        for limits in [{"max_entries":1},{"max_file_bytes":5},{"max_total_bytes":10}]:
            with self.assertRaises(ArchiveError): inspect_zip(package,limits)
        compressed=self.archive("ratio.zip",[("repeated.txt","x"*10000)],zipfile.ZIP_DEFLATED)
        with self.assertRaises(ArchiveError): inspect_zip(compressed,{"max_ratio":2})

    def test_office_zip_detection_and_nested_office_verification(self):
        for kind in ["docx","xlsx","pptx"]:
            disguised=self.root/(kind+".zip");disguised.write_bytes(self.office_bytes(kind))
            self.assertEqual(inspect_zip(disguised)["office"]["suggested_extension"],"."+kind)
        package=self.archive("office_package.zip",[("report.xlsx",self.office_bytes())])
        result=extract_zip(package,self.root/"office_output",expected_files=["report.xlsx"])
        self.assertEqual(result["status"],"verified")
        self.assertEqual(result["verified_files"][0]["office"]["office_type"],"xlsx")

    def test_partial_failure_preserves_outputs(self):
        package=self.archive("bad_python.zip",[("bad.py","def broken(:\n"),("later.txt","never reached")])
        destination=self.root/"partial"
        report=extract_zip(package,destination,expected_files=["bad.py","later.txt"])
        self.assertEqual(report["status"],"partial_failure")
        self.assertTrue((destination/"bad.py").exists())
        self.assertFalse((destination/"later.txt").exists())
        self.assertEqual(report["expected_verification"]["later.txt"]["status"],"not_verified")
        self.assertTrue(package.exists())

    def test_policy_approval_hash_and_expected_outputs(self):
        package=self.archive("service.zip",[("result.txt","synthetic")])
        service=ArchiveService(PathPolicy([self.root]),self.root/"session")
        manifest=service.inspect({"path":str(package)})
        args={"path":str(package),"destination":str(self.root/"service-output"),"expected_files":["result.txt"],"expected_sha256":manifest["archive_sha256"]}
        with self.assertRaises(PolicyError): service.extract(args)
        with self.assertRaises(PolicyError): service.extract({**args,"expected_sha256":"0"*64},approved=True)
        with self.assertRaises(PolicyError): service.extract({**args,"destination":"../outside"},approved=True)
        report=service.extract(args,approved=True)
        self.assertEqual(report["status"],"verified")
        self.assertTrue(Path(report["report_path"]).exists())
        with self.assertRaises(ArchiveError): extract_zip(package,self.root/"missing_expected",expected_files=["missing.txt"])
        self.assertFalse((self.root/"missing_expected").exists())

    def test_malformed_office_xml_not_claimed_verified(self):
        package=self.archive("bad_office.zip",[("bad.xlsx",b"not an Office ZIP")])
        report=extract_zip(package,self.root/"bad_office",expected_files=["bad.xlsx"])
        self.assertEqual(report["status"],"partial_failure")
        self.assertTrue((self.root/"bad_office/bad.xlsx").exists())

    def test_unsupported_compression_rejected(self):
        package=self.archive("bzip.zip",[("data.txt","synthetic")],zipfile.ZIP_BZIP2)
        with self.assertRaises(ArchiveError): inspect_zip(package)

    def test_encrypted_flag_rejected_without_decrypting(self):
        original=self.archive("unencrypted_source.zip",[("data.txt","synthetic")])
        payload=bytearray(original.read_bytes())
        local=payload.index(b"PK\x03\x04"); central=payload.index(b"PK\x01\x02")
        payload[local+6]|=1; payload[central+8]|=1
        encrypted=self.root/"encrypted_flag_fixture.zip"; encrypted.write_bytes(payload)
        with self.assertRaises(ArchiveError): inspect_zip(encrypted)

    def test_office_wrong_content_type_rejected(self):
        package=self.archive("wrong_content_type.zip",[("[Content_Types].xml",'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="application/wrong"/></Types>'),("xl/workbook.xml",'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')])
        with self.assertRaises(ArchiveError): inspect_zip(package)

    def test_macros_templates_and_extension_mismatch(self):
        for extension in ["docm","dotx","dotm","xlsm","xltx","xltm","xlam","pptm","potx","potm","ppsx","ppsm","ppam"]:
            native=self.root/(extension+".zip");native.write_bytes(self.office_bytes(extension))
            office=inspect_zip(native)["office"]
            self.assertEqual(office["office_type"],extension)
            self.assertEqual(office["active_content"],"macroEnabled" in OFFICE_CONTENT_TYPES[extension])
        package=self.archive("mismatched_extension.zip",[("wrong.xlsx",self.office_bytes("xlsm"))])
        self.assertEqual(extract_zip(package,self.root/"mismatch")["status"],"partial_failure")

    def test_legacy_and_binary_office_are_truthfully_limited(self):
        legacy=b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"+b"synthetic not a full OLE document"
        package=self.archive("legacy.zip",[("report.xls",legacy)])
        result=extract_zip(package,self.root/"legacy-output",expected_files=["report.xls"])
        self.assertEqual(result["status"],"verified_with_limitations")
        self.assertEqual(result["verified_files"][0]["office"]["structural_validation"],"structural_unverified")
        invalid=self.archive("invalid_legacy.zip",[("report.doc",b"not an OLE signature")])
        self.assertEqual(extract_zip(invalid,self.root/"invalid-legacy-output")["status"],"partial_failure")
        memory=io.BytesIO()
        with zipfile.ZipFile(memory,"w") as archive:
            archive.writestr("[Content_Types].xml",'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.bin" ContentType="application/vnd.ms-excel.sheet.binary.macroEnabled.main"/></Types>')
            archive.writestr("xl/workbook.bin",b"synthetic binary not parsed")
        package=self.archive("binary.zip",[("report.xlsb",memory.getvalue())])
        result=extract_zip(package,self.root/"binary-output",expected_files=["report.xlsb"])
        self.assertEqual(result["status"],"verified_with_limitations")
        self.assertTrue(result["limitations"])

    def test_text_json_success_and_invalid_content_preserved(self):
        package=self.archive("text.zip",[("readme.txt","utf8 content"),("config.json",'{"ready":true}')])
        result=extract_zip(package,self.root/"text-output")
        self.assertEqual(result["status"],"verified")
        self.assertEqual(result["verified_files"][1]["json_syntax"],"passed")
        for index,(name,data) in enumerate([("bad.txt",b"\xff"),("bad.json",b"{broken"),("duplicate.json",b'{"key":1,"key":2}'),("infinite.json",b'{"number":1e999}')]):
            package=self.archive(f"badtext{index}.zip",[(name,data)])
            destination=self.root/f"badtext-output{index}"
            report=extract_zip(package,destination)
            self.assertEqual(report["status"],"partial_failure")
            self.assertEqual((destination/name).read_bytes(),data)

    def test_policy_roots_credentials_and_direct_hardlinks(self):
        import os
        protected=self.archive("protected.zip",[("edge_profile/Default/Network/Cookies","synthetic never written")])
        service=ArchiveService(PathPolicy([self.root]),self.root/"session")
        with self.assertRaises(PolicyError): service.extract({"path":str(protected),"destination":str(self.root/"protected-output")},approved=True)
        self.assertFalse((self.root/"protected-output").exists())
        source=self.archive("hardlink-source.zip",[("safe.txt","synthetic")])
        alias=self.root/"hardlink-alias.zip"
        try: os.link(source,alias)
        except OSError: self.skipTest("Hardlink creation unavailable")
        with self.assertRaises(ArchiveError): inspect_zip(alias)
        with self.assertRaises((PolicyError,ArchiveError)): service.inspect({"path":str(alias)})

    def test_parent_link_change_detected_before_file_write(self):
        from unittest.mock import patch
        package=self.archive("race.zip",[("sub/output.txt","synthetic")])
        destination=self.root/"race-output"
        calls=0
        def detect(path):
            nonlocal calls
            _reject_links(path)
            if Path(path)==destination/"sub/output.txt":
                calls+=1
                if calls>=3: raise ArchiveError("Synthetic parent reparse change detected")
        with patch("copilot_agent.archives._reject_links",side_effect=detect):
            result=extract_zip(package,destination)
        self.assertEqual(result["status"],"partial_failure")
        self.assertFalse((destination/"sub/output.txt").exists())
        self.assertTrue(destination.exists())

    def mock_reparse(self,tags):
        from types import SimpleNamespace
        from unittest.mock import patch
        original=Path.lstat
        def details(path):
            info=original(path)
            if path not in tags: return info
            return SimpleNamespace(st_mode=info.st_mode,st_reparse_tag=tags[path],st_file_attributes=0x400,st_nlink=info.st_nlink)
        return patch.object(Path,"lstat",details)

    def test_cloud_file_and_parent_tags_keep_policy_and_verification(self):
        folder=self.root/"cloud";folder.mkdir()
        data=folder/"result.json";data.write_text('{"cloud":true}',encoding="utf-8")
        package=self.archive("cloud-source.zip",[("result.txt","synthetic")])
        policy=PathPolicy([self.root])
        for tag in sorted(CLOUD_REPARSE_TAGS):
            with self.subTest(tag=hex(tag)),self.mock_reparse({folder:tag,data:tag,package:tag}):
                self.assertEqual(policy.resolve(data,True),data)
                self.assertEqual(verify_file(data)["json_syntax"],"passed")
                self.assertEqual(inspect_zip(package)["entry_count"],1)
                with self.assertRaises(PolicyError): policy.resolve(self.root.parent/"outside-cloud-scope.txt")
                with self.assertRaises(PolicyError): policy.resolve(folder/"Cookies")
        with self.mock_reparse({self.root:0x9000001A,package:0x9000F01A}):
            report=extract_zip(package,self.root/"cloud-output")
            self.assertEqual(report["status"],"verified")

    def test_unknown_and_surrogate_reparse_file_and_parent_denied(self):
        folder=self.root/"tagged";folder.mkdir()
        data=folder/"data.txt";data.write_text("synthetic",encoding="utf-8")
        policy=PathPolicy([self.root])
        for tag in [0,0x80001234,0xA0001234,0xA0000003,0xA000000C,0x9001001A,0xB000001A]:
            for location in [folder,data]:
                with self.subTest(tag=hex(tag),location=str(location)),self.mock_reparse({location:tag}):
                    with self.assertRaises(PolicyError): policy.resolve(data,True)
                    with self.assertRaises(ArchiveError): verify_file(data)

    def test_cloud_tag_does_not_authorize_changed_resolved_path(self):
        from unittest.mock import patch
        folder=self.root/"cloud-redirect";folder.mkdir()
        data=folder/"data.txt";data.write_text("synthetic",encoding="utf-8")
        policy=PathPolicy([self.root]);original=Path.resolve
        def changed(path,*args,**kwargs):
            if path==folder: return self.root.parent/"different-named-path"
            return original(path,*args,**kwargs)
        with self.mock_reparse({folder:0x9000001A}),patch.object(Path,"resolve",changed):
            with self.assertRaises(PolicyError): policy.resolve(data,True)
            with self.assertRaises(ArchiveError): verify_file(data)
