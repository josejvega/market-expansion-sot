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

El modelo prueba automáticamente un rango calculado a partir del tamaño de la Gold:

```text
max_k = numero_de_municipios // tamano_minimo_de_cluster
k = 2 .. max_k
```

Con la Gold actual hay 785 municipios y el tamano minimo es 30, por lo que el
maximo teorico del barrido es `k=26`: se obtiene como `785 // 30`. El valor 26
no esta fijado en el codigo. Si cambia el universo o el tamano minimo, cambia
automaticamente el rango.

Este calculo solo establece cuantos clusters serian posibles en el caso ideal
de repartir los municipios de forma equilibrada. Despues de entrenar cada k se
comprueba el tamano real de todos sus clusters. En el primer experimento,
`k=10` ya produjo un cluster de 29 municipios, por lo que las soluciones
realmente elegibles fueron `k=2..9`.

Para cada valor calcula:

- `inertia`: suma de distancias internas al centroide;
- `silhouette`: separación y cohesión de los clusters;
- `min_cluster_size`;
- `max_cluster_size`;
- `eligible`.

Una solución es elegible únicamente si todos sus clusters tienen al menos 30 municipios. Entre las soluciones elegibles se selecciona la de mayor silhouette. Si hay empate, se selecciona el menor `k`.

El barrido hasta `max_k` sirve para explorar la curva completa. Para la
decision de negocio tambien deben revisarse estabilidad, perfiles y resultados
economicos, porque una solucion con muchos clusters puede cumplir el minimo
matematico y seguir siendo dificil de interpretar.

### Resultado del primer experimento

Con la Gold actual se evaluaron 25 valores, de `k=2` a `k=26`. La restriccion
de 30 municipios por cluster hizo elegibles las soluciones de `k=2` a `k=9`;
desde `k=10` algun cluster baja de 30 municipios.

El mejor valor de silhouette del experimento fue:

```text
k = 4
silhouette = 0.290526
min_cluster_size = 95
```

Por tanto, `k=4` es la recomendacion tecnica inicial por silhouette. No es aun
la decision definitiva de negocio: la silhouette evalua cohesion y separacion
geometrica, pero no mide facturacion, margen ni robustez de los municipios
seleccionados.

La conclusion queda pendiente de estos experimentos:

1. estabilidad de los clusters con varias semillas;
2. interpretacion de los perfiles en unidades de negocio;
3. comparacion de la seleccion frente al baseline;
4. facturacion y viabilidad bajo los mismos supuestos;
5. sensibilidad de los municipios seleccionados ante cambios de supuestos.

### Resultados de validacion del experimento

La metodologia, el detalle de las metricas y el criterio de decision estan
documentados en este fichero. Los CSV tecnicos generados por
`src/modelo/experimentos.py` se analizan en los notebooks del proyecto.

Se ejecuto `src/modelo/experimentos.py` sobre la Gold real. La estabilidad se
midio con Adjusted Rand Index (ARI) frente a la asignacion de la semilla 42,
usando las semillas `0, 1, 2, 3, 4 y 42`.

Los ARI medios aproximados fueron:

```text
k=2  -> 0.997
k=3  -> 0.990
k=4  -> 0.976
k=5  -> 0.671
k=6  -> 0.990
k=7  -> 0.891
k=8  -> 0.869
k=9  -> 0.786
```

`k=4` es razonablemente estable, aunque no es la solucion mas estable. `k=5`
presenta una inestabilidad clara y `k=9` deja de ser elegible con algunas
semillas porque algun cluster baja de 30 municipios.

Con `k=4`, los perfiles medianos fueron:

| Cluster | Municipios | Poblacion 18-50 | Crecimiento | Renta | Competencia por 10.000 |
|---|---:|---:|---:|---:|---:|
| 0 | 95 | 573 | 8,96 % | 11.674 | 0,87 |
| 1 | 360 | 1.437 | -0,53 % | 11.399 | 1,75 |
| 2 | 125 | 9.461 | 3,06 % | 13.167 | 1,52 |
| 3 | 205 | 229 | -2,85 % | 12.749 | 3,12 |

En el escenario central, todas las soluciones elegibles `k=2..9` produjeron
los mismos agregados de negocio para la seleccion del modelo:

```text
Baseline: 2.649.735 EUR de facturacion, -130.265 EUR de margen, 3 viables
Modelo:   3.489.720 EUR de facturacion,  709.720 EUR de margen, 5 viables
```

Esto indica que, con los supuestos actuales, el ranking final es poco sensible
a la eleccion de `k` entre las soluciones elegibles. No demuestra que todos los
municipios de las listas sean iguales; deben revisarse las listas concretas y
los cambios frente al baseline.

En la sensibilidad de 162 escenarios, los municipios con mas apariciones fueron
Marbella (97), Alcala de Guadaira (93), El Puerto de Santa Maria (88),
Fuengirola (71) y Algeciras (42). La frecuencia es una medida de robustez bajo
los supuestos probados, no una validacion historica de rentabilidad.

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
