from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from auditoria_pdf.domain import DocumentType, ParsedDocument
from auditoria_pdf.extractor import PdfTextExtractor
from auditoria_pdf.parsing.document_parsers import BaseDocumentParser


@dataclass(slots=True)
class PageLimitResolver:
    page_limits: dict[DocumentType, int | None]

    def resolve(self, document_type: DocumentType) -> int | None:
        return self.page_limits.get(document_type)


@dataclass(slots=True)
class RenderFallbackPolicy:
    allowed_types: set[DocumentType]

    def allows(self, document_type: DocumentType) -> bool:
        return document_type in self.allowed_types


class DocumentRetryPolicy:
    def needs_full_retry(self, document_type: DocumentType, parsed: ParsedDocument) -> bool:
        if document_type in {DocumentType.FACTURA, DocumentType.AUTORIZACION}:
            return not parsed.patient_document or not parsed.regimen
        if document_type in {
            DocumentType.SOPORTE,
            DocumentType.VALIDADOR,
            DocumentType.ADICIONAL,
        }:
            return not parsed.patient_document and not parsed.patient_name
        return False


@dataclass(slots=True)
class SinglePdfProcessingEngine:
    extractor: PdfTextExtractor
    page_limit_resolver: PageLimitResolver
    render_fallback_policy: RenderFallbackPolicy
    retry_policy: DocumentRetryPolicy

    def process(
        self,
        source_path: Path,
        document_type: DocumentType,
        prefix: str,
        parser: BaseDocumentParser,
    ) -> ParsedDocument:
        page_limit = self.page_limit_resolver.resolve(document_type)
        allow_render_fallback = self.render_fallback_policy.allows(document_type)

        raw_text = self.extractor.extract_text_limited(
            source_path,
            max_pages=page_limit,
            allow_render_fallback=allow_render_fallback,
        )
        parsed = parser.parse(source_path, raw_text, prefix=prefix)

        if not parser.allows_raw_text_retry():
            return parsed

        if self.retry_policy.needs_full_retry(document_type, parsed):
            raw_text_full = self.extractor.extract_text_limited(
                source_path,
                max_pages=None,
                allow_render_fallback=allow_render_fallback,
            )
            parsed_full = parser.parse(source_path, raw_text_full, prefix=prefix)
            parsed = self._merge_missing_fields(parsed, parsed_full)

        if self.retry_policy.needs_full_retry(document_type, parsed):
            raw_text_aggressive = self.extractor.extract_text_limited(
                source_path,
                max_pages=None,
                allow_render_fallback=True,
                ocr_psm=3,
                force_render_fallback=True,
            )
            parsed_aggressive = parser.parse(source_path, raw_text_aggressive, prefix=prefix)
            parsed = self._merge_missing_fields(parsed, parsed_aggressive)

        return parsed

    def _merge_missing_fields(
        self,
        parsed: ParsedDocument,
        candidate: ParsedDocument,
    ) -> ParsedDocument:
        improved = False

        if not parsed.patient_document and candidate.patient_document:
            parsed.patient_document = candidate.patient_document
            improved = True

        if not parsed.patient_document_type and candidate.patient_document_type:
            parsed.patient_document_type = candidate.patient_document_type
            improved = True

        if not parsed.patient_name and candidate.patient_name:
            parsed.patient_name = candidate.patient_name
            improved = True

        if not parsed.regimen and candidate.regimen:
            parsed.regimen = candidate.regimen
            improved = True

        if not parsed.cups_codes and candidate.cups_codes:
            parsed.cups_codes = candidate.cups_codes
            improved = True

        if not improved:
            return parsed

        if candidate.raw_text:
            if not parsed.raw_text:
                parsed.raw_text = candidate.raw_text
            elif candidate.raw_text not in parsed.raw_text:
                parsed.raw_text = f"{parsed.raw_text}\n{candidate.raw_text}"

        for key, value in candidate.metadata.items():
            if value is None:
                continue
            if key not in parsed.metadata or parsed.metadata[key] is None:
                parsed.metadata[key] = value

        return parsed
