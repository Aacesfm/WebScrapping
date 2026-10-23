import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import orquestador


class OrquestadorTests(unittest.TestCase):
    def escribir_config(self, scrappers):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        ruta = Path(carpeta.name) / 'orquestador.json'
        ruta.write_text(json.dumps({'scrappers': scrappers}), encoding='utf-8')
        return ruta

    def test_json_selecciona_solo_los_activados_con_sus_argumentos(self):
        ruta = self.escribir_config({
            'profuturo_IMSS97': {'ejecutar': 1, 'argumentos': ['--x']},
            'banorte_IMSS97': {'ejecutar': 0},
        })
        with patch.object(orquestador, 'ejecutar', return_value=0) as ejecutar:
            codigo = orquestador.main(['--config', str(ruta), '--simular'])
        self.assertEqual(codigo, 0)
        ejecutar.assert_called_once_with(
            {'profuturo_IMSS97': ['--x']}, simular=True, secuencial=False,
        )

    def test_bandera_de_consola_sobrescribe_el_json(self):
        ruta = self.escribir_config({
            'profuturo_IMSS97': {'ejecutar': 1},
            'banorte_IMSS97': {'ejecutar': 0},
        })
        with patch.object(orquestador, 'ejecutar', return_value=0) as ejecutar:
            orquestador.main([
                '--config', str(ruta), '--profuturo_IMSS97', '0', '--banorte_IMSS97', '1',
            ])
        ejecutar.assert_called_once_with(
            {'banorte_IMSS97': []}, simular=False, secuencial=False,
        )

    def test_json_invalido_se_rechaza(self):
        for scrappers in (
            {}, {'no_existe': {'ejecutar': 1}},
            {'banorte_IMSS97': {'ejecutar': 2}}, {'banorte_IMSS97': {'ejecutar': True}},
            {'banorte_IMSS97': {'ejecutar': 1, 'argumentos': 'x'}},
        ):
            with self.assertRaises(ValueError, msg=scrappers):
                orquestador.cargar_configuracion(self.escribir_config(scrappers))

    def test_json_del_proyecto_es_valido_y_conserva_seleccion_configurada(self):
        scrappers = orquestador.cargar_configuracion()
        self.assertEqual(len(scrappers), 14)
        self.assertTrue(all(datos['ejecutar'] in (0, 1) for datos in scrappers.values()))

    def test_all_con_data_dir_enruta_csv_limite_y_headless(self):
        scrappers = {
            'profuturo_IMSS73': {'ejecutar': 0, 'argumentos': []},
            'profuturo_IMSS97': {'ejecutar': 0, 'argumentos': []},
            'profuturo_ISSSTECuentaIndividual': {'ejecutar': 0, 'argumentos': []},
            'banorte_IMSS73': {'ejecutar': 0, 'argumentos': []},
            'banorte_IMSS97': {'ejecutar': 0, 'argumentos': []},
            'sura_IMSS73': {'ejecutar': 0, 'argumentos': []},
            'sura_IMSS97': {'ejecutar': 0, 'argumentos': []},
            'sura_ISSSTECuentaIndividual': {'ejecutar': 0, 'argumentos': []},
            'coppel_IMSS97': {'ejecutar': 0, 'argumentos': []},
            'pensionissste_IMSS97': {'ejecutar': 0, 'argumentos': []},
            'pensionissste_ISSSTE': {'ejecutar': 0, 'argumentos': []},
            'consar_IMSS97': {'ejecutar': 0, 'argumentos': []},
            'consar_IMSS73': {'ejecutar': 0, 'argumentos': []},
            'consar_ISSSTE': {'ejecutar': 0, 'argumentos': []},
        }
        config_path = self.escribir_config(scrappers)
        data_dir = Path(tempfile.mkdtemp())
        for filename in set(orquestador.ARCHIVOS_ENTRADA.values()):
            (data_dir / filename).write_text('id_cliente\n1\n', encoding='utf-8')

        with patch.object(orquestador, 'ejecutar', return_value=0) as ejecutar:
            codigo = orquestador.main([
                '--config', str(config_path), '--all', '--data-dir', str(data_dir),
                '--max-clientes', '3', '--timeout', '40', '--headless', '--simular',
            ])

        self.assertEqual(codigo, 0)
        seleccionados = ejecutar.call_args.args[0]
        self.assertEqual(set(seleccionados), set(scrappers))
        for name, arguments in seleccionados.items():
            input_index = arguments.index('--input') + 1
            limit_index = arguments.index('--max-clientes') + 1
            self.assertEqual(Path(arguments[input_index]).name,
                             orquestador.ARCHIVOS_ENTRADA[name])
            self.assertEqual(arguments[limit_index], '3')
            timeout_index = arguments.index('--timeout') + 1
            self.assertEqual(arguments[timeout_index], '40')
            self.assertIn('--headless', arguments)

    def test_ejecucion_secuencial_espera_cada_scraper_antes_de_iniciar_otro(self):
        events = []

        def start(command, cwd):
            events.append('inicio')
            process = Mock()
            process.wait.side_effect = lambda: events.append('espera') or 0
            return process

        with patch.object(orquestador.subprocess, 'Popen', side_effect=start):
            code = orquestador.ejecutar(
                {'profuturo_IMSS97': [], 'banorte_IMSS97': []}, secuencial=True,
            )
        self.assertEqual(code, 0)
        self.assertEqual(events, ['inicio', 'espera', 'inicio', 'espera'])

    def test_simulacion_y_seleccion_vacia_no_inician_procesos(self):
        with patch.object(orquestador.subprocess, 'Popen') as iniciar:
            self.assertEqual(orquestador.ejecutar({}, simular=False), 0)
            self.assertEqual(orquestador.ejecutar({'profuturo_IMSS97': []}, True), 0)
        iniciar.assert_not_called()

    def test_inicia_todos_antes_de_esperar_y_conserva_argumentos(self):
        eventos = []

        def iniciar(comando, cwd):
            nombre = comando[2]
            eventos.append('inicio')
            self.assertEqual(comando[:2], [orquestador.sys.executable, '-u'])
            self.assertEqual(cwd, str(orquestador.RAIZ))
            if nombre.endswith('sura_IMSS97.py'):
                self.assertEqual(comando[3:], ['--input', '/entrada con espacios.csv'])
            proceso = Mock()
            proceso.wait.side_effect = lambda: eventos.append('espera') or 0
            return proceso

        with patch.object(orquestador.subprocess, 'Popen', side_effect=iniciar):
            codigo = orquestador.ejecutar({
                'profuturo_IMSS97': [],
                'sura_IMSS97': ['--input', '/entrada con espacios.csv'],
            })
        self.assertEqual(codigo, 0)
        self.assertEqual(eventos, ['inicio', 'inicio', 'espera', 'espera'])

    def test_error_de_un_scrapper_no_impide_esperar_al_otro(self):
        primero = Mock()
        primero.wait.return_value = 2
        segundo = Mock()
        segundo.wait.return_value = 0
        with patch.object(orquestador.subprocess, 'Popen', side_effect=[primero, segundo]):
            codigo = orquestador.ejecutar({'profuturo_IMSS97': [], 'banorte_IMSS97': []})
        self.assertEqual(codigo, 1)
        segundo.wait.assert_called_once_with()

    def test_error_de_inicio_no_impide_iniciar_el_siguiente(self):
        proceso = Mock()
        proceso.wait.return_value = 0
        with patch.object(orquestador.subprocess, 'Popen',
                          side_effect=[OSError('fallo de inicio'), proceso]):
            codigo = orquestador.ejecutar({'profuturo_IMSS97': [], 'banorte_IMSS97': []})
        self.assertEqual(codigo, 1)
        proceso.wait.assert_called_once_with()

    def test_interrupcion_detiene_los_procesos_iniciados(self):
        proceso = Mock()
        proceso.poll.return_value = None
        proceso.wait.side_effect = [KeyboardInterrupt, 0]
        with patch.object(orquestador.subprocess, 'Popen', return_value=proceso):
            self.assertEqual(orquestador.ejecutar({'profuturo_IMSS97': []}), 130)
        proceso.terminate.assert_called_once_with()

    def test_proceso_que_no_termina_se_fuerza_a_cerrar(self):
        proceso = Mock()
        proceso.poll.return_value = None
        proceso.wait.side_effect = [subprocess.TimeoutExpired('scrapper', 5), 0]
        orquestador.detener_procesos({'profuturo_IMSS97': proceso})
        proceso.terminate.assert_called_once_with()
        proceso.kill.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()