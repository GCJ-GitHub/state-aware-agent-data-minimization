"""Generate tables, vector figures and data exports from archived experiment results."""
import argparse
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARMS = dict(upfront='Upfront', agent_only='Agent only', state_guard='State guard')
FAMILIES = dict(single='Single route', switch='Route switch', multi='Multiple stages')
STUDIES = (
    ('Refund cases', 'route-table-comparison/trace.json', 'results'),
    ('Independent goals', 'logistics-composition-study/results.json', 'results'),
    ('Dependent goals', 'logistics-dependent-study/results.json', 'results'),
    ('Signature rule (new)', 'logistics-signature-study/results.json', 'new_cases'),
    ('Signature rule (regression)', 'logistics-signature-study/results.json', 'regression'),
)
METRICS = ('n', 'task_success', 'unique_raw_fields', 'hindsight_unused_fields',
           'expired_evidence_fields', 'tools', 'model_calls', 'confirmations', 'any_leak')


def write_csv(name, rows):
    with (HERE / 'data' / name).open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, default=next((p for p in HERE.parents if (p / 'necessity-three-arm-holdout').is_dir()), None))
    args = parser.parse_args()
    if args.repo is None:
        parser.error('--repo must point to the archived experiment repository')
    holdout = args.repo / 'necessity-three-arm-holdout'
    summary = json.loads((holdout / 'summary.json').read_text())
    analysis = json.loads((holdout / 'analysis.json').read_text())
    metrics = json.loads((holdout / 'metrics.json').read_text())
    assert len(metrics) == summary['episodes'] == 1080
    (HERE / 'data').mkdir(exist_ok=True)
    (HERE / 'figures').mkdir(exist_ok=True)
    rows = []
    for family, groups in summary['tables'].items():
        for arm in ARMS:
            subset = [r for r in metrics if r['arm'] == arm and (family == 'all' or r['family'] == family)]
            if not subset:
                continue
            row = groups[arm]
            assert row['n'] == len(subset)
            for key in METRICS[1:]:
                assert row[key] == sum(r[key] for r in subset), (arm, family, key)
            rows.append(dict(family=family, arm=arm, **{key: row[key] for key in METRICS}))
    write_csv('autonomous-summary.csv', rows)
    write_csv('autonomous-effects.csv', [
        dict(comparator=arm, metric=metric, estimate=row['delta_per_episode'], lower=row['ci95'][0],
             upper=row['ci95'][1]) for arm, group in analysis['contrasts_state_guard_minus'].items()
        for metric, row in group.items()])
    write_csv('autonomous-runs.csv', [
        {key: row[key] for key in ('id', 'family', 'arm', 'seed', *METRICS[1:])} for row in metrics])
    lines = []
    for arm, label in ARMS.items():
        r = summary['tables']['all'][arm]
        values = [label, f"{r['task_success']}/{r['n']}", *(str(r[k]) for k in METRICS[2:])]
        lines.append(' & '.join(values) + r' \\')
    (HERE / 'autonomous_rows.tex').write_text('\n'.join(lines) + '\n' + r'\bottomrule' + '\n')
    scripted = []
    for label, path, key in STUDIES:
        raw = json.loads((args.repo / path).read_text())
        assert raw['model_calls'] == 0
        for arm in ('route_table', 'contract'):
            part = [r for r in raw[key] if r['arm'] == arm]
            scripted.append(dict(study=label, arm=arm, runs=len(part),
                                 completed=sum(r['complete'] for r in part),
                                 fields=sum(len(r.get('fields', r.get('delivered_fields'))) for r in part),
                                 denied=sum(r['denied_reads'] for r in part),
                                 confirmations=sum(r['confirmations'] for r in part)))
    write_csv('scripted-summary.csv', scripted)
    lines = []
    for a, b in zip(scripted[::2], scripted[1::2]):
        assert {k:v for k,v in a.items() if k != 'arm'} == {k:v for k,v in b.items() if k != 'arm'}
        lines.append(f"{a['study']} & {a['completed']}/{a['runs']} & {a['fields']} & "
                     f"{a['denied']} & {a['confirmations']}" + r' \\')
    (HERE / 'scripted_rows.tex').write_text('\n'.join(lines) + '\n' + r'\bottomrule' + '\n')
    plot_results(summary)
    plot_method()


