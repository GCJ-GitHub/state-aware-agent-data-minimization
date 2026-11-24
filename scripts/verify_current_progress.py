"""Offline current-release checks; --replay consumes cached model outputs only."""
import argparse,json,subprocess,sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))


def main():
    p=argparse.ArgumentParser();p.add_argument('--replay',action='store_true');a=p.parse_args()
    from publication import verify_snapshot
    verify_snapshot()
    import airgap_state_study as airgap,necessity_factorial as factorial,necessity_native_retest as native,necessity_holdout as holdout
    for module in (airgap,factorial,native,holdout):module.verify()
    for name,count in [('airgap-escalation-state-study',648),('necessity-factorial-pilot',144),('necessity-native-retest',144),('necessity-three-arm-holdout',1080)]:
        d=json.loads((BASE/name/'summary.json').read_text())
        observed=d.get('episodes',len(json.loads((BASE/name/'metrics.json').read_text())))
        assert observed==count,(name,observed);print(name,'summary count',count,'OK',flush=True)
    if not a.replay:
        print('CURRENT_RELEASE_METADATA_AND_ORIGINAL_FREEZES_VERIFIED; use --replay after extracting traces.');return
    needed={'airgap-escalation-state-study':648,'necessity-factorial-pilot':144,'necessity-native-retest':144,'necessity-three-arm-holdout':1080}
    for name,n in needed.items():
        if len(list((BASE/name/'episodes').glob('*/result.json')))!=n:
            raise RuntimeError('Missing traces; first run python scripts/extract_research_archives.py --all')
    commands=[['airgap_state_study.py','audit'],['scripts/check_state_study_results.py'],
      ['necessity_factorial.py','audit'],['scripts/check_necessity_factorial_results.py'],
      ['necessity_native_retest.py','audit'],['scripts/check_necessity_native_results.py'],
      ['scripts/audit_holdout_with_interruptions.py'],['scripts/check_necessity_holdout_results.py'],['scripts/check_holdout_state_ledger.py']]
    logs=BASE/'artifacts/verification';logs.mkdir(exist_ok=True)
    for i,cmd in enumerate(commands):
        result=subprocess.run([sys.executable]+cmd,cwd=BASE,capture_output=True,text=True)
        (logs/(f'{i+1:02d}.txt')).write_text(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError('Offline check failed: '+' '.join(cmd)+'; inspect artifacts/verification')
        print('PASS',' '.join(cmd),flush=True)
    print('CURRENT_RELEASE_ALL_OFFLINE_REPLAYS_VERIFIED; no model API calls made.')

if __name__=='__main__':main()
