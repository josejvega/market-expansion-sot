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
The municipality Gold table includes municipalities with valid data in both
population and income, keeps their latest values,
the population change from the first to latest available year, and separate
gym and other-sports-facility counts. It also includes
`gyms_per_10k_18_50`, calculated as
`gyms_count / population_18_50 * 10000`; it is null when the target population
is zero. It is saved locally under
`data/processed/gold/tabla_oro_municipios_andalucia.parquet` and uploaded to
the S3 `gold/` prefix.
The quality report has one row per source with Bronze record counts, key-field
nulls, duplicate records, source-to-Gold crossing counts and treatment notes.
It is saved locally under `data/processed/quality/tabla_calidad_fuentes.parquet`
and uploaded to the S3 `processed/quality/` prefix.
The OSM gym coverage review is saved as
`data/processed/quality/municipios_dudosos_gimnasios.parquet` and uploaded to
the same S3 prefix. It uses a fixed internal reference of one gym per 10,000
residents aged 18–50; this rate is a project assumption, not a statistic derived
from OSM or an official coverage standard. A municipality is flagged for
manual review when at least one gym is expected and its observed rate is below
0.5 gyms per 10,000 residents aged 18–50. This is a review heuristic and does
not remove any municipality from Gold.
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

This also works on EC2 when the instance has the project dependencies installed,
network access to the data sources, and AWS permissions for the configured S3
bucket. Prefer an EC2 instance role for AWS credentials; boto3 uses its standard
credential chain. Configure the storage variables in `.env` or in the process
environment before running the command.

## Municipality clustering

Run `notebooks/03_modelo.ipynb` interactively after Gold has been generated.
It loads Gold locally or from S3, excludes and reports municipalities with
missing clustering variables, and plots inertia and silhouette scores. Choose
`N_CLUSTERS` based on those plots. An interactive pairwise chart shows all
clusters across the three standardized input variables. Its `asinh` display
scale compresses extreme values without dropping municipalities; hover over a
point to see the original standardized values, municipality, and province. The
remaining cells list municipalities whose weighted competitor rate is below
their cluster mean.