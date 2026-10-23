"""Sura ISSSTE: captura saldos separados y compara las pestanas RCV y RCV + AV.

El saldo RCV mostrado por Sura incluye ahorro solidario. El registro ISSSTE
opcional se omite por indicacion del usuario; permanece en el CSV original.
Los resultados no publicados por la pagina se conservan como NaN.
"""

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

from sura_IMSS97 import (
	COLUMNAS_WEB as COLUMNAS_COMUNES, RechazoSura, VALOR_FALTANTE,
	escribir, esperar, ids_guardados, numero, normalizar_cifra,
	pulsar, resumir, texto_visible, unir, validar_entorno,
	leer_clientes as leer_entrada,
)

RUTA_CONFIGURACION = Path(__file__).resolve().parents[1] / 'config' / 'sura_ISSSTECuentaIndividual.json'
COLUMNAS_WEB = COLUMNAS_COMUNES + [
	'pension_renta_vitalicia_web', 'pension_renta_vitalicia_con_av_web',
	'saldo_negativa_web',
]
CAMPOS_FINANCIEROS = {
	'salariomensualCalculadora': 'salario_mensual',
	'saldofovisssteCalculadora': 'saldo_vivienda',
	'saldoavCalculadora': 'saldo_av',
	'domicialiacionmensualCalculadora': 'av_mensual',
	'bonopensionCalculadora': 'saldo_bono_pension',
	'saldorcvisssteCalculadora': 'saldo_rcv',
	'saldoahorrosolidarioCalculadora': 'saldo_ahorro_solidario',
	'aniosservicioCalculadora': 'anios_cotizados',
}


def informar(mensaje):
	print('[SURA ISSSTE] {}'.format(mensaje), flush=True)


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
	parser = argparse.ArgumentParser(description='Calculadora SURA ISSSTE Cuenta Individual.')
	parser.add_argument('--input', type=Path, default=Path(configuracion['input']['path']))
	parser.add_argument('--output', type=Path, default=Path(configuracion['output']['path']))
	parser.add_argument('--max-clientes', type=int, default=configuracion['execution']['max_clients'])
	parser.add_argument('--timeout', type=int, default=configuracion['execution']['max_seconds_per_client'])
	parser.add_argument('--edad-retiro', type=int, choices=range(55, 66),
						default=configuracion['results']['retirement_age'])
	parser.add_argument('--pausa', type=float, default=configuracion['browser']['pause_between_records_seconds'])
	parser.add_argument('--headless', action='store_true', default=configuracion['browser']['headless'])
	parser.add_argument('--reanudar', action='store_true', default=configuracion['execution']['resume'])
	parser.add_argument('--con-densidad', action='store_true', default=configuracion['form']['con_densidad'])
	argumentos = parser.parse_args(argv)
	if argumentos.max_clientes < 1 or argumentos.timeout < 1 or argumentos.pausa < 0:
		parser.error('Maximo y timeout deben ser positivos; pausa no puede ser negativa.')
	if argumentos.edad_retiro not in range(55, 66):
		parser.error('La edad de retiro debe estar entre 55 y 65.')
	if argumentos.input.resolve() == argumentos.output.resolve():
		parser.error('La salida no puede ser el archivo de entrada.')
	configuracion['input']['path'] = str(argumentos.input.expanduser().resolve())
	configuracion['output']['path'] = str(argumentos.output.expanduser().resolve())
	configuracion['execution'].update(max_clients=argumentos.max_clientes,
		max_seconds_per_client=argumentos.timeout, resume=argumentos.reanudar)
	configuracion['results']['retirement_age'] = argumentos.edad_retiro
	configuracion['browser'].update(headless=argumentos.headless,
		pause_between_records_seconds=argumentos.pausa)
	configuracion['form']['con_densidad'] = argumentos.con_densidad
	return configuracion


