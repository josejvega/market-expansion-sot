# Proyecto 5: Market Expansion para gimnasios

## Objetivo

Identificar los mejores municipios de Andalucía para abrir un gimnasio usando:

- crecimiento de la población;
- población entre 18 y 50 años;
- número actual de gimnasios;
- renta media como indicador complementario de capacidad de pago.

La unidad final de análisis será el **municipio**. Por eso todas las fuentes deben terminar relacionadas mediante un código municipal común.

## 1. Qué aporta cada tabla

### `gyms_andalusia.csv`

Esta tabla procede de OpenStreetMap y contiene gimnasios o instalaciones deportivas detectadas en Andalucía.

#### Columnas importantes

| Columna | Uso |
|---|---|
| `osm_type` | Tipo de objeto OSM: `node`, `way` o `relation`. Se conserva para trazabilidad. |
| `osm_id` | Identificador único del objeto en OpenStreetMap. Sirve para detectar duplicados. |
| `province_code` | Código de provincia, por ejemplo `ES-AL`. |
| `province` | Nombre de la provincia. |
| `latitude` | Latitud del objeto. |
| `longitude` | Longitud del objeto. |
| `tag_name` | Nombre de la instalación. |
| `tag_leisure`, `tag_sport`, `tag_amenity` | Tipo de actividad o instalación. Sirven para filtrar gimnasios reales. |
| `tag_brand` | Marca comercial, si está informada. |
| `tag_operator` | Empresa, entidad o persona que opera la instalación, si está informada. |
| `tag_addr:postcode`, `tag_addr:street`, `tag_addr:city` | Campos Bronze de dirección; se omiten de Silver porque solo aparecen en aproximadamente el 11-14 % de las filas. |
| `source`, `downloaded_at_utc` | Trazabilidad de la fuente y fecha de descarga. |
| `tag_*` | Atributos adicionales de OpenStreetMap. Muchos estarán vacíos. |

La tabla Silver de gimnasios conserva los identificadores OSM, la provincia, las coordenadas, la trazabilidad y las etiquetas `name`, `leisure`, `sport` y `amenity`. Añade `geometry` como punto EPSG:4326. Por ahora no incluye `municipality_code`: el CSV de gimnasios no contiene un código municipal fiable y este flujo no incorpora otras fuentes.

#### Por qué conservar `osm_type`

En OpenStreetMap un elemento puede representarse de tres formas:

- `node`: un punto con coordenadas. Es la representación habitual de un gimnasio sencillo.
- `way`: una línea cerrada o conjunto de puntos que puede representar un edificio o recinto.
- `relation`: una agrupación de elementos, por ejemplo una instalación compleja.

`osm_type` junto con `osm_id` identifica el objeto original. No identifica el municipio y no es necesario para calcular el ranking, pero permite volver a la fuente, eliminar duplicados y auditar los datos.

#### Valor de `tag_brand` y `tag_operator`

Tienen valor secundario:

- `tag_brand` permite distinguir cadenas nacionales, franquicias y gimnasios independientes.
- `tag_operator` puede ayudar a estudiar competencia directa o concentración empresarial.

No son imprescindibles para calcular la oportunidad de mercado porque suelen tener muchos valores nulos y no siempre describen correctamente el negocio. Para el análisis principal se usarían de forma opcional.

### `population_andalusia.csv`

#### Encabezado real

```text
Downloaded_at_utc,Edad,Municipios,Periodo,Provincias,Sexo,source,Total
```

> El nombre exacto observado en el archivo es `downloaded_at_utc`, en minúsculas. El resto de columnas aparece como `Edad`, `Municipios`, `Periodo`, `Provincias`, `Sexo`, `source` y `Total`.

#### Columnas a usar

