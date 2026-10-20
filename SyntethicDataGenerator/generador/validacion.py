"""Validación independiente de cada registro generado contra las reglas del proyecto."""
import numpy as np
import pandas as pd

import config as cfg
from .pensiones import evaluar, regimen_de
from .utilidades import a_fecha, edad_en

_CAMPOS_COMPARADOS = (
    'tipo_cliente', 'regimen_pensionario', 'eleccion_regimen', 'conservacion_derechos',
    'resultado_pensionario',
)
_CAMPOS_MONETARIOS = (
    'saldo_bono_pension', 'saldo_pensionario_utilizable', 'pension_autofinanciable_estimada',
    'pension_minima_legal_aplicable', 'pension_final_estimada',
)


def _mismo_monto(a, b):
    if pd.isna(a) or pd.isna(b):
        return pd.isna(a) and pd.isna(b)
    return abs(a - b) <= 0.01


def _validar_independiente(r, errores):
    if pd.notna(r['institucion']):
        return
    for campo in ('fecha_primera_cotizacion', 'fecha_ultima_cotizacion', 'NSS', 'salario_base_cotizacion', 'sueldo_basico_issste'):
        if pd.notna(r[campo]):
            errores.append(f'{campo} debe ser nulo en independiente no incorporado')
    for campo in ('semanas_imss', 'anios_issste', 'semanas_cotizadas', 'anios_cotizados', 'saldo_rcv', 'saldo_av', 'saldo_vivienda'):
        if r[campo] != 0:
            errores.append(f'{campo} debe ser 0 en independiente no incorporado')
    if r['regimen_pensionario'] != cfg.NO_APLICA:
        errores.append('régimen debe ser NO_APLICA en independiente no incorporado')


def _validar_cotizante(r, errores):
    nacimiento = a_fecha(r['fecha_nacimiento'])
    primera, ultima = a_fecha(r['fecha_primera_cotizacion']), a_fecha(r['fecha_ultima_cotizacion'])
    dias_periodo = (ultima - primera).days
    semanas, anios = r['semanas_cotizadas'], r['anios_cotizados']
    institucion = r['institucion']

    if edad_en(nacimiento, primera) < cfg.EDAD_LABORAL_MINIMA or r['edad_primera_cotizacion'] != edad_en(nacimiento, primera):
        errores.append('edad de primera cotización inválida')
    if dias_periodo < 0 or (cfg.FECHA_CORTE - ultima).days < cfg.DIAS_MIN_BAJA:
        errores.append('fechas de cotización incompatibles con la baja')
    if semanas * 7 > dias_periodo or anios > dias_periodo / cfg.DIAS_POR_ANIO + 0.005:
        errores.append('tiempo cotizado excede el periodo disponible')
    if abs(semanas - anios * cfg.SEMANAS_POR_ANIO) >= 1.5:  # Truncado a semanas y redondeo a 2 decimales.
        errores.append('semanas y años cotizados no coinciden')
    if r['estatus_laboral'] != 'BAJA':
        errores.append('estatus laboral debe ser BAJA')

    if institucion == cfg.INSTITUCION_IMSS:
        if pd.isna(r['NSS']) or len(str(r['NSS'])) != 11:
            errores.append('NSS IMSS ausente o inválido')
        if r['semanas_imss'] != semanas or r['anios_issste'] != 0 or pd.notna(r['sueldo_basico_issste']):
            errores.append('columnas IMSS/ISSSTE inconsistentes')
        if pd.isna(r['salario_base_cotizacion']) or abs(r['salario_base_cotizacion'] - r['salario_mensual'] / cfg.DIAS_POR_MES) > 0.01:
            errores.append('salario base de cotización inconsistente')
    else:
        if pd.notna(r['NSS']):
            errores.append('NSS debe ser nulo en ISSSTE')
        if r['anios_issste'] != anios or r['semanas_imss'] != 0 or pd.notna(r['salario_base_cotizacion']):
            errores.append('columnas IMSS/ISSSTE inconsistentes')
        if pd.isna(r['sueldo_basico_issste']) or abs(r['sueldo_basico_issste'] - r['salario_mensual']) > 0.01:
            errores.append('sueldo básico ISSSTE inconsistente')

    if r['regimen_pensionario'] != regimen_de(institucion, primera):
        errores.append('régimen no corresponde con la fecha de primera cotización')
    if institucion == cfg.INSTITUCION_ISSSTE and ultima < cfg.FECHA_ISSSTE_2007:
        errores.append('Cuentas Individuales sin cotización posterior a abril de 2007')
    if r['tipo_cliente'] in ('07', '08') and primera >= cfg.FECHA_ISSSTE_2007:
        errores.append('ISSSTE con 25 años no puede haber iniciado desde abril de 2007')
    if r['tipo_cliente'] in ('04', '05') and r['conservacion_derechos'] != 'SI':
        errores.append('Ley 73 con pensión requiere derechos vigentes')

    if r['historial_credito_vivienda'] == 'CREDITO_VIGENTE' and r['saldo_vivienda'] != 0:
        errores.append('crédito vigente con saldo de vivienda')
    if r['historial_credito_vivienda'] == 'SIN_CREDITO' and r['saldo_vivienda'] <= 0:
        errores.append('sin crédito y sin saldo de vivienda')

    tasa_max = max(cfg.AHORRO_VOLUNTARIO[k]['max'] for k in ('tasa_pequena', 'tasa_alta'))
    anios_capitalizacion = (cfg.FECHA_CORTE - primera).days / cfg.DIAS_POR_ANIO
    tope_av = r['salario_mensual'] * 12 * anios * tasa_max * (1 + cfg.RENDIMIENTO_RCV['max']) ** anios_capitalizacion
    if r['saldo_av'] > tope_av + 0.01:
        errores.append('saldo AV excede la capacidad de ahorro')

    recalculo = evaluar({**r, 'bono_potencial': r['saldo_bono_pension']})
    for campo in _CAMPOS_COMPARADOS:
        if recalculo[campo] != r[campo]:
            errores.append(f'{campo} no coincide con las reglas ({r[campo]} vs {recalculo[campo]})')
    for campo in _CAMPOS_MONETARIOS:
        if not _mismo_monto(recalculo[campo], r[campo]):
            errores.append(f'{campo} no coincide con las reglas')


