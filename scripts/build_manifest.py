"""Issue a new publication fingerprint, never an original-experiment freeze."""
import argparse
import hashlib
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--write',action='store_true',help='Explicitly issue fingerprints for the reviewed publication')
a=p.parse_args()
if not a.write:raise SystemExit('Review changes first; --write issues a NEW public snapshot manifest.')
manifest=root/'PUBLICATION_MANIFEST.json'
previous=json.loads(manifest.read_text()) if manifest.exists() else {}
files={}
for f in sorted(root.rglob('*')):
    rel=f.relative_to(root)
    if not f.is_file() or f.is_symlink() or any(s in rel.parts for s in ('.git','__pycache__','.venv','models','runs')):continue
    if rel.name=='PUBLICATION_MANIFEST.json':continue
    if rel.name=='.env' or (rel.name.startswith('.env.') and rel.name!='.env.example'):raise SystemExit('Private env file present')
    files[str(rel)]=hashlib.sha256(f.read_bytes()).hexdigest()
manifest.write_text(json.dumps({'kind':'sanitized-publication-snapshot',
  'note':'Checks current published bytes. Historical freeze hashes describe the original local execution, not redacted sources.',
  'reviewed_pdf_sha256':previous.get('reviewed_pdf_sha256', {}),
  'reviewed_figure_png_sha256':previous.get('reviewed_figure_png_sha256', {}),
  'sha256':files},ensure_ascii=False,indent=2)+'\n')
print('PUBLICATION_MANIFEST_WRITTEN',len(files))
