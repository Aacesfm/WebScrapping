# Coppel IMSS97

La pagina declara expresamente que el simulador es para personas del IMSS
pertenecientes al Regimen de 1997. No calcula Ley 73 y no se crea un scraper
IMSS73 para no etiquetar una proyeccion Ley97 como si fuera Ley73.

## Captura

El flujo es Comienza ahora, No tengo cuenta digital, registro de nombre,
apellidos y correo del CSV, y captura de datos financieros. El telefono
opcional queda vacio. El sitio registra los datos del invitado; no se crea
una cuenta digital ni se solicita envio de resultados.

Se usan `f_nacim`, `genero`, `nss`, `sem_cot`, `salario_mensual`, `saldo_rcv`,
`saldo_av` y `saldo_vivienda`. Los importes se redondean a pesos como en los
otros scrapers. La fecha se teclea sin barras porque el formulario las inserta.
No se consulta el historial del NSS ni se sustituyen identificadores.

## Resultados

- `Pension_web`: pension del primer calculo, que ya incluye saldo AV y vivienda.
- `saldo_total_web`: total acumulado de ese calculo, no RCV puro.
- `pension_con_av_web`: pension despues de capturar `av_mensual` en
  Quiero crecer mi retiro y pulsar Recalcular.
- `saldo_total_con_av_mensual_web`: total del recalculo con aportacion mensual.
- Los campos comunes no publicados, como RCV desglosado, quedan en `NaN`.
- `GARANTIZADA` usa el panel especifico de ayuda del Gobierno, sin inventar
  una comparacion mensual no disponible en ese panel.
- `NEGATIVA`, errores de datos, rechazos y timeouts quedan en `observaciones`.

El CSV conserva todas las columnas originales y actua como checkpoint:
cada fila se sincroniza en disco y la reanudacion evita repetir IDs.

## Ejecucion

Desde la raiz del proyecto:

```sh
.venv-py388/bin/python WebScrapp/orquestador.py --sura_ISSSTECuentaIndividual 0 --coppel_IMSS97 1 --max-clientes 2
```

Se admiten `--input`, `--output`, `--max-clientes`, `--timeout`, `--headless`
y `--edad-retiro` (60 a 65). La configuracion usa IMSS97 y retiro a los 65.
La bandera Coppel queda activada sin modificar las banderas anteriores.