# State-Aware Data Minimization for Tool-Using Agents

- [Latest compiled paper](paper.pdf) · [LaTeX source](paper.tex) · [Bibliography](references.bib)
- [Figure 1 preview](figures/tau-bench-return-trace.png) · [SVG artwork](figures/tau-bench-return-trace.svg) · [Paired traces and offline replay](../external-retail-study/README.md#引言中的回放轨迹)
- [Delivery-time guard, safety property and recovery](method.tex)
- [Autonomous comparison protocol](autonomous-protocol.tex)
- [Strong baseline, maintenance and model diagnostics](completed-followups.tex)
- [AirGap-style experiment](airgap-results.tex) · [Query-order and enforcement ablation](factorial-results.tex)
- [External retail transfer study](external-retail.tex)
- [Gaia2 delivery window, narrow grants, and maintenance](refund-maintenance.tex)
- [Full experiment index and current conclusions](../docs/LATEST_RESULTS.md)

This anonymous conference draft opens with a matched pair of controlled retail replays. Figure 1 shows how an order-status change at turn 3 leaves six unnecessary address values in the model context with agent-directed reads. The contract verifier withholds those values before delivery. Both runs complete the return. The evaluation compares delivery-time checks across models and tool environments, and measures the recovery cost of binding reads to specific evidence versions.

## Build

Run from this directory with Tectonic or a compatible LaTeX distribution. The checked-in figure files include the PNG used in Figure 1 and its editable SVG. Compilation runs locally.

```bash
tectonic paper.tex
```

To regenerate the two method figures, run `python draw_method.py` with Matplotlib. To recreate the staged call-cost figure, first extract the two autonomous archives using [the repository guide](../docs/CURRENT_REPRODUCIBILITY.md), then run `python qwen4-max-paper-replication/strong_cost_figure.py` from the repository root. The original Qwen3.8-Flash export data and its generator remain in this directory for historical reproduction. The current table rows and all raw counts link back to the study outputs above.
