"""Teacher supplied keys are authoritative; validate their transport, not their truth.

Trust is attached by literal document extraction/matching, never by an LLM's
claim. The snapshot prevents an edited/adapted problem from inheriting it.
"""
import copy
from courseagent.verification_state import digest

POLICY_VERSION = 'teacher-material-v1'
FIELDS = ('type', 'stem', 'options', 'answer', 'blanks', 'reference_answer')
PROGRAM_FIELDS = ('title', 'description', 'public_examples', 'source_protocol', 'source_reference')


def content_basis(q):
    fields = PROGRAM_FIELDS if q.get('kind') == 'programming' else FIELDS
    return digest({k: q.get(k) for k in fields})


def supplied_key(q):
    return q.get('answer_provenance', {}).get('kind') == 'teacher_material'


def trusted_key(q):
    proof = q.get('answer_provenance', {})
    return (supplied_key(q) and proof.get('policy') == POLICY_VERSION
            and proof.get('content_basis') == content_basis(q)
            and bool(proof.get('source_refs'))
            and all(r in q.get('source_refs',[]) for r in proof['source_refs'])
            and q.get('origin') not in ('web_adapted', 'web_programming_adapted', 'supplement'))


def mark_supplied_key(q, refs, method):
    """Call only after locating a literal key and matching its question/options."""
    if not refs or not any(r.get('document_id') for r in refs):
        raise ValueError('可信资料答案必须能定位到本地原文')
    q['answer_provenance'] = {'kind': 'teacher_material', 'policy': POLICY_VERSION,
                            'source_refs': copy.deepcopy(refs), 'matching_method': method,
                            'content_basis': content_basis(q)}
    return q


def quality_view(q, fields):
    """Hide authoritative answers from semantic reviewers, including whole-exam review."""
    result = {'id': q['id'], **{k: q.get(k) for k in fields}}
    if supplied_key(q):
        for key in ('answer', 'blanks', 'reference_answer', 'explanation', 'reference_code'):
            result.pop(key, None)
        result['answer_policy'] = 'teacher_material: accept key; check extraction and display only'
        if 'source_refs' in result:
            result['source_refs']=[{k:r[k] for k in ('document_id','page','paragraph','question_number') if k in r}
                                   for r in q.get('source_refs',[])]
    return result


def semantic_issue_allowed(issue, questions):
    # Original conditions and answers are not subject to model adjudication.
    if issue.get('kind') not in ('answer', 'conditions'):
        return True
    ids = issue.get('question_ids', [])
    return not any(supplied_key(questions[i]) for i in ids if i in questions)