| Columna | Uso |
|---|---|
| `Municipios` | Identificador y nombre. Ejemplo: `04001 Abla`. |
| `Periodo` | Año del dato. |
| `Edad` | Permite seleccionar `Todas las edades` o el intervalo de 18 a 50 años. |
| `Sexo` | Permite sumar hombres y mujeres para obtener población total. |
| `Total` | Número de personas. |
| `Provincias` | Control y descripción territorial. |

El código municipal se obtiene de los cinco primeros caracteres de `Municipios`:

```text
Municipios = 04001 Abla
Código municipal = 04001
Nombre = Abla
```

### `income_andalusia.csv`

#### Encabezado real

```text
Municipios,Distritos,Secciones,Indicadores de renta media,Periodo,Total,source,downloaded_at_utc
```

#### Columnas a usar

| Columna | Uso |
|---|---|
| `Municipios` | Código y nombre del municipio. |
| `Indicadores de renta media` | Identifica el indicador, por ejemplo renta neta media por persona. |
| `Periodo` | Año del dato. |
| `Total` | Valor de la renta. Hay que confirmar la unidad y el separador decimal. |
| `Distritos`, `Secciones` | Solo son necesarias para análisis inframunicipal. |
| `source`, `downloaded_at_utc` | Trazabilidad. |

La renta no es una medida directa de demanda. Se utilizará como variable complementaria para diferenciar un municipio con capacidad para pagar cuotas altas de otro donde sería más adecuado un modelo de bajo coste.

### `municipality_boundaries_andalusia.csv`

Esta tabla procede del CNIG/IGN y contiene los límites oficiales de los municipios.

#### Encabezado real

```text
nationalCode,inspireId,nationalLevel,nationalLevelName,country,name,residenceOfAuthority,beginLifespanVersion,endLifespanVersion,condominium,upperLevelUnit,administeredBy,coAdminister,boundary,geometry,source,downloaded_at_utc
```

> El encabezado real utiliza `coAdminister`. Se debe conservar el nombre que figure en el archivo.

#### Columnas a usar

| Columna | Uso |
|---|---|
| `nationalCode` | Identificador oficial CNIG del municipio. |
| `name` | Nombre del municipio dentro de un JSON. |
| `geometry` | Polígono o multipolígono municipal en GeoJSON. |
| `source` | Fuente, normalmente IGN/CNIG BDDAE. |
| `downloaded_at_utc` | Fecha de descarga. |

El resto de columnas administrativas no es necesario para el ranking, aunque puede conservarse por trazabilidad.

## 2. Cómo identificar el municipio

### Población e ingresos

En estas tablas el municipio ya aparece en `Municipios` con el formato:

```text
04001 Abla
```

Se deben crear dos campos:

| Campo | Valor de ejemplo |
|---|---|
| `municipality_code` | `04001` |
| `municipality_name` | `Abla` |

El código es preferible al nombre porque evita problemas con tildes, mayúsculas, espacios y nombres repetidos.

### CNIG

El `nationalCode` del CNIG es más largo. Por ejemplo:

```text
34010404001
```

En los datos de Andalucía, los cinco últimos dígitos corresponden al código municipal INE:

```text
nationalCode       = 34010404001
municipality_code  = 04001
```

Se debe comprobar esta regla en todos los registros antes de utilizarla. Es recomendable conservar ambos campos:

- `cnig_national_code`;
- `municipality_code`.

### Gimnasios

El CSV de gimnasios no incluye un código municipal fiable. La provincia sí aparece, pero `tag_addr:city` solo está informado en una parte pequeña de las filas y es texto libre. Por ahora la tabla Silver no añade `municipality_code` ni cruza con fuentes externas. Si más adelante se autoriza una fuente municipal de referencia, las coordenadas y sus geometrías podrían utilizarse para asignarlo espacialmente.

## 3. Qué significa convertir un gimnasio en un punto geográfico

Un gimnasio de la tabla tiene dos números:

```text
latitude  = 37.1720276
longitude = -1.8339941
```

