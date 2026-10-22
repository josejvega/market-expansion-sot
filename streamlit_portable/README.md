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

La app no entrena modelos ni requiere scikit-learn. Lee el artefacto de
candidatos que produce el modelo, `results/municipios_candidatos.parquet`,
con las columnas `municipality_code` y `cluster`. Este archivo solo contiene
municipios candidatos, no la asignación de cluster completa. Los municipios
que no aparecen se muestran con la asignación como no publicada. En S3 la clave
por defecto es `results/municipios_candidatos.parquet`; puede cambiarse con
`GYM_CANDIDATES_S3_KEY`. En modo local, el archivo por defecto es
`data/results/municipios_candidatos.parquet` y puede cambiarse con
`GYM_CANDIDATES_PATH`. Si el artefacto no existe en S3, la app informa del
error en vez de simular candidatos. Para mostrar el estudio sin candidatos,
deja `GYM_CANDIDATES_S3_KEY` vacío. El modelo se ejecuta fuera de Streamlit.

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

Para guardar o revisar las asignaciones de clusters por separado:

```powershell
python -m src.modelo.modelo
```

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
y `arn:aws:s3:::<S3_BUCKET>/results/municipios_candidatos.parquet`.
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
