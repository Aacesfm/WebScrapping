"""Construcción de la población sintética: historiales laborales por perfil, saldos e identificadores."""
import math
from datetime import timedelta

import numpy as np
import pandas as pd

import config as cfg
from .finanzas import simular_ahorro_voluntario_mensual, simular_saldos
from .identificadores import codigo_entidad, generar_correo, generar_curp, generar_nss, generar_num_issste, generar_rfc
from .pensiones import evaluar, regimen_de
from .utilidades import edad_en, normal_truncada, repartir_por_proporcion
from .validacion import validar_dataframe


def _sortear_nacimiento(rng, perfil):
    """Devuelve (fecha de nacimiento, edad cumplida) dentro del rango de edad del perfil."""
    edad_aprox = normal_truncada(rng, perfil['edad'])
    nacimiento = cfg.FECHA_CORTE - timedelta(days=round(edad_aprox * cfg.DIAS_POR_ANIO))
    return nacimiento, edad_en(nacimiento, cfg.FECHA_CORTE)


def _registro_base(genero, nacimiento, edad, salario):
    return {
        'genero': genero, 'fecha_nacimiento': nacimiento, 'edad': edad,
        'salario_mensual': round(salario, 2),
        'institucion': None, 'estatus_laboral': 'INDEPENDIENTE',
        'fecha_primera_cotizacion': None, 'edad_primera_cotizacion': None,
        'fecha_ultima_cotizacion': None, 'semanas_cotizadas': 0, 'anios_cotizados': 0.0,
        'semanas_imss': 0, 'anios_issste': 0.0,
        'salario_base_cotizacion': None, 'sueldo_basico_issste': None,
        'saldo_rcv': 0.0, 'saldo_av': 0.0, 'saldo_vivienda': 0.0,
        'saldo_ahorro_solidario': 0.0, 'porcentaje_ahorro_solidario': None,
        'historial_credito_vivienda': cfg.NO_APLICA, 'bono_potencial': 0.0,
        'beneficiarios': None, 'modalidad_pension': None,
    }


def _generar_independiente(rng, genero, perfil):
    nacimiento, edad = _sortear_nacimiento(rng, perfil)
    salario = normal_truncada(rng, perfil.get('salario', cfg.SALARIO_MENSUAL))
    return _registro_base(genero, nacimiento, edad, salario)


