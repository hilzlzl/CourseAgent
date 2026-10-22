"""Bounded, content-addressed bridge from sourcing snapshots to verification.

Sources never wait for a verifier's queue slot. Final candidates are drained
before joining; results only overlay unchanged questions. The existing task
checkpoint callbacks persist completed per-question stages across restarts.
"""
import copy
from concurrent.futures import ThreadPoolExecutor,wait
from contextvars import copy_context
import threading
import time


class CandidatePipeline:
    def __init__(self,ordinary=None,coding=None,capacity=4):
        if capacity<1:raise ValueError('Candidate capacity must be positive')
        from courseagent.verification_tools import verify_ordinary_answers,verify_programming_answers
        self.tools={'ordinary':ordinary or verify_ordinary_answers,'programming':coding or verify_programming_answers}
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='candidate-verifier')
        self.lock=threading.RLock();self.slots=threading.BoundedSemaphore(capacity)
        self.keys=set();self.updates={};self.futures=[];self.branch_futures={'ordinary':[],'programming':[]};self.pending=0
        self.stats={'submitted_questions':0,'peak_pending_batches':0,'deferred_snapshots':0,'completed_batches':0}

    @staticmethod
    def identity(branch,q):
        from courseagent.ordinary_verification import basis as ordinary_basis
        from courseagent.programming_verification import basis as coding_basis
        return branch,q['id'],(ordinary_basis if branch=='ordinary' else coding_basis)(q)

    def offer(self,branch,document):
        from courseagent.ordinary_verification import current
        from courseagent.programming_verification import current_report
        field='questions' if branch=='ordinary' else 'programming_questions'
        checker=current if branch=='ordinary' else current_report
        batch_size=6 if branch=='ordinary' else 1
        with self.lock:
            candidates=[copy.deepcopy(q) for q in document.get(field,[]) if q.get('selected') and not q.get('approved')
                        and not checker(q) and self.identity(branch,q) not in self.keys]
            submitted=0
            for offset in range(0,len(candidates),batch_size):
                if not self.slots.acquire(blocking=False):
                    self.stats['deferred_snapshots']+=1;break
                batch=candidates[offset:offset+batch_size]
                keys=[self.identity(branch,q) for q in batch];self.keys.update(keys)
                self.pending+=1;self.stats['submitted_questions']+=len(batch)
                self.stats['peak_pending_batches']=max(self.stats['peak_pending_batches'],self.pending)
                try:
                    future=self.pool.submit(copy_context().run,self._verify,branch,field,batch,time.monotonic())
                    self.futures.append(future);submitted+=len(batch)
                    self.branch_futures[branch].append(future)
                except BaseException:
                    self.keys.difference_update(keys);self.pending-=1;self.slots.release();raise
            return submitted

    def _verify(self,branch,field,batch,queued_at):
        from courseagent.model_client import model_phase,BudgetExhausted
        try:
            from courseagent.observability import span
            with span('candidate_verify_'+branch,metrics={'queue_wait_ms':round((time.monotonic()-queued_at)*1000),'question_count':len(batch)}),model_phase('checking'):
                result=self.tools[branch].invoke({'document':{field:batch},'retry_failed':False})['document']
                # Retry only unfinished requests, with per-question stage caches.
                # Content conflicts and bad source programs go to replacement.
                retry_batch=[q for q in result.get(field,[]) if
                    q.get('verification_state',{}).get('failure',{}).get('code') in ('transport','format','output_limit')]
                if retry_batch:
                    retry=self.tools[branch].invoke({'document':{field:retry_batch},'retry_failed':True})['document']
                    by_id={q['id']:q for q in retry.get(field,[])}
                    result[field]=[by_id.get(q['id'],q) for q in result.get(field,[])]
            with self.lock:
                for q in result.get(field,[]):self.updates[self.identity(branch,q)]=copy.deepcopy(q)
                self.stats['completed_batches']+=1
        except BudgetExhausted as error:
            from courseagent.verification_state import publish,failure_info
            for q in batch:
                publish(branch,q,'candidate_wait',status='paused',failure=failure_info(error))
            with self.lock:
                for q in batch:self.updates[self.identity(branch,q)]=copy.deepcopy(q)
        finally:
            with self.lock:self.pending-=1;self.slots.release()

    def merge(self,document):
        from courseagent.verification_state import merge_updates
        with self.lock:
            matching={}
            for field,branch in [('questions','ordinary'),('programming_questions','programming')]:
                for q in document.get(field,[]):
                    update=self.updates.get(self.identity(branch,q))
                    if update:matching[(branch,q['id'])]=update
            return merge_updates(document,matching)

    def drain(self):
        # surface failures instead of dropping a failed Future
        with self.lock:futures=list(self.futures)
        wait(futures)
        for future in futures:future.result()

    def drain_branch(self,branch):
        with self.lock:futures=list(self.branch_futures[branch])
        wait(futures)
        for future in futures:future.result()

    def finish(self,ordinary,coding):
        # Slots skipped during a source burst are filled without losing work.
        while True:
            self.drain()
            count=0
            for branch,state in [('ordinary',ordinary),('programming',coding)]:
                state['document']=self.merge(state['document'])
                count+=self.offer(branch,state['document'])
            if count==0:break
        return ordinary,coding

    def close(self):
        self.pool.shutdown(wait=True,cancel_futures=False)
