"""Generate envelope, incremental stream, tools, usage and failure contracts."""
import io
import json
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_commandcode as C
from wb_platforms import PlatformError

def response(events,stream=False):
    raw=io.BytesIO(b"".join(json.dumps(event).encode()+b"\n" for event in events))
    return C.ChatResponse(raw,{"model":"fixture","stream":stream},PlatformError)

FINISH={"type":"finish","finishReason":"stop","totalUsage":{"inputTokens":100,"outputTokens":2,"inputTokenDetails":{"cacheReadTokens":80}}}
class CommandTests(unittest.TestCase):
    def test_envelope_preserves_full_history_tools_and_parameters(self):
        body={"model":"fixture","max_tokens":321,"reasoning_effort":"high","messages":[
            {"role":"system","content":"SYSTEM"},{"role":"developer","content":"DEVELOPER"},
            {"role":"user","content":"first"},{"role":"assistant","content":None,"reasoning_content":"REASONING",
             "tool_calls":[{"id":"call-one","function":{"name":"lookup","arguments":'{"q":"one"}'}}]},
            {"role":"tool","tool_call_id":"call-one","content":"TOOL RESULT"},{"role":"user","content":"last"}],
            "tools":[{"type":"function","function":{"name":"lookup","parameters":{"type":"object"}}}],"tool_choice":"required"}
        value=C.envelope(body,"stable-session",PlatformError)
        self.assertEqual(value["threadId"],"stable-session")
        self.assertEqual(value["params"]["max_tokens"],321)
        self.assertEqual(value["params"]["reasoning_effort"],"high")
        self.assertEqual(value["params"]["system"][0]["text"],"SYSTEM\n")
        self.assertEqual(len(value["params"]["messages"]),4)
        result=value["params"]["messages"][2]["content"][0]
        self.assertEqual(result["toolName"],"lookup")
        self.assertEqual(result["output"]["value"],"TOOL RESULT")
        self.assertEqual(value["params"]["tool_choice"],{"type":"any"})

    def test_unsupported_options_and_blocks_fail_explicitly(self):
        for body in [{"model":"x","n":2},{"model":"x","response_format":{"type":"json_object"}},
                     {"model":"x","messages":[{"role":"user","content":[{"type":"file"}]}]},
                     {"model":"x","messages":"text"},{"model":"x","messages":[None]},
                     {"model":"x","messages":[{"role":"user","content":["text"]}]},
                     {"model":"x","messages":[{"role":"user","content":{"text":"hello"}}]},
                     {"model":"x","messages":[{"role":"assistant","tool_calls":[{"function":"invalid"}]}]}]:
            with self.assertRaises(PlatformError): C.envelope(body,"x",PlatformError)

    def test_nonstream_reasoning_tools_and_cache(self):
        value=response([{"type":"reasoning-delta","text":"THINK"},{"type":"text-delta","text":"OK"},
          {"type":"tool-input-start","id":"call-one","toolName":"lookup"},{"type":"tool-input-delta","id":"call-one","delta":'{"q":"one"}'},
          {"type":"tool-call","toolCallId":"call-one","toolName":"lookup"},dict(FINISH,finishReason="tool-calls")])
        result=json.loads(value.read())
        self.assertEqual(result["choices"][0]["message"]["reasoning_content"],"THINK")
        self.assertEqual(result["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"],'{"q":"one"}')
        self.assertEqual(result["usage"]["total_tokens"],102)
        self.assertEqual(result["usage"]["prompt_tokens_details"]["cached_tokens"],80)
        self.assertNotIn("credit",result["usage"])

    def test_stream_yields_text_before_upstream_finishes(self):
        value=response([{"type":"text-delta","text":"first"},FINISH],True)
        first=value.readline()
        self.assertIn(b"first",first)
        self.assertFalse(value.saw_finish)
        rest=b"".join(value)
        self.assertIn(b"[DONE]",rest)

    def test_incomplete_stream_keeps_measured_partial_usage(self):
        value=response([{"type":"text-delta","text":"first"},dict(FINISH,type="finish-step")],True)
        with self.assertRaises(PlatformError): b"".join(value)
        self.assertEqual(value.current_usage["total_tokens"],102)

    def test_failure_never_produces_success_terminal(self):
        for events in [[{"type":"text-delta","text":"partial"}],
                       [{"type":"finish","finishReason":"other"}],
                       [dict(FINISH,rawFinishReason="network_error")],
                       [{"type":"error","error":{"statusCode":429}}]]:
            with self.assertRaises(PlatformError): response(events).read()

    def test_usage_only_confirmed_credits(self):
        result=C.usage({"inputTokens":1,"outputTokens":2,"creditsUsed":0.01})
        self.assertEqual(result["credit"],0.01)
        self.assertEqual(C.usage({"inputTokens":1,"outputTokens":2})["total_tokens"],3)
        self.assertIsNone(C.usage({"inputTokens":float("inf"),"outputTokens":2}))
        self.assertNotIn("credit", C.usage({"inputTokens":1,"outputTokens":2,"creditsUsed":float("nan")}))
        self.assertEqual(C.usage({"inputTokens":1,"outputTokens":2,"cachedInputTokens":10})["prompt_tokens_details"]["cached_tokens"],1)

    def test_headers_and_catalogue_are_versioned(self):
        self.assertEqual(C.headers("fixture","session")["x-session-id"],"session")
        self.assertEqual(C.headers("fixture","session")["x-command-code-version"],C.PROTOCOL_VERSION)
        models=C.builtin_models()
        self.assertTrue(models)
        self.assertTrue(all(m["catalog_source"]=="command-code@"+C.PROTOCOL_VERSION for m in models.values()))

if __name__ == "__main__": unittest.main()
