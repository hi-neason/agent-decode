import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from examples.ch02_tool_call import client


def tool(**changes):
    return {"id": "fc_independent", "type": "function_call", "status": "completed",
            "call_id": "call_external", "name": "read_file", "arguments": '{"path":"docs/index.md"}',
            **changes}


def message():
    return {"id": "msg_independent", "type": "message", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": "需要"}, {"type": "output_text", "text": "依据"}]}


def response(*items, **changes):
    return {"id": "resp_independent", "status": "completed", "output": list(items),
            "usage": {"input_tokens": 8, "output_tokens": 5}, **changes}


class ToolRequestTests(unittest.TestCase):
    def test_request_reuses_chapter_one_and_explicit_function_schema(self):
        request = client.build_request("model")
        self.assertEqual(request["input"], client.PROMPT)
        self.assertEqual(client.build_request("model", "custom prompt")["input"], "custom prompt")
        self.assertFalse(request["stream"])
        self.assertFalse(request["store"])
        self.assertEqual(request["max_output_tokens"], 512)
        self.assertEqual(request["tool_choice"], "auto")
        self.assertFalse(request["parallel_tool_calls"])
        function = request["tools"][0]
        self.assertEqual(function["name"], "read_file")
        self.assertTrue(function["strict"])
        self.assertEqual(function["parameters"]["required"], ["path"])
        self.assertFalse(function["parameters"]["additionalProperties"])
        self.assertNotIn("function", function)

    def test_plain_text_and_no_calls_are_valid(self):
        result = client.parse_response(response(message()))
        self.assertEqual(result["text"], "需要依据")
        self.assertEqual(result["calls"], [])
        self.assertEqual(result["execution"], "not_executed")

    def test_complete_output_scan_keeps_mixed_text_calls_and_identity(self):
        result = client.parse_response(response(
            {"id": "rs_test", "type": "reasoning", "summary": []},
            tool(), message(), tool(id="fc_second", call_id="call_second")))
        self.assertEqual(result["text"], "需要依据")
        self.assertEqual(len(result["calls"]), 2)
        self.assertEqual(result["calls"][0]["item_id"], "fc_independent")
        self.assertEqual(result["calls"][0]["call_id"], "call_external")
        self.assertNotEqual(result["calls"][0]["call_id"], result["response_id"])
        self.assertEqual(result["calls"][0]["arguments"], {"path": "docs/index.md"})

    def test_call_id_cannot_be_inferred_from_item_id(self):
        for value in (None, "", "  ", 123):
            with self.subTest(value=value), self.assertRaises(client.llm.ProtocolError):
                client.parse_response(response(tool(call_id=value)))

    def test_optional_item_id_is_not_replaced_by_call_id(self):
        item = tool()
        del item["id"]
        result = client.parse_response(response(item))
        self.assertIsNone(result["calls"][0]["item_id"])
        self.assertEqual(result["calls"][0]["call_id"], "call_external")

    def test_duplicate_call_or_item_ids_are_rejected(self):
        for second in (tool(id="another_id"), tool(call_id="another_call")):
            with self.subTest(second=second), self.assertRaises(client.llm.ProtocolError):
                client.parse_response(response(tool(), second))

    def test_arguments_must_be_complete_json_object(self):
        for raw in ('{"path":', '[]', '"README.md"', 'null', '{"path":NaN}',
                    '{"path":"a","path":"b"}', {"path": "a"}):
            with self.subTest(raw=raw), self.assertRaises(client.llm.ProtocolError):
                client.parse_response(response(tool(arguments=raw)))

    def test_decoding_does_not_claim_schema_or_path_authorization(self):
        for arguments in ({"path": 123}, {"path": "../../outside"}, {}, {"path": "a", "extra": True}):
            with self.subTest(arguments=arguments):
                result = client.parse_response(response(tool(arguments=json.dumps(arguments))))
                self.assertEqual(result["calls"][0]["arguments"], arguments)
                self.assertEqual(result["calls"][0]["validation"], "pending")
                self.assertEqual(result["execution"], "not_executed")

    def test_unknown_name_output_and_unfinished_items_are_rejected(self):
        for item in (tool(name="delete_file"), tool(type="custom_tool_call"), tool(status="in_progress"),
                     tool(status=None), {**message(), "role": "user"}, {**message(), "status": "incomplete"}):
            with self.subTest(item=item), self.assertRaises(client.llm.ProtocolError):
                client.parse_response(response(item))

    def test_malformed_response_envelopes(self):
        for body in ([], None, response(id=None), response(output={}), response(output=[None]), response(usage=[])):
            with self.subTest(body=body), self.assertRaises(client.llm.ProtocolError):
                client.parse_response(body)

    def test_incomplete_and_error_keep_safe_reason(self):
        with self.assertRaises(client.llm.ProtocolError) as caught:
            client.parse_response(response(tool(), status="incomplete", incomplete_details={"reason": "max_output_tokens"}))
        self.assertEqual(caught.exception.details["reason"], "max_output_tokens")
        with self.assertRaises(client.llm.ProtocolError) as caught:
            client.parse_response(response(error={"code": "server_error", "message": "private text"}))
        self.assertIn("server_error", str(caught.exception))
        self.assertNotIn("private text", str(caught.exception))

    def test_refusal_is_explicit_and_cli_returns_failure(self):
        item = message()
        item["content"] = [{"type": "refusal", "refusal": "无法协助此请求"}]
        result = client.parse_response(response(item))
        self.assertEqual(result["refusals"], ["无法协助此请求"])
        with patch.object(client, "call", return_value=result), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(client.main(["--model", "model"]), 1)

    def test_show_request_and_demos_never_access_network_or_credentials(self):
        with patch.object(client.llm, "headers", side_effect=AssertionError("credentials")), patch.object(client, "call", side_effect=AssertionError("network")):
            for mode in ("tool", "text", "mixed"):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(client.main(["--demo", mode]), 0)
                self.assertEqual(json.loads(out.getvalue())["execution"], "not_executed")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "not-for-output"}), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(client.main(["--model", "model", "--show-request"]), 0)
            self.assertNotIn("not-for-output", out.getvalue())

    def test_missing_credentials_fail_before_network(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(client.urllib.request, "build_opener", side_effect=AssertionError("network")):
            with self.assertRaises(client.llm.ProtocolError):
                client.call(client.build_request("model"))

    def test_http_errors_keep_status_without_private_details(self):
        for status in (401, 429, 500):
            error = client.urllib.error.HTTPError(
                "https://api.openai.com/v1/responses", status, "private reason", {},
                io.BytesIO(b"private response body"))
            with self.subTest(status=status), patch.object(client, "call", side_effect=error):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    self.assertEqual(client.main(["--model", "model"]), 1)
                self.assertEqual(stderr.getvalue(), f"Request failed: HTTP {status}\n")

    def test_input_response_is_not_mutated(self):
        body = response(tool(), message())
        before = copy.deepcopy(body)
        client.parse_response(body)
        self.assertEqual(body, before)


if __name__ == "__main__":
    unittest.main()
