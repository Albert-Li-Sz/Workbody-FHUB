"""Incremental analytics maps: fold new SQL sequences, keep views bounded."""
import collections
import copy
import threading
import wb_pricing


def pricing_epoch():
    result = [wb_pricing.pricing_enabled(), wb_pricing.variant_inherit_enabled()]
    for path in (wb_pricing.policies_path(), wb_pricing.timeline_path(), wb_pricing.overrides_path()):
        result.append((path, wb_pricing._file_key(path)))
    return tuple(result)


class IncrementalViews:
    def __init__(self, limit=16):
        self.lock = threading.RLock()
        self.entries = collections.OrderedDict()
        self.limit = limit

    @staticmethod
    def empty(stat):
        return [stat(), stat(), {}, {}, {}]

    def get(self, database, realm, since, until, fold, stat):
        with self.lock:
            sequence = database.connection().execute("SELECT COALESCE(MAX(sequence),0) FROM usage_records").fetchone()[0]
            epoch = (getattr(database, "history_epoch", 0), pricing_epoch())
            key = (database, realm, since, until)
            entry = self.entries.get(key)
            if entry is not None and (entry["epoch"] != epoch or entry["sequence"] > sequence):
                entry = None
            if entry is None:
                maps = self.empty(stat)
                if since is not None or until is not None:
                    maps = self.get(database, realm, None, None, fold, stat)
                    maps[1] = stat()
                    for table in maps[2:]:
                        for item in table.values():
                            item["window"] = stat()
                            if "window_models" in item:
                                item["window_models"] = {}
                    rows = database.usage_rows(realm=realm, since=since, until=until, before_sequence=sequence)
                    fold(*maps[:4], since=since, until=until, realm=realm, key_map=maps[4], rows=rows, include_all=False)
                else:
                    rows = database.usage_rows(realm=realm, before_sequence=sequence)
                    fold(*maps[:4], realm=realm, key_map=maps[4], rows=rows)
                entry = {"maps": maps, "epoch": epoch, "sequence": sequence}
            elif entry["sequence"] < sequence:
                rows = database.usage_rows(realm=realm, after_sequence=entry["sequence"], before_sequence=sequence)
                fold(*entry["maps"][:4], since=since, until=until, realm=realm,
                     key_map=entry["maps"][4], rows=rows)
                entry["sequence"] = sequence
            self.entries[key] = entry
            self.entries.move_to_end(key)
            while len(self.entries) > self.limit:
                self.entries.popitem(last=False)
            return copy.deepcopy(entry["maps"])


class SnapshotViews:
    def __init__(self, limit=16):
        self.lock = threading.Lock()
        self.entries = collections.OrderedDict()
        self.limit = limit

    def get(self, database, realm, since, until, fold, empty):
        with self.lock:
            sequence = database.connection().execute("SELECT COALESCE(MAX(sequence),0) FROM usage_records").fetchone()[0]
            epoch = (getattr(database, "history_epoch", 0), pricing_epoch())
            key = (database, realm, since, until)
            entry = self.entries.get(key)
            if entry is None or entry["epoch"] != epoch or entry["sequence"] > sequence:
                entry = {"value": empty(), "sequence": 0, "epoch": epoch}
            rows = database.usage_rows(realm=realm, since=since, until=until,
                                       after_sequence=entry["sequence"], before_sequence=sequence)
            try:
                for row in rows:
                    fold(entry["value"], row)
            finally:
                rows.close()
            entry["sequence"] = sequence
            self.entries[key] = entry
            self.entries.move_to_end(key)
            while len(self.entries) > self.limit:
                self.entries.popitem(last=False)
            return copy.deepcopy(entry["value"])


VIEWS = IncrementalViews()
SNAPSHOTS = SnapshotViews()
