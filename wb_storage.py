"""Private, atomic JSON storage for account credentials and API keys."""

import json
import os
import tempfile

import wb_database


def read_private_json(path):
    database = wb_database.DATABASE
    if database and database.document_key(path):
        return database.load_document(path)
    with open(path, encoding="utf-8") as source:
        return json.load(source)


def has_document(path):
    database = wb_database.DATABASE
    return bool(database and database.has_document(path))


def document_paths(directory):
    paths = {os.path.join(directory, name) for name in os.listdir(directory) if name.endswith(".json")}
    if wb_database.DATABASE:
        paths.update(wb_database.DATABASE.document_paths(directory))
    return sorted(paths)


def delete_private_json(path):
    if wb_database.DATABASE:
        wb_database.DATABASE.delete_document(path)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    import wb_events
    wb_events.BROKER.publish("accounts", "settings")


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
        if wb_database.DATABASE:
            wb_database.DATABASE.save_document(path, data)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    import wb_events
    name = os.path.basename(path)
    if name == "settings.json":
        wb_events.BROKER.publish("settings", "scheduler")
    elif name == "pricing-overrides.json":
        wb_events.BROKER.publish("models", "usage")
    else:
        wb_events.BROKER.publish("accounts")
    return path
