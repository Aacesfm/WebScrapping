import argparse
import csv
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


RAIZ = Path(__file__).resolve().parents[1]
RUTA_ENTRADAS = RAIZ.parent / 'SyntethicDataGenerator' / 'DataOutput'
URL = ('https://afore.suramexico.com/rutadelapension/nav?view=ley97/'
	   'genera-tu-estudio-provisional-y-proyecta-tu-pension')
RUTA_SALIDA = RAIZ / 'DataOutput' / 'sura_IMSS97_resultados_web.csv'
CORREO_PRUEBA = 'cliente.sintetico@example.com'
EDAD_RETIRO = 65
TIEMPO_CLIENTE = 90
PAUSA_CLIENTES = 2
VALOR_FALTANTE = 'NaN'
COLUMNAS_WEB = [
	'Pension_web', 'pension_con_av_web', 'rcv_proy_web', 'rcv_av_proy_web',
	'sal_cot_web', 'tasa_remplazo_web', 'tasa_rendimiento_web',
	'densidad_cot_web', 'edad_retiro_calculo', 'observaciones',
]


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
	# Validamos sin descartar clientes: los errores se conservaran en observaciones.
	requeridos = ['id_cliente', 'nombre', 'ap_paterno', 'f_nacim', 'genero',
				  'sem_cot', 'salario_mensual', 'saldo_rcv', 'saldo_vivienda',
				  'saldo_av', 'av_mensual']
	for campo in requeridos:
		if not str(cliente.get(campo) or '').strip():
			raise ValueError('Falta el campo {}.'.format(campo))
	if cliente['genero'] not in ('H', 'M'):
		raise ValueError('Genero distinto de H o M.')
	nacimiento = datetime.strptime(cliente['f_nacim'], '%Y-%m-%d').date()
	if nacimiento > date.today():
		raise ValueError('La fecha de nacimiento es futura.')
	datos = {'nacimiento': nacimiento}
	for campo in ('sem_cot', 'salario_mensual', 'saldo_rcv', 'saldo_vivienda',
				  'saldo_av', 'av_mensual'):
		valor = numero(cliente[campo], campo)
		if campo == 'sem_cot' and valor != valor.to_integral_value():
			raise ValueError('Las semanas cotizadas deben ser enteras.')
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


def comprobar_bloqueo(driver):
	# No resolvemos desafios CAPTCHA ni omitimos validaciones del sitio.
	for marco in driver.find_elements(By.CSS_SELECTOR, 'iframe[src*="bframe"]'):
		if marco.is_displayed():
			raise RechazoSura('Bloqueo CAPTCHA: requiere intervencion manual.')
	mensaje = texto_visible(driver, '#modalError #messageError')
	if mensaje:
		raise RechazoSura('SURA rechazo el calculo: {}.'.format(mensaje))
	errores = texto_visible(driver, '#msform .alert-danger')
	if errores:
		raise RechazoSura('Validacion del formulario SURA: {}.'.format(errores))


def escribir(driver, selector, valor, limite):
	campo = esperar(driver, limite).until(
		EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
	)
	campo.send_keys(Keys.COMMAND if sys.platform == 'darwin' else Keys.CONTROL, 'a')
	campo.send_keys(str(valor))
	campo.send_keys(Keys.TAB)


def pulsar(driver, selector, limite):
	elemento = esperar(driver, limite).until(
		EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
	)
	# Centramos el control para evitar encabezados fijos y desplazamientos animados.
	driver.execute_script(
		'arguments[0].scrollIntoView({block: "center", behavior: "instant"});', elemento
	)
	esperar(driver, limite).until(lambda navegador: navegador.execute_script(
		'const rect = arguments[0].getBoundingClientRect(); '
		'const target = document.elementFromPoint(rect.x + rect.width / 2, '
		'rect.y + rect.height / 2); '
		'return target === arguments[0] || arguments[0].contains(target);', elemento
	))
	elemento.click()


def avanzar(driver, paso, limite):
	pulsar(driver, 'a[onclick="validaPaso({});"]'.format(paso), limite)

	def cambio(navegador):
		comprobar_bloqueo(navegador)
		return navegador.find_element(By.ID, 'paso{}'.format(paso + 1)).is_displayed()

	esperar(driver, limite).until(cambio)


