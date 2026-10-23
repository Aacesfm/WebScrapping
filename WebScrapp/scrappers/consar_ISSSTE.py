"""Scraper autonomo de la calculadora CONSAR ISSSTE Cuenta Individual."""

import argparse
import csv
import json
import os
import re
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

RUTA_CONFIGURACION = Path(__file__).resolve().parents[1] / 'config' / 'consar_ISSSTE.json'
FALTANTE = 'NaN'
COLUMNAS_WEB = [
    'Pension_web', 'pension_con_av_web', 'rcv_proy_web', 'rcv_av_proy_web',
    'sal_cot_web', 'tasa_remplazo_web', 'tasa_rendimiento_web', 'densidad_cot_web',
    'edad_retiro_calculo', 'observaciones', 'saldo_inicial_capturado',
    'saldo_inicial_incluye_av', 'saldo_acumulado_web', 'bono_capturado',
    'porcentaje_ahorro_solidario_capturado',
    'anio_afiliacion_capturado', 'afiliacion_estimada',
]


class BloqueoConsar(ValueError):
    pass


def cargar_configuracion():
    with RUTA_CONFIGURACION.open(encoding='utf-8') as archivo:
        configuracion = json.load(archivo)
    for seccion in ('input', 'output'):
        ruta = Path(configuracion[seccion]['path'])
        if not ruta.is_absolute():
            ruta = RUTA_CONFIGURACION.parent / ruta
        configuracion[seccion]['path'] = str(ruta.resolve())
    if type(configuracion['form']['include_av_in_initial_balance']) is not bool:
        raise ValueError('include_av_in_initial_balance debe ser true o false.')
    if str(configuracion['form']['afore_value']) != '552':
        raise ValueError('Este scraper utiliza Banamex (552).')
    return configuracion


def argumentos_cli(configuracion, argv=None):
    parser = argparse.ArgumentParser(description='CONSAR ISSSTE, ejecucion independiente.')
    parser.add_argument('--input', type=Path, default=Path(configuracion['input']['path']))
    parser.add_argument('--output', type=Path, default=Path(configuracion['output']['path']))
    parser.add_argument('--max-clientes', type=int, default=configuracion['execution']['max_clients'])
    parser.add_argument('--timeout', type=int, default=configuracion['execution']['max_seconds_per_client'])
    parser.add_argument('--headless', action='store_true', default=configuracion['browser']['headless'])
    argumentos = parser.parse_args(argv)
    if argumentos.max_clientes < 1 or argumentos.timeout < 1:
        parser.error('Maximo y timeout deben ser positivos.')
    entrada = argumentos.input.expanduser().resolve()
    salida = argumentos.output.expanduser().resolve()
    if entrada == salida:
        parser.error('La salida no puede ser el archivo de entrada.')
    configuracion['input']['path'] = str(entrada)
    configuracion['output']['path'] = str(salida)
    configuracion['execution'].update(max_clients=argumentos.max_clientes,
        max_seconds_per_client=argumentos.timeout)
    configuracion['browser']['headless'] = argumentos.headless
    return configuracion


def leer_clientes(configuracion):
    with open(configuracion['input']['path'], encoding=configuracion['input']['encoding'], newline='') as archivo:
        lector = csv.DictReader(archivo)
        columnas = list(lector.fieldnames or [])
        if 'id_cliente' not in columnas:
            raise ValueError('El CSV debe tener cabecera con id_cliente.')
        clientes, identidades = [], set()
        for cliente in lector:
            if not all(cliente.get(campo) == valor for campo, valor in configuracion['filters'].items()):
                continue
            identidad = cliente.get('id_cliente', '').strip()
            if not identidad or identidad in identidades:
                raise ValueError('id_cliente vacio o duplicado.')
            identidades.add(identidad)
            clientes.append(cliente)
            if len(clientes) >= configuracion['execution']['max_clients']:
                break
    for columna in ['nombre_completo'] + COLUMNAS_WEB + ['id_checkpoint']:
        if columna not in columnas:
            columnas.append(columna)
    return clientes, columnas


