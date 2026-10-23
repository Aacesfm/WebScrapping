# Generador de datos sintéticos

## Entorno Python

El workspace usa Python 3.8.8. En macOS Apple Silicon, crea el entorno nativo ARM
desde la raíz del workspace e instala las dependencias de ambos proyectos:

```bash
conda env create -p .venv-py388 -f environment.yml
conda run -p .venv-py388 python -m pip install -r SyntethicDataGenerator/requirements.txt -r WebScrapp/requirements.txt
```

En VS Code, selecciona `.venv-py388/bin/python` como intérprete y como kernel del
notebook `generador_clientes_sinteticos.ipynb`.

## Generador de casos de prueba

Desde la raíz del workspace, ejecuta:

```bash
conda run -p .venv-py388 python SyntethicDataGenerator/generar_casos_pruebas_completas.py
```

El script lee los nombres y apellidos de `SyntethicDataGenerator/DataInput/` y
guarda tres CSV normalizados en una carpeta `data_[Fecha_Hora]` dentro de
`SyntethicDataGenerator/DataOutput/`. Si falta el CSV de esquema, usa los 22
encabezados documentados; si falta el PKL, genera los casos con fronteras
salariales fijas y los fallbacks de semanas/PG.

Para reproducir los identificadores con otra semilla, usa `--seed`:

```bash
conda run -p .venv-py388 python SyntethicDataGenerator/generar_casos_pruebas_completas.py --seed 42
```

El layout añade `NSS IMSS sintetico` e `ISSSTE_SINTETICO_FORMATO`. El primero se
rellena solo para IMSS Ley 73/97 y el segundo solo para ISSSTE; ambos quedan
vacíos en los demás regímenes. Para ISSSTE no se calcula ni se afirma un dígito
verificador oficial.

## Identificadores de seguridad social

`identificadores_seguridad_social.py` expone generadores y validadores
independientes. El NSS IMSS aplica el Luhn indicado y codifica los años de
nacimiento y afiliación; el prefijo predeterminado `00` es un marcador sintético,
no una clave oficial. Se puede configurar una lista local de prefijos de prueba
con `IMSS_SUBDELEGATION_CODES`, separada por comas. Los resultados son
reproducibles por semilla e índice y se guardan como texto.

El identificador ISSSTE solo garantiza 11 caracteres numéricos, reproducibilidad
y unicidad en el dataset. No se inventa un algoritmo institucional ni se deriva
de la CURP.

La validez estructural y, para IMSS, el dígito Luhn no demuestran existencia,
asignación ni reconocimiento oficial. Ninguno de estos valores debe usarse para
trámites o identificación real.

Ejemplos de `generar_nss_imss("1980-05-04", "2000-01-01", 1, 42)` y
`generar_nss_issste_sintetico(1, 42)` (el prefijo IMSS `00` es sintético):

```text
NSS IMSS sintetico: 00008000432
ISSSTE_SINTETICO_FORMATO: 21613542717
```

Las pruebas unitarias se ejecutan desde la raíz del workspace con:

```bash
conda run -p .venv-py388 python -B -m unittest SyntethicDataGenerator.test_identificadores_seguridad_social
conda run -p .venv-py388 python -B -m unittest discover -s WebScrapp -p 'test_*.py'
```

## Envío a WebScrapp

El orquestador queda inactivo por omisión. Para simular la selección de todos
los scrapers sin abrir navegadores:

```bash
conda run -p .venv-py388 python WebScrapp/orquestador.py --all --data-dir SyntethicDataGenerator/DataOutput/data_YYYYMMDD_HHMMSS --max-clientes 3 --headless --simular
```

Para ejecutarlos uno a la vez con tres clientes cada uno, agrega
`--secuencial` y quita `--simular`. Para ejecutar solo un scraper, reemplaza
`--all` con su bandera, por ejemplo `--profuturo_IMSS97 1`. Sin `--secuencial`,
los seleccionados corren en paralelo. Cada corrida crea archivos de resultados
nuevos en `WebScrapp/DataOutput/`; no reutiliza los CSV/checkpoints históricos.
El timeout por cliente se puede ampliar con `--timeout 40` cuando la calculadora
responda lentamente.
SURA guarda datos enviados a su calculadora, así que las corridas live usan
identidades sintéticas y pueden detenerse si aparece un CAPTCHA o rechazo.

Validación live del 2026-10-22 con la carpeta
`data_20261022_215522_702264`: Profuturo IMSS73, Profuturo IMSS97, Profuturo
ISSSTE, SURA IMSS73 y SURA IMSS97 completaron tres clientes cada uno con estado
`OK`. Banorte leyó y registró los tres clientes, pero devolvió
`TIMEOUT | formulario`, también al ampliar el timeout a 40 segundos. Sus entradas
pasan la validación offline; el timeout ocurre dentro del formulario remoto.
Los seis CSV y los CSV del reintento Banorte están bajo
`WebScrapp/DataOutput/data_20261022_215522_702264_web_20261022_215727_777839/`
y `WebScrapp/DataOutput/data_20261022_215522_702264_web_20261022_220349_720342/`.

Para inspeccionar Banorte de nuevo con ventana visible, usa una salida nueva:

```bash
conda run -p .venv-py388 python WebScrapp/orquestador.py --banorte_IMSS97 1 --data-dir SyntethicDataGenerator/DataOutput/data_20261022_215522_702264 --max-clientes 3 --timeout 40 --secuencial
```

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