def plot_results(summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 9, 'pdf.fonttype': 42, 'axes.spines.top': False,
                         'axes.spines.right': False})
    colors = ['#A2AAB7', '#CA7736', '#24678C']
    fig, axes = plt.subplots(1, 2, figsize=(7, 2.4), layout='constrained')
    for ax, key, title in zip(axes, ('hindsight_unused_fields', 'expired_evidence_fields'),
                             ('(a) Eventually unused fields', '(b) Fields released on stale evidence')):
        for i, (arm, label) in enumerate(ARMS.items()):
            values = [summary['tables'][family][arm][key] for family in FAMILIES]
            x = [j + (i - 1) * .24 for j in range(3)]
            bars = ax.bar(x, values, width=.22, color=colors[i], label=label)
            ax.bar_label(bars, labels=[str(v) if v else '' for v in values], fontsize=7, padding=2)
            ax.scatter([x[j] for j,v in enumerate(values) if not v], [0]*sum(v==0 for v in values),
                       marker='_', color=colors[i], zorder=5, clip_on=False)
        ax.set_xticks(range(3), list(FAMILIES.values()))
        ax.set_title(title, loc='left', fontsize=10)
        ax.set_ylabel('Field instances')
        ax.grid(axis='y', alpha=.2)
        ax.set_axisbelow(True)
        ax.set_ylim(0, max(ax.get_ylim()[1]*1.2, 170 if key.startswith('expired') else 620))
    axes[1].legend(loc='upper right', fontsize=8, frameon=False)
    fig.savefig(HERE / 'figures' / 'exposure.pdf', metadata={'CreationDate': None})
    plt.close(fig)


def plot_method():
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    fig, ax = plt.subplots(figsize=(7, 2.04))
    ax.set(xlim=(0, 14), ylim=(0, 4))
    ax.axis('off')
    nodes = [(0.1, 2.25, 2.7, 'Agent submits\\nplan and read'),
             (3.35, 2.25, 3.1, 'Derive step need\\nfrom goal and contracts'),
             (7.05, 2.25, 3.0, 'Check current evidence\\nat field delivery'),
             (10.65, 2.25, 3.2, 'Release missing\\nstep inputs only'),
             (6.75, .22, 3.6, 'Deny stale request;\\nreturn recovery options')]
    for x,y,w,label in nodes:
        face = '#eaf2f7' if y > 1 else '#faefe6'
        ax.add_patch(FancyBboxPatch((x,y),w,1.05,boxstyle='round,pad=.04,rounding_size=.14',
                                   linewidth=.9,edgecolor='#395269',facecolor=face))
        ax.text(x+w/2,y+.525,label.replace('\\n','\n'),ha='center',va='center',fontsize=8.2)
    def arrow(a,b):
        ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-|>',mutation_scale=9,lw=1,color='#395269'))
    for a,b in [(2.8,3.35),(6.45,7.05),(10.05,10.65)]:
        arrow((a,2.77),(b,2.77))
    arrow((8.55,2.25),(8.55,1.27))
    ax.plot([6.75,1.45],[.74,.74],color='#395269',lw=1)
    arrow((1.45,.74),(1.45,2.25))
    ax.text(4.0,1.02,'Refresh and replan within authorization',ha='center',fontsize=7.5)
    ax.text(8.55,3.65,'Trusted business state and evidence versions',ha='center',fontsize=8)
    arrow((8.55,3.54),(8.55,3.31))
    fig.subplots_adjust(left=.015,right=.985,top=.97,bottom=.05)
    fig.savefig(HERE / 'figures' / 'mechanism.pdf', metadata={'CreationDate': None})
    plt.close(fig)


if __name__ == '__main__':
    main()
