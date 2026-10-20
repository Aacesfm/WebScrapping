"""Fechas, muestreo estadístico y reparto de conteos."""
from datetime import date, datetime, timedelta

import numpy as np

import config as cfg


def a_fecha(valor):
    """Convierte Timestamp/datetime a date; deja intactos los date."""
    return valor.date() if isinstance(valor, datetime) else valor


def sumar_anios(fecha, anios):
    return fecha + timedelta(days=round(anios * cfg.DIAS_POR_ANIO))


def edad_en(nacimiento, referencia):
    """Edad cumplida en años calendario."""
    return referencia.year - nacimiento.year - ((referencia.month, referencia.day) < (nacimiento.month, nacimiento.day))


def normal_truncada(rng, p, max_intentos=10_000):
    for _ in range(max_intentos):
        x = rng.normal(p['media'], p['desv'])
        if p['min'] <= x <= p['max']:
            return float(x)
    raise ValueError(f'Parámetros de distribución normal truncada incompatibles: {p}')


def lognormal_acotada(rng, p, max_intentos=10_000):
    mu = np.log(p['mediana'])
    for _ in range(max_intentos):
        x = rng.lognormal(mu, p['sigma'])
        if p['min'] <= x <= p['max']:
            return float(x)
    raise ValueError(f'Parámetros de distribución lognormal acotada incompatibles: {p}')


def ruido_multiplicativo(rng, sigma):
    """Factor lognormal con media 1."""
    return float(rng.lognormal(-sigma ** 2 / 2, sigma))


def repartir_por_proporcion(total, proporciones):
    """Reparte `total` en enteros con el método del mayor residuo."""
    claves = list(proporciones)
    pesos = np.array([proporciones[k] for k in claves], dtype=float)
    if not np.isclose(pesos.sum(), 1.0):
        raise ValueError(f'Las proporciones deben sumar 1 (suman {pesos.sum():.4f}).')
    exactos = pesos * total
    base = np.floor(exactos).astype(int)
    orden = np.argsort(-(exactos - base), kind='stable')
    base[orden[:total - base.sum()]] += 1
    return dict(zip(claves, base.tolist()))
