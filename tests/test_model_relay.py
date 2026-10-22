import contextlib
import io
import unittest
from unittest.mock import Mock, patch
from scripts import check_model_connection as probe
from courseagent import model_client

CONFIG = {'base_url': 'https://relay.example/v1', 'model': 'test', 'api_key': 'PRIVATE_KEY'}


class RelayTests(unittest.TestCase):
    def test_stream_deadline_closes_request_even_when_tokens_keep_arriving(self):
        from langchain_core.messages import AIMessageChunk
        closed=[]
        def chunks():
            try:
                yield AIMessageChunk(content='{"ok":')
                yield AIMessageChunk(content='true}')
            finally:closed.append(True)
        config={**CONFIG,'streaming':True,'timeout_seconds':5}
        with patch.object(model_client,'configuration',return_value=config),patch('langchain_openai.ChatOpenAI') as adapter,patch('courseagent.model_client.time.monotonic',side_effect=[0,1,6]):
            adapter.return_value.stream.return_value=chunks()
            metrics={}
            with self.assertRaises(TimeoutError):model_client._chat_json_langchain('test',{},metrics)
        self.assertTrue(metrics['request_deadline_exceeded']);self.assertEqual(closed,[True])

    def test_thinking_control_does_not_overwrite_legacy_token_limit(self):
        with patch.object(model_client,'configuration',return_value={**CONFIG,'thinking':'disabled','token_parameter':'max_tokens'}),patch('langchain_openai.ChatOpenAI') as adapter:
            adapter.return_value.invoke.return_value=Mock(content='{"ok":true}',usage_metadata={'output_token_details':{'reasoning':20}},response_metadata={})
            metrics={};model_client._chat_json_langchain('test',{},metrics,max_tokens=1024)
        self.assertEqual(adapter.call_args.kwargs['extra_body'],{'thinking':{'type':'disabled'},'max_tokens':1024})
        self.assertEqual(metrics['reasoning_tokens'],20)
        self.assertTrue(metrics['thinking_control_mismatch'])

    def test_task_transport_uses_remaining_time_and_no_hidden_retries(self):
        with patch.object(model_client, 'configuration', return_value={**CONFIG, 'timeout_seconds':120}),patch('langchain_openai.ChatOpenAI') as adapter,patch('courseagent.model_client.time.monotonic',return_value=100),model_client.model_budget(10,30):
            adapter.return_value.invoke.return_value=Mock(content='{"ok":true}',usage_metadata={},response_metadata={})
            with patch('courseagent.model_client.time.monotonic',return_value=125):
                model_client._chat_json_langchain('test',{}, {})
            self.assertEqual(adapter.call_args.kwargs['timeout'],5)
            self.assertEqual(adapter.call_args.kwargs['max_retries'],0)
            adapter.reset_mock()
            with patch('courseagent.model_client.time.monotonic',return_value=130),self.assertRaises(model_client.BudgetExhausted):
                model_client._chat_json_langchain('test',{}, {})
            adapter.assert_not_called()

    def test_model_proxy_is_explicit_and_transport_is_closed(self):
        for trust_env in (False, True):
            with self.subTest(trust_env=trust_env), patch.object(model_client, 'configuration', return_value={**CONFIG, 'trust_env': trust_env}), patch('langchain_openai.ChatOpenAI') as adapter, patch('httpx.Client') as transport:
                adapter.return_value.invoke.return_value=Mock(content='{"ok":true}',usage_metadata={},response_metadata={})
                self.assertTrue(model_client._chat_json_langchain('test',{}, {})['ok'])
                self.assertEqual(transport.call_args.kwargs['trust_env'],trust_env)
                self.assertIs(adapter.call_args.kwargs['http_client'],transport.return_value.__enter__.return_value)
                transport.return_value.__exit__.assert_called_once()

    def test_invalid_proxy_flag_rejected(self):
        with self.assertRaisesRegex(ValueError, 'trust_env'):
            model_client.validate_runtime_settings({**CONFIG, 'trust_env': 'false'})

    def test_json_parse_error_is_not_a_transport_failure(self):
        from courseagent.verification_state import failure_info
        with patch.object(model_client, 'configuration', return_value={**CONFIG, 'backend':'langchain'}), patch.object(model_client, '_chat_json_langchain',side_effect=ValueError('PRIVATE_INVALID_RESPONSE')):
            with self.assertRaises(ValueError) as caught:model_client.chat_json('test',{})
        self.assertEqual(failure_info(caught.exception)['code'],'format')
        self.assertNotIn('PRIVATE_INVALID_RESPONSE',str(caught.exception))

    def test_truncated_output_changes_next_retry_within_explicit_ceiling(self):
        config={**CONFIG,'backend':'langchain','max_output_tokens':8192,'adaptive_output_ceiling':16384}
        truncated=Mock(content='',usage_metadata={},response_metadata={'finish_reason':'length'})
        complete=Mock(content='{"ok":true}',usage_metadata={},response_metadata={'finish_reason':'stop'})
        with patch.object(model_client,'configuration',return_value=config),patch('langchain_openai.ChatOpenAI') as adapter,model_client.model_budget(5,60) as budget:
            adapter.return_value.invoke.side_effect=[truncated,complete,truncated,truncated]
            with self.assertRaisesRegex(ValueError,'token 上限'):model_client.chat_json('test',{})
            self.assertEqual(adapter.call_args.kwargs['max_tokens'],8192)
            self.assertTrue(model_client.chat_json('test',{})['ok'])
            self.assertEqual(adapter.call_args.kwargs['max_tokens'],16384)
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'token 上限'):model_client.chat_json('test',{})
                self.assertEqual(adapter.call_args.kwargs['max_tokens'],16384)
            self.assertEqual(budget['calls'],4)
        self.assertEqual(config['max_output_tokens'],8192)

    def test_no_output_growth_without_explicit_opt_in(self):
        with model_client.model_budget(2,20) as budget:
            model_client._increase_output_limit({**CONFIG,'max_output_tokens':8192},{})
            self.assertFalse(budget.get('output_limits'))

    def test_no_network_in_check_only(self):
        with patch.object(probe, 'configuration', return_value=CONFIG), patch.object(probe, '_chat_json_langchain') as call, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(probe.main(['--check-only']), 0)
            call.assert_not_called()

    def test_probe_is_bounded_and_never_leaks_provider_error(self):
        error = Exception('PRIVATE_KEY body'); error.status_code = 401
        output = io.StringIO()
        with patch.object(probe, 'configuration', return_value=CONFIG), patch.object(probe, '_chat_json_langchain', side_effect=error) as call, contextlib.redirect_stdout(output):
            self.assertEqual(probe.main([]), 1)
        self.assertNotIn('PRIVATE_KEY', output.getvalue())
        self.assertIn('401', output.getvalue())
        self.assertEqual(call.call_args.kwargs, {'timeout': 30, 'max_retries': 0, 'max_tokens': 64})

    def test_json_mode_disabled_omits_provider_parameter_but_parses_json(self):
        with patch.object(model_client, 'configuration', return_value={**CONFIG, 'json_mode': False}), patch('langchain_openai.ChatOpenAI') as adapter:
            adapter.return_value.invoke.return_value = Mock(content='{"ok":true}', usage_metadata={}, response_metadata={})
            self.assertEqual(model_client._chat_json_langchain('test', {}, {}), {'ok': True})
            self.assertNotIn('model_kwargs', adapter.call_args.kwargs)

    def test_invalid_json_mode_rejected_before_request(self):
        with patch.object(model_client, 'configuration', return_value={**CONFIG, 'json_mode': 'false'}), patch('langchain_openai.ChatOpenAI') as adapter:
            with self.assertRaises(ValueError): model_client._chat_json_langchain('test', {}, {})
            adapter.assert_not_called()

    def test_codex_reasoning_effort_is_forwarded_without_replacing_thinking(self):
        config={**CONFIG,'reasoning_effort':'low','thinking':'disabled'}
        with patch.object(model_client,'configuration',return_value=config),patch('langchain_openai.ChatOpenAI') as adapter:
            adapter.return_value.invoke.return_value=Mock(content='{"ok":true}',usage_metadata={},response_metadata={})
            self.assertEqual(model_client._chat_json_langchain('test',{},{}), {'ok':True})
            self.assertEqual(adapter.call_args.kwargs['extra_body'], {
                'thinking': {'type':'disabled'}, 'reasoning_effort':'low'})

    def test_invalid_reasoning_effort_rejected_before_request(self):
        with self.assertRaisesRegex(ValueError, 'reasoning_effort'):
            model_client.validate_runtime_settings({**CONFIG,'reasoning_effort':'invalid'})

    def test_streaming_and_bounded_output_options_forwarded(self):
        with patch.object(model_client, 'configuration', return_value={**CONFIG, 'streaming': True, 'max_output_tokens': 8192, 'timeout_seconds': 120}), patch('langchain_openai.ChatOpenAI') as adapter:
            from langchain_core.messages import AIMessageChunk
            adapter.return_value.stream.return_value = (x for x in [AIMessageChunk(content='{"ok":true}')])
            self.assertEqual(model_client._chat_json_langchain('test', {}, {}), {'ok': True})
            self.assertTrue(adapter.call_args.kwargs['streaming'])
            self.assertEqual(adapter.call_args.kwargs['max_tokens'],8192)
            self.assertEqual(adapter.call_args.kwargs['timeout'].read,60)

    def test_truncated_response_never_accepted_even_if_json_parses(self):
        with patch.object(model_client, 'configuration', return_value=CONFIG), patch('langchain_openai.ChatOpenAI') as adapter:
            adapter.return_value.invoke.return_value = Mock(content='{"ok":true}', usage_metadata={}, response_metadata={'finish_reason':'length'})
            with self.assertRaisesRegex(ValueError,'token 上限'):
                model_client._chat_json_langchain('test', {}, {})

    def test_legacy_token_parameter_preserved_in_extra_body(self):
        with patch.object(model_client, 'configuration', return_value={**CONFIG, 'token_parameter': 'max_tokens'}), patch('langchain_openai.ChatOpenAI') as adapter:
            adapter.return_value.invoke.return_value = Mock(content='{"ok":true}', usage_metadata={}, response_metadata={})
            model_client._chat_json_langchain('test', {}, {}, max_tokens=2500)
            self.assertEqual(adapter.call_args.kwargs['extra_body'], {'max_tokens':2500})
            self.assertNotIn('max_tokens',adapter.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
