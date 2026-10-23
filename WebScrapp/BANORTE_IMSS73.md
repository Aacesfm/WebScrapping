# Banorte Ley 73

El scraper usa `config/banorte_IMSS73.json` y el archivo
`clientes_IMSS73.csv` del conjunto `data_20261022_215522_702264`.
Conserva todas las columnas originales, incluidos los correos del CSV.

## Captura

- CURP, nombre, apellidos, correo y semanas: valores del CSV.
- Primera cotizacion: `anio_fil` con mes y dia configurables (`07-01`, como Banorte 97).
- Salario: `salario_mensual`, redondeado a pesos como Banorte 97.
- Saldo de la subcuenta RCV: `saldo_rcv`, sin sumar vivienda ni ahorro voluntario.
- Edad de retiro: 65; meses cotizados por anio: 12, ambos configurables como Banorte 97.
- NSS opcional sin capturar; no se consulta historial de seguridad social.
- Beneficiarios, desglose SAR92/Retiro97 y Modalidad 40: estado inicial sin seleccionar.
  El dataset no proporciona estos datos; no se deducen de otras columnas.

Chrome abre a mitad del ancho disponible y con toda la altura, igual que Banorte 97.
Los valores ajustados o rechazados por la web se reportan, no se sustituyen.
Un CAPTCHA que requiere intervencion manual se registra como rechazo, sin resolverlo.

## Salida

Se agregan `Pension_web`, `sal_cot_web`, `saldo_rcv_web`,
`disposicion_recursos_web`, `pension_edad_mas_1_web`,
`pension_edad_mas_2_web`, `edad_retiro_calculo`, `observaciones`,
`nombre_completo` e `id_checkpoint`.

`saldo_rcv_web` es el saldo que muestra la pagina, no una proyeccion calculada localmente.
Los datos no disponibles se guardan como `NaN`. Las negativas y rentas vitalicias
se distinguen en `observaciones`. `OK` indica que hubo resultado visible; no distingue
pension minima garantizada porque el sitio usa el mismo panel para ambos resultados.
Los registros se sincronizan en bloques de cinco antes de actualizar el checkpoint.
La reanudacion consulta los IDs del CSV para no duplicar filas.

## Ejecucion

Desde la raiz del proyecto, con el entorno compartido:

```sh
.venv-py388/bin/python WebScrapp/scrappers/banorte_IMSS73.py --max-clientes 3
```

Para ejecutar solo Banorte Ley73 desde el orquestador:

```sh
.venv-py388/bin/python WebScrapp/orquestador.py --banorte_IMSS73 1 --banorte_IMSS97 0 --max-clientes 3
```

Se admiten `--input`, `--output`, `--max-clientes`, `--timeout` y `--headless`.
`--output` tambien selecciona un checkpoint independiente.
El JSON del orquestador activa Ley73 y conserva la activacion previa de Ley97.