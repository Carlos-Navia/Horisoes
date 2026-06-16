from __future__ import annotations

from abc import ABC
from pathlib import Path

from auditoria_pdf.domain import DocumentType, ParsedDocument
from auditoria_pdf.parsing.common import (
    normalize_document_number,
    normalize_patient_name,
    normalize_regimen,
)
from auditoria_pdf.parsing.cups_extractors import (
    AdditionalCupsExtractor,
    CrcCupsExtractor,
    FevCupsExtractor,
    HaoCupsExtractor,
    HevCupsExtractor,
    PdeCupsExtractor,
    PdxCupsExtractor,
)
from auditoria_pdf.parsing.fev_invoice_field_extractor import FevInvoiceFieldExtractor
from auditoria_pdf.parsing.highlight_text_extractors import PdfHighlightTextExtractor
from auditoria_pdf.parsing.metadata_extractors import (
    AdditionalMetadataExtractor,
    CrcMetadataExtractor,
    FevMetadataExtractor,
    HaoMetadataExtractor,
    HevMetadataExtractor,
    PdeMetadataExtractor,
    PdxMetadataExtractor,
)
from auditoria_pdf.parsing.patient_document_extractors import (
    AdditionalPatientDocumentExtractor,
    CrcPatientDocumentExtractor,
    FevPatientDocumentExtractor,
    HaoPatientDocumentExtractor,
    HevPatientDocumentExtractor,
    PatternScoredPatientDocumentExtractor,
    PdePatientDocumentExtractor,
    SanitasPdePatientDocumentExtractor,
    PdxHybridPatientDocumentExtractor,
    PdxHighlightedPatientDocumentExtractor,
)
from auditoria_pdf.parsing.patient_document_type_extractors import (
    AdditionalPatientDocumentTypeExtractor,
    CrcPatientDocumentTypeExtractor,
    FevPatientDocumentTypeExtractor,
    HaoPatientDocumentTypeExtractor,
    HevPatientDocumentTypeExtractor,
    PdePatientDocumentTypeExtractor,
    PdxPatientDocumentTypeExtractor,
)
from auditoria_pdf.parsing.patient_name_extractors import (
    AdditionalPatientNameExtractor,
    CrcPatientNameExtractor,
    FevPatientNameExtractor,
    HaoPatientNameExtractor,
    HevPatientNameExtractor,
    PdePatientNameExtractor,
    PdxPatientNameExtractor,
)
from auditoria_pdf.parsing.pipelines import DocumentFieldExtractionPipeline
from auditoria_pdf.parsing.regimen_extractors import (
    AdditionalRegimenExtractor,
    CrcRegimenExtractor,
    FevRegimenExtractor,
    HaoRegimenExtractor,
    HevRegimenExtractor,
    NuevaEpsPdeRegimenExtractor,
    PdeRegimenExtractor,
    PdxRegimenExtractor,
    SanitasPdeRegimenExtractor,
)


class BaseDocumentParser(ABC):
    doc_type: DocumentType

    def __init__(self, extraction_pipeline: DocumentFieldExtractionPipeline) -> None:
        self._extraction_pipeline = extraction_pipeline

    def parse(self, source_path: Path, raw_text: str, prefix: str) -> ParsedDocument:
        normalized_text = raw_text.replace("\x00", "")
        fields = self._extraction_pipeline.extract_fields(normalized_text)
        return ParsedDocument(
            doc_type=self.doc_type,
            source_path=source_path,
            raw_text=normalized_text,
            prefix=prefix.upper(),
            patient_document=normalize_document_number(fields.get("patient_document")),
            patient_name=normalize_patient_name(fields.get("patient_name")),
            patient_document_type=fields.get("patient_document_type"),
            cups_codes=fields.get("cups_codes", set()),
            regimen=normalize_regimen(fields.get("regimen")),
            metadata=fields.get("metadata", {}),
        )

    def allows_raw_text_retry(self) -> bool:
        return True


class HighlightOnlyDocumentParser(BaseDocumentParser):
    def __init__(
        self,
        extraction_pipeline: DocumentFieldExtractionPipeline,
        highlight_text_extractor: PdfHighlightTextExtractor,
        fallback_to_raw_text_without_supported_annotations: bool = True,
    ) -> None:
        super().__init__(extraction_pipeline=extraction_pipeline)
        self._highlight_text_extractor = highlight_text_extractor
        self._fallback_to_raw_text_without_supported_annotations = (
            fallback_to_raw_text_without_supported_annotations
        )

    def parse(self, source_path: Path, raw_text: str, prefix: str) -> ParsedDocument:
        highlighted_text = self._highlight_text_extractor.extract(source_path)
        if highlighted_text:
            source_text = highlighted_text
        elif (
            self._fallback_to_raw_text_without_supported_annotations
            and not self._highlight_text_extractor.has_supported_annotations(source_path)
        ):
            source_text = raw_text
        else:
            source_text = ""

        normalized_text = source_text.replace("\x00", "")
        fields = self._extraction_pipeline.extract_fields(normalized_text)
        return ParsedDocument(
            doc_type=self.doc_type,
            source_path=source_path,
            raw_text=normalized_text,
            prefix=prefix.upper(),
            patient_document=normalize_document_number(fields.get("patient_document")),
            patient_name=normalize_patient_name(fields.get("patient_name")),
            patient_document_type=fields.get("patient_document_type"),
            cups_codes=fields.get("cups_codes", set()),
            regimen=normalize_regimen(fields.get("regimen")),
            metadata=fields.get("metadata", {}),
        )

    def allows_raw_text_retry(self) -> bool:
        return False


