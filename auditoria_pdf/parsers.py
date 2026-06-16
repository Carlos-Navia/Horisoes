from __future__ import annotations

from auditoria_pdf.parsing.common import normalize_document_type, normalize_regimen
from auditoria_pdf.parsing.cups_extractors import ContextAwareCupsExtractor
from auditoria_pdf.parsing.document_parsers import (
    AdditionalDocumentParser,
    BaseDocumentParser,
    CrcDocumentParser,
    FevDocumentParser,
    HaoDocumentParser,
    HevDocumentParser,
    PdeDocumentParser,
    PdxDocumentParser,
)
from auditoria_pdf.parsing.patient_document_extractors import (
    CrcPatientDocumentExtractor,
    PatternScoredPatientDocumentExtractor,
)
from auditoria_pdf.parsing.patient_document_type_extractors import (
    GenericPatientDocumentTypeExtractor,
)
from auditoria_pdf.parsing.patient_name_extractors import GenericPatientNameExtractor
from auditoria_pdf.parsing.resolver import (
    PrefixAwareDocumentParserResolver,
    build_default_parser_registry,
    build_default_parser_resolver,
)

_GENERIC_DOCUMENT_EXTRACTOR = PatternScoredPatientDocumentExtractor()
_CRC_DOCUMENT_EXTRACTOR = CrcPatientDocumentExtractor(
    generic_extractor=_GENERIC_DOCUMENT_EXTRACTOR
)
_GENERIC_DOCUMENT_TYPE_EXTRACTOR = GenericPatientDocumentTypeExtractor()
_GENERIC_PATIENT_NAME_EXTRACTOR = GenericPatientNameExtractor()
_CUPS_EXTRACTOR = ContextAwareCupsExtractor()


class FevParser(FevDocumentParser):
    pass


class PdeParser(PdeDocumentParser):
    pass


class CrcParser(CrcDocumentParser):
    pass


class HevParser(HevDocumentParser):
    pass


def _extract_patient_document_generic(text: str) -> str | None:
    return _GENERIC_DOCUMENT_EXTRACTOR.extract(text)


def _extract_patient_document_crc(text: str) -> str | None:
    return _CRC_DOCUMENT_EXTRACTOR.extract(text)


def _extract_patient_document_type_generic(text: str) -> str | None:
    return _GENERIC_DOCUMENT_TYPE_EXTRACTOR.extract(text)


def _extract_patient_name_generic(text: str) -> str | None:
    return _GENERIC_PATIENT_NAME_EXTRACTOR.extract(text)


def _extract_cups_codes(text: str) -> set[str]:
    return _CUPS_EXTRACTOR.extract(text)


def _normalize_document_type(value: str | None) -> str | None:
    return normalize_document_type(value)


def _normalize_regimen(value: str | None) -> str | None:
    return normalize_regimen(value)


__all__ = [
    "AdditionalDocumentParser",
    "BaseDocumentParser",
    "CrcParser",
    "FevParser",
    "HaoDocumentParser",
    "HevParser",
    "PdeParser",
    "PdxDocumentParser",
    "PrefixAwareDocumentParserResolver",
    "build_default_parser_registry",
    "build_default_parser_resolver",
    "_extract_cups_codes",
    "_extract_patient_document_crc",
    "_extract_patient_document_generic",
    "_extract_patient_document_type_generic",
    "_extract_patient_name_generic",
]
