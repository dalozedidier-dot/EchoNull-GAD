# Paramètres de sweep

## Paramètres CLI

- `--runs` (int) : nombre de runs.
- `--thresholds` (csv float) : seuils ou taux d’échantillonnage, ex: 0.25,0.5,0.7,0.8
- `--seed-base` (int) : seed de base.
- `--workers` (int) : nombre de process.
- `--enable-viz` : génère une viz d’overview (si matplotlib dispo).
- `--enable-ml` : active un denoiser torch sur la partie NullTrace (optionnel).
- `--score-weights` (csv float) : pondérations (graph, nulltrace, voidmark).
- `--output-base` (str) : chemin dossier de sortie.
- `--graph` (str) : chemin d’un graphe d’entrée.
- `--graph-format` (str) : graphml, gml, gpickle, edgelist, csv, json.
- `--export-graphs` : export GML + GraphML par seuil.
- `--manifest-max-detailed-runs` (int) : limite de runs détaillés inclus dans manifest.

## Ranges par défaut recommandés

- `thresholds` : 0.1 à 0.9 (4 à 8 points).
- `workers` : 4 à 12 selon CPU.
- `runs` : 50 (smoke), 200 (profil), 500 à 1000 (scaling).
