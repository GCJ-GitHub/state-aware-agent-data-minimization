"""Conservative source/artifact scan; never prints a matched secret value."""
import re
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
patterns={
 'github_token':r'(?:gh[pousr]_[A-Za-z0-9_]{25,}|github_pat_[A-Za-z0-9_]{25,})',
 'service_secret':r'(?:sk-[A-Za-z0-9_-]{25,}|xox[baprs]-[A-Za-z0-9-]{20,}|AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16})',
 'internal_endpoint':r'https?://[^\s"\x27<>]*(?:xiaohongshu|rednote)[^\s"\x27<>]*',
 'private_home_path':r'/'+'Users'+r'/[^/\s"\x27]+/',
 'literal_bearer':r'(?i)\bBearer\s+[A-Za-z0-9._-]{24,}',
 'private_key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s*\n[A-Za-z0-9+/=]{20,}',
 'literal_credential':r'''(?i)(?:api[_-]?key|secret|password|access[_-]?token)\s*[=:]\s*["']([A-Za-z0-9_-]{24,})["']''',
}
failures=[];scanned=0;archives_scanned=0
import hashlib,json,tarfile
from extract_research_archives import checked_members
archive_index_path=root/'artifacts/2026-11-23/ARCHIVE_MANIFEST.json'
archive_entries=json.loads(archive_index_path.read_text())['archives'] if archive_index_path.exists() else {}
archive_paths={entry['path']:entry for entry in archive_entries.values()}

def check_text(name,text):
    global scanned
    scanned+=1
    for label,pattern in patterns.items():
        if re.search(pattern,text):failures.append((name,label))

for f in root.rglob('*'):
    rel=f.relative_to(root)
    if not f.is_file() or any(x in rel.parts for x in ('.git','__pycache__','.venv','models','runs')):continue
    if f.name=='.env' or (f.name.startswith('.env.') and f.name!='.env.example'):
        failures.append((str(rel),'forbidden_env_file'));continue
    name=rel.as_posix()
    if name in archive_paths:
        entry=archive_paths[name]
        if hashlib.sha256(f.read_bytes()).hexdigest()!=entry['sha256']:
            failures.append((name,'archive_digest_mismatch'));continue
        with tarfile.open(f,'r:gz') as tar:
            members=checked_members(tar,entry)
            for member in members:
                try:text=tar.extractfile(member).read().decode('utf-8')
                except UnicodeDecodeError:
                    failures.append((name+'!'+member.name,'unexpected_binary_member'));continue
                check_text(name+'!'+member.name,text)
        archives_scanned+=1;continue
    try:text=f.read_text()
    except UnicodeDecodeError:
        failures.append((name,'unexpected_binary'));continue
    check_text(name,text)
if failures:
    for filename,label in failures:print(filename,label)
    raise SystemExit(1)
print('SECRET_SCAN_PASSED',scanned,'text files/members;',archives_scanned,'archives validated; no matched values printed')
