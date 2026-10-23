# Streamlit · interfaz portable2 con datos del repositorio

La app usa la interfaz de `streamlit_portable2` (`web/streamlit.html`, CSS y
JavaScript) y lee la tabla procesada
`gold/tabla_oro_municipios_andalucia.parquet` del bucket configurado con
`S3_BUCKET` en el `.env` de la raíz del repo. También lee los polígonos
municipales Silver desde
`processed/silver/limites_municipales_andalucia.parquet` para calcular un punto
interior de cada municipio y situarlo en el mapa. `S3_BUCKET` define el origen
de los datos; no proporciona credenciales. Si está configurado, Gold y Silver
se leen de S3 y la app falla con un error claro si no hay acceso, sin usar una
copia local que pueda estar desactualizada. Si `S3_BUCKET` no está configurado,
se leen las copias locales. No hace falta crear ni mantener un JSON intermedio.

La app no entrena modelos ni requiere scikit-learn. Lee dos artefactos del
modelo: `results/municipios_candidatos.parquet` contiene solo los municipios
candidatos y `results/municipios_clusters.parquet` contiene las asignaciones
de todos los municipios que pudieron entrar en el clustering. Los municipios
sin variables completas para entrenar se muestran como "Fuera del clustering";
si falta el segundo artefacto, se avisa de que la asignación aún no está
publicada. En S3 las claves por defecto son esas rutas bajo `results/`. En modo
local, los archivos por defecto están en `data/results/`. Si falta cualquiera
de los artefactos, el dashboard muestra lo disponible y avisa; no inventa
candidatos ni clusters. Los errores de permisos u otros fallos de S3 siguen
mostrándose como errores. `GYM_CANDIDATES_S3_KEY` puede cambiar la clave de
candidatos o desactivar su lectura si queda vacío. El modelo se ejecuta fuera
de Streamlit.

La sección "Oferta registrada en cada grupo" solo muestra medias cuando está
disponible la asignación completa de clusters; el archivo de candidatos por sí
solo no basta para calcular medias representativas. La tasa mostrada es la
media municipal de gimnasios más otras instalaciones deportivas registradas
por cada 10.000 residentes de 18–50 años, contando cada instalación igual.
Los números de cluster son etiquetas sin orden y la tasa no demuestra que un
municipio esté libre de competencia.

La capa Silver
`processed/silver/gyms_with_municipality_andalusia.parquet` aporta los puntos
OSM de instalaciones del mapa. En modo local la ruta se toma de la
configuración de rutas del repositorio; si no existe, el mapa no muestra esos
puntos. Los puntos OSM no equivalen a una auditoría de mercado.

## Preparar los datos y ejecutar

Desde la raíz del repositorio:

```powershell
python -m pip install -r streamlit_portable/requirements.txt
python -m streamlit run streamlit_portable/streamlit_app.py
```

En un equipo local, autentícate con AWS IAM Identity Center antes de arrancar
la app:

```powershell
aws sso login --profile <perfil>
$env:AWS_PROFILE = "<perfil>"
python -m streamlit run streamlit_portable/streamlit_app.py
```

En EC2 no guardes claves AWS en `.env`: asocia a la instancia un IAM role
(instance profile). boto3 obtendrá credenciales temporales de ese rol.

Para generar y publicar los artefactos del modelo, ejecuta
`notebooks/03_modelo.ipynb` interactivamente después de generar Gold. Revisa
los gráficos de inercia y silhouette, elige `N_CLUSTERS` y ejecuta desde la
celda de entrenamiento hasta la última. Con `SAVE_S3=true`, esa última celda
sube ambos Parquet a `results/` en el bucket configurado. El módulo
`src.modelo.modelo` contiene funciones de entrenamiento y persistencia, pero
no se ejecuta como comando independiente.

También puede indicarse otra ubicación para Gold y candidatos locales con
`GYM_GOLD_PATH` y `GYM_CANDIDATES_PATH`. Para usar las recomendaciones del
modelo en S3, publica el Parquet del modelo en `results/municipios_candidatos.parquet`
o configura `GYM_CANDIDATES_S3_KEY` con su clave. Gold, los límites Silver y
los gimnasios geolocalizados Silver deben estar publicados para la carga S3.

La carpeta `data/` está excluida de Git. En EC2, adjunta a la instancia un rol
IAM con permiso `s3:GetObject` sobre los objetos Gold, Silver y el modelo:
`arn:aws:s3:::<S3_BUCKET>/gold/tabla_oro_municipios_andalucia.parquet` y
`arn:aws:s3:::<S3_BUCKET>/processed/silver/limites_municipales_andalucia.parquet`,
`arn:aws:s3:::<S3_BUCKET>/processed/silver/gyms_with_municipality_andalusia.parquet`
y `arn:aws:s3:::<S3_BUCKET>/results/municipios_candidatos.parquet` y
`arn:aws:s3:::<S3_BUCKET>/results/municipios_clusters.parquet`.
Configura `S3_BUCKET` y `AWS_DEFAULT_REGION` en el `.env`. boto3 obtendrá las
credenciales temporales del rol automáticamente: no copies claves AWS a la
instancia ni al repositorio. Arranca Streamlit en la interfaz de red de la
instancia con:

```bash
python -m streamlit run streamlit_portable/streamlit_app.py \
  --server.address 0.0.0.0
```

Limita el acceso entrante con el security group o un proxy HTTPS. Publicar un
JSON tiene sentido solo si se necesita una API o una frontera de despliegue
entre sistemas; en ese caso conviene generarlo como artefacto a partir de Gold,
no como copia mantenida a mano.

La app usa los mismos cálculos y supuestos de `src/negocio/valor_negocio.py`.
La interfaz portable2 incluye campos que Gold no tiene. Las coordenadas se
calculan a partir de los polígonos municipales Silver; el punto representativo
solo localiza el municipio, no una ubicación de gimnasio. Gold no incluye un
score de recomendación: la columna se muestra como no disponible, en vez de
inventar una puntuación. Los datos turísticos, secciones censales, auditorías
e intervalos de ingresos tampoco están disponibles. La facturación y
viabilidad son escenarios, no ventas observadas ni predicciones. Los recuentos
de competencia proceden de OpenStreetMap y no permiten concluir que un
municipio carezca realmente de competidores.
