# EchoNull-GAD

Lightweight CI-native framework for graph anomaly detection via parameter sweeps.

## Badges

[![Tests](https://github.com/dalozedidier-dot/EchoNull-GAD/actions/workflows/ci.yml/badge.svg)](https://github.com/dalozedidier-dot/EchoNull-GAD/actions/workflows/ci.yml)
[![Scaling Tests](https://github.com/dalozedidier-dot/EchoNull-GAD/actions/workflows/test-scaling.yml/badge.svg)](https://github.com/dalozedidier-dot/EchoNull-GAD/actions/workflows/test-scaling.yml)

Pour un badge coverage, le plus simple est d'activer Codecov puis d'ajouter son badge ici.

## Current scaling status (février 2026)

| Runs | Mode  | Statut   | Temps approx. | Zip size      | Notes                   |
|------|-------|----------|---------------|---------------|-------------------------|
| 5    | sweep | OK       | ~1 min        | ~5 Mo         | Test initial            |
| 50   | sweep | A tester | 10 a 20 min   | ~50 a 150 Mo  | En attente de run       |
| 100  | sweep | A tester | 20 a 40 min   | ~100 a 300 Mo | En attente              |
| 200  | sweep | A tester | 40 a 90 min   | ~200 a 600 Mo | Limite hosted runners   |

## Comment tester scaling

Onglet Actions, workflow "EchoNull-GAD Scaling Test", Run workflow, choisis 50, 100 ou 200 runs.
Telecharge l'artefact et verifie:
- echonull.log (temps total, erreurs)
- manifest.json (present, hashes)
- dossiers run_0001 a run_XXXX
- viz_overview.png
- run_summary.csv (nombre de lignes)

## Features cles

- Scaling massif en GitHub Actions hosted
- Detection anomalies (null-traces, edges manquants, voids)
- Reproductibilite via SHA-256 sur artefacts
- Visualisation integree (viz_overview.png)

## Lancer en local

Installer:
  pip install -r requirements.txt

Executer:
  python echonull.py sweep --runs 50 --workers 8 --enable-viz
