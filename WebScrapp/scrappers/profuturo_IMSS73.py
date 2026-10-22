import csv
import json
import os
import re
import time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


RUTA_CONFIGURACION = (
    Path(__file__).resolve().parents[1]
    / 'config'
    / 'profuturo_IMSS73.json'
)
TEXTO_ULTIMO_SALARIO = 'Último salario cotizado'
CAMPO_CHECKPOINT = 'id_checkpoint'

PATRONES_WEB = {
    'Pension_web': r'Pensión mensual\s*\$([\d,.]+)\s*Retirandote a los {retirement_age} años',
    'pension_con_av_web': r'Pensión mensual\s*\$([\d,.]+)\s*Con ahorro voluntario',
    'rcv_proy_web': r'Sin ahorro voluntario\s*\$([\d,.]+)\s*Total acumulado',
    'rcv_av_proy_web': r'Con ahorro voluntario\s*\$([\d,.]+)\s*Total acumulado',
    'sal_cot_web': r'Último salario cotizado\s*\$([\d,.]+)',
    'tasa_remplazo_web': r'Tasa de reemplazo\s*([\d.]+)\s*%',
    'tasa_rendimiento_web': r'Tasa de Rendimiento\s*(?:\d\s+)?([\d.]+)\s*%',
    'densidad_cot_web': r'Densidad de cotización\s*(?:\d\s+)?([\d.]+)\s*%',
}
COLUMNAS_WEB = list(PATRONES_WEB) + ['edad_retiro_calculo', 'observaciones']


def cargar_configuracion():
    with RUTA_CONFIGURACION.open(encoding='utf-8') as archivo:
        configuracion = json.load(archivo)
    directorio_configuracion = RUTA_CONFIGURACION.parent
    for clave in ('input', 'output', 'checkpoint'):
        ruta = Path(configuracion[clave]['path'])
        if not ruta.is_absolute():
            configuracion[clave]['path'] = str(
                (directorio_configuracion / ruta).resolve()
            )
    return configuracion


def obtener_valor(cliente, mapeo):
    if isinstance(mapeo, list):
        return ' '.join(
            cliente[campo].strip() for campo in mapeo if cliente[campo].strip()
        )
    return cliente[mapeo]


def leer_clientes(configuracion):
    entrada = configuracion['input']
    filtros = configuracion['filters']
    campos = configuracion['form']['fields']
    execution = configuracion['execution']
    ids_muestra = set(execution.get('sample_ids', []))
    campos_requeridos = [
        campo
        for mapeo in campos.values()
        for campo in (mapeo if isinstance(mapeo, list) else [mapeo])
        if campo is not None
    ]

    with open(entrada['path'], encoding=entrada['encoding'], newline='') as archivo:
        clientes = []
        for cliente in csv.DictReader(archivo):
            if not all(
                cliente.get(campo) in valores
                if isinstance(valores, list)
                else cliente.get(campo) == valores
                for campo, valores in filtros.items()
            ):
                continue
            if ids_muestra and cliente.get(configuracion['checkpoint']['id_field']) not in ids_muestra:
                continue
            if not all(cliente.get(campo) not in (None, '') for campo in campos_requeridos):
                continue
            clientes.append(cliente)
            if len(clientes) >= execution['max_clients']:
                break
    return clientes


def segundos_restantes(limite):
    restantes = limite - time.monotonic()
    if restantes <= 0:
        raise TimeoutException('Se agotó el tiempo máximo para este cliente.')
    return restantes


def esperar(driver, limite):
    return WebDriverWait(driver, segundos_restantes(limite))


def redondear(valor, decimales):
    unidad = Decimal('1').scaleb(-decimales)
    return Decimal(str(valor)).quantize(unidad, rounding=ROUND_HALF_UP)


def ingresar_texto(elemento, valor):
    elemento.send_keys(Keys.COMMAND, 'a')
    elemento.send_keys(str(valor))


def agregar_campo(driver, limite, etiqueta, valor):
    campo = esperar(driver, limite).until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, '[aria-label="{}"]'.format(etiqueta))
        )
    )
    ingresar_texto(campo, valor)


