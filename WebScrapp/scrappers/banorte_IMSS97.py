import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

RUTA_CONFIGURACION = Path(__file__).resolve().parents[1] / 'config' / 'banorte_IMSS97.json'
ENTORNO_PROYECTO = Path(__file__).resolve().parents[2] / '.venv-py388'
ETIQUETA = 'BANORTE IMSS97'
ESTADO_POR_CASO = {
	'Negativa de pension': 'NEGATIVA',
	'Pension garantizada': 'GARANTIZADA',
	'Pension garantizada con CS': 'GARANTIZADA | con CS',
	'Pension con complemento solidario': 'OK | complemento solidario',
	'Pension con recursos propios': 'OK | recursos propios',
}
COLUMNAS_WEB = [
	'Pension_web', 'pension_con_av_web', 'rcv_proy_web', 'rcv_av_proy_web',
	'sal_cot_web', 'tasa_remplazo_web', 'tasa_rendimiento_web',
	'densidad_cot_web', 'edad_retiro_calculo', 'observaciones',
]


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
	with RUTA_CONFIGURACION.open(encoding='utf-8') as archivo:
		configuracion = json.load(archivo)
	for seccion in ('input', 'output', 'checkpoint'):
		ruta = Path(configuracion[seccion]['path'])
		if not ruta.is_absolute():
			ruta = RUTA_CONFIGURACION.parent / ruta
		configuracion[seccion]['path'] = str(ruta.resolve())
	return configuracion


def leer_clientes(configuracion):
	# Seleccionamos la muestra sin ocultar clientes con datos invalidos.
	with open(configuracion['input']['path'],
			  encoding=configuracion['input']['encoding'], newline='') as archivo:
		lector = csv.DictReader(archivo)
		columnas = list(lector.fieldnames or [])
		clientes = []
		for cliente in lector:
			if all(cliente.get(campo) == valor
				   for campo, valor in configuracion['filters'].items()):
				clientes.append(cliente)
				if len(clientes) >= configuracion['execution']['max_clients']:
					break
	return clientes, columnas


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
		raise ValueError('Dato invalido: {}'.format(campo))
	if not resultado.is_finite() or resultado < 0:
		raise ValueError('Dato invalido: {}'.format(campo))
	return resultado


