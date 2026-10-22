"""Local capability checks only. Never send requests or print configuration values."""
import argparse
import importlib.util
import json
import shutil
import sys


def inspect(programming=False):
    dependencies = ('fastapi', 'uvicorn', 'langgraph', 'langgraph.checkpoint.sqlite',
                    'langchain_openai', 'pydantic', 'bs4', 'pypdf')
    missing = []
    for name in dependencies:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ModuleNotFoundError):
            missing.append(name)
    report = {'python': sys.version.split()[0], 'python_supported': sys.version_info >= (3, 11),
              'missing_dependencies': missing, 'node_available': bool(shutil.which('node')),
              'sandbox_checked': programming, 'model_network_requests': 0, 'platform_writes': 0}
    if not missing:
        from courseagent.model_client import model_status
        status = model_status()
        report['model_configured'] = status['configured']
        # Only the boolean capability is needed; never expose endpoint/key/model names.
    if programming and not missing:
        from courseagent.code_sandbox import available
        report['python_sandbox_ready'] = available()
        report['compilers'] = {name: bool(shutil.which(name)) for name in ('gcc', 'g++', 'javac')}
    report['ok'] = report['python_supported'] and not missing and (not programming or report.get('python_sandbox_ready', False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--programming', action='store_true', help='also run a fixed hello-world in bubblewrap')
    report = inspect(parser.parse_args().programming)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['ok'] else 1)
