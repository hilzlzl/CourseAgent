"""Task-local source consumption, without assumptions about webpage layout."""
import hashlib
import json


def content_key(page):
    return hashlib.sha256(page['text'].replace('\r\n','\n').strip().encode()).hexdigest()


def scope_key(spec):
    return hashlib.sha256(json.dumps({k:spec.get(k) for k in ('topics','teaching_plan')},
        ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def reusable_types(assessment, needed):
    if assessment.get('status')!='remaining':return set()
    remaining=assessment.get('remaining_types')
    # Legacy checkpoints have only a global has_more. Allow one normal pass.
    return set(needed) if remaining is None else set(needed)&set(remaining)


def assessment_for(prior, assessment, page, spec, requested, added, rejected, inventory):
    requested=set(requested)
    raw=assessment.get('remaining_types')
    # An explicit empty list is different from a legacy omitted field.
    explicit=isinstance(raw,list) and all(str(t) in ('1','2','3','4','5') for t in raw)
    remaining=set(map(str,raw)) if explicit else (requested if assessment.get('has_more') and added else set())
    counts=dict(prior.get('type_passes',{}))
    for t in requested:counts[t]=counts.get(t,0)+1
    exhausted=set(prior.get('exhausted_types',[]))
    # No-gain pages must not cause unbounded has_more loops. The model already
    # had a bounded evidence-repair pass, where appropriate.
    exhausted.update(t for t in requested if t not in remaining or not added or counts[t]>=3)
    remaining-=exhausted
    kind=assessment.get('kind')
    unusable=kind in ('irrelevant','access_limited','summary')
    if unusable:remaining=set();exhausted.update(requested)
    return {'status':kind if unusable else ('remaining' if remaining else 'consumed'),
        'passes':prior.get('passes',0)+1,'type_passes':counts,'remaining_types':sorted(remaining),
        'exhausted_types':sorted(exhausted),'assessed_types':sorted(set(prior.get('assessed_types',[]))|requested),
        'content_key':content_key(page),'scope_key':scope_key(spec),'inventory_ids':list(inventory),
        'method':'model_interpretation','scope_version':2,'added':added,
        'total_added':prior.get('total_added',prior.get('added',0))+added,
        'zero_gain_passes':prior.get('zero_gain_passes',0)+int(not added),
        'rejected':rejected,'assessment':assessment}


def identical_consumed(web,page,spec,needed):
    """Only reuse explicit consumption of unchanged content in the same scope."""
    digest=content_key(page);scope=scope_key(spec)
    for url,a in web.get('source_assessments',{}).items():
        if (url!=page['url'] and a.get('content_key')==digest and a.get('scope_key')==scope
                and set(needed)<=set(a.get('exhausted_types',[]))):return url,a
    return None
