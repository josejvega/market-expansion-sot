# Market Expansion SOT · Gimnasios en Andalucía

## 1. Problema y decisión

El equipo de expansión debe elegir **cinco municipios para abrir gimnasios low-cost**, mejorando una decisión basada en visitas y experiencia. El proyecto compara demanda y competencia, identifica mercados similares y estima la viabilidad de un centro por municipio. **Son escenarios de apoyo a la decisión, no ventas previstas ni garantías de rentabilidad.**

## 2. Hipótesis de trabajo

- **H1:** una mayor población de 18–50 años implica mayor potencial de mercado.
- **H2:** una mayor renta se asocia con mayor probabilidad de contratar un gimnasio.
- **H3:** un mayor crecimiento demográfico ofrece más oportunidades futuras.
- **H4:** pocos gimnasios respecto a la población objetivo pueden indicar demanda no cubierta.

Estas hipótesis orientan el análisis; el clustering no demuestra causalidad y una baja presencia en OSM también puede reflejar datos incompletos.

## 3. Fuentes y trazabilidad

| Origen | Periodo utilizado | Licencia |
|---|---|---|
| INE: población por edad, tabla 68542 | 2021–2025; población objetivo de 2025 | CC BY 4.0, salvo excepción |
| INE: renta, tabla 30824 | 2024 | CC BY 4.0, salvo excepción |
| © OpenStreetMap contributors, vía Overpass | Oferta deportiva en la extracción | ODbL 1.0 |
| © IGN/CNIG: límites BDDAE y mapa IGNBase | Cartografía consultada | Licencia IGN compatible con CC BY 4.0 |

Los logs disponibles registran la ingesta del **20/10/2026**; los CSV finales no incluyen fecha de descarga que permita verificar por sí solos esa correspondencia. El periodo estadístico no es la fecha de descarga. [Enlaces, atribuciones y licencias completas](docs/fuentes_y_licencias.md).

## 4. Calidad de datos

Tabla de calidad aportada por el equipo; el cruce mide registros limpios elegibles que alcanzan su destino analítico, no exactitud comercial.

| Fuente | Registros origen | Nulos clave | Duplicados | Cruce | Tratamiento |
|---|---:|---:|---:|---:|---|
| Población | 1.201.050 | 0 % | 0 | 99,75 % | Agregar municipio/año; 10 filas limpias fuera de Gold |
| Renta | 786 | 0 % | 0 | 100 % | Rechazar 3 registros antes del cruce |
| OSM | 3.573 | 0 % | 0 | 100 % | Validar puntos y asignar municipio |
| CNIG | 786 | 0 % | 0 | 99,75 % | Rechazar 1 límite; 2 limpios fuera de Gold |

La [revisión manual de 20 registros](docs/validacion_20_gimnasios.md), realizada el **26/10/2026**, localizó referencias públicas en **20/20**, identificó 6 instalaciones especializadas o pabellones y señaló 3 casos pendientes de confirmación. **No acredita 100 % de gimnasios convencionales activos ni cobertura completa de OSM.**

## 5. Solución y resultados frente al baseline

**S3 almacena; EC2 procesa:** ingesta → Bronze → limpieza Silver → integración Gold → modelo y negocio → Streamlit. [Diagrama de arquitectura](docs/Arquitectura.png). Silver y Gold se generan en el mismo notebook, reutilizando tablas en memoria.

KMeans agrupa por población objetivo (`log1p`), renta y crecimiento, estandarizados; usa **4 clusters**, `random_state=0` y `n_init=10`. Inercia y silhouette ayudan a revisar esa elección. Negocio selecciona candidatos con competencia ponderada por **10.000 residentes de 18–50 años** inferior a la media de su cluster; exige viabilidad y superar el control heurístico de calidad. Los pesos centrales son gimnasio = 1 y otra instalación = 0,1. Se evaluaron **783 municipios**.

El baseline elige los cinco con más población objetivo: Sevilla, Málaga, Córdoba, Granada y Jerez. Ambas estrategias usan los mismos supuestos económicos.

