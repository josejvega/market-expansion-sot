# Valor de negocio y seleccion de municipios

## Proposito

El modulo `src/negocio` transforma la tabla Gold y los clusters del modelo en una priorizacion de municipios para estudiar la apertura de un gimnasio low-cost.

No es un modelo supervisado ni una prediccion validada de ventas. Es una evaluacion basada en supuestos: combina demanda potencial, competencia observada, facturacion estimada y un umbral de viabilidad. Su resultado debe interpretarse como una priorizacion para decision, no como una garantia de rentabilidad.

## Entradas

La entrada principal es:

```text
data/processed/gold/tabla_oro_municipios_andalucia.parquet
```

Debe contener, como minimo:

- `municipality_code`
- `municipality_name`
- `population_18_50`
- `gyms_count`
- `other_sports_facilities_count`

Para aplicar la seleccion del modelo tambien se necesita:

```text
data/resultados/clusters.csv
```

Ese fichero contiene `municipality_code` y `cluster`, y debe cubrir exactamente los 785 municipios de la Gold.

## Por que la competencia se usa en negocio

`gyms_count`, `other_sports_facilities_count` y la densidad de competencia describen la presion competitiva de cada municipio. Por eso son variables directamente relacionadas con la oportunidad de abrir un centro.

La decision actual es no usarlas como entradas del K-means principal. El clustering agrupa municipios por demanda y contexto socioeconomico:

- poblacion de 18 a 50 anos;
- crecimiento de poblacion;
- renta neta media por persona.

Despues, negocio compara la competencia dentro de cada grupo. Esta separacion permite responder dos preguntas distintas:

1. Que municipios se parecen entre si por demanda y capacidad economica?
2. Dentro de municipios comparables, cuales tienen menor presion competitiva?

Si la competencia entra en el clustering y vuelve a utilizarse para seleccionar candidatos, se corre el riesgo de mezclar la definicion de los grupos con la variable que se quiere evaluar. Tambien puede ocultar si el modelo encuentra grupos de demanda o simplemente grupos con muchos y pocos gimnasios.

No obstante, puede probarse como analisis alternativo. En ese caso conviene comparar dos modelos:

- **Modelo A, principal:** clustering con demanda, crecimiento y renta; competencia solo en negocio.
- **Modelo B, sensibilidad:** clustering que anade una densidad competitiva transformada y estandarizada.

La comparacion debe hacerse con silhouette, estabilidad de clusters y metricas de negocio. El Modelo B no debe sustituir al principal sin demostrar que mejora la decision y sigue siendo interpretable.

## Competencia ponderada

La Gold distingue dos grupos:

- `gyms_count`: gimnasios;
- `other_sports_facilities_count`: otras instalaciones deportivas.

El escenario central aplica:

```text
competidores_pond = gyms_count * 1.0
                  + other_sports_facilities_count * 0.1
```

Tambien existen estos escenarios:

- `solo_gimnasios`: solo cuenta `gyms_count`;
- `central`: gimnasios con peso 1 y otras instalaciones con peso 0.1;
- `todo_igual`: todos los recuentos historicos tienen peso 1.

Como Gold agrupa las instalaciones deportivas no-gimnasio, el codigo exige el mismo peso para `sports_centre` y `fitness_station`. No permite fingir una precision que los datos de entrada no tienen.

La funcion `competidores_ponderados` valida que los recuentos sean finitos, no negativos y numericos. Tambien mantiene compatibilidad con el esquema historico de tres columnas de competencia.

## Densidad competitiva

El codigo calcula despues de aplicar los pesos:

```text
comp_per_10k_18_50 = competidores_pond / population_18_50 * 10000
```

Esta es la medida que usa la regla de candidatos. La columna Gold `gyms_per_10k_18_50` es util para inspeccion y control de calidad, pero no sustituye a `comp_per_10k_18_50` porque no incluye necesariamente los pesos del escenario ni otras instalaciones.

Tambien se crea `flag_sin_competencia_osm` cuando la competencia ponderada es cero. Eso significa que OSM no ha aportado instalaciones computables; no demuestra que no exista competencia real.

## Regla de candidatos

Cuando hay clusters, `candidatos` calcula la media de `comp_per_10k_18_50` dentro de cada cluster. Un municipio es candidato si queda por debajo de esa media:

```text
candidate_flag = comp_per_10k_18_50 < media_competencia_del_cluster
```

Esta regla busca competencia relativamente baja dentro de municipios comparables. No selecciona automaticamente los cinco finales porque todavia deben pasar por la estimacion economica y la viabilidad.

Una limitacion importante es que la media puede verse afectada por valores extremos. Como analisis de sensibilidad seria razonable comparar la media con la mediana o con un percentil, manteniendo la regla central documentada.

