"""
ejecutar.py  -  T5 de principio a fin.
Uso (desde la raíz del repo):  python -m src.negocio.ejecutar

Entrada:
  - data/processed/gold/tabla_oro_municipios_andalucia.parquet
  - data/resultados/clusters.csv (salida del modelo; parquet como alternativa)
Salida (data/outputs/, ignorado por Git):
  - municipios_evaluados_<pesos>.csv, baseline_<pesos>.csv, top_facturacion_<pesos>.csv
  - si hay clusters: seleccion_modelo_<pesos>.csv, comparacion_<pesos>.csv,
    sensibilidad_detalle.csv, sensibilidad_frecuencias.csv
"""
from pathlib import Path
import numpy as np
import pandas as pd

from src.modelo.modelo import CLUSTERS_PATH, EXPECTED_MUNICIPALITIES
from src.procesado.common.paths import DATA_DIR, GOLD_TABLE_PATH

from .supuestos import ESCENARIOS_PESOS, parametros
from .valor_negocio import (comparar, evaluar, pesos_definidos, sensibilidad,
                            top5_baseline, top5_facturacion, top5_modelo)

ORO = GOLD_TABLE_PATH
CLUSTERS = [CLUSTERS_PATH, CLUSTERS_PATH.with_suffix(".parquet")]
SALIDA = DATA_DIR / "outputs"

NECESARIAS = ["municipality_code", "municipality_name", "population_18_50",
              "gyms_count", "other_sports_facilities_count"]
VER = ["municipality_name", "population_18_50", "competidores_pond", "cuota_centro",
       "socios_centro", "facturacion_anual", "margen_eur", "perdidas_eur", "viable",
       "flag_sin_competencia_osm"]


def mostrar(titulo, tabla):
    """Imprime una tabla o un aviso si está vacía."""
    if tabla.empty:
        print(f"{titulo}: ningún municipio cumple las condiciones en este escenario.")
    else:
        print(f"{titulo}:")
        print(tabla[VER].round(3).to_string(index=False))


def validar_codigos(df: pd.DataFrame, fuente: str) -> None:
    codes = df["municipality_code"].astype("string")
    if len(codes) != EXPECTED_MUNICIPALITIES:
        raise ValueError(f"{fuente}: se esperaban {EXPECTED_MUNICIPALITIES} municipios.")
    if not codes.str.fullmatch(r"\d{5}").fillna(False).all():
        raise ValueError(f"{fuente}: municipality_code debe tener cinco digitos.")
    if codes.duplicated().any():
        raise ValueError(f"{fuente}: municipality_code duplicado.")
    df["municipality_code"] = codes


def cargar_clusters() -> pd.DataFrame:
    """Lee primero el CSV producido por el modelo y exige cobertura completa."""
    for ruta in CLUSTERS:
        if ruta.exists():
            cl = (pd.read_parquet(ruta) if ruta.suffix == ".parquet"
                  else pd.read_csv(ruta, dtype={"municipality_code": "string"}))
            if not {"municipality_code", "cluster"}.issubset(cl.columns):
                raise ValueError(f"{ruta.name} debe tener las columnas municipality_code y cluster.")
            validar_codigos(cl, ruta.name)
            labels = pd.to_numeric(cl["cluster"], errors="raise")
            if (labels.isna().any() or not np.isfinite(labels.astype(float)).all()
                    or labels.lt(0).any() or labels.mod(1).ne(0).any()):
                raise ValueError(f"{ruta.name}: cluster debe ser un entero no negativo.")
            cl["cluster"] = labels.astype("int64")
            print(f"Clusters leídos de {ruta.name}: {cl['cluster'].nunique()} grupos")
            return cl[["municipality_code", "cluster"]]
    raise FileNotFoundError(
        f"No se encuentran clusters en {CLUSTERS}. Ejecuta python -m src.modelo.modelo."
    )


def cargar():
    if not ORO.is_file():
        raise FileNotFoundError(f"No se encuentra Gold en {ORO}. Ejecuta primero 02_calidad.")
    df = pd.read_parquet(ORO)
    falta = [c for c in NECESARIAS if c not in df.columns]
    if falta:
        raise ValueError(f"Faltan columnas: {falta}")
    validar_codigos(df, "Gold")
    if "cluster" in df.columns:
        raise ValueError("Gold no debe contener cluster; se lee de la salida del modelo.")
    for column in ["population_18_50", "gyms_count", "other_sports_facilities_count"]:
        values = pd.to_numeric(df[column], errors="raise")
        if (values.isna().any() or not np.isfinite(values.astype(float)).all()
                or values.lt(0).any() or values.mod(1).ne(0).any()):
            raise ValueError(f"Gold: {column} debe contener enteros no negativos.")
        df[column] = values
    if df["population_18_50"].eq(0).any():
        raise ValueError("Gold: population_18_50 debe ser positiva.")
    cl = cargar_clusters()
    if set(df["municipality_code"]) != set(cl["municipality_code"]):
        raise ValueError("Los clusters deben cubrir exactamente los municipios de Gold.")
    df = df.merge(cl, on="municipality_code", how="left", validate="one_to_one")
    print(f"Entrada: {ORO} · {len(df)} municipios · clusters: sí")
    return df


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    df = cargar()
    p = parametros()
    print("Supuestos (central):", p)
    print(f"Socios break-even: {p['coste_anual_club'] / (p['ticket_mensual'] * 12):.0f}")

    hay_clusters = "cluster" in df.columns and df["cluster"].notna().all()
    for pesos in ESCENARIOS_PESOS:
        if not pesos_definidos(pesos):
            print(f"\n[{pesos}] pesos pendientes de decidir: se salta.")
            continue
        ev = evaluar(df, pesos=pesos, con_candidatos=hay_clusters)
        ev.to_csv(SALIDA / f"municipios_evaluados_{pesos}.csv", index=False, encoding="utf-8-sig")

        base = top5_baseline(ev)
        base.to_csv(SALIDA / f"baseline_{pesos}.csv", index=False, encoding="utf-8-sig")
        top_fact = top5_facturacion(ev)
        top_fact.to_csv(SALIDA / f"top_facturacion_{pesos}.csv", index=False, encoding="utf-8-sig")

        print(f"\n[{pesos}] Municipios viables: {int(ev['viable'].sum())} de {len(ev)}")
        mostrar("BASELINE (top 5 por población 18-50)", base)
        mostrar("TOP 5 FACTURACIÓN (viables, sin clusters)", top_fact)

        if hay_clusters:
            mod = top5_modelo(ev)
            mod.to_csv(SALIDA / f"seleccion_modelo_{pesos}.csv", index=False, encoding="utf-8-sig")
            mostrar("MODELO A (candidatos viables por facturación)", mod)
            tabla, cambios = comparar(base, mod)
            tabla.to_csv(SALIDA / f"comparacion_{pesos}.csv", encoding="utf-8-sig")
            print(tabla.round(1).to_string())
            print("Cambios:", cambios)

    if hay_clusters:
        detalle, freq = sensibilidad(df)
        detalle.to_csv(SALIDA / "sensibilidad_detalle.csv", index=False, encoding="utf-8-sig")
        freq.to_csv(SALIDA / "sensibilidad_frecuencias.csv", index=False, encoding="utf-8-sig")
        print("\nSENSIBILIDAD:")
        print(freq.head(10).to_string(index=False))
    else:
        print("\nSin clusters de T4: modelo, comparación y sensibilidad quedan pendientes.")
    print("\nGuardado en:", SALIDA)


if __name__ == "__main__":
    main()
