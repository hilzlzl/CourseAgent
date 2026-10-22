"""Export original fixed examples; no model, web, browser, or task submission."""
import argparse
import copy
import json
from pathlib import Path
from courseagent.questions import export_xlsx, review_content
from courseagent.programming_questions import export_test_bundle, review_content as programming_content
from courseagent.workspace_setup import initialize_workspace

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/demo')
    args = parser.parse_args()
    initialize_workspace(ROOT)
    document = json.loads((ROOT/'examples/offline-fixture.json').read_text(encoding='utf-8'))
    document['programming_questions'] = json.loads((ROOT/'examples/programming-demo.json').read_text(encoding='utf-8'))
    document = copy.deepcopy(document)
    # These are hand-checked fixtures, not receipts from the live Agent.
    for q in document['questions']:
        q['approved'] = True
        q['approval_snapshot'] = review_content(q)
    for q in document['programming_questions']:
        q['approved'] = True
        q['approval_snapshot'] = programming_content(q)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'assignment.xlsx').write_bytes(export_xlsx(document))
    (args.output/'judge-tests.zip').write_bytes(export_test_bundle(document))
    (args.output/'assignment.json').write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'mode': 'fixed_offline_demo', 'model_calls': 0, 'platform_writes': 0,
                      'ordinary_questions': len(document['questions']), 'programming_questions': len(document['programming_questions']),
                      'output': str(args.output), 'live_agent_evaluation': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
