"""Free, deterministic provider used to exercise the controller, not an LLM."""
from .models import Action, Observation


class MockProvider:
    def choose_action(self, question: str, history: tuple[Observation, ...]) -> Action:
        if not history:
            return Action('search_sources', {'query': question, 'top_k': 2})
        last = history[-1]
        if last.action.name == 'search_sources' and last.result.get('passage_ids'):
            return Action('read_passage', {'passage_id': last.result['passage_ids'][0]})
        reads = [o for o in history if o.action.name == 'read_passage' and o.result.get('status') == 'ok']
        if reads:
            passage = reads[-1].result
            return Action('finish_answer', {
                'status': 'answered',
                'answer': 'Relevant source excerpt: ' + passage['text'],
                'citations': [passage['passage_id']],
            })
        return Action('finish_answer', {
            'status': 'abstained',
            'answer': 'No relevant source excerpt was found. I cannot answer from this document.',
            'citations': [],
        })
