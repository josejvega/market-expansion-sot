"""
ejecutar.py  -  T5 de principio a fin.
Uso (desde la raíz del repo):  python -m src.negocio.ejecutar

Entrada:
  - data/oro/municipios_andalucia.parquet           (cuando exista)
  - si no: data/processed/municipios_andalucia_competencia_niveles.csv (provisional)
  - data/resultados/clusters.parquet o clusters.csv (salida de T4: municipality_code, cluster)
Salida (data/outputs/, ignorado por Git):
  - municipios_evaluados_<pesos>.csv, baseline_<pesos>.csv, top_facturacion_<pesos>.csv
  - si hay clusters: seleccion_modelo_<pesos>.csv, comparacion_<pesos>.csv,
    sensibilidad_detalle.csv, sensibilidad_frecuencias.csv
"""
from pathlib import Path
import pandas as pd

from .supuestos import ESCENARIOS_PESOS, parametros
from .valor_negocio import (comparar, evaluar, pesos_definidos, sensibilidad,
                            top5_baseline, top5_facturacion, top5_modelo)

RAIZ = Path(__file__).resolve().parents[2]
ORO = RAIZ / "data" / "oro" / "municipios_andalucia.parquet"
PROVISIONAL = RAIZ / "data" / "processed" / "municipios_andalucia_competencia_niveles.csv"
CLUSTERS = [RAIZ / "data" / "resultados" / "clusters.parquet",
            RAIZ / "data" / "resultados" / "clusters.csv"]
SALIDA = RAIZ / "data" / "outputs"

NECESARIAS = ["municipality_code", "municipality_name", "population_18_50",
              "comp_fitness_centre", "comp_sports_centre", "comp_fitness_station"]
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


def cargar_clusters():
    """Lee la salida de T4 (parquet o csv). Devuelve None si aún no existe."""
    for ruta in CLUSTERS:
        if ruta.exists():
            cl = (pd.read_parquet(ruta) if ruta.suffix == ".parquet"
                  else pd.read_csv(ruta, dtype={"municipality_code": "string"}))
            if not {"municipality_code", "cluster"}.issubset(cl.columns):
                raise ValueError(f"{ruta.name} debe tener las columnas municipality_code y cluster.")
            cl["municipality_code"] = cl["municipality_code"].astype(str).str.zfill(5)
            if cl["municipality_code"].duplicated().any():
                raise ValueError(f"{ruta.name}: municipality_code duplicado.")
            print(f"Clusters leídos de {ruta.name}: {cl['cluster'].nunique()} grupos")
            return cl[["municipality_code", "cluster"]]
    return None


def cargar():
    if ORO.exists():
        df = pd.read_parquet(ORO)
        fuente = "tabla oro"
    else:
        df = pd.read_csv(PROVISIONAL, dtype={"ine_code": "string"}, encoding="utf-8-sig")
        df = df.rename(columns={"ine_code": "municipality_code", "pop_18_50": "population_18_50",
                                "comp_gimnasio": "comp_fitness_centre",
                                "comp_estacion_exterior": "comp_fitness_station"})
        # Pabellón / centro deportivo = polideportivo + otro_deporte (ambos son sports_centre).
        # comp_otro (10 elementos con otro leisure) queda fuera y se documenta.
        df["comp_sports_centre"] = df["comp_polideportivo"] + df["comp_otro_deporte"]
        fuente = "tabla PROVISIONAL (processed)"
    falta = [c for c in NECESARIAS if c not in df.columns]
    if falta:
        raise ValueError(f"Faltan columnas: {falta}")
    df["municipality_code"] = df["municipality_code"].astype(str).str.zfill(5)
    if df["municipality_code"].duplicated().any():
        raise ValueError("municipality_code duplicado.")
    cl = cargar_clusters()
    if cl is not None:
        df = df.merge(cl, on="municipality_code", how="left", validate="one_to_one")
        if df["cluster"].isna().any():
            print(f"Aviso: {int(df['cluster'].isna().sum())} municipios sin cluster.")
    print(f"Entrada: {fuente} · {len(df)} municipios · clusters: {'sí' if 'cluster' in df else 'no'}")
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
            if not mod.empty:
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