def completar_formulario(driver, cliente, configuracion, limite):
    navegador = configuracion['browser']
    formulario = configuracion['form']
    campos = formulario['fields']
    redondeos = formulario['rounding']

    # ==============================================
    # Abrir: Calculadora y seleccionar Ley 73
    # ==============================================
    driver.set_page_load_timeout(segundos_restantes(limite))
    driver.get(navegador['url'])
    ley = esperar(driver, limite).until(
        EC.element_to_be_clickable((
            By.CSS_SELECTOR,
            '[role="checkbox"][aria-label="{}"]'.format(formulario['ley_checkbox']),
        ))
    )
    if ley.get_attribute('aria-checked') != 'true':
        ley.click()

    # ==============================================
    # Agregar: Nombre
    # ==============================================
    ingresar_texto(
        esperar(driver, limite).until(
            EC.visibility_of_element_located((By.NAME, 'nombre'))
        ),
        obtener_valor(cliente, campos['nombre']),
    )

    # ==============================================
    # Agregar: Fecha de nacimiento
    # ==============================================
    fecha = time.strptime(cliente[campos['fecha_nacimiento']], '%Y-%m-%d')
    fecha_texto = time.strftime(formulario['date_input_format'], fecha)
    fecha_input = esperar(driver, limite).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, '.dp__input'))
    )
    ingresar_texto(fecha_input, fecha_texto)
    fecha_input.send_keys(Keys.TAB)
    esperar(driver, limite).until(
        lambda actual: bool(actual.find_element(By.NAME, 'edad').get_attribute('value'))
    )

    # ==============================================
    # Agregar: Años cotizados
    # ==============================================
    agregar_campo(
        driver,
        limite,
        'Años que has cotizado',
        redondear(cliente[campos['anios_cotizados']], redondeos['years']),
    )

    # ==============================================
    # Agregar: Salario mensual
    # ==============================================
    agregar_campo(
        driver,
        limite,
        'Salario mensual',
        redondear(cliente[campos['salario_mensual']], redondeos['currency']),
    )

    # ==============================================
    # Click: Calcular mi pensión y esperar la página siguiente
    # ==============================================
    esperar(driver, limite).until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(., 'Calcular mi pensión')]")
        )
    ).click()
    esperar(driver, limite).until(
        lambda actual: '/retiro-resumen' in actual.current_url
    )


def hay_pop_visible(driver):
    return any(
        popup.is_displayed()
        for popup in driver.find_elements(By.CSS_SELECTOR, '.swal2-popup')
    )


def texto_pantalla(driver):
    return driver.find_element(By.TAG_NAME, 'body').text


def clasificar_pop(texto, observaciones):
    if 'Negativa de pensión:' in texto:
        return observaciones['pop_negativa_pension']
    if 'Pensión mínima garantizada:' in texto:
        return observaciones['pop_pension_garantizada']
    return observaciones['pop_desconocido']


def extraer_datos_web(driver, valor_faltante, edad_retiro):
    texto = texto_pantalla(driver)
    datos = {}
    for columna, patron in PATRONES_WEB.items():
        if '{retirement_age}' in patron:
            patron = patron.format(retirement_age=edad_retiro)
        coincidencia = re.search(patron, texto)
        datos[columna] = (
            coincidencia.group(1).replace(',', '') if coincidencia else valor_faltante
        )
    return datos


def procesar_resultados(driver, configuracion, limite):
    observaciones = configuracion['observaciones']
    esperar(driver, limite).until(
        lambda actual: hay_pop_visible(actual)
        or TEXTO_ULTIMO_SALARIO in texto_pantalla(actual)
    )
    observacion = observaciones['normal']
    if hay_pop_visible(driver):
        texto_pop = driver.find_element(By.CSS_SELECTOR, '.swal2-popup').text
        print('Popup detectado: {}'.format(texto_pop))
        observacion = clasificar_pop(texto_pop, observaciones)
        esperar(driver, limite).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, '.swal2-confirm'))
        ).click()
        esperar(driver, limite).until(lambda actual: not hay_pop_visible(actual))
	
    esperar(driver, limite).until(
        lambda actual: TEXTO_ULTIMO_SALARIO in texto_pantalla(actual)
    )
    return extraer_datos_web(
        driver,
        configuracion['missing_value'],
        configuracion['results']['retirement_age'],
    ), observacion


def columnas_salida(columnas_entrada):
    columnas = list(columnas_entrada)
    for columna in ('nombre_completo',) + tuple(COLUMNAS_WEB) + (CAMPO_CHECKPOINT,):
        if columna not in columnas:
            columnas.append(columna)
    return columnas


def cargar_ids_guardados(ruta_salida, id_checkpoint):
    if not ruta_salida.exists():
        return set()
    with ruta_salida.open(encoding='utf-8-sig', newline='') as archivo:
        lector = csv.DictReader(archivo)
        if id_checkpoint not in (lector.fieldnames or []):
            raise ValueError('La salida existente no contiene el ID de checkpoint.')
        return {fila[id_checkpoint] for fila in lector if fila.get(id_checkpoint)}


def guardar_chunk(chunk, columnas, configuracion):
    if not chunk:
        return
    ruta = Path(configuracion['output']['path'])
    ruta.parent.mkdir(parents=True, exist_ok=True)
    escribir_cabecera = not ruta.exists() or ruta.stat().st_size == 0
    with ruta.open('a', encoding=configuracion['output']['encoding'], newline='') as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas, extrasaction='ignore')
        if escribir_cabecera:
            escritor.writeheader()
        escritor.writerows(chunk)
        archivo.flush()
        os.fsync(archivo.fileno())

    with Path(configuracion['output']['path']).open(
        encoding='utf-8-sig', newline=''
    ) as archivo:
        procesados = sum(1 for _ in csv.DictReader(archivo))
    checkpoint = configuracion['checkpoint']
    estado = {
        'checkpoint_id': chunk[-1][CAMPO_CHECKPOINT],
        'id_field': checkpoint['id_field'],
        'processed_count': procesados,
        'input_path': configuracion['input']['path'],
    }
    ruta_checkpoint = Path(checkpoint['path'])
    temporal = ruta_checkpoint.with_suffix(ruta_checkpoint.suffix + '.tmp')
    ruta_checkpoint.parent.mkdir(parents=True, exist_ok=True)
    with temporal.open('w', encoding='utf-8') as archivo:
        json.dump(estado, archivo, ensure_ascii=False, indent=2)
        archivo.flush()
        os.fsync(archivo.fileno())
    temporal.replace(ruta_checkpoint)


