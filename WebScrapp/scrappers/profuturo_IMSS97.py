import csv
import json
import os
import re
import sys
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
	/ 'profuturo_IMSS97.json'
)
ENTORNO_PROYECTO = Path(__file__).resolve().parents[2] / '.venv-py388'
ETIQUETA = 'PROFUTURO IMSS97'
TEXTO_ULTIMO_SALARIO = 'Último salario cotizado'

# Columna de salida -> patrón sobre el texto visible de la pantalla de resultados.
PATRONES_WEB = {
	'Pension_web': r'Pensión mensual\s*\$([\d,.]+)\s*Sin ahorro voluntario',
	'pension_con_av_web': r'Pensión mensual\s*\$([\d,.]+)\s*Con ahorro voluntario',
	'rcv_proy_web': r'Sin ahorro voluntario\s*\$([\d,.]+)\s*Total acumulado',
	'rcv_av_proy_web': r'Con ahorro voluntario\s*\$([\d,.]+)\s*Total acumulado',
	'sal_cot_web': r'Último salario cotizado\s*\$([\d,.]+)',
	'tasa_remplazo_web': r'Tasa de reemplazo\s*([\d.]+)\s*%',
	'tasa_rendimiento_web': r'Tasa de Rendimiento\s*(?:\d\s+)?([\d.]+)\s*%',
	'densidad_cot_web': r'Densidad de cotización\s*(?:\d\s+)?([\d.]+)\s*%',
}
COLUMNAS_WEB = list(PATRONES_WEB) + ['edad_retiro_calculo', 'observaciones']
CAMPO_CHECKPOINT = 'id_checkpoint'


def informar(mensaje):
	print('[{}] {}'.format(ETIQUETA, mensaje), flush=True)


def resumir(texto, limite=70):
	texto = ' '.join(str(texto).split())
	return texto if len(texto) <= limite else texto[:limite - 3] + '...'


def validar_entorno():
	if sys.version_info[:3] != (3, 8, 8) or Path(sys.prefix).resolve() != ENTORNO_PROYECTO.resolve():
		raise RuntimeError('Ejecute con el entorno virtual compartido: {}'.format(
			ENTORNO_PROYECTO / 'bin' / 'python'))


def cargar_configuracion():
	"""Carga la configuración y resuelve sus rutas relativas."""
	# ==============================================
	# Cargar: Configuración y rutas
	# ==============================================
	with RUTA_CONFIGURACION.open(encoding='utf-8') as archivo:
		configuracion = json.load(archivo)

	directorio_configuracion = RUTA_CONFIGURACION.parent
	for clave in ('input', 'output'):
		ruta = Path(configuracion[clave]['path'])
		if not ruta.is_absolute():
			configuracion[clave]['path'] = str(
				(directorio_configuracion / ruta).resolve()
			)
	ruta_checkpoint = Path(configuracion['checkpoint']['path'])
	if not ruta_checkpoint.is_absolute():
		configuracion['checkpoint']['path'] = str(
			(directorio_configuracion / ruta_checkpoint).resolve()
		)
	return configuracion


def leer_clientes(configuracion):
	"""Filtra el CSV y devuelve hasta el máximo de clientes configurado."""
	# ==============================================
	# Leer: CSV y seleccionar clientes
	# ==============================================
	entrada = configuracion['input']
	filtros = configuracion['filters']
	campos = configuracion['form']['fields']
	max_clientes = configuracion['execution']['max_clients']

	with open(entrada['path'], encoding=entrada['encoding'], newline='') as archivo:
		lector = csv.DictReader(archivo)
		clientes = []
		for cliente in lector:
			cumple_filtros = all(
				cliente.get(campo) in valores
				if isinstance(valores, list)
				else cliente.get(campo) == valores
				for campo, valores in filtros.items()
			)
			campos_requeridos = [
				campo
				for mapeo in campos.values()
				for campo in (mapeo if isinstance(mapeo, list) else [mapeo])
			]
			if (cumple_filtros
					and all(cliente.get(campo) not in (None, '') for campo in campos_requeridos)):
				clientes.append(cliente)
				if len(clientes) >= max_clientes:
					break
	return clientes


