"""Ejecuta en paralelo los scrappers activados en config/orquestador.json."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import shlex
import subprocess
import sys


RAIZ = Path(__file__).resolve().parent
RUTA_CONFIGURACION = RAIZ / 'config' / 'orquestador.json'
ARCHIVOS_ENTRADA = {
    'profuturo_IMSS73': 'clientes_IMSS73.csv',
    'profuturo_IMSS97': 'clientes_IMSS97.csv',
    'profuturo_ISSSTECuentaIndividual': 'clientes_ISSSTE_Cuentas_Individuales.csv',
    'banorte_IMSS73': 'clientes_IMSS73.csv',
    'banorte_IMSS97': 'clientes_IMSS97.csv',
    'sura_IMSS73': 'clientes_IMSS73.csv',
    'sura_IMSS97': 'clientes_IMSS97.csv',
    'sura_ISSSTECuentaIndividual': 'clientes_ISSSTE_Cuentas_Individuales.csv',
    'coppel_IMSS97': 'clientes_IMSS97.csv',
    'pensionissste_IMSS97': 'clientes_IMSS97.csv',
    'pensionissste_ISSSTE': 'clientes_ISSSTE_Cuentas_Individuales.csv',
    'consar_IMSS97': 'clientes_IMSS97.csv',
    'consar_IMSS73': 'clientes_IMSS73.csv',
    'consar_ISSSTE': 'clientes_ISSSTE_Cuentas_Individuales.csv',
}


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
    parser.add_argument('--all', action='store_true', help='Ejecutar todos los scrapers configurados.')
    parser.add_argument('--data-dir', type=Path, help='Carpeta data_... con los tres CSV de entrada.')
    parser.add_argument('--output-dir', type=Path, help='Directorio para resultados de esta corrida.')
    parser.add_argument('--max-clientes', type=int, help='Limita la muestra de cada scraper.')
    parser.add_argument('--timeout', type=int, help='Segundos máximos por cliente.')
    parser.add_argument('--headless', action='store_true', help='Ejecuta navegadores sin ventana.')
    parser.add_argument('--secuencial', action='store_true', help='Ejecuta un scraper a la vez.')
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


def ejecutar(seleccionados, simular=False, secuencial=False):
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
                if secuencial:
                    resultados[nombre] = procesos[nombre].wait()
                    del procesos[nombre]
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
    data_dir = argumentos.data_dir.expanduser().resolve() if argumentos.data_dir else None
    output_dir = argumentos.output_dir
    if data_dir:
        if not data_dir.is_dir():
            raise FileNotFoundError('No existe la carpeta de entrada: {}'.format(data_dir))
        if output_dir is None:
            run_stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            output_dir = RAIZ / 'DataOutput' / '{}_web_{}'.format(data_dir.name, run_stamp)
        output_dir = output_dir.expanduser().resolve()
        if not argumentos.simular:
            output_dir.mkdir(parents=True, exist_ok=True)
    for nombre, datos in scrappers.items():
        bandera = getattr(argumentos, nombre)
        ejecutar_scraper = bandera == 1 if bandera is not None else (
            argumentos.all or datos['ejecutar'] == 1
        )
        if not ejecutar_scraper:
            continue
        scraper_args = list(datos.get('argumentos', []))
        if data_dir:
            input_file = data_dir / ARCHIVOS_ENTRADA[nombre]
            if not input_file.is_file():
                raise FileNotFoundError('Falta el CSV requerido: {}'.format(input_file))
            scraper_args.extend([
                '--input', str(input_file),
                '--output', str(output_dir / '{}_resultados_web.csv'.format(nombre)),
            ])
            if argumentos.max_clientes is not None:
                scraper_args.extend(['--max-clientes', str(argumentos.max_clientes)])
            if argumentos.timeout is not None:
                scraper_args.extend(['--timeout', str(argumentos.timeout)])
            if argumentos.headless:
                scraper_args.append('--headless')
        elif argumentos.max_clientes is not None:
            scraper_args.extend(['--max-clientes', str(argumentos.max_clientes)])
        if argumentos.timeout is not None and not data_dir:
            scraper_args.extend(['--timeout', str(argumentos.timeout)])
        if argumentos.headless and not argumentos.data_dir:
            scraper_args.append('--headless')
        seleccionados[nombre] = scraper_args
    return ejecutar(
        seleccionados,
        simular=argumentos.simular,
        secuencial=argumentos.secuencial,
    )


if __name__ == '__main__':
    sys.exit(main())