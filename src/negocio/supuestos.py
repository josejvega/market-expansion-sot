"""
supuestos.py
Parámetros económicos de T5 (valor de negocio) y T7 (sensibilidad).
Cada valor tiene fuente, URL y fecha de consulta (sección 7.4 del challenge).
No es un fichero de datos: son supuestos documentados, no se ingieren.
"""

IVA = 0.21  # IVA general aplicado a cuotas de gimnasio privado en España

SUPUESTOS = {
    "penetracion": {
        "bajo": 0.165, "central": 0.218, "alto": 0.307,
        "fuente": ("Bajo: Informe anual sector fitness España 2025 (F. España Activa, "
                   "Deloitte, FNEID): 7 M abonados, 16,5 % pob. 15+. "
                   "Central: EHD 2024/25 (MEFPD/CSD), abonados a gimnasio privado, 15+. "
                   "Alto: EHD 2024/25, abonados a cualquier gimnasio, 15+."),
        "url": "https://www.educacionfpydeportes.gob.es/mc/deportedata/habitos/resultados.html",
        "consultado": "2026-10-20",
    },
    # Ticket SIN IVA, para que sea comparable con los costes (también sin IVA).
    "ticket_mensual": {
        "bajo": round(18.00 / (1 + IVA), 2),                 # 14,88
        "central": round(24.99 * 13 / 12 / (1 + IVA), 2),    # 22,37
        "alto": 24.91,
        "fuente": ("Bajo: Planet Fitness Clásico 18 €/mes con IVA. "
                   "Central: Basic-Fit Comfort España 24,99 € cada 4 semanas "
                   "(13 cobros/año) con IVA. Fuente precios: ESdiario 14/10/2026. "
                   "Alto: Basic-Fit FY2025, ingreso medio real por socio y mes "
                   "(grupo, contable, sin IVA)."),
        "url": "https://corporate.basic-fit.com/investors/annual-reports",
        "consultado": "2026-10-20",
    },
    "capacidad": {
        "bajo": 2200, "central": 2600, "alto": 2900,
        "fuente": ("Socios por centro de los 4 grandes low-cost en España (GestiónFit, "
                   "datos 2024): media 2.611; Synergym 2.205. Alto: Basic-Fit grupo "
                   "FY2025, 2.902."),
        "url": "https://www.gestionfit.com/industria/los-gigantes-del-fitness-low-cost-espanol",
        "consultado": "2026-10-20",
    },
    "cuota_max": {
        "bajo": 0.25, "central": 0.40, "alto": 0.60,
        "fuente": "Supuesto del equipo. Sin fuente directa; se prueba en sensibilidad.",
        "url": None,
        "consultado": None,
    },
    # Atractivo de un low-cost nuevo frente a un competidor medio (regla C).
    # Un low-cost capta en proporción a su tamaño, no a partes iguales.
    # 1.0 = reparto igualitario (todos los centros iguales).
    "atractivo_nuevo": {
        "bajo": 1.0,
        "central": round(2611 / 1200, 2),   # 2,18
        "alto": round(2902 / 1218, 2),      # 2,38
        "fuente": ("Socios por centro low-cost en España (GestiónFit 2024: 2.611) / socios medios "
                   "por centro fitness en España (Informe sector 2025: 7 M / 5.806 = 1.200). "
                   "Alto: Basic-Fit grupo 2.902 / media EHFMR 2024 1.218 (citada por GestiónFit). "
                   "Bajo: reparto igualitario."),
        "url": "https://www.gestionfit.com/industria/los-gigantes-del-fitness-low-cost-espanol",
        "consultado": "2026-10-20",
    },
    # Umbral de viabilidad en EUROS (coste anual de un club). No depende del ticket.
    "coste_anual_club": {
        "bajo": 524_000, "central": 556_000, "alto": 556_000,
        "fuente": ("Basic-Fit FY2025: costes de club (personal 261,2 + otros 343,2 + "
                   "alquiler 295,1 = 899,5 M€) / 1.618 clubes medios (central) "
                   "o / 1.716 clubes a cierre (bajo). Sin amortización ni CAPEX."),
        "url": "https://annualreport.basic-fit.com/2025/mbr/business-and-financial-review/",
        "consultado": "2026-10-20",
    },
    # Solo para la regla alternativa "demanda no cubierta".
    "socios_medios_comp": {
        "bajo": 1200, "central": 1200, "alto": 1200,
        "fuente": "Informe anual sector fitness España 2025: 7 M abonados / 5.806 centros fitness.",
        "url": "https://www.deloitte.com/es/es/services/consulting/perspectives/informe-sector-fitness-en-espana.html",
        "consultado": "2026-10-20",
    },
}


PESOS_CENTRAL = "central"
ESCENARIOS_PESOS = {
    "solo_gimnasios": {
        "fitness_centre": 1.0,
        "sports_centre": 0.0,
        "fitness_station": 0.0,
    },
    "central": {
        "fitness_centre": 1.0,
        "sports_centre": 0.1,
        "fitness_station": 0.1,
    },
    "todo_igual": {
        "fitness_centre": 1.0,
        "sports_centre": 1.0,
        "fitness_station": 1.0,
    },
}


def parametros(escenario="central", **cambios):
    """Diccionario plano con los valores de un escenario. cambios= sobrescribe uno a uno."""
    if escenario not in ("bajo", "central", "alto"):
        raise ValueError("Escenario no válido: usa 'bajo', 'central' o 'alto'.")
    p = {k: v[escenario] for k, v in SUPUESTOS.items()}
    for k, nivel in cambios.items():
        p[k] = SUPUESTOS[k][nivel]
    return p
