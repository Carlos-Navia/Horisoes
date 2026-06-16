from __future__ import annotations

import re

from auditoria_pdf.domain import DocumentType
from auditoria_pdf.parsing.common import (
    is_probable_mobile_number,
    normalize_document_number,
    normalize_patient_name,
    normalize_regimen,
)
from auditoria_pdf.parsing.contracts import (
    PatientDocumentExtractorContract,
    PatientNameExtractorContract,
    RegimenExtractorContract,
)
from auditoria_pdf.parsing.cups_extractors import NoCupsExtractor
from auditoria_pdf.parsing.document_parsers import BaseDocumentParser
from auditoria_pdf.parsing.metadata_extractors import EmptyMetadataExtractor
from auditoria_pdf.parsing.patient_document_extractors import (
    HevPatientDocumentExtractor,
    PdxHybridPatientDocumentExtractor,
)
from auditoria_pdf.parsing.patient_document_type_extractors import (
    GenericPatientDocumentTypeExtractor,
)
from auditoria_pdf.parsing.patient_name_extractors import GenericPatientNameExtractor
from auditoria_pdf.parsing.pipelines import DocumentFieldExtractionPipeline


# ─────────────────────────────────────────────────────────────────────────────
# CRC
# ─────────────────────────────────────────────────────────────────────────────

class CoosaludCrcPatientDocumentExtractor(PatientDocumentExtractorContract):
    _PATTERNS = (
        r"N[uú]mero\s+de\s+identificaci[oó]n\s*(\d{6,15})",
        r"N[UÚ]MERO\s+DE\s+IDENTIFICACI[OÓ]N\s*(\d{6,15})",
        r"Numero\s+de\s+Documento\s*:\s*(\d{6,15})",
        r"^\s*(\d{6,15})\s*$",
        r"\bCC[-/\s]+(\d{6,15})\b",
    )

    def extract(self, text: str) -> str | None:
        for pattern in self._PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                candidate = normalize_document_number(match.group(1))
                if candidate and not is_probable_mobile_number(candidate):
                    return candidate
        return None


class CoosaludCrcRegimenExtractor(RegimenExtractorContract):
    def extract(self, text: str) -> str | None:
        match = re.search(r"R[eé]gimen\s*(SUBSIDIADO|CONTRIBUTIVO)", text, re.IGNORECASE)
        if match:
            return normalize_regimen(match.group(1))
        return None


