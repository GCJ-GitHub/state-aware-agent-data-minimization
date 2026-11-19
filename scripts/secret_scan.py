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
failures=[];scanned=0
for f in root.rglob('*'):
    rel=f.relative_to(root)
    if not f.is_file() or any(x in rel.parts for x in ('.git','__pycache__','.venv','models','runs')):continue
    if f.name=='.env' or (f.name.startswith('.env.') and f.name!='.env.example'):
        failures.append((str(rel),'forbidden_env_file'));continue
    try:text=f.read_text()
    except UnicodeDecodeError:
        failures.append((str(rel),'unexpected_binary'));continue
    scanned+=1
    for label,pattern in patterns.items():
        if re.search(pattern,text):failures.append((str(rel),label))
if failures:
    for filename,label in failures:print(filename,label)
    raise SystemExit(1)
print('SECRET_SCAN_PASSED',scanned,'text files; no matched values printed')
