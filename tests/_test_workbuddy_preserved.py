"""v1.2.1 WorkBuddy preservation contract for additional account sources."""
import hashlib
import pathlib
import re
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
EXPECTED={'dashboard_static/core.js': '117f86c4a27753cc6f1b4ef0174512e310f96de209447b4f79bdf6545b341bef', 'dashboard_static/accounts.js': 'b31a8f9b7cc487469e0752d3f6256a6585e477992051b141200f672fd48af061', 'wb_accounts.py': 'a50f6863f29b2fe75e37baadaaa724bf587e4147fd9ace295964e49bb08e5d41'}
class PreservationTests(unittest.TestCase):
    def test_original_workbuddy_code_is_preserved(self):
        for path,digest in EXPECTED.items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)

    def test_original_account_controls_and_oauth_dom_are_preserved(self):
        html=(ROOT/'dashboard.html').read_text()
        start=html.index('  <section>',html.index('<div id="workbuddyAccountsPanel">'))
        end=html.index('\n  </section>',start)+len('\n  </section>')
        self.assertEqual(hashlib.sha256(html[start:end].encode()).hexdigest(),'914c1674c44763c53fa9db58997faa3b3bb5e7ec42795bd5186b00618fbf76f3')
        start=html.index('<div class="modal-mask" id="loginModal">')
        end=html.index('<div class="modal-mask source-modal"',start)
        self.assertEqual(hashlib.sha256(html[start:end].strip().encode()).hexdigest(),'60b54a7cae9f12bc228f2395e726bf69ccf421411b72e3271f5d2097e1e99f80')
        self.assertNotIn('id="pagePlatforms"',html)
        self.assertNotIn('id="btnNavPlatforms"',html)
        ids=re.findall(r'\bid="([^"]+)"',html)
        self.assertEqual(len(ids),len(set(ids)), 'DOM ids must be unique')

if __name__=='__main__': unittest.main()
