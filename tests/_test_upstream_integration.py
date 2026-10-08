"""Selected upstream v1.6.17 fixes adapted to FHUB's persistence and fairness."""
import base64
from collections import Counter
import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_STARTUP = tempfile.TemporaryDirectory(prefix='wb-upstream-startup-')
os.environ['ACCOUNTS_DIR'] = _STARTUP.name
os.environ['WB_PROXY_USAGE_DIR'] = _STARTUP.name
import wb_accounts as A
import wb_database as D
import wb_pricing as R
import wb_proxy as P
import wb_settings as S
import wb_usage_views as V


def account(uid, days=None, realm='cn', priority=100):
    a = A.Account({'uid': uid, 'accessToken': 'synthetic-' + uid, 'realm': realm, 'priority': priority})
    a.ready = mock.Mock(return_value=True)
    a.free_models = {'free-model'}
    a.credits = {'remain': 100, 'size': 100, 'used': 0, 'updated_at': time.time(), 'packages': []}
    if days is not None:
        a.credits['packages'] = [{'remain': 100, 'expire_at': time.time() + days * 86400, 'no_expiry': False}]
    a.expiring_window_days = 7
    return a


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wb-upstream-integration-')
        self.addCleanup(self.temp.cleanup)
        self.directory = self.temp.name
        for module, field, value in ((P, 'ACCOUNTS_DIR', self.directory), (P, 'POOL', None),
                                     (P, 'PRICING', None), (D, 'DATABASE', None),
                                     (R, '_settings_dir_override', self.directory),
                                     (R, '_data_dir_override', self.directory)):
            patch = mock.patch.object(module, field, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.pool = A.AccountPool(self.directory)
        self.addCleanup(self.pool.stop_background)
        R._enabled_cache['key'] = None
        R._variant_cache['key'] = None

    def test_inline_system_and_developer_keep_their_position(self):
        body = {'model': 'deepseek-v4.1-flash', 'system': 'initial', 'messages': [
            {'role': 'user', 'content': 'first'},
            {'role': 'assistant', 'content': 'answer'},
            {'role': 'system', 'content': [{'type': 'text', 'text': 'new policy'}]},
            {'role': 'developer', 'content': 'specific instruction'},
            {'role': 'user', 'content': 'next'}]}
        messages = P.messages_to_chat(body)['messages']
        self.assertEqual([x['role'] for x in messages], ['system', 'user', 'assistant', 'system', 'system', 'user'])
        self.assertEqual([x['content'] for x in messages][3:5], ['new policy', 'specific instruction'])
        body['messages'][2]['role'] = 'tool'
        with self.assertRaisesRegex(ValueError, 'messages\\[2\\].role'):
            P.messages_to_chat(body)

    def test_partial_reasoning_never_erases_selectable_efforts(self):
        base = {'supportedEfforts': ['low', 'high', 'max'], 'defaultEffort': 'high', 'extra': 'kept'}
        self.assertEqual(P.merge_reasoning(base, {'defaultEffort': 'low'})['supportedEfforts'], base['supportedEfforts'])
        merged = P.merge_reasoning(base, {'effort': 'max'})
        self.assertNotIn('effort', merged)
        self.assertEqual(merged['supportedEfforts'], base['supportedEfforts'])
        self.assertEqual(P.merge_reasoning(base, {'supportedEfforts': ['medium']})['supportedEfforts'], ['medium'])
        self.assertEqual(base['defaultEffort'], 'high', 'merge must not mutate the bundled entry')

    def test_regional_limits_migrate_and_keep_zero_distinct_from_inherit(self):
        S.save(self.directory, {'daily_token_limit': 4000, 'vendor_extension': {'safe': True}})
        self.assertEqual(S.daily_token_limit(self.directory, 'cn'), 4000)
        S.set_limits(self.directory, {'daily_token_limit': {'cn': 0, 'intl': 9000}})
        self.assertEqual(S.daily_token_limit(self.directory, 'cn'), 0)
        self.assertEqual(S.daily_token_limit(self.directory, 'intl'), 9000)
        S.set_daily_token_limit(self.directory, 5000)
        self.assertEqual(S.daily_token_limit(self.directory, 'intl'), 9000)
        S.set_limits(self.directory, {'daily_token_limit': {'cn': None}})
        self.assertEqual(S.daily_token_limit(self.directory, 'cn'), 5000)
        self.assertEqual(S.load(self.directory)['vendor_extension'], {'safe': True})
        for value in (True, -1, 1.5, float('nan'), float('inf'), None):
            before = S.load(self.directory)
            with self.assertRaises(ValueError):
                S.set_limits(self.directory, {'daily_token_limit': {'global': value}})
            self.assertEqual(S.load(self.directory), before)

    def test_regional_limits_reach_every_account_guard(self):
        cn, intl = account('cn'), account('intl', realm='intl')
        self.pool.accounts = [cn, intl]
        for key, apply in [('reserve_credits', self.pool.apply_reserve_credits),
                           ('daily_token_limit', self.pool.apply_daily_token_limit),
                           ('daily_credit_limit', self.pool.apply_daily_credit_limit),
                           ('model_daily_token_limit', self.pool.apply_model_daily_token_limit)]:
            S.set_limits(self.directory, {key: {'global': 100, 'cn': 300, 'intl': 0}})
            apply()
            self.assertEqual(getattr(cn, key), 300)
            self.assertEqual(getattr(intl, key), 0)
        S.set_limits(self.directory, {'expiring_window_days': {'global': 7, 'intl': 0}})
        self.pool.apply_expiring_window()
        self.assertEqual(cn.expiring_window_days, 7)
        self.assertEqual(intl.expiring_window_days, 0)

    def test_expiry_defaults_off_and_free_window_is_preserved(self):
        self.assertEqual(S.expiring_window_days(self.directory), 0)
        self.assertEqual(S.pool_config(self.directory)['free_switch_window_tokens'], 262144)
        self.assertEqual(S.credits_refresh_hours(self.directory), 0.5)
        for value in (float('inf'), -1, 73, True):
            with self.assertRaises(ValueError):
                S.set_credits_refresh_hours(self.directory, value)

    def test_paid_expiry_selection_stays_inside_manual_priority(self):
        preferred, soon = account('preferred', days=30, priority=0), account('soon', days=1, priority=100)
        self.pool.accounts = [preferred, soon]
        self.assertIs(self.pool.pick(realm='cn', model='paid-model'), preferred)
        preferred.ready.return_value = False
        self.assertIs(self.pool.pick(realm='cn', model='paid-model'), soon)

    def test_paid_expiry_weights_exclude_long_lived_and_other_realms(self):
        soon, later, plain = account('soon', 1), account('later', 6), account('plain', 40)
        foreign = account('foreign', 0.5, realm='intl')
        self.pool.accounts = [soon, later, plain, foreign]
        picked = Counter(self.pool.pick(realm='cn', model='paid-model').uid for _ in range(90))
        self.assertEqual(set(picked), {'soon', 'later'})
        self.assertGreater(picked['soon'], picked['later'] * 2)
        self.assertIs(self.pool.pick(realm='intl', model='paid-model'), foreign)

    def test_expiry_does_not_override_free_fairness_or_bound_session(self):
        soon, plain = account('soon', 1), account('plain', 40)
        soon.free_tokens_today, plain.free_tokens_today = 1000, 10
        self.pool.accounts = [soon, plain]
        self.assertIs(self.pool.pick(realm='cn', model='free-model'), plain)
        self.pool.affinity.bind('conversation', plain.uid)
        self.assertIs(self.pool.pick_for_session(realm='cn', session_key='conversation', model='paid-model'), plain)
        # Incremental free Token growth inside the user's large switching window
        # must not move this conversation to the temporarily cheaper peer.
        plain.free_tokens_today, soon.free_tokens_today = 2000, 10
        self.assertIs(self.pool.pick_for_session(realm='cn', session_key='conversation', model='free-model'), plain)

    def test_deduction_deadline_and_timezone_are_authoritative(self):
        a = account('parser')
        now = time.time()
        deadline = datetime.datetime.fromtimestamp(now + 3 * 86400, datetime.timezone.utc).isoformat()
        raw = {'CycleCapacitySize': 100, 'CycleCapacityRemain': 100,
               'CycleEndTime': datetime.datetime.fromtimestamp(now + 30 * 86400).isoformat(),
               'DeductionEndTime': deadline}
        parsed = a._parse_package_account(raw)
        self.assertAlmostEqual(parsed['days_left'], 3, delta=0.1)
        self.assertAlmostEqual(parsed['expire_at'], now + 3 * 86400, delta=1)
        raw['DeductionEndTime'] = int((now + 900 * 86400) * 1000)
        parsed = a._parse_package_account(raw)
        self.assertTrue(parsed['no_expiry'])
        self.assertIsNone(parsed['days_left'])
        del raw['DeductionEndTime']
        self.assertAlmostEqual(a._parse_package_account(raw)['days_left'], 30, delta=0.1)

    def test_cached_deadline_counts_down_and_expired_balance_is_not_urgent(self):
        a = account('stale', 1)
        a.credits['packages'][0]['days_left'] = 1
        with mock.patch.object(A.time, 'time', return_value=time.time() + 2 * 86400):
            self.assertIsNone(a.soonest_expiring_days())
        a.credits['packages'] = [{'remain': 50, 'days_left': 1}]
        a.credits['updated_at'] = time.time() - 2 * 86400
        self.assertIsNone(a.soonest_expiring_days())
        a.credits['packages'][0]['days_left'] = float('nan')
        self.assertIsNone(a.soonest_expiring_days())

    def test_enterprise_jwt_headers_and_cycle_quota(self):
        claims = base64.urlsafe_b64encode(json.dumps({'enterprise_id': 'synthetic-team'}).encode()).decode().rstrip('=')
        a = A.Account({'uid': 'enterprise', 'realm': 'cn', 'accessToken': 'e.' + claims + '.s'})
        a.expiring_window_days = 7
        self.assertEqual(a.enterprise_id, 'synthetic-team')
        self.assertEqual(a.headers(purpose='chat')['X-Enterprise-Id'], 'synthetic-team')
        response = {'code': 0, 'data': {'credit': 150, 'limitNum': 1000, 'cycleEndTime': '2026-10-10 00:00:00'}}
        with mock.patch.object(A, 'http_json', return_value=response) as call:
            result = a.fetch_credits()
        self.assertTrue(result['ok'])
        self.assertEqual(result['credits']['remain'], 850)
        self.assertIsNone(a.soonest_expiring_days())
        self.assertTrue(call.call_args.args[0].endswith(A.ENTERPRISE_USAGE_PATH))
        self.assertEqual(call.call_args.kwargs['headers']['X-Tenant-Id'], 'synthetic-team')
        for data in ({}, {'credit': float('nan'), 'limitNum': 100}, {'credit': True, 'limitNum': 100}):
            with mock.patch.object(A, 'http_json', return_value={'code': 0, 'data': data}):
                self.assertFalse(a.fetch_credits()['ok'])
            self.assertEqual(a.credits['remain'], 850, 'failure must not replace known balance with fake zero')

    def test_background_credit_failure_uses_backoff_and_manual_force_can_retry(self):
        a = account('backoff')
        a.credits['updated_at'] = time.time() - 4000
        with mock.patch.object(a, '_fetch_credits_raw', return_value={'ok': False, 'error': 'synthetic failure'}) as fetch:
            self.assertFalse(a.fetch_credits(force=False)['ok'])
            a.fetch_credits(force=False)
            self.assertEqual(fetch.call_count, 1)
            a.fetch_credits(force=True)
            self.assertEqual(fetch.call_count, 2)

    def test_manual_refresh_is_coalesced_and_concurrency_is_bounded(self):
        release = threading.Event()
        lock = threading.Lock()
        counts = {'active': 0, 'peak': 0}
        def refresh():
            with lock:
                counts['active'] += 1
                counts['peak'] = max(counts['peak'], counts['active'])
            release.wait(2)
            with lock:
                counts['active'] -= 1
            return True
        self.pool.accounts = [account(str(i)) for i in range(8)]
        for a in self.pool.accounts:
            a.refresh = mock.Mock(side_effect=refresh)
            a.save = mock.Mock()
        first = self.pool.start_manual_refresh()
        again = self.pool.start_manual_refresh()
        self.assertEqual(first['id'], again['id'])
        self.assertTrue(again['running'])
        release.set()
        self.assertTrue(self.pool._refresh_queue.drain(timeout=5))
        final = self.pool.credential_refresh_status(first['id'])
        self.assertEqual(final['completed'], 8)
        self.assertFalse(final['running'])
        self.assertTrue(all(row['ok'] for row in final['results']))
        self.assertLessEqual(counts['peak'], 2)
        for a in self.pool.accounts:
            a.refresh.assert_called_once()
        self.assertIsNone(self.pool.credential_refresh_status('missing'))

    def test_pricing_switch_disables_cost_but_keeps_usage_and_invalidates_views(self):
        row = {'model': 'deepseek-v4.1-flash', 'prompt_tokens': 100, 'completion_tokens': 20, 'at': time.time()}
        before = V.pricing_epoch()
        S.set_pricing_enabled(self.directory, False)
        cost = R.cost_for_row(row)
        self.assertTrue(cost.get('disabled'))
        self.assertFalse(cost['known'])
        bucket = {'cost_cny': 0}
        P._fold_cost(bucket, cost, row['model'])
        self.assertNotIn('cost_missing', bucket)
        self.assertNotEqual(before, V.pricing_epoch())
        self.assertFalse(P.runtime_settings_view()['pricing_enabled'])
        S.set_pricing_enabled(self.directory, True)
        self.assertTrue(R.pricing_enabled())
        self.assertNotEqual(cost, R.cost_for_row(row))

    def test_pricing_cycle_cannot_fetch_when_disabled_or_commit_after_toggle(self):
        refresher = R.PriceRefresher(interval_minutes=5)
        S.set_pricing_enabled(self.directory, False)
        with mock.patch.object(R, 'fetch_openrouter') as fetch:
            self.assertFalse(refresher.run_once()[0])
            fetch.assert_not_called()
        S.set_pricing_enabled(self.directory, True)
        def fetch_then_disable():
            S.set_pricing_enabled(self.directory, False)
            return {}
        with mock.patch.object(R, 'fetch_openrouter', side_effect=fetch_then_disable), mock.patch.object(R, 'record_policies') as write:
            self.assertFalse(refresher.run_once()[0])
            write.assert_not_called()

    def test_policy_file_stat_ttl_and_explicit_write_invalidation(self):
        path = str(Path(self.directory, 'probe.json'))
        Path(path).write_text('{}')
        R._forget_file_key(path)
        with mock.patch.object(R.os, 'stat', wraps=os.stat) as stat:
            first = R._file_key(path)
            self.assertEqual(R._file_key(path), first)
            self.assertEqual(stat.call_count, 1)
        Path(path).write_text('{"changed":true}')
        self.assertEqual(R._file_key(path), first)
        R._forget_file_key(path)
        self.assertNotEqual(R._file_key(path), first)

    def test_new_settings_and_keys_survive_sqlite_restart(self):
        accounts = Path(self.directory, 'accounts'); usage = Path(self.directory, 'usage')
        accounts.mkdir(); usage.mkdir()
        S.save(str(accounts), {'daily_token_limit': 1000})
        with mock.patch.dict(os.environ, {'WB_SQLITE_PATH': str(accounts / 'workbody.sqlite3')}):
            database = D.configure(str(accounts), str(usage))
            try:
                S.set_limits(str(accounts), {'daily_token_limit': {'cn': 0, 'intl': 2500},
                                             'expiring_window_days': {'cn': 7}})
                S.set_pricing_enabled(str(accounts), False)
                S.set_api_keys(str(accounts), [{'id': 'stable', 'key': 'synthetic-secret'}], delete_ids=[])
                database.close_thread()
                database = D.configure(str(accounts), str(usage))
                self.assertEqual(S.daily_token_limit(str(accounts), 'cn'), 0)
                self.assertEqual(S.daily_token_limit(str(accounts), 'intl'), 2500)
                self.assertEqual(S.expiring_window_days(str(accounts), 'cn'), 7)
                self.assertFalse(S.pricing_enabled(str(accounts)))
                self.assertEqual(S.api_keys(str(accounts))[0]['id'], 'stable')
            finally:
                database.close_thread()
                D.DATABASE = None


if __name__ == '__main__':
    unittest.main(verbosity=2)
