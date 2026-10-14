import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from horizon.agent import run_agent
from horizon.models import Action
from horizon.providers import MockProvider

DOC = 'Centripetal acceleration points toward the center.\n\nPhotosynthesis uses sunlight.'


class ScriptProvider:
    def __init__(self, *actions):
        self.actions = iter(actions)

    def choose_action(self, question, history):
        return next(self.actions)


class AgentTests(unittest.TestCase):
    def run_case(self, provider=None, **kwargs):
        with TemporaryDirectory() as folder:
            result = run_agent(DOC, 'centripetal acceleration', Path(folder),
                               provider or MockProvider(), **kwargs)
            events = [json.loads(line) for line in Path(result['trace_file']).read_text().splitlines()]
        return result, events

    def test_completion_and_linked_events(self):
        result, events = self.run_case(expected_passage='P001')
        self.assertEqual(result['termination_reason'], 'completed')
        self.assertEqual(result['steps'], 3)
        self.assertTrue(result['evaluation']['reference_passage_cited'])
        self.assertEqual(result['evaluation']['semantic_correctness'], 'not_evaluated')
        self.assertEqual([e['event_sequence'] for e in events], list(range(1, len(events) + 1)))
        self.assertTrue(all(e['run_id'] == result['run_id'] for e in events))
        calls = [(e['step_index'], e['metadata']['action_name']) for e in events if e['event_type'] == 'tool_call']
        results = [(e['step_index'], e['metadata']['action_name']) for e in events if e['event_type'] == 'tool_result']
        self.assertEqual(calls, results)
        self.assertEqual(events[-1]['event_type'], 'run_finished')

    def test_wrong_citation_rejected_then_provider_revises(self):
        result, events = self.run_case(inject='wrong_citation')
        self.assertTrue(result['fault_applied'])
        self.assertTrue(result['recovery_observed'])
        checks = [e for e in events if e['event_type'] == 'submission_checked']
        self.assertEqual([e['metadata']['structural_submission_valid'] for e in checks], [False, True])
        self.assertEqual(result['citations'], ['P001'])
        self.assertEqual(result['steps'], 4)

    def test_dropped_evidence_abstention_is_structurally_valid(self):
        result, _ = self.run_case(inject='drop_evidence', expected_passage='P001')
        self.assertEqual(result['termination_reason'], 'abstained')
        self.assertTrue(result['evaluation']['structural_submission_valid'])
        self.assertFalse(result['evaluation']['reference_passage_cited'])
        self.assertFalse(result['recovery_observed'])

    def test_existing_but_unread_citation_rejected(self):
        provider = ScriptProvider(Action('finish_answer', {'status': 'answered',
                                  'answer': 'Plausible answer', 'citations': ['P001']}))
        result, events = self.run_case(provider, max_steps=1)
        self.assertEqual(result['termination_reason'], 'step_limit')
        self.assertIsNone(result['answer'])
        checked = next(e for e in events if e['event_type'] == 'submission_checked')
        self.assertEqual(checked['metadata']['unread_citation_count'], 1)

    def test_step_limit_is_not_success(self):
        result, _ = self.run_case(max_steps=2)
        self.assertEqual(result['termination_reason'], 'step_limit')
        self.assertFalse(result['evaluation']['structural_submission_valid'])

    def test_persistent_invalid_citation_is_not_recovery(self):
        finish = Action('finish_answer', {'status': 'answered', 'answer': 'Wrong', 'citations': ['P999']})
        result, _ = self.run_case(ScriptProvider(finish, finish), max_steps=2)
        self.assertFalse(result['recovery_observed'])
        self.assertEqual(result['termination_reason'], 'step_limit')

    def test_unknown_tool_rejected_without_execution(self):
        with patch('horizon.agent.execute_tool') as execute:
            result, _ = self.run_case(ScriptProvider(Action('delete_file', {'path': 'secret'})))
        execute.assert_not_called()
        self.assertEqual(result['termination_reason'], 'invalid_action')

    def test_bad_argument_shapes_rejected(self):
        actions = [
            Action('search_sources', {'query': 'x', 'top_k': True}),
            Action('search_sources', {'query': 'x', 'top_k': 2, 'extra': 'x'}),
            Action('finish_answer', {'status': 'answered', 'answer': 'x', 'citations': 'P001'}),
            Action('read_passage', {'passage_id': 1}),
            None,
        ]
        for action in actions:
            with self.subTest(action=action):
                result, _ = self.run_case(ScriptProvider(action))
                self.assertEqual(result['termination_reason'], 'invalid_action')

    def test_provider_failure_sanitized(self):
        class BrokenProvider:
            def choose_action(self, question, history):
                raise RuntimeError('SECRET_API_KEY')
        result, events = self.run_case(BrokenProvider())
        self.assertEqual(result['termination_reason'], 'provider_error')
        self.assertNotIn('SECRET_API_KEY', json.dumps(events))

    def test_trace_excludes_question_and_source_text(self):
        _, events = self.run_case()
        serialized = json.dumps(events)
        self.assertNotIn('centripetal acceleration', serialized)
        self.assertNotIn('points toward the center', serialized)

    def test_provider_overruns_elapsed_budget(self):
        clock = [0.0]
        class SlowProvider:
            def choose_action(self, question, history):
                clock[0] = 2.0
                return Action('search_sources', {'query': question, 'top_k': 2})
        with patch('horizon.agent.time.perf_counter', side_effect=lambda: clock[0]), patch('horizon.agent.execute_tool') as execute:
            result, _ = self.run_case(SlowProvider(), max_duration_seconds=1)
        execute.assert_not_called()
        self.assertEqual(result['termination_reason'], 'time_limit')

    def test_config_validation(self):
        for config in ({'max_steps': 0}, {'max_steps': True}, {'max_duration_seconds': 0}, {'inject': 'unknown'}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.run_case(**config)

    def test_no_matching_evidence(self):
        with TemporaryDirectory() as folder:
            result = run_agent(DOC, 'volcanic eruption', Path(folder), MockProvider())
        self.assertEqual(result['termination_reason'], 'abstained')

    def test_provider_can_choose_a_different_valid_path(self):
        provider = ScriptProvider(
            Action('read_passage', {'passage_id': 'P002'}),
            Action('finish_answer', {'status': 'answered', 'answer': 'Photosynthesis uses sunlight.', 'citations': ['P002']}),
        )
        result, _ = self.run_case(provider, expected_passage='P002')
        self.assertEqual(result['steps'], 2)
        self.assertEqual(result['termination_reason'], 'completed')
        self.assertTrue(result['evaluation']['reference_passage_cited'])


if __name__ == '__main__':
    unittest.main()
