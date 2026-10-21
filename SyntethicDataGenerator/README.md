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
- `ahorro_voluntario_mensual`: aportación mensual actual, distinta del `saldo_av` histórico y sin modificar el cálculo pensionario. Como supuesto sintético, el 5 % de los clientes con cuenta AFORE aporta entre $100 y $1,999.99, con distribución lognormal acotada y mediana de referencia de $500; el resto aporta $0. Los independientes no incorporados tienen $0. Se ajusta en `AHORRO_VOLUNTARIO_MENSUAL` de `config/parametros.py`.

## Layout de salida

El CSV contiene las columnas configuradas en `COLUMNAS_SALIDA`: `id_cliente`, nombre y apellidos, edad (`age`), nacimiento (`f_nacim`), género, clave CURP de entidad (`entidad`), NSS, número ISSSTE (`num_issste`), CURP, correo, años truncados hacia abajo, año de afiliación (`anio_fil`), semanas (`sem_cot`), salario, saldos RCV, ahorro solidario, Bono de Pensión, AV y vivienda, porcentaje de ahorro solidario ISSSTE, aportación mensual voluntaria y las etiquetas de régimen, ley y escenario estimados. El número ISSSTE es sintético, de 10 dígitos más DV; el ahorro solidario se estima entre 1% y 2% del saldo RCV y el Bono de Pensión se limita a $350,000. Los campos ISSSTE quedan nulos o en cero para los demás regímenes. La validación pensionaria se ejecuta sobre los campos internos antes de proyectar este layout.

Los correos usan únicamente `yahoo.com`, `gmail.com`, `hotmail.com` y `outlook.com`, con una de las cuatro estructuras configuradas en `generador/identificadores.py`; se normalizan acentos y espacios y se evita repetir direcciones dentro del archivo.

Al exportar, el notebook crea una subcarpeta nueva con fecha y hora dentro de `DataOutput/` y guarda tres archivos: `clientes_IMSS97.csv`, `clientes_IMSS73.csv` y `clientes_ISSSTE_Cuentas_Individuales.csv`. Los independientes con `regimen_estimado = NO_APLICA` no pertenecen a esos tres grupos y se reportan en pantalla, pero no se incluyen en los CSV.

El IMSS confirma que el NSS consta de 11 dígitos y es único, permanente e intransferible. Su página pública de asignación/localización no documenta una fórmula oficial para construirlo. Por eso `nss` es un valor sintético con estructura segmentada y dígito de control para pruebas; no es un NSS asignado por el IMSS ni debe usarse para trámites o identificación real.

## Criterio de las listas

Las listas son un insumo sintético, ordenado con nombres y apellidos ampliamente frecuentes en México. Para la orientación reciente de nombres se consideró la Estadística de Nacimientos Registrados 2024 de INEGI (reporta a Santiago y Sofía como los nombres más registrados). Para apellidos, el orden inicial coincide con la referencia de apellidos frecuentes de INEGI/Censo 2020, donde Hernández, García y Martínez encabezan el listado. No contienen datos de personas identificables.

Fuentes de consulta: [INEGI, datos abiertos](https://www.inegi.org.mx/datosabiertos/) y [estadística de nombres 2024 de INEGI](https://www.inegi.org.mx/dia-mundial-estadistica/pdf/99-datos-mexico.pdf).
