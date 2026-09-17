"""Chapter 1: three text APIs, explicit protocol handling, standard library only."""

import argparse
import codecs
import json
import http.client
import re
import os
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field


SYSTEM = "只依据提供的信息回答；资料不足时说明缺口。"
PROMPT = "请解释 agent-decode 的用途，并给出依据。"
URLS = {
    "chat": "https://api.openai.com/v1/chat/completions",
    "responses": "https://api.openai.com/v1/responses",
    "messages": "https://api.anthropic.com/v1/messages",
}


class ProtocolError(ValueError):
    def __init__(self, message, result=None, details=None):
        self.result = result
        self.details = details or {}
        suffix = " " + json.dumps(self.details) if self.details else ""
        super().__init__(message + suffix)


def error_details(body):
    """Keep bounded machine identifiers, never upstream free-form messages."""
    source = body.get("error") or body
    details = {key: source.get(key) for key in ("type", "code", "param", "request_id")}
    details["reason"] = (body.get("incomplete_details") or {}).get("reason")
    return {key: value for key, value in details.items()
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:\[\]-]{1,100}", value)}


@dataclass
class Result:
    text: str = ""
    terminal: str = ""
    usage: dict = field(default_factory=dict)
    refused: bool = False


def build_request(api, model, prompt, stream=False):
    body = {"model": model, "stream": stream}
    if api == "chat":
        body.update(messages=[{"role": "system", "content": SYSTEM},
                              {"role": "user", "content": prompt}],
                    max_completion_tokens=512)
        if stream:
            body["stream_options"] = {"include_usage": True}
    elif api == "responses":
        body.update(instructions=SYSTEM, input=prompt,
                    max_output_tokens=512, store=False)
    elif api == "messages":
        body.update(system=SYSTEM, messages=[{"role": "user", "content": prompt}],
                    max_tokens=512)
    else:
        raise ProtocolError(f"Unknown API: {api}")
    return body


def headers(api):
    key_name = "ANTHROPIC_API_KEY" if api == "messages" else "OPENAI_API_KEY"
    key = os.environ.get(key_name)
    if not key:
        raise ProtocolError(f"Missing {key_name}")
    auth = ({"x-api-key": key, "anthropic-version": "2023-06-01"}
            if api == "messages" else {"Authorization": f"Bearer {key}"})
    return {"Content-Type": "application/json", **auth}


def sse_events(chunks):
    """Decode bytes -> UTF-8 lines -> complete SSE events, never JSON per chunk."""
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    pending = ""
    event, data = "message", []
    skip_lf = False
    for chunk in chunks:
        for char in decoder.decode(chunk):
            if skip_lf:
                skip_lf = False
                if char == "\n":
                    continue
            if char not in "\r\n":
                pending += char
                continue
            skip_lf = char == "\r"
            line, pending = pending, ""
            if not line:
                if data:
                    yield event, "\n".join(data)
                event, data = "message", []
            elif not line.startswith(":"):
                name, separator, value = line.partition(":")
                if separator and value.startswith(" "):
                    value = value[1:]
                if name == "event":
                    event = value
                elif name == "data":
                    data.append(value)
    pending += decoder.decode(b"", final=True)
    # SSE dispatch requires an empty line, even at EOF.
    if pending or data:
        raise ProtocolError("Truncated SSE event at transport EOF")


def response_text(response):
    text, refused = "", False
    for item in response.get("output", []):
        if item["type"] == "reasoning":
            continue  # Metadata is not user-visible answer text.
        if item["type"] != "message":
            raise ProtocolError(f"Unsupported output item: {item['type']}")
        for block in item["content"]:
            if block["type"] == "output_text":
                text += block["text"]
            elif block["type"] == "refusal":
                text += block["refusal"]
                refused = True
            else:
                raise ProtocolError(f"Unsupported content: {block['type']}")
    return text, refused


