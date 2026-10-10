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
        self.assertEqual(U.route('provider/model', {'allowed_upstreams':['cline']}), ('cline','provider/model','provider/model'))
        self.assertEqual(U.route('cline/provider/model', {'allowed_upstreams':['cline']}), ('cline','provider/model','provider/model'))
        with self.assertRaises(U.PlatformError) as result:
            U.route('opencode/model', {'allowed_upstreams':['cline']})
        self.assertEqual(result.exception.status, 403)
        with self.assertRaises(U.PlatformError):
            U.route('model', {'allowed_upstreams':['cline','opencode_zen']})

    def test_cline_native_namespace_and_other_platform_prefixes(self):
        native = {'cline-pass/model', 'cline/native', 'opencode/model'}
        key = {'allowed_upstreams': ['cline', 'opencode_zen']}
        for value in ('cline-pass/model', 'cline/native'):
            self.assertEqual(U.route(value, key, native), ('cline', value, value))
            self.assertEqual(U.route('cline/' + value, key, native), ('cline', value, value))
        self.assertEqual(U.route('opencode/model', key, native), ('opencode_zen', 'model', 'opencode/model'))
        self.assertEqual(U.route('opencode/model', {'allowed_upstreams':['cline']}, native), ('cline', 'opencode/model', 'opencode/model'))

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
        partial=U.parse_catalog('opencode_zen',{'models':[{'id':'partial','pricing':{'input':0}}]})
        self.assertEqual(partial['partial']['billing_mode'],'paid')

    def test_opencode_live_ids_use_registry_prices_without_adding_removed_models(self):
        live = {'object':'list', 'data':[{'id':'big-pickle','object':'model','owned_by':'opencode'},
            {'id':'mimo-v2.6-flash-free'}, {'id':'paid-model'}, {'id':'unpriced-free'}]}
        registry = {'opencode':{'models':{
            'big-pickle':{'name':'Big Pickle','cost':{'input':0,'output':0},'limit':{'context':200000}},
            'mimo-v2.6-flash-free':{'cost':{'input':0,'output':0}},
            'paid-model':{'cost':{'input':1,'output':2}},
            'removed-free':{'cost':{'input':0,'output':0}}}}}
        calls=[]
        def transport(request, **kwargs):
            calls.append(request)
            return io.BytesIO(json.dumps(registry if request.full_url == 'https://models.dev/api.json' else live).encode())
        self.manager.transport=transport
        self.manager.import_accounts({'upstream':'opencode_zen','public':True,'enabled':True})
        cache=self.manager.refresh_catalog('opencode_zen')
        public=next(a for a in self.manager.accounts.values() if a.document.get('public'))
        for account in self.manager.accounts.values():
            if account.upstream=='opencode_zen' and account is not public: account.document['enabled']=False
        visible={item['upstream_model'] for item in self.manager.models(['opencode_zen'])}
        self.assertEqual(visible,{'big-pickle','mimo-v2.6-flash-free'})
        self.assertNotIn('removed-free',cache['models'])
        self.assertEqual(cache['models']['paid-model']['pricing']['unit'],'USD/1M tokens')
        self.assertFalse(next(r for r in calls if r.full_url=='https://models.dev/api.json').has_header('Authorization'))

    def test_catalog_respects_per_model_protocols_and_retired_models(self):
        models=U.parse_catalog('opencode_zen',{'models':{
            'native-anthropic':{'npm':'@ai-sdk/openai-compatible','provider':{'npm':'@ai-sdk/anthropic'}},
            'native-google':{'provider':{'npm':'@ai-sdk/google'}},
            'disabled':{'disabled':True},'retired':{'status':'deprecated'}}})
        self.assertEqual(models['native-anthropic']['native_protocol'],'messages')
        self.assertEqual(set(models),{'native-anthropic'})

    def test_cline_pass_feed_does_not_depend_on_first_accounts_token(self):
        feed={'recommended':[{'id':'vendor/paid'}], 'free':[{'id':'cline-free/fixture'}],
              'clinePass':[{'id':'cline-pass/fixture','name':'Pass Fixture'}]}
        self.manager.ensure_token=mock.Mock(side_effect=U.PlatformError('expired token',401))
        def transport(request, **kwargs):
            if request.full_url.endswith('/recommended-models'):
                self.assertFalse(request.has_header('Authorization'))
                return io.BytesIO(json.dumps(feed).encode())
            raise OSError('optional metadata unavailable')
        self.manager.transport=transport
        cache=self.manager.refresh_catalog('cline')
        self.assertEqual(cache['models']['cline-pass/fixture']['entitlement'],'subscription')
        self.assertEqual(cache['groups']['subscription'],1)
        self.manager.ensure_token.assert_not_called()

    def test_console_defaults_resolve_official_config_with_only_a_key(self):
        registry={'opencode':{'api':'https://opencode.ai/zen/v1','npm':'@ai-sdk/openai-compatible',
            'models':{'big-pickle':{'cost':{'input':0,'output':0}},'claude-fixture':{'provider':{'npm':'@ai-sdk/anthropic'}}}}}
        self.manager.transport=lambda request,**kwargs:io.BytesIO(json.dumps(
            registry if request.full_url=='https://models.dev/api.json' else {'data':[{'id':'big-pickle'},{'id':'claude-fixture'}]}).encode())
        account_uid=self.manager.import_accounts({'upstream':'opencode_zen','auth_type':'oauth',
            'access_token':'console-token','org_id':'org-one'})[0]['uid']
        account=self.manager.accounts[account_uid]
        self.manager.logins._request=lambda url,**kwargs:([{'id':'org-one'}] if url.endswith('/orgs') else
            {'config':{'provider':{'opencode':{'options':{'apiKey':'organization-gateway-key'}}}}})
        self.manager.refresh_console(account)
        self.assertTrue(account.view()['credential_ready'])
        self.assertTrue(account.allows('big-pickle'))
        self.assertEqual(self.manager.model('opencode_zen','claude-fixture')['native_protocol'],'messages')
        self.assertNotIn('organization-gateway-key',json.dumps(self.manager.snapshot()))

    def test_console_template_request_uses_current_token_and_model_endpoint(self):
        gateway={'url':'https://opencode.ai/inference/openai/v1','provider':'opencode',
            'api_key':'{env:OPENCODE_CONSOLE_TOKEN}','headers':{'x-opencode-org-id':'org-one'},
            'npm':'@ai-sdk/openai-compatible','models':{'claude-fixture':{'provider':{
                'npm':'@ai-sdk/anthropic','api':'https://opencode.ai/inference/anthropic/v1'}}}}
        uid=self.manager.import_accounts({'upstream':'opencode_zen','auth_type':'oauth',
            'access_token':'console-access','org_id':'org-one','console_gateway':gateway})[0]['uid']
        account=self.manager.accounts[uid]
        calls=[]
        def transport(request,**kwargs):
            calls.append(request)
            headers={name.lower():value for name,value in request.header_items()}
            if headers.get('authorization')!='Bearer console-access' or headers.get('x-opencode-org-id')!='org-one':
                raise urllib.error.HTTPError(request.full_url,401,'Unauthorized',{},io.BytesIO(b'{"error":"invalid credential"}'))
            self.assertEqual(request.full_url,'https://opencode.ai/inference/anthropic/v1/messages')
            self.assertEqual(headers['x-api-key'],'console-access')
            return io.BytesIO(b'{"content":[{"type":"text","text":"OK"}]}')
        self.manager.transport=transport
        meta=self.manager.model('opencode_zen','claude-fixture')
        with self.manager.open('opencode_zen','claude-fixture',{'messages':[{'role':'user','content':'Reply only OK.'}]},meta,bound_uid=uid) as lease:
            self.assertIn(b'OK',lease.read())
        self.assertEqual(len(calls),1)
        self.assertFalse(self.manager.reservations)

    def test_partial_go_defaults_do_not_disappear_when_zen_is_complete(self):
        self.manager.registry_metadata=mock.Mock(return_value=({'opencode-go':{'npm':'@ai-sdk/openai-compatible',
            'models':{'go-model':{'cost':{'input':1,'output':2}}}}},False))
        self.manager.public_json=mock.Mock(return_value={'data':[{'id':'go-model'}]})
        gateway=self.manager.console_gateway({'provider':{
            'opencode':{'api':'https://opencode.ai/inference/openai/v1','npm':'@ai-sdk/openai-compatible',
                'options':{'apiKey':'zen-key'},'models':{'zen-model':{}}},
            'opencode-go':{'options':{'apiKey':'go-key'}}}})
        self.assertEqual(set(gateway['models']),{'zen-model','go/go-model'})
        self.assertEqual(gateway['provider_gateways']['opencode-go']['api_key'],'go-key')

    def test_cline_balance_queries_plan_and_all_quota_windows(self):
        account=self.cline[0]
        documents={'/users/me':{'data':{'id':'user-one'}}, '/users/user-one/balance':{'data':{'balance':7.5}},
            '/users/me/plan':{'data':{'plan':{'id':'pass','displayName':'ClinePass','pricePerSeatCents':999},
                'currentPeriodEnd':'2026-11-01T00:00:00Z'}},
            '/users/me/plan/usage-limits':{'data':{'limits':[{'type':kind,'percentUsed':used,'resetsAt':'2026-11-01T00:00:00Z'}
                for kind,used in [('five_hour',25),('weekly',50),('monthly',10)]]}}}
        self.manager.request_json=lambda upstream,path,*args,**kwargs:documents[path]
        self.manager.refresh_balance(account)
        view=account.view()
        self.assertEqual(view['balance']['remain'],7.5)
        self.assertEqual(view['subscription']['name'],'ClinePass')
        self.assertEqual(view['quota']['monthly']['remaining_percent'],90)
        self.assertEqual(view['quota']['fiveHour']['percent_used'],25)

    def test_opencode_one_broken_oauth_does_not_block_an_api_key(self):
        self.manager.import_accounts({'upstream':'opencode_zen','auth_type':'oauth','access_token':'expired-console','org_id':'org'})
        self.manager.refresh_console=mock.Mock(side_effect=U.PlatformError('expired console',401))
        self.manager.opencode_catalog=lambda account:{'big-pickle':{'id':'big-pickle','native_protocol':'chat','billing_mode':'free'}}
        self.manager.registry_metadata=lambda account=None:({},True)
        cache=self.manager.refresh_catalog('opencode_zen')
        self.assertIn('big-pickle',cache['models'])
        self.assertIn('部分',self.manager.catalog_errors['opencode_zen'])

    def test_failed_optional_quota_query_retains_known_balance(self):
        def request(upstream,path,*args,**kwargs):
            if path=='/users/me':return {'id':'user-one'}
            if path.endswith('/balance'):return {'balance':0}
            raise U.PlatformError('not entitled',403)
        self.manager.request_json=request
        self.manager.refresh_balance(self.cline[0])
        self.assertEqual(self.cline[0].view()['balance']['remain'],0)
        self.assertIn('quota',self.cline[0].view()['billing_errors'])

    def test_subscription_balance_zero_missing_expired_and_distinct_resets(self):
        now=time.time()
        for account, owner, remaining, reset in ((self.cline[0],'a',80,'2099-01-01T00:00:00Z'),
                                               (self.cline[1],'b',60,'2099-02-01T00:00:00Z')):
            account.document.update(user_id=owner,quota={'fiveHour':{'remaining_percent':remaining,'reset_at':reset}},
                billing_status={'quota':{'updated_at':now,'stale':False}})
        self.cline[1].document['enabled']=False
        result=self.manager.quota_balance('cline')
        self.assertEqual((result['total_remain'],result['total_used'],result['total_granted']),(140,60,200))
        self.assertEqual(len({row['reset_at'] for row in result['accounts']}),2)
        for account in self.cline:
            account.document['quota']['fiveHour']['remaining_percent']=0
        self.assertEqual(self.manager.quota_balance('cline')['total_remain'],0)
        self.assertTrue(self.manager.quota_balance('cline')['complete'])
        self.cline[1].document['quota']={}
        self.assertEqual(self.manager.quota_balance('cline')['unknown_count'],1)
        self.cline[0].document['quota']['fiveHour']['reset_at']='2020-01-01T00:00:00Z'
        result=self.manager.quota_balance('cline')
        self.assertEqual((result['total_remain'],result['stale_count'],result['complete']),(None,1,False))

    def test_opencode_quota_balance_deduplicates_org_and_keeps_wallet_unknown(self):
        first=next(a for a in self.manager.accounts.values() if a.upstream=='opencode_zen')
        uid=self.manager.import_accounts({'upstream':'opencode_zen','api_key':'other-zen-key'})[0]['uid']
        second=self.manager.accounts[uid]
        for account,org,remaining in ((first,'org-one',80),(second,'org-two',60)):
            account.document.update(org_id=org,quota={'fiveHour':{'remaining_percent':remaining}},
                billing_status={'quota':{'updated_at':time.time(),'stale':False}})
        self.assertEqual(self.manager.quota_balance('opencode_zen')['total_remain'],140)
        second.document['org_id']='org-one'
        second.document['billing_status']['quota']['stale']=True
        result=self.manager.quota_balance('opencode_zen')
        self.assertEqual((result['total_remain'],result['account_count'],result['complete']),(80,1,True))

    def test_quota_refresh_auth_failure_invalidates_cached_percentage(self):
        for account in self.cline:
            account.document.update(quota={'fiveHour':{'remaining_percent':80}},
                billing_status={'quota':{'updated_at':time.time(),'stale':False}})
        self.manager.refresh_catalog=mock.Mock(return_value={})
        self.manager.ensure_token=mock.Mock(side_effect=U.PlatformError('expired token',401))
        with mock.patch.object(U.threading,'Thread') as thread:
            U.Manager.refresh_async(self.manager,'cline',force=True)
            thread.call_args.kwargs['target']()
        result=self.manager.quota_balance('cline',refresh=False)
        self.assertEqual((result['total_remain'],result['complete'],result['stale_count']),(None,False,2))
        self.assertEqual(result['refresh_failed'],2)
        self.assertIsNone(self.manager.balance('opencode_zen')['total_remain'])

    def test_opencode_go_usage_does_not_invent_a_wallet_balance(self):
        account=next(a for a in self.manager.accounts.values() if a.upstream=='opencode_zen')
        def transport(request,**kwargs):
            self.assertEqual(request.full_url,'https://opencode.ai/zen/go/v1/usage')
            self.assertEqual(request.get_header('Authorization'),'Bearer zen')
            return io.BytesIO(json.dumps({'usage':{'rolling':{'percent':20,'resetsAt':'2026-11-01T00:00:00Z'},
                'monthly':{'percent':100,'resetsAt':'2026-11-01T00:00:00Z'}}}).encode())
        self.manager.transport=transport
        self.manager.refresh_balance(account)
        self.assertIsNone(account.view()['balance']['remain'])
        self.assertEqual(account.view()['quota']['fiveHour']['remaining_percent'],80)
        self.assertEqual(account.view()['quota']['monthly']['remaining_percent'],0)
        self.manager.transport=mock.Mock(side_effect=U.PlatformError('no longer entitled',403))
        self.manager.refresh_balance(account)
        self.assertTrue(account.view()['billing_status']['quota']['stale'])
        self.assertTrue(account.view()['billing_status']['subscription']['stale'])
        self.assertNotIn('monthly',self.manager.balance('opencode_zen')['quota_windows'])

    def test_console_go_usage_uses_inference_gateway_and_refreshed_account_token(self):
        uid=self.manager.import_accounts({'upstream':'opencode_zen','auth_type':'oauth',
            'access_token':'old-access','org_id':'org-one','console_gateway':{
                'url':'https://opencode.ai/inference/openai/v1','api_key':'{env:OPENCODE_CONSOLE_TOKEN}',
                'headers':{'x-opencode-org-id':'org-one'},'models':{'fixture':{}}}})[0]['uid']
        account=self.manager.accounts[uid]
        calls=[]
        def refresh(selected):
            self.assertIs(selected,account)
            selected.document['access_token']='fresh-access'
        def transport(request,**kwargs):
            calls.append(request)
            self.assertEqual(request.full_url,'https://opencode.ai/inference/go/v1/usage')
            headers={key.lower():value for key,value in request.header_items()}
            self.assertEqual(headers['authorization'],'Bearer fresh-access')
            self.assertEqual(headers['x-opencode-org-id'],'org-one')
            return io.BytesIO(b'{"usage":{"rolling":{"percent":20}}}')
        self.manager.ensure_token=mock.Mock(side_effect=refresh)
        self.manager.transport=transport
        self.manager.refresh_balance(account)
        self.manager.ensure_token.assert_called_once_with(account)
        self.assertEqual(len(calls),1)
        self.assertEqual(account.view()['quota']['fiveHour']['remaining_percent'],80)
        self.assertIsNone(account.view()['balance']['remain'])

    def test_opencode_known_errors_are_specific_without_echoing_secrets(self):
        account=next(a for a in self.manager.accounts.values() if a.upstream=='opencode_zen')
        for status,kind,code in ((403,'FreeTierError','opencode_free_tier_restricted'),
                                 (410,'ModelDeprecated','model_deprecated')):
            with self.subTest(kind=kind):
                account.cooldowns.clear()
                detail=json.dumps({'error':{'type':kind,'message':'echo '+account.token}}).encode()
                failure=urllib.error.HTTPError('https://opencode.ai/zen/v1/chat/completions',status,kind,{},io.BytesIO(detail))
                self.manager.transport=mock.Mock(side_effect=failure)
                with self.assertRaises(U.PlatformError) as raised:
                    self.manager.open('opencode_zen','fixture',{'messages':[]},self.meta,bound_uid=account.uid)
                self.assertEqual(raised.exception.status,status)
                self.assertEqual(raised.exception.code,code)
                self.assertIn(kind,str(raised.exception))
                self.assertNotIn(account.token,str(raised.exception))
                self.assertIn(kind,account.view()['last_error'])
                self.assertNotIn('*',account.cooldowns,'a model restriction must not block other models')
                self.assertFalse(self.manager.reservations)

    def test_go_quota_and_rate_limit_do_not_block_zen_on_the_same_account(self):
        import wb_device_auth
        gateway=wb_device_auth.console_gateway({'provider':{
            name:{'api':'https://opencode.ai/inference/'+path+'/v1','options':{'apiKey':'tenant-key'},
                  'models':{'fixture':{'cost':{'input':1,'output':2}},'promo':{'cost':{'input':0,'output':0}}}}
            for name,path in (('opencode','openai'),('opencode-go','go/openai'))}})
        uid=self.manager.import_accounts({'upstream':'opencode_zen','auth_type':'oauth','access_token':'current',
            'console_gateway':gateway})[0]['uid']
        account=self.manager.accounts[uid]
        self.assertEqual(self.manager.model('opencode_zen','go/promo')['billing_mode'],'free')
        account.document.update(quota={'weekly':{'remaining_percent':0,'reset_at':time.time()+60}},
            billing_status={'quota':{'stale':False}})
        meta=self.manager.model('opencode_zen','go/fixture')
        with self.assertRaises(U.PlatformError):
            self.manager.reserve('opencode_zen','go/fixture',meta,'','',1,bound_uid=uid)
        chosen,ticket=self.manager.reserve('opencode_zen','fixture',meta,'','',1,bound_uid=uid)
        self.assertIs(chosen,account);self.manager.release(ticket)
        account.document['billing_status']['quota']['stale']=True
        chosen,ticket=self.manager.reserve('opencode_zen','go/fixture',meta,'','',1,bound_uid=uid)
        self.manager.release(ticket)
        failure=urllib.error.HTTPError('https://opencode.ai/inference/go/openai/v1/chat/completions',429,'limited',{},io.BytesIO(b'INFERENCE_CAP_ERROR'))
        self.manager.transport=mock.Mock(side_effect=failure)
        with self.assertRaises(U.PlatformError):
            self.manager.open('opencode_zen','go/fixture',{'messages':[]},meta,bound_uid=uid)
        self.assertIn('go/*',account.cooldowns)
        self.assertNotIn('*',account.cooldowns)
        chosen,ticket=self.manager.reserve('opencode_zen','fixture',meta,'','',1,bound_uid=uid)
        self.manager.release(ticket)

    def test_free_tier_request_rejection_does_not_rotate_other_accounts(self):
        self.manager.import_accounts({'upstream':'opencode_zen','api_key':'second-zen'})
        failure=U.PlatformError('FreeTierError',403,'opencode_free_tier_restricted')
        with mock.patch.object(self.manager,'open',side_effect=failure) as opened:
            with self.assertRaises(U.PlatformError):
                API._open(self.manager,'opencode_zen','fixture',{},self.meta,'session','owner',None)
        self.assertEqual(opened.call_count,1)

    def test_billing_failure_marks_cached_quota_stale_without_blocking_other_queries(self):
        account=self.cline[0]
        account.document.update(balance={'remain':5,'unit':'credits'}, quota={'monthly':{'remaining_percent':90}},
            billing_status={'balance':{'updated_at':1},'quota':{'updated_at':1}})
        def request(upstream,path,*args,**kwargs):
            if path=='/users/me/plan':return {'plan':{'id':'pass','displayName':'ClinePass'}}
            raise U.PlatformError('unavailable',403)
        self.manager.request_json=request
        self.manager.refresh_balance(account)
        view=account.view()
        self.assertEqual(view['subscription']['name'],'ClinePass')
        self.assertEqual(view['balance']['remain'],5)
        self.assertTrue(view['billing_status']['balance']['stale'])
        self.assertTrue(view['billing_status']['quota']['stale'])
        self.assertFalse(self.manager.balance('cline')['complete'])
        self.assertNotIn('monthly',self.manager.balance('cline')['quota_windows'])

    def test_registry_cache_survives_restart_and_invalid_timestamp(self):
        registry={'opencode':{'models':{'big-pickle':{'cost':{'input':0,'output':0}}}}}
        self.manager.transport=lambda *args,**kwargs:io.BytesIO(json.dumps(registry).encode())
        self.assertFalse(self.manager.registry_metadata()[1])
        cache_path=os.path.join(self.manager.root,'client-model-metadata.json')
        with open(cache_path) as file:cached=json.load(file)
        cached['updated_at']='invalid'
        with open(cache_path,'w') as file:json.dump(cached,file)
        manager=U.Manager(self.accounts,self.db,transport=mock.Mock(side_effect=OSError('offline')))
        providers,stale=manager.registry_metadata()
        self.assertTrue(stale)
        self.assertEqual(providers['opencode']['models']['big-pickle']['cost']['output'],0)

    def test_model_revision_changes_when_scope_changes(self):
        previous=self.manager.snapshot()['models_revision']
        self.manager.update_account(self.cline[0].uid,{'access_scope':'subscription'})
        self.assertNotEqual(previous,self.manager.snapshot()['models_revision'])
        self.assertTrue(self.cline[0].allows('cline-free/fixture'))

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
