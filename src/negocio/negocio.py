def demanda_potencial(poblacion_18_50, penetracion):
    """Calculate potential demand based on the population aged 18-50 and market penetration."""
    if poblacion_18_50 < 0:
        raise ValueError("poblacion_18_50 debe ser mayor o igual a cero.")
    if not (0 <= penetracion <= 1):
        raise ValueError("penetracion debe estar entre 0 y 1.")

    return poblacion_18_50 * penetracion

def facturacion_potencial(demanda_potencial, captacion, ticket_mensual):
    """Calculate potential revenue based on potential demand and average spending."""
    if demanda_potencial < 0:
        raise ValueError("demanda_potencial debe ser mayor o igual a cero.")
    if captacion < 0:
        raise ValueError("captacion debe ser mayor o igual a cero.")
    if ticket_mensual < 0:
        raise ValueError("ticket_mensual debe ser mayor o igual a cero.")

    return demanda_potencial * captacion * ticket_mensual * 12  # Annual revenue