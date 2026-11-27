# State-Aware Data Minimization for Tool-Using Agents

- [Latest compiled paper](paper.pdf) · [LaTeX source](paper.tex) · [Bibliography](references.bib)
- [Delivery-time guard, safety property and recovery](method.tex)
- [Autonomous comparison protocol](autonomous-protocol.tex)
- [Strong baseline, maintenance and model diagnostics](completed-followups.tex)
- [AirGap-style experiment](airgap-results.tex) · [Query-order and enforcement ablation](factorial-results.tex)
- [External retail transfer study](external-retail.tex)
- [Gaia2 delivery window, narrow grants, and maintenance](refund-maintenance.tex)
- [Full experiment index and current conclusions](../docs/LATEST_RESULTS.md)

This twelve-page anonymous conference draft opens with a controlled retail replay. The agent completes the requested return, and the model also receives six shipping-address fields it no longer needs. An order-status change invalidates the read before delivery, while user authorization stays fixed. The paper studies how a connector can withhold such values and still let the agent recover. The evaluation compares delivery-time checks across models and tool environments, and measures the recovery cost of binding reads to specific evidence versions. The [opening trace and replay instructions](../external-retail-study/README.md#引言中的回放轨迹) link the example to the archived run.

## Build

Run from this directory with Tectonic or a compatible LaTeX distribution. The checked-in vector figures are ready for the build. No provider or model is invoked.

```bash
tectonic paper.tex
```

To regenerate the two method figures, run `python draw_method.py` with Matplotlib. To recreate the staged call-cost figure, first extract the two autonomous archives using [the repository guide](../docs/CURRENT_REPRODUCIBILITY.md), then run `python qwen4-max-paper-replication/strong_cost_figure.py` from the repository root. The original Qwen3.8-Flash export data and its generator remain in this directory for historical reproduction. The current table rows and all raw counts link back to the study outputs above.
