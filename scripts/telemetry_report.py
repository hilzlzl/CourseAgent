"""Aggregate content-free task traces; estimate cost only with explicit local prices."""
import argparse
import json
from collections import defaultdict
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]

def interval_summary(records):
    """Aggregate leaf operations, without adding nested tools or parallel time."""
    intervals=[];total=0
    for record in records:
        duration=record.get('elapsed_ms')
        if not isinstance(duration,(int,float)) or duration<0:continue
        total+=duration
        try:
            start=datetime.fromisoformat(record['started_at']).timestamp()*1000
            intervals.append((start,start+duration))
        except (ValueError,TypeError,KeyError):continue
    merged=[]
    for start,end in sorted(intervals):
        if merged and start<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],end)
        else:merged.append([start,end])
    return {'calls':len(records),'failed':sum(r.get('status')=='failed' for r in records),
            'cumulative_seconds':round(total/1000,3),
            'active_wall_seconds':round(sum(end-start for start,end in merged)/1000,3),
            'timed_records':len(intervals)}


def operation_timings(records):
    # Registry tools contain their underlying tool span; select the registry
    # layer once, rather than summing both representations of the same I/O.
    groups={'model': [r for r in records if r.get('kind')=='llm'],
            'search_and_read':[r for r in records if r.get('name') in (
                'registry_search_public_questions','registry_search_question_source',
                'registry_read_public_question_page','registry_search_indexed_questions')],
            'code_execution':[r for r in records if r.get('name') in (
                'registry_execute_python_reference','registry_execute_source_reference')]}
    return {name:interval_summary(rows) for name,rows in groups.items()}


def summarize(trace_dir,task_id=None,prices=None,scan_files=True,include_offline=True):
    records=[];source='legacy_json_scan'
    if not scan_files:
        index=Path(trace_dir)/'index.sqlite';source='sqlite_index_since_upgrade'
        if index.exists():
            from courseagent.trace_store import store_at
            records=store_at(str(Path(trace_dir).absolute())).records()
    else:
        for p in Path(trace_dir).glob('*.json'):
            try:records.append(json.loads(p.read_text()))
            except (ValueError,OSError):continue
    if not include_offline:records=[r for r in records if r.get('mode','runtime')=='runtime']
    if task_id:
        selected={r['id'] for r in records if r.get('metrics',{}).get('task_id')==task_id}
        previous=-1
        while len(selected)!=previous:
            previous=len(selected)
            selected.update(r['id'] for r in records if r.get('parent_id') in selected)
        records=[r for r in records if r['id'] in selected]
    models=[r for r in records if r.get('kind')=='llm'];roles=defaultdict(lambda:{'calls':0,'failed':0,'elapsed_ms':0})
    tokens={'input':0,'output':0};estimated=0;unpriced=0
    for r in models:
        m=r.get('metrics',{});role=m.get('role','unknown');roles[role]['calls']+=1
        roles[role]['failed']+=r.get('status')=='failed';roles[role]['elapsed_ms']+=r.get('elapsed_ms',0)
        inp=m.get('prompt_tokens',0);out=m.get('completion_tokens',0)
        tokens['input']+=inp;tokens['output']+=out
        rate=(prices or {}).get(m.get('model'))
        if rate and r.get('status')=='completed' and 'total_tokens' in m:
            estimated+=(inp*rate['input_per_million']+out*rate['output_per_million'])/1_000_000
        else:unpriced+=1
    hotspots=[]
    for r in records:
        elapsed=r.get('elapsed_ms')
        if elapsed is None and r.get('status')=='running' and r.get('started_at'):
            try:elapsed=round((datetime.now(timezone.utc)-datetime.fromisoformat(r['started_at'])).total_seconds()*1000)
            except (ValueError,TypeError):pass
        if elapsed is not None:
            hotspots.append({'name':r.get('name'),'kind':r.get('kind'),'status':r.get('status'),
                'elapsed_ms':max(0,elapsed),'role':r.get('metrics',{}).get('role'),
                'queue_wait_ms':r.get('metrics',{}).get('queue_wait_ms',0)})
    return {'record_source':source,'includes_offline':include_offline,'historical_json_included':scan_files,'task_id':task_id,'trace_count':len(records),'model_calls':len(models),'roles':dict(roles),'tokens':tokens,
            'operation_timings':operation_timings(records),
            'model_health':{'failed_calls':sum(r.get('status')=='failed' for r in models),
                'truncated_calls':sum(r.get('metrics',{}).get('finish_reason')=='length' for r in models),
                'reported_reasoning_tokens':sum(r.get('metrics',{}).get('reasoning_tokens',0) for r in models),
                'thinking_control_mismatch_calls':sum(r.get('metrics',{}).get('thinking_control_mismatch') is True for r in models)},
            'longest_steps':sorted(hotspots,key=lambda row:row['elapsed_ms'],reverse=True)[:12],
            'timing_basis':'每条为该步骤的含子调用耗时；并行或嵌套步骤不能相加为任务总耗时。running为观测时已等待时长。',
            'estimated_cost':round(estimated,6) if prices else None,'unpriced_calls':unpriced,
            'cost_basis':'用户提供每百万token费率；未区分供应商缓存命中价格，失败调用可能缺少用量，不等于账单',
            'draft_tool_calls':sum(r.get('name')=='registry_import_exam_draft' for r in records),
            'platform_writes':None,
            'delivery_basis':'工具调用不等于实际创建次数；平台写入结果以导入收据和回读记录为准'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--task-id');parser.add_argument('--scan-files',action='store_true');parser.add_argument('--include-offline',action='store_true');parser.add_argument('--prices',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/telemetry-summary.json');args=parser.parse_args()
    prices=json.loads(args.prices.read_text()) if args.prices else None
    report=summarize(ROOT/'outputs/traces',args.task_id,prices,scan_files=args.scan_files,include_offline=args.include_offline)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
