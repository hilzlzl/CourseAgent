"""Repository workspace and bundled read-only assets.

Run an editable installation from the repository root. Local configuration,
inputs and outputs stay at that root after source files move into src/.
"""
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[1] if (PACKAGE.parents[1] / 'pyproject.toml').is_file() else Path.cwd()
WEB = PACKAGE / 'web'
BROWSER = PACKAGE / 'browser'
