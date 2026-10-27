# Fuentes, atribuciones y licencias

## Datos y cartografía

| Titular y recurso | Uso | Licencia y atribución |
|---|---|---|
| Instituto Nacional de Estadística: [población, tabla 68542](https://www.ine.es/jaxiT3/Tabla.htm?t=68542) | Población municipal 2021–2025; público objetivo de 18–50 años | [Aviso legal del INE](https://www.ine.es/dyngs/AYU/index.htm?cid=125): CC BY 4.0 salvo indicación contraria. Elaboración propia con datos extraídos del sitio web del INE. |
| Instituto Nacional de Estadística: [renta, tabla 30824](https://www.ine.es/jaxiT3/Tabla.htm?t=30824) | Renta neta media por persona de 2024 | Mismas condiciones del INE; señalar transformaciones y conservar las fechas de actualización de la fuente. No implica respaldo del INE al análisis. |
| © OpenStreetMap contributors, mediante [Overpass](https://overpass-api.de/) | Localización y etiquetas de oferta deportiva | [ODbL 1.0 y requisitos de atribución](https://www.openstreetmap.org/copyright). Mantener el crédito y las obligaciones aplicables al distribuir bases derivadas. La licencia de los datos no garantiza su exhaustividad. |
| © Instituto Geográfico Nacional / CNIG: [WFS de unidades administrativas](https://www.ign.es/wfs-inspire/unidades-administrativas) | Límites BDDAE para cruces espaciales | [Licencia de uso IGN compatible con CC BY 4.0](https://www.ign.es/web/ign/portal/politica-datos). Elaboración propia de cruces y agregados. |
| © Instituto Geográfico Nacional: IGNBase | Cartografía de fondo del dashboard | Misma política de datos IGN, sujeta a las condiciones del servicio. Conservar la atribución visible del mapa. |

Los logs conservados en el notebook de ingesta registran descargas el 20/10/2026. Los CSV de negocio suministrados no incluyen `downloaded_at_utc`: no permiten demostrar por sí solos que procedan de esa misma extracción. Los periodos estadísticos anteriores se observan en los resultados, no deben confundirse con la descarga. En futuras ejecuciones deben conservarse los metadatos de origen.

## Referencias económicas

Los valores, niveles de escenario, criterios y fechas de consulta figuran en [supuestos.py](../src/negocio/supuestos.py). Las referencias se usan para construir escenarios, no se ingieren como datasets:

- [Encuesta de Hábitos Deportivos, Ministerio/CSD](https://www.educacionfpydeportes.gob.es/mc/deportedata/habitos/resultados.html): penetración. La población de referencia de la encuesta no coincide exactamente con el tramo 18–50 utilizado; su aplicación es un supuesto.
- [Basic-Fit, informes anuales](https://corporate.basic-fit.com/investors/annual-reports) y [revisión financiera FY2025](https://annualreport.basic-fit.com/2025/mbr/business-and-financial-review/): capacidad, ingresos y costes de referencia. No son costes presupuestados para cada municipio.
- [GestiónFit, operadores low-cost](https://www.gestionfit.com/industria/los-gigantes-del-fitness-low-cost-espanol): socios por centro y ratios de atractivo.
- [Deloitte / España Activa / FNEID, sector fitness](https://www.deloitte.com/es/es/services/consulting/perspectives/informe-sector-fitness-en-espana.html): referencias sectoriales.
- ESdiario (14/10/2026): tarifas citadas por el equipo; el registro de supuestos no aporta enlace directo al artículo. Su trazabilidad queda incompleta.
- Cuota máxima y pesos de competencia: criterios del equipo, no estimaciones oficiales.

Consulta registrada en el código: 20/10/2026 para las referencias externas. Sus contenidos pertenecen a sus titulares; citarlos no implica licencia abierta ni verificación independiente. Las variaciones del README sobre ticket y costes son cálculos de sensibilidad a socios constantes, no resultados de una nueva ejecución.

La [validación de 20 registros OSM](validacion_20_gimnasios.md) enlaza sus fuentes de contraste. Google Maps, webs oficiales y directorios sirven como evidencia consultada; no se incorporan sus bases de datos a OSM ni se presume autorización para redistribuir sus contenidos.

## Software de terceros

Se reconoce la autoría de los proyectos incluidos en los requisitos de [pipeline](../requirements.txt) y [dashboard](../streamlit_portable/requirements.txt):

| Proyectos | Licencia principal |
|---|---|
| NumPy, pandas, GeoPandas, scikit-learn, ipykernel, nbclient, python-dotenv | BSD-3-Clause |
| Requests, boto3, PyArrow, Streamlit | Apache-2.0 |
| Plotly | MIT |
| Matplotlib | [Licencia basada en PSF](https://matplotlib.org/stable/project/license.html) |
| Leaflet / Volodymyr Agafonkin y CloudMade | [BSD-2-Clause](https://github.com/Leaflet/Leaflet/blob/v1.9.4/LICENSE) |
| Lucide contributors; partes de Feather / Cole Bemis | [ISC; partes MIT](https://github.com/lucide-icons/lucide/blob/0.468.0/LICENSE) |
| IBM Plex Sans / IBM | [SIL OFL-1.1](https://github.com/IBM/plex/blob/master/LICENSE.txt) |

Al distribuir software deben conservarse los avisos y textos de licencia exigidos por cada versión, incluidos los de componentes transitivos. Esta relación no sustituye esos textos.

## Código propio

El repositorio no declara una licencia de distribución para el código propio. Su publicación no concede por sí sola una licencia general de reutilización. Las licencias de los datos y de terceros son independientes.
