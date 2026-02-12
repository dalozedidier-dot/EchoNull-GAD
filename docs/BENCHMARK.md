# Benchmark public (GAD)

Objectif: crédibiliser EchoNull-GAD avec un mode benchmark reproductible, basé sur des métriques GAD standardisées.

## Mode light (sans PyG)

Script:
- `benchmarks/public_benchmark.py`

Il génère un graphe de base (synthetic par défaut), produit des variantes normales vs anomalies de type *null-trace*
(nœuds silencieux, edges manquants, bridges coupés), puis calcule:

- EchoNull score
- Baselines light (structure pure): `missing_edge_ratio`, `isolated_ratio`, `missing+isolated`

Métriques:
- ROC AUC
- Average Precision (AP)
- Recall@k (sur EchoNull)

## Mode datasets publics (optionnel)

Si `torch_geometric` est installé, le même script supporte:

- `--dataset cora`
- `--dataset pubmed`

Exemple:
```bash
python benchmarks/public_benchmark.py --dataset cora --variants 200 --out-dir bench_out_cora
```

## Baselines "heavy" (roadmap)

Baselines GAD classiques (DOMINANT, CoLA, GCNAE, ...) demandent typiquement PyG/Torch.
Le repo contient un squelette `benchmarks/baselines_pyg.py` (non implémenté) pour brancher ces modèles
dans le pipeline de benchmark, une fois les dépendances activées.

Suggestion d'approche:
1) valider le mode light (rapide, zéro friction)
2) ajouter un extra `pyg` et des baselines heavy progressivement, avec AUC/AP/recall@k sur Cora/PubMed
