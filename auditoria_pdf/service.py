from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from auditoria_pdf.audit import (
    PREFIX_TO_TYPE,
    REQUIRED_TYPES,
    AuditContextFactory,
    AuditRuleEngine,
    DocumentRetryPolicy,
    DocumentTypeResolver,
    HevPatientDocumentResolver,
    PageLimitResolver,
    PdfPathValidator,
    RenderFallbackPolicy,
    SinglePdfProcessingEngine,
    UniquePdfPathCollector,
)
from auditoria_pdf.domain import AuditReport, DocumentType
from auditoria_pdf.eps_profiles import CoosaludAuditProfile, EpsAuditProfile
from auditoria_pdf.extractor import PdfTextExtractor
from auditoria_pdf.parsing import (
    BaseDocumentParser,
    PrefixAwareDocumentParserResolver,
    build_default_parser_resolver,
)
from auditoria_pdf.rules import AuditRule


def detect_document_type(pdf_path: Path) -> tuple[DocumentType, str]:
    detected = DocumentTypeResolver(prefix_to_type=PREFIX_TO_TYPE).detect(pdf_path)
    return detected.doc_type, detected.prefix


class PdfAuditService:
    def __init__(
        self,
        extractor: PdfTextExtractor | None = None,
        parser_registry: dict[DocumentType, BaseDocumentParser] | None = None,
        parser_resolver: PrefixAwareDocumentParserResolver | None = None,
        rules: list[AuditRule] | None = None,
        profile: EpsAuditProfile | None = None,
        min_pdfs: int = 2,
        max_pdfs: int = 6,
        document_type_resolver: DocumentTypeResolver | None = None,
        path_collector: UniquePdfPathCollector | None = None,
        path_validator: PdfPathValidator | None = None,
        processing_engine: SinglePdfProcessingEngine | None = None,
        hev_patient_document_resolver: HevPatientDocumentResolver | None = None,
        context_factory: AuditContextFactory | None = None,
        rule_engine: AuditRuleEngine | None = None,
    ) -> None:
        self.extractor = extractor or PdfTextExtractor()
        self.profile = profile or CoosaludAuditProfile()

        self.min_pdfs = min_pdfs
        self.max_pdfs = max_pdfs

        self.page_limits: dict[DocumentType, int | None] = dict(self.profile.page_limits())
        self.render_fallback_types = set(self.profile.render_fallback_types())

        self.path_collector = path_collector or UniquePdfPathCollector()
        self.path_validator = path_validator or PdfPathValidator()
        self.document_type_resolver = document_type_resolver or DocumentTypeResolver(
            prefix_to_type=PREFIX_TO_TYPE
        )

        default_parser_resolver = parser_resolver or build_default_parser_resolver()
        effective_parser_registry = dict(self.profile.parser_overrides())
        if parser_registry is not None:
            effective_parser_registry.update(parser_registry)

        if effective_parser_registry:
            prefix_parsers = dict(default_parser_resolver.prefix_parsers)
            type_parsers = dict(default_parser_resolver.type_parsers)
            type_parsers.update(effective_parser_registry)
            for prefix, document_type in PREFIX_TO_TYPE.items():
                parser_from_registry = type_parsers.get(document_type)
                if parser_from_registry is not None:
                    prefix_parsers[prefix] = parser_from_registry
            default_parser_resolver = PrefixAwareDocumentParserResolver(
                prefix_parsers=prefix_parsers,
                type_parsers=type_parsers,
            )
        self.parser_registry = default_parser_resolver.type_parsers
        self.parser_resolver = default_parser_resolver

        self.processing_engine = processing_engine or SinglePdfProcessingEngine(
            extractor=self.extractor,
            page_limit_resolver=PageLimitResolver(self.page_limits),
            render_fallback_policy=RenderFallbackPolicy(self.render_fallback_types),
            retry_policy=DocumentRetryPolicy(),
        )
        self.hev_patient_document_resolver = (
            hev_patient_document_resolver or HevPatientDocumentResolver()
        )

        self.context_factory = context_factory or AuditContextFactory(
            min_pdfs=self.min_pdfs,
            max_pdfs=self.max_pdfs,
        )

        default_rules = rules or self.profile.build_rules()
        self.rules = default_rules
        self.rule_engine = rule_engine or AuditRuleEngine(default_rules)

    def audit(self, pdf_paths: Iterable[Path]) -> AuditReport:
        unique_paths = self.path_collector.collect(pdf_paths)
        mandatory_documents = {}
        additional_documents = []
        errors: list[str] = []

        for source_path in unique_paths:
            path_error = self.path_validator.validate(source_path)
            if path_error:
                errors.append(path_error)
                continue

            detected = self.document_type_resolver.detect(source_path)
            parser = self.parser_resolver.resolve(detected.doc_type, detected.prefix)
            if not parser:
                errors.append(
                    "No hay parser configurado para tipo "
                    f"{detected.doc_type.value} ({source_path.name})."
                )
                continue

            try:
                parsed = self.processing_engine.process(
                    source_path=source_path,
                    document_type=detected.doc_type,
                    prefix=detected.prefix,
                    parser=parser,
                )
            except Exception as exc:  # pragma: no cover
                errors.append(f"Error procesando {source_path.name}: {exc}")
                continue

            if detected.doc_type in REQUIRED_TYPES:
                if detected.doc_type in mandatory_documents:
                    errors.append(
                        "Documento obligatorio duplicado "
                        f"({detected.doc_type.value}): {source_path.name}"
                    )
                    continue
                mandatory_documents[detected.doc_type] = parsed
            else:
                additional_documents.append(parsed)

        self.hev_patient_document_resolver.reconcile(
            mandatory_documents=mandatory_documents,
            additional_documents=additional_documents,
        )

        context = self.context_factory.build(
            mandatory_documents=mandatory_documents,
            additional_documents=additional_documents,
            total_input_pdfs=len(unique_paths),
        )
        rule_results = self.rule_engine.evaluate(context)

        return AuditReport(
            generated_at=datetime.now(),
            context=context,
            rule_results=rule_results,
            errors=errors,
        )