def completar_formulario(driver, cliente, datos, limite, edad_retiro, con_densidad):
	# Abrimos una simulacion limpia para no reutilizar resultados del cliente anterior.
	driver.set_page_load_timeout(max(1, limite - time.monotonic()))
	driver.get(URL)
	esperar(driver, limite).until(
		EC.presence_of_element_located((By.ID, 'nombreCalculadora'))
	)
	aviso = '#aviso-de-privacidad'
	esperar(driver, limite).until(
		lambda navegador: navegador.execute_script('return document.readyState') == 'complete'
	)
	if texto_visible(driver, aviso):
		pulsar(driver, aviso + ' .btn[data-dismiss="modal"]', limite)
		esperar(driver, limite).until(
			EC.invisibility_of_element_located((By.CSS_SELECTOR, aviso))
		)
	esperar(driver, limite).until(
		EC.visibility_of_element_located((By.ID, 'nombreCalculadora'))
	)

	# Capturamos datos sinteticos sin solicitar consultas de CURP/NSS ni envio de correo.
	for selector, valor in (
		('#nombreCalculadora', cliente['nombre']),
		('#apaternoCalculadora', cliente['ap_paterno']),
		('#amaternoCalculadora', cliente.get('ap_materno', '')),
		('#emailCalculadora', CORREO_PRUEBA),
		('#diaFechaCalculadora', datos['nacimiento'].day),
		('#anioFechaCalculadora', datos['nacimiento'].year),
	):
		if valor != '':
			escribir(driver, selector, valor, limite)
	Select(driver.find_element(By.ID, 'mesFechaCalculadora')).select_by_value(
		str(datos['nacimiento'].month)
	)
	# El sitio repite el id M: elegimos la primera opcion, que corresponde a Mujer.
	pulsar(driver, 'input[name="generoCalculadora"][value="{}"]'.format(
		cliente['genero']), limite)
	pulsar(driver, '#yes', limite)
	escribir(driver, '#semanasCotizadasCalculadora', datos['sem_cot'], limite)
	Select(driver.find_element(By.ID, 'edadDeRetiro')).select_by_value(str(edad_retiro))
	avanzar(driver, 1, limite)

	# Ingresamos los saldos por separado; vivienda no se suma al RCV exportado.
	for selector, campo in (
		('#salariomensualCalculadora', 'salario_mensual'),
		('#saldorcvCalculadora', 'saldo_rcv'),
		('#saldoViviendaCalculadora', 'saldo_vivienda'),
	):
		escribir(driver, selector, datos[campo], limite)
	pulsar(driver, 'input[name="ahorroVol"][value="1"]', limite)
	escribir(driver, '#ahorroVoluntarioCalculadora', datos['saldo_av'], limite)
	escribir(driver, '#ahorroMensualCalculadora', datos['av_mensual'], limite)
	pulsar(driver, 'input[name="vidaLaboral"][value="{}"]'.format(
		'1' if con_densidad else '0'), limite)
	avanzar(driver, 2, limite)
	# El boton ejecuta el reCAPTCHA normal del sitio; no se inyectan tokens.
	pulsar(driver, '#paso3 input[value="Calcular"]', limite)


def esperar_resultado(driver, limite, con_av=False):
	def resultado(navegador):
		comprobar_bloqueo(navegador)
		if texto_visible(navegador, '#saldoNegativa'):
			return 'NEGATIVA'
		if texto_visible(navegador, '#loadingPage'):
			return False
		for modalidad, panel in (('PG', '#divPensionGarantizada'),
								 ('RP', '#divRetiroProgramado')):
			sufijo = 'RCVAV' if con_av else 'RCV'
			selector = ('#pensionGarantizada' + sufijo if modalidad == 'PG'
						else '#pension' + sufijo + 'RP')
			if texto_visible(navegador, panel) and texto_visible(navegador, selector):
				return modalidad
		return False

	return esperar(driver, limite).until(resultado)


def leer_resultado(driver, modalidad, con_av=False):
	sufijo = 'RCVAV' if con_av else 'RCV'
	pension = ('#pensionGarantizada' + sufijo if modalidad == 'PG'
			   else '#pension' + sufijo + 'RP')
	tasa = '#tasa' + sufijo + ('' if modalidad == 'PG' else 'RP')
	saldo = normalizar_cifra(texto_visible(driver, '#saldoRCV' + modalidad))
	ahorro = normalizar_cifra(texto_visible(driver, '#totalAhorro' + modalidad))
	if con_av:
		total = (str(Decimal(saldo) + Decimal(ahorro))
				 if VALOR_FALTANTE not in (saldo, ahorro) else VALOR_FALTANTE)
		return {
			'pension_con_av_web': normalizar_cifra(texto_visible(driver, pension)),
			'rcv_av_proy_web': total,
		}
	return {
		'Pension_web': normalizar_cifra(texto_visible(driver, pension)),
		'rcv_proy_web': saldo,
		'tasa_remplazo_web': normalizar_cifra(texto_visible(driver, tasa)),
	}


