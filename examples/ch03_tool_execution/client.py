"""Chapter 3: execute one batch of tools, submit results once, then stop."""

import argparse
import codecs
import copy
import errno
import http.client
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from examples.ch02_tool_call import client as tools

llm = tools.llm
MAX_BYTES = 4096


class ToolError(ValueError):
    pass


def build_request(model, prompt=tools.PROMPT):
    request = tools.build_request(model, prompt)
    request['input'] = [{'role': 'user', 'content': prompt}]
    request['include'] = ['reasoning.encrypted_content']
    return request


def inspect_response(body):
    """Reuse C02 envelope validation, but leave function validation to dispatch."""
    checked = copy.deepcopy(body)
    calls = []
    if isinstance(checked, dict) and isinstance(checked.get('output'), list):
        for item in checked['output']:
            if isinstance(item, dict) and item.get('type') == 'function_call':
                tools.require(tools.identifier(item.get('name')), 'Function name must be a nonempty string')
                tools.require(isinstance(item.get('arguments'), str), 'Function arguments must be a JSON string')
                calls.append(copy.deepcopy(item))
                # C02 validates identity/status; C03 reports argument/name errors per call.
                item['name'], item['arguments'] = 'read_file', '{}'
    result = tools.parse_response(checked)
    result['calls'] = calls
    del result['execution']  # C02's inspection-only marker is not a C03 execution report.
    return result


def open_root(root):
    if (os.open not in os.supports_dir_fd or
            not all(hasattr(os, flag) for flag in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK'))):
        raise llm.ProtocolError('This example requires POSIX descriptor-relative file access')
    return os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def read_file(arguments, root_fd):
    if (not isinstance(arguments, dict) or set(arguments) != {'path'} or
            not isinstance(arguments['path'], str) or not arguments['path']):
        raise ToolError('invalid_arguments')
    path = arguments['path']
    parts = path.split('/')
    if '\x00' in path or '\\' in path or any(part in ('', '.', '..') for part in parts):
        raise ToolError('invalid_path')
    directory = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ToolError('not_regular_file')
            data = bytearray()
            while len(data) <= MAX_BYTES:
                chunk = os.read(fd, MAX_BYTES + 1 - len(data))
                if not chunk:
                    break
                data.extend(chunk)
        finally:
            os.close(fd)
    finally:
        os.close(directory)
    truncated = len(data) > MAX_BYTES
    # Incomplete trailing UTF-8 is dropped only at a deliberate byte cutoff.
    decoder = codecs.getincrementaldecoder('utf-8')('strict')
    content = decoder.decode(bytes(data[:MAX_BYTES]), final=not truncated)
    return {'path': path, 'content': content, 'truncated': truncated,
            'returned_bytes': len(content.encode('utf-8')), 'byte_limit': MAX_BYTES}


REGISTRY = {'read_file': read_file}


def dispatch(call, root_fd):
    try:
        name = call.get('name')
        if not isinstance(name, str) or name not in REGISTRY:
            raise ToolError('unknown_tool')
        raw = call.get('arguments')
        if not isinstance(raw, str):
            raise ToolError('invalid_arguments')
        try:
            arguments = json.loads(raw, parse_constant=tools.reject_constant,
                                   object_pairs_hook=tools.argument_object)
        except ValueError:
            raise ToolError('invalid_arguments') from None
        result = {'ok': True, 'data': REGISTRY[name](arguments, root_fd)}
    except ToolError as error:
        result = {'ok': False, 'error': {'code': str(error)}}
    except UnicodeDecodeError:
        result = {'ok': False, 'error': {'code': 'invalid_utf8'}}
    except FileNotFoundError:
        result = {'ok': False, 'error': {'code': 'file_not_found'}}
    except OSError as error:
        code = ('file_access_denied' if error.errno in
                (errno.EACCES, errno.EPERM, errno.ELOOP, errno.ENOTDIR) else 'io_error')
        result = {'ok': False, 'error': {'code': code}}
    return {'type': 'function_call_output', 'call_id': call['call_id'],
            'output': json.dumps(result, ensure_ascii=False)}


def call(request):
    req = urllib.request.Request(llm.URLS['responses'], json.dumps(request).encode(), llm.headers('responses'))
    with urllib.request.build_opener(llm.NoRedirect).open(req, timeout=60) as response:
        return json.load(response)


def run(model, root, prompt=tools.PROMPT, transport=call):
    request = build_request(model, prompt)
    first_body = transport(request)
    first = inspect_response(first_body)
    report = {'first': first, 'tool_outputs': [], 'second': None, 'stop_reason': 'no_tool_calls'}
    if first['refusals']:
        report['stop_reason'] = 'refusal'
        return report
    if not first['calls']:
        return report
    root_fd = open_root(root)
    try:
        report['tool_outputs'] = [dispatch(item, root_fd) for item in first['calls']]
    finally:
        os.close(root_fd)
    followup = copy.deepcopy(request)
    # Keep ALL original output, including opaque reasoning, not the inspection view.
    followup['input'] += copy.deepcopy(first_body['output']) + report['tool_outputs']
    second = inspect_response(transport(followup))
    report['second'] = second
    report['stop_reason'] = ('refusal' if second['refusals'] else
                             'further_calls_not_executed' if second['calls'] else 'completed')
    return report


def demo():
    """Synthetic responses; a real local read inside a temporary sample directory."""
    first = {'id': 'resp_demo_1', 'status': 'completed', 'output': [{
        'id': 'fc_demo', 'type': 'function_call', 'status': 'completed',
        'call_id': 'call_demo', 'name': 'read_file', 'arguments': '{"path":"README.md"}'}]}

    def transport(request):
        if len(request['input']) == 1:
            return first
        data = json.loads(request['input'][-1]['output'])['data']
        return {'id': 'resp_demo_2', 'status': 'completed', 'output': [{
            'id': 'msg_demo', 'type': 'message', 'status': 'completed', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': '模拟回答，引用实际工具结果：' + data['content']}]}]}

    with tempfile.TemporaryDirectory() as root:
        Path(root, 'README.md').write_text('agent-decode 是通过源码学习 Agent 原理的教学项目。\n', encoding='utf-8')
        return run('synthetic-demo-model', root, transport=transport)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model')
    parser.add_argument('--root', help='Explicit trusted sample directory; its files may be sent to the API')
    parser.add_argument('--prompt', default=tools.PROMPT)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--show-request', action='store_true')
    args = parser.parse_args(argv)
    if not args.demo and not args.model:
        parser.error('--model is required unless --demo is selected')
    if args.show_request:
        print(json.dumps(build_request(args.model or 'synthetic-demo-model', args.prompt), ensure_ascii=False, indent=2))
        return 0
    if not args.demo and not args.root:
        parser.error('--root is required for live execution')
    try:
        if args.demo:
            print('[DEMO: synthetic model responses; real temporary-file read; no network]', file=sys.stderr)
        result = demo() if args.demo else run(args.model, args.root, args.prompt)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['stop_reason'] in ('completed', 'no_tool_calls') else 1
    except (ValueError, KeyError, TypeError, OSError, http.client.HTTPException) as error:
        description = (f'HTTP {error.code}' if isinstance(error, urllib.error.HTTPError) else
                       str(error) if isinstance(error, llm.ProtocolError) else type(error).__name__)
        print(f'Request failed: {description}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