def numero(valor, campo):
    try:
        resultado = Decimal(str(valor))
    except InvalidOperation:
        raise ValueError('Dato no numerico en {}.'.format(campo))
    if not resultado.is_finite() or resultado < 0:
        raise ValueError('Dato negativo o no finito en {}.'.format(campo))
    return resultado


def preparar_datos(cliente, configuracion):
    if cliente.get('regimen_estimado') != 'ISSSTE' or cliente.get('ley_bandera') != 'LEY_ISSSTE':
        raise ValueError('Este scraper solo calcula ISSSTE Cuenta Individual.')
    if cliente.get('genero') not in ('H', 'M'):
        raise ValueError('Genero distinto de H o M.')
    nacimiento = datetime.strptime(cliente.get('f_nacim', ''), '%Y-%m-%d').date()
    hoy = date.today()
    edad = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
    retiro = numero(configuracion['results']['retirement_age'], 'retirement_age')
    if retiro != retiro.to_integral_value() or not 65 <= retiro <= 67:
        raise ValueError('Edad de retiro entera entre 65 y 67 (slider CONSAR).')
    if not 18 <= edad <= retiro:
        raise ValueError('Edad fuera del intervalo de calculo.')
    datos = {'nacimiento': nacimiento, 'edad': edad}
    for campo in ('salario_mensual', 'saldo_rcv', 'anios_cotizados',
                  'saldo_bono_pension', 'porcentaje_ahorro_solidario'):
        datos[campo] = numero(cliente.get(campo), campo)
    if datos['salario_mensual'] == 0:
        raise ValueError('El salario mensual debe ser positivo.')
    if datos['anios_cotizados'] != datos['anios_cotizados'].to_integral_value():
        raise ValueError('Los anios cotizados deben ser enteros.')
    if datos['porcentaje_ahorro_solidario'] not in (0, 1, 2):
        raise ValueError('El porcentaje solidario debe ser 0, 1 o 2%.')
    datos['saldo_inicial'] = datos['saldo_rcv']
    if configuracion['form']['include_av_in_initial_balance']:
        datos['saldo_inicial'] += numero(cliente.get('saldo_av'), 'saldo_av')
    datos['afiliacion_estimada'] = not str(cliente.get('anio_fil') or '').strip()
    if datos['afiliacion_estimada']:
        inicio = configuracion['form'].get('missing_affiliation_start_age')
        if inicio is None:
            raise BloqueoConsar('Falta anio_fil: configure missing_affiliation_start_age o complete el CSV.')
        inicio = numero(inicio, 'missing_affiliation_start_age')
        if inicio != inicio.to_integral_value() or inicio < 15:
            raise ValueError('La edad de inicio debe ser entera y al menos 15.')
        afiliacion = Decimal(nacimiento.year) + inicio
    else:
        afiliacion = numero(cliente['anio_fil'], 'anio_fil')
    if afiliacion != afiliacion.to_integral_value() or not nacimiento.year + 15 <= afiliacion <= hoy.year:
        raise ValueError('Anio de afiliacion invalido.')
    datos['anio_fil'] = afiliacion
    return datos


def esperar(driver, limite):
    restante = limite - time.monotonic()
    if restante <= 0:
        raise TimeoutException()
    return WebDriverWait(driver, restante)


def cifra(texto):
    limpio = str(texto).replace('$', '').replace(',', '').replace('%', '').replace('*', '').strip()
    return limpio if re.fullmatch(r'\d+(?:\.\d+)?', limpio) else FALTANTE


def texto_visible(driver, selector):
    return ' '.join(elemento.text.strip() for elemento in driver.find_elements(By.CSS_SELECTOR, selector)
        if elemento.is_displayed() and elemento.text.strip())


def comprobar_rechazo(driver):
    mensaje = texto_visible(driver, 'section.notify[data-notify="error"], .notifyjs-bootstrap-error, .notifyjs-bootstrap-warn, .modal.show .modal-body, #lMensajeError')
    if mensaje:
        raise BloqueoConsar('CONSAR: ' + ' '.join(mensaje.split())[:240])


def esperar_peticiones(driver, limite):
    esperar(driver, limite).until(lambda navegador: navegador.execute_script(
        'return jQuery.active === 0 && window.__consarPendientes === 0;'))