def procesar_cliente(driver, cliente, argumentos):
	registro = dict(cliente)
	registro.update({columna: VALOR_FALTANTE for columna in COLUMNAS_WEB})
	registro['nombre_completo'] = ' '.join(
		cliente.get(campo, '').strip() for campo in ('nombre', 'ap_paterno', 'ap_materno')
		if cliente.get(campo, '').strip()
	)
	registro['edad_retiro_calculo'] = argumentos.edad_retiro
	registro['id_checkpoint'] = cliente.get('id_cliente', '')
	avisos = []
	limite = time.monotonic() + argumentos.timeout
	try:
		datos = preparar_datos(cliente)
		edad = date.today().year - datos['nacimiento'].year - (
			(date.today().month, date.today().day)
			< (datos['nacimiento'].month, datos['nacimiento'].day)
		)
		if str(edad) != cliente.get('age'):
			avisos.append('Edad CSV distinta de la fecha de nacimiento: {}.'.format(edad))
		if edad > argumentos.edad_retiro:
			avisos.append('Edad actual mayor que la edad de retiro solicitada.')
		completar_formulario(driver, cliente, datos, limite,
							 argumentos.edad_retiro, argumentos.con_densidad)
		modalidad = esperar_resultado(driver, limite)
		if modalidad == 'NEGATIVA':
			avisos.append('Se clasifico como negativa de pension en SURA. '
						  'El saldo de devolucion no se interpreta como pension.')
		else:
			registro.update(leer_resultado(driver, modalidad))
			avisos.append('Se clasifico como pension minima garantizada.' if modalidad == 'PG'
						  else 'Termino el ciclo normal: retiro programado, no renta vitalicia.')
			# Cambiamos mediante la pestana real para obtener la proyeccion con AV.
			pulsar(driver, '#liRCVAV' + ('' if modalidad == 'PG' else 'RP'), limite)
			modalidad_av = esperar_resultado(driver, limite, con_av=True)
			if modalidad_av == 'NEGATIVA':
				avisos.append('Negativa de pension al consultar RCV + AV.')
			else:
				registro.update(leer_resultado(driver, modalidad_av, con_av=True))
				avisos.append('RCV + AV: {}.'.format(
					'pension garantizada' if modalidad_av == 'PG' else 'retiro programado'))
				faltantes = [campo for campo in ('Pension_web', 'pension_con_av_web',
							 'rcv_proy_web', 'rcv_av_proy_web', 'tasa_remplazo_web')
							 if registro[campo] == VALOR_FALTANTE]
				if faltantes:
					avisos.append('Resultado incompleto: {}.'.format(', '.join(faltantes)))
	except RechazoSura as error:
		avisos.append(str(error))
	except (ValueError, KeyError) as error:
		avisos.append('Datos no validos: {}.'.format(error))
	except TimeoutException:
		avisos.append('No continuo despues de {} segundos de espera.'.format(argumentos.timeout))
	except WebDriverException as error:
		avisos.append('Error del navegador ({}): {}.'.format(
			type(error).__name__, str(error).splitlines()[0][:400]))
	avisos.append('Sin equivalente verificado para ultimo salario cotizado, '
				  'rendimiento y densidad numerica: NaN. '
				  'Importes visibles sin centavos; RCV + AV excluye vivienda. '
				  'Continuidad laboral: {}. Correo de prueba reservado; '
				  'CURP y NSS opcionales no enviados.'.format(
					  'con periodos sin aportar' if argumentos.con_densidad else 'ininterrumpida'))
	registro['observaciones'] = ' | '.join(avisos)
	return registro


def leer_clientes(ruta, maximo):
	# Conservamos los casos incompletos para documentar su rechazo en el CSV.
	with ruta.open(encoding='utf-8-sig', newline='') as archivo:
		lector = csv.DictReader(archivo)
		columnas = lector.fieldnames
		if not columnas or 'id_cliente' not in columnas:
			raise ValueError('La entrada debe contener id_cliente y una cabecera CSV.')
		clientes = []
		ids = set()
		for cliente in lector:
			if (cliente.get('regimen_estimado') != 'IMSS97'
					or cliente.get('ley_bandera') != 'LEY_97'):
				continue
			identidad = cliente.get('id_cliente', '').strip()
			if not identidad or identidad in ids:
				raise ValueError('id_cliente vacio o duplicado: {}.'.format(identidad))
			ids.add(identidad)
			clientes.append(cliente)
			if len(clientes) >= maximo:
				break
	return clientes, columnas_salida(columnas)


