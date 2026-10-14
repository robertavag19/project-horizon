"""Bounded provider-driven controller; no network or paid provider is included."""
from pathlib import Path
import time
import uuid

from .core import split_passages
from .evaluation import check_submission, evaluate_final
from .models import Action, Observation, Provider
from .tools import execute_tool, validate_action
from .tracing import Recorder


def run_agent(document: str, question: str, log_dir: Path, provider: Provider, *,
              task_id: str = 'study_task', max_steps: int = 8,
              max_duration_seconds: float = 30, inject: str = 'none',
              expected_passage: str | None = None) -> dict:
    if type(max_steps) is not int or not 1 <= max_steps <= 100:
        raise ValueError('max_steps must be between 1 and 100')
    if not isinstance(max_duration_seconds, (int, float)) or not 0 < max_duration_seconds <= 3600:
        raise ValueError('max_duration_seconds must be between 0 and 3600')
    if inject not in ('none', 'wrong_citation', 'drop_evidence'):
        raise ValueError('unknown fault injection')
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 4000:
        raise ValueError('question must contain 1 to 4000 characters')
    if len(document.encode('utf-8')) > 1_000_000:
        raise ValueError('document exceeds 1 MB limit')
    if not isinstance(task_id, str) or not task_id or len(task_id) > 100:
        raise ValueError('task_id must contain 1 to 100 characters')
    run_id = str(uuid.uuid4())
    recorder = Recorder(log_dir / f'{run_id}.jsonl', run_id, task_id)
    passages = split_passages(document)
    history: list[Observation] = []
    read_ids: set[str] = set()
    submission = None
    injected = False
    rejected_answer_steps = []
    start = time.perf_counter()
    termination = 'step_limit'
    step = 0
    recorder.record('run_started', 0, passage_count=len(passages), max_steps=max_steps,
                    provider_type=type(provider).__name__, fault_requested=inject,
                    model_usage=None, model_cost=None)
    for step in range(1, max_steps + 1):
        if time.perf_counter() - start >= max_duration_seconds:
            termination = 'time_limit'
            break
        call_start = time.perf_counter()
        recorder.record('provider_call', step)
        try:
            action = provider.choose_action(question, tuple(history))
        except Exception as error:
            recorder.record('provider_error', step, error_type=type(error).__name__)
            termination = 'provider_error'
            break
        recorder.record('provider_result', step, duration_ms=round((time.perf_counter() - call_start) * 1000, 3))
        if time.perf_counter() - start >= max_duration_seconds:
            termination = 'time_limit'
            break
        try:
            validate_action(action)
        except (ValueError, TypeError):
            recorder.record('validation_failed', step, rule='action_schema')
            termination = 'invalid_action'
            break
        if inject == 'wrong_citation' and not injected and action.name == 'finish_answer' and action.arguments['status'] == 'answered':
            action = Action(action.name, {**action.arguments, 'citations': ['P999']})
            injected = True
            recorder.record('fault_injected', step, fault=inject, location='finish_answer_arguments')
        # Queries, source text, answers, arbitrary identifiers and provider errors are not logged.
        metadata = {'action_name': action.name}
        if action.name == 'search_sources':
            metadata.update(query_length=len(action.arguments['query']), top_k=action.arguments['top_k'])
        elif action.name == 'read_passage':
            metadata['source_ids'] = [action.arguments['passage_id']] if action.arguments['passage_id'] in {p.id for p in passages} else []
        else:
            metadata.update(answer_length=len(action.arguments['answer']), citation_count=len(action.arguments['citations']))
        recorder.record('action_selected', step, **metadata)
        if action.name == 'finish_answer':
            verification = check_submission(action.arguments, passages, read_ids)
            # Log counts, not arbitrary citation strings supplied by a provider.
            recorder.record('submission_checked', step,
                structural_submission_valid=verification['structural_submission_valid'],
                invalid_citation_count=len(verification['invalid_ids']),
                unread_citation_count=len(verification['unread_citation_ids']),
                evaluator=verification['evaluator'])
            if verification['structural_submission_valid']:
                submission = action.arguments
                termination = 'completed' if submission['status'] == 'answered' else 'abstained'
                break
            rejected_answer_steps.append(step)
            history.append(Observation(action, {'status': 'rejected', **verification}))
            continue
        tool_start = time.perf_counter()
        recorder.record('tool_call', step, action_name=action.name)
        result = execute_tool(action, passages)
        if inject == 'drop_evidence' and not injected and action.name == 'search_sources':
            result = {'status': 'ok', 'passage_ids': []}
            injected = True
            recorder.record('fault_injected', step, fault=inject, location='search_sources_result')
        if action.name == 'read_passage' and result['status'] == 'ok':
            read_ids.add(result['passage_id'])
        source_ids = result.get('passage_ids', []) if action.name == 'search_sources' else (
            [result['passage_id']] if result['status'] == 'ok' else []
        )
        recorder.record('tool_result', step, action_name=action.name,
                        status=result['status'], source_ids=source_ids,
                        duration_ms=round((time.perf_counter() - tool_start) * 1000, 3))
        history.append(Observation(action, result))
    final_check = evaluate_final(submission, passages, read_ids, expected_passage)
    recovered = bool(rejected_answer_steps and submission is not None and submission['status'] == 'answered'
                     and final_check['structural_submission_valid'])
    recorder.record('final_evaluation', step,
                    structural_submission_valid=final_check['structural_submission_valid'],
                    reference_passage_cited=final_check['reference_passage_cited'],
                    semantic_correctness=final_check['semantic_correctness'],
                    evaluator=final_check['evaluator'])
    if recovered:
        recorder.record('recovery_observed', step, first_rejected_step=rejected_answer_steps[0],
                        scope='citation_and_read_evidence_only')
    duration_ms = round((time.perf_counter() - start) * 1000, 3)
    recorder.record('run_finished', step, termination_reason=termination, duration_ms=duration_ms,
                    recovery_observed=recovered, fault_applied=injected)
    return {
        'run_id': run_id, 'task_id': task_id, 'termination_reason': termination,
        'answer': submission['answer'] if submission else None,
        'citations': submission['citations'] if submission else [],
        'steps': step, 'duration_ms': duration_ms, 'fault_applied': injected,
        'recovery_observed': recovered, 'evaluation': final_check,
        'trace_file': str(recorder.path),
        'limitations': 'Mock mode uses no LLM. Structural checks do not verify factual correctness.',
    }
