from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class DocumentType(str, Enum):
    FACTURA = "FEV"
    AUTORIZACION = "PDE"
    SOPORTE = "CRC"
    VALIDADOR = "HEV"
    ADICIONAL = "ADICIONAL"


@dataclass(slots=True)
class ParsedDocument:
    doc_type: DocumentType
    source_path: Path
    raw_text: str
    prefix: str
    patient_document: str | None = None
    patient_name: str | None = None
    patient_document_type: str | None = None
    cups_codes: set[str] = field(default_factory=set)
    regimen: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["doc_type"] = self.doc_type.value
        payload["source_path"] = str(self.source_path)
        payload["cups_codes"] = sorted(self.cups_codes)
        return payload


@dataclass(slots=True)
class AuditContext:
    mandatory_documents: dict[DocumentType, ParsedDocument]
    additional_documents: list[ParsedDocument]
    total_input_pdfs: int
    min_pdfs: int
    max_pdfs: int

    def get_mandatory(self, doc_type: DocumentType) -> ParsedDocument | None:
        return self.mandatory_documents.get(doc_type)

    def all_documents(self) -> list[ParsedDocument]:
        return [*self.mandatory_documents.values(), *self.additional_documents]


@dataclass(slots=True)
class RuleResult:
    rule_id: str
    description: str
    passed: bool
    expected: str | None = None
    actual: str | None = None
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AuditReport:
    generated_at: datetime
    context: AuditContext
    rule_results: list[RuleResult]
    errors: list[str] = field(default_factory=list)

    @property
    def parsed_documents(self) -> list[ParsedDocument]:
        return self.context.all_documents()

    @property
    def success(self) -> bool:
        return not self.errors and all(result.passed for result in self.rule_results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "success": self.success,
            "errors": self.errors,
            "context": {
                "total_input_pdfs": self.context.total_input_pdfs,
                "min_pdfs": self.context.min_pdfs,
                "max_pdfs": self.context.max_pdfs,
                "mandatory_documents": {
                    doc_type.value: parsed.to_dict()
                    for doc_type, parsed in self.context.mandatory_documents.items()
                },
                "additional_documents": [doc.to_dict() for doc in self.context.additional_documents],
            },
            "rule_results": [result.to_dict() for result in self.rule_results],
        }
