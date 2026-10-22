# Streamlit portable

Aplicacion independiente de Streamlit. No incluye datos de ejemplo ni scripts
del pipeline. Descarga el JSON de estudio desde `GYM_STUDY_URL` en el servidor
que ejecuta Streamlit y valida su estructura antes de mostrarlo.

La URL debe ser HTTPS y servir el JSON version 1 descrito en
[`STREAMLIT_DATA.md`](../STREAMLIT_DATA.md). Al ser una descarga servidor a
servidor, el endpoint no necesita habilitar CORS para el navegador.

## Ejecutar

Desde esta carpeta, instala dependencias y configura la URL:

```powershell
python -m pip install -r requirements.txt
$env:GYM_STUDY_URL = "https://tu-dominio.example/study.json"
python -m streamlit run streamlit_app.py
```

En Linux o macOS:

```sh
python -m pip install -r requirements.txt
GYM_STUDY_URL="https://tu-dominio.example/study.json" python -m streamlit run streamlit_app.py
```

El endpoint debe ser accesible desde el equipo o contenedor de Streamlit.
Si requiere autenticacion, configura el acceso en el despliegue; no pongas
tokens en el codigo ni en la URL.