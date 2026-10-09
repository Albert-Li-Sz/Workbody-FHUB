"""Responses snapshots survive restart, ancestor deletion and TTL cleanup."""
import json
import os
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wb_database import Database
from wb_responses import ResponseStore, ResponseError
import wb_settings


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.accounts = os.path.join(self.work.name, "accounts")
        self.db = Database(os.path.join(self.accounts, "db.sqlite3"), self.accounts, self.work.name)
        self.addCleanup(self.db.close_thread)
        self.store = ResponseStore(self.db, self.accounts)

    def turn(self, payload, owner="one", allowed=("workbuddy",)):
        body, context = self.store.prepare(payload, owner, allowed, 50 * 1024 * 1024)
        model = body.get("model") or "model"
        result = {"id": "upstream-id", "object": "response", "status": "completed", "model": model,
                  "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "remembered"}]}]}
        return body, self.store.finish(result, context, "workbuddy", "cn", model, "account")

    def test_chain_restores_full_history_but_not_prior_instructions(self):
        _, first = self.turn({"model": "model", "input": "secret context", "instructions": "first system"})
        body, second = self.turn({"previous_response_id": first["id"], "input": "follow up", "instructions": "new system"})
        self.assertEqual(body["instructions"], "new system")
        self.assertEqual([item["role"] for item in body["input"]], ["user", "assistant", "user"])
        self.assertNotIn("first system", json.dumps(body))
        self.assertEqual(second["previous_response_id"], first["id"])
        self.assertTrue(second["store"])

    def test_ancestor_delete_or_expiry_does_not_break_descendants(self):
        _, first = self.turn({"input": "start"})
        _, child = self.turn({"previous_response_id": first["id"], "input": "second"})
        self.store.delete(first["id"], "one", ["workbuddy"])
        body, _ = self.turn({"previous_response_id": child["id"], "input": "third"})
        self.assertEqual(len(body["input"]), 5)
        self.db.connection().execute("UPDATE responses SET expires_at=0 WHERE id=?", (child["id"],))
        self.store.cleanup(force=True)
        self.assertGreater(self.store.snapshot()["count"], 0)

    def test_restart_and_key_isolation_and_permission_removal(self):
        _, first = self.turn({"input": "private"})
        self.db.close_thread()
        store = ResponseStore(self.db, self.accounts)
        self.assertEqual(store.get(first["id"], "one", ["workbuddy"])["response"], first)
        for owner, allowed in (("two", ["workbuddy"]), ("one", []), (None, ["workbuddy"])):
            with self.assertRaises(ResponseError) as caught:
                store.get(first["id"], owner, allowed)
            self.assertEqual(caught.exception.status, 404)

    def test_store_false_can_read_parent_without_saving_current_turn(self):
        _, parent = self.turn({"input": "start"})
        body, result = self.turn({"previous_response_id": parent["id"], "input": "temporary", "store": False})
        self.assertEqual(len(body["input"]), 3)
        self.assertFalse(result["store"])
        with self.assertRaises(ResponseError):
            self.store.get(result["id"], "one", ["workbuddy"])
        self.assertEqual(self.store.snapshot()["count"], 1)

    def test_anonymous_responses_are_not_stored(self):
        _, response = self.turn({"input": "anonymous"}, owner=None)
        self.assertFalse(response["store"])
        self.assertEqual(self.store.snapshot()["count"], 0)

    def test_parallel_branches_do_not_mutate_parent_and_whole_chain_delete(self):
        _, parent = self.turn({"input": "root"})
        def branch(i):
            try:
                return self.turn({"previous_response_id": parent["id"], "input": str(i)})[1]
            finally:
                self.db.close_thread()
        with ThreadPoolExecutor(max_workers=4) as pool:
            children = list(pool.map(branch, range(12)))
        self.assertEqual(len({item["id"] for item in children}), 12)
        self.assertEqual(len(self.store.get(parent["id"], "one", ["workbuddy"], True)["history"]), 2)
        conv = self.store.get(parent["id"], "one", ["workbuddy"])["conversation"]
        self.assertEqual(self.store.delete_conversation(conv)["deleted"], 13)
        self.assertEqual(self.db.connection().execute("SELECT COUNT(*) FROM response_items").fetchone()[0], 0)

    def test_capacity_failure_is_atomic_and_does_not_evict_live_history(self):
        wb_settings.save(self.accounts, {"responses": {"max_mb": 1}})
        _, first = self.turn({"input": "keep"})
        with self.assertRaises(ResponseError) as caught:
            self.turn({"input": "x" * 1200000})
        self.assertEqual(caught.exception.code, "response_storage_full")
        self.assertEqual(self.store.snapshot()["count"], 1)
        self.assertEqual(self.store.get(first["id"], "one", ["workbuddy"])["response"], first)

    def test_tool_ids_and_replayable_reasoning_survive_snapshot(self):
        body, ctx = self.store.prepare({"model": "model", "input": "call"}, "one", ["workbuddy"], 100000)
        out = [{"type": "reasoning", "summary": [{"type": "summary_text", "text": "think"}]},
               {"type": "function_call", "call_id": "call-original", "name": "lookup", "arguments": "{}"}]
        response = self.store.finish({"status": "completed", "output": out}, ctx, "workbuddy", "cn", "model", "account")
        next_body, _ = self.store.prepare({"previous_response_id": response["id"],
            "input": [{"type": "function_call_output", "call_id": "call-original", "output": "found"}]}, "one", ["workbuddy"], 100000)
        self.assertEqual(next_body["input"][2]["call_id"], "call-original")
        self.assertEqual(next_body["input"][3]["call_id"], "call-original")

    def test_model_change_and_restored_size_limit_fail_explicitly(self):
        _, parent = self.turn({"model": "a", "input": "a" * 1000})
        with self.assertRaises(ResponseError):
            self.turn({"model": "b", "previous_response_id": parent["id"], "input": "next"})
        with self.assertRaises(ResponseError) as caught:
            self.store.prepare({"previous_response_id": parent["id"], "input": "next"}, "one", ["workbuddy"], 100)
        self.assertEqual(caught.exception.status, 413)

    def test_incomplete_length_is_replayable_but_failures_are_not(self):
        for status, reason, stored in (("incomplete", "max_output_tokens", True), ("incomplete", "content_filter", False), ("failed", None, False)):
            _, ctx = self.store.prepare({"input": "start"}, "one", ["workbuddy"], 100000)
            result = self.store.finish({"status": status, "incomplete_details": {"reason": reason}, "output": []}, ctx, "workbuddy", "cn", "m")
            count = self.db.connection().execute("SELECT COUNT(*) FROM responses WHERE id=?", (result["id"],)).fetchone()[0]
            self.assertEqual(bool(count), stored)


if __name__ == "__main__":
    unittest.main()
