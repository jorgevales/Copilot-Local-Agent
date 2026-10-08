"""Executable headless browser fixtures; requests are fulfilled locally, never production."""
import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from copilot_agent.policy import PolicyError
from copilot_agent.web_navigation import (
    NAVIGATION_SPECS, clear_navigation_state, execute_navigation, get_navigation_page, plan_hash, validate_navigation,
)


LANDING = """<!doctype html><title>Example operations portal</title><h1>Operations portal</h1>
<nav aria-label="Main"><a data-testid="customer-search" href="/search">Customer search</a>
<a id="documents" href="/documents">Documents</a><a href="https://outside.test/">Outside</a></nav>
<a href="/statement.pdf?token=private" download>Account statement PDF</a>
<form id="lookup"><label for="query">Search customers</label><input id="query" required>
<button disabled>Unavailable</button></form><table id="accounts"><tr><th>Account</th><th>Status</th></tr><tr><td>Example</td><td>Active</td></tr></table>
<div hidden>HIDDEN PRIVATE PAGE DATA</div><textarea id="private-notes">TEXTAREA PRIVATE DATA</textarea>
<div id="shadow"></div><script>const root=document.querySelector('#shadow').attachShadow({mode:'open'});root.innerHTML='<button data-testid="shadow-button">Shadow action</button>';</script>
<iframe id="embedded" src="/frame"></iframe>"""
SEARCH = """<!doctype html><title>Customer search</title><h1>Customer lookup</h1>
<label for="customer-id">Customer ID</label><input id="customer-id">
<button onclick="document.getElementById('results').hidden=false;">Search</button>
<div hidden data-testid="results" id="results"><p>Two possible results require disambiguation</p>
<a data-testid="customer-C100" href="/profile/C100">Open customer</a>
<a data-testid="customer-C101" href="/profile/C101">Open customer</a></div>"""
PROFILE = """<!doctype html><title>Customer profile</title><h1>Customer profile</h1>
<div data-testid="customer-id">C100</div><div data-testid="status">Active</div>
<div data-testid="products">Current account</div><section aria-label="Documents"><a href="/statement.pdf">Statement PDF</a></section>
<button data-testid="save" onclick="window.effectCount=(window.effectCount||0)+1;">Save</button>
<button data-testid="read-once" onclick="window.effectCount=(window.effectCount||0)+1;">Refresh</button>
<button data-testid="pagination" onclick="window.pageCount=(window.pageCount||0)+1;if(window.pageCount===2)this.hidden=true;">Next page</button>
<div data-testid="page-content">Details</div>"""


def search_plan():
    return {"task_id": "task-1", "max_actions": 20, "timeout_seconds": 20,
            "steps": [
                {"id": "search-route", "op": "click", "locator": {"testid": "customer-search"}, "effect": "navigation",
                 "expect": [{"kind": "url", "value": "https://fixture.test/search"}]},
                {"id": "query", "op": "fill", "locator": {"label": "Customer ID"}, "value": "C100"},
                {"id": "search", "op": "click", "locator": {"role": "button", "name": "Search"}, "effect": "search",
                 "expect": [{"kind": "visible", "locator": {"testid": "results"}}]},
            ], "success": [{"kind": "visible", "locator": {"testid": "results"}}]}


class NavigationSchemaTests(unittest.TestCase):
    def test_every_registered_navigation_schema_is_strict_and_bounded(self):
        self.assertEqual({"browser.recon", "browser.route", "browser.plan", "browser.tabs", "browser.customer_summary"}, set(NAVIGATION_SPECS))
        validate_navigation("browser.plan", search_plan())
        for mutate in (
            lambda p: p["steps"][0].update(op="evaluate"),
            lambda p: p["steps"][0].pop("expect"),
            lambda p: p.update(max_actions=True),
            lambda p: p["steps"][0].update(extra="ignored"),
            lambda p: p["steps"][0].update(id="query"),
            lambda p: p.update(success=[]),
        ):
            plan = search_plan()
            mutate(plan)
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                validate_navigation("browser.plan", plan)

    def test_resume_hash_binds_all_steps_and_limits(self):
        plan = search_plan()
        approved = plan_hash(plan)
        plan["resume_token"] = "opaque-token"
        self.assertEqual(approved, plan_hash(plan))
        plan["steps"][1]["value"] = "another-identifier"
        self.assertNotEqual(approved, plan_hash(plan))

    def test_customer_and_loop_preconditions_are_required(self):
        with self.assertRaises(ValueError):
            validate_navigation("browser.customer_summary", {"task_id": "t", "customer_key": "c", "identity": [], "fields": []})
        plan = search_plan()
        plan["customer_key"] = "c"
        with self.assertRaises(ValueError):
            validate_navigation("browser.plan", plan)
        plan = search_plan()
        plan["steps"] = [{"id": "loop", "op": "loop", "condition": {"kind": "visible", "locator": {"id": "next"}}, "steps": []}]
        with self.assertRaises(ValueError):
            validate_navigation("browser.plan", plan)


class NavigationBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.launch(headless=True)
        except Exception:
            edge = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
            if not edge.is_file():
                await self.playwright.stop()
                self.skipTest("Installed Chromium or Microsoft Edge is required for real-browser fixtures")
            self.browser = await self.playwright.chromium.launch(headless=True, executable_path=str(edge))
        self.browser_context = await self.browser.new_context()
        self.fixture_hosts = {"fixture.test"}
        self.pages = {"/": LANDING, "/search": SEARCH, "/profile/C100": PROFILE,
                      "/profile/C101": PROFILE.replace("C100", "C101"), "/documents": "<h1>Documents</h1>",
                      "/frame": '<h1>Embedded content</h1><button data-testid="embedded-button">Embedded action</button>',
                      "/login": '<h1>Sign in</h1><input type="password">',
                      "/denied": '<h1>Access denied</h1>', "/captcha": '<h1>Verify you are human</h1>',
                      "/rate": '<h1>Too many requests</h1>',
                      "/spa": "<h1>Single page app</h1><button onclick=\"history.pushState({},'', '/app/profile');document.querySelector('h1').textContent='Profile';\">Open profile</button>",
                      "/slow": "<h1>Slow page</h1><div data-testid='ready' hidden>Ready</div><script>setTimeout(()=>document.querySelector('[data-testid=ready]').hidden=false,200)</script>"}

        async def route(request):
            from urllib.parse import urlsplit
            parsed = urlsplit(request.request.url)
            if parsed.hostname not in self.fixture_hosts:
                await request.abort("blockedbyclient")
                return
            await request.fulfill(status=200, content_type="text/html", body=self.pages.get(parsed.path, "<h1>Unknown fixture</h1>"))
        await self.browser_context.route("**/*", route)
        self.page = await self.browser_context.new_page()
        await self.page.goto("https://fixture.test/")
        self.adapter = SimpleNamespace(tool_page=self.page, tool_context=self.browser_context,
                                       page=None, _tool_pages=[self.page])
        async def new_tool_page():
            page = await self.browser_context.new_page()
            self.adapter._tool_pages.append(page)
            return page
        self.adapter.new_tool_page = new_tool_page
        self.context = {"browser": self.adapter, "config": {"allowed_domains": ["fixture.test"]},
                        "session_dir": Path(tempfile.mkdtemp(prefix="navigation-fixture-")), "approved": True}

    async def asyncTearDown(self):
        if hasattr(self, "browser"):
            await self.browser.close()
        await self.playwright.stop()

    async def execute(self, name, args):
        return await execute_navigation(name, args, self.context)

    async def test_lost_navigation_tab_recovers_with_fresh_open_without_credit(self):
        from copilot_agent.reconciliation import capture_baseline, recover_missing_navigation
        from copilot_agent.state import SessionState
        from copilot_agent.tools import ToolRegistry
        state = SessionState(self.context['session_dir'] / 'session')
        state.data['website_private'] = True
        state.approve_domain('fixture.test')
        self.adapter.context = self.browser_context
        self.adapter.browser = self.browser
        call = {'call_id': 'lost-tab', 'name': 'browser.open', 'version': '1.0',
                'arguments': {'url': 'https://fixture.test/documents'}}
        state.begin_call(call, reconciliation_baseline=await capture_baseline(self.adapter, call))
        state.finish_call(call['call_id'], {'ok': False, 'error': {'code': 'timeout'}})
        await self.page.close()
        self.assertEqual(['lost-tab'], recover_missing_navigation(state, self.adapter))
        self.context['session_state'] = state
        registry = ToolRegistry()
        result = await registry.execute('browser.open', {'url': 'https://fixture.test/documents'}, self.context)
        self.assertTrue(result['ok'], result)
        self.assertIsNot(self.page, self.adapter.tool_page)
        info = await registry.execute('browser.info', {}, self.context)
        self.assertTrue(info['ok'], info)
        self.assertEqual('https://fixture.test/documents', info['result']['url'])
        diagnostics = await registry.execute('browser.diagnostics', {}, self.context)
        self.assertEqual('shared_verified_context', diagnostics['result']['registration'])
        self.assertEqual('unverifiable_original_tab_missing', state.data['calls']['lost-tab']['status'])
        self.assertFalse(state.data['calls']['lost-tab']['completion_credited'])

    async def test_recon_one_snapshot_covers_routes_forms_tables_frames_shadow_and_docs(self):
        await self.page.locator("#query").fill("PRIVATE CUSTOMER INPUT")
        result = await self.execute("browser.recon", {"goal": "customer search", "max_elements": 80, "max_text_chars": 2000})
        self.assertEqual("ready", result["state"])
        self.assertEqual("https://fixture.test/", result["url"])
        self.assertEqual("Customer search", result["site_map"]["routes"][0]["label"])
        self.assertEqual("Search customers", result["forms"][0]["fields"][0]["name"])
        self.assertEqual(["Account", "Status"], result["tables"][0]["headers"])
        self.assertTrue(result["frames"][0]["same_origin"])
        self.assertEqual(1, result["shadow_roots"])
        self.assertEqual("https://fixture.test/statement.pdf", result["documents"][0]["url"])
        self.assertTrue(result["documents"][0]["query_omitted"])
        self.assertNotIn("PRIVATE CUSTOMER INPUT", str(result))
        self.assertNotIn("HIDDEN PRIVATE PAGE DATA", str(result))
        self.assertNotIn("TEXTAREA PRIVATE DATA", str(result))
        self.assertNotIn("token=private", str(result))

    async def test_observed_route_freshness_and_no_guessed_routes(self):
        self.assertEqual("recon_required", (await self.execute("browser.route", {"goal": "documents"}))["status"])
        await self.execute("browser.recon", {})
        routes = await self.execute("browser.route", {"goal": "documents"})
        self.assertEqual("observed", routes["status"])
        self.assertEqual("https://fixture.test/documents", routes["routes"][0]["url"])
        self.assertEqual("no_observed_route", (await self.execute("browser.route", {"goal": "nonexistent area"}))["status"])
        await self.page.evaluate("history.pushState({},'', '/?customer=another#documents')")
        self.assertEqual("stale", (await self.execute("browser.route", {"goal": "documents"}))["status"])
        await self.execute("browser.recon", {})
        self.adapter._navigation_state["site_maps"]["tab-1"]["expires_at"] = 0
        self.assertEqual("stale", (await self.execute("browser.route", {"goal": "documents"}))["status"])

    async def test_single_request_landing_to_customer_lookup_with_verified_search(self):
        result = await self.execute("browser.plan", search_plan())
        self.assertEqual("verified", result["status"], result)
        self.assertEqual(3, result["completed_steps"])
        self.assertTrue(all(step["verification"] == "passed" for step in result["results"]))
        self.assertEqual("C100", await self.page.get_by_label("Customer ID").input_value())

    async def test_ambiguous_customer_results_stop_without_silent_selection(self):
        plan = search_plan()
        plan["steps"].append({"id": "open-result", "op": "click", "locator": {"role": "link", "name": "Open customer"}, "effect": "navigation", "expect": [{"kind": "url", "value": "https://fixture.test/profile/C100"}]})
        result = await self.execute("browser.plan", plan)
        self.assertEqual("interrupted", result["status"])
        self.assertEqual("ambiguous_locator", result["error"]["code"])
        self.assertEqual(3, result["completed_steps"])
        self.assertIsNone(result["uncertain_step"])
        self.assertFalse(result["side_effects_uncertain"])
        self.assertEqual("https://fixture.test/search", self.page.url)

    async def test_explicit_identifier_disambiguation_and_summary_facts(self):
        plan = search_plan()
        plan["steps"].append({"id": "open-result", "op": "click", "locator": {"testid": "customer-C100"}, "effect": "navigation", "expect": [{"kind": "visible", "locator": {"testid": "customer-id"}}]})
        plan["success"] = [{"kind": "visible", "locator": {"testid": "customer-id"}}]
        result = await self.execute("browser.plan", plan)
        self.assertEqual("verified", result["status"], result)
        args = {"task_id": "task-1", "customer_key": "opaque-C100", "identity": [{"locator": {"testid": "customer-id"}, "value": "C100"}],
                "fields": [{"name": "status", "locator": {"testid": "status"}}, {"name": "unknown", "locator": {"testid": "missing"}}]}
        result = await self.execute("browser.customer_summary", args)
        self.assertEqual("partial", result["status"])
        self.assertTrue(result["identity_verified"])
        self.assertFalse(result["side_effects_uncertain"])
        self.assertEqual("Active", result["facts"][0]["value"])
        self.assertEqual("observed", result["facts"][0]["evidence"])
        self.assertEqual([], result["inferences"])
        self.assertEqual("unknown", result["missing"][0]["field"])
        wrong = copy.deepcopy(args)
        wrong["identity"][0]["value"] = "C101"
        with self.assertRaisesRegex(Exception, "did not match"):
            await self.execute("browser.customer_summary", wrong)
        wrong["customer_key"] = "opaque-C101"
        with self.assertRaises(PolicyError):
            await self.execute("browser.customer_summary", wrong)

    async def test_changed_id_falls_back_to_exact_role_without_effect_retry(self):
        plan = search_plan()
        plan["steps"][0]["locator"] = {"testid": "removed-test-id", "role": "link", "name": "Customer search"}
        result = await self.execute("browser.plan", plan)
        self.assertEqual("verified", result["status"])
        self.assertEqual("role", result["results"][0]["locator_strategy"])
        self.assertEqual(0, result["results"][0]["retry_count"])

    async def test_spa_transition_and_delayed_rendering(self):
        await self.page.goto("https://fixture.test/spa")
        plan = {"task_id": "task-1", "steps": [{"id": "spa", "op": "click", "locator": {"role": "button", "name": "Open profile"}, "effect": "navigation", "expect": [{"kind": "url", "value": "https://fixture.test/app/profile"}, {"kind": "text", "locator": {"role": "heading", "name": "Profile"}, "value": "Profile"}]}], "success": [{"kind": "url", "value": "https://fixture.test/app/profile"}]}
        self.assertEqual("verified", (await self.execute("browser.plan", plan))["status"])
        await self.page.goto("https://fixture.test/slow")
        plan = {"task_id": "task-1", "steps": [{"id": "ready", "op": "wait", "locator": {"testid": "ready"}, "timeout_ms": 2000}], "success": [{"kind": "visible", "locator": {"testid": "ready"}}]}
        self.assertEqual("verified", (await self.execute("browser.plan", plan))["status"])

    async def test_same_origin_iframe_and_shadow_controls(self):
        plan = {"task_id": "task-1", "steps": [
            {"id": "frame", "op": "capture", "locator": {"testid": "embedded-button", "frame_selector": "#embedded"}},
            {"id": "shadow", "op": "capture", "locator": {"testid": "shadow-button"}},
        ], "success": [{"kind": "visible", "locator": {"testid": "shadow-button"}}]}
        result = await self.execute("browser.plan", plan)
        self.assertEqual("verified", result["status"], result)
        self.assertEqual("Embedded action", result["results"][0]["capture"])
        self.assertEqual("Shadow action", result["results"][1]["capture"])
        await self.page.locator("#embedded").evaluate("n=>n.src='https://outside.test/frame'")
        result = await self.execute("browser.plan", plan)
        self.assertEqual("policy_denied", result["error"]["code"])

    async def test_security_boundaries_stop_and_do_not_click(self):
        for path, code in (("/login", "authentication_required"), ("/denied", "access_denied"), ("/captcha", "human_verification"), ("/rate", "rate_limited")):
            await self.page.goto("https://fixture.test"+path)
            snapshot = await self.execute("browser.recon", {})
            self.assertEqual(code, snapshot["state"])
            plan = {"task_id": "task-1", "steps": [{"id": "must-not-act", "op": "capture", "locator": {"css": "h1"}}], "success": [{"kind": "visible", "locator": {"css": "h1"}}]}
            result = await self.execute("browser.plan", plan)
            self.assertEqual(code, result["error"]["code"])
            self.assertEqual(0, result["completed_steps"])

    async def test_tabs_have_stable_contexts_caps_and_preserve_primary(self):
        result = await self.execute("browser.tabs", {"operation": "open", "url": "https://fixture.test/profile/C100", "purpose": "Customer documents", "task_id": "task-1", "customer_key": "opaque-C100"})
        tab_id = result["tab_id"]
        self.assertEqual("tab-2", tab_id)
        self.assertIs(self.page, self.adapter.tool_page)
        other = get_navigation_page(self.context, tab_id, "task-1", "opaque-C100")
        self.assertEqual("https://fixture.test/profile/C100", other.url)
        with self.assertRaises(PolicyError):
            get_navigation_page(self.context, tab_id, "task-2", "opaque-C100")
        with self.assertRaises(PolicyError):
            get_navigation_page(self.context, tab_id, "task-1", "opaque-C101")
        self.context["config"]["max_tool_tabs"] = 2
        with self.assertRaises(PolicyError):
            await self.execute("browser.tabs", {"operation": "open", "url": "https://fixture.test/documents", "purpose": "Documents", "task_id": "task-1"})
        with self.assertRaises(PolicyError):
            await self.execute("browser.tabs", {"operation": "close", "tab_id": "tab-1"})
        await self.execute("browser.tabs", {"operation": "close", "tab_id": tab_id, "task_id": "task-1", "customer_key": "opaque-C100"})
        self.assertTrue(other.is_closed())
        self.assertFalse(self.page.is_closed())

    async def test_loop_bound_and_branch_condition_execute_in_one_plan(self):
        await self.page.goto("https://fixture.test/profile/C100")
        plan = {"task_id": "task-1", "steps": [{"id": "branch", "op": "branch", "condition": {"kind": "visible", "locator": {"testid": "pagination"}}, "then": [{"id": "pages", "op": "loop", "condition": {"kind": "visible", "locator": {"testid": "pagination"}}, "max_iterations": 3, "steps": [{"id": "next", "op": "click", "locator": {"testid": "pagination"}, "effect": "navigation", "expect": [{"kind": "visible", "locator": {"testid": "page-content"}}]}]}]}], "success": [{"kind": "hidden", "locator": {"testid": "pagination"}}]}
        result = await self.execute("browser.plan", plan)
        self.assertEqual("verified", result["status"], result)
        self.assertEqual(2, await self.page.evaluate("window.pageCount"))
        await self.page.reload()
        plan["steps"][0]["then"][0]["max_iterations"] = 1
        result = await self.execute("browser.plan", plan)
        self.assertEqual("loop_limit", result["error"]["code"])
        self.assertEqual(1, await self.page.evaluate("window.pageCount"))

    async def test_failed_postcondition_preserves_partial_and_never_replays_effect(self):
        await self.page.goto("https://fixture.test/profile/C100")
        plan = {"task_id": "task-1", "steps": [{"id": "save", "op": "click", "locator": {"testid": "read-once"}, "effect": "search", "timeout_ms": 50, "expect": [{"kind": "visible", "locator": {"testid": "never-present"}}]}], "success": [{"kind": "visible", "locator": {"testid": "never-present"}}]}
        result = await self.execute("browser.plan", plan)
        self.assertEqual("verification_failed", result["error"]["code"])
        self.assertEqual("save", result["uncertain_step"])
        self.assertTrue(result["side_effects_uncertain"])
        self.assertEqual(1, await self.page.evaluate("window.effectCount"))
        plan["resume_token"] = result["resume_token"]
        with self.assertRaisesRegex(PolicyError, "Uncertain side effect"):
            await self.execute("browser.plan", plan)
        self.assertEqual(1, await self.page.evaluate("window.effectCount"))

    async def test_cancel_resume_preserves_exact_completed_steps(self):
        plan = search_plan()
        cancelled = {"enabled": True}
        self.context["cancelled"] = lambda: cancelled["enabled"] and self.page.url.endswith("/search")
        result = await self.execute("browser.plan", plan)
        # Cancellation during the transition creates an uncertain boundary and
        # must never be automatically replayed after cancellation clears.
        self.assertEqual("cancelled", result["error"]["code"])
        self.assertIsNotNone(result["uncertain_step"])
        cancelled["enabled"] = False
        plan["resume_token"] = result["resume_token"]
        with self.assertRaises(PolicyError):
            await self.execute("browser.plan", plan)

    async def test_exact_resume_after_safe_precondition_failure_does_not_repeat_completed_read(self):
        plan = {"task_id": "task-1", "steps": [{"id": "capture", "op": "capture", "locator": {"css": "h1"}}, {"id": "missing", "op": "wait", "locator": {"testid": "missing"}, "timeout_ms": 10}], "success": [{"kind": "visible", "locator": {"css": "h1"}}]}
        result = await self.execute("browser.plan", plan)
        self.assertEqual(1, result["completed_steps"])
        self.assertIsNone(result["uncertain_step"])
        changed = copy.deepcopy(plan)
        changed["resume_token"] = result["resume_token"]
        changed["steps"][1]["locator"] = {"css": "h1"}
        with self.assertRaisesRegex(PolicyError, "exact approved plan"):
            await self.execute("browser.plan", changed)
        plan["resume_token"] = result["resume_token"]
        second = await self.execute("browser.plan", plan)
        self.assertEqual(1, len(second["results"]))
        self.assertEqual("locator_unavailable", second["error"]["code"])
        await self.page.get_by_label("Search customers").fill("unapproved-change")
        with self.assertRaisesRegex(PolicyError, "Page changed"):
            await self.execute("browser.plan", plan)

    async def test_consequential_boundary_requires_exact_separate_local_grant(self):
        await self.page.goto("https://fixture.test/profile/C100")
        plan = {"task_id": "task-1", "steps": [{"id": "save", "op": "click", "locator": {"testid": "save"}, "effect": "consequential", "expect": [{"kind": "visible", "locator": {"testid": "status"}}]}], "success": [{"kind": "visible", "locator": {"testid": "status"}}]}
        result = await self.execute("browser.plan", plan)
        self.assertEqual("confirmation_required", result["error"]["code"])
        self.assertIsNone(await self.page.evaluate("window.effectCount"))
        self.context["consequential_approved_plan_hash"] = plan_hash(plan)
        result = await self.execute("browser.plan", plan)
        self.assertEqual("verified", result["status"])
        self.assertEqual(1, await self.page.evaluate("window.effectCount"))

    async def test_effects_cannot_run_without_approval_or_outside_exact_origin(self):
        self.context["approved"] = False
        with self.assertRaises(PolicyError):
            await self.execute("browser.plan", search_plan())
        self.context["approved"] = True
        self.context["config"]["allowed_domains"].append("outside.test")
        plan = {"task_id": "task-1", "steps": [{"id": "outside", "op": "navigate", "url": "https://outside.test/", "expect": [{"kind": "url", "value": "https://outside.test/"}]}], "success": [{"kind": "url", "value": "https://outside.test/"}]}
        result = await self.execute("browser.plan", plan)
        self.assertEqual("policy_denied", result["error"]["code"])
        self.assertEqual("https://fixture.test/", self.page.url)

    async def test_mislabeled_consequential_control_cannot_hide_its_local_confirmation_boundary(self):
        await self.page.goto("https://fixture.test/profile/C100")
        plan = {"task_id": "task-1", "steps": [{"id": "save", "op": "click", "locator": {"testid": "save"}, "effect": "navigation", "expect": [{"kind": "visible", "locator": {"testid": "status"}}]}], "success": [{"kind": "visible", "locator": {"testid": "status"}}]}
        result = await self.execute("browser.plan", plan)
        self.assertEqual("confirmation_required", result["error"]["code"])
        self.assertIsNone(await self.page.evaluate("window.effectCount"))

    async def test_approved_safe_reset_clears_old_task_customer_and_plans(self):
        await self.page.goto("https://fixture.test/profile/C100")
        await self.execute("browser.customer_summary", {"task_id": "old-task", "customer_key": "opaque-C100",
            "identity": [{"locator": {"testid": "customer-id"}, "value": "C100"}],
            "fields": [{"name": "status", "locator": {"testid": "status"}}]})
        await self.execute("browser.recon", {"task_id": "old-task", "customer_key": "opaque-C100"})
        secondary = await self.execute("browser.tabs", {"operation": "open", "url": "https://fixture.test/documents", "task_id": "old-task", "customer_key": "opaque-C100", "purpose": "Documents"})
        old_page = get_navigation_page(self.context, secondary["tab_id"], "old-task", "opaque-C100")
        with self.assertRaises(PolicyError):
            await self.execute("browser.plan", search_plan())
        result = await self.execute("browser.tabs", {"operation": "reset", "task_id": "task-1", "url": "https://fixture.test/"})
        self.assertEqual("reset", result["status"])
        self.assertTrue(result["prior_context_cleared"])
        self.assertTrue(old_page.is_closed())
        self.assertEqual(1, len(result["tabs"]))
        self.assertFalse(result["tabs"][0]["customer_bound"])
        self.assertEqual({}, self.adapter._navigation_state["site_maps"])
        self.assertEqual("verified", (await self.execute("browser.plan", search_plan()))["status"])

    async def test_customer_identity_rechecked_after_tab_transition(self):
        await self.page.goto("https://fixture.test/profile/C100")
        plan = {"task_id": "task-1", "customer_key": "opaque-C100", "identity": [{"locator": {"testid": "customer-id"}, "value": "C100"}],
                "steps": [{"id": "wrong-profile", "op": "open_tab", "url": "https://fixture.test/profile/C101", "purpose": "Profile",
                           "expect": [{"kind": "visible", "locator": {"testid": "customer-id"}}]},
                          {"id": "must-not-extract", "op": "capture", "locator": {"testid": "status"}}],
                "success": [{"kind": "visible", "locator": {"testid": "status"}}]}
        result = await self.execute("browser.plan", plan)
        self.assertEqual("customer_identity_mismatch", result["error"]["code"])
        self.assertEqual(0, result["completed_steps"])
        self.assertFalse(any("capture" in item for item in result["results"]))

    async def test_approved_new_website_clears_prior_origin_guard_and_keeps_tab_ids_unique(self):
        self.fixture_hosts.add("other.test")
        self.context["config"]["allowed_domains"].append("other.test")
        await self.execute("browser.recon", {})
        tab = await self.execute("browser.tabs", {"operation": "open", "task_id": "task-1", "url": "https://fixture.test/documents", "purpose": "Documents"})
        old_extra = get_navigation_page(self.context, tab["tab_id"], "task-1")
        await clear_navigation_state(self.adapter)
        self.assertTrue(old_extra.is_closed())
        self.assertIsNone(self.adapter._navigation_state)
        await self.page.goto("https://other.test/")
        result = await self.execute("browser.recon", {})
        self.assertEqual("https://other.test/", result["url"])
        new_tab = await self.execute("browser.tabs", {"operation": "open", "task_id": "new-task", "url": "https://other.test/documents", "purpose": "New documents"})
        self.assertEqual("tab-3", new_tab["tab_id"])
        self.assertIs(self.page, self.adapter.tool_page)

    async def test_async_cancellation_during_read_returns_exact_safe_checkpoint(self):
        plan = {"task_id": "task-1", "steps": [{"id": "captured", "op": "capture", "locator": {"css": "h1"}},
                {"id": "wait", "op": "wait", "locator": {"testid": "never-present"}, "timeout_ms": 5000}],
                "success": [{"kind": "visible", "locator": {"css": "h1"}}]}
        task = asyncio.create_task(self.execute("browser.plan", plan))
        deadline = asyncio.get_running_loop().time()+3
        while asyncio.get_running_loop().time() < deadline:
            state = getattr(self.adapter, "_navigation_state", None)
            if state and any(record["completed"] for record in state["plans"].values()):
                break
            await asyncio.sleep(.01)
        task.cancel()
        result = await task
        self.assertEqual("cancelled", result["status"])
        self.assertFalse(result["side_effects_uncertain"])
        self.assertEqual(1, result["completed_steps"])
        self.assertTrue(result["resume_token"])


if __name__ == "__main__":
    unittest.main()
