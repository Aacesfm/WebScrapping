import copy
import csv
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from scrappers import consar_ISSSTE as scraper


class ConsarIsssteTests(unittest.TestCase):
    def setUp(self):
        self.configuracion = scraper.cargar_configuracion()
        self.configuracion['execution']['max_clients'] = 2
        self.clientes, self.columnas = scraper.leer_clientes(self.configuracion)

    def test_csv_real_bloqueado_sin_afiliacion(self):
        self.configuracion['form']['missing_affiliation_start_age'] = None
        self.assertEqual(len(self.clientes), 2)
        for cliente in self.clientes:
            with self.assertRaisesRegex(scraper.BloqueoConsar, 'Falta anio_fil'):
                scraper.preparar_datos(cliente, self.configuracion)

    def test_estima_afiliacion_inicio20_sin_alterar_csv(self):
        originales = copy.deepcopy(self.clientes)
        contenido = Path(self.configuracion['input']['path']).read_bytes()
        for cliente in self.clientes:
            datos = scraper.preparar_datos(cliente, self.configuracion)
            self.assertTrue(datos['afiliacion_estimada'])
            self.assertEqual(datos['anio_fil'], Decimal(cliente['f_nacim'][:4]) + 20)
        self.assertEqual(self.clientes, originales)
        self.assertEqual(Path(self.configuracion['input']['path']).read_bytes(), contenido)

    def test_prefiere_afiliacion_proporcionada(self):
        datos = scraper.preparar_datos(dict(self.clientes[0], anio_fil='2003'), self.configuracion)
        self.assertEqual(datos['anio_fil'], Decimal('2003'))
        self.assertFalse(datos['afiliacion_estimada'])

    def test_mapeo_con_afiliacion_sintetica_solo_fixture(self):
        cliente = dict(self.clientes[0], anio_fil='2001')
        datos = scraper.preparar_datos(cliente, self.configuracion)
        self.assertEqual(datos['saldo_inicial'], Decimal(cliente['saldo_rcv']))
        self.assertEqual(datos['saldo_bono_pension'], Decimal(cliente['saldo_bono_pension']))
        self.assertEqual(datos['porcentaje_ahorro_solidario'], Decimal('1'))
        self.assertEqual(datos['anio_fil'], Decimal('2001'))
        self.assertEqual(self.clientes[0]['anio_fil'], '')

    def test_saldo_av_solo_con_opcion_explicita(self):
        configuracion = copy.deepcopy(self.configuracion)
        configuracion['form']['include_av_in_initial_balance'] = True
        cliente = dict(self.clientes[0], anio_fil='2001')
        datos = scraper.preparar_datos(cliente, configuracion)
        self.assertEqual(datos['saldo_inicial'], Decimal(cliente['saldo_rcv']) + Decimal(cliente['saldo_av']))

    def test_rechaza_porcentaje_invalido(self):
        cliente = dict(self.clientes[0], anio_fil='2001', porcentaje_ahorro_solidario='1.5')
        with self.assertRaisesRegex(ValueError, 'porcentaje solidario'):
            scraper.preparar_datos(cliente, self.configuracion)

    def test_bloqueo_no_toca_navegador_y_conserva_csv(self):
        self.configuracion['form']['missing_affiliation_start_age'] = None
        driver = Mock()
        cliente = self.clientes[0]
        registro = scraper.procesar_cliente(driver, cliente, self.configuracion)
        self.assertTrue(registro['observaciones'].startswith('BLOQUEADO | Falta anio_fil'))
        self.assertEqual(registro['Pension_web'], 'NaN')
        self.assertEqual(registro['id_checkpoint'], cliente['id_cliente'])
        for campo, valor in cliente.items():
            self.assertEqual(registro[campo], valor)
        self.assertEqual(driver.mock_calls, [])

    def test_resultados_visibles(self):
        driver = Mock()
        driver.execute_script.return_value = False
        textos = {'#lblPensionMensualEstimada, #lblPensionMensualEstimadaFPB': '$12,345.67',
            '#lblSaldoAcumulado, #lblSaldoAcumuladoFPB': '$2,000,000',
            '#lblPorcentajePensionMensual, #lblPorcentajePensionMensualFPB': '61.7 %'}
        def elementos(tipo, selector):
            if selector not in textos:
                return []
            elemento = Mock()
            elemento.text = textos[selector]
            elemento.is_displayed.return_value = True
            oculto = Mock(text='$999,999')
            oculto.is_displayed.return_value = False
            return [oculto, elemento]
        driver.find_elements.side_effect = elementos
        resultados = scraper.extraer_resultados(driver, scraper.time.monotonic() + 2)
        self.assertEqual(resultados, {'Pension_web': '12345.67',
            'saldo_acumulado_web': '2000000', 'tasa_remplazo_web': '61.7'})
        self.assertTrue(any('scrollIntoView' in llamada[0][0]
            for llamada in driver.execute_script.call_args_list))

    def test_limites_slider_reales(self):
        self.configuracion['results']['retirement_age'] = 64
        with self.assertRaisesRegex(ValueError, 'slider CONSAR'):
            scraper.preparar_datos(dict(self.clientes[0], anio_fil='2001'), self.configuracion)

    def test_cli_real_dos_clientes_checkpoint_y_limpieza(self):
        self.configuracion['form']['missing_affiliation_start_age'] = None
        with tempfile.TemporaryDirectory(prefix='consar_issste_test_', dir='/tmp') as directorio:
            ruta = Path(directorio) / 'resultados.csv'
            argumentos = ['--output', str(ruta), '--max-clientes', '2', '--timeout', '10', '--headless']
            with patch.object(scraper, 'crear_navegador') as navegador, \
                    patch.object(scraper, 'cargar_configuracion', return_value=self.configuracion):
                scraper.main(argumentos)
                scraper.main(argumentos)
                navegador.assert_not_called()
            with ruta.open(encoding='utf-8-sig', newline='') as archivo:
                registros = list(csv.DictReader(archivo))
            self.assertEqual(len(registros), 2)
            self.assertEqual([fila['id_checkpoint'] for fila in registros],
                [cliente['id_cliente'] for cliente in self.clientes])
            for registro in registros:
                self.assertIn('BLOQUEADO | Falta anio_fil', registro['observaciones'])
                self.assertEqual(registro['Pension_web'], 'NaN')
        self.assertFalse(ruta.exists())

    def test_captura_numerica_no_usa_event_constructor(self):
        driver = Mock()
        driver.find_element.return_value.get_attribute.return_value = '$500,000.00'
        scraper.escribir(driver, 'txtSaldoActualAfore', '500000.00', scraper.time.monotonic() + 2)
        codigo, selector, valor = driver.execute_script.call_args_list[0][0]
        self.assertIn('jQuery', codigo)
        self.assertNotIn('new Event', codigo)
        self.assertEqual((selector, valor), ('#txtSaldoActualAfore', '500000.00'))

    def test_rechaza_ajustes_del_sitio(self):
        driver = Mock()
        driver.find_element.return_value.get_attribute.return_value = '$499,999'
        with self.assertRaisesRegex(scraper.BloqueoConsar, 'pagina ajusto'):
            scraper.escribir(driver, 'txtSaldoActualAfore', '500000', scraper.time.monotonic() + 2)

    def test_persistencia_resultado_sin_inventar_av_ni_rcv(self):
        driver = Mock()
        driver.execute_script.return_value = 80
        valores = {'txtSalarioBaseCotizacion': '$20,000.00',
            'txtRendimientoReralAntesComisiones': '4 %'}
        driver.find_element.side_effect = lambda tipo, identificador: Mock(
            get_attribute=Mock(return_value=valores[identificador]))
        resultado = {'Pension_web': '10000', 'saldo_acumulado_web': '2000000',
            'tasa_remplazo_web': '50'}
        with patch.object(scraper, 'completar_formulario') as completar, \
                patch.object(scraper, 'extraer_resultados', return_value=resultado):
            registro = scraper.procesar_cliente(driver, dict(self.clientes[0], anio_fil='2001'), self.configuracion)
        completar.assert_called_once()
        self.assertTrue(registro['observaciones'].startswith('OK |'))
        self.assertEqual(registro['saldo_inicial_capturado'], self.clientes[0]['saldo_rcv'])
        self.assertEqual(registro['densidad_cot_web'], '80')
        self.assertEqual(registro['tasa_rendimiento_web'], '4')
        for campo in ('pension_con_av_web', 'rcv_proy_web', 'rcv_av_proy_web'):
            self.assertEqual(registro[campo], 'NaN')

    def test_persiste_estimacion_sin_alterar_campos_originales(self):
        cliente = self.clientes[0]
        with patch.object(scraper, 'completar_formulario', side_effect=scraper.BloqueoConsar('bono ajustado')):
            registro = scraper.procesar_cliente(Mock(), cliente, self.configuracion)
        self.assertEqual(registro['anio_afiliacion_capturado'], '2001')
        self.assertEqual(registro['afiliacion_estimada'], 1)
        self.assertEqual(registro['bono_capturado'], cliente['saldo_bono_pension'])
        for campo, valor in cliente.items():
            self.assertEqual(registro[campo], valor)
        self.assertEqual(registro['observaciones'], 'BLOQUEADO | bono ajustado')

    def test_rechaza_saldos_no_finitos(self):
        for valor in ('NaN', 'Infinity', '-1', ''):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                scraper.preparar_datos(dict(self.clientes[0], anio_fil='2001', saldo_rcv=valor), self.configuracion)


if __name__ == '__main__':
    unittest.main()