def verificar_numero(driver, identificador, valor):
    capturado = driver.find_element(By.ID, identificador).get_attribute('value')
    if cifra(capturado) == FALTANTE or Decimal(cifra(capturado)) != Decimal(str(valor)):
        raise BloqueoConsar('La pagina ajusto {}: {} (CSV: {}).'.format(identificador, capturado, valor))


def escribir(driver, identificador, valor, limite):
    esperar(driver, limite).until(lambda navegador: navegador.find_element(By.ID, identificador))
    driver.execute_script('jQuery(arguments[0]).val(arguments[1]).trigger("input").trigger("change").trigger("blur");',
        '#' + identificador, str(valor))
    esperar_peticiones(driver, limite)
    verificar_numero(driver, identificador, valor)


def completar_formulario(driver, cliente, datos, configuracion, limite):
    driver.set_page_load_timeout(max(1, limite - time.monotonic()))
    driver.get(configuracion['browser']['url'])
    esperar(driver, limite).until(lambda navegador: navegador.execute_script(
        'return typeof jQuery === "function" && jQuery("#cboAfore option[value=552]").length > 0;'))
    driver.execute_script('''
        window.__consarPendientes = 0;
        Sys.Net.WebRequestManager.add_invokingRequest(function () { window.__consarPendientes++; });
        Sys.Net.WebRequestManager.add_completedRequest(function () { window.__consarPendientes--; });
        jQuery('#cboAfore').val(arguments[0]).trigger('change');
    ''',
        str(configuracion['form']['afore_value']))
    esperar(driver, limite).until(lambda navegador:
        cifra(navegador.find_element(By.ID, 'txtComisionAfore').get_attribute('value')) != FALTANTE)
    esperar_peticiones(driver, limite)
    genero = '#chkMujer' if cliente['genero'] == 'M' else '#chkHombre'
    driver.execute_script('jQuery(arguments[0]).trigger("click");', genero)
    fecha = datos['nacimiento'].strftime('%d/%m/%Y')
    driver.execute_script('jQuery("#txtFechaNacimiento").val(arguments[0]).trigger("input").trigger("change").trigger("blur");', fecha)
    esperar(driver, limite).until(lambda navegador:
        cifra(navegador.find_element(By.ID, 'txtEdad').get_attribute('value')) == str(datos['edad']))
    esperar_peticiones(driver, limite)
    if driver.find_element(By.ID, 'txtFechaNacimiento').get_attribute('value') != fecha:
        raise BloqueoConsar('La fecha capturada no coincide con el CSV.')
    if cifra(driver.find_element(By.ID, 'txtEdad').get_attribute('value')) != str(datos['edad']):
        raise BloqueoConsar('La edad calculada por CONSAR no coincide con la fecha del CSV.')
    for identificador, valor in (
        ('txtAnioAfiliacion', int(datos['anio_fil'])),
        ('txtSalarioBaseCotizacion', datos['salario_mensual']),
        ('txtSaldoActualAfore', datos['saldo_inicial']),
        ('txtBono', datos['saldo_bono_pension']),
    ):
        escribir(driver, identificador, valor, limite)
    radios = {0: '#opPorcentajeCero', 1: '#opPorcentajeUno', 2: '#opPorcentajeDos'}
    driver.execute_script('jQuery(arguments[0]).trigger("click");',
        radios[int(datos['porcentaje_ahorro_solidario'])])
    esperar_peticiones(driver, limite)
    retiro = configuracion['results']['retirement_age']
    driver.execute_script('''
        var slider = jQuery('#slider-txtEdadRetiro');
        var edad = arguments[0];
        slider.slider('value', edad);
        var slide = slider.slider('option', 'slide');
        if (slide) { slide.call(slider[0], jQuery.Event('slide'), {value: edad}); }
    ''', retiro)
    esperar_peticiones(driver, limite)
    escribir(driver, 'txtAniosCotizados', int(datos['anios_cotizados']), limite)
    for identificador, valor in (
        ('txtAnioAfiliacion', datos['anio_fil']), ('txtAniosCotizados', datos['anios_cotizados']),
        ('txtSalarioBaseCotizacion', datos['salario_mensual']),
        ('txtSaldoActualAfore', datos['saldo_inicial']), ('txtBono', datos['saldo_bono_pension']),
    ):
        verificar_numero(driver, identificador, valor)
    if driver.find_element(By.ID, 'cboAfore').get_attribute('value') != '552':
        raise BloqueoConsar('La Afore no es Banamex (552).')
    if not driver.find_element(By.CSS_SELECTOR,
            radios[int(datos['porcentaje_ahorro_solidario'])]).is_selected():
        raise BloqueoConsar('La pagina ajusto el porcentaje de ahorro solidario.')
    if cifra(driver.find_element(By.ID, 'txtEdadRetiro').get_attribute('value')) != str(retiro):
        raise BloqueoConsar('La pagina ajusto la edad de retiro.')
    error = driver.execute_script('return validaAfiliacion();')
    if error:
        raise BloqueoConsar('CONSAR: ' + str(error))
    driver.execute_script('LeerFormulario();')
    bono_aplicado = driver.execute_script('return String(pBono);')
    if Decimal(bono_aplicado) != datos['saldo_bono_pension']:
        raise BloqueoConsar('CONSAR ajusta el bono por fecha de redencion: {}.'.format(bono_aplicado))
    boton = driver.find_element(By.ID, 'Image1')
    driver.execute_script('arguments[0].scrollIntoView({block:"center"});', boton)
    boton.click()


