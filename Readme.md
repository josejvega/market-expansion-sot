# Market Expansion SOT

## Local and S3 persistence

The ingestion and cleaning wrappers in `src/ingesta/pipeline.py` and
`src/procesado/pipeline.py` apply the `SAVE_LOCALLY` and `SAVE_S3` settings.
Copy `.env.example` to `.env` and configure:

```dotenv
SAVE_LOCALLY=true
SAVE_S3=false
```

The bucket and region are configured in `.env.example`; copy that file and
adjust the values for your environment.

The example currently saves outputs locally and does not upload them. Set both
flags to `true` to keep local copies and upload to S3, or set only `SAVE_S3`
to `true` to upload without retaining project output files. In S3-only mode,
generated files are staged in a temporary directory for the duration of the
upload and removed afterward. Source response caches and JSON manifests are
never uploaded.

Raw CSV datasets go to `raw/data/`. Silver Parquet datasets go to
`processed/silver/`, and rejected rows go to `processed/silver/failed/`.
CNIG boundary rejects are written to
`limites_municipales_andalucia_failed.parquet` with a `failure_reason` column.
The cleaned gym points are spatially joined to the CNIG boundaries and saved as
`gyms_with_municipality_andalusia.parquet` in `processed/silver/`; unmatched
gyms remain in the output with null municipality fields.
The municipality Gold table keeps the latest population and income values,
the population change from the first to latest available year, and separate
gym and other-sports-facility counts. It also includes
`gyms_per_10k_18_50`, calculated as
`gyms_count / population_18_50 * 10000`; it is null when the target population
is zero. It is saved locally under
`data/processed/gold/tabla_oro_municipios_andalucia.parquet` and uploaded to
the S3 `gold/` prefix.
`notebooks/01_ingesta.ipynb` uploads immediately after each raw download when
`SAVE_S3=true`; `notebooks/02_calidad.ipynb` similarly persists each cleaned
dataset as it is produced. There are no separate upload cells.

When the quality notebook reads a raw CSV, it tries the configured S3 object
first. If the object is missing or S3 cannot be reached, it logs a warning and
uses the local CSV when available. If neither source is available, it raises an
error rather than continuing with missing data.

Set `S3_BUCKET` in `.env` and provide AWS credentials through the standard
boto3 credential chain. Uploads fail explicitly if the bucket is missing or
AWS rejects a transfer, so the pipeline cannot report a successful run after
a failed upload. When local persistence is enabled, the local output remains
available after an upload failure. In S3-only mode, temporary outputs are
removed when processing exits, including when an upload raises an error.

