"""Local multilingual ONNX embeddings. No hosted embedding API or paid model call.

Serving never downloads models. Explicit prepare-index performs model preparation.
"""
from courseagent.paths import ROOT as WORKSPACE_ROOT
from pathlib import Path
import sys
import threading
ROOT=WORKSPACE_ROOT
DEPENDENCIES=ROOT/'.runtime/retrieval'
if DEPENDENCIES.exists() and str(DEPENDENCIES) not in sys.path:sys.path.append(str(DEPENDENCIES))
MODEL='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
CACHE=ROOT/'data/embedding-models'

class LocalEmbeddings:
    model_id=MODEL
    def __init__(self, model=MODEL, cache_dir=CACHE, allow_download=False):
        self.model_id=model;self.cache_dir=cache_dir;self.allow_download=allow_download
        self._model=None;self._error=None;self._lock=threading.RLock()
    def embed(self, texts):
        with self._lock:
            if self._error:raise RuntimeError(self._error)
            try:
                if self._model is None:
                    from fastembed import TextEmbedding
                    self._model=TextEmbedding(model_name=self.model_id,cache_dir=str(self.cache_dir),
                                              threads=2,local_files_only=not self.allow_download)
                return [v.tolist() for v in self._model.embed(texts,batch_size=32)]
            except Exception as exc:
                self._error='Local embedding unavailable: '+type(exc).__name__
                raise RuntimeError(self._error) from exc
    def status(self):
        return {'model':self.model_id,'loaded':self._model is not None,'error':self._error,'remote_calls':0}