def extraer_resultados(driver, limite):
    selectores = {
        'Pension_web': '#lblPensionMensualEstimada, #lblPensionMensualEstimadaFPB',
        'saldo_acumulado_web': '#lblSaldoAcumulado, #lblSaldoAcumuladoFPB',
        'tasa_remplazo_web': '#lblPorcentajePensionMensual, #lblPorcentajePensionMensualFPB',
    }
    def leer_resultado(navegador, selector):
        for elemento in navegador.find_elements(By.CSS_SELECTOR, selector):
            navegador.execute_script('arguments[0].scrollIntoView({block:"center", inline:"center"});', elemento)
            if elemento.is_displayed() and cifra(elemento.text) != FALTANTE:
                return cifra(elemento.text)
        return FALTANTE

    def listo(navegador):
        comprobar_rechazo(navegador)
        if navegador.execute_script('return typeof sResultados_Calculo !== "undefined" && /^NP(?:[&|]|$)/.test(sResultados_Calculo);'):
            raise BloqueoConsar('CONSAR devolvio negativa de pension (NP).')
        return all(leer_resultado(navegador, selector) != FALTANTE for selector in selectores.values())
    esperar(driver, limite).until(listo)
    return {campo: leer_resultado(driver, selector) for campo, selector in selectores.items()}


def procesar_cliente(driver, cliente, configuracion):
    registro = dict(cliente)
    registro.update({columna: FALTANTE for columna in COLUMNAS_WEB})
    registro['nombre_completo'] = ' '.join(cliente.get(campo, '').strip() for campo in
        ('nombre', 'ap_paterno', 'ap_materno') if cliente.get(campo, '').strip())
    registro['id_checkpoint'] = cliente['id_cliente']
    registro['edad_retiro_calculo'] = configuracion['results']['retirement_age']
    registro['saldo_inicial_incluye_av'] = int(configuracion['form']['include_av_in_initial_balance'])
    limite = time.monotonic() + configuracion['execution']['max_seconds_per_client']
    try:
        datos = preparar_datos(cliente, configuracion)
        registro.update(saldo_inicial_capturado=str(datos['saldo_inicial']),
            anio_afiliacion_capturado=str(datos['anio_fil']),
            afiliacion_estimada=int(datos['afiliacion_estimada']),
            bono_capturado=str(datos['saldo_bono_pension']),
            porcentaje_ahorro_solidario_capturado=str(datos['porcentaje_ahorro_solidario']))
        completar_formulario(driver, cliente, datos, configuracion, limite)
        registro.update(extraer_resultados(driver, limite))
        registro['sal_cot_web'] = cifra(driver.find_element(By.ID, 'txtSalarioBaseCotizacion').get_attribute('value'))
        registro['tasa_rendimiento_web'] = cifra(driver.find_element(By.ID, 'txtRendimientoReralAntesComisiones').get_attribute('value'))
        registro['densidad_cot_web'] = str(driver.execute_script('return pDensidadCotizacion * 100;'))
        completo = all(registro[campo] != FALTANTE for campo in
            ('Pension_web', 'saldo_acumulado_web', 'tasa_remplazo_web'))
        registro['observaciones'] = ('OK' if completo else 'INCOMPLETO') + (
            ' | sin escenario AV mensual; salario_mensual usado como sueldo basico de cotizacion')
        if datos['afiliacion_estimada']:
            registro['observaciones'] += ' | afiliacion estimada: nacimiento + {} anios'.format(
                configuracion['form']['missing_affiliation_start_age'])
    except BloqueoConsar as error:
        registro['observaciones'] = 'BLOQUEADO | ' + str(error)
    except (ValueError, KeyError) as error:
        registro['observaciones'] = 'DATO INVALIDO | ' + str(error)[:240]
    except TimeoutException:
        registro['observaciones'] = 'TIMEOUT | formulario o resultados CONSAR'
    except WebDriverException as error:
        registro['observaciones'] = 'ERROR | ' + type(error).__name__
    return registro


