from __future__ import annotations

import argparse
from pathlib import Path
import unittest

from auditoria_pdf.cli import AuditServiceFactory
from auditoria_pdf.domain import DocumentType
from auditoria_pdf.eps_profiles import EpsProfileKey
from auditoria_pdf.parsing.document_parsers import (
    AdditionalDocumentParser,
    NuevaEpsPdeDocumentParser,
    PdeDocumentParser,
    SanitasPdeDocumentParser,
)
from auditoria_pdf.rules import CupsMatchRule, CupsMatchSkippedRule


class AuditServiceFactoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = AuditServiceFactory()

    def test_create_for_coosalud_uses_independent_rules(self) -> None:
        args = self._build_args(eps=EpsProfileKey.COOSALUD.value)
        service = self.factory.create_for_coosalud(args)
        self.assertIsInstance(service.rules[1], CupsMatchSkippedRule)

    def test_create_for_nueva_eps_uses_independent_rules(self) -> None:
        args = self._build_args(eps=EpsProfileKey.NUEVA_EPS.value)
        service = self.factory.create_for_nueva_eps(args)
        self.assertIsInstance(service.rules[1], CupsMatchRule)

    def test_create_for_sanitas_uses_independent_rules(self) -> None:
        args = self._build_args(eps=EpsProfileKey.SANITAS.value)
        service = self.factory.create_for_sanitas(args)
        self.assertIsInstance(service.rules[1], CupsMatchRule)

    def test_create_dispatches_eps_profile(self) -> None:
        coosalud_service = self.factory.create(
            self._build_args(eps=EpsProfileKey.COOSALUD.value)
        )
        nueva_eps_service = self.factory.create(
            self._build_args(eps=EpsProfileKey.NUEVA_EPS.value)
        )
        sanitas_service = self.factory.create(
            self._build_args(eps=EpsProfileKey.SANITAS.value)
        )

        self.assertIsInstance(coosalud_service.rules[1], CupsMatchSkippedRule)
        self.assertIsInstance(nueva_eps_service.rules[1], CupsMatchRule)
        self.assertIsInstance(sanitas_service.rules[1], CupsMatchRule)

    def test_services_read_full_documents_by_default(self) -> None:
        service = self.factory.create_for_nueva_eps(
            self._build_args(eps=EpsProfileKey.NUEVA_EPS.value)
        )

        self.assertTrue(all(limit is None for limit in service.page_limits.values()))

    def test_create_for_nueva_eps_uses_nueva_eps_pde_parser(self) -> None:
        service = self.factory.create_for_nueva_eps(
            self._build_args(eps=EpsProfileKey.NUEVA_EPS.value)
        )
        parser = service.parser_resolver.resolve(DocumentType.AUTORIZACION, "PDE")
        self.assertIsInstance(parser, NuevaEpsPdeDocumentParser)

    def test_create_for_coosalud_keeps_default_pde_parser(self) -> None:
        service = self.factory.create_for_coosalud(
            self._build_args(eps=EpsProfileKey.COOSALUD.value)
        )
        parser = service.parser_resolver.resolve(DocumentType.AUTORIZACION, "PDE")
        self.assertIsInstance(parser, PdeDocumentParser)

    def test_create_for_nueva_eps_preserves_default_fallback_parsers(self) -> None:
        service = self.factory.create_for_nueva_eps(
            self._build_args(eps=EpsProfileKey.NUEVA_EPS.value)
        )
        parser = service.parser_resolver.resolve(DocumentType.ADICIONAL, "ZZZ")
        self.assertIsInstance(parser, AdditionalDocumentParser)

    def test_create_for_sanitas_uses_sanitas_pde_parser(self) -> None:
        service = self.factory.create_for_sanitas(
            self._build_args(eps=EpsProfileKey.SANITAS.value)
        )
        parser = service.parser_resolver.resolve(DocumentType.AUTORIZACION, "PDE")
        self.assertIsInstance(parser, SanitasPdeDocumentParser)

    def test_pde_regimen_differs_by_eps_profile_for_same_text(self) -> None:
        text = """
        IPS Primaria: SUBSIDIADO-RED SALUD ARMENIA ESE
        Tipo Afiliado: CABEZA DE FAMILIA
        Categoria A filiado: A
        Semanas Cotizadas: 4
        """
        source = Path("PDE_901011395_DEMO.pdf")

        coosalud_service = self.factory.create_for_coosalud(
            self._build_args(eps=EpsProfileKey.COOSALUD.value)
        )
        nueva_eps_service = self.factory.create_for_nueva_eps(
            self._build_args(eps=EpsProfileKey.NUEVA_EPS.value)
        )

        coosalud_parser = coosalud_service.parser_resolver.resolve(
            DocumentType.AUTORIZACION,
            "PDE",
        )
        nueva_eps_parser = nueva_eps_service.parser_resolver.resolve(
            DocumentType.AUTORIZACION,
            "PDE",
        )
        self.assertIsNotNone(coosalud_parser)
        self.assertIsNotNone(nueva_eps_parser)

        coosalud_regimen = coosalud_parser.parse(source, text, prefix="PDE").regimen
        nueva_eps_regimen = nueva_eps_parser.parse(source, text, prefix="PDE").regimen

        self.assertEqual(coosalud_regimen, "SUBSIDIADO")
        self.assertEqual(nueva_eps_regimen, "CONTRIBUTIVO")

    def _build_args(self, eps: str) -> argparse.Namespace:
        return argparse.Namespace(
            eps=eps,
            tesseract_cmd=None,
            min_pdfs=2,
            max_pdfs=6,
        )


if __name__ == "__main__":
    unittest.main()
