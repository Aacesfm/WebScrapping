"""CURP, RFC y NSS sintéticos. No son identificadores expedidos oficialmente."""
import re
import unicodedata

import config as cfg

_ALFABETO_CURP = '0123456789ABCDEFGHIJKLMNÑOPQRSTUVWXYZ'
_CONSONANTES = 'BCDFGHJKLMNPQRSTVWXYZ'
_CARACTERES_HOMOCLAVE = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'


def _normalizar(valor):
    texto = str(valor).replace('Ñ', 'X').replace('ñ', 'X').upper()
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'[^A-Z0-9]+', ' ', texto).strip()


def _tokens(valor):
    return [t for t in _normalizar(valor).split() if t not in cfg.PARTICULAS_NOMBRE]


def _inicio_y_vocal(valor):
    letras = ''.join(_tokens(valor))
    if not letras:
        return 'XX'
    return letras[0] + next((c for c in letras[1:] if c in 'AEIOU'), 'X')


def _consonante_interna(letras):
    return next((c for c in letras[1:] if c in _CONSONANTES), 'X')


def codigo_entidad(estado):
    texto = unicodedata.normalize('NFKD', str(estado).upper())
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return cfg.CODIGOS_ENTIDAD.get(' '.join(texto.split()))


def generar_curp(nombre, paterno, materno, nacimiento, genero, estado):
    """CURP de 18 caracteres con homoclave fija y dígito verificador calculado."""
    nombres = _tokens(nombre)
    if len(nombres) > 1 and nombres[0] in {'JOSE', 'MARIA'}:
        nombres = nombres[1:]
    if not nombres:
        raise ValueError(f'Nombre sin letras válidas: {nombre!r}')
    if genero not in {'H', 'M'}:
        raise ValueError(f'Género no reconocido: {genero!r}')
    entidad = codigo_entidad(estado)
    if entidad is None:
        raise ValueError(f'Entidad federativa no reconocida: {estado!r}')

    letras_paterno = ''.join(_tokens(paterno))
    letras_materno = ''.join(_tokens(materno))
    letras_nombre = ''.join(nombres)
    cuatro = _inicio_y_vocal(paterno) + (letras_materno[:1] or 'X') + letras_nombre[0]
    if cuatro in cfg.PALABRAS_INCONVENIENTES:
        cuatro = cuatro[0] + 'X' + cuatro[2:]

    homonimia = 'A' if nacimiento.year >= 2000 else '0'
    base = (
        cuatro + nacimiento.strftime('%y%m%d') + genero + entidad
        + _consonante_interna(letras_paterno) + _consonante_interna(letras_materno)
        + _consonante_interna(letras_nombre) + homonimia
    )
    suma = sum(_ALFABETO_CURP.index(c) * peso for c, peso in zip(base, range(18, 1, -1)))
    return base + str((10 - suma % 10) % 10)


def generar_rfc(curp, rng):
    """RFC de persona física: 10 posiciones de la CURP más homoclave aleatoria."""
    homoclave = ''.join(rng.choice(list(_CARACTERES_HOMOCLAVE), size=3))
    return curp[:10] + homoclave


def generar_nss(rng, anio_afiliacion, anio_nacimiento):
    """NSS sintético segmentado; no reproduce una fórmula oficial de asignación del IMSS."""
    cuerpo = f'{rng.integers(1, 100):02d}{anio_afiliacion % 100:02d}{anio_nacimiento % 100:02d}{rng.integers(0, 10_000):04d}'
    suma = 0
    for i, digito in enumerate(int(c) for c in cuerpo):
        producto = digito * (1 if i % 2 == 0 else 2)
        suma += producto - 9 if producto > 9 else producto
    return cuerpo + str((10 - suma % 10) % 10)


def generar_correo(rng, nombre, paterno, materno, nacimiento, usados):
    """Genera un correo único con una de las cuatro estructuras solicitadas."""
    nombres = ''.join(_tokens(nombre)).lower()
    paternos = ''.join(_tokens(paterno)).lower()
    maternos = ''.join(_tokens(materno)).lower()
    iniciales = nombres[0] + paternos[0] + maternos[0]
    dominios = ('yahoo.com', 'gmail.com', 'hotmail.com', 'outlook.com')

    while True:
        plantilla = int(rng.integers(0, 4))
        if plantilla == 0:
            usuario = f'{nombres}_{nacimiento.year}{paternos}'
        elif plantilla == 1:
            usuario = f'{paternos[:3]}_{nombres}{int(rng.integers(0, 1_000_000)):06d}'
        elif plantilla == 2:
            usuario = f'{paternos}{maternos[0]}_{nacimiento.year}'
        else:
            usuario = f'{iniciales}{nacimiento:%d%m}_{nombres}'
        correo = f'{usuario}@{rng.choice(dominios)}'
        if correo not in usados:
            usados.add(correo)
            return correo
