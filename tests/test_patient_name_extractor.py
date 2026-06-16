from __future__ import annotations

import unittest

from auditoria_pdf.parsing.patient_name_extractors import GenericPatientNameExtractor


class PatientNameExtractorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = GenericPatientNameExtractor()

    def test_extracts_fev_structured_name_fields(self) -> None:
        text = """
        DATOS SALUD
        PRIMER NOMBRE
        GLADYS
        PRIMER APELLIDO
        TABORDA
        SEGUNDO APELLIDO
        GIRALDO
        NUMERO AUTORIZA.
        """

        self.assertEqual(self.extractor.extract(text), "GLADYS TABORDA GIRALDO")

    def test_extracts_pde_name_label_on_next_line(self) -> None:
        text = """
        Informacion Afiliado
        Nombre
        GLADYS OMAIRA TABORDA GIRALDO
        Fecha de nacimiento
        1956-09-15
        """

        self.assertEqual(self.extractor.extract(text), "GLADYS OMAIRA TABORDA GIRALDO")

    def test_extracts_crc_nombres_apellidos_compact_layout(self) -> None:
        text = """
        Fecha de atencion del servicio 10/02/2026NombresGLADYS OMAIRA ApellidosTABORDA  GIRALDO
        Tipo de Identificacion Cedula de Ciudadania
        """

        self.assertEqual(self.extractor.extract(text), "GLADYS OMAIRA TABORDA GIRALDO")

    def test_extracts_nombres_y_apellidos_without_following_field(self) -> None:
        text = """
        NOMBRES Y APELLIDOS: GLADYS OMAIRA TABORDA FECHA DE EMISION: 10/02/2026
        GENERO: FEMENINO EPS: NUEVA EPS
        """

        self.assertEqual(self.extractor.extract(text), "GLADYS OMAIRA TABORDA")


if __name__ == "__main__":
    unittest.main()
