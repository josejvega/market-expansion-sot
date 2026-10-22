# Plan de experimentos del modelo

## Objetivo

Evaluar la calidad tecnica del clustering y justificar la seleccion de `k` sin
usar facturacion, viabilidad ni ninguna otra metrica de negocio. El notebook
`03_modelo.ipynb` permanece como flujo base del modelo. Los experimentos se
ejecutan con `src/modelo/experimentos.py` y sus resultados se visualizan en un
notebook paralelo.

## Preguntas que queremos responder

1. Que valor de `k` produce clusters mas cohesionados y separados?
2. Que valor de `k` ofrece un equilibrio razonable entre calidad y complejidad?
3. La particion se mantiene al cambiar la semilla aleatoria?
4. Hay clusters demasiado pequenos o muy desequilibrados?
5. Los clusters tienen perfiles estadisticamente interpretables?
6. La decision cambia si modificamos el minimo de municipios por cluster?

## Alcance tecnico

Las variables del modelo son:

- `log1p(population_18_50)`;
- `population_growth_pct`;
- `mean_net_income_per_person`.

Se mantiene `StandardScaler`, `random_state=42` y `n_init=20`. La renta
faltante se imputa con la mediana observada. No se utilizan variables de
competencia para entrenar el clustering.

## Experimentos

### A. Calidad interna por `k`

Evaluar el rango dinamico de `k` permitido por el numero de municipios y el
tamano minimo configurado. Para cada `k` guardar:

- inertia;
- silhouette;
- tamano minimo y maximo de cluster;
- elegibilidad;
- indicador de seleccion por silhouette.

Visualizaciones:

- silhouette frente a `k`;
- inertia frente a `k`;
- tamano minimo frente a `k`, con la restriccion minima dibujada.

### B. Estabilidad de la particion

Repetir cada `k` elegible con las semillas `0, 1, 2, 3, 4 y 42`. Comparar
cada particion con la referencia mediante Adjusted Rand Index (ARI).

Guardar y visualizar:

- ARI medio por `k`;
- desviacion estandar del ARI;
- minimo y maximo ARI;
- numero de semillas elegibles.

Una solucion con silhouette alta pero ARI muy variable requiere cautela.

### C. Equilibrio de los clusters

Para `k=3`, `k=4` y `k=5`, o para las soluciones seleccionadas, representar la
distribucion de tamanos de cluster. El objetivo es identificar particiones con
grupos residuales o excesivamente dominantes.

### D. Interpretabilidad de los perfiles

Para cada cluster seleccionado calcular medianas de:

- poblacion de 18 a 50 anos;
- crecimiento poblacional;
- renta media por persona.

Visualizar los perfiles mediante un heatmap de valores normalizados. La
interpretacion debe describir diferencias observadas, sin atribuir causalidad.

### E. Separacion visual mediante PCA

Proyectar las variables escaladas en dos componentes principales y colorear
los municipios por cluster para comparar `k=3`, `k=4` y `k=5`.

La PCA es una ayuda visual y no una metrica adicional de seleccion: puede
ocultar separacion existente en dimensiones no representadas.

### F. Sensibilidad del tamano minimo

El minimo de 30 municipios por cluster es un supuesto de interpretabilidad,
no un requisito del challenge. Repetir el analisis con minimos de `20`, `30`,
`40` y `50`.

Para cada escenario registrar:

- rango de `k` evaluado;
- valores de `k` elegibles;
- `k` seleccionado por silhouette;
- silhouette de la seleccion;
- ARI medio de la seleccion;
- tamano minimo real.

El resultado se considera robusto si `k=4` sigue siendo elegible y razonable,
los perfiles no cambian radicalmente y la estabilidad se mantiene.

## Reparto entre tres personas

Cada persona trabaja con un identificador y un directorio de salida distinto
para evitar colisiones:

| Persona | Bloque | Salida principal |
|---|---|---|
| Persona 1 | Calidad interna por `k` | `evaluacion_k.csv` y graficas de silhouette/inertia |
| Persona 2 | Estabilidad y tamano de clusters | `estabilidad_k.csv` y distribuciones de tamanos |
| Persona 3 | Perfiles, PCA y sensibilidad del minimo | perfiles, coordenadas PCA y tabla de sensibilidad |

Los CSV deben incluir el identificador del experimento, la configuracion
utilizada y el tiempo de ejecucion. Ninguna persona modifica
`03_modelo.ipynb` ni `src/modelo/modelo.py` para realizar estas comparaciones.

## Criterio de decision tecnica

No se selecciona `k` por una unica grafica. La decision debe considerar, en
este orden:

1. soluciones elegibles por tamano real;
2. silhouette e inertia;
3. estabilidad entre semillas;
4. equilibrio de tamanos;
5. interpretabilidad de perfiles;
6. sensibilidad al minimo de cluster.

El resultado se documentara como una seleccion tecnica provisional. La
comparacion con baseline, facturacion, viabilidad y municipios candidatos queda
fuera de este plan y se realiza en la capa de negocio.

## Artefactos esperados

Los resultados regenerables se guardan bajo
`data/resultados/experimento_k/` o en subdirectorios identificados por cada
experimento. La documentacion versionable y las conclusiones se guardan en
`docs/` y `src/modelo/`.

Los notebooks de analisis que se decidan deben cargar los CSV ya generados,
consolidar los resultados y producir el analisis y las visualizaciones. No
deben contener una segunda implementacion del algoritmo K-means. Este fichero
documenta el plan; los resultados y las graficas viven en los notebooks de
analisis.

## Responsabilidades de los componentes

`src/modelo/experimentos.py` es el motor reproducible de los experimentos
tecnicos. Genera:

- `evaluacion_k.csv`;
- `estabilidad_k.csv`;
- `perfiles_seleccion.csv`.

Los notebooks leen estos CSV para producir las graficas. La comparacion frente al baseline, la
facturacion, la viabilidad y la sensibilidad de municipios pertenecen a
`src/negocio` y no forman parte de este experimento tecnico.

Los notebooks de analisis deben incluir, como minimo:

- silhouette por `k`;
- inertia por `k`;
- tamano minimo y elegibilidad;
- ARI medio con su variabilidad;
- distribucion de tamanos;
- proyeccion PCA;
- heatmap de perfiles.

La PCA es una ayuda visual y no sustituye a silhouette, estabilidad ni perfiles
al justificar la seleccion.