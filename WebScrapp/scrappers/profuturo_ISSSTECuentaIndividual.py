import argparse
import csv
import json
import re
import time
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


RUTA_CONFIGURACION = (
	Path(__file__).resolve().parents[1]
	/ 'config' / 'profuturo_ISSSTECuentaIndividual.json'
)
ETIQUETAS = {
	'anios_cotizados': 'Años que has cotizado',
	'ahorro_voluntario_mensual': 'Ahorro voluntario',
	'bono_pension': 'Bono de Pensión',
	'saldo_actual_afore': 'Saldo actual en Afore',
	'salario_mensual': 'Salario mensual',
	'edad_retiro': '¿A qué edad te quieres retirar?',
}
PATRONES_WEB = {
	'Pension_web': r'Pensión mensual\s*\$([\d,.]+)\s*Sin ahorro voluntario',
	'pension_con_av_web': r'Pensión mensual\s*\$([\d,.]+)\s*Con ahorro voluntario',
	'rcv_proy_web': r'Sin ahorro voluntario, sin ahorro solidario\s*\$([\d,.]+)\s*Total acumulado',
	'rcv_av_proy_web': r'Con ahorro voluntario\s*\+\s*ahorro solidario\s*\$([\d,.]+)\s*Total acumulado',
	'sal_cot_web': r'Último salario cotizado\s*\$([\d,.]+)',
	'tasa_remplazo_web': r'Tasa de reemplazo\s*([\d.]+)\s*%',
	'tasa_rendimiento_web': r'Tasa de Rendimiento\s*(?:\d\s+)?([\d.]+)\s*%',
	'densidad_cot_web': r'Densidad de cotización\s*(?:\d\s+)?([\d.]+)\s*%',
}
COLUMNAS_RESULTADO = ['nombre_completo'] + list(PATRONES_WEB) + [
	'edad_retiro_calculo', 'incremento_pension_con_ahorro_voluntario_y_solidario',
	'estado_web', 'observaciones',
]


def cargar_configuracion():
	# Leemos el JSON propio de ISSSTE y resolvemos las rutas desde su carpeta.
	with RUTA_CONFIGURACION.open(encoding='utf-8') as archivo:
		configuracion = json.load(archivo)
	for seccion in ('input', 'output'):
		configuracion[seccion]['path'] = str(
			(RUTA_CONFIGURACION.parent / configuracion[seccion]['path']).resolve()
		)
	return configuracion


def leer_clientes(configuracion):
	# Seleccionamos los primeros clientes ISSSTE sin descartar casos incompletos.
	with open(configuracion['input']['path'], newline='',
			  encoding=configuracion['input']['encoding']) as archivo:
		clientes = []
		for cliente in csv.DictReader(archivo):
			if all(cliente.get(campo) == valor
				   for campo, valor in configuracion['filters'].items()):
				clientes.append(cliente)
				if len(clientes) >= configuracion['execution']['max_clients']:
					break
	return clientes


