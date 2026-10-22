"""Empirical test adequacy: nontrivial wrong solvers must pass examples and fail hidden tests."""
from courseagent.agent_contracts import MutationDesign

def evaluate_wrong_solutions(design, cases, execute):
    design = MutationDesign.model_validate(design)
    public = [c for c in cases if c['visibility']=='public']
    hidden = [c for c in cases if c['visibility']=='hidden']
    results = []
    for wrong in design.wrong_solutions:
        evidence = {'id':wrong.id,'fault':wrong.fault,'status':'survived','hidden_checked':0}
        for case in public:
            run = execute(wrong.code,case['input'])
            if not run.get('ok') or run.get('output','').split()!=case['output'].split():
                evidence.update(status='invalid_control', reason='未通过公开样例，不计入有效错误程序')
                break
        if evidence['status']!='invalid_control':
            for index,case in enumerate(hidden):
                run = execute(wrong.code,case['input']);evidence['hidden_checked']+=1
                if not run.get('ok') or run.get('output','').split()!=case['output'].split():
                    evidence.update(status='detected',hidden_case_index=index,
                                    detection='wrong_output' if run.get('ok') else run.get('status','execution_error'))
                    break
        results.append(evidence)
    eligible=sum(r['status']!='invalid_control' for r in results)
    detected=sum(r['status']=='detected' for r in results)
    return {'passed':eligible>=2 and detected==eligible,
            'proposed_count':len(results),'eligible_count':eligible,'detected_count':detected,
            'detection_rate':detected/eligible if eligible else None,'results':results,
            'limitation':'只衡量这些具体错误程序；不能证明全部边界覆盖或算法正确。'}
