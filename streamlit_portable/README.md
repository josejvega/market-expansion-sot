# Streamlit · interfaz portable2 con datos del repositorio

La app usa la interfaz de `streamlit_portable2` (`web/streamlit.html`, CSS y
JavaScript) y lee la tabla procesada
`gold/tabla_oro_municipios_andalucia.parquet` del bucket configurado con
`S3_BUCKET` en el `.env` de la raíz del repo. También lee los polígonos
municipales Silver desde
`processed/silver/limites_municipales_andalucia.parquet` para calcular un punto
interior de cada municipio y situarlo en el mapa. Usa el proveedor estándar de
credenciales de AWS (por ejemplo, un perfil local o un rol de instancia); no
guardes claves en el código. Si S3 no está disponible, intenta las copias
locales de Gold y Silver, respectivamente. No hace falta crear ni mantener un
JSON intermedio.

Si existe `data/resultados/clusters.csv` localmente, incorpora los clusters por
código municipal. El módulo del modelo actual no los publica a S3. Sin ese
archivo, la interfaz conserva su diseño y muestra el ranking viable de negocio
y el baseline, sin fingir una selección de clusters.

## Preparar los datos y ejecutar

Desde la raíz del repositorio:

```powershell
python -m pip install -r streamlit_portable/requirements.txt
python -m streamlit run streamlit_portable/streamlit_app.py
```

Para incluir selección por clusters, ejecuta antes:

```powershell
python -m src.modelo.modelo
```

También puede indicarse otra ubicación para Gold y clusters con
`GYM_GOLD_PATH` y `GYM_CLUSTERS_PATH`. El CSV de clusters es opcional; Gold y
los límites Silver son necesarios para cargar la app con su mapa.

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
solo localiza el municipio, no una ubicación de gimnasio. Los datos turísticos,
secciones censales, auditorías e intervalos de ingresos siguen sin estar
disponibles. La facturación y viabilidad son escenarios, no ventas observadas
ni predicciones. Los recuentos de competencia proceden de OpenStreetMap y no
permiten concluir que un municipio carezca realmente de competidores.
