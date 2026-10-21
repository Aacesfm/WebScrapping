import csv
import json
import time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


RUTA_CONFIGURACION = (
	Path(__file__).resolve().parents[1]
	/ 'config'
	/ 'profuturo_IMSS97.json'
)
COLUMNAS_RESULTADO = [
	'id_cliente_sintetico',
	'nombre_completo',
	'fecha_nacimiento_enviada',
	'genero_enviado',
	'anios_cotizados_enviados',
	'saldo_afore_enviado',
	'salario_mensual_enviado',
	'ahorro_voluntario_mensual_enviado',
	'estado',
	'url_pagina_siguiente',
]


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
	return configuracion


def leer_clientes(configuracion):
	"""Filtra el CSV y devuelve la muestra solicitada en el JSON."""
	# ==============================================
	# Leer: CSV y seleccionar clientes
	# ==============================================
	entrada = configuracion['input']
	filtros = configuracion['filters']
	campos_positivos = configuracion.get('require_positive_fields', [])
	campos = configuracion['form']['fields']

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
			cumple_campos_positivos = all(
				Decimal(cliente.get(campo, '0')) > 0
				for campo in campos_positivos
			)
			if (cumple_filtros and cumple_campos_positivos
					and all(cliente.get(campo) for campo in campos.values())):
				clientes.append(cliente)
				if len(clientes) >= configuracion['sample_size']:
					break
	return clientes


def redondear(valor, decimales):
	"""Redondea importes y años según el criterio configurado."""
	unidad = Decimal('1').scaleb(-decimales)
	return Decimal(str(valor)).quantize(unidad, rounding=ROUND_HALF_UP)


def ingresar_texto(elemento, valor):
	elemento.send_keys(Keys.COMMAND, 'a')
	elemento.send_keys(str(valor))


def agregar_campo(espera, etiqueta, valor):
	campo = espera.until(
		EC.visibility_of_element_located(
			(By.CSS_SELECTOR, '[aria-label="{}"]'.format(etiqueta))
		)
	)
	ingresar_texto(campo, valor)


def seleccionar_genero(driver, genero, etiquetas, espera):
	etiqueta = etiquetas[genero]
	control = espera.until(
		EC.element_to_be_clickable(
			(By.CSS_SELECTOR, '[role="checkbox"][aria-label="{}"]'.format(etiqueta))
		)
	)
	if control.get_attribute('aria-checked') != 'true':
		control.click()


def completar_formulario(driver, cliente, configuracion):
	"""Llena los campos del cliente y envía la calculadora."""
	navegador = configuracion['browser']
	formulario = configuracion['form']
	espera = WebDriverWait(driver, navegador['timeout_seconds'])
	campos = formulario['fields']
	redondeos = formulario['rounding']

	# ==============================================
	# Abrir: Calculadora de Profuturo
	# ==============================================
	driver.get(navegador['url'])

	# ==============================================
	# Agregar: Nombre
	# ==============================================
	ingresar_texto(
		espera.until(EC.visibility_of_element_located((By.NAME, 'nombre'))),
		cliente[campos['nombre']],
	)

	# ==============================================
	# Agregar: Fecha de nacimiento
	# ==============================================
	fecha = time.strptime(cliente[campos['fecha_nacimiento']], '%Y-%m-%d')
	fecha_texto = time.strftime(formulario['date_input_format'], fecha)
	ingresar_texto(
		espera.until(EC.visibility_of_element_located((By.CSS_SELECTOR, '.dp__input'))),
		fecha_texto,
	)
	control_overlay = espera.until(
		EC.element_to_be_clickable((By.CSS_SELECTOR, '[aria-label="Toggle overlay"]'))
	)
	# Cerramos el calendario para continuar con los demás controles.
	control_overlay.click()
	espera.until(
		lambda navegador_actual: all(
			not elemento.is_displayed()
			for elemento in navegador_actual.find_elements(By.CSS_SELECTOR, '.dp__menu')
		)
	)

	# ==============================================
	# Seleccionar: Género
	# ==============================================
	seleccionar_genero(driver, cliente[campos['genero']], formulario['genero'], espera)

	# ==============================================
	# Agregar: Años que has cotizado
	# ==============================================
	agregar_campo(
		espera,
		'Años que has cotizado',
		redondear(cliente[campos['anios_cotizados']], redondeos['years']),
	)

	# ==============================================
	# Agregar: Saldo actual en Afore
	# ==============================================
	agregar_campo(
		espera,
		'Saldo actual en Afore',
		redondear(cliente[campos['saldo_actual_afore']], redondeos['currency']),
	)

	# ==============================================
	# Agregar: Salario mensual
	# ==============================================
	agregar_campo(
		espera,
		'Salario mensual',
		redondear(cliente[campos['salario_mensual']], redondeos['currency']),
	)

	# ==============================================
	# Agregar: Ahorro voluntario mensual
	# ==============================================
	agregar_campo(
		espera,
		'Ahorro voluntario mensual',
		redondear(
			cliente[campos['ahorro_voluntario_mensual']], redondeos['currency']
		),
	)

	# ==============================================
	# Click: Calcular mi pensión
	# ==============================================
	espera.until(
		EC.element_to_be_clickable(
			(By.XPATH, "//button[contains(., 'Calcular mi pensión')]")
		)
	).click()

	# ==============================================
	# Esperar: Carga de la página siguiente y detenerse
	# ==============================================
	WebDriverWait(driver, navegador['result_wait_seconds']).until(
		lambda navegador_actual: '/retiro-resumen' in navegador_actual.current_url
	)
	return driver.current_url