def _generar_cotizante(rng, tipo, genero, perfil):
    """Genera un historial y lo acepta sólo si las reglas lo clasifican en `tipo`."""
    institucion = perfil['institucion']
    ventana = perfil.get('primera_cotizacion', {})
    limite_ultima = cfg.FECHA_CORTE - timedelta(days=cfg.DIAS_MIN_BAJA)

    for _ in range(cfg.MAX_INTENTOS_POR_CLIENTE):
        nacimiento, edad = _sortear_nacimiento(rng, perfil)
        if not perfil['edad']['min'] <= edad <= perfil['edad']['max']:
            continue
        edad_aprox_primera = normal_truncada(rng, perfil['edad_primera_cotizacion'])
        primera = nacimiento + timedelta(days=round(edad_aprox_primera * cfg.DIAS_POR_ANIO))
        edad_primera = edad_en(nacimiento, primera)
        if edad_primera < cfg.EDAD_LABORAL_MINIMA:
            continue
        if ('desde' in ventana and primera < ventana['desde']) or ('antes_de' in ventana and primera >= ventana['antes_de']):
            continue

        densidad = normal_truncada(rng, cfg.DENSIDAD_COTIZACION[institucion])
        max_dias_disponibles = max(0, int((limite_ultima - primera).days * densidad))
        if institucion == cfg.INSTITUCION_IMSS:
            semanas_objetivo = int(normal_truncada(rng, perfil['semanas']))
            dias_efectivos = semanas_objetivo * 7 + int(rng.integers(0, 7))
            if edad < cfg.EDAD_MINIMA_PENSION:
                dias_efectivos = min(dias_efectivos, max_dias_disponibles)
        else:
            dias_efectivos = math.ceil(normal_truncada(rng, perfil['anios']) * cfg.DIAS_POR_ANIO)
            if edad < cfg.EDAD_MINIMA_PENSION:
                dias_efectivos = min(dias_efectivos, max_dias_disponibles)
        ultima = primera + timedelta(days=round(dias_efectivos / densidad))
        if ultima > limite_ultima:
            continue
        if institucion == cfg.INSTITUCION_ISSSTE and ultima < cfg.FECHA_ISSSTE_2007:
            continue  # Cuentas Individuales exige cotización posterior a su entrada en vigor.

        salario = round(normal_truncada(rng, perfil.get('salario', cfg.SALARIO_MENSUAL)), 2)
        regimen = regimen_de(institucion, primera)
        registro = _registro_base(genero, nacimiento, edad, salario)
        registro.update(
            institucion=institucion, estatus_laboral='BAJA',
            fecha_primera_cotizacion=primera, edad_primera_cotizacion=edad_primera,
            fecha_ultima_cotizacion=ultima,
            semanas_cotizadas=dias_efectivos // 7, anios_cotizados=round(dias_efectivos / cfg.DIAS_POR_ANIO, 2),
            **simular_saldos(rng, regimen, salario, primera, ultima, densidad),
        )
        if institucion == cfg.INSTITUCION_IMSS:
            registro.update(semanas_imss=registro['semanas_cotizadas'], salario_base_cotizacion=round(salario / cfg.DIAS_POR_MES, 2))
        else:
            registro.update(anios_issste=registro['anios_cotizados'], sueldo_basico_issste=salario)
            parametros_ahorro = cfg.AHORRO_SOLIDARIO_ISSSTE
            porcentaje = float(rng.uniform(parametros_ahorro['porcentaje_min'], parametros_ahorro['porcentaje_max']))
            registro.update(
                porcentaje_ahorro_solidario=porcentaje,
                saldo_ahorro_solidario=round(registro['saldo_rcv'] * porcentaje / 100, 2),
            )
        if regimen != cfg.REGIMEN_LEY_73:
            registro.update(
                beneficiarios='SI' if rng.random() < cfg.PROB_BENEFICIARIOS else 'NO',
                modalidad_pension=str(rng.choice(list(cfg.MODALIDADES), p=list(cfg.MODALIDADES.values()))),
            )

        resultado = evaluar(registro)
        if resultado['tipo_cliente'] == tipo or resultado['tipo_cliente'] in ('11', '12', '13'):
            registro.update(resultado)
            return registro
    raise RuntimeError(
        f'No se pudo generar un cliente tipo {tipo} en {cfg.MAX_INTENTOS_POR_CLIENTE:,} intentos. '
        'Revise la compatibilidad de los parámetros del perfil en config.'
    )


def _identificadores(rng, df):
    curps, rfcs, nsss, numeros_issste = [], [], [], []
    nsss_usados = set()
    numeros_issste_usados = set()
    for fila in df.itertuples():
        curp = generar_curp(fila.nombre, fila.apellido_paterno, fila.apellido_materno,
                            fila.fecha_nacimiento, fila.genero, fila.estado_nacimiento)
        curps.append(curp)
        rfcs.append(generar_rfc(curp, rng))
        if fila.institucion == cfg.INSTITUCION_IMSS:
            nss = generar_nss(rng, fila.fecha_primera_cotizacion.year, fila.fecha_nacimiento.year)
            while nss in nsss_usados:
                nss = generar_nss(rng, fila.fecha_primera_cotizacion.year, fila.fecha_nacimiento.year)
            nsss_usados.add(nss)
            nsss.append(nss)
            numeros_issste.append(None)
        elif fila.institucion == cfg.INSTITUCION_ISSSTE:
            numero = generar_num_issste(rng, fila.fecha_primera_cotizacion.year, fila.fecha_nacimiento.year)
            while numero in numeros_issste_usados:
                numero = generar_num_issste(rng, fila.fecha_primera_cotizacion.year, fila.fecha_nacimiento.year)
            numeros_issste_usados.add(numero)
            nsss.append(None)
            numeros_issste.append(numero)
        else:
            nsss.append(None)
            numeros_issste.append(None)
    return curps, rfcs, nsss, numeros_issste


