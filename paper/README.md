# State-Aware Data Minimization for Tool-Using Agents

- [Latest compiled paper](paper.pdf) · [LaTeX source](paper.tex) · [Bibliography](references.bib)
- [Delivery-time guard, safety property and recovery](method.tex)
- [Autonomous comparison protocol](autonomous-protocol.tex)
- [Strong baseline, maintenance and model diagnostics](completed-followups.tex)
- [AirGap-style experiment](airgap-results.tex) · [Query-order and enforcement ablation](factorial-results.tex)
- [Full experiment index and current conclusions](../docs/LATEST_RESULTS.md)

This ten-page anonymous conference draft uses two hosted model aliases and five matched model-dependent comparisons. Qwen4-Max contributes 2,736 formal runs. It also reports scripted rule-maintenance and audit studies and a separate terminal-feedback diagnostic. The central claim concerns field necessity at delivery; the refreshed route table is the strong implementation baseline.

## Build

Run from this directory with Tectonic or a compatible LaTeX distribution. The checked-in vector figures are ready for the build. No provider or model is invoked.

```bash
tectonic paper.tex
```

To regenerate the two method figures, run `python draw_method.py` with Matplotlib. To recreate the staged call-cost figure, first extract the two autonomous archives using [the repository guide](../docs/CURRENT_REPRODUCIBILITY.md), then run `python qwen4-max-paper-replication/strong_cost_figure.py` from the repository root. The original Qwen3.8-Flash export data and its generator remain in this directory for historical reproduction. The current table rows and all raw counts link back to the study outputs above.
