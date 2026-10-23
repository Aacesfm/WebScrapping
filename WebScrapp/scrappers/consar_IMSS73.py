"""Scraper autonomo CONSAR IMSS73: registra transicion, no pension Ley97."""

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

RUTA_CONFIGURACION = Path(__file__).resolve().parents[1] / 'config' / 'consar_IMSS73.json'
REGIMEN = 'IMSS73'
LEY = 'LEY_73'
FALTANTE = 'NaN'
COLUMNAS_WEB = [
    'Pension_web', 'pension_con_av_web', 'rcv_proy_web', 'rcv_av_proy_web',
    'sal_cot_web', 'tasa_remplazo_web', 'tasa_rendimiento_web', 'densidad_cot_web',
    'edad_retiro_calculo', 'saldo_inicial_capturado', 'saldo_inicial_incluye_av',
    'saldo_acumulado_web', 'leyenda_regimen_web', 'estado', 'observaciones',
]


class BloqueoConsar(ValueError):
    pass


class TransicionConsar(BloqueoConsar):
    pass


def cargar_configuracion():
    with RUTA_CONFIGURACION.open(encoding='utf-8') as archivo:
        configuracion = json.load(archivo)
    for seccion in ('input', 'output'):
        ruta = Path(configuracion[seccion]['path'])
        if not ruta.is_absolute():
            ruta = RUTA_CONFIGURACION.parent / ruta
        configuracion[seccion]['path'] = str(ruta.resolve())
    if configuracion['form']['afore'] != 'Banamex' or str(configuracion['form']['afore_value']) != '552':
        raise ValueError('Este scraper requiere Banamex (552).')
    if configuracion['form']['include_av_in_initial_balance'] is not False:
        raise ValueError('CONSAR IMSS captura solo saldo_rcv, sin AV.')
    return configuracion


def argumentos_cli(configuracion, argv=None):
    parser = argparse.ArgumentParser(description='CONSAR ' + REGIMEN + ', ejecucion independiente.')
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
            raise ValueError('El CSV debe tener id_cliente.')
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
    if cliente.get('regimen_estimado') != REGIMEN or cliente.get('ley_bandera') != LEY:
        raise ValueError('Este scraper requiere {} / {}.'.format(REGIMEN, LEY))
    if cliente.get('genero') not in ('H', 'M'):
        raise ValueError('Genero distinto de H o M.')
    nacimiento = datetime.strptime(cliente.get('f_nacim', ''), '%Y-%m-%d').date()
    hoy = date.today()
    edad = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
    retiro = numero(configuracion['results']['retirement_age'], 'retirement_age')
    if retiro != retiro.to_integral_value() or not 60 <= retiro <= 67:
        raise ValueError('Edad fuera del slider CONSAR (60 a 67).')
    if not 18 <= edad <= retiro:
        raise ValueError('Edad fuera del intervalo de calculo.')
    datos = {'nacimiento': nacimiento, 'edad': edad, 'anio_fil': cliente.get('anio_fil', '')}
    afiliacion = numero(datos['anio_fil'], 'anio_fil')
    if afiliacion != afiliacion.to_integral_value() or not nacimiento.year + 15 <= afiliacion <= hoy.year:
        raise ValueError('Anio de afiliacion invalido.')
    for campo in ('salario_mensual', 'saldo_rcv', 'sem_cot'):
        datos[campo] = numero(cliente.get(campo), campo)
    if datos['salario_mensual'] == 0 or datos['sem_cot'] != datos['sem_cot'].to_integral_value():
        raise ValueError('Salario positivo y semanas enteras requeridos.')
    if configuracion['form']['include_av_in_initial_balance'] is not False:
        raise ValueError('CONSAR IMSS captura solo saldo_rcv, sin AV.')
    datos['saldo_inicial'] = datos['saldo_rcv']
    return datos


def esperar(driver, limite):
    restante = limite - time.monotonic()
    if restante <= 0:
        raise TimeoutException('Tiempo agotado.')
    return WebDriverWait(driver, restante)


def esperar_ajax(driver, limite):
    esperar(driver, limite).until(lambda navegador: navegador.execute_script('''
        return jQuery.active === 0 && !(window.Sys && Sys.Net &&
            Sys.Net.WebRequestManager.get_activeWebRequests &&
            Sys.Net.WebRequestManager.get_activeWebRequests().length);
    '''))


