#!/bin/sh
set -eu
UPDATE_VERSION=1.1.2
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' '需要 Python 3.9+；Debian/Ubuntu 可先安装 python3。' >&2
    exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "需要 Python 3.9+")'
if [ -f "$script_dir/update.py" ] && python3 - "$script_dir/update.py" "$UPDATE_VERSION" <<'PY'
import ast, pathlib, sys
try:
    tree = ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    version = next(ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets))
except (OSError, SyntaxError, ValueError, StopIteration):
    raise SystemExit(1)
raise SystemExit(0 if version == sys.argv[2] else 1)
PY
then
    exec python3 "$script_dir/update.py" --directory "$script_dir" "$@"
fi
# A copy downloaded into an old installation can bootstrap its matching
# updater; verify the release attachment before executing it.
if ! command -v curl >/dev/null 2>&1; then
    printf '%s\n' '需要 curl 下载发布附件，或手动将 update.py 放在 update.sh 同目录。' >&2
    exit 1
fi
update_tmp=$(mktemp -d)
trap 'rm -rf "$update_tmp"' EXIT HUP INT TERM
release_url="https://github.com/Albert-Li-Sz/Workbody-FHUB/releases/download/v$UPDATE_VERSION"
curl --fail --location --silent --show-error "$release_url/update.py" -o "$update_tmp/update.py"
curl --fail --location --silent --show-error "$release_url/checksums.txt" -o "$update_tmp/checksums.txt"
python3 - "$update_tmp" <<'PY'
import hashlib, pathlib, re, sys
root = pathlib.Path(sys.argv[1])
lines = root.joinpath("checksums.txt").read_text().splitlines()
expected = next((m[1].lower() for line in lines
                 if (m := re.fullmatch(r"([a-fA-F0-9]{64})\s+\*?update\.py", line))), None)
actual = hashlib.sha256(root.joinpath("update.py").read_bytes()).hexdigest()
if expected != actual:
    raise SystemExit("update.py 发布附件校验失败")
PY
python3 "$update_tmp/update.py" --directory "$script_dir" "$@"