def ids_guardados(ruta, columnas, configuracion):
    if not ruta.exists() or not ruta.stat().st_size:
        return set()
    if not configuracion['execution']['resume']:
        raise FileExistsError('La salida existe; use una ruta nueva o resume=true.')
    with ruta.open(encoding=configuracion['output']['encoding'], newline='') as archivo:
        lector = csv.DictReader(archivo)
        if lector.fieldnames != columnas:
            raise ValueError('El layout de la salida no coincide.')
        identidades = set()
        for fila in lector:
            identidad = fila.get('id_checkpoint')
            if None in fila or any(valor is None for valor in fila.values()) or not identidad or \
                    identidad != fila.get('id_cliente') or identidad in identidades:
                raise ValueError('Salida incompleta o con IDs duplicados.')
            identidades.add(identidad)
        return identidades


def crear_navegador(configuracion):
    opciones = webdriver.ChromeOptions()
    opciones.page_load_strategy = 'eager'
    opciones.add_argument('--window-size=' + configuracion['browser']['window_size'])
    if configuracion['browser']['headless']:
        opciones.add_argument('--headless=new')
    return webdriver.Chrome(options=opciones)


def main(argv=None):
    configuracion = argumentos_cli(cargar_configuracion(), argv)
    clientes, columnas = leer_clientes(configuracion)
    if not clientes:
        raise ValueError('No se encontraron clientes ISSSTE.')
    ruta = Path(configuracion['output']['path'])
    guardados = ids_guardados(ruta, columnas, configuracion)
    if not guardados.issubset({cliente['id_cliente'] for cliente in clientes}):
        raise ValueError('Salida con IDs fuera de la muestra seleccionada.')
    pendientes = [cliente for cliente in clientes if cliente['id_cliente'] not in guardados]
    if not pendientes:
        print('[CONSAR ISSSTE] No hay clientes pendientes.', flush=True)
        return
    driver = None
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        cabecera = not ruta.exists() or ruta.stat().st_size == 0
        with ruta.open('a', encoding=configuracion['output']['encoding'], newline='') as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=columnas)
            if cabecera:
                escritor.writeheader()
            for indice, cliente in enumerate(pendientes, 1):
                try:
                    preparar_datos(cliente, configuracion)
                except (ValueError, KeyError):
                    pass
                else:
                    if driver is None:
                        driver = crear_navegador(configuracion)
                registro = procesar_cliente(driver, cliente, configuracion)
                escritor.writerow(registro)
                archivo.flush()
                os.fsync(archivo.fileno())
                print('[CONSAR ISSSTE] {}/{} | {} | {}'.format(len(guardados) + indice,
                    len(clientes), cliente['id_cliente'], registro['observaciones']), flush=True)
                if driver is not None and indice < len(pendientes):
                    time.sleep(configuracion['browser']['pause_between_records_seconds'])
    finally:
        if driver is not None:
            driver.quit()
    print('[CONSAR ISSSTE] CSV guardado: {}'.format(ruta), flush=True)


if __name__ == '__main__':
    main()