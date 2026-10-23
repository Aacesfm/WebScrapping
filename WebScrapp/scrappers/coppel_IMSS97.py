"""Coppel calcula exclusivamente IMSS97; sus totales incluyen AV y vivienda."""

import argparse
import csv
import json
import os
import time
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select

from sura_IMSS97 import (
	COLUMNAS_WEB as COLUMNAS_COMUNES, VALOR_FALTANTE, escribir, esperar,
	ids_guardados, leer_clientes as leer_entrada, normalizar_cifra, numero,
	pulsar as pulsar_control, resumir, texto_visible, validar_entorno,
)

RUTA_CONFIGURACION = Path(__file__).resolve().parents[1] / 'config' / 'coppel_IMSS97.json'
COLUMNAS_WEB = COLUMNAS_COMUNES + ['saldo_total_web', 'saldo_total_con_av_mensual_web']
CAMPOS_FINANCIEROS = {
	'saldo_retiro': 'saldo_rcv', 'semanas': 'sem_cot',
	'ahorro_voluntario': 'saldo_av', 'salario': 'salario_mensual',
	'saldo_subcuenta': 'saldo_vivienda',
}


class RechazoCoppel(Exception):
	pass


def informar(mensaje):
	print('[COPPEL IMSS97] {}'.format(mensaje), flush=True)


def cargar_configuracion():
	with RUTA_CONFIGURACION.open(encoding='utf-8') as archivo:
		configuracion = json.load(archivo)
	for seccion in ('input', 'output'):
		ruta = Path(configuracion[seccion]['path'])
		if not ruta.is_absolute():
			ruta = RUTA_CONFIGURACION.parent / ruta
		configuracion[seccion]['path'] = str(ruta.resolve())
	return configuracion


def argumentos_cli(configuracion=None, argv=None):
	if configuracion is None:
		configuracion = cargar_configuracion()
	parser = argparse.ArgumentParser(description='Simulador Coppel IMSS Ley 97, sin cuenta digital.')
	parser.add_argument('--input', type=Path, default=Path(configuracion['input']['path']))
	parser.add_argument('--output', type=Path, default=Path(configuracion['output']['path']))
	parser.add_argument('--max-clientes', type=int, default=configuracion['execution']['max_clients'])
	parser.add_argument('--timeout', type=int, default=configuracion['execution']['max_seconds_per_client'])
	parser.add_argument('--edad-retiro', type=int, choices=range(60, 66),
						default=configuracion['results']['retirement_age'])
	parser.add_argument('--headless', action='store_true', default=configuracion['browser']['headless'])
	argumentos = parser.parse_args(argv)
	if argumentos.max_clientes < 1 or argumentos.timeout < 1:
		parser.error('Maximo de clientes y timeout deben ser positivos.')
	if argumentos.edad_retiro not in range(60, 66):
		parser.error('Coppel admite retiro de 60 a 65 anios.')
	entrada = argumentos.input.expanduser().resolve()
	salida = argumentos.output.expanduser().resolve()
	if entrada == salida:
		parser.error('La salida no puede ser el archivo de entrada.')
	configuracion['input']['path'] = str(entrada)
	configuracion['output']['path'] = str(salida)
	configuracion['execution'].update(max_clients=argumentos.max_clientes,
		max_seconds_per_client=argumentos.timeout)
	configuracion['results']['retirement_age'] = argumentos.edad_retiro
	configuracion['browser']['headless'] = argumentos.headless
	return configuracion


def leer_clientes(configuracion):
	clientes, columnas = leer_entrada(configuracion)
	for columna in COLUMNAS_WEB:
		if columna not in columnas:
			columnas.append(columna)
	return clientes, columnas


