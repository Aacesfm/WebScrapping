# ISSSTE: muestra de 10 clientes con retiro a 65

## Alcance y supuestos

Se inspecciono https://afore.profuturo.mx/calculadora y se selecciono ISSSTE.
Se procesaron los primeros 10 clientes del CSV ISSSTE de la carpeta
`20261021_172249_771771`, sin utilizar ni importar los programas IMSS.
La muestra es consecutiva, no aleatoria ni representativa de toda la poblacion.

Esta prueba uso **retiro a los 65 anos** para todos los clientes y porcentaje
solidario del CSV redondeado al entero mas cercano, half_up (1.5 pasa a 2).
Solo se envian porcentajes 1 o 2. No se modifica el CSV de origen.
Los importes se enviaron redondeados a pesos enteros, con criterio half_up.
No se exige coincidencia entre las etiquetas del generador y la respuesta web;
ambas se conservan, sin corregir ni reclasificar el CSV original.

## Mapeo comprobado

| Campo web | Columna CSV / criterio |
| --- | --- |
| Nombre | nombre + ap_paterno + ap_materno |
| Fecha de nacimiento | f_nacim, convertida a dia/mes/ano |
| Edad | La calcula la web; no se escribe age |
| Genero | genero: H/M a Hombre/Mujer |
| Anos que has cotizado | anios_cotizados |
| Ahorro voluntario | av_mensual: la ayuda indica aportacion mensual |
| Ahorro solidario | porcentaje_ahorro_solidario redondeado half_up a 1 o 2 |
| Bono de Pension | saldo_bono_pension |
| Saldo actual en Afore | saldo_rcv, sin sumar otras subcuentas |
| Salario mensual | salario_mensual |
| Edad de retiro | 65, configurada en el JSON |

No se encontraron campos independientes para saldo_ahorro_solidario, saldo_av,
saldo_vivienda, numero ISSSTE, NSS, CURP, correo, entidad, semanas cotizadas o
ano de afiliacion. No se envian identificadores ni correo innecesarios.

## Resultados observados

| ID | Edad | Anos cotizados | Escenario estimado CSV | Respuesta web | Pension mensual sin/con AV |
| --- | --- | --- | --- | --- | --- |
| 2 | 68 | 17 | Negativa | Intente mas tarde | No visible |
| 3 | 64 | 25 | Garantizada | Alerta de garantizada | $6,923 / $6,923 |
| 9 | 66 | 32 | Recursos propios | Intente mas tarde | No visible |
| 19 | 63 | 30 | Recursos propios | Alerta de garantizada | $6,923 / $6,923 |
| 22 | 65 | 17 | Negativa | Alerta de negativa | No visible |
| 25 | 62 | 26 | Recursos propios | Alerta de garantizada | $6,923 / $6,923 |
| 27 | 65 | 16 | Negativa | Alerta de negativa | No visible |
| 43 | 60 | 25 | Garantizada | Alerta de garantizada | $6,923 / $6,923 |
| 44 | 61 | 28 | Recursos propios | Resultado sin alerta | $9,259 / $9,909 |
| 45 | 63 | 27 | Recursos propios | Alerta de garantizada | $6,923 / $6,923 |

Total: 2 negativas, 5 alertas de garantizada, 1 resultado sin alerta y 2 alertas
genericas "Por favor intentelo mas tarde".
No hubo timeouts ni errores de navegador en estos 10 registros.
Las pensiones ausentes se conservaron como NaN, no como cero.
Los clientes 2 y 9 tienen edad actual superior a 65; se envio 65 sin alterar
sus fechas de nacimiento. La alerta generica no permite confirmar su causa.

## Datos confirmados y caso pendiente

1. **Porcentaje solidario:** 22, 27 y 45 envian 1%; los demas, 2%. El generador
   actual produce porcentajes continuos; solo se convierten al enviar a la web.