def leer_clientes(configuracion):
	clientes, columnas = leer_entrada(configuracion)
	for columna in COLUMNAS_WEB:
		if columna not in columnas:
			columnas.append(columna)
	return clientes, columnas


def preparar_datos(cliente):
	for campo in ('id_cliente', 'nombre', 'ap_paterno', 'correo', 'curp',
				  'f_nacim', 'genero', 'porcentaje_ahorro_solidario'):
		if not str(cliente.get(campo) or '').strip():
			raise ValueError('Falta el campo {}.'.format(campo))
	if cliente['genero'] not in ('H', 'M'):
		raise ValueError('Genero distinto de H o M.')
	nacimiento = datetime.strptime(cliente['f_nacim'], '%Y-%m-%d').date()
	if nacimiento > date.today():
		raise ValueError('La fecha de nacimiento es futura.')
	if cliente['curp'][4:10] != nacimiento.strftime('%y%m%d'):
		raise ValueError('CURP y nacimiento no coinciden.')
	datos = {'nacimiento': nacimiento}
	for campo in CAMPOS_FINANCIEROS.values():
		valor = numero(cliente.get(campo), campo)
		if campo == 'anios_cotizados' and valor != valor.to_integral_value():
			raise ValueError('Los anios de servicio deben ser enteros.')
		datos[campo] = str(valor.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
	porcentaje = numero(cliente['porcentaje_ahorro_solidario'], 'porcentaje_ahorro_solidario')
	if porcentaje not in (Decimal('1'), Decimal('2')):
		raise ValueError('SURA solo admite ahorro solidario de 1% o 2%.')
	datos['porcentaje_ahorro_solidario'] = str(int(porcentaje))
	return datos


def comprobar_bloqueo(driver):
	for marco in driver.find_elements(By.CSS_SELECTOR, 'iframe[src*="bframe"]'):
		if marco.is_displayed():
			raise RechazoSura('Bloqueo CAPTCHA: requiere intervencion manual.')
	for selector in ('#modalError #messageError', '.swal2-popup .swal2-html-container',
					 '.alert-danger'):
		mensaje = texto_visible(driver, selector)
		if mensaje:
			raise RechazoSura(mensaje)


def esperar_paso(driver, selector, limite):
	def cambio(navegador):
		comprobar_bloqueo(navegador)
		return any(elemento.is_displayed() for elemento in
				   navegador.find_elements(By.CSS_SELECTOR, selector))
	esperar(driver, limite).until(cambio)


def seleccionar(driver, identificador, valor, limite):
	select = driver.find_element(By.ID, identificador)
	opciones = select.find_elements(By.TAG_NAME, 'option')
	indice = next((indice for indice, opcion in enumerate(opciones)
				   if opcion.get_attribute('value') == str(valor)), None)
	if indice is None or indice == 0:
		raise ValueError('Opcion no disponible en {}: {}'.format(identificador, valor))
	pulsar(driver, '#' + identificador + ' ~ .select-selected', limite)
	pulsar(driver, '#{} ~ .select-items > div:nth-child({})'.format(identificador, indice), limite)
	if select.get_attribute('value') != str(valor):
		raise RechazoSura('No se pudo seleccionar {}'.format(identificador))


def completar_formulario(driver, cliente, datos, limite, configuracion):
	driver.set_page_load_timeout(max(1, limite - time.monotonic()))
	driver.get(configuracion['browser']['url'])
	esperar(driver, limite).until(EC.visibility_of_element_located((By.ID, 'nombreCalculadora')))
	esperar(driver, limite).until(lambda navegador: navegador.execute_script(
		'return document.readyState === "complete" && typeof validacionesBuc !== "undefined";'))
	for selector, valor in (
		('#nombreCalculadora', cliente['nombre']),
		('#apaternoCalculadora', cliente['ap_paterno']),
		('#amaternoCalculadora', cliente.get('ap_materno', '')),
		('#emailCalculadora', cliente['correo']),
		('#diaFechaCalculadora', datos['nacimiento'].day),
		('#anioFechaCalculadora', datos['nacimiento'].year),
		('#curpCalculadora', cliente['curp']),
	):
		if str(valor).strip():
			escribir(driver, selector, valor, limite)
	seleccionar(driver, 'mesFechaCalculadora', datos['nacimiento'].month, limite)
	pulsar(driver, 'input[name="generoCalculadora"][value="{}"]'.format(cliente['genero']), limite)
	pulsar(driver, 'input[name="vidaLaboralCalculadora"][value="{}"]'.format(
		'1' if configuracion['form']['con_densidad'] else '0'), limite)
	pulsar(driver, '[onclick="validaPaso(1);"]', limite)
	esperar_paso(driver, '#salariomensualCalculadora', limite)
	for identificador, campo in CAMPOS_FINANCIEROS.items():
		escribir(driver, '#' + identificador, datos[campo], limite)
		capturado = normalizar_cifra(driver.find_element(By.ID, identificador).get_attribute('value'))
		if capturado == VALOR_FALTANTE or Decimal(capturado) != Decimal(datos[campo]):
			raise RechazoSura('SURA ajusto {}'.format(campo))
	seleccionar(driver, 'ahorrosolidarioCalculadora', datos['porcentaje_ahorro_solidario'], limite)
	seleccionar(driver, 'edadretiroCalculadora', configuracion['results']['retirement_age'], limite)
	pulsar(driver, '[onclick="validaPaso(2);"]', limite)
	esperar_paso(driver, '#paso2 input[value="Continuar"]', limite)
	pulsar(driver, '#paso2 input[value="Continuar"]', limite)


def esperar_resultado(driver, limite, con_av=False):
	sufijo = 'RCVASAV' if con_av else 'RCVAS'
	def resultado(navegador):
		comprobar_bloqueo(navegador)
		if texto_visible(navegador, '#saldoNegativa'):
			return 'NEGATIVA'
		for modalidad, prefijo in (('PA', 'PA'), ('PG', 'PG'), ('PRPRV', 'RP')):
			if texto_visible(navegador, '#VISTA-{}-{}'.format(modalidad, sufijo)) and \
					normalizar_cifra(texto_visible(navegador, '#{}-{}'.format(prefijo, sufijo))) != VALOR_FALTANTE:
				return modalidad
		return False
	return esperar(driver, limite).until(resultado)


def leer_resultado(driver, modalidad, con_av=False):
	sufijo = 'RCVASAV' if con_av else 'RCVAS'
	prefijo = 'RP' if modalidad == 'PRPRV' else modalidad
	prefijo_saldo = 'RPRV' if modalidad == 'PRPRV' else modalidad
	pension = normalizar_cifra(texto_visible(driver, '#{}-{}'.format(prefijo, sufijo)))
	saldo = normalizar_cifra(texto_visible(driver, '#{}-RCV-{}'.format(prefijo_saldo, sufijo)))
	renta = normalizar_cifra(texto_visible(driver, '#RV-' + sufijo))
	if con_av:
		ahorro = normalizar_cifra(texto_visible(driver, '#{}-AV-{}'.format(prefijo_saldo, sufijo)))
		return {
			'pension_con_av_web': pension,
			'rcv_av_proy_web': str(Decimal(saldo) + Decimal(ahorro))
			if VALOR_FALTANTE not in (saldo, ahorro) else VALOR_FALTANTE,
			'pension_renta_vitalicia_con_av_web': renta,
		}
	return {
		'Pension_web': pension, 'rcv_proy_web': saldo,
		'tasa_remplazo_web': normalizar_cifra(texto_visible(driver, '#{}-POR-{}'.format(prefijo, sufijo))),
		'pension_renta_vitalicia_web': renta,
	}


def procesar_cliente(driver, cliente, configuracion):
	registro = dict(cliente)
	registro.update({columna: VALOR_FALTANTE for columna in COLUMNAS_WEB})
	registro['nombre_completo'] = ' '.join(cliente.get(campo, '').strip()
		for campo in ('nombre', 'ap_paterno', 'ap_materno') if cliente.get(campo, '').strip())
	registro['id_checkpoint'] = cliente[configuracion['checkpoint']['id_field']]
	registro['edad_retiro_calculo'] = configuracion['results']['retirement_age']
	limite = time.monotonic() + configuracion['execution']['max_seconds_per_client']
	estado, notas = 'ERROR', ['registro ISSSTE opcional omitido']
	try:
		datos = preparar_datos(cliente)
		hoy = date.today()
		nacimiento = datos['nacimiento']
		edad = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
		if edad > registro['edad_retiro_calculo']:
			registro['observaciones'] = 'OMITIDO | edad {} > retiro {}'.format(edad, registro['edad_retiro_calculo'])
			return registro
		completar_formulario(driver, cliente, datos, limite, configuracion)
		modalidad = esperar_resultado(driver, limite)
		if modalidad == 'NEGATIVA':
			estado = 'NEGATIVA'
			registro['saldo_negativa_web'] = normalizar_cifra(texto_visible(driver, '#saldoNegativa'))
		else:
			registro.update(leer_resultado(driver, modalidad))
			estado = {'PG': 'GARANTIZADA', 'PA': 'ANTICIPADA', 'PRPRV': 'OK'}[modalidad]
			pulsar(driver, '#tab-RCVASAV', limite)
			modalidad_av = esperar_resultado(driver, limite, con_av=True)
			if modalidad_av == 'NEGATIVA':
				notas.append('AV: NEGATIVA')
			else:
				registro.update(leer_resultado(driver, modalidad_av, con_av=True))
				if modalidad_av != modalidad:
					notas.append('AV: ' + modalidad_av)
			if any(registro[campo] == VALOR_FALTANTE for campo in
				   ('Pension_web', 'pension_con_av_web', 'rcv_proy_web', 'rcv_av_proy_web')):
				estado = 'INCOMPLETO'
	except RechazoSura as error:
		estado, notas = 'RECHAZADO', [resumir(error)]
	except (ValueError, KeyError) as error:
		estado, notas = 'DATO INVALIDO', [resumir(error)]
	except TimeoutException:
		estado, notas = 'TIMEOUT', ['{}s'.format(configuracion['execution']['max_seconds_per_client'])]
	except WebDriverException as error:
		estado, notas = 'ERROR', [type(error).__name__]
	registro['observaciones'] = unir(estado, notas)
	return registro


def main(argv=None):
	validar_entorno()
	configuracion = argumentos_cli(cargar_configuracion(), argv)
	clientes, columnas = leer_clientes(configuracion)
	if not clientes:
		raise ValueError('No se encontraron clientes ISSSTE Cuenta Individual.')
	ruta = Path(configuracion['output']['path'])
	guardados = ids_guardados(ruta, columnas, configuracion['execution']['resume'],
							 configuracion['output']['encoding'])
	if not guardados.issubset({cliente['id_cliente'] for cliente in clientes}):
		raise ValueError('La salida contiene IDs fuera de la muestra seleccionada.')
	pendientes = [cliente for cliente in clientes if cliente['id_cliente'] not in guardados]
	if not pendientes:
		informar('No hay clientes pendientes.')
		return
	informar('{} pendientes de {} | salida: {}'.format(len(pendientes), len(clientes), ruta))
	informar('SURA guarda los datos enviados; se usan los correos del CSV, sin solicitar envio de resultados.')
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
					informar('Lote detenido por CAPTCHA.')
					break
				pausa = configuracion['browser']['pause_between_records_seconds']
				if pausa and indice < len(pendientes):
					time.sleep(pausa)
	finally:
		driver.quit()
	informar('CSV guardado: {}'.format(ruta))


if __name__ == '__main__':
	main()