## Demanda potencial

Con los supuestos del escenario se calcula:

```text
socios_potenciales = population_18_50 * penetracion
mercado_potencial_eur = socios_potenciales * ticket_mensual * 12
```

La medida auxiliar de demanda relativa es:

```text
demanda_por_comp = socios_potenciales / max(competidores_pond, 1)
```

El maximo evita una division por cero cuando OSM no registra competencia.

## Facturacion

El codigo ofrece dos reglas:

### Regla C

Estima la cuota capturable de un centro nuevo en funcion de su atractivo frente a la competencia:

```text
cuota_centro = min(
    atractivo_nuevo / (competidores_pond + atractivo_nuevo),
    cuota_max
)
```

Despues limita los socios por la capacidad del centro:

```text
socios_centro = min(socios_captables, capacidad)
facturacion_anual = socios_centro * ticket_mensual * 12
```

### Regla de demanda no cubierta

Estima la demanda libre despues de descontar los socios medios asociados a la competencia:

```text
libre = max(
    0,
    socios_potenciales - competidores_pond * socios_medios_comp
)
```

La demanda capturable queda limitada por `cuota_max` y por la capacidad del centro.

## Viabilidad

El umbral se expresa en euros y no depende del ticket:

```text
margen_eur = facturacion_anual - coste_anual_club
viable = margen_eur >= 0
```

Tambien se calculan:

- `socios_break_even`;
- `umbral_facturacion`;
- `perdidas_eur` para margenes negativos.

Los costes, penetracion, ticket, capacidad, cuota maxima y atractivo del nuevo centro son supuestos de escenario, no observaciones de la Gold.

## Baseline, modelo y comparacion

El baseline representa la regla sencilla de referencia: los cinco municipios con mayor `population_18_50`.

El modelo selecciona municipios que cumplen las dos condiciones:

1. `candidate_flag` es verdadero, es decir, competencia inferior a la media de su cluster;
2. `viable` es verdadero.

Entre ellos ordena por:

1. `facturacion_anual`;
2. `demanda_por_comp`;
3. `population_18_50`.

La funcion `comparar` resume para baseline y modelo:

- demanda media por competidor;
- facturacion total y media;
- numero de municipios viables;
- margen total;
- perdidas totales.

Tambien informa que municipios salen, entran o se mantienen en la seleccion.

La comparacion debe hacerse sobre el mismo universo de 785 municipios y con los mismos supuestos. No se debe afirmar que el modelo mejora solo porque cambie la lista.

## Sensibilidad

La funcion `sensibilidad` recorre una rejilla de escenarios combinando:

- penetracion baja, central y alta;
- cuota maxima baja, central y alta;
- atractivo del nuevo centro bajo, central y alto;
- escenarios de pesos de competencia;
- regla C y demanda no cubierta.

Para cada combinacion guarda la seleccion y calcula cuantas veces aparece cada municipio, su posicion media y el rango de facturacion. La frecuencia de aparicion sirve para distinguir recomendaciones robustas de resultados dependientes de un unico supuesto.

## Ejecucion

Despues de crear la Gold y ejecutar K-means:

```powershell
.\.venv\Scripts\python.exe -m src.negocio.ejecutar
```

El programa lee la Gold y `data/resultados/clusters.csv`, valida los codigos y la cobertura completa, y escribe en `data/outputs/`:

- `municipios_evaluados_<pesos>.csv`;
- `baseline_<pesos>.csv`;
- `top_facturacion_<pesos>.csv`;
- `seleccion_modelo_<pesos>.csv`;
- `comparacion_<pesos>.csv`;
- `sensibilidad_detalle.csv`;
- `sensibilidad_frecuencias.csv`.

Los resultados de negocio son salidas locales y no deben confundirse con datos observados de ventas.

## Tests y limitaciones

`tests/test_negocio.py` comprueba:

- pesos de competencia para Gold y esquema historico;
- validacion de valores invalidos;
- cobertura exacta de Gold y clusters;
- uso de la media del cluster y viabilidad;
- seleccion del baseline top-5 con desempate reproducible.

Limitaciones conocidas:

- OSM puede no cubrir todos los centros existentes.
- Gold no separa actualmente pabellones y estaciones al aire libre dentro de otras instalaciones.
- La facturacion es estimada mediante supuestos, no ventas historicas.
- El crecimiento usado por el modelo es actualmente crecimiento de poblacion total, aunque el negocio se centra en poblacion de 18 a 50 anos.
- La regla de candidato usa media del cluster y debe contrastarse con sensibilidad.
- El uso futuro de crecimiento especifico de 18 a 50 requerira actualizar Gold, modelo, documentacion y tests de forma conjunta.
