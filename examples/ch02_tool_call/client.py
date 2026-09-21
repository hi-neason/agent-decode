"""Chapter 2: request a function call, inspect it, and stop before execution."""

import argparse
import http.client
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

# Use the package name so both chapters' client.py modules remain distinct.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from examples.ch01_llm import client as llm


PROMPT = "请读取 README.md，解释 agent-decode 的用途。"


def build_request(model, prompt=PROMPT):
    request = llm.build_request("responses", model, prompt, stream=False)
    request.update(
        instructions="需要仓库事实时请求读取文件；未获得结果前不要声称已经读取。",
        tools=[{
            "type": "function",
            "name": "read_file",
            "description": "请求读取仓库内的文本文件，以文件内容作为回答依据。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "仓库内的相对文件路径"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            "strict": True,
        }],
        tool_choice="auto",
        parallel_tool_calls=False,
    )
    return request


def require(condition, message):
    if not condition:
        raise llm.ProtocolError(message)


def identifier(value):
    return isinstance(value, str) and bool(value.strip())


def reject_constant(value):
    raise llm.ProtocolError("Function arguments contain a non-JSON numeric constant")


def argument_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Function arguments contain duplicate JSON keys")
        result[key] = value
    return result


def parse_response(body):
    """Parse complete output items; arguments are data awaiting host validation."""
    require(isinstance(body, dict), "Expected a Response object")
    if body.get("error"):
        # Do not log the provider's free-form error message or the raw response.
        error = body["error"]
        require(isinstance(error, dict), "Invalid error envelope")
        raise llm.ProtocolError("Response contains an API error", details=llm.error_details(body))
    if body.get("status") != "completed":
        details = body.get("incomplete_details")
        require(details is None or isinstance(details, dict), "Invalid incomplete_details")
        raise llm.ProtocolError("Response is not completed", details=llm.error_details(body))
    require(identifier(body.get("id")), "Response id must be a nonempty string")
    require(isinstance(body.get("output"), list), "Response output must be an array")
    require(body.get("usage") is None or isinstance(body["usage"], dict), "Invalid usage object")
    result = {"response_id": body["id"], "status": "completed", "text": "",
              "calls": [], "refusals": [], "usage": body.get("usage") or {},
              "execution": "not_executed"}
    call_ids, item_ids = set(), set()
    for item in body["output"]:
        require(isinstance(item, dict), "Output item must be an object")
        item_id = item.get("id")
        if item.get("type") != "function_call" or item_id is not None:
            require(identifier(item_id), "Output item id must be a nonempty string when provided")
            require(item_id not in item_ids, "Duplicate output item id")
            item_ids.add(item_id)
        if item.get("type") == "reasoning":
            continue  # Retained by the provider; not an answer or an executable call.
        require(item.get("status") == "completed", "Output item is not completed")
        if item.get("type") == "message":
            require(item.get("role") == "assistant", "Expected assistant output message")
            require(isinstance(item.get("content"), list), "Message content must be an array")
            for part in item["content"]:
                require(isinstance(part, dict), "Content part must be an object")
                if part.get("type") == "output_text":
                    require(isinstance(part.get("text"), str), "Output text must be a string")
                    result["text"] += part["text"]
                elif part.get("type") == "refusal":
                    require(isinstance(part.get("refusal"), str), "Refusal must be a string")
                    result["refusals"].append(part["refusal"])
                else:
                    raise llm.ProtocolError("Unsupported message content type")
        elif item.get("type") == "function_call":
            require(item.get("name") == "read_file", "Unknown function name")
            call_id = item.get("call_id")
            require(identifier(call_id), "call_id must be a nonempty string")
            require(call_id not in call_ids, "Duplicate call_id")
            call_ids.add(call_id)
            raw = item.get("arguments")
            require(isinstance(raw, str), "Function arguments must be a JSON string")
            try:
                arguments = json.loads(raw, parse_constant=reject_constant, object_pairs_hook=argument_object)
            except json.JSONDecodeError as error:
                raise llm.ProtocolError("Malformed function arguments JSON") from error
            require(isinstance(arguments, dict), "Function arguments must decode to an object")
            result["calls"].append({"item_id": item_id, "call_id": call_id,
                                    "name": item["name"], "arguments": arguments,
                                    "validation": "pending"})
        else:
            raise llm.ProtocolError("Unsupported output item type")
    return result


def call(request):
    req = urllib.request.Request(llm.URLS["responses"], json.dumps(request).encode(), llm.headers("responses"))
    opener = urllib.request.build_opener(llm.NoRedirect)
    with opener.open(req, timeout=60) as response:
        return parse_response(json.load(response))


def demo(mode):
    """Handwritten synthetic payloads, not recorded model responses."""
    message = {"id": "msg_demo", "type": "message", "status": "completed", "role": "assistant",
               "content": [{"type": "output_text", "text": "需要读取 README 才能确认仓库用途。"}]}
    tool = {"id": "fc_demo", "type": "function_call", "status": "completed",
            "call_id": "call_demo", "name": "read_file", "arguments": '{"path":"README.md"}'}
    output = {"tool": [tool], "text": [message], "mixed": [message, tool]}[mode]
    return parse_response({"id": "resp_demo", "status": "completed", "output": output})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Model ID available to your account")
    parser.add_argument("--prompt", default=PROMPT)
    parser.add_argument("--demo", choices=("tool", "text", "mixed"), help="Replay synthetic data offline")
    parser.add_argument("--show-request", action="store_true", help="Print request body without sending")
    args = parser.parse_args(argv)
    if not args.model and not args.demo:
        parser.error("--model is required unless --demo is selected")
    request = build_request(args.model or "synthetic-demo-model", args.prompt)
    if args.show_request:
        print(json.dumps(request, ensure_ascii=False, indent=2))
        return 0
    try:
        if args.demo:
            print("[DEMO: synthetic data; no network or file execution]", file=sys.stderr)
        result = demo(args.demo) if args.demo else call(request)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["refusals"]:
            print("Response contains a refusal; no tools were executed.", file=sys.stderr)
            return 1
        return 0
    except (ValueError, KeyError, TypeError, OSError, http.client.HTTPException) as error:
        if isinstance(error, urllib.error.HTTPError):
            description = f"HTTP {error.code}"
        else:
            description = str(error) if isinstance(error, llm.ProtocolError) else type(error).__name__
        print(f"Request failed: {description}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
