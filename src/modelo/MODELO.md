# Modelo municipal: K-means y reglas de negocio

## Propósito

`src/modelo/modelo.py` agrupa los 785 municipios de Andalucía en perfiles comparables. K-means no predice facturación, no estima rentabilidad y no selecciona por sí solo los cinco municipios finales. Su función es crear grupos homogéneos para que la regla de negocio compare la competencia dentro de contextos parecidos.

La entrada es la tabla Gold:

```text
data/processed/gold/tabla_oro_municipios_andalucia.parquet
```

La salida del clustering es:

```text
data/resultados/clusters.csv
```

El CSV contiene exactamente dos columnas:

```text
municipality_code
cluster
```

Los códigos se guardan como texto para conservar los ceros iniciales.

## Variables de entrada

El modelo utiliza tres variables de la Gold:

1. `population_18_50`, transformada con `log1p` para reducir la asimetría del tamaño municipal.
2. `population_growth_pct`, que en la implementación actual representa el crecimiento de la población total entre el primer y el último año disponible.
3. `mean_net_income_per_person`.

Después de la transformación, las variables se estandarizan con `StandardScaler`.

No se utilizan como entradas del clustering:

- `municipality_code`, nombres o provincia;
- coordenadas o geometrías;
- `gyms_count`;
- `other_sports_facilities_count`;
- `gyms_per_10k_18_50`.

La competencia se reserva para la interpretación y la regla posterior de candidatos. Así se evita que el clustering defina los grupos usando directamente el mismo indicador que después se utiliza para medir oportunidad.

## Tratamiento de datos

- Se exige un universo de 785 municipios.
- El código municipal debe ser único y tener cinco dígitos.
- La población de 18 a 50 años debe ser positiva.
- Población y crecimiento no pueden tener valores faltantes.
- La renta negativa, los infinitos y los casos sin ninguna renta observada generan error.
- Las rentas faltantes se imputan con la mediana observada y los municipios afectados quedan registrados en el resultado del entrenamiento.
- La Gold de entrada no se modifica.

Estas reglas hacen que un resultado numérico no oculte problemas de calidad de datos.

## Selección de k

El modelo prueba automáticamente:

```text
k = 2, 3, 4, 5, 6
```

Para cada valor calcula:

- `inertia`: suma de distancias internas al centroide;
- `silhouette`: separación y cohesión de los clusters;
- `min_cluster_size`;
- `max_cluster_size`;
- `eligible`.

Una solución es elegible únicamente si todos sus clusters tienen al menos 30 municipios. Entre las soluciones elegibles se selecciona la de mayor silhouette. Si hay empate, se selecciona el menor `k`.

La silhouette ayuda a evaluar la estructura geométrica de los datos, pero no demuestra que una solución sea económicamente mejor. Por eso también hay que revisar tamaños de cluster, perfiles en unidades originales y estabilidad de la decisión.

Los parámetros fijos son:

```text
random_state = 42
n_init = 20
```

## Relación con negocio

El flujo posterior usa el cluster como contexto, no como ranking:

```text
Gold
  -> K-means
  -> cluster por municipio
  -> competencia por cada 10.000 personas 18-50
  -> comparación con la media del cluster
  -> candidate_flag
  -> selección de hasta cinco municipios
```

La capa de negocio utiliza la Gold y los clusters para:

- calcular competencia ponderada con los pesos acordados;
- comparar la presión competitiva de un municipio con la de su cluster;
- marcar candidatos cuando la competencia relativa queda por debajo de la media del cluster;
- comparar la selección del modelo con el baseline de los cinco municipios con mayor población objetivo.

El cluster no tiene orden: el número `2` no significa que sea mejor que el `1`. Los perfiles deben interpretarse con sus medianas de población, crecimiento y renta, y después con los indicadores de competencia.

## Ejecución

Desde la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m src.modelo.modelo `
  --gold data/processed/gold/tabla_oro_municipios_andalucia.parquet `
  --output data/resultados/clusters.csv
```

En WSL/bash, usa `/` y `\` para continuar líneas:

```bash
./.venv/Scripts/python.exe -m src.modelo.modelo \
  --gold data/processed/gold/tabla_oro_municipios_andalucia.parquet \
  --output data/resultados/clusters.csv
```

El modelo puede ejecutarse sin `.env` y sin conexión a S3 cuando la Gold ya existe localmente.

## Tests

Los tests principales son:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_tabla_oro.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_modelo.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_negocio.py
```

`test_tabla_oro.py` valida la construcción y persistencia de Gold. `test_modelo.py` valida la selección de `k`, silhouette, reproducibilidad, imputación y exportación de códigos. `test_negocio.py` valida que la selección posterior usa los clusters y la competencia, sin alterar la lógica del clustering.

## Limitaciones actuales

La Gold agrega el crecimiento de población total, mientras que el diseño analítico inicial proponía crecimiento específico de 18 a 50 años. Esa decisión debe confirmarse antes de presentar la `k` como definitiva.

Asimismo, OSM clasifica actualmente las instalaciones como `gym` u `other_sport_facility`; no se separan todavía pabellones y estaciones de aire libre. La regla de competencia debe documentar este límite de cobertura.
