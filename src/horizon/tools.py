"""Allowlisted, local source tools with strict argument validation."""
from .core import Passage, search_passages
from .models import Action


def validate_action(action: Action) -> None:
    if not isinstance(action, Action) or not isinstance(action.arguments, dict):
        raise ValueError('invalid_action')
    args = action.arguments
    fields = {
        'search_sources': {'query', 'top_k'},
        'read_passage': {'passage_id'},
        'finish_answer': {'status', 'answer', 'citations'},
    }
    if not isinstance(action.name, str) or action.name not in fields:
        raise ValueError('unknown_action')
    if set(args) != fields[action.name]:
        raise ValueError('invalid_arguments')
    if action.name == 'search_sources':
        if not isinstance(args['query'], str) or not 1 <= len(args['query'].strip()) <= 4000:
            raise ValueError('invalid_query')
        if type(args['top_k']) is not int or not 1 <= args['top_k'] <= 10:
            raise ValueError('invalid_top_k')
    elif action.name == 'read_passage':
        if not isinstance(args['passage_id'], str) or not 1 <= len(args['passage_id']) <= 100:
            raise ValueError('invalid_passage_id')
    else:
        if args['status'] not in ('answered', 'abstained'):
            raise ValueError('invalid_answer_status')
        if not isinstance(args['answer'], str) or not 1 <= len(args['answer'].strip()) <= 12000:
            raise ValueError('invalid_answer')
        citations = args['citations']
        if not isinstance(citations, list) or len(citations) > 20 or any(
            not isinstance(c, str) or not 1 <= len(c) <= 100 for c in citations
        ):
            raise ValueError('invalid_citations')


def execute_tool(action: Action, passages: list[Passage]) -> dict:
    validate_action(action)
    if action.name == 'search_sources':
        selected = search_passages(action.arguments['query'], passages, action.arguments['top_k'])
        return {'status': 'ok', 'passage_ids': [p.id for p in selected]}
    if action.name == 'read_passage':
        passage = next((p for p in passages if p.id == action.arguments['passage_id']), None)
        if passage is None:
            return {'status': 'not_found', 'passage_id': action.arguments['passage_id']}
        return {'status': 'ok', 'passage_id': passage.id, 'text': passage.text}
    raise ValueError('finish_is_not_a_source_tool')
