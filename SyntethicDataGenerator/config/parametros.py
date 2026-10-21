"""Parámetros ajustables del generador de clientes sintéticos.

Todo valor monetario está en pesos constantes de la fecha de corte (rendimientos reales).
Las distribuciones se describen con diccionarios:
  normal truncada -> media, desv, min, max
  lognormal acotada -> mediana, sigma, min, max
Los montos legales marcados como REFERENCIAL son supuestos de simulación: actualícelos con las
tablas oficiales vigentes si se requiere mayor fidelidad.
"""
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Rutas y formatos
# ---------------------------------------------------------------------------
DIR_BASE = Path(__file__).resolve().parent.parent
DIR_INPUT = DIR_BASE / 'DataInput'
DIR_OUTPUT = DIR_BASE / 'DataOutput'
ARCHIVO_NOMBRES = DIR_INPUT / 'nombres_mexico_500.csv'
ARCHIVO_APELLIDOS = DIR_INPUT / 'apellidos_mexico_200.csv'
PLANTILLA_ARCHIVO_SALIDA = 'data_sintetética_{fecha_hora}.csv'
CODIFICACION_ENTRADA = 'utf-8'
CODIFICACION_SALIDA = 'utf-8-sig'  # Con BOM para que Excel conserve acentos y ñ.
FORMATO_FECHA = '%Y-%m-%d'

# Controles de calidad de los insumos.
NOMBRES_ESPERADOS = 500
APELLIDOS_ESPERADOS = 200
GENEROS_ARCHIVO = {'Mujer': 'M', 'Hombre': 'H'}  # Valor en el CSV -> código usado en la salida.

# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------
SEMILLA = 20261019            # Misma semilla -> misma población sintética.
N_CLIN = 100_000                # Número exacto de clientes a generar.
FECHA_CORTE = date(2026, 10, 19)
MAX_INTENTOS_POR_CLIENTE = 50_000
PROPORCION_MUJERES = 0.5
PROB_RESIDE_EN_ESTADO_NACIMIENTO = 0.75

# ---------------------------------------------------------------------------
# Marco legal y calendario
# ---------------------------------------------------------------------------
FECHA_LEY_97 = date(1997, 7, 1)        # Cotización desde esta fecha -> IMSS Ley 97; antes -> Ley 73.
FECHA_ISSSTE_2007 = date(2007, 4, 1)   # Inicio de Cuentas Individuales ISSSTE.
EDAD_MINIMA_PENSION = 60
EDAD_LABORAL_MINIMA = 16
SEMANAS_MIN_LEY_97 = 875               # Requisito 2026 (1,000 en 2021, -25 por año hasta 750 en 2031).
SEMANAS_MIN_LEY_73 = 500
ANIOS_MIN_ISSSTE = 25
DIAS_MIN_BAJA = 30                     # Días mínimos entre la última cotización y la fecha de corte.
DIAS_POR_ANIO = 365.25
SEMANAS_POR_ANIO = DIAS_POR_ANIO / 7
DIAS_POR_MES = 30.4

# Ley 73: conservación de derechos = cuarta parte del tiempo cotizado desde la baja (mínimo 12 meses).
CONSERVACION_FRACCION = 0.25
CONSERVACION_MIN_DIAS = 365

# ---------------------------------------------------------------------------
# Identificadores de régimen / institución
# ---------------------------------------------------------------------------
INSTITUCION_IMSS = 'IMSS'
INSTITUCION_ISSSTE = 'ISSSTE'
REGIMEN_LEY_97 = 'IMSS_LEY_97'
REGIMEN_LEY_73 = 'IMSS_LEY_73'
REGIMEN_ISSSTE = 'ISSSTE_CUENTAS_INDIVIDUALES'
NO_APLICA = 'NO_APLICA'

RESULTADOS_POR_TIPO = {
    '01': 'IMSS97_RECURSOS_PROPIOS',
    '02': 'IMSS97_PENSION_GARANTIZADA',
    '03': 'IMSS97_NEGATIVA_PENSION',
    '04': 'IMSS73_DERECHO_PENSION',
    '05': 'IMSS73_GARANTIZADA',
    '06': 'IMSS73_NEGATIVA_PENSION',
    '07': 'ISSSTE_RECURSOS_PROPIOS',
    '08': 'ISSSTE_PENSION_GARANTIZADA',
    '09': 'ISSSTE_NEGATIVA_PENSION',
    '10': 'INDEPENDIENTES',
}

