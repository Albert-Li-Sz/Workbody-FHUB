"""A new shell updater must never silently reuse the previous Python updater."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wb_version import VERSION


@unittest.skipIf(os.name == "nt" or not shutil.which("sh"), "POSIX bootstrap script")
class BootstrapTests(unittest.TestCase):
    def run_bootstrap(self, local_version, valid_checksum=True):
        with tempfile.TemporaryDirectory(prefix="wb-updater-bootstrap-") as temporary:
            directory = Path(temporary)
            installation = directory / "installation with spaces"
            installation.mkdir()
            shutil.copyfile(ROOT / "update.sh", installation / "update.sh")
            marker = 'import json, sys\nprint(json.dumps({"version": VERSION, "args": sys.argv[1:]}))\n'
            current = ('VERSION = "%s"\n' % VERSION + marker).encode()
            local = ('VERSION = "%s"\n' % local_version + marker).encode() if local_version else None
            if local:
                (installation / "update.py").write_bytes(local)
            fixture = directory / "fixture.py"
            fixture.write_bytes(current)
            checksum = hashlib.sha256(current).hexdigest() if valid_checksum else "0" * 64
            checksums = directory / "checksums.txt"
            checksums.write_text(checksum + "  update.py\n")
            downloads = directory / "downloads.txt"
            binaries = directory / "bin"
            binaries.mkdir()
            curl = binaries / "curl"
            curl.write_text('#!' + sys.executable + '\n' + '''import os, pathlib, sys
args = sys.argv[1:]
url = next(a for a in args if a.startswith("https://"))
target = pathlib.Path(args[args.index("-o") + 1])
with open(os.environ["WB_FIXTURE_DOWNLOADS"], "a") as log:
    log.write(url + "\\n")
source = os.environ["WB_FIXTURE_CHECKSUMS"] if url.endswith("checksums.txt") else os.environ["WB_FIXTURE_UPDATER"]
target.write_bytes(pathlib.Path(source).read_bytes())
''')
            curl.chmod(0o755)
            environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                               WB_FIXTURE_DOWNLOADS=str(downloads), WB_FIXTURE_CHECKSUMS=str(checksums),
                               WB_FIXTURE_UPDATER=str(fixture))
            result = subprocess.run(["sh", str(installation / "update.sh"), "--source-only", "--dry-run"],
                                    env=environment, text=True, capture_output=True, timeout=15)
            requests = downloads.read_text().splitlines() if downloads.exists() else []
            self.assertEqual((installation / "update.py").read_bytes() if local else None, local)
            return result, requests, str(installation)

    def test_matching_local_updater_runs_without_a_download(self):
        result, requests, installation = self.run_bootstrap(VERSION)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(requests, [])
        self.assertEqual(json.loads(result.stdout), {"version": VERSION,
                         "args": ["--directory", installation, "--source-only", "--dry-run"]})

    def test_old_or_missing_local_updater_downloads_verified_matching_version(self):
        for local_version in ("1.1.0", None):
            result, requests, installation = self.run_bootstrap(local_version)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(requests), 2)
            self.assertTrue(all("/v%s/" % VERSION in url for url in requests))
            self.assertEqual(json.loads(result.stdout), {"version": VERSION,
                             "args": ["--directory", installation, "--source-only", "--dry-run"]})

    def test_invalid_checksum_stops_before_running_the_downloaded_updater(self):
        result, requests, _ = self.run_bootstrap("1.1.0", valid_checksum=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("发布附件校验失败", result.stderr)
        self.assertEqual(len(requests), 2)


if __name__ == "__main__":
    unittest.main()