class FevDocumentParser(BaseDocumentParser):
    doc_type = DocumentType.FACTURA

    def __init__(self) -> None:
        fev_field_extractor = FevInvoiceFieldExtractor(
            fallback_patient_document_extractor=PatternScoredPatientDocumentExtractor()
        )
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=FevPatientDocumentExtractor(
                    fev_field_extractor=fev_field_extractor
                ),
                patient_document_type_extractor=FevPatientDocumentTypeExtractor(),
                patient_name_extractor=FevPatientNameExtractor(),
                regimen_extractor=FevRegimenExtractor(fev_field_extractor=fev_field_extractor),
                cups_extractor=FevCupsExtractor(),
                metadata_extractor=FevMetadataExtractor(),
            )
        )


class PdeDocumentParser(BaseDocumentParser):
    doc_type = DocumentType.AUTORIZACION

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=PdePatientDocumentExtractor(),
                patient_document_type_extractor=PdePatientDocumentTypeExtractor(),
                patient_name_extractor=PdePatientNameExtractor(),
                regimen_extractor=PdeRegimenExtractor(),
                cups_extractor=PdeCupsExtractor(),
                metadata_extractor=PdeMetadataExtractor(),
            ),
        )


class NuevaEpsPdeDocumentParser(BaseDocumentParser):
    doc_type = DocumentType.AUTORIZACION

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=PdePatientDocumentExtractor(),
                patient_document_type_extractor=PdePatientDocumentTypeExtractor(),
                patient_name_extractor=PdePatientNameExtractor(),
                regimen_extractor=NuevaEpsPdeRegimenExtractor(),
                cups_extractor=PdeCupsExtractor(),
                metadata_extractor=PdeMetadataExtractor(),
            ),
        )


class SanitasPdeDocumentParser(BaseDocumentParser):
    doc_type = DocumentType.AUTORIZACION

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=SanitasPdePatientDocumentExtractor(),
                patient_document_type_extractor=PdePatientDocumentTypeExtractor(),
                patient_name_extractor=PdePatientNameExtractor(),
                regimen_extractor=SanitasPdeRegimenExtractor(),
                cups_extractor=PdeCupsExtractor(),
                metadata_extractor=PdeMetadataExtractor(),
            ),
        )


class CrcDocumentParser(BaseDocumentParser):
    doc_type = DocumentType.SOPORTE

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=CrcPatientDocumentExtractor(),
                patient_document_type_extractor=CrcPatientDocumentTypeExtractor(),
                patient_name_extractor=CrcPatientNameExtractor(),
                regimen_extractor=CrcRegimenExtractor(),
                cups_extractor=CrcCupsExtractor(),
                metadata_extractor=CrcMetadataExtractor(),
            )
        )


class HevDocumentParser(BaseDocumentParser):
    doc_type = DocumentType.VALIDADOR

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=HevPatientDocumentExtractor(),
                patient_document_type_extractor=HevPatientDocumentTypeExtractor(),
                patient_name_extractor=HevPatientNameExtractor(),
                regimen_extractor=HevRegimenExtractor(),
                cups_extractor=HevCupsExtractor(),
                metadata_extractor=HevMetadataExtractor(),
            ),
        )


class PdxDocumentParser(BaseDocumentParser):
    doc_type = DocumentType.ADICIONAL

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=PdxHybridPatientDocumentExtractor(
                    table_extractor=PdxHighlightedPatientDocumentExtractor()
                ),
                patient_document_type_extractor=PdxPatientDocumentTypeExtractor(),
                patient_name_extractor=PdxPatientNameExtractor(),
                regimen_extractor=PdxRegimenExtractor(),
                cups_extractor=PdxCupsExtractor(),
                metadata_extractor=PdxMetadataExtractor(),
            ),
        )


class HaoDocumentParser(BaseDocumentParser):
    doc_type = DocumentType.ADICIONAL

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=HaoPatientDocumentExtractor(),
                patient_document_type_extractor=HaoPatientDocumentTypeExtractor(),
                patient_name_extractor=HaoPatientNameExtractor(),
                regimen_extractor=HaoRegimenExtractor(),
                cups_extractor=HaoCupsExtractor(),
                metadata_extractor=HaoMetadataExtractor(),
            )
        )


class AdditionalDocumentParser(BaseDocumentParser):
    doc_type = DocumentType.ADICIONAL

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=AdditionalPatientDocumentExtractor(),
                patient_document_type_extractor=AdditionalPatientDocumentTypeExtractor(),
                patient_name_extractor=AdditionalPatientNameExtractor(),
                regimen_extractor=AdditionalRegimenExtractor(),
                cups_extractor=AdditionalCupsExtractor(),
                metadata_extractor=AdditionalMetadataExtractor(),
            )
        )
