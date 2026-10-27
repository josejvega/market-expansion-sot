# Validación manual de 20 registros OSM

## Conclusión

Se revisó una muestra aleatoria de 20 registros clasificados como gimnasio en `gyms_with_municipality_andalusia.parquet`. Los 20 tienen una referencia pública localizada, pero algunos son instalaciones especializadas, pabellones o casos que requieren confirmación adicional.

La muestra valida la existencia de referencias públicas, no una precisión de `20/20` gimnasios convencionales activos.

## Resultado resumido

| Indicador | Resultado |
|---|---:|
| Registros revisados | 20 |
| Registros con referencia pública localizada | 20 |
| Instalaciones especializadas o pabellones identificados | 6 |
| Casos que requieren confirmación adicional | 3 |

## Método

Se comprobó el nombre y el municipio en Google Maps. Cuando la ficha no era clara, no coincidía exactamente o no era accesible, se utilizó la web oficial u otra fuente publicada.

Se considera corroborada una referencia cuando una fuente pública permite identificar el establecimiento y el municipio. La correspondencia exacta con el registro OSM, la tipología de gimnasio y la actividad actual se valoran por separado; los casos ambiguos no se dan por confirmados. El porcentaje de referencias localizadas no mide la precisión como competidores activos ni la cobertura de establecimientos ausentes en OSM.

**Fecha de revisión:** 26/10/2026, confirmada por el equipo.

La tabla estructurada para publicar en S3 está en
[validacion_20_gimnasios.csv](validacion_20_gimnasios.csv). Se compiló a mano
desde la evidencia de [validacion_20_gimnasios.txt](validacion_20_gimnasios.txt);
no la genera el pipeline de evaluación de competencia. La app la lee
exclusivamente desde `results/negocio/auditoria_20_gimnasios.csv` en S3.

## Interpretación para el modelo

OSM se utiliza como fuente de localización de oferta deportiva, no como auditoría completa del mercado. El 100 % de cruce representa asignación espacial a municipios CNIG; no demuestra que todos los puntos sean gimnasios convencionales. La ausencia de un registro OSM tampoco demuestra ausencia de competencia.

## Evidencia detallada

El detalle de los 20 registros, sus identificadores, fuentes, enlaces y observaciones se conserva en [validacion_20_gimnasios.txt](validacion_20_gimnasios.txt). Este Markdown contiene únicamente el resumen para revisión y presentación.
