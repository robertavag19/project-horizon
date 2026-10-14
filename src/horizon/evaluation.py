"""Independent structural final checks; these do not grade semantic correctness."""
from .core import Passage, verify_citations


def check_submission(submission: dict, passages: list[Passage], read_ids: set[str]) -> dict:
    citations = submission['citations']
    checked = verify_citations(citations, passages)
    unread = [c for c in citations if c not in read_ids]
    abstained = submission['status'] == 'abstained'
    accepted = (not citations) if abstained else (checked['citation_ids_valid'] and not unread)
    return {
        **checked, 'unread_citation_ids': unread,
        'structural_submission_valid': bool(accepted),
        'semantic_correctness': 'not_evaluated',
        'evaluator': 'citation_and_read_evidence_v1',
    }


def evaluate_final(submission: dict | None, passages: list[Passage], read_ids: set[str],
                   expected_passage: str | None = None) -> dict:
    if submission is None:
        return {'structural_submission_valid': False, 'reference_passage_cited': None,
                'semantic_correctness': 'not_evaluated', 'evaluator': 'citation_and_read_evidence_v1'}
    result = check_submission(submission, passages, read_ids)
    result['reference_passage_cited'] = (
        expected_passage in submission['citations'] if expected_passage is not None else None
    )
    return result
