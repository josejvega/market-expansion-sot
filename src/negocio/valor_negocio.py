"""
valor_negocio.py
Demanda, facturación y viabilidad de un centro nuevo por municipio (T5),
selección final (T6) y sensibilidad (T7).
Entrada: DataFrame con una fila por municipio y, como mínimo:
  municipality_code, municipality_name, population_18_50,
  comp_fitness_centre, comp_sports_centre, comp_fitness_station
  (y cluster para el modelo y la sensibilidad).
"""
from itertools import product
import numpy as np
import pandas as pd

from .supuestos import ESCENARIOS_PESOS, PESOS_CENTRAL, parametros


def pesos_definidos(nombre):
    """True si el escenario de pesos no tiene valores pendientes (None)."""
    return all(v is not None for v in ESCENARIOS_PESOS[nombre].values())


def competidores_ponderados(df, pesos=PESOS_CENTRAL):
    nombre = pesos if isinstance(pesos, str) else "personalizado"
    pesos = ESCENARIOS_PESOS[pesos] if isinstance(pesos, str) else pesos
    if any(v is None for v in pesos.values()):
        raise ValueError(f"Pesos '{nombre}' pendientes de decidir: rellénalos en supuestos.py.")
    out = df.copy()
    out["competidores_pond"] = sum(out[f"comp_{k}"].fillna(0) * v for k, v in pesos.items())
    pop = out["population_18_50"]
    out["comp_per_10k_18_50"] = np.where(pop > 0, out["competidores_pond"] / pop * 10_000, np.nan)
    out["flag_sin_competencia_osm"] = out["competidores_pond"].eq(0)
    return out


def candidatos(df):
    """Regla del challenge: menos competencia por habitante objetivo que la media del cluster."""
    out = df.copy()
    media = out.groupby("cluster")["comp_per_10k_18_50"].transform("mean")
    out["media_cluster_comp_per_10k"] = media
    out["candidate_flag"] = out["comp_per_10k_18_50"] < media
    return out


def demanda(df, p):
    out = df.copy()
    out["socios_potenciales"] = out["population_18_50"] * p["penetracion"]
    out["mercado_potencial_eur"] = out["socios_potenciales"] * p["ticket_mensual"] * 12
    out["demanda_por_comp"] = out["socios_potenciales"] / np.maximum(out["competidores_pond"], 1)
    return out


def facturacion(df, p, regla="C"):
    out = df.copy()
    techo = out["socios_potenciales"] * p["cuota_max"]
    if regla == "C":
        f = p["atractivo_nuevo"]   # cuota ponderada por atractivo: f / (C + f)
        out["cuota_centro"] = np.minimum(f / (out["competidores_pond"] + f), p["cuota_max"])
        out["socios_captables"] = out["socios_potenciales"] * out["cuota_centro"]
    elif regla == "demanda_no_cubierta":
        libre = np.maximum(0, out["socios_potenciales"]
                           - out["competidores_pond"] * p["socios_medios_comp"])
        out["socios_captables"] = np.minimum(libre, techo)
        out["cuota_centro"] = np.where(out["socios_potenciales"] > 0,
                                       out["socios_captables"] / out["socios_potenciales"], 0)
    else:
        raise ValueError("Regla no válida: 'C' o 'demanda_no_cubierta'.")
    out["socios_centro"] = np.minimum(out["socios_captables"], p["capacidad"])
    out["facturacion_anual"] = out["socios_centro"] * p["ticket_mensual"] * 12
    return out


def viabilidad(df, p):
    out = df.copy()
    out["umbral_facturacion"] = p["coste_anual_club"]
    out["socios_break_even"] = p["coste_anual_club"] / (p["ticket_mensual"] * 12)
    out["margen_eur"] = out["facturacion_anual"] - p["coste_anual_club"]
    out["perdidas_eur"] = (-out["margen_eur"]).clip(lower=0)   # pérdidas operativas estimadas
    out["viable"] = out["margen_eur"] >= 0
    return out


def evaluar(df, escenario="central", pesos=PESOS_CENTRAL, regla="C", con_candidatos=False, **cambios):
    """Cadena completa. Se aplica igual al baseline y al modelo."""
    p = parametros(escenario, **cambios)
    out = competidores_ponderados(df, pesos)
    if con_candidatos:
        out = candidatos(out)
    out = demanda(out, p)
    out = facturacion(out, p, regla)
    return viabilidad(out, p)


def top5_baseline(df_eval):
    """Práctica actual del cliente: los 5 con más población 18-50."""
    return df_eval.nlargest(5, "population_18_50")


def top5_facturacion(df_eval):
    """Referencia: los 5 viables que más facturan, sin usar clusters."""
    viables = df_eval[df_eval["viable"]]
    return viables.sort_values(["facturacion_anual", "demanda_por_comp"], ascending=False).head(5)


def top5_modelo(df_eval):
    """Modelo A: candidatos viables, por facturación; desempate por demanda por competidor."""
    eleg = df_eval[df_eval["candidate_flag"] & df_eval["viable"]]
    return eleg.sort_values(["facturacion_anual", "demanda_por_comp", "population_18_50"],
                            ascending=False).head(5)


def comparar(base, modelo):
    """Tabla baseline vs modelo con las métricas que pide el challenge."""
    def resumen(t):
        return {"demanda_por_comp_media": t["demanda_por_comp"].mean(),
                "facturacion_total": t["facturacion_anual"].sum(),
                "facturacion_media": t["facturacion_anual"].mean(),
                "viables": int(t["viable"].sum()),
                "margen_total_eur": t["margen_eur"].sum(),
                "perdidas_total_eur": t["perdidas_eur"].sum()}
    r = pd.DataFrame({"baseline": resumen(base), "modelo": resumen(modelo)})
    r["diferencia"] = r["modelo"] - r["baseline"]
    sb, sm = set(base["municipality_name"]), set(modelo["municipality_name"])
    cambios = {"salen": sorted(sb - sm), "entran": sorted(sm - sb), "se_mantienen": sorted(sb & sm)}
    return r, cambios


def sensibilidad(df):
    """Rejilla de escenarios. Devuelve el detalle y cuántas veces sale cada municipio."""
    filas, n = [], 0
    niveles = ["bajo", "central", "alto"]
    for pen, cuota, atr, pesos, regla in product(niveles, niveles, niveles,
                                                 [k for k in ESCENARIOS_PESOS if pesos_definidos(k)],
                                                 ["C", "demanda_no_cubierta"]):
        n += 1
        ev = evaluar(df, "central", pesos, regla, con_candidatos=True,
                     penetracion=pen, cuota_max=cuota, atractivo_nuevo=atr)
        top = top5_modelo(ev).assign(
            escenario=f"pen={pen}|cuota={cuota}|atr={atr}|pesos={pesos}|regla={regla}")
        top["posicion"] = range(1, len(top) + 1)
        filas.append(top[["escenario", "posicion", "municipality_code", "municipality_name",
                          "facturacion_anual", "demanda_por_comp"]])
    detalle = pd.concat(filas, ignore_index=True)
    freq = (detalle.groupby(["municipality_code", "municipality_name"])
            .agg(apariciones=("escenario", "count"), posicion_media=("posicion", "mean"),
                 fact_min=("facturacion_anual", "min"), fact_max=("facturacion_anual", "max"))
            .reset_index().sort_values(["apariciones", "posicion_media"], ascending=[False, True]))
    freq["robustez"] = freq["apariciones"].astype(str) + f" de {n}"
    return detalle, freq
