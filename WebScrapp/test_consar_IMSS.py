import ast
import copy
import csv
import inspect
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from scrappers import consar_IMSS73, consar_IMSS97

SCRAPERS = (consar_IMSS97, consar_IMSS73)
AVISO = ('Si cotizaste para ambos reg\u00edmenes del Seguro Social (LSS 1973 y LSS 1997), '
    'eres un trabajador de Transici\u00f3n, por lo que seguramente te estar\u00e1s pensionando '
    'con la Ley del Seguro Social 73.')


def muestra(scraper):
    configuracion = scraper.cargar_configuracion()
    configuracion['execution']['max_clients'] = 1
    clientes, columnas = scraper.leer_clientes(configuracion)
    return configuracion, clientes[0], columnas


class ConsarImssTests(unittest.TestCase):
    def test_configuracion_y_datos_originales(self):
        for scraper in SCRAPERS:
            with self.subTest(scraper=scraper.REGIMEN):
                configuracion, cliente, _ = muestra(scraper)
                original = dict(cliente)
                datos = scraper.preparar_datos(cliente, configuracion)
                self.assertEqual(configuracion['form']['afore'], 'Banamex')
                self.assertEqual(configuracion['form']['afore_value'], '552')
                self.assertIs(configuracion['form']['include_av_in_initial_balance'], False)
                self.assertEqual(configuracion['results']['retirement_age'], 65)
                self.assertEqual(datos['anio_fil'], cliente['anio_fil'])
                self.assertIsInstance(datos['anio_fil'], str)
                self.assertEqual(datos['sem_cot'], Decimal(cliente['sem_cot']))
                self.assertEqual(datos['saldo_inicial'], Decimal(cliente['saldo_rcv']))
                self.assertEqual(cliente, original)
        _, cliente73, _ = muestra(consar_IMSS73)
        self.assertEqual((cliente73['id_cliente'], cliente73['anio_fil'], cliente73['sem_cot']),
            ('361', '1995', '1000'))

    def test_autonomia_sin_importar_scrapers(self):
        for scraper in SCRAPERS:
            arbol = ast.parse(inspect.getsource(scraper))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.ImportFrom):
                    self.assertNotIn('scrapper', nodo.module or '')
                    self.assertNotIn('consar_', nodo.module or '')
                if isinstance(nodo, ast.Import):
                    self.assertFalse(any('consar_' in alias.name or 'scrapper' in alias.name for alias in nodo.names))
            for nombre in ('cargar_configuracion', 'argumentos_cli', 'leer_clientes', 'preparar_datos'):
                self.assertEqual(getattr(scraper, nombre).__module__, scraper.__name__)

    def test_datos_invalidos_no_abren_navegador(self):
        for scraper in SCRAPERS:
            configuracion, cliente, _ = muestra(scraper)
            for valor in ('NaN', 'Infinity', '-1', ''):
                with self.subTest(scraper=scraper.REGIMEN, valor=valor):
                    driver = Mock()
                    registro = scraper.procesar_cliente(driver, dict(cliente, saldo_rcv=valor), configuracion)
                    self.assertEqual(registro['estado'], 'DATO INVALIDO')
                    self.assertEqual(registro['Pension_web'], 'NaN')
                    self.assertEqual(driver.mock_calls, [])

    def test_no_agrega_av_y_rechaza_otro_regimen(self):
        for scraper in SCRAPERS:
            configuracion, cliente, _ = muestra(scraper)
            configuracion['form']['include_av_in_initial_balance'] = True
            with self.assertRaisesRegex(ValueError, 'solo saldo_rcv'):
                scraper.preparar_datos(cliente, configuracion)
            configuracion['form']['include_av_in_initial_balance'] = False
            with self.assertRaises(ValueError):
                scraper.preparar_datos(dict(cliente, ley_bandera='OTRA'), configuracion)

    def test_slider_y_semanas_invalidos(self):
        for scraper in SCRAPERS:
            configuracion, cliente, _ = muestra(scraper)
            for retiro in (59, 68, 65.5):
                configuracion['results']['retirement_age'] = retiro
                with self.assertRaisesRegex(ValueError, 'slider CONSAR'):
                    scraper.preparar_datos(cliente, configuracion)
            configuracion['results']['retirement_age'] = 65
            with self.assertRaisesRegex(ValueError, 'semanas enteras'):
                scraper.preparar_datos(dict(cliente, sem_cot='1000.5'), configuracion)

    def test_escritura_jquery_y_rechazo_de_ajustes(self):
        for scraper in SCRAPERS:
            driver = Mock()
            driver.find_element.return_value.get_attribute.return_value = '$500,000.00'
            scraper.escribir(driver, 'txtSaldoActualAfore', '500000', scraper.time.monotonic() + 2)
            codigo, selector, valor = driver.execute_script.call_args_list[0][0]
            self.assertIn('.trigger("input").trigger("change").trigger("blur")', codigo)
            self.assertNotIn('new Event', codigo)
            self.assertEqual((selector, valor), ('#txtSaldoActualAfore', '500000'))
            driver.find_element.return_value.get_attribute.return_value = '499999'
            with self.assertRaisesRegex(scraper.BloqueoConsar, 'pagina ajusto'):
                scraper.escribir(driver, 'txtSaldoActualAfore', '500000', scraper.time.monotonic() + 2)

    def test_aviso_solo_si_es_visible(self):
        for scraper in SCRAPERS:
            driver = Mock()
            elemento = Mock(text=AVISO)
            driver.find_elements.side_effect = lambda tipo, selector: [elemento] if selector == '#msgGenracionTransicion' else []
            elemento.is_displayed.return_value = False
            scraper.comprobar_rechazo(driver)
            elemento.is_displayed.return_value = True
            with self.assertRaisesRegex(scraper.TransicionConsar, 'Seguro Social 73'):
                scraper.comprobar_rechazo(driver)

    def test_transicion_conserva_csv_sin_pension_ni_cerrar_aviso(self):
        for scraper in SCRAPERS:
            configuracion, cliente, _ = muestra(scraper)
            driver = Mock()
            with patch.object(scraper, 'completar_formulario'), patch.object(scraper,
                    'extraer_resultados', side_effect=scraper.TransicionConsar(AVISO)):
                registro = scraper.procesar_cliente(driver, cliente, configuracion)
            self.assertEqual(registro['estado'], 'TRANSICION')
            self.assertEqual(registro['leyenda_regimen_web'], AVISO)
            self.assertIn('TRANSICION | aviso Ley73', registro['observaciones'])
            for campo in ('Pension_web', 'pension_con_av_web', 'saldo_acumulado_web', 'rcv_proy_web', 'rcv_av_proy_web'):
                self.assertEqual(registro[campo], 'NaN')
            self.assertEqual(driver.mock_calls, [])
            for campo, valor in cliente.items():
                self.assertEqual(registro[campo], valor)

    def test_transicion_notificacion_real_con_plantilla_oculta(self):
        for scraper in SCRAPERS:
            driver = Mock()
            plantilla = Mock(text=AVISO)
            plantilla.is_displayed.return_value = False
            visible = Mock(text='Generacion de Transicion. Podras pensionarte bajo el regimen de la Ley 73.')
            visible.is_displayed.return_value = True
            def elementos(tipo, selector):
                if selector == '#msgGenracionTransicion':
                    return [plantilla]
                if selector == 'section.notify[data-notify="error"]':
                    return [visible]
                return []
            driver.find_elements.side_effect = elementos
            with self.assertRaisesRegex(scraper.TransicionConsar, 'Ley 73'):
                scraper.comprobar_rechazo(driver)

    def test_ley73_nunca_publica_resultado_del_motor97(self):
        scraper = consar_IMSS73
        configuracion, cliente, _ = muestra(scraper)
        with patch.object(scraper, 'completar_formulario'), patch.object(scraper,
                'extraer_resultados', return_value={'Pension_web': '13773'}):
            registro = scraper.procesar_cliente(Mock(), cliente, configuracion)
        self.assertEqual(registro['Pension_web'], 'NaN')
        self.assertEqual(registro['estado'], 'BLOQUEADO')

    def test_extrae_solo_resultados_visibles_incluyendo_fpb(self):
        scraper = consar_IMSS97
        driver = Mock()
        driver.execute_script.return_value = False
        def elementos(tipo, selector):
            valores = {'PorcentajePension': '68.9 %', 'SaldoAcumulado': '$ 2,263,627',
                'PensionMensual': '$13,773'}
            for clave, valor in valores.items():
                if clave in selector:
                    oculto = Mock(text='999999')
                    oculto.is_displayed.return_value = False
                    visible = Mock(text=valor)
                    visible.is_displayed.return_value = True
                    return [oculto, visible]
            return []
        driver.find_elements.side_effect = elementos
        self.assertEqual(scraper.extraer_resultados(driver, scraper.time.monotonic() + 2),
            {'Pension_web': '13773', 'saldo_acumulado_web': '2263627', 'tasa_remplazo_web': '68.9'})

    def test_cli_checkpoint_incremental_fsync_y_resume(self):
        for scraper in SCRAPERS:
            configuracion, cliente, _ = muestra(scraper)
            with tempfile.TemporaryDirectory(prefix='consar_imss_test_', dir='/tmp') as directorio:
                ruta = Path(directorio) / 'salida.csv'
                argumentos = ['--output', str(ruta), '--max-clientes', '1', '--timeout', '10', '--headless']
                with patch.object(scraper, 'crear_navegador') as crear, \
                        patch.object(scraper, 'completar_formulario'), \
                        patch.object(scraper, 'extraer_resultados', side_effect=scraper.TransicionConsar(AVISO)), \
                        patch.object(scraper.os, 'fsync', wraps=scraper.os.fsync) as fsync:
                    scraper.main(argumentos)
                    scraper.main(argumentos)
                    crear.assert_called_once()
                    crear.return_value.quit.assert_called_once()
                    fsync.assert_called_once()
                with ruta.open(encoding='utf-8-sig', newline='') as archivo:
                    registros = list(csv.DictReader(archivo))
                self.assertEqual(len(registros), 1)
                self.assertEqual(registros[0]['id_checkpoint'], cliente['id_cliente'])
                for campo, valor in cliente.items():
                    self.assertEqual(registros[0][campo], valor)
            self.assertFalse(ruta.exists())

    def test_rechaza_checkpoint_truncado_y_duplicado(self):
        for scraper in SCRAPERS:
            configuracion, cliente, columnas = muestra(scraper)
            with tempfile.TemporaryDirectory(dir='/tmp') as directorio:
                ruta = Path(directorio) / 'salida.csv'
                with ruta.open('w', encoding='utf-8-sig', newline='') as archivo:
                    escritor = csv.DictWriter(archivo, fieldnames=columnas)
                    escritor.writeheader()
                    registro = dict(cliente, id_checkpoint=cliente['id_cliente'])
                    escritor.writerow(registro)
                    escritor.writerow(registro)
                with self.assertRaisesRegex(ValueError, 'IDs duplicados'):
                    scraper.ids_guardados(ruta, columnas, configuracion)
                ruta.write_text('id_cliente,id_checkpoint\n361\n', encoding='utf-8-sig')
                with self.assertRaises(ValueError):
                    scraper.ids_guardados(ruta, ['id_cliente', 'id_checkpoint'], configuracion)

    def test_cli_y_proteccion_entrada(self):
        for scraper in SCRAPERS:
            configuracion, _, _ = muestra(scraper)
            resultado = scraper.argumentos_cli(copy.deepcopy(configuracion),
                ['--max-clientes', '2', '--timeout', '12', '--headless', '--output', '/tmp/consar_cli.csv'])
            self.assertEqual(resultado['execution']['max_clients'], 2)
            self.assertEqual(resultado['execution']['max_seconds_per_client'], 12)
            self.assertTrue(resultado['browser']['headless'])
            with self.assertRaises(SystemExit):
                scraper.argumentos_cli(configuracion, ['--output', configuracion['input']['path']])


if __name__ == '__main__':
    unittest.main()