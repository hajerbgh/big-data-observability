# Big Data Observability — US Accidents (2016–2023)

Projet de profilage, de contrôle qualité et de détection d'anomalies sur le dataset US Accidents. Les traitements Python utilisent Pandas en lecture par chunks afin de borner la mémoire utilisée. Cette solution est adaptée à un traitement local sur fichier ; elle ne prétend pas remplacer un moteur distribué comme Spark pour un cluster ou un débit temps réel élevé.

## Structure

```text
data/
  US_Accidents_March23.csv
  batches/                 # micro-lots écrits par le processeur
  quality_metrics.csv      # métriques des règles, par lot
  alerts_log.csv           # alertes de volume, drift et outliers
  performance_log.csv      # chronométrage et mémoire, par lot
notebooks/
  data_profiling.ipynb
src/
  quality_rules.py
  anomaly_detection.py
  batch_processor.py
requirements.txt
```

Les fichiers de `data/` sont des données locales et ne sont pas suivis par Git.

## Installation

Depuis la racine du dépôt :

```powershell
python -m pip install -r requirements.txt
```

## Partie 1 — Data profiling

Le notebook `notebooks/data_profiling.ipynb` présente les dimensions et types, les valeurs manquantes, les doublons de lignes, les statistiques numériques, les fréquences des principales modalités catégorielles et les valeurs aberrantes numériques par la règle IQR (1,5 × IQR). Il calcule également le profil horaire et peut exporter les métriques qualité.

Le notebook charge le dataset complet en mémoire. Pour une machine limitée en RAM, exécuter plutôt le processeur par lots décrit en partie 4.

## Partie 2 — Règles de qualité

`src/quality_rules.py:run_data_quality_checks` retourne une ligne par règle avec :

- `Rule_Category`, `Target_Attribute`
- `Error_Count`, `Affected_Record_Count`, `Total_Record_Count`
- `Conformity_Rate_%`

Les contrôles portent sur la complétude de chaque attribut, l'unicité des ID sur l'ensemble du flux (index SQLite temporaire sur disque), le format parseable des dates et des champs numériques, les limites physiques de coordonnées (latitude [-90, 90], longitude [-180, 180]), la sévérité (entier de 1 à 4), la plage configurée de température (-50 à 130 °F) et l'ordre chronologique strict `Start_Time < End_Time`. Les valeurs manquantes sont traitées par la règle de complétude ; elles ne sont pas comptées une seconde fois comme valeurs invalides ou dates incohérentes.

Les bornes physiques et les champs critiques sont des règles métier à confirmer avec le propriétaire des données avant un usage opérationnel.

## Partie 3 — Anomalies et dérive

`src/anomaly_detection.py:detect_volume_and_drift_anomalies` produit un DataFrame d'alertes :

- **Volume** : comparaison de chaque décompte quotidien avec la distribution historique quotidienne ; une alerte est émise à partir de |z-score| ≥ 3. Au moins sept jours de référence sont nécessaires. Le processeur exige au moins trois dates dans le lot et exclut ses premier et dernier jours pour limiter les faux positifs dus aux lots qui coupent une journée. L'écart-type est protégé par une borne de type Poisson lorsque les volumes historiques sont constants.
- **Data drift** : Population Stability Index (PSI) sur `Severity`, `Temperature(F)` et `Distance(mi)`. Les intervalles numériques sont définis par les déciles historiques ; le PSI ≥ 0,2 déclenche une alerte.
- **Valeurs numériques aberrantes** : limites IQR historiques sur température et distance ; alerte si au moins 1 % des valeurs courantes sont hors limites.

Dans le processeur, le premier micro-lot fournit la référence aux lots suivants. Il s'agit d'une référence de démarrage, non d'une référence métier certifiée ; pour une surveillance récurrente, enregistrer une période historique stable et représentative.

## Partie 4 — Traitement par micro-lots

Depuis la racine du dépôt :

```powershell
python -c "from src.batch_processor import simulate_micro_batches; simulate_micro_batches('data/US_Accidents_March23.csv', chunk_size=500000)"
```

La lecture, les contrôles qualité, la détection et l'écriture se font lot par lot. Le processeur génère les métriques qualité pour chaque lot ainsi qu'un journal de performance comprenant les durées de lecture, de contrôles, d'écriture et totale, le débit et la mémoire estimée du DataFrame.

### Comparer deux tailles de lots

Exécuter les deux configurations séparément ; chaque exécution écrit ses journaux dans son propre dossier pour permettre la comparaison sans écrasement :

```powershell
python -c "from src.batch_processor import simulate_micro_batches; simulate_micro_batches('data/US_Accidents_March23.csv', 100000, 'data/benchmarks/batches_100k', 'data/benchmarks/100k')"
python -c "from src.batch_processor import simulate_micro_batches; simulate_micro_batches('data/US_Accidents_March23.csv', 1000000, 'data/benchmarks/batches_1m', 'data/benchmarks/1m')"
```

Comparer les fichiers `performance_log.csv` produits dans les deux dossiers de journaux. Les temps dépendent du matériel, du cache disque et des autres processus ; conserver la même machine et répéter les mesures pour une comparaison défendable. Ce benchmark relit et réécrit le dataset complet à chaque exécution.

## Périmètre restant

Le dashboard Power BI et son raccordement aux journaux ne sont pas inclus dans les parties 1 à 4. Les seuils de détection et les résultats de performance doivent être validés sur plusieurs exécutions et avec des périodes de référence représentatives avant toute mise en production.
