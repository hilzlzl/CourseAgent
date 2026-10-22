"""Prepare synthetic task datasets offline; remote upload/evaluation are explicit opt-ins."""
import argparse
import json
import uuid
import logging
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


class SafeSDKLog(logging.Filter):
    """SDK diagnostics can embed masked keys and payloads; retain level only."""
    def filter(self,record):
        if record.levelno>=logging.WARNING:
            record.msg='LangSmith SDK transport warning; see local acceptance status (provider details omitted).'
            record.args=();record.exc_info=None;record.exc_text=None
        return True

def examples(dataset):
    return [{'id':str(uuid.uuid5(uuid.NAMESPACE_URL,'educoder:'+dataset['version']+':'+c['id'])),
             'inputs':{'prompt':c['prompt']},
             'outputs':{'counts':c['counts'],'programming_count':c['programming_count']},
             'metadata':{'case_id':c['id'],'version':dataset['version'],'synthetic':True}}
            for c in dataset['cases']]

def score(outputs,reference):
    actual=outputs.get('counts',{});expected=reference['counts']
    # Both shortages and extra questions fail quota accuracy.
    quota=all(actual.get(str(t),0)==expected.get(str(t),0) for t in range(1,6)) and outputs.get('programming_count')==reference['programming_count']
    return {'quota_match':quota,'preview_completed':outputs.get('passed') is True,
            'review_preserved':outputs.get('review_unchanged') is True,'platform_writes':outputs.get('platform_writes',0)}


def run_private_preview(runner,prompt,prefix,max_calls,max_seconds):
    from langsmith import tracing_context
    with tracing_context(enabled=False):
        report=runner(prompt,prefix,max_calls,max_seconds)
    return {k:report.get(k) for k in ('passed','counts','programming_count','model_calls','elapsed_seconds','review_unchanged','platform_writes')}

def upload(client,name,items,json_transport=False):
    from langsmith.utils import LangSmithNotFoundError
    try:dataset=client.read_dataset(dataset_name=name)
    except LangSmithNotFoundError:dataset=client.create_dataset(dataset_name=name,description='Synthetic assignment task quotas; no teacher documents or private tests.')
    existing={str(item.id) for item in client.list_examples(dataset_id=dataset.id)}
    pending=[e for e in items if e['id'] not in existing]
    if pending:
        if json_transport:
            # These small synthetic records have no attachments. JSON avoids
            # multipart uploads rejected by some local proxies.
            for item in pending:
                client.request_with_retries('POST','/examples',
                    headers={'Content-Type':'application/json'},
                    data=json.dumps({**item,'dataset_id':str(dataset.id)}).encode())
        else:client.create_examples(dataset_id=dataset.id,examples=pending)
    return {'name':name,'total':len(items),'created':len(pending)}

def main():
    logging.getLogger('langsmith.client').addFilter(SafeSDKLog())
    parser=argparse.ArgumentParser();parser.add_argument('--dataset',type=Path,default=ROOT/'evaluations/tasks-v3.json')
    parser.add_argument('--upload',action='store_true');parser.add_argument('--live',action='store_true')
    parser.add_argument('--case',action='append',help='远端实测只运行指定case ID，可重复；完整数据集仍上传')
    parser.add_argument('--direct',action='store_true',help='忽略本机代理环境变量，直接连接LangSmith')
    parser.add_argument('--json-upload',action='store_true',help='使用无附件JSON接口上传小型合成样例')
    parser.add_argument('--max-calls',type=int,default=100);parser.add_argument('--max-seconds',type=int,default=1500)
    args=parser.parse_args();source=json.loads(args.dataset.read_text());items=examples(source)
    if args.case and set(args.case)-{c['id'] for c in source['cases']}:parser.error('未知case ID')
    name='educoder-'+source['version'];out=ROOT/'outputs/langsmith-dataset.json'
    out.write_text(json.dumps({'name':name,'examples':items,'uploaded':False},ensure_ascii=False,indent=2))
    if not args.upload and not args.live:
        print(json.dumps({'prepared':len(items),'uploaded':False,'model_calls':0,'platform_writes':0}));return
    from courseagent.observability import configuration
    from langsmith import Client
    config=configuration()
    if not config['enabled'] or not config['api_key']:parser.error('请先启用并配置本地 LangSmith；离线数据集已保留')
    from urllib.parse import urlparse
    parsed=urlparse(config['endpoint'])
    if parsed.scheme!='https' or parsed.username or parsed.password:parser.error('LangSmith endpoint 必须是无凭据 HTTPS URL')
    import requests
    session=requests.Session()
    if args.direct:session.trust_env=False
    client=Client(api_key=config['api_key'],api_url=config['endpoint'],timeout_ms=15000,session=session,
                  auto_batch_tracing=False)
    print(json.dumps(upload(client,name,items,json_transport=args.json_upload),ensure_ascii=False),flush=True)
    out.write_text(json.dumps({'name':name,'examples':items,'uploaded':True},ensure_ascii=False,indent=2))
    if args.live:
        from evaluate_live_agent import run
        from langsmith.evaluation import evaluate
        def predictor(inputs):
            identity=uuid.uuid4().hex
            from courseagent.observability import span
            from langsmith import tracing_context
            # evaluate() enables automatic SDK tracing. Disable it inside the
            # business pipeline so graph states/private programs never become
            # automatic child inputs. Explicit content-free spans still run.
            with tracing_context(enabled=False), span('synthetic_evaluation_task',metrics={'task_id':identity,'synthetic':True}):
                report=run_private_preview(run,inputs['prompt'],ROOT/'outputs/langsmith-live'/identity,args.max_calls,args.max_seconds)
            # Upload metrics only; local artifacts retain all questions and private programs.
            return {k:report.get(k) for k in ('passed','counts','programming_count','model_calls','elapsed_seconds','review_unchanged','platform_writes')}
        def evaluator(run,example):
            result=score(run.outputs or {},example.outputs)
            return {'results':[{'key':key,'score':int(value)} for key,value in result.items() if key!='platform_writes']}
        data=list(client.list_examples(dataset_name=name)) if args.case else name
        if args.case:data=[e for e in data if (e.metadata or {}).get('case_id') in args.case]
        if args.case and len(data)!=len(set(args.case)):raise ValueError('远端指定样例缺失或重复，未运行空实验')
        results=evaluate(predictor,data=data,evaluators=[evaluator],max_concurrency=1,client=client,
                 experiment_prefix='educoder-preview',description='Preview only; no Educoder import or publishing.')
        rows=[]
        for item in results:
            run_record=item['run'];example=item['example']
            rows.append({'case_id':(example.metadata or {}).get('case_id'),
                         'outputs':run_record.outputs or {},
                         'scores':score(run_record.outputs or {},example.outputs)})
        report={'experiment_name':results.experiment_name,'experiment_id':str(results.experiment_id),
                'url':results.url,'completed_cases':len(rows),'platform_writes':0,'cases':rows,
                'remote_experiment_completed':True,
                'agent_cases_passed':sum(r['scores']['quota_match'] and r['scores']['preview_completed'] and r['scores']['review_preserved'] for r in rows)}
        (ROOT/'outputs/langsmith-live-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'ok':False,'error_type':type(error).__name__,
                          'message':'远端评测未完成；请检查网络、代理、权限及模型状态。未输出服务端原文或密钥。'},ensure_ascii=False))
        raise SystemExit(1) from None
