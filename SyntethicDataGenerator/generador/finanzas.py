"""Simulación de saldos RCV, AV y vivienda a partir del historial laboral y el salario."""
from datetime import timedelta

import numpy as np

import config as cfg
from .utilidades import lognormal_acotada, normal_truncada, ruido_multiplicativo


def _acumular(salario, inicio, fin, tasa, densidad, rendimiento):
    """Valor a la fecha de corte de aportar `tasa` del salario entre `inicio` y `fin`.

    El salario histórico decrece hacia atrás con el crecimiento real; las aportaciones se
    capitalizan con el rendimiento real hasta la fecha de corte.
    """
    if tasa <= 0 or fin <= inicio:
        return 0.0
    dias = (fin - inicio).days
    pasos = max(1, round(dias / 30.4375))
    puntos = inicio.toordinal() + (np.arange(pasos) + 0.5) * dias / pasos
    anios_a_fin = (fin.toordinal() - puntos) / cfg.DIAS_POR_ANIO
    anios_a_corte = (cfg.FECHA_CORTE.toordinal() - puntos) / cfg.DIAS_POR_ANIO
    salario_historico = salario * (1 + cfg.CRECIMIENTO_REAL_SALARIO) ** (-anios_a_fin)
    aportes = salario_historico * 12 * (dias / pasos / cfg.DIAS_POR_ANIO) * tasa * densidad
    return float(np.sum(aportes * (1 + rendimiento) ** anios_a_corte))


def _saldo_rcv(rng, regimen, salario, primera, ultima, densidad, rendimiento):
    total = sum(
        _acumular(salario, max(primera, desde) if desde else primera, ultima, tasa, densidad, rendimiento)
        for desde, tasa in cfg.TASAS_RCV[regimen]
    )
    return total * ruido_multiplicativo(rng, cfg.RUIDO_RCV_SIGMA)


def _saldo_av(rng, salario, primera, ultima, densidad, rendimiento):
    c = cfg.AHORRO_VOLUNTARIO
    probabilidad = min(c['prob_max'], c['prob_base'] * (salario / cfg.SALARIO_MENSUAL['media']) ** c['elasticidad_salario'])
    if rng.random() >= probabilidad:
        return 0.0
    tasa = lognormal_acotada(rng, c['tasa_alta'] if rng.random() < c['prob_monto_alto'] else c['tasa_pequena'])
    anios_laborales = (ultima - primera).days / cfg.DIAS_POR_ANIO
    anios_ahorro = min(anios_laborales, max(c['anios_minimos'], anios_laborales * normal_truncada(rng, c['fraccion_vida_laboral'])))
    inicio = max(primera, ultima - timedelta(days=round(anios_ahorro * cfg.DIAS_POR_ANIO)))
    return _acumular(salario, inicio, ultima, tasa, densidad, rendimiento)


def _saldo_vivienda(rng, salario, primera, ultima, densidad):
    """Devuelve (saldo, historial de crédito). El crédito vigente absorbe las aportaciones."""
    c = cfg.VIVIENDA
    rendimiento = normal_truncada(rng, c['rendimiento'])
    historial = str(rng.choice(list(c['prob_historial']), p=list(c['prob_historial'].values())))
    inicio_minimo_credito = primera + timedelta(days=round(c['antiguedad_minima_credito_anios'] * cfg.DIAS_POR_ANIO))

    if inicio_minimo_credito >= ultima:
        historial = 'SIN_CREDITO'
    if historial == 'CREDITO_LIQUIDADO':
        plazo = normal_truncada(rng, c['plazo_credito_anios'])
        liquidacion_minima = inicio_minimo_credito + timedelta(days=round(plazo * cfg.DIAS_POR_ANIO))
        if liquidacion_minima >= ultima:
            historial = 'CREDITO_VIGENTE'

    if historial == 'CREDITO_VIGENTE':
        return 0.0, historial
    if historial == 'SIN_CREDITO':
        saldo = _acumular(salario, primera, ultima, c['tasa_aportacion'], densidad, rendimiento)
    else:
        liquidacion = liquidacion_minima + timedelta(days=int(rng.random() * (ultima - liquidacion_minima).days))
        saldo = _acumular(salario, liquidacion, ultima, c['tasa_aportacion'], densidad, rendimiento)
    return saldo * ruido_multiplicativo(rng, c['ruido_sigma']), historial


def _bono_pension(salario, primera, ultima, densidad):
    """Bono potencial por servicio previo a la entrada en vigor de Cuentas Individuales."""
    c = cfg.BONO_PENSION_ISSSTE
    if primera >= cfg.FECHA_ISSSTE_2007:
        return 0.0
    anios_previos = (min(ultima, cfg.FECHA_ISSSTE_2007) - primera).days / cfg.DIAS_POR_ANIO * densidad
    anios_2007_a_baja = max(0.0, (ultima - cfg.FECHA_ISSSTE_2007).days / cfg.DIAS_POR_ANIO)
    salario_2007 = salario * (1 + cfg.CRECIMIENTO_REAL_SALARIO) ** (-anios_2007_a_baja)
    anios_a_corte = (cfg.FECHA_CORTE - cfg.FECHA_ISSSTE_2007).days / cfg.DIAS_POR_ANIO
    return salario_2007 * 12 * anios_previos * c['factor_salario_anual'] * (1 + c['rendimiento_real']) ** anios_a_corte


def simular_saldos(rng, regimen, salario, primera, ultima, densidad):
    """Saldos coherentes entre sí: comparten salario, historial y rendimiento del cliente."""
    rendimiento = normal_truncada(rng, cfg.RENDIMIENTO_RCV)
    vivienda, historial = _saldo_vivienda(rng, salario, primera, ultima, densidad)
    bono = _bono_pension(salario, primera, ultima, densidad) if regimen == cfg.REGIMEN_ISSSTE else 0.0
    return {
        'saldo_rcv': round(_saldo_rcv(rng, regimen, salario, primera, ultima, densidad, rendimiento), 2),
        'saldo_av': round(_saldo_av(rng, salario, primera, ultima, densidad, rendimiento), 2),
        'saldo_vivienda': round(vivienda, 2),
        'historial_credito_vivienda': historial,
        'bono_potencial': round(bono, 2),
    }
