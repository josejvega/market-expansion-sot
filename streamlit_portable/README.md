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

Si existe `data/resultados/clusters.csv` localmente, incorpora los clusters por
código municipal. Si no existe, entrena el modelo K-means del repositorio con
la Gold recién cargada (incluida Gold leída desde S3). Así se calculan las
candidatas reales del modelo y su ranking de negocio; no se sustituye por el
top 5 de facturación general. El entrenamiento es determinista y usa las
mismas reglas que `python -m src.modelo.modelo`.

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

Para guardar o revisar las asignaciones de clusters por separado:

```powershell
python -m src.modelo.modelo
```

También puede indicarse otra ubicación para Gold y clusters locales con
`GYM_GOLD_PATH` y `GYM_CLUSTERS_PATH`. Si no hay CSV local, la app genera los
clusters desde la Gold que está usando. Gold y los límites Silver sí son
necesarios para cargar el estudio y su mapa.

La carpeta `data/` está excluida de Git. En EC2, adjunta a la instancia un rol
IAM con permiso `s3:GetObject` sobre los objetos Gold y Silver:
`arn:aws:s3:::<S3_BUCKET>/gold/tabla_oro_municipios_andalucia.parquet` y
`arn:aws:s3:::<S3_BUCKET>/processed/silver/limites_municipales_andalucia.parquet`.
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
