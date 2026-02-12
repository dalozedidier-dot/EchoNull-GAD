# Null-trace anomalies

## Définition

Une null-trace anomaly est une anomalie qui se manifeste par une absence.

C’est l’inverse d’un outlier classique où l’on observe un pic ou une valeur extrême. Ici, ce qui est anormal, c’est qu’un signal attendu ne se produit pas, ou qu’une structure attendue n’existe plus.

## Exemples typiques en graphe

1) Nœud silencieux
- Un nœud dont le degré ou l’activité chute brutalement.
- Variante : un nœud « pivot » devient isolé.

2) Arête manquante
- Une relation attendue n’apparaît plus entre deux nœuds historiquement liés.
- Version plus stricte : la probabilité attendue d’existence de l’arête est haute, mais l’arête n’est pas là.

3) Motif absent
- Disparition de triangles, de cliques, ou d’un motif local stable.
- Chute du clustering coefficient local dans une zone précise.

4) Pont cassé
- Une arête ou un petit ensemble d’arêtes qui relie deux communautés disparaît.
- La connectivité globale reste correcte, mais l’accessibilité entre sous-graphes se dégrade.

## Lecture mathématique minimale

On observe un graphe G et une expectation E(G) issue d’un baseline :
- historique
- simulation
- modèle probabiliste
- graphe de référence

On mesure ensuite des déficits :
- déficit d’arêtes : |E_ref| - |E_obs|
- déficit de motifs : triangles_ref - triangles_obs
- déficit de connectivité : distance moyenne, composantes, centralités

Une null-trace anomaly apparaît si ces déficits dépassent une tolérance définie par domaine.

## Dans EchoNull-GAD

Dans le dépôt, la brique RiftLens calcule des métriques simples par seuil et la brique NullTrace peut dériver des deltas basés sur un déficit d’arêtes au-delà de l’attendu.
