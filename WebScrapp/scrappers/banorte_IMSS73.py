import argparse
import csv
import json
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By

from banorte_IMSS97 import (
	RechazoBanorte, cifra, escribir, esperar, guardar_chunk, leer_clientes,
	numero, pulsar, resumir, validar_entorno, visible,
)

RUTA_CONFIGURACION = Path(__file__).resolve().parents[1] / 'config' / 'banorte_IMSS73.json'
COLUMNAS_WEB = [
	'Pension_web', 'sal_cot_web', 'saldo_rcv_web', 'disposicion_recursos_web',
	'pension_edad_mas_1_web', 'pension_edad_mas_2_web',
	'edad_retiro_calculo', 'observaciones',
]


def informar(mensaje):
	print('[BANORTE IMSS73] {}'.format(mensaje), flush=True)


def cargar_configuracion():
	with RUTA_CONFIGURACION.open(encoding='utf-8') as archivo:
		configuracion = json.load(archivo)
	for seccion in ('input', 'output', 'checkpoint'):
		ruta = Path(configuracion[seccion]['path'])
		if not ruta.is_absolute():
			ruta = RUTA_CONFIGURACION.parent / ruta
		configuracion[seccion]['path'] = str(ruta.resolve())
	return configuracion


def argumentos_cli(configuracion, argv=None):
	parser = argparse.ArgumentParser(description='Scraper Banorte Ley 73.')
	parser.add_argument('--input', type=Path)
	parser.add_argument('--output', type=Path)
	parser.add_argument('--max-clientes', type=int)
	parser.add_argument('--timeout', type=int)
	parser.add_argument('--headless', action='store_true')
	argumentos = parser.parse_args(argv)
	for argumento, clave in ((argumentos.max_clientes, 'max_clients'),
							(argumentos.timeout, 'max_seconds_per_client')):
		if argumento is not None:
			if argumento <= 0:
				parser.error('El limite y timeout deben ser positivos.')
			configuracion['execution'][clave] = argumento
	if argumentos.input:
		configuracion['input']['path'] = str(argumentos.input.expanduser().resolve())
	if argumentos.output:
		ruta = argumentos.output.expanduser().resolve()
		configuracion['output']['path'] = str(ruta)
		configuracion['checkpoint']['path'] = str(ruta.with_name(ruta.stem + '_checkpoint.json'))
	if argumentos.headless:
		configuracion['browser']['headless'] = True
	return configuracion


def columnas_salida(columnas_entrada):
	columnas = list(columnas_entrada)
	for columna in ['nombre_completo'] + COLUMNAS_WEB + ['id_checkpoint']:
		if columna not in columnas:
			columnas.append(columna)
	return columnas


