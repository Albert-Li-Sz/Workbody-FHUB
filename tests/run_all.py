"""Run every bundled suite and print one line per file.

    python tests/run_all.py                  # everything
    python tests/run_all.py realm            # only suites whose name contains "realm"
    python tests/run_all.py --jobs 1         # one suite at a time (default: min(4, cpus))
    python tests/run_all.py --timeout 300    # per-suite wall clock, seconds
    python tests/run_all.py --logs DIR       # keep every suite's full output in DIR

Python suites run under the current interpreter; the JS suites need `node` on
PATH and are reported as skipped when it is missing. `_mobile_check.py` is not
part of this set: it drives the dashboard with Playwright/Firefox and is run by
hand.

Each suite's output goes to a file rather than a pipe, so a suite that spawns the
gateway still sees a normal console.

Two things the runner is responsible for, because a suite cannot be:

  - bounding a suite. Several of them start the gateway and wait on it; a hang
    used to hold the whole job until its own timeout, so every suite now has a
    wall clock and is killed - together with anything it started - when it runs
    out.
  - saying what went wrong. The last line of a crashed JS suite is a bare
    "Node.js v20.20.2", so a failure line carries the first error instead, and
    `--logs` keeps every suite's full output for the CI artifact.
"""
import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TAIL_LINES = 25
DEFAULT_TIMEOUT = float(os.environ.get("WB_TEST_TIMEOUT_SECONDS", "180"))
if not 0 < DEFAULT_TIMEOUT < float("inf"):
    raise ValueError("WB_TEST_TIMEOUT_SECONDS must be a positive finite number")

# The first line that looks like the reason the suite stopped. A traceback's
# last line is the actual exception, so both ends of the log are candidates.
ERROR_HINTS = re.compile(
    r"(Traceback \(most recent call last\)"
    r"|^\s*[\w.]*(Error|Exception)\b"
    r"|^\s*(FAILED|AssertionError)"
    r"|is not a function"
    r"|Cannot read|Cannot find|not defined"
    r"|timed out)", re.I)


def _force_utf8_output():
    """Make this process's stdout/stderr survive non-ASCII suite summaries.

    The suites are run with PYTHONIOENCODING=utf-8 so a child can print its
    Chinese labels, and their output is read back from a utf-8 log file. This
    process then re-prints those same lines, and on the Windows CI runner its
    own stdout is cp1252 - so the very first Chinese summary line aborted the
    whole run with UnicodeEncodeError, after the suites themselves had passed.
    Reconfiguring here keeps the two halves consistent; errors="replace" means
    an exotic code point degrades to '?' instead of killing the run.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_force_utf8_output()


def suites(pattern):
    names = sorted(n for n in os.listdir(HERE)
                   if n.startswith("_test_") and n.endswith((".py", ".js")))
    return [n for n in names if pattern in n]


def command(name):
    path = os.path.join(HERE, name)
    if name.endswith(".js"):
        return ["node", path]
    return [sys.executable, path]


def read_lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return [line.rstrip() for line in fh if line.strip()]
    except OSError:
        return []


def first_error(lines):
    """The most useful single line from a failed suite's output.

    A Python suite ends with its exception; a JS suite that dies during load ends
    with "Node.js v20.20.2" and the reason is a dozen lines above. Prefer the
    last line that looks like an error, fall back to the last line at all.
    """
    for line in reversed(lines):
        if ERROR_HINTS.search(line):
            return line.strip()
    return (lines[-1].strip() if lines else "")


def start_kwargs():
    """Put the suite in its own process group, so its tree can be killed."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(proc):
    """Kill a suite and everything it started.

    Killing only the direct child leaves its grandchildren behind: the suites
    that start wb_proxy.py would leave a gateway holding a port, and the next
    suite would inherit a machine that is not in the state the first one saw.
    """
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            done = subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=30)
            if done.returncode != 0:
                # taskkill refused (a locked-down host, or the pid is gone).
                proc.kill()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        print("        warning: %s survived the kill" % proc.pid)


