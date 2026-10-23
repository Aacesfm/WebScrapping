import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


WORKSPACE = Path(__file__).resolve().parents[1]
GENERATOR_DIR = WORKSPACE / "SyntethicDataGenerator"
SCRAPPER_DIR = Path(__file__).resolve().parent / "scrappers"
sys.path.insert(0, str(GENERATOR_DIR))
sys.path.insert(0, str(SCRAPPER_DIR))

import generar_casos_pruebas_completas as generator
import banorte_IMSS73
import banorte_IMSS97
import coppel_IMSS97
import consar_IMSS97
import pensionissste_IMSS97
import pensionissste_ISSSTE
import profuturo_IMSS73
import profuturo_IMSS97
import profuturo_ISSSTECuentaIndividual
import sura_IMSS73
import sura_IMSS97
import sura_ISSSTECuentaIndividual


class ScraperInputContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        _, cases = generator.generate(seed=42)
        with patch("generar_casos_pruebas_completas.OUTPUT_DIR", cls.root):
            cls.data_dir = generator.escribir_datasets_web(cases, timestamp="contract")

    def set_input_output(self, config, input_path, output_path):
        config["input"]["path"] = str(input_path)
        config["output"]["path"] = str(output_path)
        config["execution"]["max_clients"] = 3
        config["browser"]["headless"] = True
        if "checkpoint" in config and "path" in config["checkpoint"]:
            config["checkpoint"]["path"] = str(output_path.with_name(output_path.stem + "_checkpoint.json"))
        return config

    def sura_arguments(self, input_path, output_path):
        return [
            "--input", str(input_path),
            "--output", str(output_path),
            "--max-clientes", "3",
            "--headless",
        ]

    def test_profuturo_imss97_accepts_three_mapped_clients(self):
        config = self.set_input_output(
            profuturo_IMSS97.cargar_configuracion(),
            self.data_dir / "clientes_IMSS97.csv", self.root / "p97.csv",
        )
        clients = profuturo_IMSS97.leer_clientes(config)
        self.assertEqual(len(clients), 3)
        self.assertTrue(all(profuturo_IMSS97.obtener_valor(
            clients[0], config["form"]["fields"]["nombre"]
        ) for _ in [0]))

    def test_profuturo_imss73_accepts_three_mapped_clients(self):
        config = self.set_input_output(
            profuturo_IMSS73.cargar_configuracion(),
            self.data_dir / "clientes_IMSS73.csv", self.root / "p73.csv",
        )
        clients = profuturo_IMSS73.leer_clientes(config)
        self.assertEqual(len(clients), 3)
        self.assertTrue(all(client["f_nacim"] and client["anios_cotizados"] for client in clients))

    def test_profuturo_issste_prepares_three_mapped_clients(self):
        config = self.set_input_output(
            profuturo_ISSSTECuentaIndividual.cargar_configuracion(),
            self.data_dir / "clientes_ISSSTE_Cuentas_Individuales.csv",
            self.root / "issste.csv",
        )
        clients = profuturo_ISSSTECuentaIndividual.leer_clientes(config)
        self.assertEqual(len(clients), 3)
        for client in clients:
            data, _ = profuturo_ISSSTECuentaIndividual.preparar_datos(client, config)
            self.assertIn(data["ahorro_solidario"], {"1", "2"})

    def test_banorte_imss73_prepares_three_mapped_clients(self):
        config = self.set_input_output(
            banorte_IMSS73.cargar_configuracion(),
            self.data_dir / "clientes_IMSS73.csv", self.root / "banorte73.csv",
        )
        clients, columns = banorte_IMSS73.leer_clientes(config)
        self.assertEqual(len(clients), 3)
        self.assertIn("correo", columns)
        for client in clients:
            data = banorte_IMSS73.preparar_datos(client, config)
            self.assertEqual(data["salario_mensual"], str(int(float(client["salario_mensual"]))))
            self.assertEqual(client["ley_bandera"], "LEY_73")

    def test_banorte_imss97_prepares_three_mapped_clients(self):
        config = self.set_input_output(
            banorte_IMSS97.cargar_configuracion(),
            self.data_dir / "clientes_IMSS97.csv", self.root / "banorte.csv",
        )
        clients, _ = banorte_IMSS97.leer_clientes(config)
        self.assertEqual(len(clients), 3)
        for client in clients:
            banorte_IMSS97.preparar_datos(client, config)

    def test_pensionissste_imss97_prepares_three_mapped_clients(self):
        scraper = pensionissste_IMSS97
        config = self.set_input_output(
            scraper.cargar_configuracion(), self.data_dir / 'clientes_IMSS97.csv',
            self.root / 'pensionissste97.csv',
        )
        clients, _ = scraper.leer_clientes(config)
        self.assertEqual(len(clients), 3)
        for client in clients:
            data = scraper.preparar_datos(client, config)
            self.assertEqual(float(data['anios_cotizados']), float(client['anios_cotizados']))

    def test_pensionissste_issste_prepares_three_mapped_clients(self):
        scraper = pensionissste_ISSSTE
        config = self.set_input_output(
            scraper.cargar_configuracion(), self.data_dir / 'clientes_ISSSTE_Cuentas_Individuales.csv',
            self.root / 'pensionissste_issste.csv',
        )
        clients, _ = scraper.leer_clientes(config)
        self.assertEqual(len(clients), 3)
        for client in clients:
            data = scraper.preparar_datos(client, config)
            self.assertEqual(float(data['saldo_bono_pension']), float(client['saldo_bono_pension']))
            self.assertIn(data['porcentaje_ahorro_solidario'], ('0', '1', '2'))

    def test_pensionissste_initial_balance_flag_only_adds_rcv_and_av(self):
        for scraper in (pensionissste_IMSS97, pensionissste_ISSSTE):
            config = scraper.cargar_configuracion()
            config['execution']['max_clients'] = 1
            client = scraper.leer_clientes(config)[0][0]
            client.update(saldo_rcv='500000', saldo_av='5000', saldo_vivienda='999999',
                          saldo_ahorro_solidario='888888')
            for flag, expected in ((True, '505000'), (False, '500000')):
                with self.subTest(scraper=scraper.__name__, flag=flag):
                    config['form']['include_av_in_initial_balance'] = flag
                    self.assertEqual(scraper.preparar_datos(client, config)['saldo_inicial'], expected)

    def test_pensionissste_scrapers_have_no_sibling_imports(self):
        import ast
        for scraper in (pensionissste_IMSS97, pensionissste_ISSSTE):
            tree = ast.parse(Path(scraper.__file__).read_text(encoding='utf-8'))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name.split('.')[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.append((node.module or '').split('.')[0])
            siblings = {path.stem for path in SCRAPPER_DIR.glob('*.py')}
            self.assertFalse(set(imports) & siblings)
            self.assertEqual(Path(scraper.cargar_configuracion()['output']['path']).name,
                             scraper.__name__ + '_resultados_web.csv')

    def test_pensionissste_each_script_starts_in_isolation_with_own_json(self):
        import shutil
        import subprocess
        for scraper in (pensionissste_IMSS97, pensionissste_ISSSTE):
            with self.subTest(scraper=scraper.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                scripts = root / 'scrappers'
                configs = root / 'config'
                scripts.mkdir()
                configs.mkdir()
                script = scripts / Path(scraper.__file__).name
                shutil.copy2(scraper.__file__, script)
                shutil.copy2(scraper.RUTA_CONFIGURACION, configs / scraper.RUTA_CONFIGURACION.name)
                result = subprocess.run([sys.executable, '-I', str(script), '--help'],
                                        cwd=root, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('--input', result.stdout)

    def test_pensionissste_preserves_input_and_compares_monthly_av(self):
        for scraper in (pensionissste_IMSS97, pensionissste_ISSSTE):
            config = scraper.cargar_configuracion()
            config['execution']['max_clients'] = 1
            client = scraper.leer_clientes(config)[0][0]
            base = {'pension': '10000', 'saldo': '1000000', 'tasa': '50',
                    'modalidad': 'Retiro programado', 'salario': '20000', 'estado': 'OK'}
            additional = dict(base, pension='11000', saldo='1100000')
            with patch.object(scraper, 'completar_formulario') as form, \
                    patch.object(scraper, 'extraer_resultados', side_effect=[base, additional]):
                result = scraper.procesar_cliente(Mock(), client, config)
            self.assertEqual(result['Pension_web'], '10000')
            self.assertEqual(result['pension_con_av_web'], '11000')
            self.assertEqual(result['correo'], client['correo'])
            self.assertEqual(result['saldo_rcv'], client['saldo_rcv'])
            self.assertEqual(result['rcv_proy_web'], 'NaN')
            self.assertEqual(form.call_count, 2)
            self.assertTrue(form.call_args.kwargs['con_av'])

    def test_consar_imss97_prepares_three_mapped_clients(self):
        scraper = consar_IMSS97
        config = self.set_input_output(
            scraper.cargar_configuracion(), self.data_dir / 'clientes_IMSS97.csv',
            self.root / 'consar97.csv',
        )
        clients, _ = scraper.leer_clientes(config)
        self.assertEqual(len(clients), 3)
        for client in clients:
            data = scraper.preparar_datos(client, config)
            self.assertEqual(data['anio_fil'], client['anio_fil'])
            self.assertEqual(config['form']['afore'], 'Banamex')

    def test_coppel_imss97_prepares_three_mapped_clients(self):
        config = self.set_input_output(
            coppel_IMSS97.cargar_configuracion(),
            self.data_dir / 'clientes_IMSS97.csv', self.root / 'coppel97.csv',
        )
        clients, _ = coppel_IMSS97.leer_clientes(config)
        self.assertEqual(len(clients), 3)
        for client in clients:
            data = coppel_IMSS97.preparar_datos(client)
            self.assertEqual(data['saldo_rcv'], str(int(float(client['saldo_rcv']))))
            self.assertTrue(client['correo'])

    def test_coppel_preserves_balances_and_rejects_ley73(self):
        config = coppel_IMSS97.cargar_configuracion()
        config['execution']['max_clients'] = 1
        client = coppel_IMSS97.leer_clientes(config)[0][0]
        data = coppel_IMSS97.preparar_datos(client)
        for field in ('saldo_rcv', 'saldo_av', 'saldo_vivienda', 'av_mensual'):
            self.assertEqual(float(data[field]), float(client[field]))
        self.assertEqual(len(client['nss']), 11)
        for changes in ({'ley_bandera': 'LEY_73'}, {'correo': ''}, {'sem_cot': '1.5'},
                        {'saldo_rcv': '-1'}, {'nss': '123'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                coppel_IMSS97.preparar_datos(dict(client, **changes))

    def test_coppel_cli_accepts_orchestrator_arguments(self):
        config = coppel_IMSS97.argumentos_cli(coppel_IMSS97.cargar_configuracion(), [
            '--input', 'entrada.csv', '--output', 'salida.csv',
            '--max-clientes', '2', '--timeout', '40', '--headless',
        ])
        self.assertEqual(Path(config['input']['path']).name, 'entrada.csv')
        self.assertEqual(config['execution']['max_clients'], 2)
        self.assertEqual(config['execution']['max_seconds_per_client'], 40)
        self.assertTrue(config['browser']['headless'])

    def test_coppel_records_visible_totals_without_calling_them_rcv(self):
        scraper = coppel_IMSS97
        config = scraper.cargar_configuracion()
        config['execution']['max_clients'] = 1
        client = scraper.leer_clientes(config)[0][0]
        values = {'#pension_mensual': '$19,774.00', '#monto_total_tiempo': '$3,860,530.76',
                  '#pension_mensual_recalculo': '$22,911.00', '#monto_total_tiempo2': '$4,473,032.16'}
        with patch.object(scraper, 'completar_formulario'), \
                patch.object(scraper, 'esperar_resultado', return_value='OK'), \
                patch.object(scraper, 'esperar'), patch.object(scraper, 'esperar_paso'), \
                patch.object(scraper, 'pulsar'), patch.object(scraper, 'escribir') as write, \
                patch.object(scraper, 'texto_visible', side_effect=lambda driver, selector: values.get(selector, '')):
            result = scraper.procesar_cliente(Mock(), client, config)
        self.assertEqual(result['Pension_web'], '19774.00')
        self.assertEqual(result['pension_con_av_web'], '22911.00')
        self.assertEqual(result['saldo_total_web'], '3860530.76')
        self.assertEqual(result['rcv_proy_web'], 'NaN')
        self.assertEqual(result['correo'], client['correo'])
        write.assert_called_once()
        self.assertEqual(write.call_args.args[1:3], ('#pension_ideal', client['av_mensual'].split('.')[0]))

    def test_coppel_handles_guaranteed_and_negative_pensions(self):
        scraper = coppel_IMSS97
        config = scraper.cargar_configuracion()
        config['execution']['max_clients'] = 1
        client = scraper.leer_clientes(config)[0][0]
        for state in ('NEGATIVA', 'GARANTIZADA'):
            with self.subTest(state=state), patch.object(scraper, 'completar_formulario'), \
                    patch.object(scraper, 'esperar_resultado', return_value=state), \
                    patch.object(scraper, 'texto_visible', return_value='$10,000'):
                result = scraper.procesar_cliente(Mock(), client, config)
            self.assertTrue(result['observaciones'].startswith(state))
            self.assertEqual(result['pension_con_av_web'], 'NaN')
            self.assertEqual(result['Pension_web'], '10000' if state == 'GARANTIZADA' else 'NaN')

    def test_sura_imss73_prepares_three_mapped_clients(self):
        config = sura_IMSS73.argumentos_cli(
            sura_IMSS73.cargar_configuracion(),
            self.sura_arguments(self.data_dir / "clientes_IMSS73.csv", self.root / "sura73.csv"),
        )
        clients, _ = sura_IMSS73.leer_clientes(config)
        self.assertEqual(len(clients), 3)
        for client in clients:
            sura_IMSS73.preparar_datos(client)

    def test_sura_issste_prepares_three_mapped_clients(self):
        config = sura_ISSSTECuentaIndividual.argumentos_cli(
            sura_ISSSTECuentaIndividual.cargar_configuracion(),
            self.sura_arguments(
                self.data_dir / "clientes_ISSSTE_Cuentas_Individuales.csv",
                self.root / "sura_issste.csv",
            ),
        )
        clients, _ = sura_ISSSTECuentaIndividual.leer_clientes(config)
        self.assertEqual(len(clients), 3)
        for client in clients:
            sura_ISSSTECuentaIndividual.preparar_datos(client)
            self.assertTrue(client["correo"])
            self.assertEqual(client["ley_bandera"], "LEY_ISSSTE")

    def test_sura_issste_preserves_separate_balances(self):
        config = sura_ISSSTECuentaIndividual.cargar_configuracion()
        config['input']['path'] = str(self.data_dir / 'clientes_ISSSTE_Cuentas_Individuales.csv')
        config['execution']['max_clients'] = 1
        client = sura_ISSSTECuentaIndividual.leer_clientes(config)[0][0]
        data = sura_ISSSTECuentaIndividual.preparar_datos(client)
        for field in ('saldo_rcv', 'saldo_ahorro_solidario', 'saldo_bono_pension',
                      'saldo_av', 'av_mensual', 'saldo_vivienda'):
            self.assertEqual(float(data[field]), float(client[field]))
        for changes in ({'correo': ''}, {'anios_cotizados': '1.5'},
                        {'porcentaje_ahorro_solidario': '0'}, {'saldo_rcv': '-1'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                sura_ISSSTECuentaIndividual.preparar_datos(dict(client, **changes))

    def test_sura_issste_captures_csv_email_without_optional_registration(self):
        scraper = sura_ISSSTECuentaIndividual
        config = scraper.cargar_configuracion()
        config['execution']['max_clients'] = 1
        client = scraper.leer_clientes(config)[0][0]
        data = scraper.preparar_datos(client)
        driver = Mock()
        values = {identifier: data[field] for identifier, field in scraper.CAMPOS_FINANCIEROS.items()}
        driver.find_element.side_effect = lambda by, identifier: Mock(
            get_attribute=Mock(return_value=values[identifier]))
        with patch.object(scraper, 'esperar'), patch.object(scraper, 'esperar_paso'), \
                patch.object(scraper, 'seleccionar'), patch.object(scraper, 'pulsar') as click, \
                patch.object(scraper, 'escribir') as write:
            scraper.completar_formulario(driver, client, data, 999999999, config)
        submitted = {call.args[1]: call.args[2] for call in write.call_args_list}
        self.assertEqual(submitted['#emailCalculadora'], client['correo'])
        self.assertNotIn('#nssCalculadora', submitted)
        self.assertEqual(click.call_args_list[-1].args[1], '#paso2 input[value="Continuar"]')

    def test_sura_issste_reads_programmed_retirement_and_life_annuity(self):
        scraper = sura_ISSSTECuentaIndividual
        amounts = {
            '#RP-RCVAS': '$14,196', '#RPRV-RCV-RCVAS': '$2,196,965',
            '#RP-POR-RCVAS': '70%', '#RV-RCVAS': '$13,266',
            '#RP-RCVASAV': '$15,284', '#RPRV-RCV-RCVASAV': '$2,196,965',
            '#RPRV-AV-RCVASAV': '$183,236', '#RV-RCVASAV': '$14,282',
        }
        with patch.object(scraper, 'texto_visible', side_effect=lambda driver, selector:
                          amounts.get(selector, '')):
            result = scraper.leer_resultado(Mock(), 'PRPRV')
            result_av = scraper.leer_resultado(Mock(), 'PRPRV', con_av=True)
        self.assertEqual(result['Pension_web'], '14196')
        self.assertEqual(result['pension_renta_vitalicia_web'], '13266')
        self.assertEqual(result['rcv_proy_web'], '2196965')
        self.assertEqual(result_av['pension_con_av_web'], '15284')
        self.assertEqual(result_av['rcv_av_proy_web'], '2380201')

    def test_sura_issste_records_negative_pension_and_rejections(self):
        scraper = sura_ISSSTECuentaIndividual
        config = scraper.cargar_configuracion()
        config['execution']['max_clients'] = 1
        client = scraper.leer_clientes(config)[0][0]
        with patch.object(scraper, 'completar_formulario'), \
                patch.object(scraper, 'esperar_resultado', return_value='NEGATIVA'), \
                patch.object(scraper, 'texto_visible', return_value='$100,000'):
            result = scraper.procesar_cliente(Mock(), client, config)
        self.assertTrue(result['observaciones'].startswith('NEGATIVA'))
        self.assertEqual(result['saldo_negativa_web'], '100000')
        self.assertEqual(result['Pension_web'], 'NaN')
        with patch.object(scraper, 'completar_formulario',
                          side_effect=scraper.RechazoSura('CAPTCHA manual')):
            result = scraper.procesar_cliente(Mock(), client, config)
        self.assertTrue(result['observaciones'].startswith('RECHAZADO'))
        self.assertEqual(result['correo'], client['correo'])

    def test_sura_imss97_prepares_three_mapped_clients(self):
        config = sura_IMSS97.argumentos_cli(
            sura_IMSS97.cargar_configuracion(),
            self.sura_arguments(self.data_dir / "clientes_IMSS97.csv", self.root / "sura97.csv"),
        )
        clients, _ = sura_IMSS97.leer_clientes(config)
        self.assertEqual(len(clients), 3)
        for client in clients:
            sura_IMSS97.preparar_datos(client)


if __name__ == "__main__":
    unittest.main()
