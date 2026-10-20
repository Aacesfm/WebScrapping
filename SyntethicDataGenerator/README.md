# Generador de datos sintéticos

## Estructura

- `../SyntethicDataGenerator - Input/nombres_mexico_500.csv`: 250 nombres asociados a Mujer y 250 asociados a Hombre.
- `../SyntethicDataGenerator - Input/apellidos_mexico_200.csv`: 200 apellidos.
- `generador_clientes_sinteticos.ipynb`: construye clientes ficticios y los exporta a `output/`.

Los archivos están codificados como UTF-8; la salida del notebook usa UTF-8 con BOM para abrirse correctamente en Excel.

## Criterio de las listas

Las listas son un insumo sintético, ordenado con nombres y apellidos ampliamente frecuentes en México. Para la orientación reciente de nombres se consideró la Estadística de Nacimientos Registrados 2024 de INEGI (reporta a Santiago y Sofía como los nombres más registrados). Para apellidos, el orden inicial coincide con la referencia de apellidos frecuentes de INEGI/Censo 2020, donde Hernández, García y Martínez encabezan el listado. No contienen datos de personas identificables.

Fuentes de consulta: [INEGI, datos abiertos](https://www.inegi.org.mx/datosabiertos/) y [estadística de nombres 2024 de INEGI](https://www.inegi.org.mx/dia-mundial-estadistica/pdf/99-datos-mexico.pdf).