Estos valores representan su posición en la Tierra. Convertirlo en un punto geográfico significa crear un objeto espacial:

```python
Point(longitude, latitude)
```

El orden correcto para crear el punto es **longitud, latitud**, aunque las columnas estén almacenadas como `latitude`, `longitude`.

Los puntos deben declararse inicialmente con el sistema de coordenadas WGS84:

```text
EPSG:4326
```

## 4. Cómo usar la información GeoJSON del CNIG

En el CSV, `geometry` no es todavía un polígono utilizable por GeoPandas: está guardado como texto JSON. Su contenido tiene esta estructura simplificada:

```json
{
  "type": "MultiPolygon",
  "coordinates": [ ... ]
}
```

El proceso conceptual es:

1. Leer el texto de la columna `geometry`.
2. Interpretarlo como JSON.
3. Convertirlo en una geometría de Shapely.
4. Crear una GeoDataFrame con esa geometría.
5. Asignarle el CRS `EPSG:4326`.

Ejemplo:

```python
import json
import geopandas as gpd
from shapely.geometry import shape

cnig["geometry"] = cnig["geometry"].apply(
    lambda value: shape(json.loads(value))
)

municipios = gpd.GeoDataFrame(
    cnig,
    geometry="geometry",
    crs="EPSG:4326"
)
```

La geometría es el límite espacial que permite saber qué territorio pertenece a cada municipio. No se utiliza para unir por texto, sino para hacer una relación espacial.

## 5. Cómo hacer la unión espacial punto-en-polígono

Una unión espacial punto-en-polígono responde a esta pregunta:

> ¿Dentro de qué polígono municipal se encuentra el punto del gimnasio?

### Paso 1: crear los puntos de gimnasios

```python
from shapely.geometry import Point
import geopandas as gpd

puntos = gpd.GeoDataFrame(
    gyms,
    geometry=[
        Point(longitude, latitude)
        for longitude, latitude in zip(
            gyms["longitude"], gyms["latitude"]
        )
    ],
    crs="EPSG:4326"
)
```

### Paso 2: preparar los municipios

```python
municipios["municipality_code"] = (
    municipios["nationalCode"].str[-5:]
)
```

La extracción de los cinco últimos dígitos debe validarse comparándola con municipios conocidos del INE.

### Paso 3: unir puntos y polígonos

```python
resultado = gpd.sjoin(
    puntos,
    municipios[[
        "nationalCode",
        "municipality_code",
        "name",
        "geometry"
    ]],
    how="left",
    predicate="within"
)
```

`predicate="within"` significa que cada punto se asigna al polígono que lo contiene.

Después de esta operación, cada gimnasio tendrá su municipio:

```text
osm_id | latitude | longitude | municipality_code | municipality_name
```

### Comprobaciones posteriores

- Gimnasios con `municipality_code` vacío: están fuera de los polígonos o tienen coordenadas incorrectas.
- Puntos con coordenadas nulas: no pueden asignarse espacialmente.
- Puntos en el límite municipal: revisar el resultado.
- Gimnasios duplicados: comprobar `osm_type` y `osm_id`.
- Gimnasios cuyo `province_code` no coincide con el municipio asignado: revisar coordenadas.

## 6. Cómo unir INE, OSM y CNIG

El flujo recomendado es:

```text
OSM gimnasios
    latitude + longitude
            |
            v
CNIG geometrías municipales
    municipality_code
            |
            v
INE población e ingresos
    municipality_code
```

En términos de tablas:

1. `gyms_andalusia.csv` se cruza espacialmente con `municipality_boundaries_andalusia.csv`.
2. El CNIG asigna `municipality_code` a cada gimnasio.
3. Se cuentan los gimnasios por `municipality_code`.
4. Ese conteo se une con población e ingresos mediante `municipality_code`.
5. El resultado final tiene una fila por municipio.

La unión de población e ingresos sería conceptualemente:

