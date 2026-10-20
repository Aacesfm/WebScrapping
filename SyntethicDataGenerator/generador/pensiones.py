"""Reglas pensionarias: régimen, elegibilidad, estimación de pensión y clasificación por tipo."""
import math

import numpy as np
import pandas as pd

import config as cfg
from .utilidades import a_fecha


def regimen_de(institucion, primera_cotizacion):
    """IMSS: cotización desde 01-07-1997 -> Ley 97; antes -> Ley 73. ISSSTE: Cuentas Individuales."""
    if institucion == cfg.INSTITUCION_ISSSTE:
        return cfg.REGIMEN_ISSSTE
    return cfg.REGIMEN_LEY_97 if a_fecha(primera_cotizacion) >= cfg.FECHA_LEY_97 else cfg.REGIMEN_LEY_73


def eleccion_de(regimen, primera_cotizacion):
    if regimen == cfg.REGIMEN_LEY_97:
        return 'LEY_97'
    if regimen == cfg.REGIMEN_LEY_73:
        return 'LEY_73'
    if a_fecha(primera_cotizacion) < cfg.FECHA_ISSSTE_2007:
        return 'CUENTAS_INDIVIDUALES_OPCION_2007'
    return 'CUENTAS_INDIVIDUALES_OBLIGATORIO'


def conserva_derechos(ultima_cotizacion, semanas):
    """Ley 73: vigencia = 1/4 del tiempo cotizado desde la baja, mínimo 12 meses."""
    dias_baja = (cfg.FECHA_CORTE - a_fecha(ultima_cotizacion)).days
    return dias_baja <= max(cfg.CONSERVACION_MIN_DIAS, semanas * 7 * cfg.CONSERVACION_FRACCION)


def pension_garantizada(regimen, semanas):
    c = cfg.PENSION_GARANTIZADA[regimen]
    if regimen == cfg.REGIMEN_ISSSTE:
        return float(c['base'])
    factor = 1 + c['incremento_por_100_semanas'] * max(0, semanas - c['semanas_base']) / 100
    return c['base'] * min(factor, c['tope_factor'])


def pension_minima_ley_73():
    return cfg.PENSION_MINIMA_LEY_73_SMG * cfg.SALARIO_MINIMO_DIARIO * cfg.DIAS_POR_MES


def pension_ley_73(salario_mensual, semanas, edad):
    """Cuantía básica + incrementos sobre el salario promedio de las últimas 250 semanas."""
    anios_promedio = cfg.SEMANAS_PROMEDIO_LEY_73 / cfg.SEMANAS_POR_ANIO
    promedio_mensual = salario_mensual * (1 + cfg.CRECIMIENTO_REAL_SALARIO) ** (-anios_promedio / 2)
    veces_smg = promedio_mensual / cfg.DIAS_POR_MES / cfg.SALARIO_MINIMO_DIARIO
    _, cuantia, incremento = next(fila for fila in cfg.TABLA_LEY_73 if veces_smg <= fila[0])
    anios_excedentes = max(0, semanas - cfg.SEMANAS_MIN_LEY_73) / cfg.SEMANAS_POR_ANIO
    porcentaje = min(100.0, cuantia + incremento * anios_excedentes)
    factor_edad = cfg.FACTOR_EDAD_CESANTIA.get(edad, 1.0 if edad >= 65 else cfg.FACTOR_EDAD_CESANTIA[60])
    return promedio_mensual * porcentaje / 100 * factor_edad


def factor_actuarial(genero, edad, beneficiarios, modalidad):
    """Capital requerido por cada peso de pensión mensual (renta cierta a la esperanza de vida)."""
    esperanza = max(
        cfg.ESPERANZA_VIDA_MINIMA,
        cfg.ESPERANZA_VIDA_A_60[genero] - cfg.DESCENSO_ESPERANZA_POR_ANIO * (edad - 60),
    )
    i_mensual = (1 + cfg.TASA_TECNICA) ** (1 / 12) - 1
    factor = (1 - (1 + i_mensual) ** (-esperanza * 12)) / i_mensual
    recargo = cfg.RECARGO_MODALIDAD[modalidad] + (cfg.RECARGO_SEGURO_SOBREVIVENCIA if beneficiarios == 'SI' else 0.0)
    return factor * (1 + recargo)


def _resultado(salida, tipo, motivo):
    salida.update(
        tipo_cliente=tipo,
        resultado_pensionario=cfg.RESULTADOS_POR_TIPO.get(tipo, 'NO_CLASIFICADO'),
        motivo_resultado=motivo,
    )
    return salida


