"""Reproduce the whole-project audit findings without touching live data.

Run: python3 scripts/audit_project.py [--output FILE]
Exit 1 means findings were reproduced; 0 means none; 2 means the probe failed.
All credentials are synthetic. The listener uses a random loopback port.
"""
import argparse
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def probe():
    with tempfile.TemporaryDirectory(prefix='workbody-project-audit-') as workspace:
        accounts = Path(workspace) / 'accounts'
        usage = Path(workspace) / 'usage'
        accounts.mkdir()
        usage.mkdir()
        os.environ['ACCOUNTS_DIR'] = str(accounts)
        os.environ['WB_PROXY_USAGE_DIR'] = str(usage)
        sys.path.insert(0, str(ROOT))
        import wb_proxy as P
        import wb_accounts as A
        import wb_settings as S
        import wb_reqlog as R
        import wb_scheduler as scheduler_module

        P.ACCOUNTS_DIR = str(accounts)
        P.USAGE_DIR = str(usage)
        P.USAGE_LOG = str(usage / 'usage.jsonl')
        P.CURRENT_REALM = 'intl'
        P.API_KEY = 'AUDIT_STARTUP_ONLY'
        P.log = lambda *args, **kwargs: None
        P.POOL = A.AccountPool(str(accounts), log=lambda *args: None)

        keys = [{'id': 'audit-id', 'name': 'audit', 'key': 'AUDIT_CURRENT_ONLY',
                 'enabled': True, 'realm': 'intl'}]
        S.set_api_keys(str(accounts), keys)
        before = {'retired_key_accepted': bool(P.identify_key('AUDIT_STARTUP_ONLY')),
                  'current_key_accepted': bool(P.identify_key('AUDIT_CURRENT_ONLY'))}
        Path(S.settings_path(str(accounts))).write_text('{broken', encoding='utf-8')
        after = {'retired_key_accepted': bool(P.identify_key('AUDIT_STARTUP_ONLY')),
                 'current_key_accepted': bool(P.identify_key('AUDIT_CURRENT_ONLY'))}
        assert not before['retired_key_accepted'] and before['current_key_accepted']
        S.set_api_keys(str(accounts), keys)
        S.set_panel_password(str(accounts), 'AUDIT_PANEL_ONLY')
        panel_token = P.PANEL.create()

        class AuditServer(ThreadingHTTPServer):
            daemon_threads = True
            def handle_error(self, request, client_address):
                self.errors.append(type(sys.exc_info()[1]).__name__)

        server = AuditServer(('127.0.0.1', 0), P.Handler)
        server.errors = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(method, path, payload=None, panel=False, anonymous=False):
            headers = {'Content-Type': 'application/json'}
            if not anonymous:
                headers['Authorization'] = 'Bearer AUDIT_CURRENT_ONLY'
            if panel:
                headers['X-Panel-Token'] = panel_token
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            at = time.monotonic()
            try:
                connection.request(method, path, None if payload is None else json.dumps(payload), headers)
                response = connection.getresponse()
                body = response.read().decode('utf-8', 'replace')
                return {'status': response.status, 'elapsed_ms': round((time.monotonic()-at)*1000),
                        'body': json.loads(body) if body else None}
            except Exception as error:
                return {'status': None, 'exception': type(error).__name__}
            finally:
                connection.close()

        observations = {}
        try:
            observations['corrupt_settings'] = {'before': before, 'after': after}
            observations['retired_password_change'] = request('POST', '/panel/password',
                {'current': 'AUDIT_PANEL_ONLY', 'new': 'admin'}, panel=True)
            wrong_password = request('POST', '/panel/password',
                {'current': 'AUDIT_WRONG_ONLY', 'new': 'AUDIT_NEW_ONLY'}, panel=True)
            observations['wrong_current_password'] = {'status': wrong_password['status'],
                'panel_session_still_valid': P.PANEL.valid(panel_token)}
            logged = []
            with mock.patch.object(P, 'log', side_effect=lambda message, *args, **kwargs: logged.append(message)):
                for target in ('/?pwd=AUDIT_URL_ONLY', '/?%70wd=AUDIT_ENCODED_ONLY&KEY=AUDIT_KEY_ONLY'):
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                    connection.request('GET', target)
                    response = connection.getresponse()
                    response.read()
                    connection.close()
            observations['url_password_logged'] = {'http_status': response.status,
                'password_in_access_log': any('AUDIT_URL_ONLY' in line or 'AUDIT_ENCODED_ONLY' in line
                                               or 'AUDIT_KEY_ONLY' in line for line in logged)}
            observations['api_key_realm_write'] = request('POST', '/realm', {'realm': 'cn'})
            assert observations['api_key_realm_write']['status'] == 403
            observations['invalid_requests'] = {}
            with mock.patch.object(P, 'open_upstream', side_effect=RuntimeError('offline audit: no upstream')):
                for label, path, payload in [
                    ('chat_message_null', '/v1/chat/completions', {'model':'deepseek-v4.1-flash','messages':[None]}),
                    ('chat_model_list', '/v1/chat/completions', {'model':['invalid'],'messages':[{'role':'user','content':'test'}]}),
                    ('responses_tools_integer', '/v1/responses', {'model':'deepseek-v4.1-flash','input':'test','tools':42}),
                    ('responses_model_integer', '/v1/responses', {'model':42,'input':'test'}),
                    ('responses_input_empty', '/v1/responses', {'model':'deepseek-v4.1-flash','input':[]}),
                    ('messages_messages_null', '/v1/messages', {'model':'deepseek-v4.1-flash','messages':[None],'max_tokens':32}),
                    ('chat_function_name_list', '/v1/chat/completions', {'messages':[{'role':'user','content':'test'}],'tools':[{'type':'function','function':{'name':[]}}]}),
                    ('chat_tool_calls_integer', '/v1/chat/completions', {'messages':[{'role':'assistant','tool_calls':42}]}),
                    ('responses_input_type_list', '/v1/responses', {'input':[{'type':[]}]}),
                    ('chat_temperature_overflow', '/v1/chat/completions', {'messages':[{'role':'user','content':'test'}],'temperature':10**1000}),
                ]:
                    observations['invalid_requests'][label] = request('POST', path, payload)
            expired = A.Account({'uid':'audit-expired','realm':'intl','accessToken':'AUDIT_ACCESS_ONLY',
                                 'refreshToken':'AUDIT_REFRESH_ONLY','expiresAt': int(time.time())-1})
            P.POOL.accounts = [expired]
            def slow_refresh():
                time.sleep(0.15)
                return False
            with mock.patch.object(expired, 'refresh', side_effect=slow_refresh) as refresh:
                result = request('GET', '/health', anonymous=True)
                observations['anonymous_health_refresh'] = {'status':result['status'],
                    'elapsed_ms':result['elapsed_ms'], 'refresh_calls':refresh.call_count}
            P.POOL.accounts = []

            from types import SimpleNamespace
            checkin = mock.Mock(return_value={'ok': True, 'msg': 'synthetic'})
            account = SimpleNamespace(uid='audit-scheduler',realm='cn',enabled=True,
                checkin=checkin,can_checkin=lambda: True,expires_at=int(time.time())+86400)
            scheduled_pool = SimpleNamespace(accounts=[account],dir=str(accounts))
            scheduler = scheduler_module.Scheduler(scheduled_pool)
            scheduler.enabled = False
            scheduler.checkin_hours = [time.localtime().tm_hour]
            scheduler.checkin_enabled = True
            for flag in ('travel_enabled','keepalive_enabled','cat_enabled','daily_chat_enabled','growth_enabled'):
                setattr(scheduler, flag, False)
            scheduler._stop_event.set()
            with mock.patch.object(scheduler_module.time, 'sleep', return_value=None), \
                 mock.patch.object(scheduler_module.wb_tasks, 'fetch_streak_days', return_value=0), \
                 mock.patch.object(scheduler_module.wb_tasks, 'run_streak_bonus', return_value={'logs': []}):
                scheduler._run_loop()
            observations['disabled_scheduler_startup'] = {'enabled':scheduler.enabled,
                'stop_requested':scheduler._stop_event.is_set(), 'checkin_calls':checkin.call_count}

            restart_scheduler = scheduler_module.Scheduler(SimpleNamespace(accounts=[], dir=str(accounts)))
            entered = threading.Event()
            release = threading.Event()
            real_wait = restart_scheduler._stop_event.wait
            def controlled_wait(timeout=None):
                if timeout == 10:
                    entered.set()
                return real_wait(timeout)
            def controlled_startup_sleep(_seconds):
                entered.set()
                release.wait(timeout=3)
            with mock.patch.object(scheduler_module.time, 'sleep', side_effect=controlled_startup_sleep), \
                 mock.patch.object(restart_scheduler._stop_event, 'wait', side_effect=controlled_wait), \
                 mock.patch.object(restart_scheduler, '_execute_cycle', return_value=None):
                try:
                    restart_scheduler.start()
                    assert entered.wait(timeout=2)
                    original_thread = restart_scheduler._thread
                    restart_scheduler.stop()
                    restart_scheduler.start()
                    new_thread_created = restart_scheduler._thread is not original_thread
                    release.set()
                    original_thread.join(timeout=2)
                    alive_after_restart = restart_scheduler._thread.is_alive()
                    stop_after_restart = restart_scheduler._stop_event.is_set()
                finally:
                    release.set()
                    restart_scheduler.stop()
                    restart_scheduler._thread.join(timeout=3)
            observations['scheduler_restart'] = {'new_thread_created': new_thread_created,
                'worker_alive_after_restart': alive_after_restart,
                'stop_event_set': stop_after_restart}

            log = Path(P.USAGE_LOG)
            at = time.time()
            with log.open('w', encoding='utf-8') as file:
                for index in range(1200):
                    file.write(json.dumps({'at':at,'account':'audit-account','model':'audit-model',
                        'total_tokens':1,'credit':1,'status':200,'outcome':'completed',
                        'padding':'x'*2000})+'\n')
            state = {'day':'','totals':None,'credits':{},'models':{},'offset':0,'at':0}
            with mock.patch.object(P, '_daily_usage', state):
                first_stats = P.daily_usage_stats(ttl=0)
                first = first_stats['tokens']['audit-account']
                assert R.compact_main(str(log), max_mb=1, retention_days=30)
                second_stats = P.daily_usage_stats(ttl=0)
                second = second_stats['tokens']['audit-account']
                state.update({'day':'','totals':None,'credits':None,'models':None,'offset':0,'at':0})
                restarted_stats = P.daily_usage_stats(ttl=0)
                observations['daily_usage_after_rotation'] = {'before':first,'after':second,
                    'archived_files':len(R.archive_files(str(usage))),
                    'all_counters_preserved': second_stats == first_stats,
                    'restart_counters_preserved': restarted_stats == first_stats}
                with log.open('a', encoding='utf-8') as file:
                    file.write(json.dumps({'at':at,'account':'audit-account','model':'audit-model',
                        'total_tokens':2,'credit':3,'outcome':'completed'})+'\n')
                updated = P.daily_usage_stats(ttl=0)
                observations['daily_usage_after_rotation']['incremental_append_preserved'] = (
                    updated['tokens']['audit-account'] == 1202
                    and updated['credits']['audit-account'] == 1203
                    and updated['models']['audit-account']['audit-model'] == 1202)

            large = Path(workspace) / 'large-usage'
            large.mkdir()
            with (large/'usage.jsonl').open('w', encoding='utf-8') as file:
                for index in range(2200):
                    file.write(json.dumps({'at':at,'account':'audit-account','status':200,
                        'outcome':'completed','index':index,'padding':'x'*4000})+'\n')
            rows = R.read_rows(str(large))
            observations['archive_reader_truncation'] = {'actual_rows':2200,'returned_rows':len(rows),
                'main_file_bytes':(large/'usage.jsonl').stat().st_size,
                'first_returned_index':rows[0]['index']}
            observations['handler_exceptions'] = server.errors
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        findings = []
        def finding(code, condition):
            if condition:
                findings.append(code)
        finding('A01', observations['corrupt_settings']['after']['retired_key_accepted'])
        finding('A02', observations['daily_usage_after_rotation']['after'] < observations['daily_usage_after_rotation']['before'])
        finding('A03', observations['archive_reader_truncation']['returned_rows'] != observations['archive_reader_truncation']['actual_rows'])
        finding('A04', observations['url_password_logged']['password_in_access_log'])
        finding('A05', observations['anonymous_health_refresh']['refresh_calls'] > 0)
        finding('A06', observations['scheduler_restart']['worker_alive_after_restart'] is False)
        finding('A07', observations['disabled_scheduler_startup']['checkin_calls'] > 0)
        finding('A08', any(observations['invalid_requests'][name]['status'] is None for name in ('chat_message_null', 'responses_tools_integer')))
        finding('A09', observations['retired_password_change']['status'] is None)
        return {'scope': 'synthetic temporary state, loopback HTTP, mocked upstream only',
                'observations': observations, 'findings': findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='optional evidence JSON destination')
    args = parser.parse_args()
    try:
        result = probe()
    except Exception as error:
        print(json.dumps({'probe_error': type(error).__name__}), file=sys.stderr)
        return 2
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered, encoding='utf-8')
    print(rendered, end='')
    return 1 if result['findings'] else 0


if __name__ == '__main__':
    sys.exit(main())