Repeated uploads use the same object keys and replace the current objects
(subject to the bucket's versioning settings), rather than creating new keys.
Most cleaners produce the same rows from the same input, but processing is not
strictly byte-for-byte idempotent: CNIG Silver records `loaded_at_utc` at each
run, and refreshed ingestions can produce new source data and timestamps.

The CNIG raw dataset is downloaded through the ingestion wrapper used by
`notebooks/01_ingesta.ipynb`; the cleaning module is called through the
processing wrapper in `notebooks/02_calidad.ipynb`.

INE CSV downloads stream with a five-minute read timeout and retry transient
connection failures up to three times. A failed transfer is discarded instead
of being treated as a complete source file.

## Run the notebooks

Install the project dependencies and execute the ingestion and processing
notebooks in order:

```bash
python -m pip install -r requirements.txt
python run.py
```

`run.py` executes `01_ingesta.ipynb` followed by `02_calidad.ipynb`, using the
project root as the working directory. Each cell has a one-hour timeout by
default; pass `--timeout SECONDS` to change it. The command stops and returns
an error if a notebook cell fails. It creates a temporary Jupyter kernel using
the same Python interpreter that launched `run.py` and does not overwrite the
notebook files.

To run the complete ingestion and processing flow without reading from or
uploading anything to S3, use:

```bash
python run.py --local-only
```

This option overrides the storage settings for the duration of the run, saves
raw and processed outputs locally, and produces the Gold table at
`data/processed/gold/tabla_oro_municipios_andalucia.parquet`. It does not
change `.env` or the process environment after the command finishes. Internet
access to the source data providers is still required for fresh downloads.

This also works on EC2 when the instance has the project dependencies installed,
network access to the data sources, and AWS permissions for the configured S3
bucket. Prefer an EC2 instance role for AWS credentials; boto3 uses its standard
credential chain. Configure the storage variables in `.env` or in the process
environment before running the command.

## Municipality clustering

After Gold has been generated, install the updated requirements and select the
project's Python environment in `notebooks/03_modelo.ipynb`. Run its cells in
order, or run the same model directly from the project root:

```bash
python -m pip install -r requirements.txt
python -m src.modelo.modelo
```

The model notebook first displays the client's baseline: the five municipalities
with the largest population aged 18-50, using the same Gold and `top5_baseline`
function as business. This reference selection has no competition or viability
filter and creates no additional output file. Economic comparison remains in
the business notebook. The model CLI runs clustering only.

This is a separate local-only stage: `run.py` still executes ingestion and
quality only. The model reads the existing Gold at
`data/processed/gold/tabla_oro_municipios_andalucia.parquet`, does not modify it,
and writes only `data/resultados/clusters.csv`. The CSV contains exactly 785
unique municipality codes and two columns, `municipality_code` and `cluster`.
Read it with `pd.read_csv(path, dtype={"municipality_code": "string"})` to
preserve leading zeros. Cluster labels are group identifiers, not a ranking.

The implementation is in `src/modelo/modelo.py`. Features are
`log1p(population_18_50)`, `population_growth_pct` and
`mean_net_income_per_person`, followed by `StandardScaler`. Growth refers to
total population, not specifically ages 18-50. Missing income is imputed with
the observed municipal median and affected codes are logged and displayed in
the notebook; missing population or growth, invalid codes, duplicate keys,
non-finite values and a universe other than 785 municipalities raise errors.
Competition counts are never model inputs.

K-means uses `random_state=42` and `n_init=20`. For k=2..6, the model reports
inertia, silhouette and minimum/maximum cluster sizes. It selects the highest
silhouette among solutions with at least 30 municipalities in every cluster,
preferring smaller k on exact ties. If no solution qualifies, it raises an
error instead of exporting unreliable groups. The notebook shows cluster
profiles in original units; these use imputed income where applicable.
Reproduction requires the same Gold and dependency versions.

Candidates, weighted competition (1 / 0.1), revenue, viability, top-five
selection, baseline comparison and business sensitivity are deliberately left
to the downstream business module. Clustering metrics do
not demonstrate economic improvement or predict actual profitability.

## Business integration

After generating clusters, run `notebooks/04_negocio.ipynb` or:

```bash
python -m src.negocio.ejecutar
```

Business reads the same local Gold and prefers `data/resultados/clusters.csv`
over the optional Parquet alternative. Missing inputs, invalid codes or labels,
and differences between the 785 Gold and cluster municipality codes raise errors
instead of producing a partial comparison. No provisional Gold is used.

The central competition measure is exactly
`gyms_count + 0.1 * other_sports_facilities_count`. Gold does not distinguish
sports centres from outdoor stations, so its aggregate is used directly, without
inventing a breakdown or adding facilities not present in ingestion. Scenarios
use weights 1/0 (gyms only), 1/0.1 (central), and 1/1 (all equal). Different
weights within the aggregate are rejected. Existing business formulas, economic
assumptions and sensitivity scenarios are otherwise unchanged.

Outputs are local in `data/outputs/`, including `baseline_central.csv`,
`seleccion_modelo_central.csv`, `comparacion_central.csv`,
`sensibilidad_detalle.csv` and `sensibilidad_frecuencias.csv`. Baseline selects
the five largest target populations; the model selects up to five viable
candidates below their cluster's mean weighted competition per 10,000 people.
There is no forced filling of five places when fewer qualify. A full local
sequence is notebooks 01 to 04, or `python run.py --local-only` followed by
`python -m src.modelo.modelo` and `python -m src.negocio.ejecutar`.