def run_one(name, env, timeout, logs_dir):
    """Run one suite; return everything the caller needs to report it."""
    started = time.time()
    sandbox = tempfile.TemporaryDirectory(prefix="wb-suite-")
    env = dict(env)
    for key in ("WB_PRICING_FILE", "API_KEY", "WB_PROXY_KEY", "PANEL_PASSWORD", "PANEL_PASSWORD_FILE"):
        env.pop(key, None)
    for key, subdir in (("ACCOUNTS_DIR", "accounts"), ("WB_PROXY_USAGE_DIR", "usage"), ("WB_PRICING_DIR", "pricing")):
        env[key] = os.path.join(sandbox.name, subdir)
        os.makedirs(env[key], exist_ok=True)
    env["WB_SQLITE_PATH"] = os.path.join(env["ACCOUNTS_DIR"], "workbody.sqlite3")
    handle, log_path = tempfile.mkstemp(suffix=".log", prefix=name + ".")
    os.close(handle)
    timed_out = False
    try:
        with open(log_path, "w", encoding="utf-8") as sink:
            proc = subprocess.Popen(command(name), cwd=ROOT, env=env,
                                    stdout=sink, stderr=subprocess.STDOUT,
                                    **start_kwargs())
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                kill_tree(proc)
                code = -1
        lines = read_lines(log_path)
        kept = None
        if logs_dir:
            kept = os.path.join(logs_dir, name + ".log")
            try:
                shutil.copyfile(log_path, kept)
            except OSError:
                kept = None
        return {
            "name": name,
            "ok": code == 0,
            "code": code,
            "seconds": time.time() - started,
            "timed_out": timed_out,
            "last": (lines[-1].strip() if lines else "")[:90],
            "error": first_error(lines),
            "tail": lines[-TAIL_LINES:],
            "log": kept,
        }
    finally:
        sandbox.cleanup()
        try:
            os.unlink(log_path)
        except OSError:
            pass


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="run_all.py",
        description="Run every bundled suite and print one line per file.")
    parser.add_argument("pattern", nargs="?", default="",
                        help="only run suites whose name contains this")
    parser.add_argument("--jobs", type=int, default=None, metavar="N",
                        help="suites to run at once (default: min(4, cpus))")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        metavar="SEC",
                        help="per-suite wall clock (default: %(default)s)")
    parser.add_argument("--logs", metavar="DIR", default=None,
                        help="keep every suite's full output in DIR")
    args = parser.parse_args(argv[1:])
    if not 0 < args.timeout < float("inf"):
        parser.error("--timeout must be a positive number of seconds")
    if args.jobs is not None and args.jobs <= 0:
        parser.error("--jobs must be a positive number of suites")
    if args.jobs is None:
        args.jobs = min(4, os.cpu_count() or 1)
    return args


def main(argv):
    args = parse_args(argv)
    pattern = args.pattern
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [ROOT] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    # A suite may print non-ASCII (Chinese labels are common here). The child
    # writes straight into a utf-8 log file, so its own stdout encoding has to
    # be utf-8 too - on the CI Windows runner the locale is cp1252 and a
    # Chinese label would otherwise abort the suite with UnicodeEncodeError.
    env["PYTHONIOENCODING"] = "utf-8"
    have_node = shutil.which("node") is not None

    selected = suites(pattern)
    if not selected:
        # A typo in the filter, or every suite deleted/renamed, would otherwise
        # report "0 passed, 0 failed" and exit 0 - the one result CI must never
        # treat as a pass.
        print("  no suite matches %r in %s" % (pattern, HERE))
        return 2

    logs_dir = args.logs
    if logs_dir:
        try:
            os.makedirs(logs_dir, exist_ok=True)
        except OSError as exc:
            print("  cannot create %s: %s" % (logs_dir, exc))
            return 2

    passed, failed, skipped, durations = [], [], [], []
    todo = []
    for name in selected:
        if name.endswith(".js") and not have_node:
            skipped.append(name)
            print("  [skip] %-38s node is not on PATH" % name)
        else:
            todo.append(name)

    def report(item):
        """One line per suite, plus where to read more when it failed."""
        name = item["name"]
        durations.append((item["seconds"], name))
        if item["ok"]:
            passed.append(name)
            summary = item["last"]
        else:
            failed.append(name)
            summary = item["error"] or item["last"]
            if item["timed_out"]:
                summary = "timed out after %gs" % args.timeout
        print("  [%s] %-38s %-52s %5.1fs"
              % ("PASS" if item["ok"] else "FAIL", name, summary[:52], item["seconds"]))
        if not item["ok"]:
            if item["log"]:
                print("        full output: %s" % item["log"])
            else:
                print("        --- last %d lines of %s ---" % (TAIL_LINES, name))
                for line in item["tail"]:
                    print("        " + line)

    started = time.time()
    if args.jobs > 1:
        # The suites are separate processes and were made independent of each
        # other first (own temp dirs, spare ports), so they can overlap. Reported
        # as they finish: a run that takes a minute should not go quiet.
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(run_one, name, env, args.timeout, logs_dir)
                       for name in todo]
            for future in as_completed(futures):
                report(future.result())
    else:
        for name in todo:
            report(run_one(name, env, args.timeout, logs_dir))
    total = time.time() - started

    print("")
    if durations:
        slowest = sorted(durations, reverse=True)[:3]
        print("  slowest: %s"
              % ", ".join("%s %.1fs" % (name, secs) for secs, name in slowest))
    print("  %d passed, %d failed, %d skipped  (%s)"
          % (len(passed), len(failed), len(skipped), ROOT))
    print("  total %.1fs with --jobs %d" % (total, args.jobs))
    if failed:
        print("  failed: %s" % ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
