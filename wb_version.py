"""Canonical application version and checks for release artifact consistency."""
from pathlib import Path

VERSION = "1.1.3"


def verify_artifacts(root=None, tag=None):
    root = Path(root) if root else Path(__file__).resolve().parent
    if tag is not None and tag not in (VERSION, "v" + VERSION):
        raise ValueError("release tag differs from application version")
    expected = {
        "Dockerfile": 'org.opencontainers.image.version="%s"' % VERSION,
        "docker-compose.yml": "ghcr.io/albert-li-sz/workbody-fhub:" + VERSION,
        "docker-compose.direct.yml": "ghcr.io/albert-li-sz/workbody-fhub:" + VERSION,
        "deploy/nginx/Dockerfile": 'org.opencontainers.image.version="%s"' % VERSION,
        "update.py": 'VERSION = "%s"' % VERSION,
        "update.sh": "UPDATE_VERSION=" + VERSION,
        "README.md": "当前版本 **%s**" % VERSION,
    }
    for name, marker in expected.items():
        if marker not in (root / name).read_text(encoding="utf-8"):
            raise ValueError("%s differs from application version %s" % (name, VERSION))
    source = (root / "wb_proxy.py").read_text(encoding="utf-8")
    if '"version": VERSION' not in source or 'server_version = "Workbody-FHUB/" + VERSION' not in source:
        raise ValueError("runtime version must use wb_version.VERSION")
    return VERSION