def preparar_datos(cliente, configuracion, exploratorio=False):
	campos = configuracion['form']['fields']
	datos = {}
	avisos = []
	for destino, origen in campos.items():
		if isinstance(origen, list):
			datos[destino] = ' '.join(cliente[campo].strip() for campo in origen)
		else:
			datos[destino] = cliente[origen].strip()
		if not datos[destino]:
			raise ValueError('Falta el campo {}.'.format(destino))
	nacimiento = datetime.strptime(datos['fecha_nacimiento'], '%Y-%m-%d').date()
	hoy = date.today()
	edad = hoy.year - nacimiento.year - (
		(hoy.month, hoy.day) < (nacimiento.month, nacimiento.day)
	)
	if edad < 0:
		raise ValueError('La fecha de nacimiento es futura.')
	if str(edad) != cliente.get('age'):
		avisos.append('Edad CSV distinta de la calculada: {}.'.format(edad))
	manual = configuracion['form']['manual_por_cliente'].get(cliente['id_cliente'], {})
	porcentaje = Decimal(datos.pop('porcentaje_ahorro_solidario'))
	if not porcentaje.is_finite() or not Decimal('1') <= porcentaje <= Decimal('2'):
		raise ValueError('Porcentaje de ahorro solidario fuera del intervalo 1 a 2.')
	if configuracion['form']['rounding']['solidarity_percentage'] != 'half_up':
		raise ValueError('Regla de redondeo solidario no reconocida.')
	# Convertimos el porcentaje decimal del CSV en una opcion admitida: 1 o 2.
	solidario = manual.get('ahorro_solidario', int(
		porcentaje.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
	))
	retiro = configuracion['form']['edad_retiro']
	if isinstance(solidario, bool) or str(solidario) not in ('1', '2'):
		raise ValueError('Ahorro solidario debe ser 1 o 2.')
	retiro_decimal = Decimal(str(retiro))
	if (not retiro_decimal.is_finite() or retiro_decimal != retiro_decimal.to_integral_value()
			or retiro_decimal < 60):
		raise ValueError('Edad de retiro debe ser entera y al menos 60.')
	if edad > retiro_decimal:
		avisos.append('Edad actual {} mayor al retiro configurado {}; se envia sin cambiarla.'.format(
			edad, retiro
		))
	datos['ahorro_solidario'] = str(solidario)
	datos['edad_retiro'] = str(int(retiro_decimal))
	if Decimal(str(solidario)) != porcentaje:
		avisos.append('Porcentaje CSV {} sustituido por {} para esta simulacion.'.format(
			porcentaje, solidario
		))
	if datos['genero'] not in configuracion['form']['genero']:
		raise ValueError('Genero no reconocido.')
	for campo in ETIQUETAS:
		if campo == 'edad_retiro':
			continue
		numero = Decimal(datos[campo])
		if not numero.is_finite() or numero < 0:
			raise ValueError('Importe o tiempo invalido en {}.'.format(campo))
		if campo == 'anios_cotizados' and numero != numero.to_integral_value():
			raise ValueError('Los años cotizados requieren revision manual: no son enteros.')
		datos[campo] = str(numero.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
	return datos, avisos


def esperar(driver, limite):
	restante = limite - time.monotonic()
	if restante <= 0:
		raise TimeoutException('Se agoto el tiempo del cliente.')
	return WebDriverWait(driver, restante)


def escribir(elemento, valor):
	elemento.clear()
	elemento.send_keys(valor)


def completar_formulario(driver, datos, configuracion, limite):
	# Abrimos la calculadora y elegimos ISSSTE antes de localizar sus campos.
	driver.set_page_load_timeout(max(1, limite - time.monotonic()))
	driver.get(configuracion['browser']['url'])
	esperar(driver, limite).until(EC.element_to_be_clickable(
		(By.XPATH, "//*[normalize-space(text())='ISSSTE']")
	)).click()
	esperar(driver, limite).until(EC.visibility_of_element_located(
		(By.CSS_SELECTOR, '[aria-label="Bono de Pensión"]')
	))
	escribir(driver.find_element(By.NAME, 'nombre'), datos['nombre'])
	# Confirmamos la fecha y esperamos la edad calculada por el formulario.
	fecha = datetime.strptime(datos['fecha_nacimiento'], '%Y-%m-%d')
	campo_fecha = driver.find_element(By.CSS_SELECTOR, '.dp__input')
	escribir(campo_fecha, fecha.strftime(configuracion['form']['date_input_format']))
	campo_fecha.send_keys(Keys.TAB)
	esperar(driver, limite).until(
		lambda navegador: bool(navegador.find_element(By.NAME, 'edad').get_attribute('value'))
	)
	# Seleccionamos genero, porcentaje solidario y los importes del cliente.
	genero = configuracion['form']['genero'][datos['genero']]
	driver.find_element(By.CSS_SELECTOR, '[role="checkbox"][aria-label="{}"]'.format(genero)).click()
	driver.find_element(By.CSS_SELECTOR, '[role="combobox"][aria-label="Ahorro solidario"]').click()
	esperar(driver, limite).until(EC.element_to_be_clickable((
		By.XPATH, "//*[@role='option' and normalize-space(.)='{}']".format(datos['ahorro_solidario'])
	))).click()
	for campo, etiqueta in ETIQUETAS.items():
		escribir(driver.find_element(By.CSS_SELECTOR, '[aria-label="{}"]'.format(etiqueta)), datos[campo])
	# Enviamos el calculo y esperamos resultados o mensajes de validacion visibles.
	esperar(driver, limite).until(EC.element_to_be_clickable(
		(By.XPATH, "//button[normalize-space(.)='Calcular']")
	)).click()
	esperar(driver, limite).until(lambda navegador: (
		'/retiro-resumen' in navegador.current_url
		or any(elemento.is_displayed() for elemento in navegador.find_elements(
			By.CSS_SELECTOR, '.swal2-popup, .q-field--error .q-field__messages'
		))
	))


def extraer_resultados(driver, limite):
	# Leemos las alertas para identificar el resultado, sin guardar toda la pagina.
	alertas = []
	for _ in range(3):
		esperar(driver, limite).until(lambda navegador: (
			any(elemento.is_displayed() for elemento in navegador.find_elements(By.CSS_SELECTOR, '.swal2-popup'))
			or 'Último salario cotizado' in navegador.find_element(By.TAG_NAME, 'body').text
			or any(elemento.is_displayed() for elemento in navegador.find_elements(
				By.CSS_SELECTOR, '.q-field--error .q-field__messages'
			))
		))
		visibles = [elemento for elemento in driver.find_elements(By.CSS_SELECTOR, '.swal2-popup')
					if elemento.is_displayed()]
		if not visibles:
			break
		alertas.append(visibles[0].text)
		esperar(driver, limite).until(EC.element_to_be_clickable(
			(By.CSS_SELECTOR, '.swal2-confirm')
		)).click()
		esperar(driver, limite).until(EC.invisibility_of_element_located((By.CSS_SELECTOR, '.swal2-popup')))
	texto = driver.find_element(By.TAG_NAME, 'body').text
	resultado = {}
	# Extraemos solo cifras visibles; una pension ausente no se convierte en cero.
	for columna, patron in PATRONES_WEB.items():
		coincidencia = re.search(patron, texto)
		resultado[columna] = coincidencia.group(1).replace(',', '') if coincidencia else 'NaN'
	# Calculamos la diferencia mensual solo cuando ambas pensiones son visibles.
	pension_sin_ahorro = Decimal(resultado['Pension_web'])
	pension_con_ahorro = Decimal(resultado['pension_con_av_web'])
	resultado['incremento_pension_con_ahorro_voluntario_y_solidario'] = (
		str(pension_con_ahorro - pension_sin_ahorro)
		if pension_sin_ahorro.is_finite() and pension_con_ahorro.is_finite()
		else 'NaN'
	)
	alerta = '\n'.join(alertas)
	if 'negativa de pensión' in alerta.lower():
		estado = 'negativa_pension'
	elif 'garantizada' in alerta.lower():
		estado = 'pension_garantizada'
	elif alertas:
		estado = 'alerta_no_identificada'
	elif 'Último salario cotizado' in texto:
		estado = 'resultado_sin_alerta'
	else:
		estado = 'validacion_formulario'
	observaciones = {
		'negativa_pension': 'La calculadora mostro negativa de pension.',
		'pension_garantizada': 'La calculadora mostro pension minima garantizada.',
		'resultado_sin_alerta': 'Termino el ciclo normal.',
		'validacion_formulario': 'El formulario no permitio obtener resultados.',
	}
	resultado.update(
		estado_web=estado,
		observaciones=observaciones.get(estado, 'Alerta no identificada: {}'.format(
			' '.join(alerta.split())
		)),
	)
	return resultado


def ejecutar(configuracion, exploratorio=False):
	clientes = leer_clientes(configuracion)
	if not clientes:
		raise ValueError('No hay clientes ISSSTE para procesar.')
	ruta = Path(configuracion['output']['path'])
	columnas = list(clientes[0]) + [
		campo for campo in COLUMNAS_RESULTADO if campo not in clientes[0]
	]
	opciones = webdriver.ChromeOptions()
	if configuracion['browser']['headless']:
		opciones.add_argument('--headless=new')
	driver = None
	ruta.parent.mkdir(parents=True, exist_ok=True)
	# Creamos una salida nueva sin sobrescribir muestras anteriores.
	with ruta.open('x', encoding=configuracion['output']['encoding'], newline='') as archivo:
		escritor = csv.DictWriter(archivo, fieldnames=columnas)
		escritor.writeheader()
		try:
			for cliente in clientes:
				registro = dict(cliente)
				registro.update({campo: 'NaN' for campo in COLUMNAS_RESULTADO})
				registro['edad_retiro_calculo'] = configuracion['form']['edad_retiro']
				registro['nombre_completo'] = ' '.join(
					cliente[campo].strip()
					for campo in configuracion['form']['fields']['nombre']
				)
				try:
					datos, avisos = preparar_datos(cliente, configuracion, exploratorio)
					registro['observaciones'] = ' '.join(avisos)
				except (KeyError, ValueError, ArithmeticError) as error:
					registro.update(estado_web='pendiente_manual', observaciones=str(error))
				else:
					# Reutilizamos un navegador y limitamos la espera por cliente.
					try:
						if driver is None:
							driver = webdriver.Chrome(options=opciones)
						limite = time.monotonic() + configuracion['execution']['max_seconds_per_client']
						completar_formulario(driver, datos, configuracion, limite)
						resultado = extraer_resultados(driver, limite)
						registro.update(resultado)
						registro['observaciones'] = ' '.join(
							avisos + [resultado['observaciones']]
						)
					except (TimeoutException, WebDriverException) as error:
						registro['estado_web'] = 'timeout' if isinstance(error, TimeoutException) else 'error_navegador'
						registro['observaciones'] += ' {}: {}'.format(type(error).__name__, str(error))
				# Guardamos cada cliente para conservar tambien los casos fallidos.
				escritor.writerow(registro)
				archivo.flush()
				print('Cliente {}: {}'.format(cliente['id_cliente'], registro['estado_web']), flush=True)
		finally:
			# Cerramos el navegador aunque falle una interaccion o la escritura.
			if driver is not None:
				driver.quit()
	return ruta


def main():
	argumentos = argparse.ArgumentParser(description='Muestra independiente de ISSSTE.')
	argumentos.add_argument('--exploratorio', action='store_true',
							help='Indica una ejecucion exploratoria en consola sin cambiar las reglas del JSON.')
	opciones = argumentos.parse_args()
	if opciones.exploratorio:
		print('Ejecucion exploratoria con las reglas actuales del JSON.')
	ruta = ejecutar(cargar_configuracion(), opciones.exploratorio)
	print('CSV guardado: {}'.format(ruta))


if __name__ == '__main__':
	main()