def obtener_valor(cliente, mapeo):
	if isinstance(mapeo, list):
		return ' '.join(cliente[campo].strip() for campo in mapeo if cliente[campo].strip())
	return cliente[mapeo]


def segundos_restantes(limite):
	restantes = limite - time.monotonic()
	if restantes <= 0:
		raise TimeoutException('Se agotó el tiempo máximo para este cliente.')
	return restantes


def esperar(driver, limite):
	return WebDriverWait(driver, segundos_restantes(limite))


def redondear(valor, decimales):
	"""Redondea importes y años según el criterio configurado."""
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


def seleccionar_genero(driver, genero, etiquetas, limite):
	etiqueta = etiquetas[genero]
	control = esperar(driver, limite).until(
		EC.element_to_be_clickable(
			(By.CSS_SELECTOR, '[role="checkbox"][aria-label="{}"]'.format(etiqueta))
		)
	)
	if control.get_attribute('aria-checked') != 'true':
		control.click()


def completar_formulario(driver, cliente, configuracion, limite):
	"""Llena los campos del cliente y envía la calculadora."""
	navegador = configuracion['browser']
	formulario = configuracion['form']
	campos = formulario['fields']
	redondeos = formulario['rounding']

	# ==============================================
	# Abrir: Calculadora de Profuturo
	# ==============================================
	driver.set_page_load_timeout(segundos_restantes(limite))
	driver.get(navegador['url'])

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
	ingresar_texto(
		esperar(driver, limite).until(
			EC.visibility_of_element_located((By.CSS_SELECTOR, '.dp__input'))
		),
		fecha_texto,
	)
	# Confirmamos la fecha al salir del campo y esperamos el valor interno del formulario.
	driver.find_element(By.CSS_SELECTOR, '.dp__input').send_keys(Keys.TAB)
	esperar(driver, limite).until(
		lambda navegador_actual: bool(
			navegador_actual.find_element(By.NAME, 'edad').get_attribute('value')
		)
	)

	# ==============================================
	# Seleccionar: Género
	# ==============================================
	seleccionar_genero(
		driver, cliente[campos['genero']], formulario['genero'], limite
	)

	# ==============================================
	# Agregar: Años que has cotizado
	# ==============================================
	agregar_campo(
		driver,
		limite,
		'Años que has cotizado',
		redondear(cliente[campos['anios_cotizados']], redondeos['years']),
	)

	# ==============================================
	# Agregar: Saldo actual en Afore
	# ==============================================
	agregar_campo(
		driver,
		limite,
		'Saldo actual en Afore',
		redondear(cliente[campos['saldo_actual_afore']], redondeos['currency']),
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
	# Agregar: Ahorro voluntario mensual
	# ==============================================
	agregar_campo(
		driver,
		limite,
		'Ahorro voluntario mensual',
		redondear(
			cliente[campos['ahorro_voluntario_mensual']], redondeos['currency']
		),
	)

	# ==============================================
	# Click: Calcular mi pensión
	# ==============================================
	esperar(driver, limite).until(
		EC.element_to_be_clickable(
			(By.XPATH, "//button[contains(., 'Calcular mi pensión')]")
		)
	).click()

	# ==============================================
	# Esperar: Carga de la página siguiente y detenerse
	# ==============================================
	esperar(driver, limite).until(
		lambda navegador_actual: '/retiro-resumen' in navegador_actual.current_url
	)
	return driver.current_url


def hay_pop_visible(driver):
	return any(
		pop.is_displayed()
		for pop in driver.find_elements(By.CSS_SELECTOR, '.swal2-popup')
	)


def texto_pantalla(driver):
	return driver.find_element(By.TAG_NAME, 'body').text


def clasificar_pop(texto, observaciones):
	if 'Negativa de pensión:' in texto:
		return observaciones['pop_negativa_pension']
	if 'Pensión mínima garantizada:' in texto:
		return observaciones['pop_pension_garantizada']
	return observaciones['pop_desconocido']


def extraer_datos_web(driver, valor_faltante):
	"""Lee las cifras visibles; lo que no aparezca se guarda como valor faltante."""
	texto = texto_pantalla(driver)
	datos = {}
	for columna, patron in PATRONES_WEB.items():
		coincidencia = re.search(patron, texto)
		datos[columna] = (
			coincidencia.group(1).replace(',', '') if coincidencia else valor_faltante
		)
	return datos


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
			raise ValueError(
				'La salida existente no tiene la columna del checkpoint; '
				'use un archivo de salida nuevo.'
			)
		return {fila[id_checkpoint] for fila in lector if fila.get(id_checkpoint)}


def guardar_checkpoint(configuracion, checkpoint_id, procesados):
	checkpoint = configuracion['checkpoint']
	ruta = Path(checkpoint['path'])
	ruta.parent.mkdir(parents=True, exist_ok=True)
	temporal = ruta.with_suffix(ruta.suffix + '.tmp')
	estado = {
		'checkpoint_id': checkpoint_id,
		'id_field': checkpoint['id_field'],
		'processed_count': procesados,
		'input_path': configuracion['input']['path'],
	}
	with temporal.open('w', encoding='utf-8') as archivo:
		json.dump(estado, archivo, ensure_ascii=False, indent=2)
		archivo.flush()
		os.fsync(archivo.fileno())
	temporal.replace(ruta)


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

	ultimo_id = chunk[-1][CAMPO_CHECKPOINT]
	guardados = cargar_ids_guardados(ruta, CAMPO_CHECKPOINT)
	guardar_checkpoint(configuracion, ultimo_id, len(guardados))


def procesar_pantalla_resultados(driver, configuracion, limite):
	"""Atiende el pop si aparece y extrae los datos; devuelve (datos, observación)."""
	observaciones = configuracion['observaciones']

	# ==============================================
	# Esperar: Pop de pensión garantizada o resultados directos
	# ==============================================
	esperar(driver, limite).until(
		lambda d: hay_pop_visible(d) or TEXTO_ULTIMO_SALARIO in texto_pantalla(d)
	)

	# ==============================================
	# Click: Ok en el pop (solo si apareció)
	# ==============================================
	observacion = observaciones['normal']
	if hay_pop_visible(driver):
		texto_pop = driver.find_element(By.CSS_SELECTOR, '.swal2-popup').text
		observacion = clasificar_pop(texto_pop, observaciones)
		esperar(driver, limite).until(
			EC.element_to_be_clickable((By.CSS_SELECTOR, '.swal2-confirm'))
		).click()
		esperar(driver, limite).until(
			lambda d: not hay_pop_visible(d)
		)

	# ==============================================
	# Extraer: Pensión, totales acumulados y tasas
	# ==============================================
	esperar(driver, limite).until(
		lambda d: TEXTO_ULTIMO_SALARIO in texto_pantalla(d)
	)
	return extraer_datos_web(driver, configuracion['missing_value']), observacion


def procesar_cliente(driver, cliente, configuracion):
	"""Devuelve el registro de entrada más los resultados web y la observación."""
	faltante = configuracion['missing_value']
	registro = dict(cliente)
	campos = configuracion['form']['fields']
	registro['nombre_completo'] = obtener_valor(cliente, campos['nombre'])
	registro.update({columna: faltante for columna in PATRONES_WEB})
	registro['edad_retiro_calculo'] = configuracion['results']['retirement_age']
	registro['observaciones'] = faltante
	registro[CAMPO_CHECKPOINT] = cliente[configuracion['checkpoint']['id_field']]
	limite = time.monotonic() + configuracion['execution']['max_seconds_per_client']
	try:
		completar_formulario(driver, cliente, configuracion, limite)
		datos, observacion = procesar_pantalla_resultados(driver, configuracion, limite)
		registro.update(datos)
		registro['observaciones'] = observacion
	except TimeoutException:
		registro['observaciones'] = configuracion['observaciones']['timeout'].format(
			segundos=configuracion['execution']['max_seconds_per_client']
		)
	except Exception as error:
		registro['observaciones'] = configuracion['observaciones']['error'].format(
			tipo=type(error).__name__, mensaje=resumir(error) or 'Sin detalle'
		)
	finally:
		try:
			driver.execute_script('window.stop();')
		except Exception:
			pass
	return registro


def main():
	validar_entorno()
	# ==============================================
	# Iniciar: Leer configuración y muestra
	# ==============================================
	configuracion = cargar_configuracion()
	clientes = leer_clientes(configuracion)
	if not clientes:
		raise ValueError('No se encontraron clientes que cumplan los filtros configurados.')

	ruta_salida = Path(configuracion['output']['path'])
	ruta_estado = Path(configuracion['checkpoint']['path'])
	if ruta_estado.exists():
		with ruta_estado.open(encoding='utf-8') as archivo:
			estado_checkpoint = json.load(archivo)
		if estado_checkpoint.get('input_path') != configuracion['input']['path']:
			raise ValueError('El checkpoint pertenece a otro archivo de entrada.')
	if ruta_salida.exists() and not configuracion['execution']['resume']:
		raise FileExistsError('La salida existe y la reanudación está desactivada.')
	if ruta_estado.exists() and not ruta_salida.exists():
		raise FileNotFoundError('Existe un checkpoint, pero no se encuentra su CSV de salida.')

	ids_guardados = cargar_ids_guardados(
		ruta_salida, configuracion['checkpoint']['id_field']
	) if ruta_salida.exists() else set()
	pendientes = [
		cliente for cliente in clientes
		if cliente[configuracion['checkpoint']['id_field']] not in ids_guardados
	]
	if not pendientes:
		informar('Todos los clientes configurados ya estan procesados.')
		return

	columnas = columnas_salida(list(clientes[0].keys()))
	if ruta_salida.exists():
		with ruta_salida.open(encoding='utf-8-sig', newline='') as archivo:
			columnas_existentes = csv.reader(archivo).__next__()
		if columnas_existentes != columnas:
			raise ValueError('El esquema de la salida existente no coincide con el CSV actual.')

	# ==============================================
	# Abrir: Navegador para completar el formulario
	# ==============================================
	opciones = webdriver.ChromeOptions()
	if configuracion['browser']['headless']:
		opciones.add_argument('--headless=new')
	driver = webdriver.Chrome(options=opciones)
	chunk = []
	tamano_chunk = configuracion['execution']['chunk_size']
	try:
		for indice, cliente in enumerate(pendientes, start=len(ids_guardados)):
			# ==============================================
			# Procesar: Un cliente completo
			# ==============================================
			registro = procesar_cliente(driver, cliente, configuracion)
			chunk.append(registro)
			informar('{}/{} | {} | {}'.format(
				indice + 1, len(clientes), registro[CAMPO_CHECKPOINT], registro['observaciones']
			))
			if len(chunk) >= tamano_chunk:
				guardar_chunk(chunk, columnas, configuracion)
				ids_guardados.update(
					fila[CAMPO_CHECKPOINT] for fila in chunk
				)
				chunk = []
			if configuracion['browser']['pause_between_records_seconds'] > 0:
				time.sleep(configuracion['browser']['pause_between_records_seconds'])
		if chunk:
			guardar_chunk(chunk, columnas, configuracion)
	finally:
		# ==============================================
		# Cerrar: Navegador
		# ==============================================
		driver.quit()

	informar('CSV guardado: {}'.format(configuracion['output']['path']))


if __name__ == '__main__':
	main()
