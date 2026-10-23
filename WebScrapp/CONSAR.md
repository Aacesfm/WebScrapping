# CONSAR

Cada scraper es autonomo, tiene su JSON homonimo en `config` y no importa
otros scrapers. Los tres seleccionan Banamex (552) y estan registrados en
el orquestador con su dataset correspondiente.

## Ejecucion independiente

Desde la raiz del proyecto:

```sh
.venv-py388/bin/python WebScrapp/scrappers/consar_IMSS97.py --max-clientes 1
.venv-py388/bin/python WebScrapp/scrappers/consar_IMSS73.py --max-clientes 1
.venv-py388/bin/python WebScrapp/scrappers/consar_ISSSTE.py --max-clientes 1
```

Aceptan `--input`, `--output`, `--max-clientes`, `--timeout` y `--headless`.
El CSV conserva los datos originales y sirve como checkpoint incremental.
Si cambias parametros de captura o dataset, usa una nueva salida para no
mezclar resultados: la reanudacion identifica IDs, no configuraciones.

## Ley 73

Con afiliacion 1995, CONSAR muestra que el trabajador pertenece a la
Generacion de Transicion y puede pensionarse bajo Ley73. Para calcular el
monto, la propia leyenda remite al simulador del IMSS:
https://tspi.imss.gob.mx/serviciosperifericos-web/servicio/simularPension/inicio

`consar_IMSS73.py` captura ese aviso visible en `leyenda_regimen_web`, marca
`TRANSICION` y conserva `Pension_web=NaN`. No cierra el aviso para ejecutar
el motor Ley97 ni presenta una proyeccion Ley97 como pension Ley73.

## Mapeos

- Saldo inicial: solo `saldo_rcv`; no suma vivienda ni ahorro solidario.
- IMSS: `anio_fil`, `sem_cot`, `salario_mensual`, `f_nacim` y `genero`.
- ISSSTE: `anios_cotizados`, `saldo_bono_pension` y
  `porcentaje_ahorro_solidario` (0%, 1% o 2%) en sus propios campos.
- Los correos, nombres e identificadores originales se conservan en el CSV;
  no se consultan historiales de seguridad social.
- El saldo proyectado total se guarda como `saldo_acumulado_web`, no como
  RCV puro. Los escenarios AV no capturados quedan en `NaN`.
- Rendimiento de la web: 4%; retiro configurado: 65 anios.

## Afiliacion ISSSTE

El dataset ISSSTE tiene `anio_fil` vacio, pero CONSAR lo exige. Por indicacion
del usuario, `form.missing_affiliation_start_age: 20` aplica:

`anio_afiliacion_capturado = anio_nacimiento + 20`

Solo se usa cuando falta el dato original; si existe `anio_fil`, tiene prioridad.
La regla no modifica el CSV original ni se deduce de `anios_cotizados`.
La salida registra `afiliacion_estimada` y `anio_afiliacion_capturado`.
Configurar `missing_affiliation_start_age` como `null` vuelve a bloquear los
clientes sin afiliacion. La estimacion es un supuesto autorizado, no un dato
real ni una garantia de que sea neutro para el calculo.

El salario del CSV se captura como sueldo basico de cotizacion ISSSTE.
Si CONSAR ajusta el bono por su fecha de redencion, el scraper registra el
bloqueo en lugar de sustituir el bono proporcionado.

## Validacion

Se verificaron muestras pequenas con Banamex: IMSS97 con pension visible,
Ley73 con aviso de transicion e ISSSTE con pension visible y afiliacion
estimada. Los errores de formulario y datos se conservan en `observaciones`.
No se resuelven desafios CAPTCHA ni se omiten validaciones del sitio.