# Baselines et métriques GAD

## Baselines classiquement citées
- DOMINANT
- CoLA
- GCNAE
- ANOMALOUS
- (et autres GAD GNN)

## Datasets publics
- Cora, CiteSeer, PubMed
- (éventuellement Reddit, ogbn-arxiv si le cadre le justifie)

## Méthode propre

1) Fixer un protocole
- train/val/test
- injection d’anomalies contrôlées (node/edge/structure/motif absent)
- seeds multiples

2) Mesures à reporter
- AUC ROC, Average Precision
- recall@k, precision@k
- métriques structurelles interprétables (isolated nodes, edge deficit)

3) Positionner EchoNull-GAD
- soit comme complément interprétable (signaux faibles par absence)
- soit comme baseline lightweight face aux GNN lourds