# ---------------------------------------------------------------------------
# Perfiles (tipo de cliente)
# ---------------------------------------------------------------------------
# proporcion: peso del perfil (deben sumar 1).
# edad: edad a la fecha de corte.
# edad_primera_cotizacion: edad al inicio de la cotización.
# primera_cotizacion: ventana legal para la primera cotización ('desde' inclusive, 'antes_de' exclusive).
# semanas (IMSS) / anios (ISSSTE): tiempo efectivamente cotizado objetivo.
# salario: sobreescribe SALARIO_MENSUAL para ese perfil (opcional).
PERFILES = {
    '01': {
        'descripcion': 'IMSS Ley 97 - pensión con recursos propios',
        'institucion': INSTITUCION_IMSS, 'proporcion': 0.08,
        'edad': dict(media=62, desv=3, min=60, max=70),
        'edad_primera_cotizacion': dict(media=37, desv=4, min=31, max=50),
        'primera_cotizacion': {'desde': FECHA_LEY_97},
        'semanas': dict(media=1200, desv=250, min=875, max=1900),
        'salario': dict(media=50_000, desv=10_000, min=35_000, max=85_000),
    },
    '02': {
        'descripcion': 'IMSS Ley 97 - pensión garantizada',
        'institucion': INSTITUCION_IMSS, 'proporcion': 0.17,
        'edad': dict(media=63, desv=3, min=60, max=72),
        'edad_primera_cotizacion': dict(media=37, desv=4, min=31, max=50),
        'primera_cotizacion': {'desde': FECHA_LEY_97},
        'semanas': dict(media=1250, desv=250, min=875, max=1900),
    },
    '03': {
        'descripcion': 'IMSS Ley 97 - negativa de pensión (semanas insuficientes)',
        'institucion': INSTITUCION_IMSS, 'proporcion': 0.08,
        'edad': dict(media=63, desv=3, min=60, max=72),
        'edad_primera_cotizacion': dict(media=40, desv=4, min=31, max=55),
        'primera_cotizacion': {'desde': FECHA_LEY_97},
        'semanas': dict(media=500, desv=150, min=100, max=874),
    },
    '04': {
        'descripcion': 'IMSS Ley 73 - pensión ordinaria superior al mínimo',
        'institucion': INSTITUCION_IMSS, 'proporcion': 0.15,
        'edad': dict(media=63, desv=3, min=60, max=72),
        'edad_primera_cotizacion': dict(media=22, desv=4, min=16, max=32),
        'primera_cotizacion': {'antes_de': FECHA_LEY_97},
        'semanas': dict(media=1500, desv=350, min=700, max=2500),
    },
    '05': {
        'descripcion': 'IMSS Ley 73 - pensión ajustada al mínimo legal',
        'institucion': INSTITUCION_IMSS, 'proporcion': 0.10,
        'edad': dict(media=61, desv=2, min=60, max=66),
        'edad_primera_cotizacion': dict(media=24, desv=4, min=16, max=34),
        'primera_cotizacion': {'antes_de': FECHA_LEY_97},
        'semanas': dict(media=1400, desv=250, min=800, max=2200),
        'salario': dict(media=10_800, desv=1_200, min=9_582, max=14_500),
    },
    '06': {
        'descripcion': 'IMSS Ley 73 - negativa de pensión (menos de 500 semanas)',
        'institucion': INSTITUCION_IMSS, 'proporcion': 0.06,
        'edad': dict(media=63, desv=3, min=60, max=72),
        'edad_primera_cotizacion': dict(media=24, desv=5, min=16, max=38),
        'primera_cotizacion': {'antes_de': FECHA_LEY_97},
        'semanas': dict(media=300, desv=100, min=50, max=499),
    },
    '07': {
        'descripcion': 'ISSSTE Cuentas Individuales - pensión con recursos propios',
        'institucion': INSTITUCION_ISSSTE, 'proporcion': 0.10,
        'edad': dict(media=62, desv=3, min=60, max=72),
        'edad_primera_cotizacion': dict(media=25, desv=4, min=18, max=35),
        'primera_cotizacion': {'antes_de': FECHA_ISSSTE_2007},
        'anios': dict(media=28, desv=2.5, min=25, max=36),
        'salario': dict(media=28_000, desv=7_000, min=18_000, max=60_000),
    },
    '08': {
        'descripcion': 'ISSSTE Cuentas Individuales - pensión garantizada',
        'institucion': INSTITUCION_ISSSTE, 'proporcion': 0.10,
        'edad': dict(media=62, desv=3, min=60, max=72),
        'edad_primera_cotizacion': dict(media=24, desv=4, min=18, max=35),
        'primera_cotizacion': {'antes_de': FECHA_ISSSTE_2007},
        'anios': dict(media=27, desv=2, min=25, max=34),
        'salario': dict(media=11_000, desv=1_500, min=9_582, max=15_000),
    },
    '09': {
        'descripcion': 'ISSSTE Cuentas Individuales - negativa de pensión (menos de 25 años)',
        'institucion': INSTITUCION_ISSSTE, 'proporcion': 0.06,
        'edad': dict(media=67, desv=3, min=65, max=75),
        'edad_primera_cotizacion': dict(media=30, desv=6, min=18, max=50),
        'anios': dict(media=15, desv=5, min=3, max=24.9),
    },
    '10': {
        'descripcion': 'Independiente no incorporado',
        'institucion': None, 'proporcion': 0.10,
        'edad': dict(media=52, desv=10, min=30, max=70),
    },
}

