"""FastAPI transport with durable task events and legacy workbench compatibility.

Agent execution lives in a separate Worker. Legacy handlers are reused as a
synchronous service adapter; no second HTTP server or reverse proxy is involved.
"""
from courseagent.paths import ROOT as WORKSPACE_ROOT
import asyncio
import io
import json
from email.message import Message
from pathlib import Path
from typing import Literal
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import Response,StreamingResponse,JSONResponse
from pydantic import BaseModel,Field
from starlette.concurrency import run_in_threadpool
from courseagent import app as legacy
from courseagent.task_store import TaskStore,store_for

ROOT=WORKSPACE_ROOT

class ServiceAdapter(legacy.Handler):
    def reply(self,body,content_type='application/json; charset=utf-8',status=200,filename=None):
        headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}
        if filename:headers['Content-Disposition']=f'attachment; filename="{filename}"'
        self.response=Response(body,status_code=status,media_type=content_type,headers=headers)

def dispatch(method,path,headers,body):
    handler=object.__new__(ServiceAdapter)
    handler.path=path;handler.headers=Message();handler.rfile=io.BytesIO(body)
    for name,value in headers.items():handler.headers[name]=value
    handler.headers.replace_header('Content-Length',str(len(body))) if 'Content-Length' in handler.headers else handler.headers.__setitem__('Content-Length',str(len(body)))
    if method=='GET':handler.do_GET()
    else:handler.do_POST()
    return handler.response

class StartTask(BaseModel):
    prompt:str=Field(min_length=1,max_length=12000)
    name:str=Field(default='',max_length=240)
    classroom_url:str=''
    course:str=''
    execute:bool=False


def create_app(root=ROOT):
    api=FastAPI(title='Educoder Assignment Agent',version='0.4.0')
    root=Path(root)
    @api.exception_handler(HTTPException)
    async def http_error(request,error):
        return JSONResponse({'error':error.detail},status_code=error.status_code)
    def check_origin(request):
        origin=request.headers.get('origin')
        if origin and origin!=str(request.base_url).rstrip('/'):
            raise HTTPException(403,'不接受其他网页发起的修改')
    @api.get('/api/health')
    async def health():return {'ok':True,'service':'fastapi','task_backend':'sqlite','worker':'independent','published':False}
    @api.post('/api/agent-start',status_code=202)
    def start_task(payload:StartTask,request:Request):
        check_origin(request)
        from courseagent.agent_jobs import start
        import copy
        document=copy.deepcopy(legacy.load_state())
        if payload.name:document['name']=payload.name
        sources=json.loads(legacy.SOURCES.read_text())['sources'] if legacy.SOURCES.exists() else []
        try:return start(root,document,{'prompt':payload.prompt},sources,
                         {'classroom_url':payload.classroom_url,'course':payload.course},execute=payload.execute)
        except ValueError as error:raise HTTPException(409,str(error)) from None
    @api.get('/api/agent-events')
    async def events(request:Request,after:int=0):
        if after<0:raise HTTPException(400,'事件游标不正确')
        try:cursor=max(after,int(request.headers.get('last-event-id','0')))
        except ValueError:raise HTTPException(400,'事件游标不正确') from None
        async def stream():
            nonlocal cursor
            # A reconnect replays durable events. Heartbeats keep proxies alive.
            yield ': connected\n\n'
            while not await request.is_disconnected():
                batch=await run_in_threadpool(store_for(root).events,after=cursor)
                if batch:
                    for item in batch:
                        cursor=item['seq']
                        yield 'id: '+str(cursor)+'\nevent: progress\ndata: '+json.dumps(item,ensure_ascii=False)+'\n\n'
                else:yield ': heartbeat\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    @api.api_route('/{path:path}',methods=['GET','POST'])
    async def compatible(request:Request,path:str):
        # Incremental migration: existing document/review/export APIs share the same service code.
        length=request.headers.get('content-length','0')
        try:size=int(length)
        except ValueError:raise HTTPException(400,'请求大小不正确') from None
        if size>25_000_000:raise HTTPException(413,'最多25 MB')
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>25_000_000:raise HTTPException(413,'最多25 MB')
        return await run_in_threadpool(dispatch,request.method,request.url.path,dict(request.headers),bytes(body))
    return api

api=create_app()

if __name__=='__main__':
    import argparse,uvicorn
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    # SSE is intentionally long lived; it must not hold a restart indefinitely.
    uvicorn.run(api,host='127.0.0.1',port=args.port,timeout_graceful_shutdown=5)
