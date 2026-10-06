"""Private, atomic JSON storage for account credentials and API keys."""

import json
import os
import tempfile


def restrict_directory(directory):
    if os.name != "nt":
        os.chmod(directory, 0o700)


def restrict_file(path):
    if os.name != "nt":
        os.chmod(path, 0o600)


def write_private_json(path, data):
    """Create the temporary file privately, then atomically replace the target."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    restrict_directory(directory)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp",
                               dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            if os.name != "nt":
                os.fchmod(fh.fileno(), 0o600)
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path