def preparar_datos(cliente, configuracion):
	for campo in ('id_cliente', 'nombre', 'ap_paterno', 'curp', 'correo',
				  'f_nacim', 'anio_fil', 'sem_cot', 'saldo_rcv', 'salario_mensual'):
		if not str(cliente.get(campo) or '').strip():
			raise ValueError('Falta {}'.format(campo))
	datos = {}
	for campo in ('sem_cot', 'saldo_rcv', 'salario_mensual'):
		valor = numero(cliente[campo], campo)
		if campo == 'sem_cot' and valor != valor.to_integral_value():
			raise ValueError('Semanas no enteras')
		datos[campo] = str(valor.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
	datos['fecha_cotizacion'] = '{}-{}'.format(
		int(cliente['anio_fil']), configuracion['form']['first_contribution_month_day'])
	datetime.strptime(datos['fecha_cotizacion'], '%Y-%m-%d')
	nacimiento = datetime.strptime(cliente['f_nacim'], '%Y-%m-%d')
	if cliente['curp'][4:10] != nacimiento.strftime('%y%m%d'):
		raise ValueError('CURP y nacimiento no coinciden')
	return datos


def comprobar_rechazo(driver):
	if visible(driver, 'iframe[src*="bframe"]'):
		raise RechazoBanorte('CAPTCHA: requiere revision manual')
	for selector, mensaje in (
		('#error500', 'Banorte: error de calculo'),
		('#aCalculadora97', 'Banorte clasifica como Ley 97'),
		('#noPuedesPensionarteAEstaEdad', 'No permite retiro a esta edad'),
	):
		if visible(driver, selector):
			raise RechazoBanorte(mensaje)
	for elemento in visible(driver, 'input.is-invalid'):
		raise RechazoBanorte('Formulario: {}'.format(elemento.get_attribute('id')))


def esperar_paso(driver, selector, limite):
	def cambio(navegador):
		comprobar_rechazo(navegador)
		return visible(navegador, selector)
	return esperar(driver, limite).until(cambio)


def capturar_numero(driver, identificador, valor, limite, oculto=None):
	escribir(driver, identificador, valor, limite)
	campo = driver.find_element(By.ID, identificador)
	for destino in (identificador, oculto) if oculto else (identificador,):
		capturado = driver.find_element(By.ID, destino).get_attribute('value').replace(',', '')
		if not capturado or Decimal(capturado) != Decimal(str(valor)):
			raise RechazoBanorte('Banorte ajusto {}'.format(identificador))
	if not driver.execute_script('return arguments[0].validity.valid;', campo):
		raise RechazoBanorte('Fuera de rango: {}'.format(identificador))
	for atributo in ('min', 'max'):
		tope = campo.get_attribute(atributo)
		if tope and ((atributo == 'min' and Decimal(str(valor)) < Decimal(tope)) or
					 (atributo == 'max' and Decimal(str(valor)) > Decimal(tope))):
			raise RechazoBanorte('Fuera de rango: {}'.format(identificador))


def completar_formulario(driver, cliente, datos, configuracion, limite):
	driver.set_page_load_timeout(max(1, limite - time.monotonic()))
	driver.get(configuracion['browser']['url'])
	esperar_paso(driver, '#curp', limite)
	esperar(driver, limite).until(
		lambda navegador: navegador.execute_script('return document.readyState') == 'complete')
	time.sleep(configuracion['browser']['page_ready_pause_seconds'])
	for identificador, valor in (
		('curp', cliente['curp']), ('firstName', cliente['nombre']),
		('lastName', '{} {}'.format(cliente['ap_paterno'], cliente.get('ap_materno', '')).strip()),
		('email', cliente['correo']), ('fechaCotizado', datos['fecha_cotizacion']),
	):
		escribir(driver, identificador, valor, limite)
	if driver.find_element(By.ID, 'fechaCotizado').get_attribute('value') != datos['fecha_cotizacion']:
		raise RechazoBanorte('No se pudo capturar fecha de cotizacion')
	capturar_numero(driver, 'semanasCotizadasField', datos['sem_cot'], limite, 'semanasCotizadas')
	comprobar_rechazo(driver)
	pulsar(driver, '#ctaStep1', limite)
	esperar_paso(driver, '#salarioMensualField', limite)
	for identificador, valor, oculto in (
		('edadRetiro', configuracion['results']['retirement_age'], None),
		('mesesCotizadosAnio', configuracion['form']['contribution_months_per_year'], None),
		('salarioMensualField', datos['salario_mensual'], 'salarioMensual'),
		('saldoInicialEnCuentaString', datos['saldo_rcv'], 'saldoInicialEnCuenta'),
	):
		capturar_numero(driver, identificador, valor, limite, oculto)
	comprobar_rechazo(driver)
	if not driver.find_element(By.ID, 'acceptance').is_selected():
		pulsar(driver, '#acceptance', limite)
	pulsar(driver, '#ctaStepTwo', limite)


def extraer_resultados(driver, configuracion, limite):
	faltante = configuracion['missing_value']
	def listo(navegador):
		comprobar_rechazo(navegador)
		if visible(navegador, '#loading'):
			return False
		if visible(navegador, '#negativaDePension'):
			return 'NEGATIVA'
		if visible(navegador, '#rentaVitalicia'):
			return 'RENTA VITALICIA'
		if cifra(navegador, '#pensionCalculo1', faltante) != faltante:
			return 'OK'
		return False
	caso = esperar(driver, limite).until(listo)
	selectores = {
		'Pension_web': '#pensionCalculo1',
		'sal_cot_web': '#resultados_salarioMensual',
		'saldo_rcv_web': '#resultados_saldoEnCuentaAfore',
		'disposicion_recursos_web': '#disposicionTotalDeRecursos',
		'pension_edad_mas_1_web': '#pensionCalculo2',
		'pension_edad_mas_2_web': '#pensionCalculo3',
	}
	resultados = {columna: cifra(driver, selector, faltante)
				  for columna, selector in selectores.items()}
	if caso != 'OK':
		resultados = {columna: faltante for columna in selectores}
		resultados['saldo_rcv_web'] = cifra(driver,
			'#saldoAcumuladoEnCTA' if caso == 'NEGATIVA' else '#saldoAcumuladoEnCTARV', faltante)
		if caso == 'RENTA VITALICIA':
			resultados['Pension_web'] = cifra(driver, '#saldoRentaVitalicia', faltante)
	return resultados, caso


def procesar_cliente(driver, cliente, configuracion):
	registro = dict(cliente)
	registro.update({columna: configuracion['missing_value'] for columna in COLUMNAS_WEB})
	registro['nombre_completo'] = ' '.join(cliente.get(campo, '').strip()
		for campo in ('nombre', 'ap_paterno', 'ap_materno') if cliente.get(campo, '').strip())
	registro['id_checkpoint'] = cliente[configuracion['checkpoint']['id_field']]
	registro['edad_retiro_calculo'] = configuracion['results']['retirement_age']
	limite = time.monotonic() + configuracion['execution']['max_seconds_per_client']
	etapa = 'datos'
	try:
		if numero(cliente.get('age'), 'age') > registro['edad_retiro_calculo']:
			registro['observaciones'] = 'OMITIDO | edad {} > retiro {}'.format(
				cliente.get('age'), registro['edad_retiro_calculo'])
			return registro
		datos = preparar_datos(cliente, configuracion)
		etapa = 'formulario'
		completar_formulario(driver, cliente, datos, configuracion, limite)
		etapa = 'resultados'
		resultados, caso = extraer_resultados(driver, configuracion, limite)
		registro.update(resultados)
		registro['observaciones'] = caso
	except ValueError as error:
		registro['observaciones'] = 'DATO INVALIDO | ' + resumir(error)
	except RechazoBanorte as error:
		registro['observaciones'] = 'RECHAZADO | ' + resumir(error)
	except TimeoutException:
		registro['observaciones'] = 'TIMEOUT | {}'.format(etapa)
	except WebDriverException as error:
		registro['observaciones'] = 'ERROR | {}'.format(type(error).__name__)
	return registro


def main(argv=None):
	validar_entorno()
	configuracion = argumentos_cli(cargar_configuracion(), argv)
	clientes, columnas_entrada = leer_clientes(configuracion)
	if not clientes:
		raise ValueError('No hay clientes para procesar.')
	columnas = columnas_salida(columnas_entrada)
	ruta = Path(configuracion['output']['path'])
	ruta_checkpoint = Path(configuracion['checkpoint']['path'])
	ids_guardados = set()
	if ruta_checkpoint.exists():
		with ruta_checkpoint.open(encoding='utf-8') as archivo:
			estado = json.load(archivo)
		if estado['input_path'] != configuracion['input']['path']:
			raise ValueError('Checkpoint de otra entrada: use nuevas rutas de salida.')
		if not ruta.exists():
			raise FileNotFoundError('Existe checkpoint sin CSV de salida.')
	if ruta.exists() and ruta.stat().st_size:
		if not configuracion['execution']['resume']:
			raise FileExistsError('La salida existe; no se sobrescribira.')
		with ruta.open(encoding=configuracion['output']['encoding'], newline='') as archivo:
			lector = csv.DictReader(archivo)
			if lector.fieldnames != columnas:
				raise ValueError('El layout del CSV existente no coincide.')
			ids_guardados = {fila['id_checkpoint'] for fila in lector}
	pendientes = [cliente for cliente in clientes
		if cliente[configuracion['checkpoint']['id_field']] not in ids_guardados]
	if not pendientes:
		informar('La muestra ya esta procesada.')
		return
	previos = len(ids_guardados)
	opciones = webdriver.ChromeOptions()
	opciones.page_load_strategy = 'eager'
	if configuracion['browser']['headless']:
		opciones.add_argument('--headless=new')
	driver = webdriver.Chrome(options=opciones)
	chunk = []
	try:
		driver.maximize_window()
		pantalla = driver.get_window_rect()
		driver.set_window_rect(x=pantalla['x'], y=pantalla['y'],
			width=pantalla['width'] // 2, height=pantalla['height'])
		for indice, cliente in enumerate(pendientes, start=1):
			registro = procesar_cliente(driver, cliente, configuracion)
			chunk.append(registro)
			informar('{}/{} | {} | {}'.format(previos + indice, len(clientes),
				registro['id_checkpoint'], registro['observaciones']))
			if len(chunk) >= configuracion['execution']['chunk_size']:
				guardar_chunk(chunk, columnas, configuracion, ids_guardados)
			pausa = configuracion['browser']['pause_between_records_seconds']
			if pausa > 0 and indice < len(pendientes):
				time.sleep(pausa)
	finally:
		try:
			guardar_chunk(chunk, columnas, configuracion, ids_guardados)
		finally:
			driver.quit()
	informar('CSV guardado: {}'.format(ruta))


if __name__ == '__main__':
	main()