| Métrica anual estimada | Baseline | Modelo | Diferencia |
|---|---:|---:|---:|
| Centros viables / seleccionados | 3/5 | 5/5 | +2 viables |
| Facturación conjunta | 2.649.735 € | 3.489.720 € | +839.985 € (+31,7 %) |
| Margen operativo conjunto | −130.265 € | 709.720 € | +839.985 € |
| Socios potenciales por competidor, media | 973,8 | 2.263,4 | +132,4 % |

## 6. Recomendación y valor de negocio

**Priorizar el estudio de Marbella, Algeciras, Fuengirola, Huelva y Sanlúcar de Barrameda**, un centro por municipio. El Puerto de Santa María y Alcalá de Guadaíra quedan pendientes de validación por baja cobertura aparente de competencia. El umbral de calidad —oferta ponderada ≥50 % de una referencia de 1 gimnasio/10.000 personas objetivo— es una regla interna, no cobertura real demostrada.

La demanda se obtiene como población objetivo × penetración. La captación combina atractivo y competencia, con topes de cuota y capacidad; facturación = socios efectivos × ticket sin IVA × 12.

| Supuesto central | Fuente o criterio | Impacto si cambia |
|---|---|---|
| Penetración: 21,8 % | Hábitos Deportivos, Ministerio/CSD | Cambia demanda y viabilidad; efecto limitado por capacidad |
| Ticket: 22,37 €/mes sin IVA | Tarifas citadas; normalización anual | −10 % implica −69.794 €/centro, a socios constantes |
| Capacidad: 2.600 socios | GestiónFit / referencia low-cost | Limita ingresos a 697.944 €/centro/año |
| Cuota máxima: 40 %; atractivo: 2,18 | Equipo; ratios sectoriales | Cambian captación y ranking |
| Coste anual: 556.000 €/centro | Basic-Fit; incluye alquiler | +10 % reduce margen en 55.600 €/centro |

Los cinco centros alcanzan el mismo techo: **697.944 € de ingresos y 141.944 € de margen por centro**; no se presupone crecimiento ilimitado. Equilibrio: unos 2.071 socios. La sensibilidad contempla 108 combinaciones: Huelva aparece en 67 y Algeciras en 65; son frecuencias, no probabilidades. La alternativa diversificada selecciona 3 centros, no fuerza cinco. [Supuestos y referencias](src/negocio/supuestos.py).

## 7. Limitaciones y siguientes pasos

Validar actividad y competencia real, incluidos municipios vecinos; estudiar barrios, accesibilidad y locales; recalcular alquiler, inversión inicial y maduración. El escenario no incluye CAPEX, financiación, amortización ni impuestos. Las fechas de población y renta difieren; datos y dependencias pueden cambiar resultados. La demanda sin tope es diagnóstica, no facturación realizable. Completar la trazabilidad de la revisión manual y verificar cada nueva ejecución antes de decidir.

## 8. Ejecución y uso de IA

**EC2 Linux, desde la raíz:** Python 3.11 recomendado, Internet, bucket S3 y rol IAM con permisos S3 adecuados, sin claves en Git. El equipo confirma ejecución de extremo a extremo; no se ha repetido para esta revisión documental.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r streamlit_portable/requirements.txt
test -f .env || cp .env.example .env
```

Configura `.env`: `SAVE_S3=true`, `SAVE_LOCALLY=false`, `S3_BUCKET=tu-bucket` y `AWS_DEFAULT_REGION=region-del-bucket`. Después:

```bash
python run.py
python -m streamlit run streamlit_portable/streamlit_app.py --server.address 127.0.0.1
```

[run.py](run.py) ejecuta los notebooks 01–04, se detiene ante errores y admite `--timeout SEGUNDOS`; **Streamlit se inicia aparte**. Alternativa interactiva: [notebooks](notebooks) en orden, kernel `.venv`; revisa `N_CLUSTERS` antes de repetir. En Windows utiliza `.\.venv\Scripts\python.exe`. Gold queda en S3 `gold/`, clusters y candidatos en `results/`, CSV e informe de negocio en `results/negocio/`. Reenvía el puerto 8501 para consultar la app; [más configuración](streamlit_portable/README.md).

**IA generativa:** se utilizó GitHub Copilot como asistencia, incluida esta documentación; no es fuente estadística ni validación de resultados. La responsabilidad es del equipo. **Código propio sin licencia de distribución declarada**; datos y dependencias conservan sus licencias.
