import contextlib
import copy
import errno
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from examples.ch03_tool_execution import client


def tool(**changes):
    return {'id': 'fc_one', 'type': 'function_call', 'status': 'completed',
            'call_id': 'call_one', 'name': 'read_file', 'arguments': '{"path":"README.md"}', **changes}


def message(refusal=False):
    content = {'type': 'refusal', 'refusal': '拒绝请求'} if refusal else {'type': 'output_text', 'text': '有依据的回答'}
    return {'id': 'msg_one', 'type': 'message', 'status': 'completed',
            'role': 'assistant', 'content': [content]}


def response(*items):
    return {'id': 'resp_one', 'status': 'completed', 'output': list(items)}


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'README.md').write_text('源码教学\n', encoding='utf-8')
        self.fd = client.open_root(self.root)
        self.addCleanup(os.close, self.fd)

    def output(self, item):
        return json.loads(client.dispatch(item, self.fd)['output'])

    def test_normal_and_nested_file(self):
        self.assertEqual(self.output(tool())['data']['content'], '源码教学\n')
        (self.root / 'docs').mkdir()
        (self.root / 'docs/a.md').write_text('nested', encoding='utf-8')
        result = self.output(tool(arguments='{"path":"docs/a.md"}'))
        self.assertTrue(result['ok'])
        self.assertEqual(result['data']['content'], 'nested')
        self.assertFalse(result['data']['truncated'])

    def test_unknown_function_never_dispatches(self):
        for name in ('delete_file', None, []):
            with self.subTest(name=name):
                self.assertEqual(self.output(tool(name=name))['error']['code'], 'unknown_tool')

    def test_invalid_json_and_schema(self):
        for raw in ('{', '[]', '{}', 'null', '{"path":2}', '{"path":""}',
                    '{"path":"README.md","extra":true}', '{"path":NaN}',
                    '{"path":"a","path":"b"}', None):
            with self.subTest(raw=raw):
                self.assertEqual(self.output(tool(arguments=raw))['error']['code'], 'invalid_arguments')

    def test_absolute_traversal_and_ambiguous_paths_rejected(self):
        for path in ('/etc/passwd', '../secret', 'docs/../../secret', './README.md',
                     'docs//a.md', 'README.md/', 'a\x00b', 'a\\b'):
            with self.subTest(path=path):
                result = self.output(tool(arguments=json.dumps({'path': path})))
                self.assertEqual(result['error']['code'], 'invalid_path')

    def test_io_failures_are_distinct_from_access_denials_without_raw_messages(self):
        cases = ((errno.EIO, 'io_error'), (errno.EMFILE, 'io_error'),
                 (errno.EACCES, 'file_access_denied'), (errno.EPERM, 'file_access_denied'),
                 (errno.ELOOP, 'file_access_denied'), (errno.ENOTDIR, 'file_access_denied'))
        for number, code in cases:
            with self.subTest(errno=number), patch.dict(client.REGISTRY, {
                'read_file': Mock(side_effect=OSError(number, 'private path and details'))
            }):
                result = self.output(tool())
            self.assertEqual(result, {'ok': False, 'error': {'code': code}})

    def test_missing_file_is_tool_error(self):
        self.assertEqual(self.output(tool(arguments='{"path":"missing"}'))['error']['code'], 'file_not_found')

    def test_symlinks_rejected_for_leaf_and_intermediate_directory(self):
        with tempfile.TemporaryDirectory() as outside:
            Path(outside, 'secret').write_text('never read this', encoding='utf-8')
            (self.root / 'leaf').symlink_to(Path(outside, 'secret'))
            (self.root / 'dir').symlink_to(outside, target_is_directory=True)
            for path in ('leaf', 'dir/secret'):
                result = self.output(tool(arguments=json.dumps({'path': path})))
                self.assertFalse(result['ok'])
                self.assertNotIn('never read this', json.dumps(result))
        (self.root / 'local').symlink_to('README.md')
        self.assertFalse(self.output(tool(arguments='{"path":"local"}'))['ok'])

    def test_directory_and_fifo_are_rejected_without_blocking(self):
        (self.root / 'folder').mkdir()
        os.mkfifo(self.root / 'pipe')
        for path in ('folder', 'pipe'):
            with self.subTest(path=path):
                self.assertEqual(self.output(tool(arguments=json.dumps({'path': path})))['error']['code'], 'not_regular_file')

    def test_truncation_preserves_utf8_boundary_and_exact_limit(self):
        (self.root / 'README.md').write_text('中' * 2000, encoding='utf-8')
        data = self.output(tool())['data']
        self.assertTrue(data['truncated'])
        self.assertEqual(data['returned_bytes'], 4095)
        self.assertEqual(data['content'], '中' * 1365)
        (self.root / 'README.md').write_bytes(b'a' * client.MAX_BYTES)
        self.assertFalse(self.output(tool())['data']['truncated'])
        (self.root / 'README.md').write_bytes(b'')
        self.assertEqual(self.output(tool())['data']['content'], '')

    def test_read_budget_is_bounded_even_for_large_files(self):
        (self.root / 'README.md').write_bytes(b'x' * (client.MAX_BYTES * 10))
        with patch.object(client.os, 'read', wraps=os.read) as read:
            result = self.output(tool())
        self.assertTrue(result['data']['truncated'])
        self.assertEqual(sum(call.args[1] for call in read.call_args_list), client.MAX_BYTES + 1)
        self.assertEqual(result['data']['returned_bytes'], client.MAX_BYTES)

    def test_unsupported_platform_fails_without_opening_root(self):
        with patch.object(client.os, 'supports_dir_fd', set()), patch.object(client.os, 'open') as opened:
            with self.assertRaises(client.llm.ProtocolError):
                client.open_root(self.root)
        opened.assert_not_called()

    def test_http_diagnostics_keep_status_without_response_details(self):
        for status in (401, 429, 500):
            error = client.urllib.error.HTTPError('https://api.openai.com/v1/responses',
                status, 'private reason', {}, io.BytesIO(b'private body'))
            self.addCleanup(error.close)
            stderr = io.StringIO()
            with self.subTest(status=status), patch.object(client, 'run', side_effect=error):
                with contextlib.redirect_stderr(stderr):
                    self.assertEqual(client.main(['--model', 'model', '--root', str(self.root)]), 1)
                self.assertEqual(stderr.getvalue(), f'Request failed: HTTP {status}\n')

    def test_invalid_utf8_is_not_silently_replaced(self):
        for data in (b'\xff', b'\xe4\xb8', b'a\xff' + b'x' * client.MAX_BYTES):
            (self.root / 'README.md').write_bytes(data)
            self.assertEqual(self.output(tool())['error']['code'], 'invalid_utf8')

    def test_root_symlink_is_rejected(self):
        (self.root / 'alias').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            client.open_root(self.root / 'alias')

    def test_full_history_and_call_id_are_preserved_without_mutation(self):
        reasoning = {'id': 'rs_one', 'type': 'reasoning', 'summary': [], 'encrypted_content': 'opaque'}
        first = response(reasoning, message(), tool())
        original = copy.deepcopy(first)
        transport = Mock(side_effect=[first, response(message())])
        result = client.run('test-model', self.root, transport=transport)
        self.assertEqual(result['stop_reason'], 'completed')
        self.assertEqual(transport.call_count, 2)
        initial = transport.call_args_list[0].args[0]
        followup = transport.call_args_list[1].args[0]
        self.assertFalse(initial['store'])
        self.assertEqual(initial['include'], ['reasoning.encrypted_content'])
        self.assertEqual(followup['input'][:1], initial['input'])
        self.assertEqual(followup['input'][1:4], first['output'])
        output = followup['input'][4]
        self.assertEqual(output['type'], 'function_call_output')
        self.assertEqual(output['call_id'], 'call_one')
        self.assertEqual(json.loads(output['output'])['data']['content'], '源码教学\n')
        self.assertNotIn('previous_response_id', followup)
        self.assertEqual(first, original)

    def test_each_call_gets_result_even_when_one_fails(self):
        transport = Mock(side_effect=[response(tool(name='unknown'),
            tool(id='fc_two', call_id='call_two')), response(message())])
        result = client.run('model', self.root, transport=transport)
        self.assertEqual([item['call_id'] for item in result['tool_outputs']], ['call_one', 'call_two'])
        self.assertFalse(json.loads(result['tool_outputs'][0]['output'])['ok'])
        self.assertTrue(json.loads(result['tool_outputs'][1]['output'])['ok'])

    def test_refusal_or_no_call_never_opens_root_or_sends_followup(self):
        for output in (response(message()), response(message(refusal=True), tool())):
            transport = Mock(return_value=output)
            with patch.object(client, 'open_root', side_effect=AssertionError('file execution')):
                result = client.run('model', '/not-opened', transport=transport)
            self.assertEqual(transport.call_count, 1)
            self.assertEqual(result['tool_outputs'], [])

    def test_second_call_is_reported_but_never_executed(self):
        transport = Mock(side_effect=[response(tool()), response(tool())])
        with patch.object(client, 'dispatch', wraps=client.dispatch) as dispatch:
            result = client.run('model', self.root, transport=transport)
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(result['stop_reason'], 'further_calls_not_executed')

    def test_second_refusal_is_terminal(self):
        transport = Mock(side_effect=[response(tool()), response(message(refusal=True))])
        result = client.run('model', self.root, transport=transport)
        self.assertEqual(result['stop_reason'], 'refusal')

    def test_corrupt_wire_fields_stop_before_dispatch_or_followup(self):
        changes = [{'name': value} for value in (None, [], '', '  ')]
        changes += [{'arguments': value} for value in (None, {}, [])]
        for change in changes:
            transport = Mock(return_value=response(tool(**change)))
            with self.subTest(change=change), patch.object(client, 'dispatch') as dispatch:
                with self.assertRaises(client.llm.ProtocolError):
                    client.run('model', self.root, transport=transport)
            dispatch.assert_not_called()
            self.assertEqual(transport.call_count, 1)

    def test_malformed_json_string_still_gets_a_paired_tool_error(self):
        transport = Mock(side_effect=[response(tool(arguments='{')), response(message())])
        result = client.run('model', self.root, transport=transport)
        self.assertEqual(transport.call_count, 2)
        output = result['tool_outputs'][0]
        self.assertEqual(output['call_id'], 'call_one')
        self.assertEqual(json.loads(output['output'])['error']['code'], 'invalid_arguments')

    def test_invalid_identity_or_incomplete_response_stops_before_execution(self):
        invalid = [response(tool(call_id='')), response(tool(), tool(id='other')),
                   response(tool(status='in_progress')),
                   {**response(tool()), 'status': 'incomplete'}]
        for body in invalid:
            with self.subTest(body=body), patch.object(client, 'dispatch', side_effect=AssertionError('execute')):
                with self.assertRaises(client.llm.ProtocolError):
                    client.run('model', self.root, transport=Mock(return_value=body))

    def test_offline_demo_and_show_request_need_no_credentials(self):
        with patch.object(client.llm, 'headers', side_effect=AssertionError('network')):
            with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(client.main(['--demo']), 0)
            self.assertEqual(json.loads(out.getvalue())['stop_reason'], 'completed')
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(client.main(['--model', 'model', '--show-request']), 0)
            self.assertEqual(json.loads(out.getvalue())['model'], 'model')

    def test_live_requires_explicit_root_before_network(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            client.main(['--model', 'model'])
        self.assertEqual(caught.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
