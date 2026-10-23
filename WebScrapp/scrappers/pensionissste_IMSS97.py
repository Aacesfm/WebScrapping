"""Scraper autonomo de PENSIONISSSTE para IMSS Ley 97, no Ley 73."""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

RUTA_CONFIGURACION = Path(__file__).resolve().parents[1] / 'config' / 'pensionissste_IMSS97.json'
ENTORNO_PROYECTO = Path(__file__).resolve().parents[2] / '.venv-py388'
FALTANTE = 'NaN'
COLUMNAS_WEB = [
	'Pension_web', 'pension_con_av_web', 'rcv_proy_web', 'rcv_av_proy_web',
	'sal_cot_web', 'tasa_remplazo_web', 'tasa_rendimiento_web', 'densidad_cot_web',
	'edad_retiro_calculo', 'observaciones', 'saldo_inicial_capturado',
	'saldo_inicial_incluye_av', 'saldo_acumulado_web', 'saldo_acumulado_con_av_web',
	'modalidad_web', 'modalidad_con_av_web',
]


class RechazoPensionissste(Exception):
	pass


def informar(mensaje):
	print('[PENSIONISSSTE IMSS97] {}'.format(mensaje), flush=True)


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
	return configuracion


def argumentos_cli(configuracion, argv=None):
	parser = argparse.ArgumentParser(description='PENSIONISSSTE IMSS97, ejecucion independiente.')
	parser.add_argument('--input', type=Path, default=Path(configuracion['input']['path']))
	parser.add_argument('--output', type=Path, default=Path(configuracion['output']['path']))
	parser.add_argument('--max-clientes', type=int, default=configuracion['execution']['max_clients'])
	parser.add_argument('--timeout', type=int, default=configuracion['execution']['max_seconds_per_client'])
	parser.add_argument('--headless', action='store_true', default=configuracion['browser']['headless'])
	argumentos = parser.parse_args(argv)
	if argumentos.max_clientes < 1 or argumentos.timeout < 1:
		parser.error('Maximo y timeout deben ser positivos.')
	entrada, salida = argumentos.input.expanduser().resolve(), argumentos.output.expanduser().resolve()
	if entrada == salida:
		parser.error('La salida no puede ser el archivo de entrada.')
	configuracion['input']['path'], configuracion['output']['path'] = str(entrada), str(salida)
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
	if cliente.get('regimen_estimado') != 'IMSS97' or cliente.get('ley_bandera') != 'LEY_97':
		raise ValueError('Este scraper solo calcula IMSS97.')
	for campo in ('id_cliente', 'nombre', 'ap_paterno', 'f_nacim', 'genero'):
		if not str(cliente.get(campo) or '').strip():
			raise ValueError('Falta {}.'.format(campo))
	if cliente['genero'] not in ('H', 'M'):
		raise ValueError('Genero distinto de H o M.')
	nacimiento = datetime.strptime(cliente['f_nacim'], '%Y-%m-%d').date()
	hoy = date.today()
	edad = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
	if edad < 18:
		raise ValueError('El cliente no cumple la mayoria de edad.')
	retiro = numero(configuracion['results']['retirement_age'], 'retirement_age')
	if retiro < 60 or retiro > 100 or retiro != retiro.to_integral_value():
		raise ValueError('Edad de retiro entera entre 60 y 100.')
	datos = {'nacimiento': nacimiento, 'edad': edad}
	campos = ['salario_mensual', 'saldo_rcv', 'anios_cotizados', 'av_mensual']
	if configuracion['form']['include_av_in_initial_balance']:
		campos.append('saldo_av')
	for campo in campos:
		valor = numero(cliente.get(campo), campo)
		if campo == 'anios_cotizados' and valor != valor.to_integral_value():
			raise ValueError('Los anios cotizados deben ser enteros.')
		datos[campo] = str(valor.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
	datos['saldo_inicial'] = str(Decimal(datos['saldo_rcv']) + Decimal(datos.get('saldo_av', '0')))
	return datos


def esperar(driver, limite):
	if limite <= time.monotonic():
		raise TimeoutException()
	return WebDriverWait(driver, limite - time.monotonic())


def texto_visible(driver, selector):
	return ' '.join(elemento.text.strip() for elemento in driver.find_elements(By.CSS_SELECTOR, selector)
		if elemento.is_displayed() and elemento.text.strip())


def cifra(texto):
	limpio = str(texto).replace('$', '').replace(',', '').replace('%', '').strip()
	return limpio if re.fullmatch(r'\d+(?:\.\d+)?', limpio) else FALTANTE


def comprobar_rechazo(driver):
	mensaje = texto_visible(driver, '.modal.show .content_text, .modal.show .modal-body')
	if mensaje:
		raise RechazoPensionissste(' '.join(mensaje.split())[:180])
	for marco in driver.find_elements(By.CSS_SELECTOR, 'iframe[src*="bframe"]'):
		if marco.is_displayed():
			raise RechazoPensionissste('CAPTCHA: requiere revision manual.')


def escribir(driver, identificador, valor, limite):
	campo = esperar(driver, limite).until(EC.element_to_be_clickable((By.ID, identificador)))
	campo.send_keys(Keys.COMMAND if sys.platform == 'darwin' else Keys.CONTROL, 'a')
	campo.send_keys(str(valor))
	campo.send_keys(Keys.TAB)
	comprobar_rechazo(driver)


def completar_formulario(driver, cliente, datos, configuracion, limite, con_av=False):
	driver.set_page_load_timeout(max(1, limite - time.monotonic()))
	driver.get(configuracion['browser']['url'])
	esperar(driver, limite).until(lambda navegador:
		navegador.execute_script('return document.readyState') == 'complete')
	esperar(driver, limite).until(EC.element_to_be_clickable((By.ID, 'cotiza_institu')))
	Select(driver.find_element(By.ID, 'cotiza_institu')).select_by_value('2')
	escribir(driver, 'nombre_ch', ' '.join(cliente.get(campo, '').strip() for campo in
		('nombre', 'ap_paterno', 'ap_materno') if cliente.get(campo, '').strip()), limite)
	fecha = datos['nacimiento'].strftime('%d/%m/%Y')
	escribir(driver, 'fecha_nch', fecha, limite)
	if driver.find_element(By.ID, 'fecha_nch').get_attribute('value') != fecha:
		raise RechazoPensionissste('La fecha capturada no coincide con el CSV.')
	Select(driver.find_element(By.ID, 'genero')).select_by_value('1' if cliente['genero'] == 'M' else '2')
	for identificador, valor in (
		('edad_retiro', configuracion['results']['retirement_age']),
		('saldo_des', datos['salario_mensual']), ('saldo_act', datos['saldo_inicial']),
		('nanios_cot', datos['anios_cotizados']),
	):
		escribir(driver, identificador, valor, limite)
		capturado = cifra(driver.find_element(By.ID, identificador).get_attribute('value'))
		if capturado == FALTANTE or Decimal(capturado) != Decimal(str(valor)):
			raise RechazoPensionissste('La pagina ajusto {}'.format(identificador))
	mensual = datos['av_mensual'] if con_av else '0'
	Select(driver.find_element(By.ID, 'aporta_adicional')).select_by_value('1' if Decimal(mensual) > 0 else '2')
	if Decimal(mensual) > 0:
		escribir(driver, 'monto_mdestinado', mensual, limite)
		if cifra(driver.find_element(By.ID, 'monto_mdestinado').get_attribute('value')) != mensual + '.00':
			capturado = cifra(driver.find_element(By.ID, 'monto_mdestinado').get_attribute('value'))
			if capturado == FALTANTE or Decimal(capturado) != Decimal(mensual):
				raise RechazoPensionissste('La pagina ajusto AV mensual.')
	boton = esperar(driver, limite).until(EC.element_to_be_clickable((By.ID, 'datos_futuro_estimar')))
	driver.execute_script('arguments[0].scrollIntoView({block:"center"});', boton)
	boton.click()


def extraer_resultados(driver, limite):
	def listo(navegador):
		comprobar_rechazo(navegador)
		return (texto_visible(navegador, '#modalidad_Pen') and
			cifra(texto_visible(navegador, '#pens_mensual')) != FALTANTE)
	esperar(driver, limite).until(listo)
	modalidad = texto_visible(driver, '#modalidad_Pen')
	return {'pension': cifra(texto_visible(driver, '#pens_mensual')),
		'saldo': cifra(texto_visible(driver, '#s_acumulado_65')),
		'tasa': cifra(texto_visible(driver, '#t_reemplazo')), 'modalidad': modalidad,
		'salario': cifra(driver.find_element(By.ID, 'recSaldoDes').get_attribute('value')),
		'estado': 'NEGATIVA' if 'negativa' in modalidad.lower() else
			'GARANTIZADA' if 'garantizada' in modalidad.lower() else 'OK'}


def procesar_cliente(driver, cliente, configuracion):
	registro = dict(cliente)
	registro.update({columna: FALTANTE for columna in COLUMNAS_WEB})
	registro['nombre_completo'] = ' '.join(cliente.get(campo, '').strip() for campo in
		('nombre', 'ap_paterno', 'ap_materno') if cliente.get(campo, '').strip())
	registro['id_checkpoint'] = cliente['id_cliente']
	registro['edad_retiro_calculo'] = configuracion['results']['retirement_age']
	registro['saldo_inicial_incluye_av'] = int(configuracion['form']['include_av_in_initial_balance'])
	limite = time.monotonic() + configuracion['execution']['max_seconds_per_client']
	etapa = 'datos'
	try:
		datos = preparar_datos(cliente, configuracion)
		registro['saldo_inicial_capturado'] = datos['saldo_inicial']
		if datos['edad'] > registro['edad_retiro_calculo']:
			registro['observaciones'] = 'OMITIDO | edad mayor al retiro'
			return registro
		etapa = 'base'
		completar_formulario(driver, cliente, datos, configuracion, limite)
		base = extraer_resultados(driver, limite)
		registro.update(Pension_web=base['pension'], saldo_acumulado_web=base['saldo'],
			tasa_remplazo_web=base['tasa'], modalidad_web=base['modalidad'], sal_cot_web=base['salario'])
		adicional = base
		if Decimal(datos['av_mensual']) > 0:
			etapa = 'con AV mensual'
			completar_formulario(driver, cliente, datos, configuracion, limite, con_av=True)
			adicional = extraer_resultados(driver, limite)
		registro.update(pension_con_av_web=adicional['pension'],
			saldo_acumulado_con_av_web=adicional['saldo'], modalidad_con_av_web=adicional['modalidad'])
		estado = base['estado']
		if estado != adicional['estado']:
			estado += ' | AV: ' + adicional['estado']
		if any(resultado[campo] == FALTANTE for resultado in (base, adicional) for campo in ('pension', 'saldo')):
			estado = 'INCOMPLETO | ' + estado
		registro['observaciones'] = estado + ' | comparacion AV mensual; mismo saldo inicial'
	except RechazoPensionissste as error:
		registro['observaciones'] = 'RECHAZADO | ' + str(error)
	except (ValueError, KeyError) as error:
		registro['observaciones'] = 'DATO INVALIDO | ' + str(error)[:180]
	except TimeoutException:
		registro['observaciones'] = 'TIMEOUT | ' + etapa
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


def main(argv=None):
	configuracion = argumentos_cli(cargar_configuracion(), argv)
	if sys.version_info[:3] != (3, 8, 8) or Path(sys.prefix).resolve() != ENTORNO_PROYECTO.resolve():
		raise RuntimeError('Use {}'.format(ENTORNO_PROYECTO / 'bin' / 'python'))
	clientes, columnas = leer_clientes(configuracion)
	if not clientes:
		raise ValueError('No se encontraron clientes IMSS97.')
	ruta = Path(configuracion['output']['path'])
	guardados = ids_guardados(ruta, columnas, configuracion)
	if not guardados.issubset({cliente['id_cliente'] for cliente in clientes}):
		raise ValueError('Salida con IDs fuera de la muestra seleccionada.')
	pendientes = [cliente for cliente in clientes if cliente['id_cliente'] not in guardados]
	if not pendientes:
		informar('No hay clientes pendientes.')
		return
	opciones = webdriver.ChromeOptions()
	opciones.page_load_strategy = 'eager'
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
				if indice < len(pendientes):
					time.sleep(configuracion['browser']['pause_between_records_seconds'])
	finally:
		driver.quit()
	informar('CSV guardado: {}'.format(ruta))


if __name__ == '__main__':
	main()
