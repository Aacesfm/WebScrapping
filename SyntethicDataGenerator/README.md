# Generador de datos sintéticos

## Estructura

- `generador_clientes_sinteticos.ipynb`: orquesta la carga de insumos, la generación, el control de calidad y la exportación a `DataOutput/`.
- `config/`: todos los parámetros ajustables (`parametros.py`) y catálogos (`catalogos.py`): rutas, semilla, `N_CLIN`, fecha de corte, proporción por perfil, distribuciones de edad, salario y saldos, probabilidades, tasas de aportación y montos legales de referencia.
- `generador/`: lógica (historial laboral por perfil, saldos RCV/AV/vivienda, reglas pensionarias, identificadores sintéticos y validación).
- `DataInput/`: 250 nombres de mujer, 250 de hombre y 200 apellidos.

Los archivos están codificados como UTF-8; la salida usa UTF-8 con BOM para abrirse correctamente en Excel.

## Reglas principales

- IMSS: primera cotización desde el 01-07-1997 -> Ley 97; antes -> Ley 73. ISSSTE: Cuentas Individuales.
- Cada cliente se genera por perfil (tipos 01 a 10 de `Reglas.rtf`), se clasifica con las reglas y se valida; `validacion_reglas` debe ser `OK` en el 100 % de los registros.
- Montos en pesos constantes de la fecha de corte. Pensiones y resoluciones son estimaciones simuladas; la pensión garantizada y el Bono de Pensión son valores de referencia configurables.

## Criterio de las listas

Las listas son un insumo sintético, ordenado con nombres y apellidos ampliamente frecuentes en México. Para la orientación reciente de nombres se consideró la Estadística de Nacimientos Registrados 2024 de INEGI (reporta a Santiago y Sofía como los nombres más registrados). Para apellidos, el orden inicial coincide con la referencia de apellidos frecuentes de INEGI/Censo 2020, donde Hernández, García y Martínez encabezan el listado. No contienen datos de personas identificables.

Fuentes de consulta: [INEGI, datos abiertos](https://www.inegi.org.mx/datosabiertos/) y [estadística de nombres 2024 de INEGI](https://www.inegi.org.mx/dia-mundial-estadistica/pdf/99-datos-mexico.pdf).