def ids_guardados(ruta, columnas, reanudar):
	if not ruta.exists() or ruta.stat().st_size == 0:
		return set()
	if not reanudar:
		raise FileExistsError('La salida existe. Use --reanudar o una salida nueva.')
	with ruta.open(encoding='utf-8-sig', newline='') as archivo:
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


def argumentos_cli():
	parser = argparse.ArgumentParser(
		description='Calculadora SURA IMSS97 con el layout CSV de Profuturo. '
					'La pagina guarda los datos de cada simulacion en SURA.'
	)
	parser.add_argument('--input', type=Path, help='CSV sintetico IMSS97 de entrada.')
	parser.add_argument('--output', type=Path, default=RUTA_SALIDA)
	parser.add_argument('--max-clientes', type=int, default=10)
	parser.add_argument('--edad-retiro', type=int, choices=range(60, 66), default=EDAD_RETIRO)
	parser.add_argument('--timeout', type=int, default=TIEMPO_CLIENTE)
	parser.add_argument('--pausa', type=float, default=PAUSA_CLIENTES)
	parser.add_argument('--con-densidad', action='store_true',
						help='Seleccionar periodos sin trabajo; no fija un porcentaje.')
	parser.add_argument('--headless', action='store_true')
	parser.add_argument('--reanudar', action='store_true')
	argumentos = parser.parse_args()
	if argumentos.max_clientes < 1 or argumentos.timeout < 1 or argumentos.pausa < 0:
		parser.error('Maximo y timeout deben ser positivos; pausa no puede ser negativa.')
	if argumentos.input is None:
		candidatos = sorted(RUTA_ENTRADAS.glob('*/clientes_IMSS97.csv'))
		if len(candidatos) != 1:
			parser.error('Indique --input: no se encontro un unico CSV IMSS97.')
		argumentos.input = candidatos[0]
	if argumentos.input.resolve() == argumentos.output.resolve():
		parser.error('La salida no puede ser el archivo de entrada.')
	return argumentos


def main():
	argumentos = argumentos_cli()
	if sys.version_info[:2] != (3, 8) or sys.prefix == sys.base_prefix:
		raise RuntimeError('Ejecute el script dentro de un entorno virtual Python 3.8.')
	clientes, columnas = leer_clientes(argumentos.input, argumentos.max_clientes)
	guardados = ids_guardados(argumentos.output, columnas, argumentos.reanudar)
	if not guardados.issubset({cliente['id_cliente'] for cliente in clientes}):
		raise ValueError('La salida contiene IDs fuera de la muestra de entrada seleccionada.')
	pendientes = [cliente for cliente in clientes if cliente['id_cliente'] not in guardados]
	if not pendientes:
		print('No hay clientes pendientes.')
		return
	print('Entrada: {}\nSalida: {}\nPendientes: {}'.format(
		argumentos.input, argumentos.output, len(pendientes)))
	print('SURA guarda los datos al calcular. Se usara {} y no se enviaran correos.'.format(
		CORREO_PRUEBA))
	opciones = webdriver.ChromeOptions()
	if argumentos.headless:
		opciones.add_argument('--headless=new')
	opciones.add_argument('--window-size=1440,1100')
	opciones.page_load_strategy = 'eager'
	driver = webdriver.Chrome(options=opciones)
	try:
		argumentos.output.parent.mkdir(parents=True, exist_ok=True)
		cabecera = not argumentos.output.exists() or argumentos.output.stat().st_size == 0
		# El propio CSV es el checkpoint; cada cliente se confirma en disco por separado.
		with argumentos.output.open('a', encoding='utf-8-sig', newline='') as archivo:
			escritor = csv.DictWriter(archivo, fieldnames=columnas, extrasaction='ignore')
			if cabecera:
				escritor.writeheader()
			for indice, cliente in enumerate(pendientes, 1):
				registro = procesar_cliente(driver, cliente, argumentos)
				escritor.writerow(registro)
				archivo.flush()
				os.fsync(archivo.fileno())
				print('{}/{} - Cliente {}: {}'.format(
					indice, len(pendientes), cliente['id_cliente'], registro['observaciones']))
				if 'CAPTCHA' in registro['observaciones'].upper():
					print('Lote detenido por CAPTCHA. No se intentara evadir la proteccion.')
					break
				# Respetamos una pausa configurable entre clientes para moderar las solicitudes.
				if argumentos.pausa and indice < len(pendientes):
					time.sleep(argumentos.pausa)
	finally:
		# Cerramos Chrome incluso si se interrumpe el lote o falla la escritura.
		driver.quit()
	print('CSV guardado: {}'.format(argumentos.output))


if __name__ == '__main__':
	main()