# ---------------------------------------------------------------------------
# Historial laboral
# ---------------------------------------------------------------------------
# Fracción del periodo entre primera y última cotización con aportaciones efectivas.
DENSIDAD_COTIZACION = {
    INSTITUCION_IMSS: dict(media=0.80, desv=0.12, min=0.50, max=1.0),
    INSTITUCION_ISSSTE: dict(media=0.95, desv=0.04, min=0.85, max=1.0),
}

# ---------------------------------------------------------------------------
# Variables financieras
# ---------------------------------------------------------------------------
# 1) Salario mensual al momento de la baja (normal truncada).
SALARIO_MENSUAL = dict(media=16_000, desv=7_000, min=9_582, max=60_000)
SALARIO_MINIMO_DIARIO = 315.04            # REFERENCIAL (2026).
CRECIMIENTO_REAL_SALARIO = 0.015          # Anual; el salario histórico es menor al final.

# 2) Saldo RCV: aportaciones (% del salario) por régimen como (inicio mínimo, tasa).
#    inicio None = desde la primera cotización.
TASAS_RCV = {
    REGIMEN_LEY_97: [(None, 0.02 + 0.0315 + 0.01125)],
    REGIMEN_LEY_73: [(date(1992, 5, 1), 0.02), (date(1997, 7, 1), 0.0315 + 0.01125)],
    REGIMEN_ISSSTE: [(FECHA_ISSSTE_2007, 0.02 + 0.03175 + 0.06125)],
}
RENDIMIENTO_RCV = dict(media=0.04, desv=0.01, min=0.0, max=0.07)   # Real anual, por cliente.
RUIDO_RCV_SIGMA = 0.18                    # Variabilidad lognormal multiplicativa (media 1).

# 3) Saldo AV: exceso de ceros + mezcla de ahorradores pequeños y grandes.
AHORRO_VOLUNTARIO = dict(
    prob_base=0.10,                       # Probabilidad de ahorrar con salario promedio.
    elasticidad_salario=1.0,              # p = prob_base * (salario / salario medio) ** elasticidad.
    prob_max=0.60,
    prob_monto_alto=0.20,                 # Entre los ahorradores, proporción con aportación elevada.
    tasa_pequena=dict(mediana=0.010, sigma=0.50, min=0.002, max=0.03),   # Fracción del salario.
    tasa_alta=dict(mediana=0.080, sigma=0.35, min=0.04, max=0.20),
    fraccion_vida_laboral=dict(media=0.50, desv=0.25, min=0.05, max=1.0),
    anios_minimos=1.0,
)

# Aportacion mensual actual; es distinta del saldo AV acumulado historicamente.
AHORRO_VOLUNTARIO_MENSUAL = dict(
    probabilidad=0.05,
    monto=dict(mediana=500.0, sigma=0.60, min=100.0, max=1_999.99),
)

# 4) Saldo de vivienda (Infonavit / Fovissste).
VIVIENDA = dict(
    tasa_aportacion=0.05,
    rendimiento=dict(media=0.005, desv=0.005, min=0.0, max=0.02),
    ruido_sigma=0.10,
    prob_historial={'SIN_CREDITO': 0.50, 'CREDITO_LIQUIDADO': 0.25, 'CREDITO_VIGENTE': 0.25},
    antiguedad_minima_credito_anios=2.5,
    plazo_credito_anios=dict(media=12, desv=4, min=5, max=20),
)

