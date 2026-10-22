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
        ejecutar.assert_called_once_with({'profuturo_IMSS97': ['--x']}, simular=True)

    def test_bandera_de_consola_sobrescribe_el_json(self):
        ruta = self.escribir_config({
            'profuturo_IMSS97': {'ejecutar': 1},
            'banorte_IMSS97': {'ejecutar': 0},
        })
        with patch.object(orquestador, 'ejecutar', return_value=0) as ejecutar:
            orquestador.main([
                '--config', str(ruta), '--profuturo_IMSS97', '0', '--banorte_IMSS97', '1',
            ])
        ejecutar.assert_called_once_with({'banorte_IMSS97': []}, simular=False)

    def test_json_invalido_se_rechaza(self):
        for scrappers in (
            {}, {'no_existe': {'ejecutar': 1}},
            {'banorte_IMSS97': {'ejecutar': 2}}, {'banorte_IMSS97': {'ejecutar': True}},
            {'banorte_IMSS97': {'ejecutar': 1, 'argumentos': 'x'}},
        ):
            with self.assertRaises(ValueError, msg=scrappers):
                orquestador.cargar_configuracion(self.escribir_config(scrappers))

    def test_json_del_proyecto_es_valido_y_no_ejecuta_nada_por_defecto(self):
        scrappers = orquestador.cargar_configuracion()
        self.assertEqual(len(scrappers), 6)
        self.assertEqual(sum(datos['ejecutar'] for datos in scrappers.values()), 0)

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