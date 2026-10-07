"""The public health flag follows the key check used by /v1 requests."""
import os
import sys
import tempfile
import unittest
import threading
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wb_proxy as proxy
import wb_settings as settings


class RequestWithoutKey(object):
    _key_ok = proxy.Handler._key_ok

    def _panel_ok(self):
        return False

    def _supplied_key(self):
        return ""

    def _json(self, status, payload):
        return status, payload


class HealthAuthTests(unittest.TestCase):
    def test_lan_address_discovery_cannot_block_startup_on_stalled_dns(self):
        started = threading.Event()
        release = threading.Event()
        done = threading.Event()
        addresses = []

        def stalled_dns(*args):
            started.set()
            release.wait(timeout=5)
            return [(proxy.socket.AF_INET, proxy.socket.SOCK_STREAM, 6, "", ("192.168.1.5", 0))]

        def discover():
            addresses.append(proxy.local_ip_addresses())
            done.set()

        with mock.patch.object(proxy.socket, "getaddrinfo", side_effect=stalled_dns), \
                mock.patch.object(proxy.socket, "socket", side_effect=OSError("no network")):
            worker = threading.Thread(target=discover)
            try:
                worker.start()
                self.assertTrue(started.wait(timeout=1))
                finished_without_dns = done.wait(timeout=2)
            finally:
                release.set()
                worker.join(timeout=2)
        self.assertTrue(finished_without_dns, "startup must not wait for hostname DNS to finish")
        self.assertEqual(addresses, [[]])

    def test_health_follows_current_settings(self):
        with tempfile.TemporaryDirectory(prefix="health-auth-") as directory:
            with mock.patch.multiple(proxy, ACCOUNTS_DIR=directory, API_KEY=None, POOL=None):
                request = RequestWithoutKey()

                def check(required):
                    status, health = proxy.Handler._get_health(request)
                    self.assertEqual(status, 200)
                    self.assertIs(health["api_key_required"], required)
                    self.assertIs(request._key_ok(), not required)

                check(False)
                key = {"name": "panel key", "key": "panel-secret", "enabled": True}
                settings.set_api_keys(directory, [key])
                check(True)

                settings.set_api_keys(directory, [dict(key, enabled=False)])
                check(True)

                settings.set_api_keys(directory, [key])
                settings.set_auth_disabled(directory, True)
                check(False)

                settings.set_auth_disabled(directory, False)
                settings.set_api_keys(directory, [])
                proxy.API_KEY = "launcher-secret"
                check(True)


if __name__ == "__main__":
    unittest.main()
