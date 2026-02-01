# NullTrace

Prototype v0.1 du module NullTrace.

## Installation
pip install -r requirements.txt
pip install -r requirements-dev.txt
pre-commit install

## Lancement
python src/null_trace.py tests/data/current.csv --previous-shadow tests/data/previous_shadow.csv --output-dir outputs

## Objectif
Produire un shadow descriptif et un diff descriptif entre deux versions de données.

## Format attendu des CSV

NullTrace utilise deux fichiers de référence :

- `data/current.csv`
- `data/previous_shadow.csv` (ou un `manifest.json` produit par un snapshot précédent)

Contraintes minimales :
- CSV UTF-8, séparateur `,`
- Ligne d’en-tête obligatoire
- Colonnes numériques privilégiées (les colonnes non numériques peuvent être ignorées selon l’implémentation)
- Ordre des lignes stable si tu compares des snapshots alignés (sinon utiliser une clé/colonne d’index dans les données)

Fixtures de test :
- `tests/data/current.csv`
- `tests/data/previous_shadow.csv`