def validar_registro(r):
    """Devuelve la lista de incumplimientos del registro (vacía si todo es correcto)."""
    errores = []
    nacimiento = a_fecha(r['fecha_nacimiento'])
    if r['edad'] != edad_en(nacimiento, cfg.FECHA_CORTE):
        errores.append('edad no coincide con la fecha de nacimiento')
    if r['genero'] not in ('H', 'M'):
        errores.append('género debe ser H o M')
    for campo in ('saldo_rcv', 'saldo_av', 'saldo_vivienda', 'saldo_bono_pension', 'saldo_pensionario_utilizable'):
        if r[campo] < 0:
            errores.append(f'{campo} negativo')
    if r['salario_mensual'] < cfg.SALARIO_MINIMO_DIARIO * cfg.DIAS_POR_MES:
        errores.append('salario inferior al mínimo')
    if r['resolucion_simulada'] is not True and r['resolucion_simulada'] is not np.True_:
        errores.append('la resolución debe identificarse como simulada')
    if r['resultado_pensionario'] != cfg.RESULTADOS_POR_TIPO.get(r['tipo_cliente']):
        errores.append('resultado no corresponde al tipo de cliente')

    curp = str(r['CURP'])
    if (len(curp) != 18 or curp[4:10] != nacimiento.strftime('%y%m%d') or curp[10] != r['genero']
            or str(r['RFC'])[:10] != curp[:10]):
        errores.append('CURP/RFC incoherentes con los datos demográficos')

    if pd.isna(r['institucion']):
        _validar_independiente(r, errores)
    else:
        _validar_cotizante(r, errores)
    return errores


def validar_dataframe(df):
    """Serie con 'OK' o la lista de incumplimientos por cliente."""
    resultados = []
    for registro in df.to_dict('records'):
        errores = validar_registro(registro)
        resultados.append('OK' if not errores else '; '.join(errores))
    return pd.Series(resultados, index=df.index)
