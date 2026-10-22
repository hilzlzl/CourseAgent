# Open Deep Research researcher port

Upstream: https://github.com/langchain-ai/open_deep_research

Revision: `1b7d2e80db9faa586165c60e09096dbbfd483a64`

`upstream/` contains the unmodified researcher implementation and state file
for review, not runtime imports. `provenance.json` records their checksums.
The upstream MIT license is retained in `LICENSE`.

`researcher.py` ports the core `researcher`, `researcher_tools` and
`compress_research` graph. This is an adapted source integration, not an
installation of the complete upstream application or a direct import of its
unchanged `researcher_subgraph`.

Changes:

- Synchronous execution fits the existing worker and task budgets.
- Model and tools are injected. The existing model relay/settings stay in use;
  structured JSON decisions become LangChain tool-call messages, so provider
  support for native tool calling is not required.
- One bounded batch tool per decision; independent searches run concurrently
  inside that tool. Successful observations checkpoint before the next call.
- Completion comes from the project's actual question/material handoff and
  budgets. A model cannot certify question quotas, answers or platform delivery.
- Compression returns a structured source manifest; original page text is
  passed intact to extraction. No summarizing away stems/options/examples.
- No research supervisor fan-out, user clarification loop or report generator.
  Existing ordinary/programming branches keep their ownership and parallelism.
