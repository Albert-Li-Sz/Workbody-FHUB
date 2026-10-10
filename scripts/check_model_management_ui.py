"""Browser acceptance of model policies and independent configuration pages."""
import json
import sys
import threading
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import wb_events
import wb_proxy as P
import wb_settings as S
import _test_model_policy as fixture


def main():
    from playwright.sync_api import sync_playwright
    scenario = fixture.HTTPTests("test_management_auth_and_both_public_ids")
    scenario.setUp()
    try:
        S.set_panel_password(P.ACCOUNTS_DIR, "synthetic-ui-password")
        models = {"provider/model-%03d" % index: {"native_protocol": "chat", "billing_mode": "free",
            "context_length": 100000, "max_output_tokens": 32000, "reasoning_efforts": ["low", "high"]}
            for index in range(121)}
        scenario.manager.catalogues["cline"] = {"models": models, "updated_at": time.time()}
        def refresh(upstream, force=False):
            if not force:
                return
            scenario.manager.refreshing.add(upstream)
            def done():
                scenario.manager.catalogues[upstream]["updated_at"] = time.time()
                scenario.manager.refreshing.discard(upstream)
                wb_events.BROKER.publish("models", "accounts")
            threading.Timer(0.25, done).start()
        scenario.manager.refresh_async = refresh
        base = "http://127.0.0.1:%d" % scenario.server.server_address[1]
        output = ROOT / "dist" / "model-management-ui"
        output.mkdir(parents=True, exist_ok=True)
        workbuddy = [("wb-model-%03d" % index, {"name": "Fixture", "credits": "x0.50", "maxInputTokens": 100000,
            "maxOutputTokens": 32000, "supportsReasoning": True}) for index in range(121)]
        with mock.patch.object(P, "fetch_models", return_value=workbuddy), sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, permissions=["clipboard-read", "clipboard-write"], bypass_csp=True)
            page = context.new_page()
            errors, requests = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: requests.append(request.url))
            page.goto(base + "/?tab=models")
            page.locator("#panelPwdInput").fill("synthetic-ui-password")
            page.locator('[data-action="submitPanelLogin"]').click()
            page.wait_for_selector("#modelsTable tbody tr .model-copy")
            for channel in ("workbuddy-cn", "workbuddy-intl", "cline", "opencode_zen", "commandcode"):
                page.locator("#modelChannelSelect").select_option(channel)
                page.wait_for_function("!modelLibraryLoading")
            page.locator("#modelChannelSelect").select_option("cline")
            page.wait_for_function("MODELS_DATA.length === 121")
            page.locator("#modelLibrarySearch").fill("provider/model")
            page.locator("#modelLibraryNext").click()
            assert page.locator("#modelLibraryPager").inner_text().startswith("2 / 3")
            page.evaluate("window.scrollTo(0,900)")
            before = page.evaluate("({scroll:window.scrollY,table:document.querySelector('#modelsTable tbody').innerHTML})")
            request_count = sum("/settings/models?" in url for url in requests)
            page.evaluate("queuePanelRefresh(['models','accounts','platforms'])")
            page.wait_for_timeout(1000)
            after = page.evaluate("({scroll:window.scrollY,table:document.querySelector('#modelsTable tbody').innerHTML})")
            assert before == after, "SSE replaced a table or moved the scroll position"
            assert sum("/settings/models?" in url for url in requests) == request_count
            page.evaluate("refreshModelLibrary()")
            page.wait_for_function("!document.querySelector('#modelRefreshButton').disabled")
            assert page.locator("#modelLibraryPager").inner_text().startswith("2 / 3")
            assert abs(page.evaluate("window.scrollY") - before["scroll"]) <= 1
            row = page.locator("#modelsTable tbody tr").first
            row.locator('[data-action="editModelAlias"]').fill("friendly")
            row.locator('[data-action="saveModelAlias"]').click()
            page.wait_for_selector('.model-copy[data-arg="cline/friendly"]')
            page.locator('.model-copy[data-arg="cline/friendly"]').click()
            assert page.evaluate("navigator.clipboard.readText()") == "cline/friendly"
            canonical = row.locator(".model-copy").first.get_attribute("data-arg")
            row.locator(".model-copy").first.click()
            assert page.evaluate("navigator.clipboard.readText()") == canonical
            row.locator('[data-action="toggleModelEnabled"]').uncheck()
            page.wait_for_function("modelId => MODELS_DATA.find(m=>m.id===modelId).enabled===false", arg=canonical)
            assert page.locator("#modelsTable tbody tr").count() == 50
            # A panel session does not grant an external platform API key.
            # Verify the public list with the synthetic client key instead.
            public = page.evaluate("async()=>await(await fetch('/v1/models?upstream=cline',{headers:{Authorization:'Bearer synthetic-client'}})).json()")
            assert canonical not in [model["id"] for model in public["data"]]
            row.locator('[data-action="toggleModelEnabled"]').check()
            page.wait_for_function("modelId => MODELS_DATA.find(m=>m.id===modelId).enabled===true", arg=canonical)
            page.evaluate("window.scrollTo(0,0)")
            page.screenshot(path=str(output / "models-desktop.png"), full_page=False)
            for tab, selector in (("keys", "#keyList"), ("proxies", "#slotList"), ("behavior", "#setLocalWebTools")):
                page.locator("#btnNav" + tab.capitalize()).click()
                assert page.locator("#page" + tab.capitalize()).is_visible()
                assert page.locator(selector).is_visible()
                page.reload()
                page.wait_for_selector("#page" + tab.capitalize() + ".active")
            page.goto(base + "/?tab=settings#settings-slots")
            page.wait_for_selector("#pageProxies.active")
            page.locator('[data-action="addProxySlotRow"]').click()
            page.locator('[data-action="onProxySlotUrlInput"]').last.fill("http://127.0.0.1:18080")
            page.locator('[data-action="saveProxySlots"]').click()
            page.wait_for_function("PROXY_SLOTS.some(slot=>slot.url==='http://127.0.0.1:18080')")
            page.locator("#btnNavBehavior").click()
            page.locator("#setLocalWebTools").check()
            with page.expect_response(lambda response: response.url.endswith("/settings/save")) as saved:
                page.locator('[data-action="saveLocalWebTools"]').click()
            assert saved.value.status == 200
            page.locator("#btnNavKeys").click()
            page.locator('[data-action="addApiKeyRow"]').click()
            page.locator('[id^="editKeyName_"]').fill("UI saved key")
            page.locator('[id^="editKeyValue_"]').fill("synthetic-ui-created-key")
            with page.expect_response(lambda response: response.url.endswith("/settings/save")) as saved:
                page.locator('[data-action="saveSingleKey"]').click()
            assert saved.value.status == 200
            page.wait_for_function("API_KEY_ROWS.some(row=>row.name==='UI saved key'&&row.id&&!row._editing)")
            page.reload()
            page.wait_for_function("API_KEY_ROWS.some(row=>row.name==='UI saved key'&&row.id)")
            context.close()
            mobile = browser.new_context(viewport={"width": 390, "height": 844}, bypass_csp=True)
            page = mobile.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/?tab=models")
            page.locator("#panelPwdInput").fill("synthetic-ui-password")
            page.locator('[data-action="submitPanelLogin"]').click()
            page.wait_for_selector("#modelChannelSelect")
            page.locator("#modelChannelSelect").select_option("cline")
            page.wait_for_function("MODELS_DATA.length === 121")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "model page overflows phone width"
            page.screenshot(path=str(output / "models-mobile.png"), full_page=False)
            for tab in ("keys", "proxies", "behavior"):
                page.locator('[data-action="toggleSidebar"]').click()
                assert page.evaluate("document.querySelector('.main-nav').getBoundingClientRect().top < document.querySelector('.workspace-sidebar-footer').getBoundingClientRect().top"), "mobile navigation appears below the footer"
                page.locator("#btnNav" + tab.capitalize()).click()
                page.wait_for_selector("#page" + tab.capitalize() + ".active")
                page.wait_for_function("!document.body.classList.contains('sidebar-open')")
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), tab + " page overflows phone width"
                page.screenshot(path=str(output / (tab + "-mobile.png")), full_page=False, animations="disabled")
            assert not errors, errors
            browser.close()
        print(json.dumps({"passed": True, "checks": ["five channels", "SSE scroll and table stability", "manual completion", "paging",
            "save alias", "copy both IDs", "disable and enable", "independent pages", "direct URL and legacy anchor",
            "API Key, proxy and behavior save", "all configuration pages on mobile", "mobile model layout", "no JavaScript errors"], "screenshots": str(output)}, ensure_ascii=False))
    finally:
        scenario.doCleanups()


if __name__ == "__main__":
    main()
