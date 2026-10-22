"""Ejecuta en paralelo los scrappers activados en config/orquestador.json."""

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys


RAIZ = Path(__file__).resolve().parent
RUTA_CONFIGURACION = RAIZ / 'config' / 'orquestador.json'


def cargar_configuracion(ruta=RUTA_CONFIGURACION):
    with ruta.open(encoding='utf-8') as archivo:
        scrappers = json.load(archivo).get('scrappers')
    if not isinstance(scrappers, dict) or not scrappers:
        raise ValueError('Defina al menos un scrapper en "scrappers".')
    for nombre, datos in scrappers.items():
        if not (RAIZ / 'scrappers' / (nombre + '.py')).is_file():
            raise ValueError('No existe el scrapper: {}.'.format(nombre))
        if type(datos.get('ejecutar')) is not int or datos['ejecutar'] not in (0, 1):
            raise ValueError('{}: "ejecutar" debe ser 0 o 1.'.format(nombre))
        argumentos = datos.get('argumentos', [])
        if not isinstance(argumentos, list) or not all(isinstance(a, str) for a in argumentos):
            raise ValueError('{}: "argumentos" debe ser una lista de textos.'.format(nombre))
    return scrappers


def leer_argumentos(nombres, argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=RUTA_CONFIGURACION)
    for nombre in nombres:
        parser.add_argument(
            '--' + nombre, type=int, choices=(0, 1),
            help='Sobrescribe la bandera del JSON para esta ejecucion.',
        )
    parser.add_argument(
        '--simular', action='store_true',
        help='Mostrar los comandos sin ejecutar los scrappers.',
    )
    return parser.parse_args(argv)


def detener_procesos(procesos):
    for proceso in procesos.values():
        if proceso.poll() is None:
            proceso.terminate()
    for proceso in procesos.values():
        try:
            proceso.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proceso.kill()
            proceso.wait()


def ejecutar(seleccionados, simular=False):
    """Inicia todos los scrappers antes de esperar; seleccionados: {nombre: [argumentos]}."""
    if not seleccionados:
        print('No hay scrappers activados. Ponga "ejecutar": 1 en alguno.')
        return 0

    procesos = {}
    resultados = {}
    try:
        for nombre, argumentos in seleccionados.items():
            comando = [sys.executable, '-u', str(RAIZ / 'scrappers' / (nombre + '.py'))] + argumentos
            print('[{}] {}'.format(nombre, shlex.join(comando)), flush=True)
            if simular:
                continue
            try:
                procesos[nombre] = subprocess.Popen(comando, cwd=str(RAIZ))
            except OSError as error:
                print('[{}] No se pudo iniciar: {}'.format(nombre, error),
                      file=sys.stderr)
                resultados[nombre] = 1

        for nombre, proceso in procesos.items():
            resultados[nombre] = proceso.wait()
    except KeyboardInterrupt:
        print('\nInterrupcion recibida. Deteniendo los scrappers...', flush=True)
        detener_procesos(procesos)
        return 130
    except BaseException:
        detener_procesos(procesos)
        raise

    for nombre, codigo in resultados.items():
        print('[{}] {} (codigo {}).'.format(
            nombre, 'Finalizado' if codigo == 0 else 'Error', codigo,
        ), flush=True)
    return 1 if any(resultados.values()) else 0


def main(argv=None):
    previo = argparse.ArgumentParser(add_help=False)
    previo.add_argument('--config', type=Path, default=RUTA_CONFIGURACION)
    scrappers = cargar_configuracion(previo.parse_known_args(argv)[0].config)
    argumentos = leer_argumentos(scrappers, argv)
    seleccionados = {}
    for nombre, datos in scrappers.items():
        bandera = getattr(argumentos, nombre)
        if (datos['ejecutar'] if bandera is None else bandera) == 1:
            seleccionados[nombre] = datos.get('argumentos', [])
    return ejecutar(seleccionados, simular=argumentos.simular)


if __name__ == '__main__':
    sys.exit(main())