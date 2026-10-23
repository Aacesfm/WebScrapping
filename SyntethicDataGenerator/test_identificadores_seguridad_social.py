import csv
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))

from generar_casos_pruebas_completas import (
    FALLBACK_SCHEMA,
    IMSS_REGIMENS,
    LAN_ISSSTE,
    generate,
    mapear_clientes_web,
    escribir_datasets_web,
    WEB_CLIENT_COLUMNS,
)
from identificadores_seguridad_social import (
    calcular_digito_verificador_imss,
    generar_nss_imss,
    generar_nss_issste_sintetico,
    validar_formato_nss_issste,
    validar_nss_imss,
)


class IdentificadoresSeguridadSocialTests(unittest.TestCase):
    def test_luhn_imss(self):
        self.assertEqual(calcular_digito_verificador_imss("7992739871"), "3")

    def test_imss_reproducible_y_consistente_con_fechas(self):
        birth = date(1980, 5, 4)
        affiliation = date(2000, 1, 1)
        nss = generar_nss_imss(birth, affiliation, 12, 99)

        self.assertEqual(nss, generar_nss_imss(birth, affiliation, 12, 99))
        self.assertEqual(len(nss), 11)
        self.assertTrue(validar_nss_imss(nss, birth, affiliation))
        self.assertFalse(validar_nss_imss(nss, date(1981, 5, 4), affiliation))
        self.assertFalse(validar_nss_imss(nss, birth, date(2001, 1, 1)))

    def test_imss_rechaza_afiliacion_antes_de_los_18(self):
        with self.assertRaises(ValueError):
            generar_nss_imss("2000-01-01", "2017-12-31", 1, 4)

    def test_issste_solo_valida_formato_y_es_reproducible(self):
        identifier = generar_nss_issste_sintetico(1, 42)

        self.assertEqual(identifier, generar_nss_issste_sintetico(1, 42))
        self.assertNotEqual(identifier, generar_nss_issste_sintetico(2, 42))
        self.assertTrue(validar_formato_nss_issste(identifier))
        self.assertFalse(validar_formato_nss_issste(int(identifier)))
        self.assertFalse(validar_formato_nss_issste("1234567890A"))

    def test_generador_asigna_columnas_segun_regimen_y_sin_duplicados(self):
        schema, rows = generate(seed=314)
        _, repeated_rows = generate(seed=314)
        self.assertEqual(schema, FALLBACK_SCHEMA)
        self.assertIn("NSS IMSS sintetico", schema)
        self.assertIn("ISSSTE_SINTETICO_FORMATO", schema)
        case_columns = [
            column for column in schema
            if column not in {"NSS IMSS sintetico", "ISSSTE_SINTETICO_FORMATO"}
        ]
        case_keys = [tuple(row[column] for column in case_columns) for row in rows]
        self.assertEqual(len(case_keys), len(set(case_keys)))

        imss_ids = []
        issste_ids = []
        for row in rows:
            imss_id = row["NSS IMSS sintetico"]
            issste_id = row["ISSSTE_SINTETICO_FORMATO"]
            if row["Regimen"] in IMSS_REGIMENS:
                self.assertEqual(issste_id, "")
                if imss_id:
                    self.assertTrue(validar_nss_imss(
                        imss_id,
                        row["Fecha de nacimiento"],
                        row["Fecha Afiliacion"],
                    ))
                    imss_ids.append(imss_id)
            elif row["Regimen"] == LAN_ISSSTE:
                self.assertEqual(imss_id, "")
                self.assertTrue(validar_formato_nss_issste(issste_id))
                issste_ids.append(issste_id)
            else:
                self.assertEqual(imss_id, "")
                self.assertEqual(issste_id, "")

        self.assertEqual(len(imss_ids), len(set(imss_ids)))
        self.assertEqual(len(issste_ids), len(set(issste_ids)))
        self.assertEqual(
            [row["NSS IMSS sintetico"] for row in rows],
            [row["NSS IMSS sintetico"] for row in repeated_rows],
        )
        self.assertEqual(
            [row["ISSSTE_SINTETICO_FORMATO"] for row in rows],
            [row["ISSSTE_SINTETICO_FORMATO"] for row in repeated_rows],
        )

    def test_exportacion_crea_tres_archivos_en_carpeta_data_timestamp(self):
        _, rows = generate(seed=42)
        with tempfile.TemporaryDirectory() as directory:
            with patch("generar_casos_pruebas_completas.OUTPUT_DIR", Path(directory)):
                folder = escribir_datasets_web(rows, timestamp="20261022_120000")

            self.assertEqual(folder.name, "data_20261022_120000")
            self.assertEqual(
                {path.name for path in folder.iterdir()},
                {
                    "clientes_IMSS97.csv",
                    "clientes_IMSS73.csv",
                    "clientes_ISSSTE_Cuentas_Individuales.csv",
                },
            )
            for path in folder.iterdir():
                with path.open(encoding="utf-8-sig", newline="") as file:
                    header = next(csv.reader(file))
                self.assertEqual(header, WEB_CLIENT_COLUMNS)

    def test_mapeo_entrega_al_menos_tres_clientes_scrapeables_por_regimen(self):
        _, rows = generate(seed=42)
        mapped = mapear_clientes_web(rows)
        self.assertEqual(set(mapped), {"IMSS97", "IMSS73", "ISSSTE"})
        self.assertTrue(all(len(clients) >= 3 for clients in mapped.values()))
        self.assertTrue(all(client["nombre"] and client["ap_paterno"] and client["ap_materno"]
                            for clients in mapped.values() for client in clients))


if __name__ == "__main__":
    unittest.main()