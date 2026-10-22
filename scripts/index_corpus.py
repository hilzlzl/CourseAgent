"""Read-only corpus migration/preparation; never changes review, jobs, or platform state."""
import argparse,json
from pathlib import Path
from courseagent.retrieval_runtime import get_index,remember_sources,remember_document,ROOT
from courseagent.semantic_embeddings import LocalEmbeddings

def prepare(*,vectors=False,download=False):
    summaries={'sources':0,'snapshots':0,'candidate_upserts':0,'rejected_snapshots':0}
    sources=ROOT/'data/sources.json'
    if sources.exists():summaries['sources']=remember_sources(json.loads(sources.read_text()).get('sources',[]))
    paths=list((ROOT/'outputs/agent-tasks').glob('*/task.json'))
    # Newer verified receipts supersede earlier snapshots of the same id.
    for p in sorted(paths,key=lambda p:p.stat().st_mtime):
        try:
            value=json.loads(p.read_text());document=value.get('result')
            if not isinstance(document,dict):continue
            summaries['candidate_upserts']+=remember_document(document);summaries['snapshots']+=1
        except (ValueError,TypeError,KeyError):summaries['rejected_snapshots']+=1
    index=get_index()
    if vectors:
        index.embeddings=LocalEmbeddings(allow_download=download)
        summaries['vector_preparation']=index.prepare_vectors()
    summaries.update(index.stats());summaries['platform_writes']=0
    return summaries

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--vectors',action='store_true')
    parser.add_argument('--download-model',action='store_true');args=parser.parse_args()
    report=prepare(vectors=args.vectors,download=args.download_model)
    (ROOT/'outputs/retrieval-index-preparation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
