# Scaling

Objectif : passer de 50 runs à 500-1000 runs avec statut CI fiable et artefacts auditables.

## Principes appliqués

1) Statut CI fiable
- Retry 3x dans les workflows scaling.
- Le workflow échoue si toutes les tentatives échouent.
- Upload d’artefacts en `if: always()`.

2) Outputs exploitables
- `run_summary.csv` est flat.
- CSV normalisés par module.
- `runs.jsonl` garde un payload détaillé append-only.

3) Manifest sous contrôle
- `runs` détaillé dans le manifest est limité par `manifest-max-detailed-runs`.
- Au-delà, le détail reste dans `runs.jsonl`, hashé et référencé.

## Pistes pour aller plus loin

- Chunking des runs (batches) et early stopping basé sur stabilisation de la variance du score.
- Joblib ou Dask pour parallel scaling, avec gestion mémoire.
- Exports Gephi uniquement pour une fraction de runs ou sur demande (flag).