def procesar_cliente(driver, cliente, configuracion):
    campos = configuracion['form']['fields']
    faltante = configuracion['missing_value']
    registro = dict(cliente)
    registro['nombre_completo'] = obtener_valor(cliente, campos['nombre'])
    registro.update({columna: faltante for columna in PATRONES_WEB})
    registro['edad_retiro_calculo'] = configuracion['results']['retirement_age']
    registro['observaciones'] = faltante
    registro[CAMPO_CHECKPOINT] = cliente[configuracion['checkpoint']['id_field']]
    limite = time.monotonic() + configuracion['execution']['max_seconds_per_client']
    try:
        completar_formulario(driver, cliente, configuracion, limite)
        datos, observacion = procesar_resultados(driver, configuracion, limite)
        registro.update(datos)
        registro['observaciones'] = observacion
    except TimeoutException:
        registro['observaciones'] = configuracion['observaciones']['timeout'].format(
            segundos=configuracion['execution']['max_seconds_per_client']
        )
    except Exception as error:
        registro['observaciones'] = configuracion['observaciones']['error'].format(
            tipo=type(error).__name__, mensaje=str(error).strip() or 'Sin detalle'
        )
        print('Error con el cliente {}: {}'.format(
            cliente[configuracion['checkpoint']['id_field']], error
        ))
    finally:
        try:
            driver.execute_script('window.stop();')
        except Exception:
            pass
    return registro


def main():
    configuracion = cargar_configuracion()
    clientes = leer_clientes(configuracion)
    if not clientes:
        raise ValueError('No se encontraron clientes IMSS Ley 73 para procesar.')

    ruta_salida = Path(configuracion['output']['path'])
    ruta_checkpoint = Path(configuracion['checkpoint']['path'])
    if ruta_checkpoint.exists():
        with ruta_checkpoint.open(encoding='utf-8') as archivo:
            estado = json.load(archivo)
        if estado.get('input_path') != configuracion['input']['path']:
            raise ValueError('El checkpoint pertenece a otro archivo de entrada.')
    if ruta_checkpoint.exists() and not ruta_salida.exists():
        raise FileNotFoundError('Existe checkpoint pero no su CSV de salida.')
    if ruta_salida.exists() and not configuracion['execution']['resume']:
        raise FileExistsError('La salida existe y la reanudación está desactivada.')

    ids_guardados = cargar_ids_guardados(
        ruta_salida, configuracion['checkpoint']['id_field']
    ) if ruta_salida.exists() else set()
    pendientes = [
        cliente for cliente in clientes
        if cliente[configuracion['checkpoint']['id_field']] not in ids_guardados
    ]
    if not pendientes:
        print('Todos los clientes IMSS Ley 73 configurados ya están procesados.')
        return

    columnas = columnas_salida(list(clientes[0].keys()))
    if ruta_salida.exists():
        with ruta_salida.open(encoding='utf-8-sig', newline='') as archivo:
            columnas_existentes = next(csv.reader(archivo))
        if columnas_existentes != columnas:
            raise ValueError('El esquema del CSV existente no coincide con el input Ley 73.')

    opciones = webdriver.ChromeOptions()
    if configuracion['browser']['headless']:
        opciones.add_argument('--headless=new')
    driver = webdriver.Chrome(options=opciones)
    chunk = []
    tamano_chunk = configuracion['execution']['chunk_size']
    try:
        for indice, cliente in enumerate(pendientes, start=len(ids_guardados) + 1):
            print('Procesando cliente {} de {}: {}'.format(
                indice, len(clientes), cliente[configuracion['checkpoint']['id_field']]
            ))
            chunk.append(procesar_cliente(driver, cliente, configuracion))
            if len(chunk) >= tamano_chunk:
                guardar_chunk(chunk, columnas, configuracion)
                print('Checkpoint guardado: {}'.format(chunk[-1][CAMPO_CHECKPOINT]))
                chunk = []
            if configuracion['browser']['pause_between_records_seconds'] > 0:
                time.sleep(configuracion['browser']['pause_between_records_seconds'])
        if chunk:
            guardar_chunk(chunk, columnas, configuracion)
            print('Checkpoint guardado: {}'.format(chunk[-1][CAMPO_CHECKPOINT]))
    finally:
        driver.quit()

    print('Procesamiento Ley 73 terminado. CSV: {}'.format(ruta_salida))


if __name__ == '__main__':
    main()