def evaluar(r):
    """Deriva régimen, elegibilidad, pensión y tipo de cliente a partir de los atributos del registro.

    Entradas usadas: institucion, genero, edad, estatus_laboral, fecha_primera_cotizacion,
    fecha_ultima_cotizacion, semanas_cotizadas, anios_cotizados, salario_mensual, saldo_rcv,
    saldo_av, bono_potencial, beneficiarios, modalidad_pension.
    """
    salida = {
        'regimen_pensionario': cfg.NO_APLICA, 'eleccion_regimen': cfg.NO_APLICA,
        'conservacion_derechos': cfg.NO_APLICA, 'saldo_bono_pension': 0.0,
        'saldo_pensionario_utilizable': 0.0, 'pension_autofinanciable_estimada': np.nan,
        'pension_minima_legal_aplicable': np.nan, 'pension_final_estimada': 0.0,
    }
    if pd.isna(r['institucion']):
        return _resultado(salida, '10', 'Sin cotizaciones IMSS ni ISSSTE: no genera derecho contributivo.')

    regimen = regimen_de(r['institucion'], r['fecha_primera_cotizacion'])
    salida['regimen_pensionario'] = regimen
    salida['eleccion_regimen'] = eleccion_de(regimen, r['fecha_primera_cotizacion'])
    semanas, anios = r['semanas_cotizadas'], r['anios_cotizados']
    elegible = r['edad'] >= cfg.EDAD_MINIMA_PENSION and r['estatus_laboral'] == 'BAJA'
    if not elegible:
        return _resultado(salida, None, 'No cumple edad mínima o no está dado de baja.')

    saldo = r['saldo_rcv'] + r['saldo_av']
    salida['saldo_pensionario_utilizable'] = round(saldo, 2)

    if regimen == cfg.REGIMEN_LEY_73:
        vigente = conserva_derechos(r['fecha_ultima_cotizacion'], semanas)
        salida['conservacion_derechos'] = 'SI' if vigente else 'NO'
        if semanas < cfg.SEMANAS_MIN_LEY_73:
            return _resultado(salida, '06', f'Ley 73 con {semanas} semanas; se requieren {cfg.SEMANAS_MIN_LEY_73}.')
        if not vigente:
            return _resultado(salida, None, 'Derechos Ley 73 no vigentes.')
        calculada = pension_ley_73(r['salario_mensual'], semanas, r['edad'])
        minima = pension_minima_ley_73()
        salida.update(
            pension_autofinanciable_estimada=round(calculada, 2),
            pension_minima_legal_aplicable=round(minima, 2),
            pension_final_estimada=round(max(calculada, minima), 2),
        )
        if calculada > minima:
            return _resultado(salida, '04', 'Cuantía Ley 73 superior a la pensión mínima legal.')
        return _resultado(salida, '05', 'Cuantía Ley 73 inferior al mínimo; se aplica el piso legal.')

    if regimen == cfg.REGIMEN_ISSSTE and anios >= cfg.ANIOS_MIN_ISSSTE:
        bono = r['bono_potencial']
        salida['saldo_bono_pension'] = bono
        saldo += bono
        salida['saldo_pensionario_utilizable'] = round(saldo, 2)

    requisito_cumplido = semanas >= cfg.SEMANAS_MIN_LEY_97 if regimen == cfg.REGIMEN_LEY_97 else anios >= cfg.ANIOS_MIN_ISSSTE
    autofinanciable = saldo / factor_actuarial(r['genero'], r['edad'], r['beneficiarios'], r['modalidad_pension'])
    salida['pension_autofinanciable_estimada'] = round(autofinanciable, 2)

    if not requisito_cumplido:
        if regimen == cfg.REGIMEN_LEY_97:
            return _resultado(salida, '03', f'Ley 97 con {semanas} semanas; se requieren {cfg.SEMANAS_MIN_LEY_97}.')
        return _resultado(salida, '09', f'ISSSTE con {anios:.2f} años; se requieren {cfg.ANIOS_MIN_ISSSTE}.')

    garantizada = pension_garantizada(regimen, semanas)
    salida['pension_minima_legal_aplicable'] = round(garantizada, 2)
    es_ley_97 = regimen == cfg.REGIMEN_LEY_97
    if autofinanciable >= garantizada:
        salida['pension_final_estimada'] = round(autofinanciable, 2)
        return _resultado(salida, '01' if es_ley_97 else '07', 'Saldo suficiente para financiar la pensión por sí mismo.')
    salida['pension_final_estimada'] = round(garantizada, 2)
    return _resultado(salida, '02' if es_ley_97 else '08', 'Cumple requisitos; saldo insuficiente, aplica pensión garantizada.')