def parse_response(api, body):
    result = Result(usage=body.get("usage") or {})
    if body.get("error") and (api != "responses" or "status" not in body):
        raise ProtocolError("API returned an error", result, error_details(body))
    if api == "chat":
        if len(body["choices"]) != 1:
            raise ProtocolError("Expected exactly one choice")
        choice = body["choices"][0]
        result.terminal = choice["finish_reason"]
        message = choice["message"]
        if message.get("tool_calls") or message.get("function_call") or message.get("audio"):
            raise ProtocolError("This chapter only supports text output")
        result.text = (message.get("content") or "") + (message.get("refusal") or "")
        result.refused = bool(message.get("refusal"))
        success = result.terminal == "stop"
    elif api == "responses":
        result.terminal = body["status"]
        result.text, result.refused = response_text(body)
        success = result.terminal == "completed" and not body.get("error")
    else:
        result.terminal = body["stop_reason"]
        for block in body["content"]:
            if block["type"] != "text":
                raise ProtocolError(f"Unsupported content: {block['type']}")
            result.text += block["text"]
        success = result.terminal in ("end_turn", "stop_sequence")
    if not success:
        raise ProtocolError(f"Generation did not complete successfully: {result.terminal}",
                            result, error_details(body))
    return result


def parse_stream(api, chunks, on_text=lambda text: None):
    result = Result()
    terminal_seen = False

    def append(text, refused=False):
        result.text += text
        result.refused |= refused
        on_text(text)

    try:
        for event, raw in sse_events(chunks):
            if terminal_seen:
                raise ProtocolError("Unexpected event after protocol terminal")
            if api == "chat" and raw == "[DONE]":
                terminal_seen = True
                continue
            body = json.loads(raw)
            kind = body.get("type", event)
            if body.get("error") or kind == "error":
                raise ProtocolError("API error inside HTTP 200 stream", result, error_details(body))
            if api == "chat":
                if body.get("usage"):
                    result.usage = body["usage"]
                choices = body.get("choices", [])
                if len(choices) > 1:
                    raise ProtocolError("Expected exactly one choice")
                for choice in choices:
                    if choice.get("index", 0) != 0:
                        raise ProtocolError("Unexpected choice index")
                    delta = choice.get("delta", {})
                    if delta.get("tool_calls") or delta.get("function_call") or delta.get("audio"):
                        raise ProtocolError("This chapter only supports text output")
                    append(delta.get("content") or "")
                    if delta.get("refusal"):
                        append(delta["refusal"], refused=True)
                    if choice.get("finish_reason"):
                        result.terminal = choice["finish_reason"]
            elif api == "responses":
                if kind in ("response.output_text.delta", "response.refusal.delta"):
                    append(body["delta"], refused=kind == "response.refusal.delta")
                elif kind == "response.completed":
                    final = parse_response(api, body["response"])
                    if final.text != result.text:
                        raise ProtocolError("Final response text disagrees with streamed deltas")
                    result.terminal, result.usage = final.terminal, final.usage
                    terminal_seen = True
                elif kind in ("response.failed", "response.incomplete"):
                    final = body.get("response") or {}
                    result.terminal = final.get("status") or kind.removeprefix("response.")
                    result.usage.update(final.get("usage") or {})
                    raise ProtocolError(f"Generation ended with {kind}", result, error_details(final))
                elif kind in ("response.output_item.added", "response.output_item.done"):
                    if body["item"]["type"] not in ("message", "reasoning"):
                        raise ProtocolError("Unsupported non-text output item")
                elif kind in ("response.content_part.added", "response.content_part.done"):
                    if body["part"]["type"] not in ("output_text", "refusal"):
                        raise ProtocolError("Unsupported content part")
                elif kind not in ("response.created", "response.in_progress",
                                  "response.output_text.done", "response.refusal.done"):
                    raise ProtocolError(f"Unsupported stream event: {kind}")
            else:
                if kind == "message_start":
                    result.usage.update(body["message"].get("usage") or {})
                elif kind == "content_block_start":
                    block = body["content_block"]
                    if block["type"] != "text":
                        raise ProtocolError("This chapter only supports text blocks")
                    append(block.get("text", ""))
                elif kind == "content_block_delta":
                    if body["delta"]["type"] != "text_delta":
                        raise ProtocolError("Unsupported non-text delta")
                    append(body["delta"]["text"])
                elif kind == "message_delta":
                    result.terminal = body["delta"].get("stop_reason") or result.terminal
                    result.usage.update(body.get("usage") or {})
                elif kind == "message_stop":
                    terminal_seen = True
                elif kind not in ("content_block_stop", "ping"):
                    raise ProtocolError(f"Unsupported stream event: {kind}")
        allowed = {"chat": ("stop",), "responses": ("completed",),
                   "messages": ("end_turn", "stop_sequence")}
        if not terminal_seen or result.terminal not in allowed[api]:
            raise ProtocolError(f"Missing successful protocol terminal ({result.terminal or 'none'})")
        return result
    except ProtocolError as error:
        if error.result is None:
            error.result = result
        raise
    except (ValueError, KeyError, TypeError, OSError, http.client.HTTPException) as error:
        raise ProtocolError(f"Stream failed: {type(error).__name__}", result) from error


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        raise ProtocolError("Redirect rejected; credentials must remain at the official endpoint")


