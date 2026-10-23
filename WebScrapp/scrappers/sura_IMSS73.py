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


RUTA_CONFIGURACION = Path(__file__).resolve().parents[1] / 'config' / 'sura_IMSS73.json'
ENTORNO_PROYECTO = Path(__file__).resolve().parents[2] / '.venv-py388'
ETIQUETA = 'SURA IMSS73'
VALOR_FALTANTE = 'NaN'
COLUMNAS_WEB = [
	'Pension_web', 'pension_con_av_web', 'rcv_proy_web', 'rcv_av_proy_web',
	'sal_cot_web', 'tasa_remplazo_web', 'tasa_rendimiento_web',
	'densidad_cot_web', 'edad_retiro_calculo', 'observaciones',
]


def validar_entorno():
	if sys.version_info[:3] != (3, 8, 8) or Path(sys.prefix).resolve() != ENTORNO_PROYECTO.resolve():
		raise RuntimeError('Ejecute con el entorno virtual compartido: {}'.format(
			ENTORNO_PROYECTO / 'bin' / 'python'))


def informar(mensaje):
	print('[{}] {}'.format(ETIQUETA, mensaje), flush=True)


def resumir(texto, limite=70):
	texto = ' '.join(str(texto).split())
	return texto if len(texto) <= limite else texto[:limite - 3] + '...'


def unir(estado, notas):
	return estado + (' | ' + '; '.join(notas) if notas else '')


def cargar_configuracion():
	with RUTA_CONFIGURACION.open(encoding='utf-8') as archivo:
		configuracion = json.load(archivo)
	for seccion in ('input', 'output'):
		ruta = Path(configuracion[seccion]['path'])
		if not ruta.is_absolute():
			ruta = RUTA_CONFIGURACION.parent / ruta
		configuracion[seccion]['path'] = str(ruta.resolve())
	return configuracion


def columnas_salida(columnas_entrada):
	columnas = list(columnas_entrada)
	for columna in ['nombre_completo'] + COLUMNAS_WEB + ['id_checkpoint']:
		if columna not in columnas:
			columnas.append(columna)
	return columnas


def numero(valor, campo):
	try:
		resultado = Decimal(str(valor))
	except InvalidOperation:
		raise ValueError('Valor no numerico en {}: {}.'.format(campo, valor))
	if not resultado.is_finite() or resultado < 0:
		raise ValueError('{} debe ser un numero finito no negativo.'.format(campo))
	return resultado


