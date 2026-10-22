"""Run the explicitly shipped, synthetic offline suite without private fixtures."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


if __name__ == '__main__':
    manifest = json.loads((ROOT/'scripts/public_manifest.json').read_text())
    result = subprocess.run([sys.executable, '-m', 'tests.run_offline_tests', *manifest['test_suites']], cwd=ROOT)
    raise SystemExit(result.returncode)
