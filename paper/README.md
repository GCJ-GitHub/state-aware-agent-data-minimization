# State-Aware Data Minimization for Tool-Using Agents

- [Latest compiled paper](paper.pdf) · [LaTeX source](paper.tex) · [Bibliography](references.bib)
- [Delivery-time guard, safety property and recovery](method.tex)
- [Autonomous comparison protocol](autonomous-protocol.tex)
- [Strong baseline, maintenance and model diagnostics](completed-followups.tex)
- [AirGap-style experiment](airgap-results.tex) · [Query-order and enforcement ablation](factorial-results.tex)
- [External retail transfer study](external-retail.tex)
- [Gaia2 delivery window, narrow grants, and maintenance](refund-maintenance.tex)
- [Full experiment index and current conclusions](../docs/LATEST_RESULTS.md)

This twelve-page anonymous conference draft studies how the reason for reading a field can expire before the value is delivered. The evaluation retains the hosted-model and retail tool comparisons, adds a controlled delivery window on public Gaia2 tasks, and separates delivery-time checks from the scope of version binding. In a five-scenario refund rerun, narrow binding removed three avoidable denials and twelve tool calls while matching the strengthened route table. A separate scripted rule-change comparison found equal authored changes, regression scope and audit coverage under shared tooling. The full Gaia2 reachability run and the limitations of the controlled studies are recorded in the experiment index.

## Build

Run from this directory with Tectonic or a compatible LaTeX distribution. The checked-in vector figures are ready for the build. No provider or model is invoked.

```bash
tectonic paper.tex
```

To regenerate the two method figures, run `python draw_method.py` with Matplotlib. To recreate the staged call-cost figure, first extract the two autonomous archives using [the repository guide](../docs/CURRENT_REPRODUCIBILITY.md), then run `python qwen4-max-paper-replication/strong_cost_figure.py` from the repository root. The original Qwen3.8-Flash export data and its generator remain in this directory for historical reproduction. The current table rows and all raw counts link back to the study outputs above.
