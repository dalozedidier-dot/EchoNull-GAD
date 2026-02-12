# Changelog

## Unreleased

- (placeholder)

## 0.2.0

- Remove noisy `.github/workflows/blank.yml` and clean repo from generated artefacts.
- Reinforce `.gitignore` for outputs (`_echonull_out/`, `manifest.json`, `echonull.log`, zips, coverage).
- Fix mypy configuration incoherence by relying on `pyproject.toml` only (remove `mypy.ini`).
- Make scaling workflows reliable: retry 3x, always upload artefacts, fail job if all attempts fail, harmonize low/high variants.
- Add a dedicated lint job running `pre-commit run --all-files`.
- Add `--output-base`, `--graph`, `--graph-format`, `--export-graphs`, `--manifest-max-detailed-runs` to the CLI.
- Add graph loaders (GraphML, GML, GPickle, edge-list, CSV, JSON).
- Produce analysis-friendly outputs: `run_summary.csv` flat plus normalized module CSVs (`riftlens_by_threshold.csv`, `nulltrace.csv`, `voidmark.csv`) and `runs.jsonl`.
- Add `env.json` for reproducibility and reference it in `manifest.json`.
- Add GitHub Release workflow (tag-based) building sdist/wheel artefacts.
- Add public benchmark pipeline (synthetic by default; Cora/PubMed optional) reporting AUC/AP/Recall@k.
- Add sweep early stopping (mean/std stabilization), streaming `runs.jsonl`, and incremental `agg.json` for memory-stable 500–1000 runs.

## 0.1.0

- Initial EchoNull script: sweep, gad, viz, ml (optional), manifest, zip.
