"""Generador independiente de casos sintéticos para pruebas pensionarias.

Implementa el alcance visible en PROMPT_REPLICAR_GENERADOR_EDITADO_TRANSCRIPCION.txt.
La transcripción no incluye el script fuente ni varios detalles citados como
"mismos que el script"; los patrones, casos negativos y cruces omitidos se
marcan como aproximaciones para no presentarlos como una réplica literal.
"""

from __future__ import annotations

import argparse
import csv
import pickle
import random
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from identificadores_seguridad_social import (
    generar_nss_imss,
    generar_nss_issste_sintetico,
    validar_formato_nss_issste,
    validar_nss_imss,
)


BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "DataInput"
OUTPUT_DIR = BASE_DIR / "DataOutput"
SCHEMA_CANDIDATES = (
    INPUT_DIR / "CASOS_10_PRUEBAS_transformado.csv",
    BASE_DIR / "CASOS_10_PRUEBAS_transformado.csv",
    OUTPUT_DIR / "CASOS_10_PRUEBAS_transformado.csv",
    OUTPUT_DIR / "CASOS_PRUEBAS_COMPLETAS.csv",
)
CATALOG_PKL = INPUT_DIR / "catalogs_consolidated.pkl"
NAMES_CSV = INPUT_DIR / "nombres_mexico_500.csv"
SURNAMES_CSV = INPUT_DIR / "apellidos_mexico_200.csv"
ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
FALLBACK_SCHEMA = [
    "Nombre completo",
    "Correo electronico",
    "Celular",
    "CURP",
    "Fecha de nacimiento",
    "Genero",
    "Regimen",
    "Salario basico",
    "Semanas cotizadas ante el IMSS",
    "Anos de cotizacion",
    "Saldo de ahorro para el retiro",
    "Saldo de subcuenta de vivienda",
    "Saldo de ahorro solidario",
    "Bono de pension",
    "Porcentaje de ahorro solidario",
    "Saldo ahorro voluntario",
    "Edad de retiro",
    "Meta mensual para tu retiro",
    "Ahorro mensual adicional",
    "Fecha Afiliacion",
    "NSS IMSS sintetico",
    "ISSSTE_SINTETICO_FORMATO",
]
WEB_CLIENT_COLUMNS = [
    "id_cliente", "nombre", "ap_paterno", "ap_materno", "age", "f_nacim",
    "genero", "entidad", "nss", "num_issste", "curp", "correo",
    "anios_cotizados", "anio_fil", "sem_cot", "salario_mensual", "saldo_rcv",
    "saldo_ahorro_solidario", "porcentaje_ahorro_solidario", "saldo_bono_pension",
    "saldo_av", "saldo_vivienda", "av_mensual", "regimen_estimado",
    "ley_bandera", "escenario_estimado",
]

AGES = [18, 20, 25, 30, 35, 40, 45, 47, 50, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 70, 75, 80, 90, 100, 109, 110]
RETIRE_AGES = [60, 61, 62, 63, 64, 65, 66, 70, 75, 80]
ISSSTE_SERVICE_LEVELS = [5, 10, 15, 20, 24, 25, 26, 30, 35, 40]
MAX_TOTAL_CASES = 9800
LAN_IMSS97 = "IMSS Ley 97"
LAN_IMSS73 = "IMSS Ley 73"
LAN_ISSSTE = "ISSSTE Cuentas Individuales"
LAN_INDEP = "Independiente"
REGIMENS = (LAN_IMSS97, LAN_IMSS73, LAN_ISSSTE, LAN_INDEP)
IMSS_REGIMENS = {LAN_IMSS97, LAN_IMSS73}
WEB_REGIMENS = {
    LAN_IMSS97: ("IMSS97", "LEY_97"),
    LAN_IMSS73: ("IMSS73", "LEY_73"),
    LAN_ISSSTE: ("ISSSTE", "LEY_ISSSTE"),
}
IDENTIFIER_SEED = 20261022
EMAIL_DOMAINS = ["gmail.com", "hotmail.com", "yahoo.com", "outlook.com"]
DISPLAY_GENDER_ALTERNATIVES = ["Prefiero no decir"]
CURP_ENTITY_CODES = ["AS", "BC", "BS", "CC", "CL", "CM", "CS", "CH", "DF", "DG", "GT", "GR", "HG", "JC", "MC", "MN", "MS", "NT", "NL", "OC", "PL", "QT", "QR", "SP", "SL", "SR", "TC", "TS", "TL", "VZ", "YN", "ZS", "NE"]

# Conjuntos convencionales; el TXT pide los del script original, que no fue
# incluido. Estos valores son aproximaciones y no una garantía de identidad CURP.
CURP_COMMON_WORDS = {"DA", "DAS", "DE", "DEL", "DER", "DI", "DIE", "DD", "EL", "LA", "LAS", "LOS", "LE", "LES", "MAC", "MC", "VAN", "VON", "Y"}
CURP_COMPOUND_SKIP_NAMES = {"MARIA", "JOSE"}
BAD_CURP_WORDS = {"BACA", "BAKA", "BUEI", "BUEY", "CACA", "CACO", "CAGA", "CAGO", "CAKA", "COGE", "COJA", "COJE", "COJI", "COJO", "COLA", "CULO", "FETO", "GUEI", "GUEY", "JOTO", "KACA", "KACO", "KAGA", "KAGO", "KOGE", "KOJO", "KAKA", "KULO", "MAME", "MAMO", "MEAR", "MEAS", "MEON", "MION", "MOCO", "MULA", "PEDA", "PEDO", "PENE", "PUTA", "PUTO", "QULO", "RATA", "RUIN"}

_USED_EMAILS: set[str] = set()
_USED_CELLS: set[str] = set()
_PEOPLE_CACHE: dict[str, list[str]] | None = None

