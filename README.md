# EchoNull-GAD

EchoNull-GAD est un petit pipeline de détection d’anomalies orienté graphes, centré sur une idée simple : certaines anomalies ne sont pas un signal présent, mais un signal attendu qui n’apparaît pas. Le dépôt produit des runs auditables, des CSV exploitables, un manifest hashé, et des artefacts zip.

## Définition : qu’est-ce qu’une « null-trace anomaly » ?

Une null-trace anomaly est une anomalie par absence.

Intuition :
- Un nœud qui devrait « parler » devient silencieux (degré ou interactions qui s’effondrent).
- Une arête attendue n’existe plus, ou n’apparaît jamais là où elle était structurellement plausible.
- Un motif attendu disparaît (triangle, communauté, pont entre deux zones).
- Une partie du graphe se vide, se déconnecte ou perd sa cohérence locale.

Lecture mathématique simple :
- On compare un graphe observé G à une structure de référence ou à une expectation (baseline, historique, modèle).
- L’anomalie se manifeste par un déficit d’arêtes, de motifs, de connectivité, ou de densité locale, au-delà d’un seuil attendu.

Voir `docs/NULL_TRACE.md` pour une version plus détaillée.

## Entrées : formats de graphes supportés

Le loader intégré supporte les formats suivants :
- GraphML (`.graphml`)
- GML (`.gml`)
- GPickle (`.gpickle`, `.pkl`)
- Edge list (`.edgelist`, `.txt`)
- CSV edge list (`.csv`)
- JSON simple (`.json`)

Détails, conventions de colonnes, et exemples dans `docs/GRAPH_IO.md`.

## Utilisation rapide

### Sweep

```bash
python echonull.py sweep --runs 50 --thresholds 0.25,0.5,0.7,0.8 --workers 8 --enable-viz
```

Avec un graphe d’entrée :

```bash
python echonull.py sweep --runs 50 --graph data/my_graph.graphml --graph-format graphml
```

Choisir explicitement le dossier de sortie :

```bash
python echonull.py sweep --runs 200 --output-base _echonull_out/sweep_custom_200
```

### GAD (score final)

```bash
python echonull.py gad --runs 50
```

## Paramètres à sweeper

Les hyperparamètres actuellement exposés sont :
- `thresholds` : liste de seuils ou taux d’échantillonnage d’arêtes pour générer des variantes de graphes.
- `seed-base` : base de seed pour la reproductibilité.
- `workers` : parallélisation process.
- `enable-ml` : active un débruitage torch optionnel sur la brique NullTrace.
- `score-weights` : pondérations (graph, nulltrace, voidmark) pour le score final.
- `graph`, `graph-format` : charge un graphe externe au lieu du mode synthétique.
- `export-graphs` : export GML + GraphML par seuil (utile pour Gephi). Désactivé par défaut.
- `manifest-max-detailed-runs` : limite automatique d’inclusion détaillée des runs dans le manifest.

Voir `docs/SWEEP_PARAMS.md` pour la liste complète avec ranges par défaut.

## Sorties

Chaque run produit un dossier `_echonull_out/<output-base>/` avec notamment :
- `overview.json`
- `env.json` (Python, plateforme, pip freeze tronqué, git sha)
- `run_summary.csv` (flat, colonnes scalaires)
- `riftlens_by_threshold.csv`
- `nulltrace.csv`
- `voidmark.csv`
- `runs.jsonl` (payload détaillé append-only)
- `manifest.json` (hashes + pointeurs)
- `<output-base>.zip` (bundle des fichiers)

## CI

- `ci.yml` exécute `pre-commit run --all-files` puis les tests.
- `test-scaling.yml` et `test-scaling-low.yml` exécutent un sweep avec retries et statut fiable : le workflow échoue si toutes les tentatives échouent, tout en uploadant les artefacts.

## Baselines GAD

Les comparaisons standard (DOMINANT, CoLA, GCNAE, etc.) et les datasets publics (Cora, PubMed…) sont décrits dans `docs/BASELINES.md`. L’implémentation d’un bench automatisé est prévue comme module optionnel, sans alourdir le coeur.

## Scaling

Résultats observés sur 50 runs : l’artefact zip fait environ 1.6 MB (ordre de grandeur). Pour 500 à 1000 runs, le manifest limite automatiquement la partie détaillée et pousse le détail dans `runs.jsonl`.

Voir `docs/SCALING.md`.
