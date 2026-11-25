"""Plot business-stage and post-closure call counts from the two matched studies."""
from collections import Counter
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
PAPER = ROOT / "paper"


def counts(files, wrapped):
    totals = Counter()
    episodes = Counter()
    for path in files:
        record = json.loads(path.read_text())
        row = record["row"] if wrapped else record
        arm = row["arm"]
        episodes[arm] += 1
        after = sum(event.get("detail") == "workflow_closed" for event in row["events"])
        totals[arm, "before"] += len(row["calls"]) - after
        totals[arm, "after"] += after
    assert episodes == {"contract": 360, "route_table": 360}
    return totals


def main():
    old = counts((ROOT / "strong-backend-autonomous" / "episodes").glob("*.json"), False)
    new = counts((OUT / "episodes" / "strong").glob("*.json"), True)
    plt.rcParams.update({"font.size": 9, "pdf.fonttype": 42, "axes.spines.top": False,
                        "axes.spines.right": False, "axes.spines.left": False})
    fig, ax = plt.subplots(figsize=(7.0, 2.35))
    names = ["Qwen3.8-Flash  /  table", "Qwen3.8-Flash  /  contract",
             "Qwen4-Max  /  table", "Qwen4-Max  /  contract"]
    arms = ["route_table", "contract"] * 2
    x = [3.4, 2.7, 1.45, .75]
    pairs = list(zip((old, old, new, new), arms))
    before = [counts[arm, "before"] for counts, arm in pairs]
    after = [counts[arm, "after"] for counts, arm in pairs]
    ax.barh(x, before, height=.48, color="#185879", label="Through business outcome", zorder=3)
    ax.barh(x, after, left=before, height=.48, color="#e8b169", edgecolor="#b0732d",
            linewidth=.55, label="After workflow closure", zorder=3)
    for y, a, b in zip(x, before, after):
        ax.text(a / 2, y, f"{a:,}", color="white", ha="center", va="center", weight="bold")
        ax.text(a + b / 2, y, f"{b:,}", color="#382612", ha="center", va="center", size=8)
    ax.set(yticks=x, yticklabels=names, xlim=(0, 11500), ylim=(.3, 3.8), xlabel="Tool calls (360 runs per arm)")
    ax.tick_params(axis="y", length=0, pad=7)
    ax.xaxis.set_major_formatter(lambda number, _: f"{int(number):,}")
    ax.xaxis.grid(alpha=.23, zorder=0)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1), frameon=False, ncol=2, borderaxespad=0)
    fig.subplots_adjust(left=.28, right=.97, top=.84, bottom=.21)
    fig.savefig(PAPER / "figures" / "strong-call-stages.pdf")
    fig.savefig(OUT / "strong-call-stages.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