```python
resultado_final = poblacion_resumida.merge(
    renta_resumida,
    on="municipality_code",
    how="left"
).merge(
    gimnasios_por_municipio,
    on="municipality_code",
    how="left"
)
```

Los municipios sin gimnasios deben conservarse y recibir `gym_count = 0`, porque pueden ser precisamente oportunidades de expansión.

## 7. Cómo calcular el crecimiento de población

Primero hay que agregar la población por municipio, año y grupo de edad. Para población total se deben sumar hombres y mujeres, evitando duplicar registros.

### Crecimiento absoluto

Si se comparan 2023 y 2025:

```text
population_growth_abs = population_2025 - population_2023
```

### Crecimiento porcentual

```text
population_growth_pct =
    ((population_2025 - population_2023) / population_2023) * 100
```

Ejemplo:

```text
Población 2023 = 10.000
Población 2025 = 10.500
Crecimiento absoluto = 500
Crecimiento porcentual = 5 %
```

Si se dispone de más años, es mejor calcular una variación entre el primer y el último año disponibles. También se puede calcular el crecimiento anual compuesto:

```text
CAGR = (population_final / population_inicial) ** (1 / numero_de_años) - 1
```

### Crecimiento de la población de 18 a 50 años

El mismo cálculo debe realizarse específicamente para el grupo de edad objetivo:

```text
population_18_50_growth_pct =
    ((population_18_50_final - population_18_50_initial)
     / population_18_50_initial) * 100
```

Hay que controlar el caso de municipios con población inicial igual a cero para evitar divisiones por cero.

## 8. Cómo reflejar el crecimiento en las tablas

### Tabla intermedia de población

```text
municipality_code | municipality_name | period | age_group | sex | population
04001             | Abla              | 2023   | 18-50      | Total | 1200
04001             | Abla              | 2025   | 18-50      | Total | 1260
```

### Tabla de indicadores de población

```text
municipality_code | municipality_name | population_2023 | population_2025 | growth_abs | growth_pct | population_18_50 | growth_18_50_pct
04001             | Abla              | 4300            | 4380            | 80         | 1.86      | 1260             | 2.44
```

### Tabla final de market expansion

```text
municipality_code | municipality_name | province | population_total | population_18_50 | growth_pct | growth_18_50_pct | income_per_person | gym_count | gyms_per_10k_18_50 | opportunity_score
04001             | Abla              | Almería | 4380             | 1260             | 1.86       | 2.44             | 12411             | 0         | 0.00               | 72.4
```

## 9. Indicadores para decidir dónde abrir

### Gimnasios por cada 10.000 personas de 18 a 50 años

```text
gyms_per_10k_18_50 =
    (gym_count / population_18_50) * 10000
```

Un valor bajo puede indicar menor competencia, pero debe interpretarse junto con el tamaño y el crecimiento del municipio. Un municipio pequeño sin gimnasios no necesariamente tiene suficiente demanda.

### Índice de oportunidad

Se pueden normalizar los indicadores y combinar, por ejemplo:

```text
opportunity_score =
    0.35 * population_18_50_score
  + 0.30 * population_growth_score
  + 0.20 * low_competition_score
  + 0.15 * income_score
```

Donde `low_competition_score` debe ser mayor cuando hay menos gimnasios por cada 10.000 personas de 18 a 50 años.

Los pesos son una decisión de negocio y deben justificarse. El resultado debe interpretarse como una priorización de municipios, no como una garantía de rentabilidad.

## 10. Encabezado de la tabla final

```text
municipality_code,municipality_name,province,population_total,population_18_50,population_initial,population_final,population_growth_abs,population_growth_pct,population_18_50_initial,population_18_50_final,population_18_50_growth_pct,income_per_person,gym_count,gyms_per_10k_population,gyms_per_10k_18_50,opportunity_score
```

Esta es la tabla que se utilizaría para ordenar los municipios y presentar los candidatos prioritarios para la expansión.