def preparar_datos(cliente):
	if cliente.get('regimen_estimado') != 'IMSS97' or cliente.get('ley_bandera') != 'LEY_97':
		raise ValueError('La calculadora Coppel solo admite IMSS Ley 97.')
	for campo in ('id_cliente', 'nombre', 'ap_paterno', 'correo', 'nss', 'f_nacim', 'genero'):
		if not str(cliente.get(campo) or '').strip():
			raise ValueError('Falta el campo {}.'.format(campo))
	if cliente['genero'] not in ('H', 'M'):
		raise ValueError('Genero distinto de H o M.')
	if len(cliente['nss']) != 11 or not cliente['nss'].isdigit():
		raise ValueError('NSS debe contener 11 digitos.')
	nacimiento = datetime.strptime(cliente['f_nacim'], '%Y-%m-%d').date()
	hoy = date.today()
	edad = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
	if not 18 <= edad <= 65:
		raise ValueError('Coppel solo admite edades de 18 a 65 anios.')
	datos = {'nacimiento': nacimiento, 'edad': edad}
	for campo in list(CAMPOS_FINANCIEROS.values()) + ['av_mensual']:
		valor = numero(cliente.get(campo), campo)
		if campo == 'sem_cot' and valor != valor.to_integral_value():
			raise ValueError('Las semanas deben ser enteras.')
		datos[campo] = str(valor.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
	return datos


def cerrar_encuesta(driver):
	try:
		for marco in driver.find_elements(By.CSS_SELECTOR, '#kampyleInvite iframe'):
			if marco.is_displayed():
				driver.switch_to.frame(marco)
				for boton in driver.find_elements(By.CSS_SELECTOR,
						'button[aria-label="Close Survey"], button[title="Close Survey"]'):
					if boton.is_displayed():
						boton.click()
	finally:
		driver.switch_to.default_content()


def pulsar(driver, selector, limite):
	cerrar_encuesta(driver)
	pulsar_control(driver, selector, limite)


def comprobar_rechazo(driver):
	for marco in driver.find_elements(By.CSS_SELECTOR, 'iframe[src*="bframe"]'):
		if marco.is_displayed():
			raise RechazoCoppel('CAPTCHA: requiere revision manual.')
	for selector in ('.invalid-feedback', '.swal2-popup .swal2-html-container',
					 '.modal.show .modal-body'):
		mensaje = texto_visible(driver, selector)
		if mensaje:
			raise RechazoCoppel(mensaje)


def esperar_paso(driver, selector, limite):
	def cambio(navegador):
		comprobar_rechazo(navegador)
		return any(elemento.is_displayed() for elemento in
				   navegador.find_elements(By.CSS_SELECTOR, selector))
	esperar(driver, limite).until(cambio)


def completar_formulario(driver, cliente, datos, configuracion, limite):
	driver.set_page_load_timeout(max(1, limite - time.monotonic()))
	driver.get(configuracion['browser']['url'])
	esperar(driver, limite).until(lambda navegador:
		navegador.execute_script('return document.readyState') == 'complete')
	pulsar(driver, '#accionar', limite)
	pulsar(driver, '#btn_sin_cuenta', limite)
	for selector, valor in (
		('#nombre', cliente['nombre']),
		('#apellidos', '{} {}'.format(cliente['ap_paterno'], cliente.get('ap_materno', '')).strip()),
		('#emailInvitado', cliente['correo']),
	):
		escribir(driver, selector, valor, limite)
	pulsar(driver, '#aceptarTerminos', limite)
	pulsar(driver, '#btn_registro_sesion', limite)
	esperar_paso(driver, '#fecha', limite)
	escribir(driver, '#fecha', datos['nacimiento'].strftime('%d%m%Y'), limite)
	if driver.find_element(By.ID, 'fecha').get_attribute('value') != datos['nacimiento'].strftime('%d/%m/%Y'):
		raise RechazoCoppel('La fecha capturada no coincide con el CSV.')
	esperar(driver, limite).until(lambda navegador:
		len(navegador.find_element(By.ID, 'edad_deseada').find_elements(By.TAG_NAME, 'option')) > 1)
	Select(driver.find_element(By.ID, 'edad_deseada')).select_by_value(
		str(configuracion['results']['retirement_age']))
	Select(driver.find_element(By.ID, 'genero')).select_by_value('1' if cliente['genero'] == 'M' else '2')
	escribir(driver, '#nss', cliente['nss'], limite)
	for identificador, campo in CAMPOS_FINANCIEROS.items():
		escribir(driver, '#' + identificador, datos[campo], limite)
		capturado = normalizar_cifra(driver.find_element(By.ID, identificador).get_attribute('value'))
		if capturado == VALOR_FALTANTE or Decimal(capturado) != Decimal(datos[campo]):
			raise RechazoCoppel('Coppel ajusto {}'.format(campo))
	pulsar(driver, '#btn_calcular', limite)


def esperar_resultado(driver, limite, con_av=False):
	pension = '#pension_mensual_recalculo' if con_av else '#pension_mensual'
	saldo = '#monto_total_tiempo2' if con_av else '#monto_total_tiempo'
	def resultado(navegador):
		comprobar_rechazo(navegador)
		for elemento in navegador.find_elements(By.CSS_SELECTOR, '[id="monto_total_tiempo_semanas_no"]'):
			if elemento.is_displayed():
				return 'NEGATIVA'
		if not con_av and normalizar_cifra(texto_visible(navegador, '#pg_pmg')) != VALOR_FALTANTE:
			return 'GARANTIZADA'
		if (normalizar_cifra(texto_visible(navegador, pension)) != VALOR_FALTANTE and
				normalizar_cifra(texto_visible(navegador, saldo)) != VALOR_FALTANTE):
			return 'OK'
		return False
	return esperar(driver, limite).until(resultado)


def procesar_cliente(driver, cliente, configuracion):
	registro = dict(cliente)
	registro.update({columna: VALOR_FALTANTE for columna in COLUMNAS_WEB})
	registro['nombre_completo'] = ' '.join(cliente.get(campo, '').strip()
		for campo in ('nombre', 'ap_paterno', 'ap_materno') if cliente.get(campo, '').strip())
	registro['id_checkpoint'] = cliente[configuracion['checkpoint']['id_field']]
	registro['edad_retiro_calculo'] = configuracion['results']['retirement_age']
	limite = time.monotonic() + configuracion['execution']['max_seconds_per_client']
	etapa = 'datos'
	try:
		datos = preparar_datos(cliente)
		if datos['edad'] > registro['edad_retiro_calculo']:
			registro['observaciones'] = 'OMITIDO | edad mayor al retiro'
			return registro
		etapa = 'formulario'
		completar_formulario(driver, cliente, datos, configuracion, limite)
		etapa = 'resultado base'
		estado = esperar_resultado(driver, limite)
		if estado == 'NEGATIVA':
			registro['observaciones'] = estado
			return registro
		if estado == 'GARANTIZADA':
			registro['Pension_web'] = normalizar_cifra(texto_visible(driver, '#pg_pmg'))
			registro['saldo_total_web'] = normalizar_cifra(texto_visible(driver, '#pg_saldo'))
			registro['observaciones'] = 'GARANTIZADA | panel sin comparacion AV mensual'
			return registro
		registro['Pension_web'] = normalizar_cifra(texto_visible(driver, '#pension_mensual'))
		registro['saldo_total_web'] = normalizar_cifra(texto_visible(driver, '#monto_total_tiempo'))
		etapa = 'aportacion mensual'
		pulsar(driver, '#btn_crecer_retiro', limite)
		esperar_paso(driver, '#pension_ideal', limite)
		escribir(driver, '#pension_ideal', datos['av_mensual'], limite)
		previo = texto_visible(driver, '#monto_total_tiempo2')
		pulsar(driver, '#recalcular', limite)
		if Decimal(datos['av_mensual']) > 0 and datos['edad'] < registro['edad_retiro_calculo']:
			esperar(driver, limite).until(lambda navegador:
				texto_visible(navegador, '#monto_total_tiempo2') != previo)
		esperar_resultado(driver, limite, con_av=True)
		registro['pension_con_av_web'] = normalizar_cifra(texto_visible(driver, '#pension_mensual_recalculo'))
		registro['saldo_total_con_av_mensual_web'] = normalizar_cifra(texto_visible(driver, '#monto_total_tiempo2'))
		registro['observaciones'] = 'OK | base incluye saldo AV y vivienda; comparacion con AV mensual'
	except RechazoCoppel as error:
		registro['observaciones'] = 'RECHAZADO | ' + resumir(error)
	except (ValueError, KeyError) as error:
		registro['observaciones'] = 'DATO INVALIDO | ' + resumir(error)
	except TimeoutException:
		registro['observaciones'] = 'TIMEOUT | ' + etapa
	except WebDriverException as error:
		registro['observaciones'] = 'ERROR | ' + type(error).__name__
	return registro


def main(argv=None):
	validar_entorno()
	configuracion = argumentos_cli(cargar_configuracion(), argv)
	clientes, columnas = leer_clientes(configuracion)
	if not clientes:
		raise ValueError('No se encontraron clientes IMSS97.')
	ruta = Path(configuracion['output']['path'])
	guardados = ids_guardados(ruta, columnas, configuracion['execution']['resume'],
							 configuracion['output']['encoding'])
	if not guardados.issubset({cliente['id_cliente'] for cliente in clientes}):
		raise ValueError('La salida contiene IDs fuera de la muestra seleccionada.')
	pendientes = [cliente for cliente in clientes if cliente['id_cliente'] not in guardados]
	if not pendientes:
		informar('No hay clientes pendientes.')
		return
	opciones = webdriver.ChromeOptions()
	opciones.page_load_strategy = configuracion['browser']['page_load_strategy']
	opciones.add_argument('--window-size=' + configuracion['browser']['window_size'])
	if configuracion['browser']['headless']:
		opciones.add_argument('--headless=new')
	driver = webdriver.Chrome(options=opciones)
	try:
		ruta.parent.mkdir(parents=True, exist_ok=True)
		cabecera = not ruta.exists() or ruta.stat().st_size == 0
		with ruta.open('a', encoding=configuracion['output']['encoding'], newline='') as archivo:
			escritor = csv.DictWriter(archivo, fieldnames=columnas)
			if cabecera:
				escritor.writeheader()
			for indice, cliente in enumerate(pendientes, 1):
				registro = procesar_cliente(driver, cliente, configuracion)
				escritor.writerow(registro)
				archivo.flush()
				os.fsync(archivo.fileno())
				informar('{}/{} | {} | {}'.format(len(guardados) + indice, len(clientes),
					cliente['id_cliente'], registro['observaciones']))
				if 'CAPTCHA' in registro['observaciones'].upper():
					break
				pausa = configuracion['browser']['pause_between_records_seconds']
				if pausa and indice < len(pendientes):
					time.sleep(pausa)
	finally:
		driver.quit()
	informar('CSV guardado: {}'.format(ruta))


if __name__ == '__main__':
	main()
