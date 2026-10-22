"""Create a new reviewed source tree and ZIP. Never publish or copy runtime data."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from audit_public import audit

ROOT = Path(__file__).resolve().parents[1]


def export(root, destination):
    root = Path(root).resolve()
    destination = Path(destination).resolve()
    if destination.exists() or destination.with_suffix('.zip').exists():
        raise ValueError('Destination already exists; choose a new directory.')
    manifest = json.loads((root/'scripts/public_manifest.json').read_text())
    issues = audit(root, manifest['files'])
    if issues:
        raise ValueError('Public audit failed: '+json.dumps(issues, ensure_ascii=False))
    # Compare against actual local secrets too; never log their values.
    secrets = []
    for config_name in ('model-config.local.json', 'langsmith-config.local.json'):
        config_path = root/config_name
        if not config_path.exists():
            continue
        def collect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    credential_field = key.lower() in {'api_key', 'key', 'token', 'access_token', 'api_token', 'secret'} or key.lower().endswith('_api_key')
                    if isinstance(item, str) and credential_field and len(item) >= 12:
                        secrets.append(item.encode())
                    elif isinstance(item, (dict, list)):
                        collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
        collect(json.loads(config_path.read_text(encoding='utf-8')))
    content = {}
    for relative in manifest['files']:
        data = (root/relative).read_bytes()
        if any(secret in data for secret in secrets):
            raise ValueError('Local secret detected in public file: '+relative)
        content[relative] = data
    destination.mkdir(parents=True)
    for relative, data in content.items():
        target = destination/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    receipt = {'format': 'courseagent-public-source-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
               'runtime_data_included': False, 'files': {name: hashlib.sha256(data).hexdigest() for name, data in content.items()}}
    (destination/'PUBLIC_RELEASE_MANIFEST.json').write_text(json.dumps(receipt, indent=2)+'\n')
    archive_path = destination.with_suffix('.zip')
    with ZipFile(archive_path, 'w', ZIP_DEFLATED) as archive:
        for name in [*content, 'PUBLIC_RELEASE_MANIFEST.json']:
            archive.write(destination/name, 'CourseAgent/'+name)
    return {'directory': str(destination), 'zip': str(archive_path), 'source_files': len(content), 'published': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/public-release'/('CourseAgent-'+datetime.now().strftime('%Y%m%d-%H%M%S')))
    args = parser.parse_args()
    print(json.dumps(export(ROOT, args.output), ensure_ascii=False, indent=2))
