"""Identificadores de seguridad social sintéticos para datos de prueba.

La validación estructural o del dígito no acredita asignación institucional.
"""

from __future__ import annotations

import os
import random
import re
from datetime import date, datetime
from math import gcd


_DEFAULT_SYNTHETIC_PREFIX = "00"
_ISSSTE_MODULUS = 10 ** 11


def _configured_imss_prefixes() -> tuple[str, ...]:
    configured = os.environ.get("IMSS_SUBDELEGATION_CODES", _DEFAULT_SYNTHETIC_PREFIX)
    prefixes = tuple(code.strip() for code in configured.split(",") if code.strip())
    if not prefixes or any(re.fullmatch(r"\d{2}", code) is None for code in prefixes):
        raise ValueError("IMSS_SUBDELEGATION_CODES debe contener claves de dos dígitos separadas por comas.")
    return prefixes


def _parse_date(value: date | str) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    for date_format in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), date_format).date()
        except ValueError:
            continue
    return None


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def calcular_digito_verificador_imss(base_10: str) -> str:
    """Calcula el dígito Luhn especificado para los primeros diez dígitos."""
    if re.fullmatch(r"\d{10}", base_10) is None:
        raise ValueError("base_10 debe contener exactamente diez dígitos.")
    total = 0
    for index, character in enumerate(base_10):
        product = int(character) * (1 if index % 2 == 0 else 2)
        total += product - 9 if product > 9 else product
    return str((10 - total % 10) % 10)


def generar_nss_imss(
    fecha_nacimiento: date | str,
    fecha_afiliacion: date | str,
    idx: int,
    seed: int,
) -> str:
    """Genera un NSS estructural sintético; no acredita asignación del IMSS.

    El prefijo predeterminado ``00`` es un marcador sintético, no una clave
    oficial validada. Puede configurarse una lista de prefijos con la variable
    ``IMSS_SUBDELEGATION_CODES`` (por ejemplo, ``"00,01"`` para pruebas).
    """
    birth = _parse_date(fecha_nacimiento)
    affiliation = _parse_date(fecha_afiliacion)
    if birth is None or affiliation is None:
        raise ValueError("Las fechas de nacimiento y afiliación deben ser válidas.")
    if affiliation < _add_years(birth, 18):
        raise ValueError("La afiliación IMSS sintética debe ocurrir a los 18 años o después.")
    if idx < 1:
        raise ValueError("idx debe ser un entero positivo.")

    prefixes = _configured_imss_prefixes()
    rng = random.Random((int(seed) << 32) ^ int(idx))
    prefix = rng.choice(prefixes)
    serial = ((int(idx) - 1 + int(seed)) % 9999) + 1
    base_10 = "{}{:02d}{:02d}{:04d}".format(
        prefix,
        affiliation.year % 100,
        birth.year % 100,
        serial,
    )
    return base_10 + calcular_digito_verificador_imss(base_10)


def validar_nss_imss(
    nss: str,
    fecha_nacimiento: date | str | None = None,
    fecha_afiliacion: date | str | None = None,
) -> bool:
    """Valida formato y Luhn; opcionalmente contrasta años y cronología."""
    if not isinstance(nss, str) or re.fullmatch(r"\d{11}", nss) is None:
        return False
    if calcular_digito_verificador_imss(nss[:10]) != nss[10]:
        return False

    birth = _parse_date(fecha_nacimiento) if fecha_nacimiento is not None else None
    affiliation = _parse_date(fecha_afiliacion) if fecha_afiliacion is not None else None
    if fecha_nacimiento is not None and birth is None:
        return False
    if fecha_afiliacion is not None and affiliation is None:
        return False
    if birth is not None and int(nss[4:6]) != birth.year % 100:
        return False
    if affiliation is not None and int(nss[2:4]) != affiliation.year % 100:
        return False
    if birth is not None and affiliation is not None and affiliation < _add_years(birth, 18):
        return False
    return True


def _issste_affine_parameters(seed: int) -> tuple[int, int]:
    rng = random.Random((int(seed) << 1) ^ 0x495353535445)
    multiplier = rng.randrange(1, _ISSSTE_MODULUS)
    while gcd(multiplier, _ISSSTE_MODULUS) != 1:
        multiplier = rng.randrange(1, _ISSSTE_MODULUS)
    return multiplier, rng.randrange(_ISSSTE_MODULUS)


def generar_nss_issste_sintetico(idx: int, seed: int) -> str:
    """Genera 11 dígitos deterministas, sin inferir formato institucional."""
    if idx < 1:
        raise ValueError("idx debe ser un entero positivo.")
    multiplier, offset = _issste_affine_parameters(seed)
    value = (multiplier * (int(idx) - 1) + offset) % _ISSSTE_MODULUS
    return "{:011d}".format(value)


def validar_formato_nss_issste(nss: str) -> bool:
    """Valida únicamente 11 dígitos; no valida un dígito ISSSTE oficial."""
    return isinstance(nss, str) and re.fullmatch(r"\d{11}", nss) is not None