def call(api, request, on_text=lambda text: None):
    req = urllib.request.Request(URLS[api], json.dumps(request).encode(), headers(api))
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(req, timeout=60) as response:
        if request["stream"]:
            if response.headers.get_content_type() != "text/event-stream":
                raise ProtocolError("Expected text/event-stream")
            return parse_stream(api, iter(lambda: response.read1(4096), b""), on_text)
        return parse_response(api, json.load(response))


def demo(api, stream, on_text=lambda text: None):
    """Synthetic protocol data: not captured model output and not a live API test."""
    text = "我没有读取仓库文件，无法确认其用途。"
    if api == "chat":
        body = {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 12}}
        events = [{"choices": [{"delta": {"content": text}, "finish_reason": None}]},
                  {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                  {"choices": [], "usage": body["usage"]}, "[DONE]"]
    elif api == "responses":
        body = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 10, "output_tokens": 12}}
        events = [{"type": "response.output_text.delta", "delta": text},
                  {"type": "response.output_text.done", "text": text},
                  {"type": "response.completed", "response": body}]
    else:
        body = {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}],
                "usage": {"input_tokens": 10, "output_tokens": 12}}
        events = [{"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
                  {"type": "content_block_start", "index": 0,
                   "content_block": {"type": "text", "text": ""}},
                  {"type": "content_block_delta", "index": 0,
                   "delta": {"type": "text_delta", "text": text}},
                  {"type": "content_block_stop", "index": 0},
                  {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                   "usage": {"output_tokens": 12}}, {"type": "message_stop"}]
    if not stream:
        return parse_response(api, body)
    wire = "".join("data: " + (e if isinstance(e, str) else json.dumps(e, ensure_ascii=False))
                   + "\n\n" for e in events).encode()
    return parse_stream(api, (wire[i:i + 7] for i in range(0, len(wire), 7)), on_text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, choices=URLS)
    parser.add_argument("--model", help="Model ID available to your account (required for live calls)")
    parser.add_argument("--prompt", default=PROMPT)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--demo", action="store_true", help="Replay synthetic data offline")
    parser.add_argument("--show-request", action="store_true", help="Print body only; never send")
    args = parser.parse_args(argv)
    if not args.model and not args.demo:
        parser.error("--model is required unless --demo is selected")
    request = build_request(args.api, args.model or "synthetic-demo-model", args.prompt, args.stream)
    if args.show_request:
        print(json.dumps(request, ensure_ascii=False, indent=2))
        return 0
    try:
        if args.demo:
            print("[DEMO: synthetic fixtures, no network or model call]", file=sys.stderr)
        on_text = lambda text: print(text, end="", flush=True)
        result = (demo(args.api, args.stream, on_text) if args.demo
                  else call(args.api, request, on_text))
        if args.stream:
            print()
            metadata = asdict(result)
            del metadata["text"]
            print(json.dumps(metadata, ensure_ascii=False), file=sys.stderr)
        else:
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError, http.client.HTTPException) as error:
        # Do not print upstream response bodies, request headers, or credentials.
        if isinstance(error, ProtocolError) and error.result is not None:
            partial = asdict(error.result)
            if args.stream:
                print()
                del partial["text"]  # Deltas have already been printed, and remain partial.
            print("[PARTIAL RESULT; request failed] " + json.dumps(partial, ensure_ascii=False),
                  file=sys.stderr)
        description = str(error) if isinstance(error, (ProtocolError, urllib.error.HTTPError)) else type(error).__name__
        print(f"Request failed: {description}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
