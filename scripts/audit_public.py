"""Audit the public allowlist without displaying secret values or file contents."""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {'data', 'outputs', '.runtime', '.browser-profile', '.git', '.venv', 'node_modules', '__pycache__'}
SECRET_PATTERNS = [
    re.compile(r'\b(?:sk|ghp|gho|github_pat|lsv2_pt)_[A-Za-z0-9_-]{24,}'),
    re.compile(r'\bsk-[A-Za-z0-9_-]{24,}'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'https://www\.educoder\.net/classrooms/[A-Za-z0-9_-]{4,}/'),
    re.compile(r'(?:/mnt/[a-z]/Users/|[A-Z]:[\\/]Users[\\/])[^/\\\s\"\']+'),
]


def audit(root, files):
    root = Path(root).resolve()
    problems = []
    for relative in files:
        relative = Path(relative)
        path = root/relative
        if relative.is_absolute() or '..' in relative.parts or any(p in FORBIDDEN_PARTS for p in relative.parts):
            problems.append({'file': str(relative), 'reason': 'private_or_unsafe_path'})
            continue
        if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
            problems.append({'file': str(relative), 'reason': 'missing_or_unsafe_file'})
            continue
        if relative.name.endswith('.local.json') or relative.name.startswith('.env'):
            problems.append({'file': str(relative), 'reason': 'local_configuration'})
        if path.stat().st_size > 2_000_000:
            problems.append({'file': str(relative), 'reason': 'unexpected_large_file'})
        text = path.read_text(encoding='utf-8', errors='replace')
        # The scanner's own detection patterns are code, not user identifiers.
        for number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                problems.append({'file': str(relative), 'line': number, 'reason': 'credential_or_personal_identifier_pattern'})
        if relative.name.endswith('.example.json'):
            try:
                config = json.loads(text)
                if config.get('api_key'):
                    problems.append({'file': str(relative), 'reason': 'example_key_must_be_empty'})
            except ValueError:
                problems.append({'file': str(relative), 'reason': 'invalid_example_json'})
    return problems


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    manifest = json.loads((args.root/'scripts/public_manifest.json').read_text())
    issues = audit(args.root, manifest['files'])
    print(json.dumps({'passed': not issues, 'checked_files': len(manifest['files']), 'issues': issues}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if issues else 0)
