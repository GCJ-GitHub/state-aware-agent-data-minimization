# State-Aware Data Minimization for Tool-Using Agents

- [Latest compiled paper](paper.pdf) · [LaTeX source](paper.tex) · [Bibliography](references.bib)
- [Figure 1 preview](figures/tau-bench-return-trace.png) · [SVG artwork](figures/tau-bench-return-trace.svg) · [Paired traces and offline replay](../external-retail-study/README.md#引言中的回放轨迹)
- [Delivery-time guard, safety property and recovery](method.tex)
- [Evaluation organized around three research questions](evaluation.tex)
- [Appendices with experimental protocols and full results](evaluation-details.tex) · [Gaia2 and refund rerun tables](timing-refund-details.tex)
- [Autonomous comparison protocol](autonomous-protocol.tex)
- [Strong baseline, maintenance and model diagnostics](completed-followups.tex)
- [AirGap-style experiment](airgap-results.tex) · [Query-order and enforcement ablation](factorial-results.tex)
- [External retail transfer study](external-retail.tex)
- [Compositional refund-rule maintenance and audit](refund-maintenance.tex)
- [Full experiment index and current conclusions](../docs/LATEST_RESULTS.md)

The 16-page draft opens with a matched pair of controlled retail replays. Figure 1 shows six unnecessary address values reaching the model under agent-directed reads. The contract verifier withholds those values, and both runs complete the return.

Section 3.1 uses the replay to explain four conditions at delivery. Equation (6) encodes them as request scope, current plan admissibility, step readiness, and an exact match to the missing fields defined in Equation (5). The order becomes delivered at turn 3, so the address-change plan fails the admissibility check. Algorithm 1 applies the common predicate to the current snapshot and checks grant validity in contract mode under Equation (8). Algorithm 2 describes how the agent refreshes state and continues after a denial. The wallet-refund example illustrates grant version binding and reuse of applicable verification records. [Method source](method.tex)

Sections 4.1–4.3 examine excess delivery despite correct task outcomes, the timing of the delivery check, and the recovery cost of version binding. The appendices start on page 9 and contain full tables, protocols, ablations and diagnostics.

## Build

Run from this directory with Tectonic or a compatible LaTeX distribution. The checked-in figure files include the PNG used in Figure 1 and its editable SVG. Compilation runs locally.

```bash
tectonic paper.tex
```

To regenerate the two method figures, run `python draw_method.py` with Matplotlib. To recreate the staged call-cost figure, first extract the two autonomous archives using [the repository guide](../docs/CURRENT_REPRODUCIBILITY.md), then run `python qwen4-max-paper-replication/strong_cost_figure.py` from the repository root. The original Qwen3.8-Flash export data and its generator remain in this directory for historical reproduction. The current table rows and all raw counts link back to the study outputs above.
