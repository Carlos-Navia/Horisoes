from __future__ import annotations

from pathlib import Path
import unittest

from auditoria_pdf.cli import CliArgumentFactory
from auditoria_pdf.domain import AuditContext, DocumentType, ParsedDocument
from auditoria_pdf.rules import (
    CupsMatchRule,
    FileSetComplianceRule,
    PatientDocumentConsistencyRule,
    RegimenConsistencyRule,
)


def _build_document(
    doc_type: DocumentType,
    prefix: str,
    source_name: str,
    *,
    patient_document: str | None = "123456789",
    patient_name: str | None = "PACIENTE DEMO",
    regimen: str | None = "SUBSIDIADO",
    cups_codes: set[str] | None = None,
) -> ParsedDocument:
    return ParsedDocument(
        doc_type=doc_type,
        source_path=Path(source_name),
        raw_text="",
        prefix=prefix,
        patient_document=patient_document,
        patient_name=patient_name,
        regimen=regimen,
        cups_codes=cups_codes or set(),
    )


class OptionalPdeBehaviorTest(unittest.TestCase):
    def test_cli_default_min_pdfs_is_two(self) -> None:
        parser = CliArgumentFactory().build()
        args = parser.parse_args([])
        self.assertEqual(args.min_pdfs, 2)

    def test_file_set_rule_fails_with_only_fev(self) -> None:
        fev = _build_document(
            DocumentType.FACTURA,
            "FEV",
            "FEV_demo.pdf",
            cups_codes={"8901"},
        )
        context = AuditContext(
            mandatory_documents={DocumentType.FACTURA: fev},
            additional_documents=[],
            total_input_pdfs=1,
            min_pdfs=2,
            max_pdfs=6,
        )

        result = FileSetComplianceRule().evaluate(context)

        self.assertFalse(result.passed)
        self.assertIn("al menos un PDF adicional", " ".join(result.details))

    def test_file_set_rule_passes_with_fev_plus_optional_pdf(self) -> None:
        fev = _build_document(
            DocumentType.FACTURA,
            "FEV",
            "FEV_demo.pdf",
            cups_codes={"8901"},
        )
        crc = _build_document(
            DocumentType.SOPORTE,
            "CRC",
            "CRC_demo.pdf",
            patient_document="123456789",
        )
        context = AuditContext(
            mandatory_documents={DocumentType.FACTURA: fev},
            additional_documents=[crc],
            total_input_pdfs=2,
            min_pdfs=2,
            max_pdfs=6,
        )

        result = FileSetComplianceRule().evaluate(context)

        self.assertTrue(result.passed)
        self.assertEqual(result.details, ["Estructura del lote valida."])

    def test_cups_rule_is_skipped_when_pde_is_missing(self) -> None:
        fev = _build_document(
            DocumentType.FACTURA,
            "FEV",
            "FEV_demo.pdf",
            cups_codes={"8901"},
        )
        crc = _build_document(
            DocumentType.SOPORTE,
            "CRC",
            "CRC_demo.pdf",
        )
        context = AuditContext(
            mandatory_documents={DocumentType.FACTURA: fev},
            additional_documents=[crc],
            total_input_pdfs=2,
            min_pdfs=2,
            max_pdfs=6,
        )

        result = CupsMatchRule().evaluate(context)

        self.assertTrue(result.passed)
        self.assertIn("PDE es opcional", " ".join(result.details))

    def test_cups_rule_fails_when_pde_has_extra_codes(self) -> None:
        fev = _build_document(
            DocumentType.FACTURA,
            "FEV",
            "FEV_demo.pdf",
            cups_codes={"907009"},
        )
        pde = _build_document(
            DocumentType.AUTORIZACION,
            "PDE",
            "PDE_demo.pdf",
            cups_codes={"907009", "890205"},
        )
        context = AuditContext(
            mandatory_documents={
                DocumentType.FACTURA: fev,
                DocumentType.AUTORIZACION: pde,
            },
            additional_documents=[],
            total_input_pdfs=2,
            min_pdfs=2,
            max_pdfs=6,
        )

        result = CupsMatchRule().evaluate(context)

        self.assertFalse(result.passed)
        self.assertIn("no presentes en FEV", " ".join(result.details))

    def test_regimen_rule_is_skipped_when_pde_is_missing(self) -> None:
        fev = _build_document(
            DocumentType.FACTURA,
            "FEV",
            "FEV_demo.pdf",
            regimen="SUBSIDIADO",
        )
        crc = _build_document(
            DocumentType.SOPORTE,
            "CRC",
            "CRC_demo.pdf",
        )
        context = AuditContext(
            mandatory_documents={DocumentType.FACTURA: fev},
            additional_documents=[crc],
            total_input_pdfs=2,
            min_pdfs=2,
            max_pdfs=6,
        )

        result = RegimenConsistencyRule().evaluate(context)

        self.assertTrue(result.passed)
        self.assertIn("PDE es opcional", " ".join(result.details))

    def test_document_rule_passes_when_no_targets_exist(self) -> None:
        fev = _build_document(
            DocumentType.FACTURA,
            "FEV",
            "FEV_demo.pdf",
            patient_document="123456789",
        )
        context = AuditContext(
            mandatory_documents={DocumentType.FACTURA: fev},
            additional_documents=[],
            total_input_pdfs=1,
            min_pdfs=2,
            max_pdfs=6,
        )

        result = PatientDocumentConsistencyRule().evaluate(context)

        self.assertTrue(result.passed)
        self.assertIn("regla omitida", " ".join(result.details).lower())

    def test_document_rule_passes_when_document_missing_but_name_matches(self) -> None:
        fev = _build_document(
            DocumentType.FACTURA,
            "FEV",
            "FEV_demo.pdf",
            patient_document="123456789",
            patient_name="GLADYS OMAIRA TABORDA GIRALDO",
        )
        crc = _build_document(
            DocumentType.SOPORTE,
            "CRC",
            "CRC_demo.pdf",
            patient_document=None,
            patient_name="GLADYS OMAIRA TABORDA GIRALDO",
        )
        context = AuditContext(
            mandatory_documents={DocumentType.FACTURA: fev},
            additional_documents=[crc],
            total_input_pdfs=2,
            min_pdfs=2,
            max_pdfs=6,
        )

        result = PatientDocumentConsistencyRule().evaluate(context)

        self.assertTrue(result.passed)
        self.assertIn("Coincidencia por nombre exacto", " ".join(result.details))

    def test_document_rule_fails_when_neither_document_nor_name_matches(self) -> None:
        fev = _build_document(
            DocumentType.FACTURA,
            "FEV",
            "FEV_demo.pdf",
            patient_document="123456789",
            patient_name="GLADYS OMAIRA TABORDA GIRALDO",
        )
        crc = _build_document(
            DocumentType.SOPORTE,
            "CRC",
            "CRC_demo.pdf",
            patient_document="999999999",
            patient_name="MARIA SOLEDAD RUIZ",
        )
        context = AuditContext(
            mandatory_documents={DocumentType.FACTURA: fev},
            additional_documents=[crc],
            total_input_pdfs=2,
            min_pdfs=2,
            max_pdfs=6,
        )

        result = PatientDocumentConsistencyRule().evaluate(context)

        self.assertFalse(result.passed)
        self.assertIn("Diferencia detectada", " ".join(result.details))


if __name__ == "__main__":
    unittest.main()
