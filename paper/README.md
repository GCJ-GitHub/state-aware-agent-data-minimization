# State-Aware Data Minimization for Tool-Using Agents

This is an English, anonymous-author, two-column conference manuscript draft. The generic LaTeX layout can be adapted to an official venue style. The PDF lives alongside the editable source, bibliography, vector diagrams, generated table rows and CSVs.

- [Compiled manuscript](paper.pdf)
- [LaTeX source](paper.tex) and [bibliography](references.bib)
- [Tables and figure generator](make_figures.py)
- [Autonomous run-level data](data/autonomous-runs.csv), [aggregates](data/autonomous-summary.csv) and [paired effects](data/autonomous-effects.csv)
- [Scripted baseline comparison data](data/scripted-summary.csv)

The manuscript uses the frozen 1,080-attempt autonomous study and four later scripted comparisons. No models are invoked by the paper build. The scripted studies compare the two stronger enforcement backends. The autonomous study compares three release policies, with the primary contrast between the two on-demand arms.

## Rebuild

From this directory in the repository, use Python 3 with Matplotlib 3.9 or newer and a LaTeX installation. The generator finds the archived inputs by walking up from this directory. A standalone copy can use \`--repo <path-to-repository>\`.

\`\`\`bash
python3 make_figures.py
tectonic paper.tex
\`\`\`

The generator checks published counts against the run-level data and reconstructs both tables and both vector figures. The paired intervals are exported from the archived 5,000-draw analysis. The source input paths are listed in the generator.

## Submission direction

Develop the contribution as a systems-security conference paper about the data-delivery boundary, recoverability, and the result against a strong composable baseline. An evaluation in the style of [USENIX Security](https://www.usenix.org/conference/usenixsecurity27/call-for-papers) is a useful target for the systems claim. [PoPETs/PETS](https://petsymposium.org/cfp27.php) is another fit if the paper focuses on the privacy boundary and its practical consequences. PoPETs uses journal-style review and publishes accepted papers in the journal. This draft does not select a venue or cycle.

The highest-priority remaining experiment is to run the same autonomous model against both stronger backends, holding authorization, recovery, tool schema and event trigger fixed. See the repository's [follow-up plan](../docs/STRONG_BASELINE_FOLLOWUP.md) for the experiment design. Before formal submission, choose the venue style, verify its current anonymity and AI disclosure policies, and arrange an appropriate artifact link.
