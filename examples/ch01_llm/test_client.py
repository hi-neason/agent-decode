import contextlib
import http.client
import io
import json
import os
import unittest
from unittest.mock import patch

import client


def wire(*events):
    return [("".join("data: " + (e if isinstance(e, str) else json.dumps(e)) + "\n\n"
                     for e in events)).encode()]


class ProtocolTests(unittest.TestCase):
    def test_sse_all_line_endings_bom_and_split_crlf(self):
        for newline in ("\r", "\n", "\r\n"):
            raw = ("\ufeff: comment" + newline + "event: answer" + newline
                   + 'data: {"text":"中文"}' + newline + newline).encode()
            with self.subTest(newline=repr(newline)):
                events = list(client.sse_events(bytes([byte]) for byte in raw))
                self.assertEqual(events, [("answer", '{"text":"中文"}')])

    def test_sse_fragmented_utf8_crlf_comments_and_multiline(self):
        data = ': heartbeat\r\nevent: answer\r\ndata: {"text":\r\ndata: "中文"}\r\n\r\n'.encode()
        events = list(client.sse_events(bytes([b]) for b in data))
        self.assertEqual(events[0][0], "answer")
        self.assertEqual(json.loads(events[0][1]), {"text": "中文"})

    def test_incomplete_sse_is_not_dispatched(self):
        for data in (b'data: {}', b'data: {}\n', b'data: "\xe4'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                list(client.sse_events([data]))

    def test_demo_parity_and_callback(self):
        for api in client.URLS:
            with self.subTest(api=api):
                parts = []
                result = client.demo(api, True, parts.append)
                self.assertEqual(result, client.demo(api, False))
                self.assertEqual("".join(parts), result.text)

    def test_chat_usage_empty_choices_after_finish(self):
        result = client.parse_stream("chat", wire(
            {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"completion_tokens": 1}}, "[DONE]"))
        self.assertEqual(result.usage, {"completion_tokens": 1})
        self.assertEqual(result.text, "ok")

    def test_terminal_is_semantic_not_transport(self):
        cases = [("chat", [{"choices": [{"delta": {}, "finish_reason": "stop"}]}]),
                 ("chat", ["[DONE]"]),
                 ("messages", [{"type": "message_delta", "delta": {"stop_reason": "end_turn"}}]),
                 ("responses", [{"type": "response.output_text.done", "text": "ok"}])]
        for api, events in cases:
            with self.subTest(api=api), self.assertRaises(client.ProtocolError):
                client.parse_stream(api, wire(*events))

    def test_failed_terminals(self):
        cases = [("chat", [{"choices": [{"delta": {}, "finish_reason": "length"}]}, "[DONE]"]),
                 ("messages", [{"type": "message_delta", "delta": {"stop_reason": "max_tokens"}},
                               {"type": "message_stop"}]),
                 ("responses", [{"type": "response.incomplete"}]),
                 ("responses", [{"type": "response.failed"}])]
        for api, events in cases:
            with self.subTest(api=api), self.assertRaises(client.ProtocolError):
                client.parse_stream(api, wire(*events))

    def test_error_inside_http_success(self):
        for api in client.URLS:
            with self.subTest(api=api), self.assertRaises(client.ProtocolError):
                client.parse_stream(api, wire({"type": "error", "error": {"message": "failed"}}))

    def test_multiple_output_blocks_and_reasoning(self):
        result = client.parse_response("responses", {"status": "completed", "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": "a"},
                                               {"type": "output_text", "text": "b"}]},
            {"type": "message", "content": [{"type": "refusal", "refusal": "c"}]}]})
        self.assertEqual(result.text, "abc")
        self.assertTrue(result.refused)
        result = client.parse_response("messages", {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": "a"}, {"type": "text", "text": "b"}]})
        self.assertEqual(result.text, "ab")

    def test_unsupported_tools_not_silent(self):
        cases = [("chat", {"choices": [{"delta": {"tool_calls": [{}]}}]}),
                 ("responses", {"type": "response.output_item.added", "item": {"type": "function_call"}}),
                 ("messages", {"type": "content_block_start", "content_block": {"type": "tool_use"}})]
        for api, event in cases:
            with self.subTest(api=api), self.assertRaises(client.ProtocolError):
                client.parse_stream(api, wire(event))

    def test_request_shapes_and_headers(self):
        chat = client.build_request("chat", "model", "question", True)
        self.assertEqual(chat["stream_options"], {"include_usage": True})
        self.assertIn("max_completion_tokens", chat)
        self.assertNotIn("stream_options", client.build_request("chat", "m", "q"))
        responses = client.build_request("responses", "model", "question")
        self.assertFalse(responses["store"])
        self.assertEqual(responses["input"], "question")
        self.assertIn("max_output_tokens", responses)
        messages = client.build_request("messages", "model", "question")
        self.assertIn("max_tokens", messages)
        self.assertEqual(messages["system"], client.SYSTEM)
        self.assertEqual(messages["messages"][0]["role"], "user")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}, clear=True):
            self.assertEqual(client.headers("messages")["anthropic-version"], "2023-06-01")

    def test_missing_credentials_and_demo_never_calls_network(self):
        with patch.dict(os.environ, {}, clear=True):
            for api in client.URLS:
                with self.subTest(api=api), self.assertRaises(client.ProtocolError):
                    client.headers(api)
            with patch.object(client, "call", side_effect=AssertionError("network")):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(client.main(["--api", "responses", "--demo", "--stream"]), 0)

    def test_show_request_does_not_include_secret(self):
        out = io.StringIO()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret-value"}), contextlib.redirect_stdout(out):
            self.assertEqual(client.main(["--api", "chat", "--model", "m", "--show-request"]), 0)
        self.assertNotIn("secret-value", out.getvalue())
        self.assertEqual(json.loads(out.getvalue())["model"], "m")

    def test_redirect_rejected(self):
        with self.assertRaises(client.ProtocolError):
            client.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.invalid")

    def test_messages_usage_is_cumulative(self):
        result = client.parse_stream("messages", wire(
            {"type": "message_start", "message": {"usage": {"input_tokens": 10, "output_tokens": 1}}},
            {"type": "message_delta", "delta": {}, "usage": {"output_tokens": 3}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 7}},
            {"type": "message_stop"}))
        self.assertEqual(result.usage, {"input_tokens": 10, "output_tokens": 7})

    def test_refusal_deltas_and_final_do_not_duplicate_text(self):
        final = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "refusal", "refusal": "Cannot help"}]}]}
        result = client.parse_stream("responses", wire(
            {"type": "response.refusal.delta", "delta": "Cannot help"},
            {"type": "response.refusal.done", "refusal": "Cannot help"},
            {"type": "response.completed", "response": final}))
        self.assertEqual(result.text, "Cannot help")
        self.assertTrue(result.refused)

    def test_nonstream_unsuccessful_status(self):
        cases = [("chat", {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}),
                 ("responses", {"status": "incomplete", "output": []}),
                 ("messages", {"stop_reason": "max_tokens", "content": []})]
        for api, body in cases:
            with self.subTest(api=api), self.assertRaises(client.ProtocolError):
                client.parse_response(api, body)

    def test_incomplete_reasons_and_partial_result_are_preserved(self):
        for reason in ("max_output_tokens", "content_filter"):
            body = {"status": "incomplete", "incomplete_details": {"reason": reason},
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "partial"}]}],
                    "usage": {"output_tokens": 3}}
            with self.subTest(reason=reason):
                with self.assertRaises(client.ProtocolError) as caught:
                    client.parse_response("responses", body)
                self.assertEqual(caught.exception.details, {"reason": reason})
                self.assertEqual(caught.exception.result.text, "partial")
                with self.assertRaises(client.ProtocolError) as caught:
                    client.parse_stream("responses", wire(
                        {"type": "response.output_text.delta", "delta": "partial"},
                        {"type": "response.incomplete", "response": body}))
                self.assertEqual(caught.exception.details["reason"], reason)
                self.assertEqual(caught.exception.result.usage, {"output_tokens": 3})

    def test_stream_error_keeps_identifiers_not_raw_messages(self):
        with self.assertRaises(client.ProtocolError) as caught:
            client.parse_stream("responses", wire(
                {"type": "response.output_text.delta", "delta": "partial"},
                {"type": "error", "code": "server_error", "param": "input",
                 "message": "private upstream message"}))
        self.assertEqual(caught.exception.details, {"type": "error", "code": "server_error", "param": "input"})
        self.assertNotIn("private upstream message", str(caught.exception))
        self.assertEqual(caught.exception.result.text, "partial")

    def test_partial_cli_output_is_labeled_and_stream_not_duplicated(self):
        for streaming in (False, True):
            out, err = io.StringIO(), io.StringIO()
            def failed_call(api, request, on_text):
                if streaming:
                    on_text("partial answer")
                raise client.ProtocolError("incomplete", client.Result(text="partial answer", usage={"output_tokens": 2}))
            with patch.object(client, "call", side_effect=failed_call), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = client.main(["--api", "responses", "--model", "m"] + (["--stream"] if streaming else []))
            self.assertEqual(code, 1)
            self.assertIn("PARTIAL RESULT", err.getvalue())
            self.assertEqual((out.getvalue() + err.getvalue()).count("partial answer"), 1)
            self.assertIn('"output_tokens": 2', err.getvalue())

    def test_incomplete_http_read_is_graceful_and_retains_stream_partial(self):
        def chunks():
            yield b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n'
            raise http.client.IncompleteRead(b"unframed", 10)
        with self.assertRaises(client.ProtocolError) as caught:
            client.parse_stream("responses", chunks())
        self.assertEqual(caught.exception.result.text, "partial")
        self.assertIn("IncompleteRead", str(caught.exception))
        with patch.object(client, "call", side_effect=http.client.IncompleteRead(b"secret", 10)), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(client.main(["--api", "chat", "--model", "m"]), 1)
        self.assertIn("IncompleteRead", err.getvalue())
        self.assertNotIn("secret", err.getvalue())


if __name__ == "__main__":
    unittest.main()
