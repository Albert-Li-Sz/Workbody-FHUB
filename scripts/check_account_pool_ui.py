"""Optional Firefox checks against a synthetic local gateway; needs Playwright."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("mobile_fixture", ROOT / "tests/_mobile_check.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def main():
    from playwright.sync_api import sync_playwright
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wb-account-browser-") as directory:
        fixture.FIX = directory
        fixture.PORT = fixture.free_port()
        fixture.BASE = "http://127.0.0.1:%d" % fixture.PORT
        fixture.build_fixtures()
        fixture.set_password()
        # Replace only the upstream credit fetch. All HTTP auth, JSON, HTML,
        # event delegation, realm filtering and bulk writes use shipped code.
        source = '''import time, wb_accounts, wb_proxy
def fetch(account):
    if not account.enabled:
        return {"ok": False}
    account.credits = dict(account.credits, updated_at=time.time())
    return {"ok": True, "credits": account.credits}
wb_accounts.Account.fetch_credits = fetch
wb_proxy.main()
'''
        env = dict(os.environ, ACCOUNTS_DIR=os.path.join(directory, "accounts"),
                   WB_PROXY_USAGE_DIR=os.path.join(directory, "usage"))
        proc = subprocess.Popen([sys.executable, "-c", source, "--host", "127.0.0.1",
                                 "--port", str(fixture.PORT), "--panel-password", fixture.PASSWORD],
                                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            assert fixture.wait_identity(), "synthetic gateway did not become ready"
            try:
                urllib.request.urlopen(fixture.BASE + "/accounts/balance", timeout=5)
                raise AssertionError("anonymous balance query must fail")
            except urllib.error.HTTPError as exc:
                assert exc.code == 401
            with sync_playwright() as runtime:
                browser = runtime.firefox.launch(headless=True)
                # Firefox applies CSP to Playwright's predicate compiler too.
                # This affects only the test context, never gateway headers.
                page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                fixture.login(page)
                fixture.goto_tab(page, "accounts")
                page.wait_for_selector("#accounts tbody tr")
                assert page.locator("#accounts tbody tr").count() == 3
                page.click("#accountRealmCn")
                page.wait_for_function("document.querySelector('#accounts').textContent.includes('test-user-cn')")
                assert page.locator("#accounts tbody tr").count() == 1
                assert page.locator("#accountRealmCn").get_attribute("aria-pressed") == "true"
                # Real POST must disable only cn; the intl accounts still exist.
                page.locator('[data-action="setAll"][data-arg="0"]').click()
                page.wait_for_function("window.ACCOUNTS.filter(a=>a.realm==='cn').every(a=>!a.enabled)")
                assert page.evaluate("window.ACCOUNTS.find(a=>a.nickname==='test-user-a').enabled")
                page.click("#accountRealmIntl")
                page.wait_for_function("document.querySelector('#accountRealmIntl').getAttribute('aria-pressed')==='true'")
                page.click("#btnQueryBalances")
                page.wait_for_function("!document.querySelector('#btnQueryBalances').disabled")
                result = page.evaluate("async()=>await(await fetch('/accounts/balance',{headers:authHeaders()})).json()")
                assert result["total_remain"] == 168
                assert result["by_realm"]["intl"]["total_remain"] == 126
                assert result["by_realm"]["cn"]["total_remain"] == 42
                assert page.locator("#accountBalanceTotal").inner_text() == "168"
                assert "查询失败" in page.locator("#accountBalanceStatus").inner_text()
                assert page.evaluate("window.ACTIVE_GATEWAY_REALM") == "intl"
                page.screenshot(path=str(output / "1.0.2-account-pool-desktop.png"), full_page=True)
                # Test the shipped slot editor and HTTP save, not a DOM mock.
                page.evaluate("async()=>await postJSON('/proxy/slots/save',{slots:[]})")
                fixture.goto_tab(page, "settings")
                page.locator('[data-action="addProxySlotRow"]').click()
                page.locator('[data-action="onProxySlotUrlInput"]').fill("socks5h://proxy.example:1080")
                page.locator('[data-action="onProxySlotUsernameInput"]').fill("synthetic-user")
                secret = 'p:@ /?"<&'
                password_input = page.locator('[data-action="onProxySlotPasswordInput"]')
                password_input.fill(secret)
                assert password_input.get_attribute("type") == "password"
                page.evaluate("loadProxySlots()")
                assert password_input.input_value() == secret, "polling discarded unsaved credentials"
                with page.expect_response(lambda response: response.url.endswith("/proxy/slots/save")) as saved:
                    page.locator('[data-action="saveProxySlots"]').click()
                saved_payload = saved.value.json()
                assert saved.value.status == 200
                assert saved_payload["slots"][0]["url"] == "socks5h://proxy.example:1080"
                assert saved_payload["slots"][0]["password"] == secret
                page.reload()
                fixture.goto_tab(page, "settings")
                page.wait_for_function("value=>document.querySelector('[data-action=onProxySlotPasswordInput]')?.value===value", arg=secret)
                assert page.locator('[data-action="onProxySlotUsernameInput"]').input_value() == "synthetic-user"
                page.locator("#slotList").screenshot(path=str(output / "1.0.2-proxy-slots-desktop.png"))
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.locator('[data-action="onProxySlotPasswordInput"]').is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.locator("#slotList").screenshot(path=str(output / "1.0.2-proxy-slots-mobile.png"))
                fixture.goto_tab(page, "accounts")
                page.click("#accountRealmCn")
                assert page.locator("#accountRealmCn").is_visible()
                assert page.locator("#btnQueryBalances").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(output / "1.0.2-account-pool-mobile.png"), full_page=True)
                assert not errors, errors
                browser.close()
                print(json.dumps({"anonymous_balance_status":401, "total_remain":168,
                                  "intl_remain":126, "cn_remain":42,
                                  "realm_switch":True, "bulk_scope":True, "partial_refresh":True,
                                  "proxy_credentials_save_reload":True, "proxy_password_masked":True,
                                  "desktop_width":1440, "mobile_width":390, "page_errors":errors}))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    main()