# Bono de Pensión ISSSTE (sólo con elección de Cuentas Individuales y requisitos cumplidos).
BONO_PENSION_ISSSTE = dict(factor_salario_anual=0.25, rendimiento_real=0.02)   # REFERENCIAL.

# ---------------------------------------------------------------------------
# Estimación pensionaria
# ---------------------------------------------------------------------------
TASA_TECNICA = 0.035                      # Real anual del cálculo actuarial.
ESPERANZA_VIDA_A_60 = {'H': 21.5, 'M': 24.5}
DESCENSO_ESPERANZA_POR_ANIO = 0.8
ESPERANZA_VIDA_MINIMA = 5.0
PROB_BENEFICIARIOS = 0.85
RECARGO_SEGURO_SOBREVIVENCIA = 0.12       # Si hay beneficiarios.
MODALIDADES = {'RENTA_VITALICIA': 0.5, 'RETIRO_PROGRAMADO': 0.5}
RECARGO_MODALIDAD = {'RENTA_VITALICIA': 0.05, 'RETIRO_PROGRAMADO': 0.0}

# Pensión garantizada mensual. REFERENCIAL: reemplazar por las tablas oficiales.
PENSION_GARANTIZADA = {
    REGIMEN_LEY_97: dict(base=4_400.0, semanas_base=875,
                         incremento_por_100_semanas=0.04, tope_factor=1.5),
    REGIMEN_ISSSTE: dict(base=6_000.0),
}

# Ley 73: pensión mínima en veces el salario mínimo y tabla de cuantías (art. 167 LSS 1973).
PENSION_MINIMA_LEY_73_SMG = 1.0
SEMANAS_PROMEDIO_LEY_73 = 250
# (límite superior en veces el salario mínimo, cuantía básica %, incremento anual %)
TABLA_LEY_73 = [
    (1.00, 80.00, 0.563), (1.25, 77.11, 0.814), (1.50, 58.18, 1.178),
    (1.75, 49.23, 1.430), (2.00, 42.67, 1.615), (2.25, 37.65, 1.756),
    (2.50, 33.68, 1.868), (2.75, 30.48, 1.958), (3.00, 27.83, 2.033),
    (3.25, 25.60, 2.096), (3.50, 23.70, 2.149), (3.75, 22.07, 2.195),
    (4.00, 20.65, 2.235), (4.25, 19.39, 2.271), (4.50, 18.29, 2.302),
    (4.75, 17.30, 2.330), (5.00, 16.41, 2.355), (5.25, 15.61, 2.377),
    (5.50, 14.88, 2.398), (5.75, 14.22, 2.416), (6.00, 13.62, 2.433),
    (float('inf'), 13.00, 2.450),
]
FACTOR_EDAD_CESANTIA = {60: 0.75, 61: 0.80, 62: 0.85, 63: 0.90, 64: 0.95}  # 65 o más: 1.00

# ---------------------------------------------------------------------------
# Layout de salida
# ---------------------------------------------------------------------------
COLUMNAS_SALIDA = [
    'id_cliente_sintetico', 'tipo_cliente', 'nombre', 'apellido_paterno', 'apellido_materno',
    'nombre_completo', 'genero', 'fecha_nacimiento', 'edad', 'estado_nacimiento',
    'estado_residencia', 'CURP', 'RFC', 'NSS', 'institucion', 'regimen_pensionario',
    'eleccion_regimen', 'conservacion_derechos', 'estatus_laboral',
    'fecha_primera_cotizacion', 'edad_primera_cotizacion', 'fecha_ultima_cotizacion',
    'semanas_cotizadas', 'anios_cotizados', 'semanas_imss', 'anios_issste',
    'salario_mensual', 'salario_base_cotizacion', 'sueldo_basico_issste',
    'saldo_rcv', 'saldo_av', 'ahorro_voluntario_mensual', 'saldo_vivienda', 'historial_credito_vivienda',
    'saldo_bono_pension', 'saldo_pensionario_utilizable', 'beneficiarios', 'modalidad_pension',
    'pension_autofinanciable_estimada', 'pension_minima_legal_aplicable',
    'pension_final_estimada', 'resultado_pensionario', 'motivo_resultado',
    'resolucion_simulada', 'validacion_reglas',
]