def cifra(texto):
    limpio = str(texto).replace('$', '').replace(',', '').replace('%', '').replace('*', '').strip()
    return limpio if re.fullmatch(r'\d+(?:\.\d+)?', limpio) else FALTANTE


def texto_visible(driver, selector):
    return ' '.join(elemento.text.strip() for elemento in driver.find_elements(By.CSS_SELECTOR, selector)
        if elemento.is_displayed() and elemento.text.strip())


def comprobar_rechazo(driver):
    leyenda = texto_visible(driver, '#msgGenracionTransicion')
    notificacion = texto_visible(driver, 'section.notify[data-notify="error"]')
    if not leyenda and re.search(r'(?:Ley|Social)\s*73', notificacion, re.IGNORECASE):
        leyenda = notificacion
    if leyenda:
        raise TransicionConsar(leyenda)
    mensaje = notificacion or texto_visible(driver,
        '.notifyjs-bootstrap-error, .notifyjs-bootstrap-warn, .modal.show .modal-body, #lMensajeError')
    if mensaje:
        raise BloqueoConsar('CONSAR: ' + ' '.join(mensaje.split()))


def verificar_numero(driver, identificador, valor):
    capturado = driver.find_element(By.ID, identificador).get_attribute('value')
    if cifra(capturado) == FALTANTE or Decimal(cifra(capturado)) != Decimal(str(valor)):
        raise BloqueoConsar('La pagina ajusto {}: {} (CSV: {}).'.format(identificador, capturado, valor))