def procesar_cliente(driver, cliente, configuracion):
	navegador = configuracion['browser']
	campos = configuracion['form']['fields']
	url_siguiente = completar_formulario(driver, cliente, configuracion)
	redondeos = configuracion['form']['rounding']
	return {
		'id_cliente_sintetico': cliente['id_cliente_sintetico'],
		'nombre_completo': cliente[campos['nombre']],
		'fecha_nacimiento_enviada': cliente[campos['fecha_nacimiento']],
		'genero_enviado': cliente[campos['genero']],
		'anios_cotizados_enviados': redondear(
			cliente[campos['anios_cotizados']], redondeos['years']
		),
		'saldo_afore_enviado': redondear(
			cliente[campos['saldo_actual_afore']], redondeos['currency']
		),
		'salario_mensual_enviado': redondear(
			cliente[campos['salario_mensual']], redondeos['currency']
		),
		'ahorro_voluntario_mensual_enviado': redondear(
			cliente[campos['ahorro_voluntario_mensual']], redondeos['currency']
		),
		'estado': 'calculado',
		'url_pagina_siguiente': url_siguiente,
	}


def guardar_resultados(resultados, configuracion):
	# ==============================================
	# Guardar: Registro de datos enviados y estado
	# ==============================================
	salida = configuracion['output']
	ruta_salida = Path(salida['path'])
	if ruta_salida.exists() and not configuracion['overwrite_output']:
		raise FileExistsError(
			'El archivo de salida ya existe y overwrite_output está desactivado: '
			+ str(ruta_salida)
		)

	ruta_salida.parent.mkdir(parents=True, exist_ok=True)
	with ruta_salida.open('w', encoding=salida['encoding'], newline='') as archivo:
		escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS_RESULTADO)
		escritor.writeheader()
		escritor.writerows(resultados)


def main():
	# ==============================================
	# Iniciar: Leer configuración y muestra
	# ==============================================
	configuracion = cargar_configuracion()
	clientes = leer_clientes(configuracion)
	if not clientes:
		raise ValueError('No se encontraron clientes que cumplan los filtros configurados.')

	# ==============================================
	# Abrir: Navegador para completar el formulario
	# ==============================================
	opciones = webdriver.ChromeOptions()
	if configuracion['browser']['headless']:
		opciones.add_argument('--headless=new')
	if configuracion['browser'].get('leave_browser_open', False):
		opciones.add_experimental_option('detach', True)
	driver = webdriver.Chrome(options=opciones)
	resultados = []
	preservar_navegador = False
	try:
		for indice, cliente in enumerate(clientes):
			try:
				# ==============================================
				# Procesar: Enviar un cliente y detenerse al avanzar
				# ==============================================
				print(
					'Procesando cliente {} de {}: {}'.format(
						indice + 1, len(clientes), cliente['id_cliente_sintetico']
					)
				)
				registro = procesar_cliente(driver, cliente, configuracion)
				resultados.append(registro)
				preservar_navegador = configuracion['browser'].get(
					'leave_browser_open', False
				)
				print('Página siguiente cargada; se detiene este cliente.')
				break
			except Exception as error:
				resultados.append({
					'id_cliente_sintetico': cliente['id_cliente_sintetico'],
					'nombre_completo': cliente.get('nombre_completo', ''),
					'estado': 'error',
					'url_pagina_siguiente': '',
				})
				print('Error con el cliente {}: {}'.format(
					cliente['id_cliente_sintetico'], error
				))
			time.sleep(configuracion['browser']['pause_between_records_seconds'])
	finally:
		if not preservar_navegador:
			# ==============================================
			# Cerrar: Navegador si no se alcanzó la página siguiente
			# ==============================================
			driver.quit()

	guardar_resultados(resultados, configuracion)
	print('Resultados guardados en: {}'.format(configuracion['output']['path']))


if __name__ == '__main__':
	main()
