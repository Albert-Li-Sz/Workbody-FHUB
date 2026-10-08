"""Parallel suites have private state, UTF-8 logs and bounded process trees."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wb-runner-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tests = self.root / 'tests'
        self.tests.mkdir()
        shutil.copyfile(HERE / 'run_all.py', self.tests / 'run_all.py')

    def suite(self, name, body):
        (self.tests / ('_test_' + name + '.py')).write_text(body, encoding='utf-8')

    def run_runner(self, *arguments, env=None):
        result = subprocess.run([sys.executable, str(self.tests / 'run_all.py')] + list(arguments),
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
        return result, result.stdout.decode('utf-8', 'replace')

    def test_utf8_parent_handles_legacy_console_encoding(self):
        self.suite('unicode', "print('保存完成：中文标签')\n")
        env = dict(os.environ, PYTHONIOENCODING='cp1252')
        result, output = self.run_runner('unicode', env=env)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn('保存完成：中文标签', output)
        self.assertIn('1 passed', output)

    def test_parallel_suites_have_separate_data_and_keep_full_logs(self):
        body = """import os
from pathlib import Path
for key in ('ACCOUNTS_DIR', 'WB_PROXY_USAGE_DIR', 'WB_PRICING_DIR'):
    path = Path(os.environ[key], 'private-state.json')
    assert not path.exists(), 'another suite shared my state'
    path.write_text('synthetic')
print(os.environ['ACCOUNTS_DIR'])
"""
        self.suite('a', body)
        self.suite('b', body)
        logs = self.root / 'logs'
        result, output = self.run_runner('--jobs', '2', '--logs', str(logs))
        self.assertEqual(result.returncode, 0, output)
        first = (logs / '_test_a.py.log').read_text().strip()
        second = (logs / '_test_b.py.log').read_text().strip()
        self.assertNotEqual(first, second)
        self.assertFalse(Path(first).exists(), 'suite temp data must be removed after completion')

    @unittest.skipIf(os.name == 'nt', 'POSIX process status check; Windows uses taskkill /T')
    def test_timeout_kills_descendants(self):
        pid_file = self.root / 'child.pid'
        self.suite('hang', "import subprocess,sys,time\nfrom pathlib import Path\nchild=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\nPath(%r).write_text(str(child.pid))\ntime.sleep(60)\n" % str(pid_file))
        result, output = self.run_runner('hang', '--timeout', '1')
        self.assertEqual(result.returncode, 1, output)
        self.assertIn('timed out after 1s', output)
        pid = pid_file.read_text().strip()
        check = subprocess.run(['ps', '-p', pid, '-o', 'stat='], capture_output=True, text=True)
        status = check.stdout.strip()
        self.assertTrue(not status or status.startswith('Z'), 'child still running: ' + status)

    def test_invalid_args_and_empty_filter_cannot_report_pass(self):
        self.suite('only', "print('okay')\n")
        for args in [('missing',), ('--jobs','0'), ('--timeout','nan')]:
            result, output = self.run_runner(*args)
            self.assertNotEqual(result.returncode, 0, output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
