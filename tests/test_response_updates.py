"""Offline regressions; never use real credentials or network."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request

from test_grok import grok


class ResponseUpdates(unittest.TestCase):
    def test_default_and_explicit_model_selection(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            parser = grok.build_parser()
            self.assertEqual(parser.parse_args(['text', 'hi']).model, 'grok-4.6')
            args = parser.parse_args(['text', 'hi', '--model', 'grok-4.7', '--reasoning-effort', 'high'])
            request = grok.build_text_payload(args)
            self.assertEqual(request['model'], 'grok-4.7')
            self.assertEqual(request['reasoning']['effort'], 'high')
        with mock.patch.dict(os.environ, {'XAI_TEXT_MODEL': 'chosen-model', 'GROK_HOME': '/tmp/grok-fixture'}):
            args = grok.build_parser().parse_args(['search', 'x', 'hi'])
            self.assertEqual(args.model, 'chosen-model')
            self.assertEqual(args.auth_file, Path('/tmp/grok-fixture/auth.json'))

    def test_incomplete_sse_preserves_answer_usage_and_artifacts(self):
        response = {'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'},
                    'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'partial answer'}]}],
                    'usage': {'server_side_tool_usage_details': {'x_posts_fetched': 12}, 'cost_in_usd_ticks': 10000000}}
        event = {'type': 'response.incomplete', 'response': response}
        parsed = grok.parse_sse_response([('data: ' + json.dumps(event) + '\n').encode(), b'\n'])
        with tempfile.TemporaryDirectory() as temp:
            args = grok.build_parser().parse_args(['--cache-dir', temp, 'text', 'hello'])
            with mock.patch.object(grok, 'load_credential', return_value=grok.Credential('fake', 'api_key', 'test')), mock.patch.object(grok, 'call_responses', return_value=parsed):
                result = grok.command_text(args)
            self.assertEqual(result['answer'], 'partial answer')
            self.assertEqual(result['response_status'], 'incomplete')
            self.assertEqual(result['search_items']['x_posts_fetched'], 12)
            self.assertTrue(result['warnings'])
            self.assertEqual(json.loads((Path(result['result_path']) / 'raw-response.json').read_text()), response)

    def test_http_and_sse_redact_unlabelled_active_token(self):
        token = 'fixture-session-secret-without-api-prefix'
        exc = HTTPError('https://api.x.ai', 401, 'error', {}, io.BytesIO(json.dumps({'error': {'message': 'bad ' + token}}).encode()))
        request = Request('https://api.x.ai', headers={'Authorization': 'Bearer ' + token})
        with mock.patch.object(grok, 'urlopen', side_effect=exc):
            with self.assertRaises(grok.GrokError) as caught:
                grok.open_request(request, 1)
        self.assertNotIn(token, str(caught.exception))
        event = {'type': 'error', 'error': {'message': 'bad ' + token}}
        with self.assertRaises(grok.GrokError) as caught:
            grok.parse_sse_response([('data: ' + json.dumps(event)).encode()], token=token)
        self.assertNotIn(token, str(caught.exception))

    def test_web_limit_and_media_flags(self):
        parser = grok.build_parser()
        args = parser.parse_args(['search', 'web', 'hi', '--allow-domain', 'a,b,c,d,e,f'])
        with self.assertRaises(grok.GrokError):
            grok.build_search_tool(args)
        args = parser.parse_args(['search', 'web', 'hi', '--enable-image-search', '--enable-image-understanding'])
        tool = grok.build_search_tool(args)
        self.assertTrue(tool['enable_image_search'])
        self.assertTrue(tool['enable_image_understanding'])

    def test_text_image_input_and_sanitized_dry_run(self):
        args = grok.build_parser().parse_args(['--dry-run', 'text', 'describe', '--image', 'data:image/png;base64,AAAA'])
        request = grok.build_text_payload(args)
        self.assertEqual(request['input'][0]['content'][1]['type'], 'input_image')
        self.assertFalse(request['store'])
        self.assertNotIn('AAAA', json.dumps(grok.command_text(args)))

    def test_truncated_stream_does_not_silently_succeed(self):
        with self.assertRaises(grok.GrokError):
            grok.parse_sse_response([b'data: {"type":"response.output_text.delta","delta":"hi"}\n'])
