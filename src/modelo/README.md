# `src/modelo`

Esta carpeta contiene las reglas analíticas reproducibles del proyecto Market Expansion.

## Baseline actual

Este es un baseline inicial. Como solo necesita la población de 18 a 50 años,
lee directamente la tabla Silver de población. La tabla Gold será la entrada
preferente cuando exista una tabla municipal integrada con población, renta,
crecimiento y competencia.

`baseline.py` implementa la práctica de referencia del challenge:

> seleccionar los cinco municipios con mayor población de 18 a 50 años.

La función `select_top_municipalities`:

- recibe la tabla Silver de población;
- utiliza el año más reciente si no se indica `year`;
- ordena por `population_18_50` de mayor a menor;
- resuelve empates por `municipality_code` para que el resultado sea reproducible;
- devuelve como máximo `top_n` municipios, cinco por defecto;
- exige una única fila por municipio y año seleccionado;
- no modifica la tabla de entrada ni escribe archivos.

## Contrato de entrada

La tabla debe contener estas columnas:

```text
municipality_code
municipality_name
year
population_18_50
```

La entrada habitual es:

```text
data/processed/silver/population_andalusia.parquet
```

generada por `src/procesado`.

## Salida

La función devuelve un `pandas.DataFrame` con:

```text
baseline_rank
municipality_code
municipality_name
year
population_18_50
```

El notebook `notebooks/03_modelo.ipynb` muestra el resultado y lo guarda en:

```text
data/processed/baseline/top_5_municipalities.csv
```

Los resultados generados bajo `data/` no se versionan porque son datos derivados locales. La lógica sí se versiona en `src/modelo` y sus pruebas en `tests/`.

## Flujo

```text
population_andalusia.parquet
            |
            v
src/modelo/baseline.py
            |
            v
notebooks/03_modelo.ipynb
            |
            v
data/processed/baseline/top_5_municipalities.csv
```

## Evolución prevista

El baseline se mantendrá como referencia fija para comparar futuros modelos. Las mejoras, como k-means, competencia relativa, renta y crecimiento, deberán implementarse como funciones separadas y compararse sobre el mismo universo de municipios y con la misma métrica de negocio.