class CoosaludCrcPatientNameExtractor(PatientNameExtractorContract):
    def extract(self, text: str) -> str | None:
        match = re.search(
            r"Nombres\s*([^\d\n]{2,60}?)(?=Apellidos)Apellidos\s*([^\d\n]{2,60})",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        if match:
            return normalize_patient_name(f"{match.group(1).strip()} {match.group(2).strip()}")
        
        match = re.search(r"Nombre\s*y\s*Apellidos:\s*([^\n]+)", text, re.IGNORECASE)
        if match:
            return normalize_patient_name(match.group(1).strip())
            
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PDE
# ─────────────────────────────────────────────────────────────────────────────

class CoosaludPdePatientDocumentExtractor(PatientDocumentExtractorContract):
    _PATTERNS = (
        r"Tipo\s*y\s*No.\s*de\s*documento:\s*(?:CC|TI|CE|RC|PA)?\s*(\d{6,15})",
        # ADRES BDUA: NÚMERO DE IDENTIFICACION (generalmente en dos lineas seguido del valor)
        r"N[uú]mero\s+de\s+identificaci[oó]?n\s+(\d{6,15})",
    )

    def extract(self, text: str) -> str | None:
        for pattern in self._PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                candidate = normalize_document_number(match.group(1))
                if candidate and not is_probable_mobile_number(candidate):
                    return candidate
        return None


class CoosaludPdePatientNameExtractor(PatientNameExtractorContract):
    _PATTERNS = (
        r"Nombres\s*y\s*apellidos:\s*\n?\s*([^\n]{5,100})",
        r"Nombres:\s*([^\n]{5,100})",
    )

    def extract(self, text: str) -> str | None:
        # ADRES BDUA Format
        adres_match = re.search(
            r"Nombres\s+([^\d\n]{2,60}?)\s+Apellidos\s+([^\d\n]{2,60})",
            text,
            re.IGNORECASE,
        )
        if adres_match:
            return normalize_patient_name(f"{adres_match.group(1).strip()} {adres_match.group(2).strip()}")

        for pattern in self._PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return normalize_patient_name(match.group(1).strip())
        return None


class CoosaludPdeRegimenExtractor(RegimenExtractorContract):
    _PATTERNS = (
        r"R[eé]gimen\s*de\s*Afiliaci[oó]n:\s*\n?\s*(Subsidiado|Contributivo)",
        r"R[eé]gimen:\s*(Subsidiado|Contributivo)",
        # ADRES BDUA table format where columns might stick together
        r"(SUBSIDIADO|CONTRIBUTIVO)\s*\d{2}/\d{2}/\d{4}",
        # Fallback for ADRES
        r"\b(SUBSIDIADO|CONTRIBUTIVO)\b",
    )

    def extract(self, text: str) -> str | None:
        for pattern in self._PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return normalize_regimen(match.group(1))
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PDX
# ─────────────────────────────────────────────────────────────────────────────

class CoosaludPdxPatientDocumentExtractor(PatientDocumentExtractorContract):
    _PATTERNS = (
        r"Identificado\s+con\s+Documento\s*(?:CC|TI|CE|RC|PA)?\s*(\d{6,15})",
        r"Documento:\s*(\d{6,15})",
        r"DOCUMENTO\s+DE\s+IDENTIFICACION:\s*(?:CC|TI|CE|RC|PA)?\s*(\d{6,15})",
    )

    def extract(self, text: str) -> str | None:
        for pattern in self._PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                candidate = normalize_document_number(match.group(1))
                if candidate and not is_probable_mobile_number(candidate):
                    return candidate
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Parsers Completos
# ─────────────────────────────────────────────────────────────────────────────

class CoosaludCrcDocumentParser(BaseDocumentParser):
    doc_type = DocumentType.SOPORTE

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=CoosaludCrcPatientDocumentExtractor(),
                patient_document_type_extractor=GenericPatientDocumentTypeExtractor(),
                patient_name_extractor=CoosaludCrcPatientNameExtractor(),
                regimen_extractor=CoosaludCrcRegimenExtractor(),
                cups_extractor=NoCupsExtractor(),
                metadata_extractor=EmptyMetadataExtractor(),
            )
        )


class CoosaludPdeDocumentParser(BaseDocumentParser):
    doc_type = DocumentType.AUTORIZACION

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=CoosaludPdePatientDocumentExtractor(),
                patient_document_type_extractor=GenericPatientDocumentTypeExtractor(),
                patient_name_extractor=CoosaludPdePatientNameExtractor(),
                regimen_extractor=CoosaludPdeRegimenExtractor(),
                cups_extractor=NoCupsExtractor(),
                metadata_extractor=EmptyMetadataExtractor(),
            )
        )


class CoosaludPdxDocumentParser(BaseDocumentParser):
    doc_type = DocumentType.ADICIONAL

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=PdxHybridPatientDocumentExtractor(
                    strict_extractor=CoosaludPdxPatientDocumentExtractor()
                ),
                patient_document_type_extractor=GenericPatientDocumentTypeExtractor(),
                patient_name_extractor=GenericPatientNameExtractor(),
                regimen_extractor=CoosaludCrcRegimenExtractor(),
                cups_extractor=NoCupsExtractor(),
                metadata_extractor=EmptyMetadataExtractor(),
            )
        )


class CoosaludHevDocumentParser(BaseDocumentParser):
    doc_type = DocumentType.VALIDADOR

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=HevPatientDocumentExtractor(),
                patient_document_type_extractor=GenericPatientDocumentTypeExtractor(),
                patient_name_extractor=GenericPatientNameExtractor(),
                regimen_extractor=CoosaludCrcRegimenExtractor(),
                cups_extractor=NoCupsExtractor(),
                metadata_extractor=EmptyMetadataExtractor(),
            )
        )