def escribir(driver, identificador, valor, limite):
    esperar(driver, limite).until(lambda navegador: navegador.find_element(By.ID, identificador))
    driver.execute_script('jQuery(arguments[0]).val(arguments[1]).trigger("input").trigger("change").trigger("blur");',
        '#' + identificador, str(valor))
    esperar_ajax(driver, limite)
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
        jQuery('#cboAfore').val('552').trigger('change');
    ''')
    esperar(driver, limite).until(lambda navegador:
        cifra(navegador.find_element(By.ID, 'txtComisionAfore').get_attribute('value')) != FALTANTE)
    esperar_peticiones(driver, limite)
    driver.execute_script('jQuery(arguments[0]).trigger("click");',
        '#chkMujer' if cliente['genero'] == 'M' else '#chkHombre')
    fecha = datos['nacimiento'].strftime('%d/%m/%Y')
    driver.execute_script('jQuery("#txtFechaNacimiento").val(arguments[0]).trigger("input").trigger("change").trigger("blur");', fecha)
    esperar(driver, limite).until(lambda navegador:
        cifra(navegador.find_element(By.ID, 'txtEdad').get_attribute('value')) == str(datos['edad']))
    esperar_peticiones(driver, limite)
    escribir(driver, 'txtAnioAfiliacion', datos['anio_fil'], limite)
    esperar_peticiones(driver, limite)
    for identificador, valor in (
        ('txtSalarioBaseCotizacion', datos['salario_mensual']),
        ('txtSaldoActualAfore', datos['saldo_inicial']),
        ('txtRendimientoReralAntesComisiones', 4),
    ):
        escribir(driver, identificador, valor, limite)
        esperar_peticiones(driver, limite)
    retiro = configuracion['results']['retirement_age']
    driver.execute_script('''
        var slider = jQuery('#slider-txtEdadRetiro');
        slider.slider('value', arguments[0]);
        var slide = slider.slider('option', 'slide');
        if (slide) { slide.call(slider[0], jQuery.Event('slide'), {value: arguments[0]}); }
    ''', retiro)
    esperar_peticiones(driver, limite)
    escribir(driver, 'txtSemanasCotizadas', datos['sem_cot'], limite)
    esperar_peticiones(driver, limite)
    for identificador, valor in (
        ('txtAnioAfiliacion', datos['anio_fil']), ('txtSemanasCotizadas', datos['sem_cot']),
        ('txtSalarioBaseCotizacion', datos['salario_mensual']), ('txtSaldoActualAfore', datos['saldo_inicial']),
        ('txtRendimientoReralAntesComisiones', 4), ('txtEdadRetiro', retiro), ('txtEdad', datos['edad']),
    ):
        verificar_numero(driver, identificador, valor)
    if driver.find_element(By.ID, 'txtFechaNacimiento').get_attribute('value') != fecha:
        raise BloqueoConsar('La fecha capturada no coincide con el CSV.')
    if driver.find_element(By.ID, 'cboAfore').get_attribute('value') != '552':
        raise BloqueoConsar('La Afore no es Banamex (552).')
    boton = driver.find_element(By.ID, 'Image1')
    driver.execute_script('arguments[0].scrollIntoView({block:"center"});', boton)
    boton.click()


def esperar_peticiones(driver, limite):
    esperar_ajax(driver, limite)
    esperar(driver, limite).until(lambda navegador: navegador.execute_script(
        'return window.__consarPendientes === 0;'))


def extraer_resultados(driver, limite):
    def aviso_o_resultado(navegador):
        comprobar_rechazo(navegador)
        if texto_visible(navegador, '#lblPensionMensualEstimada, #lblPensionMensualEstimadaFPB2'):
            raise BloqueoConsar('No se observo aviso Ley73; el motor IMSS97 no acredita una pension Ley73.')
        return False
    esperar(driver, limite).until(aviso_o_resultado)


def procesar_cliente(driver, cliente, configuracion):
    registro = dict(cliente)
    registro.update({columna: FALTANTE for columna in COLUMNAS_WEB})
    registro['nombre_completo'] = ' '.join(cliente.get(campo, '').strip() for campo in
        ('nombre', 'ap_paterno', 'ap_materno') if cliente.get(campo, '').strip())
    registro['id_checkpoint'] = cliente['id_cliente']
    registro['edad_retiro_calculo'] = configuracion['results']['retirement_age']
    registro['saldo_inicial_incluye_av'] = 0
    limite = time.monotonic() + configuracion['execution']['max_seconds_per_client']
    try:
        datos = preparar_datos(cliente, configuracion)
        registro['saldo_inicial_capturado'] = str(datos['saldo_inicial'])
        completar_formulario(driver, cliente, datos, configuracion, limite)
        extraer_resultados(driver, limite)
        raise BloqueoConsar('No se observo aviso Ley73; no se publica pension del motor Ley97.')
    except TransicionConsar as error:
        registro.update(estado='TRANSICION', leyenda_regimen_web=str(error),
            observaciones='TRANSICION | aviso Ley73 | ' + str(error))
    except BloqueoConsar as error:
        registro.update(estado='BLOQUEADO', observaciones='BLOQUEADO | ' + str(error))
    except (ValueError, KeyError) as error:
        registro.update(estado='DATO INVALIDO', observaciones='DATO INVALIDO | ' + str(error))
    except TimeoutException as error:
        diagnostico = texto_visible(driver, '.notifyjs-wrapper, #msgGenracionTransicion') if driver else ''
        registro.update(estado='TIMEOUT', observaciones='TIMEOUT | ' + (diagnostico or str(error)[:300]))
    except WebDriverException as error:
        registro.update(estado='ERROR', observaciones='ERROR | ' + type(error).__name__ + ' | ' + str(error)[:300])
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
        raise ValueError('No se encontraron clientes ' + REGIMEN)
    ruta = Path(configuracion['output']['path'])
    guardados = ids_guardados(ruta, columnas, configuracion)
    if not guardados.issubset({cliente['id_cliente'] for cliente in clientes}):
        raise ValueError('Salida con IDs fuera de la muestra seleccionada.')
    pendientes = [cliente for cliente in clientes if cliente['id_cliente'] not in guardados]
    if not pendientes:
        print('[CONSAR {}] No hay clientes pendientes.'.format(REGIMEN), flush=True)
        return
    driver = None
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        cabecera = not ruta.exists() or ruta.stat().st_size == 0
        with ruta.open('a', encoding=configuracion['output']['encoding'], newline='') as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=columnas)
            if cabecera:
                escritor.writeheader()
            for cliente in pendientes:
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
                print('[CONSAR {}] {} | {}'.format(REGIMEN, cliente['id_cliente'], registro['observaciones']), flush=True)
    finally:
        if driver is not None:
            driver.quit()
    print('[CONSAR {}] CSV guardado: {}'.format(REGIMEN, ruta), flush=True)


if __name__ == '__main__':
    main()