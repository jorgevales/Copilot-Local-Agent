"""Local byte-ingestion tests; no browser, model, or Copilot connection."""
import base64
import tempfile
import unittest
from pathlib import Path

from agent_ui.uploads import MAX_MESSAGE_ATTACHMENTS, UploadError, UploadStore
from copilot_agent.attachments import MAX_FILE_BYTES


def payload(name="review.py", content=b"print('safe review only')\n", **overrides):
    result = {"name": name, "content_type": "text/x-python", "declared_size": len(content),
              "content_base64": base64.b64encode(content).decode("ascii")}
    result.update(overrides)
    return result


class UploadStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = UploadStore(Path(self.temp.name) / "staging")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_python_is_reviewable_content_with_stable_id_and_private_path(self):
        record = self.store.add(**payload(client_message_id="msg_1"))
        self.assertEqual("code", record["kind"])
        self.assertFalse(record["executable"])
        self.assertEqual("review.py", record["name"])
        self.assertNotIn("path", record)
        path, = self.store.resolve_paths([record["attachment_id"]])
        self.assertEqual(b"print('safe review only')\n", path.read_bytes())
        self.assertEqual("review.py", path.name)
        retried = self.store.add(**payload(client_message_id="msg_1"))
        self.assertEqual(record["attachment_id"], retried["attachment_id"])

    def test_reused_id_with_different_bytes_is_rejected(self):
        self.store.add(**payload(client_message_id="msg_1"))
        with self.assertRaises(UploadError):
            self.store.add(**payload(content=b"different", client_message_id="msg_1"))

    def test_filename_paths_and_unsupported_extensions_are_rejected(self):
        for name in ("../review.py", r"C:\secret\review.py", "CON.txt", "archive.zip", "payload.exe"):
            with self.subTest(name=name), self.assertRaises(UploadError):
                self.store.add(**payload(name=name))

    def test_mismatched_size_binary_python_and_credentials_are_rejected(self):
        with self.assertRaises(UploadError):
            self.store.add(**payload(declared_size=100))
        with self.assertRaises(UploadError):
            self.store.add(**payload(content=b"\xff\x00"))
        with self.assertRaises(UploadError):
            self.store.add(**payload(content=b"password=secret-value"))

    def test_size_limit_and_message_count_are_server_enforced(self):
        oversize = b"x" * (MAX_FILE_BYTES + 1)
        with self.assertRaises(UploadError):
            self.store.add(**payload(content=oversize))
        ids = []
        for index in range(MAX_MESSAGE_ATTACHMENTS):
            item = self.store.add(**payload(name=f"file-{index}.txt", content=f"item {index}".encode()))
            ids.append(item["attachment_id"])
        with self.assertRaises(UploadError):
            self.store.add(**payload(name="twenty-one.txt", content=b"last"))
        with self.assertRaises(UploadError):
            self.store.resolve_paths(ids + [ids[0]])

    def test_changed_staged_file_is_rejected(self):
        record = self.store.add(**payload())
        path, = self.store.resolve_paths([record["attachment_id"]])
        path.write_bytes(b"tampered")
        with self.assertRaises(UploadError):
            self.store.resolve_paths([record["attachment_id"]])

    def test_close_removes_session_staging(self):
        record = self.store.add(**payload())
        path, = self.store.resolve_paths([record["attachment_id"]])
        self.store.close()
        self.assertFalse(path.exists())

    def test_per_message_limit_allows_multiple_messages_and_consumed_retry_keeps_identity(self):
        prior = []
        for index in range(20):
            item = self.store.add(**payload(name=f"first-{index}.txt", content=f"first {index}".encode(),
                                            client_message_id=f"message-a:{index}"))
            prior.append(item["attachment_id"])
        with self.assertRaises(UploadError):
            self.store.add(**payload(name="first-over-limit.txt", content=b"extra",
                                     client_message_id="message-a:20"))
        next_message = self.store.add(**payload(name="second-0.txt", content=b"second",
                                                client_message_id="message-b:0"))
        path, = self.store.resolve_paths([prior[0]])
        self.store.discard([prior[0]])
        self.assertFalse(path.exists())
        retried = self.store.add(**payload(name="first-0.txt", content=b"first 0",
                                           client_message_id="message-a:0"))
        self.assertEqual(retried["attachment_id"], prior[0])
        self.assertEqual(self.store.resolve_paths([next_message["attachment_id"]])[0].read_bytes(), b"second")


if __name__ == "__main__":
    unittest.main()