def preparar_datos(cliente):
	# Validamos sin excluir filas para registrar los datos incorrectos en observaciones.
	requeridos = [
		'id_cliente', 'nombre', 'ap_paterno', 'f_nacim', 'genero',
		'salario_mensual', 'saldo_rcv', 'saldo_vivienda', 'saldo_av', 'av_mensual',
	]
	for campo in requeridos:
		if not str(cliente.get(campo) or '').strip():
			raise ValueError('Falta el campo {}.'.format(campo))
	if cliente['genero'] not in ('H', 'M'):
		raise ValueError('Genero distinto de H o M.')

	nacimiento = datetime.strptime(cliente['f_nacim'], '%Y-%m-%d').date()
	if nacimiento > date.today():
		raise ValueError('La fecha de nacimiento es futura.')

	semanas = cliente.get('sem_cot', '').strip()
	anio_inicio = cliente.get('anio_fil', '').strip()
	if semanas:
		semanas_numero = numero(semanas, 'sem_cot')
		if semanas_numero != semanas_numero.to_integral_value():
			raise ValueError('Las semanas cotizadas deben ser enteras.')
	elif not anio_inicio:
		raise ValueError('Se requiere sem_cot o anio_fil para el primer paso.')

	datos = {
		'nacimiento': nacimiento,
		'semanas': str(int(numero(semanas, 'sem_cot'))) if semanas else '',
		'anio_inicio': anio_inicio,
	}
	for campo in ('salario_mensual', 'saldo_rcv', 'saldo_vivienda', 'saldo_av', 'av_mensual'):
		valor = numero(cliente[campo], campo)
		datos[campo] = str(valor.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
	return datos


def normalizar_cifra(texto):
	limpio = str(texto).replace('$', '').replace(',', '').replace('%', '').strip()
	if not re.fullmatch(r'\d+(?:\.\d+)?', limpio):
		return VALOR_FALTANTE
	return limpio


class RechazoSura(Exception):
	pass


def esperar(driver, limite):
	restante = limite - time.monotonic()
	if restante <= 0:
		raise TimeoutException('Tiempo maximo por cliente agotado.')
	return WebDriverWait(driver, restante)


def texto_visible(driver, selector):
	return ' | '.join(dict.fromkeys(
		elemento.text.strip()
		for elemento in driver.find_elements(By.CSS_SELECTOR, selector)
		if elemento.is_displayed() and elemento.text.strip()
	))


def escribir(driver, selector, valor, limite):
	campo = esperar(driver, limite).until(
		EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
	)
	if str(valor) == '0':
		# La pagina bloquea teclear 0 como primer digito; lo asignamos con eventos.
		driver.execute_script(
			'arguments[0].value = "0";'
			'arguments[0].dispatchEvent(new Event("input", {bubbles: true}));'
			'arguments[0].dispatchEvent(new Event("change", {bubbles: true}));', campo)
		return
	campo.send_keys(Keys.COMMAND if sys.platform == 'darwin' else Keys.CONTROL, 'a')
	campo.send_keys(str(valor))
	campo.send_keys(Keys.TAB)


def seleccionar_radio(driver, selector, limite):
	radio = esperar(driver, limite).until(
		EC.presence_of_element_located((By.CSS_SELECTOR, selector))
	)
	etiqueta = radio.find_element(By.XPATH, './ancestor::label[1]')
	esperar(driver, limite).until(lambda _: etiqueta.is_displayed())
	driver.execute_script(
		'arguments[0].scrollIntoView({block: "center", behavior: "instant"});', etiqueta)
	etiqueta.click()


def cerrar_aviso_si_aparece(driver, limite):
	# El aviso "Estimado Usuario" bloquea el formulario hasta pulsar CONTINUAR.
	boton = esperar(driver, limite).until(EC.element_to_be_clickable(
		(By.CSS_SELECTOR, '#aviso-de-privacidad .btn-secondary')))
	boton.click()
	esperar(driver, limite).until(
		EC.invisibility_of_element_located((By.ID, 'aviso-de-privacidad')))


def comprobar_bloqueo(driver):
	# No omitimos controles de acceso ni intentamos resolver desafíos CAPTCHA.
	for marco in driver.find_elements(By.CSS_SELECTOR, 'iframe[src*="bframe"]'):
		if marco.is_displayed():
			raise RechazoSura('Bloqueo CAPTCHA: requiere intervencion manual.')
	mensaje = texto_visible(driver, '#modalError #messageError')
	if mensaje:
		raise RechazoSura('SURA rechazo el calculo: {}.'.format(mensaje))


def ingresar_paso_personal(driver, cliente, datos, limite, configuracion):
	# Abrimos la calculadora Ley 73 y esperamos el formulario real del primer paso.
	driver.set_page_load_timeout(max(1, limite - time.monotonic()))
	driver.get(configuracion['browser']['url'])
	cerrar_aviso_si_aparece(driver, limite)
	esperar(driver, limite).until(
		EC.visibility_of_element_located((By.ID, 'nombreCalculadora'))
	)

	# Capturamos los datos requeridos y usamos un correo reservado para pruebas.
	for selector, valor in (
		('#nombreCalculadora', cliente['nombre']),
		('#apaternoCalculadora', cliente['ap_paterno']),
		('#amaternoCalculadora', cliente.get('ap_materno', '')),
		('#emailCalculadora', configuracion['form']['email']),
		('#diaFechaCalculadora', datos['nacimiento'].day),
		('#anioFechaCalculadora', datos['nacimiento'].year),
	):
		escribir(driver, selector, valor, limite)
	Select(driver.find_element(By.ID, 'mesFechaCalculadora')).select_by_value(
		str(datos['nacimiento'].month)
	)

	# El sitio repite el id M; usamos el valor del radio dentro del formulario.
	seleccionar_radio(
		driver, '#paso1 input[name="generoCalculadora"][value="{}"]'.format(
			cliente['genero']), limite
	)
	if datos['semanas']:
		seleccionar_radio(driver, '#paso1 input[name="semanas-cotizadas"][value="1"]', limite)
		escribir(driver, '#semanasCotizadasCalculadora', datos['semanas'], limite)
	else:
		seleccionar_radio(driver, '#paso1 input[name="semanas-cotizadas"][value="2"]', limite)
		escribir(driver, '#anioCalculadora', datos['anio_inicio'], limite)

	selector_edad = esperar(driver, limite).until(
		EC.presence_of_element_located((By.ID, 'edadRetiro'))
	)
	esperar(driver, limite).until(
		lambda _: any(
			opcion.get_attribute('value') == str(configuracion['results']['retirement_age'])
			for opcion in selector_edad.find_elements(By.TAG_NAME, 'option')
		)
	)
	Select(selector_edad).select_by_value(str(configuracion['results']['retirement_age']))

	# Continuamos al paso de saldos solo después de que SURA valide el formulario.
	boton = esperar(driver, limite).until(
		EC.element_to_be_clickable((By.CSS_SELECTOR, '#paso1 [name="next"]'))
	)
	boton.click()
	esperar(driver, limite).until(
		lambda navegador: navegador.find_element(By.ID, 'paso2').is_displayed()
	)
	comprobar_bloqueo(driver)


def ingresar_paso_saldos(driver, datos, limite, proyeccion):
	# SURA separa las subcuentas de vivienda; el CSV solo aporta un saldo agregado.
	for selector, valor in (
		('#salariomensualCalculadora', datos['salario_mensual']),
		('#saldorcvCalculadora', datos['saldo_rcv']),
		('#saldoSAR92', '0'),
		('#saldoVivienda92', '0'),
		('#saldoViv97', datos['saldo_vivienda']),
	):
		escribir(driver, selector, valor, limite)

	con_av = proyeccion == 'con-av' or (
		proyeccion == 'auto'
		and (Decimal(datos['saldo_av']) > 0 or Decimal(datos['av_mensual']) > 0)
	)
	seleccionar_radio(
		driver, '#paso2 input[name="ahorroVol"][value="{}"]'.format(
			'1' if con_av else '0'), limite
	)
	if con_av:
		escribir(driver, '#ahorroVoluntarioCalculadora', datos['saldo_av'], limite)
		escribir(driver, '#ahorroMensualCalculadora', datos['av_mensual'], limite)
	return con_av


def calcular(driver, limite):
	# El tercer paso realiza el cálculo y SURA indica que guarda los datos enviados.
	boton = esperar(driver, limite).until(
		EC.element_to_be_clickable((By.CSS_SELECTOR, '#paso2 [name="next"]'))
	)
	boton.click()
	esperar(driver, limite).until(
		lambda navegador: navegador.find_element(By.ID, 'paso3').is_displayed()
	)
	comprobar_bloqueo(driver)
	calcular_boton = esperar(driver, limite).until(
		EC.element_to_be_clickable((By.CSS_SELECTOR, '#paso3 input[name="next"]'))
	)
	calcular_boton.click()

	def resultado(navegador):
		comprobar_bloqueo(navegador)
		if texto_visible(navegador, '#saldoNegativa'):
			return 'NEGATIVA'
		for modalidad, selector in (
			('PG', '#paso4'), ('RV', '#paso5'),
		):
			panel = navegador.find_element(By.CSS_SELECTOR, selector)
			if panel.is_displayed():
				return modalidad
		return False

	return esperar(driver, limite).until(resultado)


def leer_resultado(driver, modalidad, con_av):
	sufijo = 'Garantizada' if modalidad == 'PG' else 'Vitalicia'
	pension_selector = '#pension' + sufijo
	saldo_selector = '#saldoRCV' + sufijo
	ahorro_selector = '#saldoAhorroVoluntario' + sufijo
	tasa_selector = '#porcentajeSueldo' + sufijo
	pension = normalizar_cifra(texto_visible(driver, pension_selector))
	saldo = normalizar_cifra(texto_visible(driver, saldo_selector))
	ahorro = normalizar_cifra(texto_visible(driver, ahorro_selector))
	datos = {
		'Pension_web': VALOR_FALTANTE,
		'pension_con_av_web': VALOR_FALTANTE,
		'rcv_proy_web': saldo,
		'rcv_av_proy_web': VALOR_FALTANTE,
		'tasa_remplazo_web': normalizar_cifra(texto_visible(driver, tasa_selector)),
	}
	if con_av:
		datos['pension_con_av_web'] = pension
		if saldo != VALOR_FALTANTE and ahorro != VALOR_FALTANTE:
			datos['rcv_av_proy_web'] = str(Decimal(saldo) + Decimal(ahorro))
	else:
		datos['Pension_web'] = pension
	return datos


def procesar_cliente(driver, cliente, configuracion):
	registro = dict(cliente)
	registro.update({columna: VALOR_FALTANTE for columna in COLUMNAS_WEB})
	registro['nombre_completo'] = ' '.join(
		cliente.get(campo, '').strip()
		for campo in ('nombre', 'ap_paterno', 'ap_materno')
		if cliente.get(campo, '').strip()
	)
	registro['edad_retiro_calculo'] = configuracion['results']['retirement_age']
	registro['id_checkpoint'] = cliente.get(configuracion['checkpoint']['id_field'], '')
	estado = 'ERROR'
	notas = []
	limite = time.monotonic() + configuracion['execution']['max_seconds_per_client']
	try:
		datos = preparar_datos(cliente)
		edad = date.today().year - datos['nacimiento'].year - (
			(date.today().month, date.today().day)
			< (datos['nacimiento'].month, datos['nacimiento'].day)
		)
		if str(edad) != cliente.get('age'):
			notas.append('edad CSV distinta de la calculada ({})'.format(edad))
		if edad >= 65:
			registro['observaciones'] = unir('OMITIDO', notas + ['edad >= 65, SURA no calcula'])
			return registro

		ingresar_paso_personal(
			driver, cliente, datos, limite, configuracion
		)
		con_av = ingresar_paso_saldos(driver, datos, limite, configuracion['form']['proyeccion'])
		modalidad = calcular(driver, limite)
		if modalidad == 'NEGATIVA':
			estado = 'NEGATIVA'
		else:
			registro.update(leer_resultado(driver, modalidad, con_av))
			estado = 'GARANTIZADA' if modalidad == 'PG' else 'OK'
			notas.append(('con AV' if con_av else 'sin AV') + ('' if modalidad == 'PG' else ', vitalicia'))
			faltantes = [
				campo for campo in (
					'Pension_web' if not con_av else 'pension_con_av_web',
					'rcv_proy_web',
				) if registro[campo] == VALOR_FALTANTE
			]
			if faltantes:
				estado = 'INCOMPLETO'
				notas.append('falta ' + ', '.join(faltantes))
		if Decimal(datos['salario_mensual']) > 82513:
			notas.append('salario topado a 82513')
	except RechazoSura as error:
		estado = 'RECHAZADO'
		notas.append(resumir(error))
	except (ValueError, KeyError) as error:
		estado = 'DATO INVALIDO'
		notas.append(resumir(error))
	except TimeoutException:
		estado = 'TIMEOUT'
		notas.append('{}s'.format(configuracion['execution']['max_seconds_per_client']))
	except WebDriverException as error:
		estado = 'ERROR'
		notas.append(type(error).__name__)
	registro['observaciones'] = unir(estado, notas)
	return registro


def leer_clientes(configuracion):
	# Conservamos clientes incompletos para escribir su causa en el CSV de resultados.
	with open(configuracion['input']['path'],
			  encoding=configuracion['input']['encoding'], newline='') as archivo:
		lector = csv.DictReader(archivo)
		columnas = lector.fieldnames
		if not columnas or 'id_cliente' not in columnas:
			raise ValueError('La entrada debe contener id_cliente y una cabecera CSV.')
		clientes = []
		ids = set()
		for cliente in lector:
			if not all(cliente.get(campo) == valor
					   for campo, valor in configuracion['filters'].items()):
				continue
			identidad = cliente.get('id_cliente', '').strip()
			if not identidad or identidad in ids:
				raise ValueError('id_cliente vacio o duplicado: {}.'.format(identidad))
			ids.add(identidad)
			clientes.append(cliente)
			if len(clientes) >= configuracion['execution']['max_clients']:
				break
	return clientes, columnas_salida(columnas)


def ids_guardados(ruta, columnas, reanudar, encoding='utf-8-sig'):
	if not ruta.exists() or ruta.stat().st_size == 0:
		return set()
	if not reanudar:
		raise FileExistsError('La salida existe. Use --reanudar o una salida nueva.')
	with ruta.open(encoding=encoding, newline='') as archivo:
		lector = csv.DictReader(archivo)
		if lector.fieldnames != columnas:
			raise ValueError('La salida existente no tiene el mismo layout que la entrada.')
		guardados = set()
		for fila in lector:
			identidad = fila.get('id_checkpoint')
			if (None in fila or any(valor is None for valor in fila.values())
					or not identidad or identidad != fila.get('id_cliente')
					or identidad in guardados):
				raise ValueError('La salida contiene un registro incompleto o duplicado.')
			guardados.add(identidad)
		return guardados


def argumentos_cli(configuracion=None, argv=None):
	if configuracion is None:
		configuracion = cargar_configuracion()
	parser = argparse.ArgumentParser(
		description='Calculadora SURA IMSS73 con layout CSV compatible con IMSS97.'
	)
	parser.add_argument('--input', type=Path, default=Path(configuracion['input']['path']))
	parser.add_argument('--output', type=Path, default=Path(configuracion['output']['path']))
	parser.add_argument('--max-clientes', type=int, default=configuracion['execution']['max_clients'])
	parser.add_argument('--edad-retiro', type=int, choices=range(60, 66),
						default=configuracion['results']['retirement_age'])
	parser.add_argument('--timeout', type=int,
						default=configuracion['execution']['max_seconds_per_client'])
	parser.add_argument('--pausa', type=float,
						default=configuracion['browser']['pause_between_records_seconds'])
	parser.add_argument(
		'--proyeccion', choices=('auto', 'sin-av', 'con-av'),
		default=configuracion['form']['proyeccion'],
		help='Una sola proyeccion por cliente; auto usa AV cuando hay saldo o aportacion.',
	)
	parser.add_argument('--headless', action='store_true', default=configuracion['browser']['headless'])
	parser.add_argument('--reanudar', action='store_true', default=configuracion['execution']['resume'])
	argumentos = parser.parse_args(argv)
	if argumentos.max_clientes < 1 or argumentos.timeout < 1 or argumentos.pausa < 0:
		parser.error('Maximo y timeout deben ser positivos; pausa no puede ser negativa.')
	if argumentos.edad_retiro not in range(60, 66):
		parser.error('La edad de retiro debe estar entre 60 y 65.')
	if argumentos.proyeccion not in ('auto', 'sin-av', 'con-av'):
		parser.error('La proyeccion debe ser auto, sin-av o con-av.')
	if argumentos.input.resolve() == argumentos.output.resolve():
		parser.error('La salida no puede ser el archivo de entrada.')
	configuracion['input']['path'] = str(argumentos.input.resolve())
	configuracion['output']['path'] = str(argumentos.output.resolve())
	configuracion['execution'].update(
		max_clients=argumentos.max_clientes, max_seconds_per_client=argumentos.timeout,
		resume=argumentos.reanudar)
	configuracion['results']['retirement_age'] = argumentos.edad_retiro
	configuracion['browser'].update(
		headless=argumentos.headless, pause_between_records_seconds=argumentos.pausa)
	configuracion['form']['proyeccion'] = argumentos.proyeccion
	return configuracion


def main():
	validar_entorno()
	configuracion = argumentos_cli(cargar_configuracion())
	clientes, columnas = leer_clientes(configuracion)
	if not clientes:
		raise ValueError('No se encontraron clientes sinteticos IMSS Ley 73.')
	ruta_salida = Path(configuracion['output']['path'])
	guardados = ids_guardados(ruta_salida, columnas, configuracion['execution']['resume'],
							 configuracion['output']['encoding'])
	if not guardados.issubset({cliente['id_cliente'] for cliente in clientes}):
		raise ValueError('La salida contiene IDs fuera de la muestra seleccionada.')
	pendientes = [cliente for cliente in clientes if cliente['id_cliente'] not in guardados]
	if not pendientes:
		informar('No hay clientes pendientes.')
		return

	informar('{} pendientes de {} | salida: {}'.format(
		len(pendientes), len(clientes), ruta_salida))
	informar('Aviso: SURA guarda los datos enviados; no se resuelven CAPTCHA.')
	opciones = webdriver.ChromeOptions()
	if configuracion['browser']['headless']:
		opciones.add_argument('--headless=new')
	opciones.add_argument('--window-size=' + configuracion['browser']['window_size'])
	opciones.page_load_strategy = configuracion['browser']['page_load_strategy']
	driver = webdriver.Chrome(options=opciones)
	try:
		ruta_salida.parent.mkdir(parents=True, exist_ok=True)
		cabecera = not ruta_salida.exists() or ruta_salida.stat().st_size == 0
		# El CSV es el checkpoint; cada fila se confirma en disco antes de seguir.
		with ruta_salida.open('a', encoding=configuracion['output']['encoding'], newline='') as archivo:
			escritor = csv.DictWriter(archivo, fieldnames=columnas, extrasaction='ignore')
			if cabecera:
				escritor.writeheader()
			for indice, cliente in enumerate(pendientes, 1):
				registro = procesar_cliente(driver, cliente, configuracion)
				escritor.writerow(registro)
				archivo.flush()
				os.fsync(archivo.fileno())
				informar('{}/{} | {} | {}'.format(
					len(guardados) + indice, len(clientes), cliente['id_cliente'],
					registro['observaciones']))
				if 'CAPTCHA' in registro['observaciones'].upper():
					informar('Lote detenido por CAPTCHA.')
					break
				pausa = configuracion['browser']['pause_between_records_seconds']
				if pausa and indice < len(pendientes):
					time.sleep(pausa)
	finally:
		# Cerramos Chrome incluso si se interrumpe el lote o falla la escritura.
		driver.quit()
	informar('CSV guardado: {}'.format(ruta_salida))


if __name__ == '__main__':
	main()
