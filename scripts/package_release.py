"""Build updater-compatible public source assets from an exact Git revision."""
import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from update import EXCLUDED


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def private_path(name):
    first = PurePosixPath(name).parts[0]
    return first in EXCLUDED or first.startswith(".env.") or first in ("logs", "python", "dist")


def package(ref, output):
    if ref.startswith("-"):
        raise ValueError("invalid Git revision")
    revision = git("rev-parse", "--verify", ref + "^{commit}").decode().strip()
    version_source = git("show", revision + ":wb_version.py").decode()
    match = re.search(r'^VERSION\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"$', version_source, re.M)
    if not match:
        raise ValueError("Git revision has no stable application version")
    version = match[1]
    paths, excluded = [], []
    for entry in git("ls-tree", "-r", "-z", "--full-tree", revision).split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        name = raw_name.decode("utf-8")
        if private_path(name):
            excluded.append(name)
            continue
        mode, kind, _ = metadata.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError("source archive requires ordinary files: " + name)
        paths.append(name)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / ("workbody-fhub-%s-source.tar.gz" % version)
    with tempfile.TemporaryDirectory(prefix="workbody-package-") as directory:
        temporary = Path(directory) / archive.name
        subprocess.run(["git", "archive", "--format=tar.gz", "--prefix=Workbody-FHUB-%s/" % version,
                        "--output=" + str(temporary), revision, "--", *paths], cwd=ROOT, check=True)
        with tarfile.open(temporary) as source:
            for member in source:
                parts = PurePosixPath(member.name).parts
                if (member.name.startswith("/") or ".." in parts or "\\" in member.name
                        or ":" in member.name or not (member.isdir() or member.isfile())):
                    raise ValueError("source archive contains unsupported paths")
                if len(parts) > 1 and private_path("/".join(parts[1:])):
                    raise ValueError("source archive contains private runtime paths")
        archive.write_bytes(temporary.read_bytes())
    for name in ("update.py", "update.sh"):
        path = output / name
        path.write_bytes(git("show", revision + ":" + name))
        path.chmod(0o755)
    print("Packaged v%s from %s: %s" % (version, revision, archive))
    print("Excluded runtime paths: " + ", ".join(excluded))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="exact Git revision to package")
    parser.add_argument("--output-dir", required=True, help="directory for source and updater attachments")
    args = parser.parse_args()
    package(args.ref, Path(args.output_dir).resolve())


if __name__ == "__main__":
    main()
