"""Exercise malicious paths, links, duplicates, digest and overwrite protection."""
import hashlib,importlib.util,io,json,tarfile,tempfile
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('archive_extractor',BASE/'scripts/extract_research_archives.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
checks=[]
for case in ('parent_path','absolute_path','symlink','duplicate','wrong_prefix','digest_mismatch','overwrite_conflict'):
    with tempfile.TemporaryDirectory(prefix='archive-safety-') as folder:
        root=Path(folder);archive=root/'fixture.tar.gz';name='s/episodes/item.txt'
        if case=='parent_path':name='../escaped.txt'
        if case=='absolute_path':name='/escaped.txt'
        if case=='wrong_prefix':name='s/private/item.txt'
        count=2 if case=='duplicate' else 1
        with tarfile.open(archive,'w:gz') as tar:
            for _ in range(count):
                info=tarfile.TarInfo(name)
                if case=='symlink':info.type=tarfile.SYMTYPE;info.linkname='../../escaped.txt';info.size=0;tar.addfile(info)
                else:info.size=1;tar.addfile(info,io.BytesIO(b'B'))
        entry={'path':'fixture.tar.gz','sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'file_count':count,'uncompressed_bytes':0 if case=='symlink' else count,'largest_member_bytes':1,'allowed_prefixes':['s/episodes/']}
        if case=='digest_mismatch':entry['sha256']='0'*64
        manifest=root/'manifest.json';manifest.write_text(json.dumps({'archives':{'s':entry}}))
        module.BASE=root;module.MANIFEST=manifest;out=root/'out'
        if case=='overwrite_conflict':
            target=out/'s/episodes/item.txt';target.parent.mkdir(parents=True);target.write_bytes(b'A')
        try:module.extract('s',out)
        except (ValueError,FileExistsError):pass
        else:raise AssertionError('Unexpected acceptance: '+case)
        if case=='overwrite_conflict':assert target.read_bytes()==b'A'
        assert not (root/'escaped.txt').exists()
        checks.append({'case':case,'passed':True})
print(json.dumps({'all_passed':True,'checks':checks,'model_api_calls':0}))