def preparar_datos(cliente, configuracion):
	for campo in ('id_cliente', 'nombre', 'ap_paterno', 'curp', 'correo', 'f_nacim',
				  'anio_fil', 'sem_cot', 'saldo_rcv', 'saldo_av',
				  'av_mensual', 'salario_mensual'):
		if not str(cliente.get(campo) or '').strip():
			raise ValueError('Falta {}'.format(campo))
	datos = {}
	for campo in ('sem_cot', 'saldo_rcv', 'saldo_av', 'av_mensual', 'salario_mensual'):
		valor = numero(cliente[campo], campo)
		if campo == 'sem_cot' and valor != valor.to_integral_value():
			raise ValueError('Semanas no enteras')
		datos[campo] = str(valor.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
	# El CSV solo proporciona el anio; el mes y dia son configurables.
	datos['fecha_cotizacion'] = '{}-{}'.format(
		int(cliente['anio_fil']), configuracion['form']['first_contribution_month_day']
	)
	datetime.strptime(datos['fecha_cotizacion'], '%Y-%m-%d')
	nacimiento = datetime.strptime(cliente['f_nacim'], '%Y-%m-%d')
	if cliente['curp'][4:10] != nacimiento.strftime('%y%m%d'):
		raise ValueError('CURP y nacimiento no coinciden')
	return datos


class RechazoBanorte(Exception):
	pass


def esperar(driver, limite):
	restante = limite - time.monotonic()
	if restante <= 0:
		raise TimeoutException()
	return WebDriverWait(driver, restante)


def visible(driver, selector):
	return [elemento for elemento in driver.find_elements(By.CSS_SELECTOR, selector)
			if elemento.is_displayed()]


def texto_visible(driver, selector):
	return ' '.join(elemento.text.strip() for elemento in visible(driver, selector))


def comprobar_rechazo(driver):
	# Detectamos bloqueos sin resolver ni omitir el CAPTCHA del sitio.
	if visible(driver, 'iframe[src*="bframe"]'):
		raise RechazoBanorte('CAPTCHA: requiere revision manual')
	for selector, mensaje in (
		('#error500', 'Banorte: error de calculo'),
		('#calculadora73', 'Banorte clasifica como Ley 73'),
		('#noPuedesPensionarteAEstaEdad', 'No permite retiro a esta edad'),
	):
		if visible(driver, selector):
			raise RechazoBanorte(mensaje)
	for elemento in visible(driver, 'input.is-invalid'):
		raise RechazoBanorte('Formulario: {}'.format(elemento.get_attribute('id')))


def escribir(driver, identificador, valor, limite):
	campo = esperar(driver, limite).until(
		EC.presence_of_element_located((By.ID, identificador))
	)
	# Emitimos los eventos de captura sin depender del teclado regional de macOS.
	driver.execute_script(
		'arguments[0].value = arguments[1];'
		'arguments[0].dispatchEvent(new Event("input", {bubbles:true}));'
		'arguments[0].dispatchEvent(new Event("change", {bubbles:true}));'
		'arguments[0].dispatchEvent(new Event("blur", {bubbles:true}));'
		'arguments[0].dispatchEvent(new Event("focusout", {bubbles:true}));',
		campo, str(valor)
	)


def pulsar(driver, selector, limite):
	boton = esperar(driver, limite).until(
		EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
	)
	driver.execute_script(
		'arguments[0].scrollIntoView({block:"center",behavior:"instant"});', boton
	)
	# Subimos en pasos cortos y comprobamos el clic despues de cada movimiento.
	esperar(driver, limite).until(lambda navegador: navegador.execute_script(
		'const rect = arguments[0].getBoundingClientRect();'
		'const target = document.elementFromPoint(rect.x + rect.width / 2, '
		'rect.y + rect.height / 2);'
		'const libre = target === arguments[0] || arguments[0].contains(target);'
		'if (!libre) window.scrollBy(0, -rect.height / 4);'
		'return libre;', boton
	))
	boton.click()


def esperar_paso(driver, selector, limite):
	def cambio(navegador):
		comprobar_rechazo(navegador)
		return visible(navegador, selector)
	return esperar(driver, limite).until(cambio)


def completar_formulario(driver, cliente, datos, configuracion, limite):
	# Abrimos una calculadora limpia para no mezclar resultados entre clientes.
	driver.set_page_load_timeout(max(1, limite - time.monotonic()))
	driver.get(configuracion['browser']['url'])
	esperar_paso(driver, '#curp', limite)
	# Con carga eager el sitio aun no enlaza sus scripts; esperamos a que termine.
	esperar(driver, limite).until(
		lambda navegador: navegador.execute_script('return document.readyState') == 'complete'
	)
	time.sleep(configuracion['browser']['page_ready_pause_seconds'])
	# Capturamos los datos sinteticos; el NSS es opcional y no se consulta.
	for identificador, valor in (
		('curp', cliente['curp']),
		('firstName', cliente['nombre']),
		('lastName', '{} {}'.format(cliente['ap_paterno'], cliente.get('ap_materno', '')).strip()),
		('email', cliente['correo']),
		('semanasCotizadasField', datos['sem_cot']),
	):
		escribir(driver, identificador, valor, limite)
	# Capturamos la fecha ISO y dejamos que el sitio aplique sus validaciones.
	escribir(driver, 'fechaCotizado', datos['fecha_cotizacion'], limite)
	fecha = driver.find_element(By.ID, 'fechaCotizado')
	if fecha.get_attribute('value') != datos['fecha_cotizacion']:
		raise RechazoBanorte('No se pudo capturar fecha de cotizacion')
	pulsar(driver, '#ctaStep1', limite)
	esperar_paso(driver, '#saldoEnCta', limite)

	# Capturamos saldos separados; no sumamos vivienda a la subcuenta RCV.
	valores = (
		('saldoEnCta', datos['saldo_rcv']),
		('saldoEnSubctaAV', datos['saldo_av']),
		('edadRetiro', configuracion['results']['retirement_age']),
		('ahorroVoluntario', datos['av_mensual']),
		('mesesCotizadosAnio', configuracion['form']['contribution_months_per_year']),
		('salarioMensual', datos['salario_mensual']),
	)
	for identificador, valor in valores:
		escribir(driver, identificador, valor, limite)
		campo = driver.find_element(By.ID, identificador)
		capturado = campo.get_attribute('value').replace(',', '')
		if not capturado or Decimal(capturado) != Decimal(str(valor)):
			raise RechazoBanorte('Banorte ajusto {}'.format(identificador))
		if not driver.execute_script('return arguments[0].validity.valid;', campo):
			raise RechazoBanorte('Fuera de rango: {}'.format(identificador))
	# Aceptamos el aviso para habilitar el calculo con datos de prueba.
	if not driver.find_element(By.ID, 'acceptance').is_selected():
		pulsar(driver, '#acceptance', limite)
	pulsar(driver, '#ctaStepTwo', limite)


def cifra(driver, selector, faltante):
	texto = texto_visible(driver, selector).replace(',', '')
	coincidencia = re.fullmatch(r'\s*\$?\s*(\d+(?:\.\d+)?)\s*%?\s*', texto)
	return coincidencia.group(1) if coincidencia else faltante


def extraer_resultados(driver, configuracion, limite):
	faltante = configuracion['missing_value']

	def listo(navegador):
		if visible(navegador, '#loading'):
			return False
		titulo = texto_visible(navegador, '#header_title').lower()
		if not titulo or titulo.strip() == '...':
			return False
		comprobar_rechazo(navegador)
		if visible(navegador, '#negativaDePension'):
			return 'Negativa de pension'
		pension = cifra(navegador, '#chartTotalSinAV', faltante)
		saldo = cifra(navegador, '#t_saldoSinAV', faltante)
		if pension != faltante and saldo != faltante:
			if 'garantizada' in titulo and 'solidario' in titulo:
				return 'Pension garantizada con CS'
			if 'garantizada' in titulo:
				return 'Pension garantizada'
			if 'solidario' in titulo:
				return 'Pension con complemento solidario'
			return 'Pension con recursos propios'
		return False

	# Esperamos cifras visibles o una negativa; nunca leemos contenedores ocultos.
	caso = esperar(driver, limite).until(listo)
	selectores = {
		'Pension_web': '#chartTotalSinAV',
		'pension_con_av_web': '#chartTotalConAV',
		'rcv_proy_web': '#t_saldoSinAV',
		'rcv_av_proy_web': '#t_saldoConAV',
		'sal_cot_web': '.resultados_SalarioMensual',
		'tasa_remplazo_web': '#t_tasaSinAV',
		'tasa_rendimiento_web': '.resultados_Rendimiento',
		'densidad_cot_web': '.resultados_DensidadCotizacion',
	}
	resultados = {columna: cifra(driver, selector, faltante)
				  for columna, selector in selectores.items()}
	if caso == 'Negativa de pension':
		resultados['rcv_proy_web'] = cifra(
			driver, '#resultados_saldoEstimadoAlRetiroSinAV', faltante
		)
		resultados['Pension_web'] = faltante
		resultados['pension_con_av_web'] = faltante
	return resultados, caso


def procesar_cliente(driver, cliente, configuracion):
	registro = dict(cliente)
	registro.update({columna: configuracion['missing_value'] for columna in COLUMNAS_WEB})
	registro['nombre_completo'] = ' '.join(
		cliente.get(campo, '').strip() for campo in ('nombre', 'ap_paterno', 'ap_materno')
		if cliente.get(campo, '').strip()
	)
	registro['id_checkpoint'] = cliente[configuracion['checkpoint']['id_field']]
	registro['edad_retiro_calculo'] = configuracion['results']['retirement_age']
	limite = time.monotonic() + configuracion['execution']['max_seconds_per_client']
	etapa = 'datos'
	try:
		if numero(cliente.get('age'), 'age') > registro['edad_retiro_calculo']:
			registro['observaciones'] = 'OMITIDO | edad {} > retiro {}'.format(
				cliente.get('age'), registro['edad_retiro_calculo']
			)
			return registro
		datos = preparar_datos(cliente, configuracion)
		etapa = 'formulario'
		completar_formulario(driver, cliente, datos, configuracion, limite)
		etapa = 'resultados'
		resultados, caso = extraer_resultados(driver, configuracion, limite)
		registro.update(resultados)
		registro['observaciones'] = ESTADO_POR_CASO.get(caso, 'OK | ' + resumir(caso))
	except ValueError as error:
		registro['observaciones'] = 'DATO INVALIDO | ' + resumir(error)
	except RechazoBanorte as error:
		registro['observaciones'] = 'RECHAZADO | ' + resumir(error)
	except TimeoutException:
		registro['observaciones'] = 'TIMEOUT | {}'.format(etapa)
	except WebDriverException as error:
		registro['observaciones'] = 'ERROR | {}'.format(type(error).__name__)
	return registro


def guardar_chunk(chunk, columnas, configuracion, ids_guardados):
	if not chunk:
		return
	# Guardamos y sincronizamos el CSV antes de actualizar el checkpoint.
	ruta = Path(configuracion['output']['path'])
	ruta.parent.mkdir(parents=True, exist_ok=True)
	cabecera = not ruta.exists() or ruta.stat().st_size == 0
	with ruta.open('a', encoding=configuracion['output']['encoding'], newline='') as archivo:
		escritor = csv.DictWriter(archivo, fieldnames=columnas)
		if cabecera:
			escritor.writeheader()
		escritor.writerows(chunk)
		archivo.flush()
		os.fsync(archivo.fileno())
	ids_guardados.update(fila['id_checkpoint'] for fila in chunk)
	ruta_checkpoint = Path(configuracion['checkpoint']['path'])
	ruta_checkpoint.parent.mkdir(parents=True, exist_ok=True)
	temporal = ruta_checkpoint.with_suffix('.json.tmp')
	with temporal.open('w', encoding='utf-8') as archivo:
		json.dump({
			'checkpoint_id': chunk[-1]['id_checkpoint'],
			'id_field': configuracion['checkpoint']['id_field'],
			'processed_count': len(ids_guardados),
			'input_path': configuracion['input']['path'],
		}, archivo, indent=2)
	temporal.replace(ruta_checkpoint)
	chunk.clear()


def main():
	validar_entorno()
	configuracion = cargar_configuracion()
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
	# Abrimos Chrome y procesamos la muestra con pausas entre clientes.
	driver = webdriver.Chrome(options=opciones)
	driver.maximize_window()
	pantalla = driver.get_window_rect()
	driver.set_window_rect(
		x=pantalla['x'], y=pantalla['y'],
		width=pantalla['width'] // 2, height=pantalla['height']
	)
	chunk = []
	try:
		for indice, cliente in enumerate(pendientes, start=1):
			registro = procesar_cliente(driver, cliente, configuracion)
			chunk.append(registro)
			informar('{}/{} | {} | {}'.format(
				previos + indice, len(clientes), registro['id_checkpoint'],
				registro['observaciones']))
			if len(chunk) >= configuracion['execution']['chunk_size']:
				guardar_chunk(chunk, columnas, configuracion, ids_guardados)
			pausa = configuracion['browser']['pause_between_records_seconds']
			if pausa > 0 and indice < len(pendientes):
				time.sleep(pausa)
	finally:
		# Conservamos registros terminados y cerramos el navegador aun si se interrumpe.
		try:
			guardar_chunk(chunk, columnas, configuracion, ids_guardados)
		finally:
			driver.quit()
	informar('CSV guardado: {}'.format(ruta))


if __name__ == '__main__':
	main()
