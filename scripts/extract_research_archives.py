"""Verify and extract lossless study archives; never executes archived content."""
import argparse,hashlib,json,shutil,tarfile
from pathlib import Path,PurePosixPath
BASE=Path(__file__).resolve().parents[1]
MANIFEST=BASE/'artifacts/2026-11-23/ARCHIVE_MANIFEST.json'


def checked_members(tar,entry):
    members=tar.getmembers();seen=set();size=0
    for m in members:
        p=PurePosixPath(m.name)
        if not m.isfile() or p.is_absolute() or '..' in p.parts or '\\' in m.name:
            raise ValueError('Unsafe archive member: '+m.name)
        if m.name in seen or not any(m.name.startswith(prefix) for prefix in entry['allowed_prefixes']):
            raise ValueError('Unexpected/duplicate member: '+m.name)
        if m.size>entry['largest_member_bytes']:raise ValueError('Unexpected member size')
        seen.add(m.name);size+=m.size
    if len(members)!=entry['file_count'] or size!=entry['uncompressed_bytes']:
        raise ValueError('Archive member totals mismatch')
    return members


def extract(study,out):
    entry=json.loads(MANIFEST.read_text())['archives'][study];archive=BASE/entry['path']
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Archive digest mismatch')
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True);written=0;reused=0
    with tarfile.open(archive,'r:gz') as tar:
        members=checked_members(tar,entry)
        for m in members:
            dest=out/m.name
            if out not in dest.resolve().parents:raise ValueError('Extraction escapes destination')
            with tar.extractfile(m) as stream:
                if dest.exists():
                    data=stream.read()
                    if not dest.is_file() or dest.read_bytes()!=data:raise FileExistsError('Refusing to overwrite different file: '+m.name)
                    reused+=1;continue
                dest.parent.mkdir(parents=True,exist_ok=True)
                with dest.open('xb') as target:shutil.copyfileobj(stream,target)
            written+=1
    return {'study':study,'written':written,'already_identical':reused,'files':entry['file_count']}


def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--list',action='store_true');g.add_argument('--all',action='store_true');g.add_argument('--study')
    p.add_argument('--out',type=Path,default=BASE);a=p.parse_args();entries=json.loads(MANIFEST.read_text())['archives']
    if a.list:
        for name,e in entries.items():print(name,e['file_count'],'files;',e['compressed_bytes'],'compressed bytes')
        return
    if a.study and a.study not in entries:p.error('Unknown study')
    for name in entries if a.all else [a.study]:print(json.dumps(extract(name,a.out)),flush=True)

if __name__=='__main__':main()
