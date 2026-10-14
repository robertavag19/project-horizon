import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from horizon.agent import run_agent
from horizon.models import Observation, ProviderFailure
from horizon.openai_provider import OpenAIConfig, OpenAIProvider, post_response


KEY = 'test-key-not-a-real-secret'
DOC = 'Centripetal acceleration is v squared divided by r and points toward the center.'


def response(name='search_sources', arguments=None, usage=True, **overrides):
    result = {'status': 'completed', 'output': [{'type': 'function_call', 'call_id': 'call_1',
        'name': name, 'arguments': json.dumps(arguments or {'query': 'centripetal', 'top_k': 2})}]}
    if usage:
        result['usage'] = {'input_tokens': 100, 'output_tokens': 30}
    result.update(overrides)
    return result


class FakeTransport:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.payloads = []

    def __call__(self, payload, key, timeout):
        self.payloads.append(copy.deepcopy(payload))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


class OpenAIProviderTests(unittest.TestCase):
    def provider(self, transport, **config):
        return OpenAIProvider(KEY, allow_live=True, transport=transport, config=OpenAIConfig(**config))

    def test_no_call_without_explicit_opt_in(self):
        transport = FakeTransport()
        with self.assertRaises(ValueError):
            OpenAIProvider(KEY, transport=transport)
        self.assertEqual(transport.payloads, [])

    def test_empty_key_rejected(self):
        with self.assertRaises(ValueError):
            OpenAIProvider('', allow_live=True)

    def test_full_loop_and_api_payload(self):
        transport = FakeTransport(response(), response('read_passage', {'passage_id': 'P001'}),
            response('finish_answer', {'status': 'answered', 'answer': 'Acceleration is v squared divided by r.', 'citations': ['P001']}))
        provider = self.provider(transport)
        with TemporaryDirectory() as folder:
            result = run_agent(DOC, 'What is centripetal acceleration?', Path(folder), provider)
            trace = Path(result['trace_file']).read_text()
        self.assertEqual(result['termination_reason'], 'completed')
        self.assertEqual(result['model_usage']['requests'], 3)
        self.assertEqual(result['model_usage']['input_tokens'], 300)
        self.assertEqual(result['model_usage']['output_tokens'], 90)
        self.assertAlmostEqual(result['model_usage']['estimated_cost_usd'], 0.000264)
        self.assertNotIn(KEY, trace)
        self.assertNotIn(DOC, trace)
        first = transport.payloads[0]
        self.assertFalse(first['store'])
        self.assertFalse(first['parallel_tool_calls'])
        self.assertEqual(first['tool_choice'], 'required')
        self.assertTrue(all(tool['strict'] for tool in first['tools']))
        last = transport.payloads[-1]
        outputs = [item for item in last['input'] if item.get('type') == 'function_call_output']
        self.assertEqual(len(outputs), 2)
        self.assertIn(DOC, outputs[-1]['output'])
        self.assertNotIn('previous_response_id', last)

    def test_rejected_submission_is_returned_to_model(self):
        finish = response('finish_answer', {'status': 'answered', 'answer': 'Based on the note.', 'citations': ['P001']})
        transport = FakeTransport(response(), response('read_passage', {'passage_id': 'P001'}), finish, finish)
        with TemporaryDirectory() as folder:
            result = run_agent(DOC, 'centripetal', Path(folder), self.provider(transport), inject='wrong_citation')
        self.assertTrue(result['recovery_observed'])
        last_output = transport.payloads[-1]['input'][-1]
        feedback = json.loads(last_output['output'])
        self.assertEqual(feedback['executed_arguments']['citations'], ['P999'])
        self.assertEqual(feedback['result']['status'], 'rejected')

    def test_request_budget_stops_before_network(self):
        transport = FakeTransport(response())
        provider = self.provider(transport, max_requests=1)
        action = provider.choose_action('x', ())
        with self.assertRaises(ProviderFailure) as error:
            provider.choose_action('x', (Observation(action, {'status': 'ok', 'passage_ids': []}),))
        self.assertEqual(error.exception.reason, 'request_limit')
        self.assertEqual(len(transport.payloads), 1)

    def test_token_budget_stops_before_network(self):
        transport = FakeTransport()
        provider = self.provider(transport, max_reserved_tokens=1)
        with self.assertRaises(ProviderFailure) as error:
            provider.choose_action('x', ())
        self.assertEqual(error.exception.reason, 'token_budget')
        self.assertEqual(transport.payloads, [])

    def test_input_size_stops_before_network(self):
        transport = FakeTransport()
        with self.assertRaises(ProviderFailure):
            self.provider(transport, max_request_bytes=10).choose_action('x', ())
        self.assertEqual(transport.payloads, [])

    def test_incomplete_or_malformed_response_is_not_answer(self):
        values = [response(status='incomplete'), response(output=[]),
                  response(output=[{'type': 'message', 'content': 'plausible'}]),
                  response('search_sources', {'query': 'x', 'top_k': True}),
                  response(output=[{'type': 'function_call', 'call_id': 'x', 'name': 'search_sources', 'arguments': 'not json'}]),
                  response(output=[response()['output'][0], response()['output'][0]])]
        for value in values:
            with self.subTest(value=value), self.assertRaises(ProviderFailure):
                self.provider(FakeTransport(value)).choose_action('x', ())

    def test_non_object_response_is_rejected_and_usage_unknown(self):
        provider = self.provider(FakeTransport([]))
        with self.assertRaises(ProviderFailure) as error:
            provider.choose_action('x', ())
        self.assertEqual(error.exception.reason, 'invalid_provider_response')
        self.assertIsNone(provider.usage.estimated_cost_usd)

    def test_missing_usage_is_unknown(self):
        provider = self.provider(FakeTransport(response(usage=False)))
        provider.choose_action('x', ())
        self.assertIsNone(provider.usage.input_tokens)
        self.assertIsNone(provider.usage.estimated_cost_usd)
        self.assertGreater(provider.usage.reserved_tokens, 0)

    def test_network_timeout_not_retried_and_logged_without_secret(self):
        transport = FakeTransport(ProviderFailure('request_timeout'))
        with TemporaryDirectory() as folder:
            result = run_agent(DOC, 'centripetal', Path(folder), self.provider(transport))
            trace = Path(result['trace_file']).read_text()
        self.assertEqual(result['termination_reason'], 'request_timeout')
        self.assertEqual(len(transport.payloads), 1)
        self.assertIsNone(result['model_usage']['estimated_cost_usd'])
        self.assertNotIn(KEY, trace)

    def test_transport_uses_fixed_host_timeout_and_no_retry(self):
        with patch('horizon.openai_provider.http.client.HTTPSConnection') as connection:
            connection.return_value.getresponse.side_effect = TimeoutError('SECRET')
            with self.assertRaises(ProviderFailure) as error:
                post_response({}, KEY, 2)
        self.assertEqual(error.exception.reason, 'request_timeout')
        connection.assert_called_once_with('api.openai.com', timeout=2)
        connection.return_value.request.assert_called_once()
        connection.return_value.close.assert_called_once()

    def test_http_error_not_exposed(self):
        with patch('horizon.openai_provider.http.client.HTTPSConnection') as connection:
            connection.return_value.getresponse.return_value.status = 401
            with self.assertRaises(ProviderFailure) as error:
                post_response({}, KEY, 2)
        self.assertEqual(str(error.exception), 'api_error')
        connection.return_value.getresponse.return_value.read.assert_not_called()

    def test_cli_live_gate_prevents_network(self):
        from horizon.cli import main
        with patch('sys.argv', ['horizon', '--mode', 'agent', '--provider', 'openai']), \
             patch('horizon.openai_provider.post_response') as transport, \
             patch('sys.stderr'):
            with self.assertRaises(SystemExit) as error:
                main()
        self.assertEqual(error.exception.code, 2)
        transport.assert_not_called()

    def test_config_rejects_bool_and_nan(self):
        for config in ({'max_requests': True}, {'max_output_tokens': 0}, {'timeout_seconds': float('nan')}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                OpenAIConfig(**config)
