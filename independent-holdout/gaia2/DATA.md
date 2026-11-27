# Gaia2 Adaptability data and reproduction

The upstream validation snapshot is [Meta Agents Research Environments Gaia2, revision c128283](https://huggingface.co/datasets/meta-agents-research-environments/gaia2/tree/c128283/adaptability). Download the Parquet directly from the upstream dataset. The repository records the complete 160-case inventory in [coverage.json](scale/coverage.json), keeps the task IDs and event types, and publishes our run metrics and tool-name traces. The original scenario payloads and application databases remain upstream.

```bash
curl --fail --location --retry 3 \
  https://huggingface.co/datasets/meta-agents-research-environments/gaia2/resolve/c128283/adaptability/validation-00000-of-00001.parquet \
  --output adaptability.parquet
echo 'e449bf40b5dbb26df844c23c62e8ea94ee313ea6dd13d4aedb730fd8c1a6230e  adaptability.parquet' | shasum -a 256 -c
```

Gaia2's native tools and verdicts were run using [ARE at a9fd2edccb4bc7e22fbf45c8482a5fef30a2a5a4](https://github.com/facebookresearch/meta-agents-research-environments/tree/a9fd2edccb4bc7e22fbf45c8482a5fef30a2a5a4), version 1.2.0, and Python 3.11. Set up the pinned upstream checkout in an isolated Python environment and install its lockfile. This includes PyArrow 22.0.0 and requests. Offline JSON summaries use Python's standard library.

For hosted reruns, set `GAIA_MAAS_URL` to a compatible, authorized full chat-completions URL and `GAIA_MAAS_DEV_KEY` to the corresponding credential through your local environment. Neither is required for offline summaries. Local runs use the indicated Qwen tag through Ollama on loopback. An environment file containing actual values belongs outside the publication.

`FREEZE.sha256` verifies the published runner and protocol bytes. `EXECUTION_FREEZE.sha256` retains the original run's fingerprints for provenance. Publication externalizes the gateway address and updates checks accordingly. The metrics, case IDs, event settings and output records are unchanged by this change.
