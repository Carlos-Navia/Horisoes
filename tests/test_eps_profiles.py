from __future__ import annotations

from pathlib import Path
import unittest

from auditoria_pdf.domain import AuditContext, DocumentType, ParsedDocument
from auditoria_pdf.eps_profiles import (
    CoosaludAuditProfile,
    EpsAuditProfileFactory,
    EpsProfileKey,
    NuevaEpsAuditProfile,
    SanitasAuditProfile,
)
from auditoria_pdf.parsing.document_parsers import NuevaEpsPdeDocumentParser, SanitasPdeDocumentParser
from auditoria_pdf.rules import CupsMatchRule, CupsMatchSkippedRule


def _build_document(
    doc_type: DocumentType,
    prefix: str,
    cups_codes: set[str],
) -> ParsedDocument:
    return ParsedDocument(
        doc_type=doc_type,
        source_path=Path(f"{prefix}_demo.pdf"),
        raw_text="",
        prefix=prefix,
        cups_codes=cups_codes,
    )


class EpsProfilesTest(unittest.TestCase):
    def test_factory_supports_three_explicit_profiles(self) -> None:
        factory = EpsAuditProfileFactory()
        self.assertIsInstance(factory.create_for_coosalud(), CoosaludAuditProfile)
        self.assertIsInstance(factory.create_for_nueva_eps(), NuevaEpsAuditProfile)
        self.assertIsInstance(factory.create_for_sanitas(), SanitasAuditProfile)
        self.assertIsInstance(factory.create(EpsProfileKey.NUEVA_EPS.value), NuevaEpsAuditProfile)
        self.assertIsInstance(factory.create(EpsProfileKey.SANITAS.value), SanitasAuditProfile)

    def test_factory_rejects_unsupported_eps(self) -> None:
        factory = EpsAuditProfileFactory()
        with self.assertRaises(ValueError):
            factory.create("sura")

    def test_profiles_isolate_cups_rule_behavior(self) -> None:
        context = AuditContext(
            mandatory_documents={
                DocumentType.FACTURA: _build_document(
                    DocumentType.FACTURA, "FEV", {"8901"}
                ),
                DocumentType.AUTORIZACION: _build_document(
                    DocumentType.AUTORIZACION, "PDE", {"9999"}
                ),
            },
            additional_documents=[],
            total_input_pdfs=2,
            min_pdfs=2,
            max_pdfs=6,
        )
        coosalud_rule = CoosaludAuditProfile().build_rules()[1]
        nueva_eps_rule = NuevaEpsAuditProfile().build_rules()[1]
        sanitas_rule = SanitasAuditProfile().build_rules()[1]

        self.assertIsInstance(coosalud_rule, CupsMatchSkippedRule)
        self.assertIsInstance(nueva_eps_rule, CupsMatchRule)
        self.assertIsInstance(sanitas_rule, CupsMatchRule)
        self.assertTrue(coosalud_rule.evaluate(context).passed)
        self.assertFalse(nueva_eps_rule.evaluate(context).passed)
        self.assertFalse(sanitas_rule.evaluate(context).passed)

    def test_nueva_eps_profile_overrides_only_pde_parser(self) -> None:
        overrides = NuevaEpsAuditProfile().parser_overrides()
        self.assertIn(DocumentType.AUTORIZACION, overrides)
        self.assertIsInstance(overrides[DocumentType.AUTORIZACION], NuevaEpsPdeDocumentParser)
        self.assertNotIn(DocumentType.FACTURA, overrides)
        self.assertEqual(CoosaludAuditProfile().parser_overrides(), {})

        sanitas_overrides = SanitasAuditProfile().parser_overrides()
        self.assertIn(DocumentType.AUTORIZACION, sanitas_overrides)
        self.assertIsInstance(
            sanitas_overrides[DocumentType.AUTORIZACION], SanitasPdeDocumentParser
        )


if __name__ == "__main__":
    unittest.main()
