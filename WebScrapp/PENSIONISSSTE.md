# PENSIONISSSTE

Los scrapers IMSS97 e ISSSTE Cuenta Individual son autonomos: cada archivo
contiene su lectura CSV, validaciones, flujo Selenium, extraccion y guardado.
Ninguno importa al otro ni a otros scrapers. Cada uno carga su JSON homonimo
desde `config`, independientemente del directorio de ejecucion.
Requieren el entorno compartido Python 3.8.8 y Selenium del proyecto.

## Ejecucion independiente

Desde la raiz del proyecto:

```sh
.venv-py388/bin/python WebScrapp/scrappers/pensionissste_IMSS97.py --max-clientes 2
.venv-py388/bin/python WebScrapp/scrappers/pensionissste_ISSSTE.py --max-clientes 2
```

Tambien estan registrados en el orquestador con sus respectivos datasets:

```sh
.venv-py388/bin/python WebScrapp/orquestador.py --max-clientes 2 --secuencial
```

Ambos admiten `--input`, `--output`, `--max-clientes`, `--timeout` y `--headless`.
Los JSON conservan las banderas anteriores del orquestador y activan estos dos.
Retiro por defecto a los 65, modificable en `results.retirement_age`.

## Saldo inicial configurable

En cada JSON, `form.include_av_in_initial_balance` controla el saldo capturado:

- `true`: `saldo_rcv + saldo_av`, por indicacion del usuario.
- `false`: solo `saldo_rcv`.

No se suman vivienda, saldo solidario ni bono al saldo inicial.
El bono ISSSTE (`saldo_bono_pension`) se captura en su campo propio, en pesos.
El porcentaje solidario se toma de `porcentaje_ahorro_solidario` (0, 1 o 2%).
Los anios cotizados se toman de `anios_cotizados`, no se deducen de semanas.
La pagina no pide correo, NSS ni registro ISSSTE: se conservan en la salida,
sin enviarlos ni consultarlos. Los importes se redondean a pesos.

## Comparacion y salida

Se hacen dos estimaciones manteniendo el mismo saldo inicial:

- `Pension_web`: sin aportacion voluntaria mensual nueva.
- `pension_con_av_web`: con `av_mensual` del CSV.
- En ISSSTE, ambas mantienen el mismo porcentaje solidario y bono.
- Si `av_mensual` es cero, se reutiliza la primera estimacion.

`saldo_acumulado_web` y `saldo_acumulado_con_av_web` contienen los totales
mostrados por la pagina, no un desglose RCV. Las columnas RCV comunes quedan
en `NaN` para no presentar esos totales como RCV puro.
`saldo_inicial_capturado` y `saldo_inicial_incluye_av` registran el mapeo usado.
Se guardan las modalidades de ambas estimaciones y los errores en `observaciones`.
Los campos no extraidos de la web permanecen en `NaN`.

El propio CSV actua como checkpoint, sincronizado despues de cada cliente.
La reanudacion evita IDs duplicados y rechaza layouts o filas incompletas.
Si cambias el dataset, edad, bandera de saldo o cualquier supuesto de captura,
usa una nueva ruta de salida: el checkpoint identifica IDs, no configuraciones.

## Alcance

La pagina abre directamente el formulario, sin cuenta digital ni pantallas de Coppel.
La metodologia observada usa cuentas individuales y retiro programado, con
densidad del 80%, rendimiento real antes de comisiones del 4% y comision del 0.52%.
Estos son supuestos del sitio, no del scraper, y pueden cambiar.
No se implementa Ley73 ni ISSSTE Decimo Transitorio: no se encontro un flujo
para esas formulas en esta calculadora. No se resuelven desafios CAPTCHA.