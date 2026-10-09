"""Platform scope, entitlement, reservations, affinity and official auth adapters."""
import io
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_database as D
import wb_platforms as U
import wb_settings as S
import wb_protocol_bridge as B
import wb_platform_api as API


class PlatformsTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.accounts = os.path.join(self.work.name, 'accounts')
        self.db = D.Database(os.path.join(self.accounts, 'db.sqlite3'), self.accounts, self.work.name)
        self.addCleanup(self.db.close_thread)
        self.manager = U.Manager(self.accounts, self.db)
        self.manager.refresh_async = lambda *args, **kwargs: None
        self.manager.import_accounts([{'upstream':'cline', 'access_token':'one'},
            {'upstream':'cline', 'access_token':'two'}, {'upstream':'opencode_zen', 'api_key':'zen'}])
        self.cline = sorted((a for a in self.manager.accounts.values() if a.upstream == 'cline'), key=lambda a:a.uid)
        self.meta = {'native_protocol':'chat', 'billing_mode':'free'}
        S.set_pool_config(self.accounts, {'max_in_flight':0})

    def reserve(self, session='', owner='one', amount=1000, meta=None, bound=None):
        return self.manager.reserve('cline', 'model', meta or self.meta, session, owner, amount, bound)

    def row(self, account, **values):
        return dict({'account':account.uid, 'upstream':'cline', 'billing_mode':'free', 'outcome':'completed',
            'at':time.time(), 'total_tokens':1000}, **values)

    def test_legacy_and_single_platform_aliases(self):
        self.assertEqual(U.route('model', None), ('workbuddy','model','model'))
        self.assertEqual(U.route('provider/model', {'allowed_upstreams':['cline']}), ('cline','provider/model','cline/provider/model'))
        with self.assertRaises(U.PlatformError) as result:
            U.route('opencode/model', {'allowed_upstreams':['cline']})
        self.assertEqual(result.exception.status, 403)
        with self.assertRaises(U.PlatformError):
            U.route('model', {'allowed_upstreams':['cline','opencode_zen']})

    def test_catalog_entitlements_and_native_protocols(self):
        models=U.parse_catalog('cline', {'data':{'recommended':[{'id':'paid'}], 'free':[{'id':'free'}], 'clinePass':[{'id':'pass'}]}})
        self.assertEqual(models['free']['billing_mode'],'free')
        self.assertEqual(models['paid']['billing_mode'],'paid')
        self.assertEqual(models['pass']['entitlement'],'subscription')
        zen=U.parse_catalog('opencode_zen', {'data':[{'id':'gpt-fixture'}, {'id':'claude-fixture'},
            {'id':'glm-fixture'}, {'id':'gemini-fixture'}, {'id':'named-free'}, {'id':'observed-free','pricing':{'input':0,'output':0}}]})
        self.assertEqual([zen[x]['native_protocol'] for x in ('gpt-fixture','claude-fixture','glm-fixture')], ['responses','messages','chat'])
        self.assertNotIn('gemini-fixture',zen)
        self.assertEqual(zen['named-free']['billing_mode'],'paid')
        self.assertEqual(zen['observed-free']['billing_mode'],'free')

    def test_priority_persistence_and_platform_local_selection(self):
        self.manager.update_account(self.cline[1].uid, {'priority':1,'models':['allowed-*']})
        account,ticket=self.manager.reserve('cline','allowed-model',self.meta,'','',1)
        self.assertEqual(account.uid,self.cline[1].uid)
        self.manager.release(ticket)
        reloaded=U.Manager(self.accounts,self.db)
        self.assertEqual(reloaded.accounts[account.uid].priority,1)
        self.assertEqual(self.reserve()[0].uid,self.cline[0].uid)
        for a in self.cline:self.manager.update_account(a.uid,{'enabled':False})
        with self.assertRaises(U.PlatformError):self.reserve()

    def test_concurrent_requests_consider_reservations(self):
        def allocate(i):
            try:return self.reserve(owner=str(i))
            finally:self.db.close_thread()
        with ThreadPoolExecutor(max_workers=8) as executor:
            allocated=list(executor.map(allocate,range(24)))
        counts={a.uid:sum(v[0].uid==a.uid for v in allocated) for a in self.cline}
        self.assertEqual(sorted(counts.values()),[12,12])
        account,ticket=allocated[0]
        self.manager.settle(ticket,self.row(account,total_tokens=100))
        self.assertEqual(self.manager.reservations[ticket]['estimate'],0)
        self.assertEqual(self.manager.daily[account.uid]['free_tokens'],100)
        self.manager.release(ticket)

    def test_session_keeps_account_with_large_window(self):
        first,ticket=self.reserve('same-session')
        self.manager.settle(ticket,self.row(first,total_tokens=20000))
        self.manager.release(ticket)
        second,ticket=self.reserve('same-session')
        self.assertEqual(first.uid,second.uid)
        self.manager.settle(ticket,self.row(second,total_tokens=300000))
        self.manager.release(ticket)
        third,ticket=self.reserve('same-session')
        self.assertNotEqual(first.uid,third.uid)

    def test_bound_opaque_history_never_falls_back(self):
        first=self.cline[0]
        first.cooldowns['*']=time.time()+10
        with self.assertRaises(U.PlatformError):self.reserve(bound=first.uid)
        self.assertFalse(self.manager.reservations)

    def test_max_in_flight_and_cancelled_consumption(self):
        S.set_pool_config(self.accounts,{'max_in_flight':1})
        a,ticket=self.reserve()
        b,other=self.reserve()
        self.assertNotEqual(a.uid,b.uid)
        with self.assertRaises(U.PlatformError):self.reserve()
        self.manager.settle(ticket,self.row(a,outcome='client_aborted',total_tokens=456))
        with self.assertRaises(U.PlatformError):self.reserve()
        self.manager.release(ticket)
        self.assertEqual(self.manager.daily[a.uid]['free_tokens'],456)

    def test_midnight_reload_excludes_current_committed_row(self):
        a,ticket=self.reserve()
        row=self.row(a)
        self.db.append_usage(row)
        self.manager.day='previous day'
        self.manager.settle(ticket,row)
        self.assertEqual(self.manager.daily[a.uid]['free_tokens'],1000)

    def test_paid_credits_reconcile_generation_ids_and_reservations(self):
        a=self.cline[0]; self.manager._today()
        self.manager._count(self.row(a,billing_mode='paid',has_credit=True,credit=10,total_tokens=100,
                                    upstream_generation_id='gen-one'))
        a.document['paid_usage']={'day':self.manager.day,'unit':'credits','transactions':[
            {'id':'gen-one','credit':10,'tokens':100},{'id':'gen-two','credit':5,'tokens':50}]}
        self.assertEqual(self.manager._paid_load(a),15)
        self.assertEqual(self.manager._paid_estimate('cline',{'pricing':{'output':999999}},100),10)
        a,ticket=self.reserve(meta={'native_protocol':'chat','billing_mode':'paid'},amount=100)
        self.assertEqual(self.manager.reservations[ticket]['estimate'],10)

    def test_refresh_serialized_and_uses_bound_proxy(self):
        a=self.cline[0]
        S.set_proxy_slots(self.accounts,[{'url':'http://127.0.0.1:8080','username':'synthetic-user','password':'synthetic-pass'}])
        slot=S.proxy_slots(self.accounts)[0]
        a.document.update(expires_at=time.time(),refresh_token='synthetic-refresh',proxy_slot=slot['id'])
        calls=[]
        def transport(request,**kwargs):
            calls.append((request,kwargs))
            return io.BytesIO(json.dumps({'data':{'accessToken':'new','expiresAt':time.time()+3600}}).encode())
        self.manager.transport=transport
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda _:self.manager.ensure_token(a),range(8)))
        self.assertEqual(len(calls),1)
        self.assertEqual(a.token,'workos:new')
        self.assertIn('synthetic-user:synthetic-pass@',calls[0][1]['proxy'])

    def test_connection_failure_releases_slot(self):
        def failed(*args,**kwargs):raise urllib.error.URLError('offline')
        self.manager.transport=failed
        with self.assertRaises(U.PlatformError) as result:
            self.manager.open('cline','model',{'messages':[]},self.meta)
        self.assertEqual(result.exception.status,502)
        self.assertFalse(self.manager.reservations)

    def test_bridge_schema_and_confirmed_cline_credits(self):
        result=B.chat_to_responses({'messages':[{'role':'user','content':'hello'}], 'response_format':
            {'type':'json_schema','json_schema':{'name':'answer','schema':{'type':'object'},'strict':True}}})
        self.assertEqual(result['text']['format']['name'],'answer')
        self.assertNotIn('json_schema',result['text']['format'])
        response=io.BytesIO(B.frame('',{'id':'gen-test','usage':{'total_tokens':10,'creditsUsed':2}})+B.frame('','[DONE]'))
        list(B.chat_lines(response,'chat','cline'))
        self.assertEqual(response.generation_id,'gen-test')
        self.assertEqual(B.usage({'creditsUsed':2},'chat','cline')['credit'],2)

    def test_refresh_network_failure_releases_slot(self):
        a = self.cline[0]
        a.document.update(expires_at=time.time(), refresh_token='synthetic-refresh')
        self.manager.transport = mock.Mock(side_effect=urllib.error.URLError('offline'))
        with self.assertRaises(U.PlatformError) as result:
            self.manager.open('cline', 'model', {'messages':[]}, self.meta, bound_uid=a.uid)
        self.assertEqual(result.exception.code, 'credential_refresh_failed')
        self.assertFalse(self.manager.reservations)

    def test_multimodal_tool_results_keep_images(self):
        body = {'messages': [{'role':'tool', 'tool_call_id':'call-one', 'content':[
            'result', {'type':'image_url', 'image_url':{'url':'data:image/png;base64,aGVsbG8='}}]}]}
        response = B.chat_to_responses(body)['input'][0]['output']
        messages = B.chat_to_messages(body)['messages'][0]['content'][0]['content']
        self.assertEqual([part['type'] for part in response], ['input_text','input_image'])
        self.assertEqual([part['type'] for part in messages], ['text','image'])
        self.assertEqual(messages[1]['source']['data'], 'aGVsbG8=')

    def test_retries_keep_original_rate_limit_when_no_other_account(self):
        manager = mock.Mock()
        manager.accounts = self.manager.accounts
        rate = U.PlatformError('limit', 429, 'upstream_error', 137)
        manager.open.side_effect = [rate, U.PlatformError('none', 503, 'account_unavailable')]
        with self.assertRaises(U.PlatformError) as caught:
            API._open(manager, 'cline', 'model', {}, self.meta, 'session', 'owner')
        self.assertIs(caught.exception, rate)
        self.assertEqual(caught.exception.wait, 137)
        self.assertTrue(all(call.args[0]=='cline' for call in manager.open.call_args_list))

    def test_reimport_preserves_omitted_account_settings(self):
        account = self.cline[0]
        account.document.update(priority=7, models=['allowed-*'], enabled=False,
                                name='Keep name', refresh_token='keep-refresh', proxy_slot='saved-proxy')
        token = account.document['access_token']
        self.manager.import_accounts([{'upstream':'cline','access_token':token,'email':'updated-profile@example.invalid'}])
        self.assertEqual(account.priority,7)
        self.assertEqual(account.document['models'],['allowed-*'])
        self.assertFalse(account.enabled)
        self.assertEqual(account.document['name'],'Keep name')
        self.assertEqual(account.document['proxy_slot'],'saved-proxy')
        self.assertEqual(account.document['refresh_token'],'keep-refresh')
        self.manager.import_accounts([{'upstream':'cline','access_token':token,'priority':20,'enabled':True}])
        self.assertEqual(account.priority,20)
        self.assertTrue(account.enabled)


if __name__=='__main__':unittest.main()