2. **Edad de retiro:** siempre 65, tambien para los mayores de esa edad.
3. **Saldo Afore:** exclusivamente saldo_rcv, confirmado por el usuario.
4. **Ahorro voluntario:** saldo_av es saldo acumulado, verificado en el generador;
   av_mensual es una aportacion mensual distinta. La web pide la mensual, por
   lo que se envia av_mensual. Los saldos acumulados de 3 ($91,455.69) y 25
   ($1,408,749.37) permanecen en la salida, sin sumarse al RCV ni enviarse como
   mensualidad. No hay campo separado para saldo_av.
5. **Bono:** saldo_bono_pension si existe en el CSV: 7 clientes tienen $350,000
   y 3 tienen cero. Se envia separado del RCV.
6. **Alerta generica:** los clientes 2 y 9 no obtuvieron pension visible.
   Conservar sus alertas para una eventual comprobacion manual, sin inferir
   negativa de pension ni modificar la edad configurada.

## Archivos y ejecucion

### Layout de nuevas salidas

Se conservan las columnas originales del CSV y se agregan nombre_completo,
las ocho metricas financieras usadas tambien en IMSS73 e IMSS97,
edad_retiro_calculo, incremento_pension_con_ahorro_voluntario_y_solidario,
estado_web y observaciones. Las alertas conocidas se resumen en observaciones; una alerta
no identificada conserva su mensaje para poder revisarla.

No se agregan url_resultado, texto_resultado_web, datos_enviados_json,
exploratorio ni alerta_web. Los CSV generados previamente no se modifican.
ISSSTE no agrega id_checkpoint porque aun no implementa reanudacion.

Columnas incorporadas:

- edad_retiro_calculo: en los tres programas, sin confundirla con age.
  IMSS73 usa results.retirement_age; ISSSTE usa form.edad_retiro.
  IMSS97 registra la referencia results.retirement_age=65 del JSON; no agrega
  un campo de edad al formulario ni modifica el calculo de la web.
- incremento_pension_con_ahorro_voluntario_y_solidario: solo en ISSSTE,
  pension_con_av_web menos Pension_web, en pesos mensuales. Queda NaN si
  falta cualquiera de los dos valores; puede ser cero si las pensiones coinciden.

estado_web se mantiene solo en ISSSTE. No se incorpora a los otros dos.
El nuevo esquema no es compatible con reanudar CSV anteriores de IMSS:
usar rutas nuevas de salida y checkpoint para conservar los archivos previos.

### Evidencia de las pruebas anteriores

- Programa: `scrappers/profuturo_ISSSTECuentaIndividual.py`.
- Configuracion: `config/profuturo_ISSSTECuentaIndividual.json`.
- Evidencia actual: `DataOutput/profuturo_ISSSTE_muestra_10_retiro65.csv`, con datos originales,
  datos enviados en JSON, alertas y texto completo del resultado.
- Evidencia historica: `DataOutput/profuturo_ISSSTE_muestra_10.csv`, conservada
   sin sobrescribir; corresponde a los supuestos de la primera exploracion.

Opcionalmente se puede fijar el porcentaje de un cliente en `form.manual_por_cliente`:

```json
{
   "2": {"ahorro_solidario": 2}
}
```

No es necesario agregar ajustes manuales para ejecutar esta muestra.
La edad se toma de form.edad_retiro, no de ajustes por cliente.
Para repetir la prueba, cambiar primero output.path a un nombre nuevo:
el programa no sobrescribe archivos existentes. El indicador --exploratorio
solo informa en consola y no cambia los valores configurados ni agrega columnas.

Desde la raiz del workspace:

```bash
.venv-py38/bin/python WebScrapp/scrappers/profuturo_ISSSTECuentaIndividual.py
.venv-py38/bin/python WebScrapp/scrappers/profuturo_ISSSTECuentaIndividual.py --exploratorio
```

Validado con Python 3.8.20 y Selenium 4.27.1 ya instalados. No se instalaron
dependencias. La declaracion compartida `selenium>=4.30,<5` no coincide con este
entorno y requiere revision antes de reinstalar en Python 3.8; no se modifico
porque afecta tambien a los otros programas.