_BLOCK_BUDGETS = {
    "B1": 1300, "B2": 500, "B3": 500, "B4": 700, "B5": 900,
    "B6": 1500, "B6b": 1000, "B7": 600, "B8": 300, "B9": 500,
    "B10": 250, "B11": 250, "B12": 150, "B13": 150,
    "B14": 900, "B15": 900,
}


def _strip_accents(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(char for char in text if unicodedata.category(char) != "Mn")


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _strip_accents(value).lower())


def _only_letters(value: Any) -> str:
    return re.sub(r"[^A-Z]", "", _strip_accents(value).upper().replace("Ñ", "X"))


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", _strip_accents(value).lower())


def _safe_num(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _parse_case_date(value: Any) -> date | None:
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


def _normalize_gender_label(raw: Any) -> str:
    value = _strip_accents(raw).strip().lower()
    if value in {"mujer", "femenino", "f", "m"}:
        return "Femenino"
    if value in {"hombre", "masculino", "h"}:
        return "Masculino"
    return "Prefiero no decir"


def _birthdate_from_age(age: int) -> str:
    return date.today().replace(year=date.today().year - int(age)).strftime("%d/%m/%Y")


def _ret_age_for(age: int, desired: int) -> int:
    return max(int(desired), int(age) + 1)


def _letters(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _read_csv_dict(path: Path) -> list[dict[str, str]]:
    errors = []
    for encoding in ENCODINGS:
        try:
            with path.open("r", encoding=encoding, newline="") as file:
                return list(csv.DictReader(file))
        except (OSError, UnicodeError, csv.Error) as error:
            errors.append(str(error))
    raise RuntimeError(f"No se pudo leer {path}: {'; '.join(errors)}")


def _read_schema() -> list[str]:
    for candidate in SCHEMA_CANDIDATES:
        if not candidate.is_file():
            continue
        for encoding in ENCODINGS:
            try:
                with candidate.open("r", encoding=encoding, newline="") as file:
                    header = next(csv.reader(file), [])
                if not header:
                    continue
                normalized_headers = {_normalize_header(column) for column in header}
                if _normalize_header("Fecha Afiliacion") not in normalized_headers:
                    header.append("Fecha Afiliacion")
                for identifier_column in ("NSS IMSS sintetico", "ISSSTE_SINTETICO_FORMATO"):
                    if _normalize_header(identifier_column) not in normalized_headers:
                        header.append(identifier_column)
                return header
            except (OSError, UnicodeError, csv.Error):
                continue
    return list(FALLBACK_SCHEMA)


def _load_catalogs() -> dict[str, Any]:
    if not CATALOG_PKL.is_file():
        return {}
    try:
        with CATALOG_PKL.open("rb") as file:
            catalog = pickle.load(file)
    except Exception as error:
        raise RuntimeError(f"No se pudo cargar {CATALOG_PKL}: {error}") from error
    return catalog if isinstance(catalog, dict) else {}


def _load_people_catalogs() -> dict[str, list[str]]:
    global _PEOPLE_CACHE
    if _PEOPLE_CACHE is not None:
        return _PEOPLE_CACHE

    female_names: list[str] = []
    male_names: list[str] = []
    surnames: list[str] = []
    if not NAMES_CSV.is_file():
        raise FileNotFoundError(f"No se encontró el catálogo de nombres: {NAMES_CSV}")
    if not SURNAMES_CSV.is_file():
        raise FileNotFoundError(f"No se encontró el catálogo de apellidos: {SURNAMES_CSV}")

    for row in _read_csv_dict(NAMES_CSV):
        name = (row.get("nombre") or "").strip()
        if not name:
            continue
        gender = _normalize_gender_label(row.get("genero"))
        if gender == "Masculino":
            male_names.append(name)
        elif gender == "Femenino":
            female_names.append(name)
    surnames = [(row.get("apellido") or "").strip() for row in _read_csv_dict(SURNAMES_CSV)]
    surnames = [name for name in surnames if name]

    if not male_names or not female_names:
        raise ValueError(f"El catálogo de nombres debe incluir ambos géneros: {NAMES_CSV}")
    if not surnames:
        raise ValueError(f"El catálogo de apellidos está vacío: {SURNAMES_CSV}")

    _PEOPLE_CACHE = {
        "male": male_names[:200],
        "female": female_names,
        "surnames": surnames,
    }
    return _PEOPLE_CACHE


def _gender_from_idx(idx: int) -> str:
    return "Masculino" if idx % 2 == 0 else "Femenino"


def _identity_from_idx(idx: int) -> dict[str, str]:
    rng = random.Random((idx * 7919) + 97)
    gender = _gender_from_idx(idx)
    people = _load_people_catalogs()
    name = rng.choice(people["male" if gender == "Masculino" else "female"])
    paternal = rng.choice(people["surnames"])
    maternal = rng.choice(people["surnames"])
    return {"nombre": name, "paterno": paternal, "materno": maternal,
            "genero": gender, "nombre_completo": f"{name} {paternal} {maternal}"}


def _display_gender_from_idx(idx: int, base_gender: str) -> str:
    if idx % 150 == 0:
        return random.Random((idx * 1543) + 29).choice(DISPLAY_GENDER_ALTERNATIVES)
    return base_gender


def _cell_from_idx(idx: int) -> str:
    ladas = ["55", "56", "33", "81", "222", "443", "999", "664", "442", "477", "449", "614", "228", "229", "844", "818", "667"]
    rng = random.Random((idx * 10007) + 41)
    while True:
        lada = rng.choice(ladas)
        cell = (lada + "".join(str(rng.randrange(10)) for _ in range(10 - len(lada))))[:10].zfill(10)
        if cell not in _USED_CELLS:
            _USED_CELLS.add(cell)
            return cell


def _build_email(identity: dict[str, str], birth: str, idx: int) -> str:
    name = _slug(identity["nombre"])
    paternal = _slug(identity["paterno"])
    maternal = _slug(identity["materno"])
    try:
        year = datetime.strptime(birth, "%d/%m/%Y").year
    except ValueError:
        year = date.today().year - 40
    last_two = str(year)[-2:]
    number = (idx * 73) % 997 + 1
    # Orden aproximado: el arreglo original de 18 plantillas no estaba incluido.
    patterns = [
        "{n}.{p}", "{n}_{p}", "{n}{p}", "{n}.{m}.{p}", "{n}{p}{m}",
        "{p}.{n}", "{p}_{n}", "{p}{n}", "{n}{num}", "{n}.{num}",
        "{n}_{num}", "{n}{yy}", "{n}.{yy}", "{p}{yy}", "{p}.{yy}",
        "{n}{p}{num}", "{n}_{p}_{num}", "{n}.{p}{yy}",
    ]
    local = patterns[(idx - 1) % len(patterns)].format(
        n=name, p=paternal, m=maternal, num=number, yy=last_two
    )
    local = re.sub(r"[^a-z0-9_]", "", local).strip("_") or f"cliente{idx}"
    domain = EMAIL_DOMAINS[idx % len(EMAIL_DOMAINS)]
    email = f"{local}@{domain}"
    suffix = 1
    while email in _USED_EMAILS:
        email = f"{local}{suffix}@{domain}"
        suffix += 1
    _USED_EMAILS.add(email)
    return email


def _pick_name_parts(value: str) -> list[str]:
    normalized = _strip_accents(value).upper().replace("Ñ", "X")
    tokens = re.findall(r"[A-Z]+", normalized)
    return [part for part in tokens if part not in CURP_COMMON_WORDS]


def _curp_name_token(nombre: str) -> str:
    tokens = _pick_name_parts(nombre)
    if len(tokens) > 1 and tokens[0] in CURP_COMPOUND_SKIP_NAMES:
        return tokens[1]
    return tokens[0] if tokens else "X"


def _first_internal_vowel(value: str) -> str:
    return next((char for char in value[1:] if char in "AEIOU"), "X")


def _first_internal_consonant(value: str) -> str:
    return next((char for char in value[1:] if char in "BCDFGHJKLMNPQRSTVWXYZ"), "X")


def _curp_char_value(char: str) -> int:
    alphabet = "0123456789ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"
    return alphabet.find(char) if char in alphabet else 0


def _curp_check_digit(base17: str) -> str:
    total = sum(_curp_char_value(char) * (18 - index) for index, char in enumerate(base17[:17]))
    return str((10 - total % 10) % 10)


def _build_curp(nombre: str, paterno: str, materno: str, birth_ddmmyyyy: str, genero_txt: str, idx: int) -> str:
    ap = (_pick_name_parts(paterno) or ["X"])[0]
    am = (_pick_name_parts(materno) or ["X"])[0]
    first = _curp_name_token(nombre)
    chars = [ap[0], _first_internal_vowel(ap), am[0], first[0]]
    if "".join(chars) in BAD_CURP_WORDS:
        chars[1] = "X"
    try:
        birth = datetime.strptime(birth_ddmmyyyy, "%d/%m/%Y").date()
    except ValueError:
        birth = date(1990, 1, 1)
    gender_code = {"Masculino": "H", "Femenino": "M"}.get(genero_txt, "X")
    name_code = "".join(chars)
    state = CURP_ENTITY_CODES[idx % len(CURP_ENTITY_CODES)]
    consonants = _first_internal_consonant(ap) + _first_internal_consonant(am) + _first_internal_consonant(first)
    homoclave = str(idx % 10) if birth.year < 2000 else chr(65 + idx % 26)
    base17 = f"{name_code}{birth:%y%m%d}{gender_code}{state}{consonants}{homoclave}"[:17].ljust(17, "X")
    return base17 + _curp_check_digit(base17)


def _curp_from_idx(idx: int) -> str:
    identity = _identity_from_idx(idx)
    birth = date(20 + idx % 60, 7, 1).strftime("%d/%m/%Y")
    return _build_curp(identity["nombre"], identity["paterno"], identity["materno"], birth, identity["genero"], idx)


def _safe_date_replace_year(value: date, year: int) -> date:
    try:
        return value.replace(year=year)
    except ValueError:
        return value.replace(year=year, day=28)


def _affiliation_date_for(regimen: str, birth: str, idx: int) -> str:
    if regimen in {LAN_ISSSTE, LAN_INDEP}:
        return ""
    try:
        born = datetime.strptime(birth, "%d/%m/%Y").date()
    except ValueError:
        return ""
    labor_start = _safe_date_replace_year(born, born.year + 18)
    cutoff = date(1997, 7, 1)
    if regimen == LAN_IMSS73:
        end = cutoff - timedelta(days=1)
        start = min(labor_start, end)
    else:
        start = max(labor_start, cutoff + timedelta(days=1))
        end = max(start, date.today())
    span = (end - start).days
    return (start + timedelta(days=(idx * 17) % (span + 1))).strftime("%d/%m/%Y")


def _base_case(idx: int, regimen: str, age: int, retire_age: int) -> dict[str, Any]:
    identity = _identity_from_idx(idx)
    birth = _birthdate_from_age(age)
    display_gender = _display_gender_from_idx(idx, identity["genero"])
    return {
        "Nombre completo": identity["nombre_completo"],
        "Correo electrónico": _build_email(identity, birth, idx),
        "Celular": _cell_from_idx(idx),
        "CURP": _build_curp(identity["nombre"], identity["paterno"], identity["materno"], birth, display_gender, idx),
        "Fecha de nacimiento": birth,
        "Fecha Afiliacion": _affiliation_date_for(regimen, birth, idx),
        "Género": display_gender,
        "Régimen": regimen,
        "Salario básico": 20000,
        "Semanas cotizadas ante el IMSS": 1000,
        "Años de cotización": 25,
        "Saldo de ahorro para el retiro": 500000,
        "Saldo de subcuenta de vivienda": 100000,
        "Saldo de ahorro solidario": 50000,
        "Bono de pensión": 100000,
        "Porcentaje de ahorro solidario": 0.01,
        "Saldo ahorro voluntario": 5000,
        "Edad de retiro": _ret_age_for(age, retire_age),
        "Meta mensual para tu retiro": 20000,
        "Ahorro mensual adicional": 1000,
    }


def _normalize_by_regimen(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    regimen = normalized.get("Régimen")
    if regimen in {LAN_IMSS97, LAN_IMSS73}:
        normalized["Años de cotización"] = ""
        normalized["Bono de pensión"] = 0
        normalized["Saldo de ahorro solidario"] = 0
        normalized["Porcentaje de ahorro solidario"] = 0
        if normalized.get("Semanas cotizadas ante el IMSS") in (None, ""):
            normalized["Semanas cotizadas ante el IMSS"] = 0
    elif regimen == LAN_ISSSTE:
        normalized["Semanas cotizadas ante el IMSS"] = ""
    elif regimen == LAN_INDEP:
        normalized["Semanas cotizadas ante el IMSS"] = ""
        normalized["Años de cotización"] = ""
        normalized["Bono de pensión"] = 0
        normalized["Saldo de ahorro solidario"] = 0
        normalized["Porcentaje de ahorro solidario"] = ""
    return normalized


def _add_case(rows: list[dict[str, Any]], seen: set[tuple[Any, ...]], schema: list[str], row: dict[str, Any]) -> bool:
    normalized_row = {
        _normalize_header(column): value
        for column, value in _normalize_by_regimen(row).items()
    }
    projected = {
        column: normalized_row.get(_normalize_header(column), "")
        for column in schema
    }
    identifier_columns = {
        _normalize_header("NSS IMSS sintetico"),
        _normalize_header("ISSSTE_SINTETICO_FORMATO"),
    }
    key = tuple(
        str(projected[column])
        for column in schema
        if _normalize_header(column) not in identifier_columns
    )
    if key in seen:
        return False
    seen.add(key)
    rows.append(projected)
    return True


def _boundary_values(value: Any) -> list[float]:
    found: list[float] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if _normalize_header(str(key)) in {"limiteinf", "limitesup"}:
                try:
                    found.append(float(str(item).replace(",", "").replace("$", "").strip()))
                except (TypeError, ValueError):
                    continue
            elif isinstance(item, (dict, list, tuple)):
                found.extend(_boundary_values(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_boundary_values(item))
    return found


def _collect_salary_boundaries(cat: dict[str, Any]) -> list[float]:
    values: set[float] = set()
    for key in ("cuota_social", "porc_contribucion"):
        values.update(_boundary_values(cat.get(key)))
    for key in ("cat_pisos_topes_imss", "cat_pisos_topes_issste"):
        items = cat.get(key)
        if isinstance(items, list) and items:
            values.update(_boundary_values(items[0]))
    values.update({0, 1, 10, 100, 1000, 5000, 10000, 20000, 50000, 100000})
    return sorted(value for value in values if value >= 0)


def _collect_week_boundaries(cat: dict[str, Any]) -> dict[int, int]:
    source = cat.get("cat_sem_req_imss")
    if isinstance(source, list) and source and isinstance(source[0], dict):
        source = source[0]
    if not isinstance(source, dict):
        return {}
    result = {}
    for year in range(2026, 2032):
        if str(year) in source:
            result[year] = int(_safe_num(source[str(year)]))
        elif year in source:
            result[year] = int(_safe_num(source[year]))
    return result


def _salary_boundary_cloud(boundary: float) -> list[float]:
    return sorted({round(max(0, boundary + delta), 2) for delta in (-10, -5, -1, 0, 1, 5, 10)})


def _sample_even(items: list[Any], max_items: int) -> list[Any]:
    if len(items) <= max_items:
        return list(items)
    if max_items <= 0:
        return []
    if max_items == 1:
        return [items[0]]
    return [items[round(index * (len(items) - 1) / (max_items - 1))] for index in range(max_items)]


def _first_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _pg_rows(cat: dict[str, Any]) -> list[dict[str, Any]]:
    value = cat.get("pg")
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return [value] if isinstance(value, dict) else []


def _row_number(row: dict[str, Any], *needles: str, default: float = 0) -> float:
    for key, value in row.items():
        label = _strip_accents(key).lower()
        if all(needle in label for needle in needles):
            return _safe_num(value)
    return default


def generate(seed: int = IDENTIFIER_SEED) -> tuple[list[str], list[dict[str, Any]]]:
    _USED_EMAILS.clear()
    _USED_CELLS.clear()
    schema = _read_schema()
    cat = _load_catalogs()
    salary_boundaries = _sample_even(_collect_salary_boundaries(cat), 12)
    pg_rows = _pg_rows(cat)
    sampled_pg_rows = _sample_even(pg_rows, 40)
    sampled_pg_rows_64_65 = _sample_even([row for row in pg_rows if int(_row_number(row, "edad", default=-1)) in {64, 65}], 45)
    quantia_values = _boundary_values(cat.get("cuantias_incrementos"))
    sampled_quantias = _sample_even(sorted(set(quantia_values)), 10)
    week_requirements = _collect_week_boundaries(cat)
    info_fin = _first_dict(cat.get("info_fin"))

    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    seen_imss_ids: set[str] = set()
    seen_issste_ids: set[str] = set()
    idx = 1

    def emit(block: str, regimen: str, age: int, retire: int, **updates: Any) -> None:
        nonlocal idx
        if len(rows) >= MAX_TOTAL_CASES or block_counts[block] >= _BLOCK_BUDGETS[block]:
            return
        client_idx = idx
        case = _base_case(idx, regimen, int(age), int(retire))
        idx += 1
        case.update(updates)
        case["NSS IMSS sintetico"] = ""
        case["ISSSTE_SINTETICO_FORMATO"] = ""
        if regimen in IMSS_REGIMENS:
            try:
                birth = case["Fecha de nacimiento"]
                affiliation = case["Fecha Afiliacion"]
                synthetic_nss = generar_nss_imss(birth, affiliation, client_idx, seed)
                collision_seed = seed
                while synthetic_nss in seen_imss_ids:
                    collision_seed += 1
                    synthetic_nss = generar_nss_imss(birth, affiliation, client_idx, collision_seed)
                if validar_nss_imss(synthetic_nss, birth, affiliation):
                    case["NSS IMSS sintetico"] = synthetic_nss
                    seen_imss_ids.add(synthetic_nss)
            except ValueError:
                pass
        elif regimen == LAN_ISSSTE:
            collision_seed = seed
            synthetic_issste = generar_nss_issste_sintetico(client_idx, collision_seed)
            while synthetic_issste in seen_issste_ids:
                collision_seed += 1
                synthetic_issste = generar_nss_issste_sintetico(client_idx, collision_seed)
            if validar_formato_nss_issste(synthetic_issste):
                case["ISSSTE_SINTETICO_FORMATO"] = synthetic_issste
                seen_issste_ids.add(synthetic_issste)
        if _add_case(rows, seen, schema, case):
            block_counts[block] += 1

    block_counts = {key: 0 for key in _BLOCK_BUDGETS}

    # B1: horizonte de edades y retiros; se conservan los cuatro regímenes.
    for regimen in REGIMENS:
        for age in AGES:
            if regimen == LAN_INDEP and age > 70:
                continue
            for retirement in RETIRE_AGES:
                emit("B1", regimen, age, retirement)

    # B2: semanas alrededor del máximo laboral y pares inverosímiles.
    for age in AGES:
        max_weeks = (age - 18) * 52
        for regimen in (LAN_IMSS97, LAN_IMSS73):
            for weeks in (max_weeks - 1, max_weeks, max_weeks + 1, max_weeks + 500, max_weeks + 1000):
                emit("B2", regimen, age, 65, **{"Semanas cotizadas ante el IMSS": max(0, weeks)})
    for age, weeks in ((30, 2000), (35, 2500), (40, 3000), (25, 1800), (18, 1200)):
        for regimen in (LAN_IMSS97, LAN_IMSS73):
            emit("B2", regimen, age, 65, **{"Semanas cotizadas ante el IMSS": weeks})

    # B3: fronteras de años de servicio y combinaciones incompatibles.
    for age in [value for value in AGES if value <= 90]:
        service = {age - 18, age - 17, age - 13, age - 8, 24, 25, 26, *ISSSTE_SERVICE_LEVELS}
        for years in sorted(service):
            emit("B3", LAN_ISSSTE, age, 65, **{"Años de cotización": max(0, years)})
    for age, years in ((30, 25), (35, 30), (40, 35), (25, 20)):
        emit("B3", LAN_ISSSTE, age, 65, **{"Años de cotización": years})

    # B4: nube alrededor de fronteras salariales catalogadas.
    for boundary in salary_boundaries:
        for salary in _salary_boundary_cloud(boundary):
            for regimen in (LAN_IMSS97, LAN_IMSS73, LAN_ISSSTE):
                for age in (55, 60, 65):
                    emit("B4", regimen, age, 65, **{"Salario básico": salary})

    # B5: semanas requeridas por año, con edad y retiro fronterizos.
    for year, requirement in week_requirements.items():
        for weeks in range(requirement - 2, requirement + 3):
            for age in range(60, 66):
                for retirement in (60, 61, 62, 63, 64, 65, 66, 70):
                    emit("B5", LAN_IMSS97, age, retirement, **{"Semanas cotizadas ante el IMSS": weeks})

    # B6: PG; filas y llaves inferidas de la tabla disponible, si existe.
    for pg_row in sampled_pg_rows:
        age = int(_row_number(pg_row, "edad", default=60))
        pg_value = _row_number(pg_row, "pg", default=_row_number(pg_row, "monto", default=1000))
        retirement = _ret_age_for(age, 65)
        week_limits = (
            _row_number(pg_row, "semanas_min", default=1000),
            _row_number(pg_row, "semanas_max", default=1000),
        )
        salary_limits = (
            _row_number(pg_row, "limite_inf", default=20000),
            _row_number(pg_row, "limite_sup", default=20000),
        )
        target_balance = max(0, int(pg_value * 180))
        for shift in (-1, 0, 1):
            for weeks in week_limits:
                for salary in salary_limits:
                    for balance_delta in (-1, 0, 1):
                        emit(
                            "B6", LAN_IMSS97, max(18, age + shift), retirement,
                            **{
                                "Semanas cotizadas ante el IMSS": max(0, int(weeks)),
                                "Salario básico": max(0, salary),
                                "Saldo de ahorro para el retiro": max(0, target_balance + balance_delta),
                                "Meta mensual para tu retiro": max(1000, int(pg_value)),
                            }
                        )
    # Casos de respaldo para mantener útil el bloque cuando no hay tabla PG.
    if not sampled_pg_rows:
        for age in (59, 60, 64, 65, 66):
            for weeks in (874, 875, 876, 999, 1000, 1001):
                emit("B6", LAN_IMSS97, age, 65, **{"Semanas cotizadas ante el IMSS": weeks})

    # B6b: subgrupo explícito 64/65 y focos de semanas, salario y saldo.
    for pg_row in sampled_pg_rows_64_65:
        pg_age = int(_row_number(pg_row, "edad", default=64))
        if pg_age not in {64, 65}:
            continue
        pg_value = _row_number(pg_row, "pg", default=1000)
        week_limits = (
            int(_row_number(pg_row, "semanas_min", default=874)),
            int(_row_number(pg_row, "semanas_max", default=875)),
        )
        salary_limits = (
            _row_number(pg_row, "limite_inf", default=1),
            _row_number(pg_row, "limite_sup", default=1000),
        )
        target_balance = max(0, int(pg_value * 180))
        for weeks in week_limits:
            for salary in salary_limits:
                for balance_delta in (-1, 0, 1):
                    emit(
                        "B6b", LAN_IMSS97, pg_age, 65,
                        **{
                            "Semanas cotizadas ante el IMSS": weeks,
                            "Salario básico": max(0, salary),
                            "Saldo de ahorro para el retiro": max(0, target_balance + balance_delta),
                            "Meta mensual para tu retiro": max(1000, int(pg_value)),
                        }
                    )
    if not sampled_pg_rows_64_65:
        for field, values in (("Semanas cotizadas ante el IMSS", (874, 875, 876)), ("Salario básico", (1, 1000, 20000)), ("Saldo de ahorro para el retiro", (0, 1, 500000))):
            for value in values:
                emit("B6b", LAN_IMSS97, 64, 65, **{field: value})

    # B7: cuantías, semanas Ley 73 y modalidad 40 aproximada.
    for amount in sampled_quantias or [0, 1, 1000, 10000, 20000, 50000]:
        for age in (50, 60, 65, 75):
            emit("B7", LAN_IMSS73, age, 65, **{"Salario básico": amount})
    for age in (47, 50, 55, 60, 65, 70, 75, 80):
        for weeks in (50, 100, 250, 499, 500, 501, 750, 1000, 1500, 2000, 2500, 3000):
            emit("B7", LAN_IMSS73, age, 65, **{"Semanas cotizadas ante el IMSS": weeks})
    current_year = date.today().year
    for target_year in (2026, 2028, 2030):
        for delta in (-5, -1, 0, 1, 5):
            emit("B7", LAN_IMSS73, 60, 65, **{"Fecha Afiliacion": f"01/07/{target_year + delta - current_year + current_year}"})

    # B8: ISSSTE, ahorro solidario y bono.
    for age in (55, 60, 65, 80):
        for years in (10, 25, 40):
            for solidarity in (0, 0.01, 0.02):
                for bonus in (0, 100000, 1000000):
                    emit("B8", LAN_ISSSTE, age, 65, **{"Años de cotización": years,
                         "Porcentaje de ahorro solidario": solidarity, "Bono de pensión": bonus})

    # B9: independientes con retiros tardíos y saldos/cantidades contrastantes.
    independent_balances = (0, 1, 1000, 100000, 500000, 1000000, 5000000)
    for age in (18, 25, 35, 45, 55, 60, 65, 70):
        for retirement in (60, 62, 65, 70, 80):
            for balance in independent_balances:
                emit("B9", LAN_INDEP, age, retirement, **{"Saldo de ahorro para el retiro": balance,
                     "Saldo ahorro voluntario": balance, "Ahorro mensual adicional": balance / 10})

    # B10: vectores de balances y combinaciones de componentes.
    balances = (0, 1, 100, 1000, 10000, 100000, 500000, 1000000, 5000000, 10000000)
    for regimen in (LAN_IMSS97, LAN_IMSS73, LAN_ISSSTE):
        for balance in balances:
            emit("B10", regimen, 60, 65, **{"Saldo de ahorro para el retiro": balance,
                 "Saldo de subcuenta de vivienda": balance, "Saldo ahorro voluntario": balance})
            emit("B10", regimen, 60, 65, **{"Saldo de ahorro para el retiro": balance,
                 "Saldo de ahorro solidario": balance, "Bono de pensión": balance})

    # B11: secuencias monotónicas. Los campos inactivos se normalizan por régimen.
    for balance in balances:
        emit("B11", LAN_IMSS97, 60, 65, **{"Saldo de ahorro para el retiro": balance,
             "Saldo ahorro voluntario": balance})
        emit("B11", LAN_IMSS97, 60, 65, **{"Semanas cotizadas ante el IMSS": balance})
        emit("B11", LAN_ISSSTE, 60, 65, **{"Años de cotización": balance})
        emit("B11", LAN_ISSSTE, 60, 60 + balance, **{"Saldo de ahorro para el retiro": balance})

    # B12: lista aproximada de diez combinaciones inválidas; no venía el set fuente.
    negative_cases = [
        (LAN_IMSS97, 18, 60, {"Salario básico": -1}),
        (LAN_IMSS97, 30, 65, {"Semanas cotizadas ante el IMSS": -1}),
        (LAN_IMSS73, 47, 65, {"Saldo de ahorro para el retiro": -100}),
        (LAN_ISSSTE, 25, 60, {"Años de cotización": -1}),
        (LAN_ISSSTE, 60, 65, {"Porcentaje de ahorro solidario": -0.01}),
        (LAN_INDEP, 35, 65, {"Ahorro mensual adicional": -1000}),
        (LAN_IMSS97, 45, 65, {"Edad de retiro": 17}),
        (LAN_IMSS73, 55, 65, {"Saldo de subcuenta de vivienda": -1}),
        (LAN_ISSSTE, 60, 65, {"Bono de pensión": -1}),
        (LAN_INDEP, 70, 65, {"Saldo ahorro voluntario": -500}),
    ]
    for regimen, age, retirement, updates in negative_cases:
        emit("B12", regimen, age, retirement, **updates)

    # B13: edad laboral y fecha de Ley 73 (fechas extremas aproximadas).
    min_work_age = int(_safe_num(info_fin.get("edad_laboral_minima", 18))) or 18
    for age in (min_work_age - 1, min_work_age, min_work_age + 1, 18):
        emit("B13", LAN_IMSS97, max(0, age), 65)
    for salary, weeks, balance, age in ((0, 0, 0, 18), (1, 500, 1, 60), (10000000, 3000, 10000000, 65), (20000, 1000, 500000, 110)):
        emit("B13", LAN_IMSS97, age, 65, **{"Salario básico": salary,
             "Semanas cotizadas ante el IMSS": weeks, "Saldo de ahorro para el retiro": balance})
    raw_law_date = info_fin.get("fecha_ley73")
    if raw_law_date:
        try:
            law_date = date.fromisoformat(str(raw_law_date))
            for margin in (-730, -1, 180, 1825):
                boundary_date = law_date + timedelta(days=margin)
                emit("B13", LAN_IMSS73, 60, 65, **{"Fecha Afiliacion": boundary_date.strftime("%d/%m/%Y")})
        except ValueError:
            pass

    # B14: caos de portal; fechas, etiquetas y valores intencionalmente raros.
    odd_dates = ("", "31/02/2000", "29/02/1900", "01/01/0001", "99/99/9999", "2026-12-31")
    odd_genders = ("X", "No binario", "", "Prefiero no decir", "Hombre/Masculino")
    odd_regimens = (LAN_IMSS97, LAN_IMSS73, LAN_ISSSTE, LAN_INDEP, "Régimen desconocido")
    odd_values = (-1000000, -1, 0, 0.01, 999999999, 10**15)
    for offset in range(180):
        age = AGES[offset % len(AGES)]
        regimen = odd_regimens[offset % len(odd_regimens)]
        field_value = odd_values[offset % len(odd_values)]
        emit("B14", regimen, age, (60, 65, 80, 0, 150)[offset % 5],
             **{"Fecha de nacimiento": odd_dates[offset % len(odd_dates)],
                "Género": odd_genders[offset % len(odd_genders)],
                "Nombre completo": f"Prueba {offset} !??",
                "Salario básico": field_value,
                "Saldo de ahorro para el retiro": odd_values[(offset + 1) % len(odd_values)],
                "Saldo de subcuenta de vivienda": odd_values[(offset + 2) % len(odd_values)],
                "CURP": "INVALIDA" if offset % 2 else "",
                "Fecha Afiliacion": odd_dates[(offset + 2) % len(odd_dates)]})

    # B15: prioridades UAT del resumen, con valores de semanas disponibles.
    req_ref = week_requirements.get(2026, min(week_requirements.values(), default=1000))
    for age in (59, 60, 64, 65, 66):
        for delta in (0, 1, 2, 5):
            emit("B15", LAN_IMSS97, age, age + delta)
    for weeks in (req_ref - 1, req_ref, req_ref + 1, 499, 500, 501, 749, 750, 874, 875, 876, 999, 1000, 1001):
        emit("B15", LAN_IMSS97, 60, 65, **{"Semanas cotizadas ante el IMSS": weeks})
    for weeks in (499, 500, 501):
        for voluntary in (0, 1, 1000, 100000):
            emit("B15", LAN_IMSS73, 60, 65, **{"Semanas cotizadas ante el IMSS": weeks,
                 "Saldo ahorro voluntario": voluntary})
    for salary, weeks in ((1, 875), (1000, 1000), (20000, 1250), (100000, 1500)):
        for age in (64, 65):
            emit("B15", LAN_IMSS97, age, 65, **{"Salario básico": salary,
                 "Semanas cotizadas ante el IMSS": weeks})
    for years in (0, 9, 10, 24, 25, 26, 40, 41):
        emit("B15", LAN_ISSSTE, 60, 65, **{"Años de cotización": years})
    for balance in (0, 1, 1000000, 10000000, 10**15):
        emit("B15", LAN_INDEP, 60, 65, **{"Saldo de ahorro para el retiro": balance,
             "Saldo ahorro voluntario": balance, "Ahorro mensual adicional": balance})

    return schema, rows


def _normalized_tokens(value: str) -> list[str]:
    return _strip_accents(value).casefold().split()


def _take_surname_suffix(tokens: list[str], surnames: list[str]) -> tuple[list[str], str] | None:
    candidates = sorted(surnames, key=lambda surname: len(_normalized_tokens(surname)), reverse=True)
    normalized_tokens = [_strip_accents(token).casefold() for token in tokens]
    for surname in candidates:
        parts = _normalized_tokens(surname)
        if parts and normalized_tokens[-len(parts):] == parts:
            return tokens[:-len(parts)], " ".join(tokens[-len(parts):])
    return None


def _split_generated_name(full_name: str, surnames: list[str]) -> tuple[str, str, str] | None:
    tokens = full_name.split()
    maternal = _take_surname_suffix(tokens, surnames)
    if maternal is None:
        return None
    before_maternal, maternal_name = maternal
    paternal = _take_surname_suffix(before_maternal, surnames)
    if paternal is None:
        return None
    given_tokens, paternal_name = paternal
    if not given_tokens:
        return None
    return " ".join(given_tokens), paternal_name, maternal_name


def _numeric_or_none(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 and number < float("inf") else None


def mapear_clientes_web(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Normaliza casos válidos al layout que consumen los seis scrapers."""
    people = _load_people_catalogs()
    surnames = people["surnames"]
    mapped = {target: [] for target, _ in WEB_REGIMENS.values()}
    cutoff = date(1997, 7, 1)
    used_ids: set[str] = set()

    for source_index, row in enumerate(rows, start=1):
        regimen = row.get("Regimen")
        if regimen not in WEB_REGIMENS or str(row.get("Nombre completo", "")).startswith("Prueba "):
            continue
        identity = _split_generated_name(str(row.get("Nombre completo", "")), surnames)
        birth = _parse_case_date(row.get("Fecha de nacimiento", ""))
        curp = str(row.get("CURP", "")).strip().upper()
        gender = {"Masculino": "H", "Femenino": "M"}.get(row.get("Genero"))
        if identity is None or birth is None or gender is None:
            continue
        age = date.today().year - birth.year - ((date.today().month, date.today().day) < (birth.month, birth.day))
        if age < 18 or age > 64 or len(curp) != 18 or curp[4:10] != birth.strftime("%y%m%d"):
            continue
        if curp[10] != gender or not curp[11:13].isalpha():
            continue

        salary = _numeric_or_none(row.get("Salario basico"))
        rcv = _numeric_or_none(row.get("Saldo de ahorro para el retiro"))
        housing = _numeric_or_none(row.get("Saldo de subcuenta de vivienda"))
        voluntary_balance = _numeric_or_none(row.get("Saldo ahorro voluntario"))
        voluntary_monthly = _numeric_or_none(row.get("Ahorro mensual adicional"))
        if None in (salary, rcv, housing, voluntary_balance, voluntary_monthly):
            continue

        target_regimen, law = WEB_REGIMENS[regimen]
        affiliation = _parse_case_date(row.get("Fecha Afiliacion", ""))
        weeks: int | None = None
        years: int | None = None
        nss = ""
        issste_id = ""
        solidarity = _numeric_or_none(row.get("Porcentaje de ahorro solidario"))
        solidarity_balance = _numeric_or_none(row.get("Saldo de ahorro solidario"))
        bonus = _numeric_or_none(row.get("Bono de pension"))

        if target_regimen.startswith("IMSS"):
            raw_weeks = _numeric_or_none(row.get("Semanas cotizadas ante el IMSS"))
            if (affiliation is None or raw_weeks is None or not raw_weeks.is_integer()
                    or affiliation < _safe_date_replace_year(birth, birth.year + 18)
                    or (target_regimen == "IMSS73" and affiliation >= cutoff)
                    or (target_regimen == "IMSS97" and affiliation < cutoff)):
                continue
            weeks = int(raw_weeks)
            if weeks < 1 or weeks > (age - 18) * 52:
                continue
            years = weeks // 52
            nss = str(row.get("NSS IMSS sintetico", ""))
            if not validar_nss_imss(nss, birth, affiliation):
                continue
        else:
            raw_years = _numeric_or_none(row.get("Anos de cotizacion"))
            if (raw_years is None or not raw_years.is_integer() or raw_years < 1
                    or raw_years > age - 18 or solidarity is None
                    or solidarity <= 0 or solidarity_balance is None or bonus is None):
                continue
            years = int(raw_years)
            if solidarity <= 0.02:
                solidarity *= 100
            if solidarity < 1 or solidarity > 2:
                continue
            issste_id = str(row.get("ISSSTE_SINTETICO_FORMATO", ""))
            if not validar_formato_nss_issste(issste_id):
                continue

        client_id = str(source_index)
        if client_id in used_ids:
            continue
        used_ids.add(client_id)
        mapped[target_regimen].append({
            "id_cliente": client_id,
            "nombre": identity[0],
            "ap_paterno": identity[1],
            "ap_materno": identity[2],
            "age": str(age),
            "f_nacim": birth.isoformat(),
            "genero": gender,
            "entidad": curp[11:13],
            "nss": nss,
            "num_issste": issste_id,
            "curp": curp,
            "correo": str(row.get("Correo electronico", "")).strip(),
            "anios_cotizados": str(years),
            "anio_fil": str(affiliation.year) if affiliation else "",
            "sem_cot": str(weeks) if weeks is not None else "",
            "salario_mensual": str(salary),
            "saldo_rcv": str(rcv),
            "saldo_ahorro_solidario": str(solidarity_balance or 0),
            "porcentaje_ahorro_solidario": str(solidarity or 0),
            "saldo_bono_pension": str(bonus or 0),
            "saldo_av": str(voluntary_balance),
            "saldo_vivienda": str(housing),
            "av_mensual": str(voluntary_monthly),
            "regimen_estimado": target_regimen,
            "ley_bandera": law,
            "escenario_estimado": "CASO_SINTETICO",
        })
    return mapped


def escribir_datasets_web(rows: list[dict[str, Any]], timestamp: str | None = None) -> Path:
    mapped = mapear_clientes_web(rows)
    if any(len(mapped[target]) < 3 for target, _ in WEB_REGIMENS.values()):
        counts = {regimen: len(clientes) for regimen, clientes in mapped.items()}
        raise ValueError("Se requieren al menos 3 clientes válidos por régimen: {}".format(counts))
    folder_timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_dir = OUTPUT_DIR / "data_{}".format(folder_timestamp)
    output_dir.mkdir(parents=True, exist_ok=False)
    filenames = {
        "IMSS97": "clientes_IMSS97.csv",
        "IMSS73": "clientes_IMSS73.csv",
        "ISSSTE": "clientes_ISSSTE_Cuentas_Individuales.csv",
    }
    for regimen, filename in filenames.items():
        path = output_dir / filename
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=WEB_CLIENT_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(mapped[regimen])
        print("{} clientes {}: {}".format(len(mapped[regimen]), regimen, path.resolve()))
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera casos pensionarios con identificadores sintéticos.")
    parser.add_argument("--seed", type=int, default=IDENTIFIER_SEED)
    args = parser.parse_args()
    if not any(candidate.is_file() for candidate in SCHEMA_CANDIDATES):
        print("No se encontró CSV de esquema; se usará el layout documentado de 22 campos.")
    if not CATALOG_PKL.is_file():
        print("No se encontró catalogs_consolidated.pkl; se usarán los valores de respaldo.")
    _, rows = generate(seed=args.seed)
    print("{} casos generados para pruebas".format(len(rows)))
    output_dir = escribir_datasets_web(rows)
    print("Datasets listos para WebScrapp: {}".format(output_dir.resolve()))


if __name__ == "__main__":
    main()