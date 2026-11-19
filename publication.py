"""Portable verification/configuration for the sanitized research publication."""
import hashlib
import json
import os
from pathlib import Path

REPO=Path(__file__).resolve().parent


def model_path():
    return Path(os.environ.get('LOCAL_MODEL_PATH',str(REPO/'models/Qwen3-1.7B-4bit'))).expanduser()


def verify_snapshot():
    manifest=REPO/'PUBLICATION_MANIFEST.json'
    if not manifest.exists():
        raise RuntimeError('Publication manifest missing; do not substitute historical private-machine freezes.')
    data=json.loads(manifest.read_text())
    for name,expected in data['sha256'].items():
        path=REPO/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise RuntimeError('Published artifact changed: '+name)
    return True
