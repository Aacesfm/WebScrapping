"""Catálogos de referencia usados por el generador (no son parámetros estadísticos)."""

ESTADOS_MEXICO = [
    'Aguascalientes', 'Baja California', 'Baja California Sur', 'Campeche', 'Chiapas',
    'Chihuahua', 'Ciudad de México', 'Coahuila', 'Colima', 'Durango',
    'Guanajuato', 'Guerrero', 'Hidalgo', 'Jalisco', 'México',
    'Michoacán', 'Morelos', 'Nayarit', 'Nuevo León', 'Oaxaca',
    'Puebla', 'Querétaro', 'Quintana Roo', 'San Luis Potosí',
    'Sinaloa', 'Sonora', 'Tabasco', 'Tamaulipas',
    'Tlaxcala', 'Veracruz', 'Yucatán', 'Zacatecas',
]

# Claves de entidad federativa para la CURP (llave normalizada: mayúsculas, sin acentos).
CODIGOS_ENTIDAD = {
    'AGUASCALIENTES': 'AS', 'BAJA CALIFORNIA': 'BC',
    'BAJA CALIFORNIA SUR': 'BS', 'CAMPECHE': 'CC', 'CHIAPAS': 'CS',
    'CHIHUAHUA': 'CH', 'CIUDAD DE MEXICO': 'DF', 'DISTRITO FEDERAL': 'DF',
    'COAHUILA': 'CL', 'COAHUILA DE ZARAGOZA': 'CL', 'COLIMA': 'CM',
    'DURANGO': 'DG', 'GUANAJUATO': 'GT', 'GUERRERO': 'GR', 'HIDALGO': 'HG',
    'JALISCO': 'JC', 'MEXICO': 'MC', 'ESTADO DE MEXICO': 'MC',
    'MICHOACAN': 'MN', 'MICHOACAN DE OCAMPO': 'MN', 'MORELOS': 'MS',
    'NAYARIT': 'NT', 'NUEVO LEON': 'NL', 'OAXACA': 'OC', 'PUEBLA': 'PL',
    'QUERETARO': 'QT', 'QUINTANA ROO': 'QR', 'SAN LUIS POTOSI': 'SP',
    'SINALOA': 'SL', 'SONORA': 'SR', 'TABASCO': 'TC', 'TAMAULIPAS': 'TS',
    'TLAXCALA': 'TL', 'VERACRUZ': 'VZ', 'VERACRUZ DE IGNACIO DE LA LLAVE': 'VZ',
    'YUCATAN': 'YN', 'ZACATECAS': 'ZS', 'EXTRANJERO': 'NE',
}

PARTICULAS_NOMBRE = {
    'DA', 'DAS', 'DE', 'DEL', 'DER', 'DI', 'DIE', 'LA', 'LAS', 'LE', 'LOS', 'Y',
    'MAC', 'MC', 'VAN', 'VON',
}

PALABRAS_INCONVENIENTES = {
    'BACA', 'BAKA', 'BUEI', 'BUEY', 'CACA', 'CACO', 'CAGA', 'CAGO', 'CAKA',
    'CAKO', 'COGE', 'COJA', 'COJE', 'COJI', 'COJO', 'COLA', 'CULO', 'FALO',
    'FETO', 'GETA', 'GUEI', 'GUEY', 'JETA', 'JOTO', 'KACA', 'KACO', 'KAGA',
    'KAGO', 'KAKA', 'KAKO', 'KOGE', 'KOJO', 'KULO', 'LILO', 'LOCA', 'LOCO',
    'LOKA', 'LOKO', 'MAME', 'MAMO', 'MEAR', 'MEAS', 'MEON', 'MION', 'MOCO',
    'MOKO', 'MULA', 'MULO', 'NACA', 'NACO', 'PEDA', 'PEDO', 'PENE', 'PIPI',
    'PITO', 'POPO', 'PUTA', 'PUTO', 'QULO', 'RATA', 'ROBA', 'ROBE', 'ROBO',
    'RUIN',
}
