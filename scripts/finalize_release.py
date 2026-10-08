"""Publish one complete checksum manifest after image verification receipts exist."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


def finalize(tag):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("invalid release tag")
    with tempfile.TemporaryDirectory(prefix="workbody-release-assets-") as temporary:
        root = Path(temporary)
        subprocess.run(["gh", "release", "download", tag, "--dir", str(root), "--clobber"], check=True)
        required = {"images.json", "app-verification.json", "nginx-verification.json",
                    "workbody-fhub-%s-source.tar.gz" % tag[1:], "update.py", "update.sh"}
        missing = required - {p.name for p in root.iterdir()}
        if missing:
            raise ValueError("release assets incomplete: " + ", ".join(sorted(missing)))
        receipt = json.loads((root / "images.json").read_text())
        if receipt.get("tag") != tag:
            raise ValueError("image receipt differs from release tag")
        for name in ("app", "nginx"):
            verified = json.loads((root / (name + "-verification.json")).read_text())
            if set(verified.get("platforms", {})) != {"linux/amd64", "linux/arm64"}:
                raise ValueError(name + " image has no complete architecture verification")
            if verified.get("source") != receipt.get("commit"):
                raise ValueError(name + " verification belongs to a different source commit")
            expected_image = receipt["images"][name.upper()]["image"] + ":" + tag
            if verified.get("image") != expected_image:
                raise ValueError(name + " verification belongs to a different image tag")
        manifest = "".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n"
                           for path in sorted(root.iterdir()) if path.is_file() and path.name != "checksums.txt")
        (root / "checksums.txt").write_text(manifest, encoding="utf-8")
        subprocess.run(["gh", "release", "upload", tag, str(root / "checksums.txt"), "--clobber"], check=True)
        print("Published checksums for %d verified release assets." % len(manifest.splitlines()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    finalize(parser.parse_args().tag)
