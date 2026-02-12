# Graph I/O

EchoNull-GAD propose un loader léger via `load_graph(path, fmt=None)`.

## Formats supportés

- GraphML (`graphml`) via `networkx.read_graphml`
- GML (`gml`) via `networkx.read_gml`
- GPickle (`gpickle`) via `networkx.read_gpickle`
- Edge list (`edgelist`) via `networkx.read_edgelist`
- CSV (`csv`) : edge list CSV, colonnes auto-détectées
- JSON (`json`) : structure simple nodes/edges

## CSV : conventions

Détection de colonnes source/target via (ordre de priorité) :
- source/target
- src/dst
- start/end
- from/to
- u/v

Sinon, fallback : les deux premières colonnes.

Toutes les valeurs sont converties en string.

## JSON : conventions

Supporte :
- {"edges":[{"source":"A","target":"B"}, ...]}
- {"edges":[["A","B"], ...]}
- optionnel : {"nodes":[...]} pour préserver des nœuds isolés

## Neo4j export

Un export Neo4j se ramène souvent à une edge-list CSV, donc compatible si les colonnes source/target sont présentes. Pour un export en deux fichiers (nodes.csv + edges.csv), l’approche recommandée est de charger d’abord edges.csv et d’ajouter nodes.csv comme liste de nœuds si besoin.
