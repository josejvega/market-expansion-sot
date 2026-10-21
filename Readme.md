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
`notebooks/01_ingesta.ipynb` uploads immediately after each raw download when
`SAVE_S3=true`; `notebooks/02_calidad.ipynb` similarly persists each cleaned
dataset as it is produced. There are no separate upload cells.

When the quality notebook reads a raw CSV, it tries the configured S3 object
first. If the object is missing or S3 cannot be reached, it logs a warning and
uses the local CSV when available. If neither source is available, it raises an
error rather than continuing with missing data.

Set `S3_BUCKET` in `.env` and provide AWS credentials through the standard
boto3 credential chain. S3 uploads are best-effort: if AWS is unavailable or
rejects an upload, a warning is logged and processing continues. When local
persistence is enabled, the local output remains available after an upload
failure. In S3-only mode, the temporary output is removed when processing
finishes, including after a failed upload; review the warning before relying
on that output.

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