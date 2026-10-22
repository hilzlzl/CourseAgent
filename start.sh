#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ -x .venv/bin/python ]]; then
  courseagent_python=.venv/bin/python
else
  courseagent_python=python3
  if [[ -d .runtime/python ]]; then
    export PYTHONPATH="$PWD/.runtime/python${PYTHONPATH:+:$PYTHONPATH}"
  fi
fi
if ! "$courseagent_python" -c 'import courseagent, fastapi, uvicorn, langgraph.checkpoint.sqlite, langchain_openai, bs4, pypdf' 2>/dev/null; then
  echo '请先安装依赖：python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt && .venv/bin/python -m pip install --no-deps -e .'
  exit 1
fi
exec "$courseagent_python" -m courseagent.run_service "$@"
