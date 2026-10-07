"""Deterministic privacy, consent, freshness and namespace isolation tests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from copilot_agent.policy import PolicyError
from copilot_agent.protocol import validate_schema
from copilot_agent.site_knowledge import (
    KNOWLEDGE_EXAMPLES, KNOWLEDGE_SPECS, execute_knowledge, knowledge_directory,
    prepare_knowledge, validate_knowledge,
)


class SiteKnowledgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="copilot_site_knowledge_test_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
        isolated = object()
        self.page = SimpleNamespace(url="https://example.com/home", context=isolated)
        self.context = {"session_dir": self.root / "session-a",
                        "browser": SimpleNamespace(tool_page=self.page, tool_context=isolated),
                        "knowledge_directory": self.root / "private-memory",
                        "site_knowledge_clock": lambda: self.now,
                        "site_knowledge_bindings": {}, "approved": False}
        self.bind_args = deepcopy(KNOWLEDGE_EXAMPLES["site_knowledge.bind"])
        self.save_args = deepcopy(KNOWLEDGE_EXAMPLES["site_knowledge.save"])

    def approve(self, name, args, *, consent=True):
        prepared = prepare_knowledge(args, self.context, name=name)
        self.context.update(approved=True, approval_hash="a" * 64,
                            site_knowledge_reviewed=deepcopy(prepared))
        if name == "site_knowledge.save" and consent:
            self.context["site_knowledge_consent"] = deepcopy(prepared)
        return prepared

    def bind(self, **changes):
        args = dict(self.bind_args, **changes)
        self.approve("site_knowledge.bind", args)
        return execute_knowledge("site_knowledge.bind", args, self.context)

    def save(self, args=None):
        args = self.save_args if args is None else args
        self.approve("site_knowledge.save", args)
        return execute_knowledge("site_knowledge.save", args, self.context)

    def retrieve(self):
        return execute_knowledge("site_knowledge.retrieve", {"origin": "https://example.com"}, self.context)

    def record(self):
        return next((self.root / "private-memory").glob("*.json"))

    def test_catalog_examples_have_strict_supported_schemas(self):
        self.assertEqual(set(KNOWLEDGE_SPECS), set(KNOWLEDGE_EXAMPLES))
        for name, (schema, approval, description) in KNOWLEDGE_SPECS.items():
            self.assertEqual(validate_schema(KNOWLEDGE_EXAMPLES[name], schema), [], name)
            self.assertFalse(schema["additionalProperties"])
            self.assertIn(approval, {"read_only", "user_approval"})
            self.assertTrue(description)

    def test_bind_is_real_reviewed_local_grant_and_does_not_save(self):
        prepared = prepare_knowledge(self.bind_args, self.context, name="site_knowledge.bind")
        self.assertFalse((self.root / "private-memory").exists())
        self.context.update(approved=True, approval_hash="a" * 64)
        with self.assertRaises(PolicyError):
            execute_knowledge("site_knowledge.bind", self.bind_args, self.context)
        self.assertFalse(self.context["site_knowledge_bindings"])
        self.context["site_knowledge_reviewed"] = prepared
        result = execute_knowledge("site_knowledge.bind", self.bind_args, self.context)
        self.assertEqual(result["status"], "bound")
        self.assertFalse(result["knowledge_saved"])
        self.assertFalse((self.root / "private-memory").exists())
        self.assertEqual(self.retrieve()["status"], "missing")

    def test_decline_and_llm_consent_flags_cannot_save(self):
        self.bind()
        self.context["approved"] = False
        with self.assertRaises(PolicyError):
            execute_knowledge("site_knowledge.save", self.save_args, self.context)
        self.assertFalse((self.root / "private-memory").exists())
        self.approve("site_knowledge.save", self.save_args, consent=False)
        self.context["site_knowledge_consent"] = True
        with self.assertRaises(PolicyError):
            execute_knowledge("site_knowledge.save", self.save_args, self.context)
        with self.assertRaises(ValueError):
            execute_knowledge("site_knowledge.save", dict(self.save_args, consent=True), self.context)
        self.assertFalse((self.root / "private-memory").exists())
        # A refusal does not clear task/session scope or prevent continued reads.
        self.assertEqual(self.retrieve()["status"], "missing")

    def test_save_retrieve_query_export_and_verified_provenance(self):
        self.bind()
        saved = self.save()
        self.assertEqual(saved["status"], "saved")
        self.assertTrue(saved["locally_verified"])
        result = self.retrieve()
        self.assertEqual(result["status"], "fresh")
        self.assertEqual(result["knowledge"], self.save_args["knowledge"])
        self.assertEqual(result["age_seconds"], 0)
        self.assertEqual(result["confidence"], "locally_reviewed_templates")
        self.assertTrue(result["requires_current_page_verification"])
        self.assertEqual(result["provenance"]["source_urls"], ["https://example.com/customers/search"])
        query = execute_knowledge("site_knowledge.query", {"origin": "https://example.com", "category": "routes", "route": "/documents"}, self.context)
        self.assertEqual(query["knowledge"], {"routes": []})
        summary = execute_knowledge("site_knowledge.export", {"origin": "https://example.com"}, self.context)
        self.assertEqual(summary["summary"]["item_counts"], {"routes": 1})
        self.assertNotIn("knowledge", summary)
        stored = self.record().read_text(encoding="utf-8")
        for value in ("tenant-a", "private-user", str(self.root)):
            self.assertNotIn(value, stored)
        record = json.loads(stored)
        self.assertEqual(record["consent"]["categories"], ["routes"])
        self.assertEqual(record["consent"]["approval_hash"], "a" * 64)
        self.assertEqual(len(record["consent"]["review_sha256"]), 64)

    def test_all_allowed_categories_and_generic_parameter_templates(self):
        self.bind()
        knowledge = {
            "routes": [{"path": "/customers/{customer}/documents", "purpose": "documents", "parent_path": "/customers/{customer}"}],
            "locators": [{"path": "/customers/search", "purpose": "search", "strategy": "role", "role": "textbox", "value": "Customer search"},
                         {"path": "/documents", "purpose": "documents", "strategy": "css", "value": "nav .documents"}],
            "forms": [{"path": "/customers/search", "purpose": "customer_search", "fields": [{"label": "Customer ID", "required": True, "input_type": "text"}]}],
            "document_areas": [{"path": "/customers/{customer}/documents", "label": "Documents", "file_types": ["pdf", "docx"]}],
            "recovery": [{"path": "/documents", "failure": "layout_changed", "steps": ["reinspect_page", "use_locator_fallback"]}],
        }
        result = self.save({"origin": "https://example.com", "categories": list(knowledge), "knowledge": knowledge})
        self.assertEqual(result["item_counts"], {key: len(items) for key, items in knowledge.items()})
        self.assertEqual(self.retrieve()["knowledge"], knowledge)

    def test_expiry_boundary_prevents_reuse_without_deleting_record(self):
        self.bind()
        self.save(dict(self.save_args, ttl_days=1))
        self.now += timedelta(days=1, seconds=-1)
        self.assertEqual(self.retrieve()["status"], "fresh")
        self.now += timedelta(seconds=1)
        for name in ("site_knowledge.retrieve", "site_knowledge.query", "site_knowledge.export"):
            result = execute_knowledge(name, {"origin": "https://example.com"}, self.context)
            self.assertEqual(result["status"], "expired")
            self.assertEqual(result["knowledge"], {})
        self.assertTrue(self.record().exists())

    def test_invalidation_requires_approval_and_blocks_retrieval(self):
        self.bind()
        self.save()
        args = {"origin": "https://example.com"}
        with self.assertRaises(PolicyError):
            execute_knowledge("site_knowledge.invalidate", args, self.context)
        self.approve("site_knowledge.invalidate", args)
        result = execute_knowledge("site_knowledge.invalidate", args, self.context)
        self.assertEqual(result["status"], "invalidated")
        self.assertTrue(result["retained_locally"])
        self.assertEqual(self.retrieve()["knowledge"], {})
        self.assertEqual(self.retrieve()["status"], "invalidated")

    def test_namespace_isolation_across_tenant_user_and_environment(self):
        self.bind()
        original = self.save()["namespace_id"]
        for changes in ({"tenant": "tenant-b"}, {"user_scope": "another-user"}, {"environment": "production"}):
            self.bind(**changes)
            result = self.retrieve()
            self.assertEqual(result["status"], "missing")
            self.assertNotEqual(result["namespace_id"], original)
            self.assertEqual(len(self.context["site_knowledge_bindings"]), 1)
        self.bind()
        self.assertEqual(self.retrieve()["status"], "fresh")

    def test_new_session_requires_local_rebinding_then_reuses_approved_knowledge(self):
        self.bind()
        self.save()
        self.context["session_dir"] = self.root / "session-b"
        with self.assertRaises(PolicyError):
            self.retrieve()
        self.bind()
        self.assertEqual(self.retrieve()["status"], "fresh")

    def test_copied_record_cannot_cross_tenant_namespace(self):
        self.bind()
        self.save()
        original = self.record().read_bytes()
        binding = self.bind(tenant="tenant-b")
        (self.root / "private-memory" / (binding["namespace_id"] + ".json")).write_bytes(original)
        with self.assertRaisesRegex(PolicyError, "namespace"):
            self.retrieve()

    def test_unselected_scope_arbitrary_origin_and_wrong_tab_are_denied(self):
        with self.assertRaises(PolicyError):
            self.retrieve()
        with self.assertRaises(PolicyError):
            prepare_knowledge(dict(self.bind_args, origin="https://other.test"), self.context, name="site_knowledge.bind")
        self.bind()
        self.save()
        self.page.url = "https://other.test/home"
        with self.assertRaises(PolicyError):
            self.retrieve()
        self.page.url = "https://example.com/home"
        for addition in ({"tenant": "tenant-b"}, {"user_scope": "another-user"}, {"namespace_id": "a" * 64}):
            with self.assertRaises(ValueError):
                execute_knowledge("site_knowledge.retrieve", {"origin": "https://example.com", **addition}, self.context)

    def test_material_changes_in_payload_categories_ttl_directory_require_fresh_consent(self):
        self.bind()
        self.approve("site_knowledge.save", self.save_args)
        changed = deepcopy(self.save_args)
        changed["knowledge"]["routes"][0]["path"] = "/documents"
        with self.assertRaises(PolicyError):
            execute_knowledge("site_knowledge.save", changed, self.context)
        with self.assertRaises(PolicyError):
            execute_knowledge("site_knowledge.save", dict(self.save_args, ttl_days=31), self.context)
        self.context["knowledge_directory"] = self.root / "another-memory"
        with self.assertRaises(PolicyError):
            execute_knowledge("site_knowledge.save", self.save_args, self.context)
        self.assertFalse((self.root / "private-memory").exists())
        self.assertFalse((self.root / "another-memory").exists())

    def test_ids_queries_names_contact_details_and_tokens_rejected_without_echo(self):
        self.bind()
        rejected_paths = ["/customers/12345/documents", "/customers/jane-smith/documents",
                          "/customers/secret/documents", "/customers/lookup?customer=12345",
                          "/documents#private", "/customers/%4aane", "/documents/123.pdf",
                          "/customers/{customer}/documents?token=TOPSECRET", "/../documents"]
        for path in rejected_paths:
            args = deepcopy(self.save_args)
            args["knowledge"]["routes"][0]["path"] = path
            with self.assertRaises(ValueError) as error:
                prepare_knowledge(args, self.context, name="site_knowledge.save")
            self.assertNotIn("TOPSECRET", str(error.exception))
        for label in ("Jane Smith", "jane@example.test", "API token abcsecret", "Customer 12345", "Bearer abcdefghijk"):
            args = deepcopy(self.save_args)
            args["knowledge"]["routes"][0]["label"] = label
            with self.assertRaises(ValueError) as error:
                prepare_knowledge(args, self.context, name="site_knowledge.save")
            self.assertNotIn(label, str(error.exception))
        args = deepcopy(self.save_args)
        args["knowledge"]["Jane Smith"] = []
        with self.assertRaises(ValueError) as error:
            prepare_knowledge(args, self.context, name="site_knowledge.save")
        self.assertNotIn("Jane Smith", str(error.exception))
        self.assertFalse((self.root / "private-memory").exists())

    def test_form_values_raw_page_content_and_unapproved_categories_rejected(self):
        self.bind()
        fields = [{"label": "Customer ID", "required": True, "input_type": "text", "value": "secret"}]
        args = {"origin": "https://example.com", "categories": ["forms"],
                "knowledge": {"forms": [{"path": "/customers/search", "purpose": "customer_search", "fields": fields}]}}
        with self.assertRaises(ValueError):
            prepare_knowledge(args, self.context, name="site_knowledge.save")
        for addition in ({"page_text": "private"}, {"cookies": []}, {"customer_id": "12345"}):
            with self.assertRaises(ValueError):
                prepare_knowledge({**self.save_args, **addition}, self.context, name="site_knowledge.save")
        args = deepcopy(self.save_args)
        args["categories"] = ["document_areas"]
        with self.assertRaises(ValueError):
            prepare_knowledge(args, self.context, name="site_knowledge.save")

    def test_authentication_and_captcha_recovery_cannot_bypass_user(self):
        self.bind()
        for failure in ("auth_expired", "access_denied", "captcha"):
            args = {"origin": "https://example.com", "categories": ["recovery"],
                    "knowledge": {"recovery": [{"path": "/", "failure": failure, "steps": ["use_locator_fallback"]}]}}
            with self.assertRaises(ValueError):
                prepare_knowledge(args, self.context, name="site_knowledge.save")
            args["knowledge"]["recovery"][0]["steps"] = ["ask_user", "stop"]
            self.save(args)
            self.assertEqual(self.retrieve()["knowledge"], args["knowledge"])

    def test_locators_cannot_persist_dynamic_customer_attributes_or_script(self):
        self.bind()
        for strategy, value in (("css", "[data-customer-id='12345']"), ("css", "#jane-smith"),
                                ("css", "a[href*='token=secret']"), ("test_id", "customer-12345"),
                                ("label", "Jane Smith"), ("css", "button:has-text('Delete Jane')")):
            args = {"origin": "https://example.com", "categories": ["locators"],
                    "knowledge": {"locators": [{"path": "/customers/search", "purpose": "search", "strategy": strategy, "value": value}]}}
            with self.assertRaises(ValueError):
                prepare_knowledge(args, self.context, name="site_knowledge.save")

    def test_corrupt_tampered_nonfinite_and_duplicate_records_fail_closed(self):
        self.bind()
        self.save()
        path = self.record()
        original = path.read_text(encoding="utf-8")
        record = json.loads(original)
        samples = ["{broken", original.replace('"schema_version":1', '"schema_version":1,"schema_version":1'),
                   original.replace('"schema_version":1', '"schema_version":NaN')]
        changed = deepcopy(record)
        changed["knowledge"]["routes"][0]["path"] = "/documents"
        samples.append(json.dumps(changed))
        changed = deepcopy(record)
        changed["provenance"]["request"] = "Jane Smith"
        samples.append(json.dumps(changed))
        changed = deepcopy(record)
        changed["expires_at"] = "2099-01-01T00:00:00+00:00"
        samples.append(json.dumps(changed))
        changed = deepcopy(record)
        changed["knowledge"]["routes"][0]["label"] = "Jane Smith"
        samples.append(json.dumps(changed))
        for text in samples:
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(PolicyError):
                self.retrieve()
        path.write_text(original, encoding="utf-8")
        self.assertEqual(self.retrieve()["status"], "fresh")

    def test_local_device_storage_not_config_runtime_or_developer_memory(self):
        context = dict(self.context)
        del context["knowledge_directory"]
        context["config"] = {"runtime_dir": str(self.root / "OneDrive" / "runtime")}
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root / "local")}, clear=True):
            directory = knowledge_directory(context)
            self.assertEqual(directory, self.root / "local" / "CopilotLocalAgent" / "site-knowledge")
            prepared = prepare_knowledge(self.bind_args, context, name="site_knowledge.bind")
            self.assertIn("outside OneDrive", prepared["storage_scope"])
            self.assertFalse(directory.exists())
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(PolicyError):
                knowledge_directory(context)

    def test_bounded_payload_ttl_strict_boolean_and_current_https_scope(self):
        self.bind()
        for ttl in (True, 0, 91, 1.5):
            with self.assertRaises(ValueError):
                validate_knowledge("site_knowledge.save", dict(self.save_args, ttl_days=ttl), self.context)
        args = deepcopy(self.save_args)
        args["knowledge"]["routes"] *= 41
        with self.assertRaises(ValueError):
            validate_knowledge("site_knowledge.save", args, self.context)
        for url in ("http://example.com/", "about:blank", "https://user:secret@example.com/", "https://example.com:444/"):
            self.page.url = url
            with self.assertRaises(PolicyError):
                self.retrieve()

    def test_hardlinked_record_is_not_a_memory_capability(self):
        import os
        self.bind()
        self.save()
        try:
            os.link(self.record(), self.root / "record-alias.json")
        except OSError:
            self.skipTest("Hardlink creation unavailable")
        with self.assertRaises(PolicyError):
            self.retrieve()

    def test_control_page_and_foreign_browser_context_cannot_bind_knowledge(self):
        self.context["browser"].page = self.page
        with self.assertRaises(PolicyError):
            prepare_knowledge(self.bind_args, self.context, name="site_knowledge.bind")
        del self.context["browser"].page
        self.page.context = object()
        with self.assertRaises(PolicyError):
            prepare_knowledge(self.bind_args, self.context, name="site_knowledge.bind")


if __name__ == "__main__":
    unittest.main()