def generar_clientes(rng, nombres, apellidos):
    """Devuelve un DataFrame con `cfg.N_CLIN` clientes, una fila por cliente, ya validados."""
    n = cfg.N_CLIN
    conteos = repartir_por_proporcion(n, {t: p['proporcion'] for t, p in cfg.PERFILES.items()})
    tipos = rng.permutation(np.repeat(list(conteos), list(conteos.values())))
    generos = np.where(rng.random(n) < cfg.PROPORCION_MUJERES, 'M', 'H')

    registros = []
    for tipo, genero in zip(tipos, generos):
        perfil = cfg.PERFILES[tipo]
        if perfil['institucion'] is None:
            registro = _generar_independiente(rng, genero, perfil)
            registro.update(evaluar(registro))
        else:
            registro = _generar_cotizante(rng, tipo, genero, perfil)
        registros.append(registro)
    df = pd.DataFrame(registros)

    nombres_por_genero = {
        cfg.GENEROS_ARCHIVO[g]: grupo['nombre'].to_numpy() for g, grupo in nombres.groupby('genero')
    }
    apellidos_disponibles = apellidos['apellido'].to_numpy()
    estados = np.array(cfg.ESTADOS_MEXICO)
    estado_nacimiento = rng.choice(estados, size=n)
    reside_igual = rng.random(n) < cfg.PROB_RESIDE_EN_ESTADO_NACIMIENTO

    df['id_cliente_sintetico'] = np.arange(1, n + 1)
    df['nombre'] = [rng.choice(nombres_por_genero[g]) for g in df['genero']]
    df['apellido_paterno'] = rng.choice(apellidos_disponibles, size=n)
    df['apellido_materno'] = rng.choice(apellidos_disponibles, size=n)
    df['nombre_completo'] = df['nombre'] + ' ' + df['apellido_paterno'] + ' ' + df['apellido_materno']
    df['estado_nacimiento'] = estado_nacimiento
    df['estado_residencia'] = np.where(reside_igual, estado_nacimiento, rng.choice(estados, size=n))

    for columna in ('fecha_nacimiento', 'fecha_primera_cotizacion', 'fecha_ultima_cotizacion'):
        df[columna] = pd.to_datetime(df[columna])
    df['edad_primera_cotizacion'] = df['edad_primera_cotizacion'].astype('Int64')
    df['CURP'], df['RFC'], df['NSS'], df['num_issste'] = _identificadores(rng, df)
    correos_usados = set()
    df['correo'] = [
        generar_correo(rng, fila.nombre, fila.apellido_paterno, fila.apellido_materno,
                       fila.fecha_nacimiento, correos_usados)
        for fila in df.itertuples()
    ]
    # Sorteamos al final para conservar los datos previos con la misma semilla.
    df['ahorro_voluntario_mensual'] = [
        simular_ahorro_voluntario_mensual(rng) if tiene_cuenta else 0.0
        for tiene_cuenta in df['institucion'].notna()
    ]
    df['resolucion_simulada'] = True
    df['validacion_reglas'] = validar_dataframe(df)
    invalidos = df[df['validacion_reglas'] != 'OK']
    if not invalidos.empty:
        muestra = invalidos[['id_cliente_sintetico', 'validacion_reglas']].head()
        raise ValueError(f'{len(invalidos)} registros incumplen reglas:\n{muestra}')

    codigos_entidad = df['estado_nacimiento'].map(codigo_entidad)
    regimenes = df['regimen_pensionario'].map({
        cfg.REGIMEN_LEY_97: 'IMSS97',
        cfg.REGIMEN_LEY_73: 'IMSS73',
        cfg.REGIMEN_ISSSTE: 'ISSSTE',
        cfg.NO_APLICA: cfg.NO_APLICA,
    })
    leyes = df['regimen_pensionario'].map({
        cfg.REGIMEN_LEY_97: 'LEY_97',
        cfg.REGIMEN_LEY_73: 'LEY_73',
        cfg.REGIMEN_ISSSTE: 'LEY_ISSSTE',
        cfg.NO_APLICA: cfg.NO_APLICA,
    })
    df['id_cliente'] = df['id_cliente_sintetico']
    df['ap_paterno'] = df['apellido_paterno']
    df['ap_materno'] = df['apellido_materno']
    df['age'] = df['edad']
    df['f_nacim'] = df['fecha_nacimiento']
    df['entidad'] = codigos_entidad
    df['nss'] = df['NSS']
    df['curp'] = df['CURP']
    df['anios_cotizados'] = np.floor(df['anios_cotizados']).astype(int)
    df['anio_fil'] = pd.to_datetime(df['fecha_primera_cotizacion']).dt.year.astype('Int64')
    df['sem_cot'] = df['semanas_cotizadas']
    df['av_mensual'] = df['ahorro_voluntario_mensual']
    df['regimen_estimado'] = regimenes
    df['ley_bandera'] = leyes
    df['escenario_estimado'] = df['resultado_pensionario']
    return df[cfg.COLUMNAS_SALIDA]
