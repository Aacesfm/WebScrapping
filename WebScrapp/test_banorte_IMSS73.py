import csv
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'scrappers'))
import banorte_IMSS73 as scraper


class BanorteLey73Tests(unittest.TestCase):
    def setUp(self):
        self.config = scraper.cargar_configuracion()
        self.config['execution']['max_clients'] = 1
        self.client = scraper.leer_clientes(self.config)[0][0]

    def test_solo_prepara_campos_del_csv_sin_sumar_otros_saldos(self):
        client = dict(self.client, saldo_rcv='100.50', saldo_av='900', saldo_vivienda='800')
        data = scraper.preparar_datos(client, self.config)
        self.assertEqual(data['saldo_rcv'], '101')
        self.assertEqual(set(data), {'sem_cot', 'saldo_rcv', 'salario_mensual', 'fecha_cotizacion'})
        self.assertEqual(client['correo'], self.client['correo'])

    def test_rechaza_correo_faltante_curp_inconsistente_y_semanas_fraccionarias(self):
        for changes in ({'correo': ''}, {'curp': 'AAAA000101AAAAAA00'}, {'sem_cot': '1.5'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                scraper.preparar_datos(dict(self.client, **changes), self.config)

    def test_argumentos_del_orquestador_actualizan_configuracion_y_checkpoint(self):
        config = scraper.argumentos_cli(self.config, [
            '--input', 'entrada.csv', '--output', 'salida.csv',
            '--max-clientes', '3', '--timeout', '40', '--headless',
        ])
        self.assertEqual(Path(config['input']['path']).name, 'entrada.csv')
        self.assertEqual(Path(config['checkpoint']['path']).name, 'salida_checkpoint.json')
        self.assertEqual(config['execution']['max_clients'], 3)
        self.assertEqual(config['execution']['max_seconds_per_client'], 40)
        self.assertTrue(config['browser']['headless'])

    def test_captura_detecta_cambios_del_sitio_en_campo_oculto(self):
        driver = Mock()
        driver.find_element.return_value.get_attribute.return_value = '999'
        with patch.object(scraper, 'escribir'), self.assertRaises(scraper.RechazoBanorte):
            scraper.capturar_numero(driver, 'saldoInicialEnCuentaString', '500000',
                                   time.monotonic() + 1, 'saldoInicialEnCuenta')

    def test_resultados_normales_negativa_y_renta_vitalicia(self):
        for case, visible_selector, pension, balance in (
            ('OK', None, '23448', '500000'),
            ('NEGATIVA', '#negativaDePension', 'NaN', '600000'),
            ('RENTA VITALICIA', '#rentaVitalicia', '8000', '700000'),
        ):
            amounts = {
                '#pensionCalculo1': '23448', '#resultados_saldoEnCuentaAfore': '500000',
                '#saldoAcumuladoEnCTA': '600000', '#saldoAcumuladoEnCTARV': '700000',
                '#saldoRentaVitalicia': '8000',
            }
            with self.subTest(case=case), patch.object(scraper, 'comprobar_rechazo'), \
                    patch.object(scraper, 'visible', side_effect=lambda driver, selector:
                                 [Mock()] if selector == visible_selector else []), \
                    patch.object(scraper, 'cifra', side_effect=lambda driver, selector, missing:
                                 amounts.get(selector, missing)):
                result, state = scraper.extraer_resultados(Mock(), self.config, time.monotonic() + 1)
            self.assertEqual(state, case)
            self.assertEqual(result['Pension_web'], pension)
            self.assertEqual(result['saldo_rcv_web'], balance)
            if case != 'OK':
                self.assertEqual(result['pension_edad_mas_1_web'], 'NaN')

    def test_captcha_se_registra_sin_intentar_resolverlo(self):
        with patch.object(scraper, 'completar_formulario',
                          side_effect=scraper.RechazoBanorte('CAPTCHA: requiere revision manual')):
            result = scraper.procesar_cliente(Mock(), self.client, self.config)
        self.assertEqual(result['Pension_web'], 'NaN')
        self.assertEqual(result['observaciones'], 'RECHAZADO | CAPTCHA: requiere revision manual')
        self.assertEqual(result['correo'], self.client['correo'])

    def test_chunk_y_reanudacion_no_duplican_clientes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'resultados.csv'
            config = scraper.argumentos_cli(self.config, ['--output', str(output)])
            with patch.object(scraper, 'completar_formulario'), \
                    patch.object(scraper, 'extraer_resultados', return_value=({'Pension_web': '123'}, 'OK')):
                record = scraper.procesar_cliente(Mock(), self.client, config)
            columns = scraper.columnas_salida(list(self.client))
            chunk = [record]
            ids = set()
            scraper.guardar_chunk(chunk, columns, config, ids)
            self.assertEqual(chunk, [])
            self.assertEqual(ids, {self.client['id_cliente']})
            with output.open(encoding='utf-8-sig', newline='') as file:
                self.assertEqual(len(list(csv.DictReader(file))), 1)
            with open(config['checkpoint']['path'], encoding='utf-8') as file:
                self.assertEqual(json.load(file)['processed_count'], 1)
            with patch.object(scraper, 'validar_entorno'), \
                    patch.object(scraper, 'cargar_configuracion', return_value=config), \
                    patch.object(scraper.webdriver, 'Chrome') as chrome:
                scraper.main([])
            chrome.assert_not_called()


if __name__ == '__main__':
    unittest.main()