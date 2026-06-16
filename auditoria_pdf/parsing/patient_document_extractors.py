from __future__ import annotations

from dataclasses import dataclass
import re

from auditoria_pdf.parsing.common import (
    is_probable_mobile_number,
    normalize_document_number,
    normalize_ocr_digit_noise,
    normalize_search_text,
    normalize_whitespace,
)
from auditoria_pdf.parsing.contracts import PatientDocumentExtractorContract
from auditoria_pdf.parsing.fev_invoice_field_extractor import FevInvoiceFieldExtractor


@dataclass(slots=True)
class DocumentCandidate:
    document: str
    score: int
    start: int


class PatternScoredPatientDocumentExtractor(PatientDocumentExtractorContract):
    _CONTEXT_WINDOW = 160

    _PATTERN_WEIGHTS: tuple[tuple[str, int], ...] = (
        (
            r"TIPO\s+DOCUMENTO[^\n]{0,80}?NUMERO\s+DOCUMENTO\s*[:=\-]?\s*(\d[\d\.\-\s]{5,24})",
            140,
        ),
        (
            r"DOCUMENTO\s+IDENTIDAD[^\d\n]{0,25}(\d{6,15})",
            139,
        ),
        (
            r"TIPO\s+DE\s+IDENTIFIC[^\n]{0,120}?NUMERO\s+DE\s+IDENTIFIC[^\d\n:]{0,20}\s*[:=\-]?\s*(\d[\d\.\-\s]{5,24})",
            139,
        ),
        (
            r"(?:NUMERO|N[UUM]MERO)\s+DE\s+DOCUMENTO\s*[:=\-]?\s*(?:\r?\n\s*[^\d\n]{0,80}){0,2}\r?\n\s*(\d[\d\.\-\s]{5,24})",
            138,
        ),
        (
            r"(?:NUMERO|N[UUM]MERO)\s+DE\s+DOCUMENTO\s*[:=\-]?\s*(\d[\d\.\-\s]{5,24})",
            136,
        ),
        (
            r"(?:NUMERO|N[UUM]MERO)\s+DE\s+IDENTIFIC[^\d\n:]{0,25}\s*[:=\-]?\s*(\d[\d\.\-\s]{5,24})",
            134,
        ),
        (
            r"(?:NUMERO|N[UUM]MERO)\s+(?:DE\s+)?ID\s*[:=\-]?\s*(\d[\d\.\-\s]{5,24})",
            134,
        ),
        (
            r"DOCUMENTO\s+IDENTIDAD\s*[:=\-]?\s*(?:\r?\n\s*)?(\d[\d\.\-\s]{5,24})",
            130,
        ),
        (
            r"(?:NUMERO|N[UUM]MERO)\s+DOCUMENTO\s*[:=\-]?\s*(\d[\d\.\-\s]{5,24})",
            126,
        ),
        (
            r"IDENTIFIC[^\d\n:]{0,25}\s*[:=\-]?\s*(?:CC|TI|CE|RC|PA|PASAPORTE|CEDULA)?[\s\-\.:]*(\d[\d\.\-\s]{5,24})",
            122,
        ),
        (
            r"AFILIADO\s*[:=\-]?\s*(?:CC|TI|CE|RC|PA)?[\s\-\.:]*(\d{6,15})",
            118,
        ),
        (
            r"PACIENTE[^\n]{0,120}\b(?:CC|TI|CE|RC|PA)\s+(\d{6,15})",
            114,
        ),
        (
            r"\b(\d{6,15})\s+(?:CEDULA|TARJETA\s+DE\s+IDENTIDAD|REGISTRO\s+CIVIL|PASAPORTE)\b",
            98,
        ),
        (
            r"\b(?:CC|TI|CE|RC|PA)[\s\-\.:]+(\d{6,15})\b",
            92,
        ),
        (
            r"DocumentNumber=(\d{6,15})",
            90,
        ),
        (
            r"identific\w*[^\d\n]*((?:\d[^\d\n]*){6,15})",
            70,
        ),
    )

    _POSITIVE_TOKENS: tuple[str, ...] = (
        "DATOS DEL PACIENTE",
        "NOMBRE PACIENTE",
        "IDENTIFIC",
        "NUMERO DOCUMENTO",
        "NUMERO DE IDENTIFIC",
        "TIPO DOCUMENTO",
        "AFILIADO",
        "PACIENTE",
        "USUARIO",
    )

    _NEGATIVE_TOKENS: tuple[str, ...] = (
        "NIT",
        "REGISTRO MEDICO",
        "TELEFONO",
        "CELULAR",
        "CORREO",
        "PROMOTOR",
        "EDUCADOR",
        "AUTORIZACION",
        "FACTURA",
        "CUFE",
        "RESOLUCION",
        "CONTRATO",
        "CUENTA MEDICA",
    )

    def extract(self, text: str) -> str | None:
        if not text:
            return None

        candidates: list[DocumentCandidate] = []
        for pattern, base_score in self._PATTERN_WEIGHTS:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                raw_candidate = normalize_whitespace(match.group(1))
                normalized_document = normalize_document_number(raw_candidate)
                if not normalized_document:
                    continue

                score = self._score_candidate(
                    text=text,
                    document=normalized_document,
                    start=match.start(),
                    base_score=base_score,
                )
                candidates.append(
                    DocumentCandidate(
                        document=normalized_document,
                        score=score,
                        start=match.start(),
                    )
                )

        if not candidates:
            return self._extract_from_anchor_lines(text)

        best = max(candidates, key=lambda item: (item.score, -item.start, len(item.document)))
        return best.document

    def _score_candidate(
        self,
        text: str,
        document: str,
        start: int,
        base_score: int,
    ) -> int:
        context_start = max(0, start - self._CONTEXT_WINDOW)
        context_end = min(len(text), start + self._CONTEXT_WINDOW)
        context = normalize_search_text(text[context_start:context_end])

        score = base_score
        for token in self._POSITIVE_TOKENS:
            if token in context:
                score += 7

        for token in self._NEGATIVE_TOKENS:
            if token in context:
                score -= 10

        if "DATOS DEL PACIENTE" in context and "IDENTIFIC" in context:
            score += 24
        if "NUMERO DOCUMENTO" in context:
            score += 20
        if "NUMERO DE IDENTIFIC" in context:
            score += 20
        if "NIT" in context and document.startswith("9"):
            score -= 28
        if len(document) in {8, 9, 10, 11}:
            score += 8
        if document.startswith("000"):
            score -= 22
        if len(set(document)) <= 2:
            score -= 12

        typed_pattern = rf"\b(?:CC|TI|CE|RC|PA)\W{{0,3}}{re.escape(document)}\b"
        if re.search(typed_pattern, context):
            score += 16

        frequency = len(re.findall(rf"\b{re.escape(document)}\b", text))
        score += min(frequency, 4) * 5

        return score

    def _extract_from_anchor_lines(self, text: str) -> str | None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return None

        candidates: list[DocumentCandidate] = []
        for idx, line in enumerate(lines):
            normalized_line = normalize_search_text(line)
            if not any(
                token in normalized_line
                for token in ("IDENTIFIC", "DOCUMENTO", "AFILIADO", "PACIENTE")
            ):
                continue

            window = " ".join(lines[idx : idx + 3])
            for match in re.finditer(r"\d[\d\.\-\s]{5,24}", window):
                normalized_document = normalize_document_number(match.group(0))
                if not normalized_document:
                    continue

                score = 60
                if "IDENTIFIC" in normalized_line:
                    score += 20
                if "PACIENTE" in normalized_line:
                    score += 10
                candidates.append(
                    DocumentCandidate(
                        document=normalized_document,
                        score=score,
                        start=idx,
                    )
                )

        if not candidates:
            return None
        best = max(candidates, key=lambda item: (item.score, -item.start, len(item.document)))
        return best.document


class DelegatingPatientDocumentExtractor(PatientDocumentExtractorContract):
    def __init__(self, delegate: PatientDocumentExtractorContract | None = None) -> None:
        self._delegate = delegate or PatternScoredPatientDocumentExtractor()

    def extract(self, text: str) -> str | None:
        return self._delegate.extract(text)


class BasePatternPatientDocumentExtractor(PatientDocumentExtractorContract):
    _PRIMARY_PATTERNS: tuple[str, ...] = ()
    _STOP_PATTERNS: tuple[str, ...] = ()
    _MAX_LINES: int | None = None

    def __init__(self, fallback_extractor: PatientDocumentExtractorContract | None = None) -> None:
        self._fallback_extractor = fallback_extractor or PatternScoredPatientDocumentExtractor()

    def extract(self, text: str) -> str | None:
        if not text:
            return None

        scoped_text = self._build_scoped_text(text)
        primary_candidate = self._extract_from_patterns(scoped_text)
        if primary_candidate:
            return primary_candidate

        scoped_fallback = self._fallback_extractor.extract(scoped_text)
        if scoped_fallback and not is_probable_mobile_number(scoped_fallback):
            return scoped_fallback

        full_fallback = self._fallback_extractor.extract(text)
        if full_fallback and not is_probable_mobile_number(full_fallback):
            return full_fallback

        return scoped_fallback or full_fallback

    def _extract_from_patterns(self, text: str) -> str | None:
        for pattern in self._PRIMARY_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                candidate_raw = self._pick_match_group(match)
                normalized = normalize_document_number(normalize_whitespace(candidate_raw))
                if normalized and not is_probable_mobile_number(normalized):
                    return normalized
        return None

    def _pick_match_group(self, match: re.Match[str]) -> str:
        if match.lastindex is None:
            return match.group(0)
        for idx in range(1, match.lastindex + 1):
            value = match.group(idx)
            if value:
                return value
        return match.group(0)

    def _build_scoped_text(self, text: str) -> str:
        lines = text.splitlines()
        if self._MAX_LINES is not None:
            lines = lines[: self._MAX_LINES]
        scoped_text = "\n".join(lines)

        if not self._STOP_PATTERNS:
            return scoped_text

        upper_scoped = scoped_text.upper()
        cut_index = len(scoped_text)
        for stop_pattern in self._STOP_PATTERNS:
            match = re.search(stop_pattern, upper_scoped)
            if match:
                cut_index = min(cut_index, match.start())

        return scoped_text[:cut_index]


class FevPatientDocumentExtractor(PatientDocumentExtractorContract):
    def __init__(
        self,
        fev_field_extractor: FevInvoiceFieldExtractor | None = None,
    ) -> None:
        self._fev_field_extractor = fev_field_extractor or FevInvoiceFieldExtractor(
            fallback_patient_document_extractor=PatternScoredPatientDocumentExtractor()
        )

    def extract(self, text: str) -> str | None:
        return self._fev_field_extractor.extract_patient_document(text)


class PdePatientDocumentExtractor(BasePatternPatientDocumentExtractor):
    _MAX_LINES = 150
    _PRIMARY_PATTERNS = (
        r"(?:NUMERO|N[UUM]MERO)\s+DE\s+IDENTIFIC(?:ACION)?\s*[:=\-]?\s*(\d[\d\.\-\s]{5,24})",
        # ADRES BDUA format
        r"N[uú]mero\s+de\s+identificaci[oó]?n\s+(\d{6,15})",
        r"AFILIADO\s*[:=\-]?\s*(?:CC|TI|CE|RC|PA)?[\s\-\.:]*(\d[\d\.\-\s]{5,24})",
        r"PACIENTE[^\n]{0,120}\b(?:CC|TI|CE|RC|PA)\W{0,4}(\d[\d\.\-\s]{5,24})",
        r"IDENTIFIC(?:ACION)?\s+DEL\s+PACIENTE\s*[:=\-]?\s*(\d[\d\.\-\s]{5,24})",
    )


class SanitasPdePatientDocumentExtractor(PatientDocumentExtractorContract):
    _FIELD_PATTERNS: tuple[str, ...] = (
        r"(?:NUMERO|N[UUM]MERO)\s+DE\s+DOCUMENTO\s+DEL\s+COTIZANTE\s+TITULAR\s*[:=\-]?\s*(\d[\d\.\-\s]{5,24})",
        r"(?:NUMERO|N[UUM]MERO)\s+DE\s+DOCUMENTO\s+DEL\s+COTIZANTE\s+TITULAR\s*[:=\-]?\s*(?:\r?\n\s*){0,2}(\d[\d\.\-\s]{5,24})",
    )
    _ANCHOR_TOKENS: tuple[str, ...] = (
        "DOCUMENTO DEL COTIZANTE TITULAR",
        "COTIZANTE TITULAR",
    )

    def __init__(
        self,
        fallback_extractor: PatientDocumentExtractorContract | None = None,
    ) -> None:
        self._fallback_extractor = fallback_extractor or PdePatientDocumentExtractor()

    def extract(self, text: str) -> str | None:
        if not text:
            return None

        direct = self._extract_direct_match(text)
        if direct:
            return direct

        lines = [normalize_whitespace(line) for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines[:220]):
            normalized_line = normalize_search_text(line)
            if not any(token in normalized_line for token in self._ANCHOR_TOKENS):
                continue

            for offset in range(0, 3):
                line_index = index + offset
                if line_index >= len(lines):
                    break
                for candidate in re.findall(r"\d[\d\.\-\s]{5,24}", lines[line_index]):
                    normalized = normalize_document_number(candidate)
                    if normalized and not is_probable_mobile_number(normalized):
                        return normalized

        fallback = self._fallback_extractor.extract(text)
        if fallback and not is_probable_mobile_number(fallback):
            return fallback
        return None

    def _extract_direct_match(self, text: str) -> str | None:
        for pattern in self._FIELD_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                normalized = normalize_document_number(normalize_whitespace(match.group(1)))
                if normalized and not is_probable_mobile_number(normalized):
                    return normalized
        return None


class PdeHighlightedPatientDocumentExtractor(PatientDocumentExtractorContract):
    _ANCHOR_TOKENS: tuple[str, ...] = ("IDENTIFIC", "DOCUMENTO", "AFILIADO", "PACIENTE")
    _NOISE_TOKENS: tuple[str, ...] = ("NIT", "TEL", "CEL", "CUFE", "AUTORIZACION")

    def __init__(
        self,
        fallback_extractor: PatientDocumentExtractorContract | None = None,
    ) -> None:
        self._fallback_extractor = fallback_extractor or PdePatientDocumentExtractor()

    def extract(self, text: str) -> str | None:
        lines = [normalize_whitespace(line) for line in text.splitlines() if line.strip()]
        if not lines:
            return None

        anchor_indexes = [
            idx
            for idx, line in enumerate(lines)
            if any(token in normalize_search_text(line) for token in self._ANCHOR_TOKENS)
        ]
        frequencies: dict[str, int] = {}
        best_by_document: dict[str, DocumentCandidate] = {}

        for line_index, line in enumerate(lines):
            for match in re.finditer(r"\d[\d\.\-\s]{5,24}", line):
                document = normalize_document_number(match.group(0))
                if not document or is_probable_mobile_number(document):
                    continue

                frequencies[document] = frequencies.get(document, 0) + 1
                score = self._score_candidate(
                    lines=lines,
                    line_index=line_index,
                    document=document,
                    anchor_indexes=anchor_indexes,
                )

                candidate = DocumentCandidate(
                    document=document,
                    score=score,
                    start=line_index,
                )
                current = best_by_document.get(document)
                if current is None or candidate.score > current.score:
                    best_by_document[document] = candidate

        if best_by_document:
            weighted: list[DocumentCandidate] = []
            for document, candidate in best_by_document.items():
                frequency_bonus = min(frequencies.get(document, 0), 3) * 6
                weighted.append(
                    DocumentCandidate(
                        document=document,
                        score=candidate.score + frequency_bonus,
                        start=candidate.start,
                    )
                )
            best = max(weighted, key=lambda item: (item.score, len(item.document), -item.start))
            return best.document

        fallback = self._fallback_extractor.extract(text)
        if fallback and not is_probable_mobile_number(fallback):
            return fallback
        return None

    def _score_candidate(
        self,
        lines: list[str],
        line_index: int,
        document: str,
        anchor_indexes: list[int],
    ) -> int:
        line = lines[line_index]
        normalized_line = normalize_search_text(line)
        document_length = len(document)

        score = 45
        if 8 <= document_length <= 11:
            score += 28
        elif document_length == 7:
            score += 16
        elif 12 <= document_length <= 15:
            score += 18
        elif document_length == 6:
            score += 4

        if re.fullmatch(r"[0-9\.\-\s]+", line):
            score += 18
        if any(token in normalized_line for token in self._ANCHOR_TOKENS):
            score += 24

        if anchor_indexes:
            distance = min(abs(line_index - anchor_idx) for anchor_idx in anchor_indexes)
            score += max(0, 30 - (distance * 8))

        if any(token in normalized_line for token in self._NOISE_TOKENS):
            score -= 16
        if "NIT" in normalized_line and document.startswith("9") and document_length >= 9:
            score -= 30
        if len(set(document)) <= 2:
            score -= 10

        return score


class _HevLegacyPatientDocumentExtractor(BasePatternPatientDocumentExtractor):
    _MAX_LINES = 120
    _STOP_PATTERNS = (
        r"\bFIRMA\b",
        r"\bBACTERIOLOG",
        r"\bPROFESIONAL\b",
    )
    _PRIMARY_PATTERNS = (
        r"DOCUMENTO\s+IDENTIDAD\s*[:=\-]?\s*(\d[\d\.\-\s]{5,24})",
        r"IDENTIFIC(?:ACION)?\s+PACIENTE\s*[:=\-]?\s*(\d[\d\.\-\s]{5,24})",
        r"(?:PACIENTE|USUARIO)[^\n]{0,120}\b(?:CC|TI|CE|RC|PA)\W{0,4}(\d[\d\.\-\s]{5,24})",
    )


class HevPatientDocumentExtractor(PatientDocumentExtractorContract):
    _MAX_LINES = 180
    _STOP_TOKENS: tuple[str, ...] = (
        "NOMBRE E IDENTIFICACION",
        "FIRMA DEL AGENTE",
        "FIRMA DEL PACIENTE",
    )
    _IDENTIFICATION_CONTEXT_TOKENS: tuple[str, ...] = (
        "IDENTIFIC",
        "NUMERO",
        "CEDULA",
        "PACIENTE",
        "USUARIO",
    )
    _NEGATIVE_CONTEXT_TOKENS: tuple[str, ...] = (
        "FIRMA",
        "EDUCADOR",
        "BACTERIOLOG",
        "PROFESIONAL",
    )
    _FIELD_PATTERNS: tuple[str, ...] = (
        r"(?:NUM\w{0,8}\s*(?:DE\s*)?IDENT\w{0,16})\s*[:=\-]?\s*([A-Z0-9OoIl|!QDSZBGT\.\-\/\s]{5,32})",
        r"(?:IDENT\w{0,16}\s*(?:DEL)?\s*PACIENTE)\s*[:=\-]?\s*([A-Z0-9OoIl|!QDSZBGT\.\-\/\s]{5,32})",
        r"CEDULA(?:\s+DE\s+CIUDADANIA)?\s*(?:NRO|NO|#)?\s*[:=\-]?\s*([A-Z0-9OoIl|!QDSZBGT\.\-\/\s]{5,32})",
    )
    _OCR_DIGIT_TRANSLATION = str.maketrans(
        {
            "O": "0",
            "Q": "0",
            "D": "0",
            "I": "1",
            "L": "1",
            "|": "1",
            "!": "1",
            "Z": "2",
            "S": "5",
            "G": "6",
            "T": "7",
            "B": "8",
        }
    )

    def __init__(
        self,
        legacy_extractor: PatientDocumentExtractorContract | None = None,
        generic_extractor: PatientDocumentExtractorContract | None = None,
    ) -> None:
        self._legacy_extractor = legacy_extractor or _HevLegacyPatientDocumentExtractor()
        self._generic_extractor = generic_extractor or PatternScoredPatientDocumentExtractor()

    def extract(self, text: str) -> str | None:
        if not text:
            return None

        scoped_lines = self._build_scoped_lines(text)
        scoped_text = "\n".join(scoped_lines)

        anchored_candidate = self._extract_from_identification_fields(scoped_lines, scoped_text)
        if anchored_candidate:
            return anchored_candidate

        legacy_candidate = self._legacy_extractor.extract(scoped_text)
        if legacy_candidate and self._is_reliable_candidate(legacy_candidate, scoped_lines):
            return legacy_candidate

        generic_candidate = self._generic_extractor.extract(scoped_text)
        if generic_candidate and self._is_reliable_candidate(generic_candidate, scoped_lines):
            return generic_candidate

        return None

    def _build_scoped_lines(self, text: str) -> list[str]:
        lines = [normalize_whitespace(line) for line in text.splitlines() if line.strip()]
        scoped: list[str] = []
        for line in lines[: self._MAX_LINES]:
            normalized_line = normalize_search_text(line)
            if any(token in normalized_line for token in self._STOP_TOKENS):
                break
            scoped.append(line)
        return scoped

    def _extract_from_identification_fields(
        self,
        lines: list[str],
        scoped_text: str,
    ) -> str | None:
        candidates: dict[str, DocumentCandidate] = {}

        for pattern in self._FIELD_PATTERNS:
            for match in re.finditer(pattern, scoped_text, re.IGNORECASE | re.MULTILINE):
                context_text = normalize_search_text(match.group(0))
                for normalized in self._extract_digit_candidates(match.group(1)):
                    score = self._score_candidate(
                        document=normalized,
                        line_index=self._line_index_from_offset(lines, match.start()),
                        context_text=context_text,
                    )
                    self._upsert_candidate(candidates, normalized, score, match.start())

        for line_index, line in enumerate(lines):
            normalized_line = normalize_search_text(line)
            if "IDENT" not in normalized_line and "CEDULA" not in normalized_line:
                continue

            window = line
            if line_index + 1 < len(lines):
                window = f"{line} {lines[line_index + 1]}"
            context_text = normalize_search_text(window)

            for raw_candidate in re.findall(r"[A-Z0-9OoIl|!QDSZBGT\.\-\/\s]{6,28}", window):
                for normalized in self._extract_digit_candidates(raw_candidate):
                    score = self._score_candidate(
                        document=normalized,
                        line_index=line_index,
                        context_text=context_text,
                    )
                    self._upsert_candidate(candidates, normalized, score, line_index)

        if not candidates:
            return None

        best = max(candidates.values(), key=lambda item: (item.score, len(item.document), -item.start))
        return best.document

    def _extract_digit_candidates(self, raw_value: str) -> list[str]:
        if not raw_value:
            return []

        normalized_raw = normalize_whitespace(raw_value).upper().translate(self._OCR_DIGIT_TRANSLATION)
        normalized_raw = normalize_ocr_digit_noise(normalized_raw)
        normalized_raw = re.sub(r"[^0-9]", " ", normalized_raw)
        sequences = re.findall(r"\d{6,15}", normalized_raw)

        candidates: list[str] = []
        for sequence in sequences:
            if is_probable_mobile_number(sequence):
                continue
            if len(sequence) in {7, 8, 9, 10, 11}:
                candidates.append(sequence)
            if len(sequence) == 9 and sequence.startswith("1"):
                candidates.append(sequence[1:])

        # Preserve order but remove duplicates.
        return list(dict.fromkeys(candidates))

    def _score_candidate(self, document: str, line_index: int, context_text: str) -> int:
        score = 70
        length = len(document)
        if 8 <= length <= 10:
            score += 30
        elif length == 7:
            score += 18
        elif length == 11:
            score += 12

        score += max(0, 22 - line_index)

        if any(token in context_text for token in self._IDENTIFICATION_CONTEXT_TOKENS):
            score += 24
        if any(token in context_text for token in self._NEGATIVE_CONTEXT_TOKENS):
            score -= 40
        if document.startswith("3") and len(document) == 10:
            score -= 26
        if len(set(document)) <= 2:
            score -= 12

        return score

    def _is_reliable_candidate(self, candidate: str, lines: list[str]) -> bool:
        if not candidate:
            return False
        if is_probable_mobile_number(candidate):
            return False
        if len(candidate) < 7:
            return False
        if len(set(candidate)) <= 2:
            return False

        return self._has_identification_context(candidate, lines)

    def _has_identification_context(self, candidate: str, lines: list[str]) -> bool:
        for line_index, line in enumerate(lines):
            compact_digits = re.sub(r"\D", "", line)
            if candidate not in compact_digits:
                continue

            line_context = normalize_search_text(line)
            if (
                any(token in line_context for token in self._IDENTIFICATION_CONTEXT_TOKENS)
                and not any(token in line_context for token in self._NEGATIVE_CONTEXT_TOKENS)
            ):
                return True

            window_start = max(0, line_index - 1)
            window_end = min(len(lines), line_index + 2)
            context_text = normalize_search_text(" ".join(lines[window_start:window_end]))

            if any(token in context_text for token in self._NEGATIVE_CONTEXT_TOKENS):
                continue
            if any(token in context_text for token in self._IDENTIFICATION_CONTEXT_TOKENS):
                return True

        return False

    def _upsert_candidate(
        self,
        candidates: dict[str, DocumentCandidate],
        document: str,
        score: int,
        start: int,
    ) -> None:
        candidate = DocumentCandidate(document=document, score=score, start=start)
        current = candidates.get(document)
        if current is None or candidate.score > current.score:
            candidates[document] = candidate

    def _line_index_from_offset(self, lines: list[str], offset: int) -> int:
        running = 0
        for index, line in enumerate(lines):
            next_running = running + len(line) + 1
            if offset < next_running:
                return index
            running = next_running
        return max(0, len(lines) - 1)


class PdxHighlightedPatientDocumentExtractor(PatientDocumentExtractorContract):
    _DOC_TYPE_PATTERN = r"\b(?:CC|TI|CE|RC|PA)\b"
    _IDENTIFICATION_TOKENS: tuple[str, ...] = ("IDEN", "DOCUMENTO")
    _NEGATIVE_CONTEXT_TOKENS: tuple[str, ...] = (
        "BACTERIOLOG",
        "MEDICO",
        "FIRMA",
        "NOTA",
        "TECNICA",
        "CITOLOG",
        "CONTACT CENTER",
        "NIT",
        "REFERENCIA",
        "EXAMEN",
        "RESULTADO",
        "UNIDADES",
        "ORDENAMIENTO",
    )

    def extract(self, text: str) -> str | None:
        lines = [normalize_whitespace(line) for line in text.splitlines() if line.strip()]
        if not lines:
            return None

        structured_candidate = self._extract_from_identification_blocks(lines)
        if structured_candidate:
            return structured_candidate

        joined = "\n".join(lines)
        best_candidates: dict[str, DocumentCandidate] = {}

        for match in re.finditer(
            rf"{self._DOC_TYPE_PATTERN}\W*([0-9OoIl\.\-\s]{{5,24}})",
            joined,
            re.IGNORECASE,
        ):
            document = normalize_document_number(match.group(1))
            if not document or is_probable_mobile_number(document):
                continue
            score = self._score_candidate(
                lines=lines,
                line_index=self._line_index_from_offset(lines, match.start()),
                document=document,
                context=match.group(0),
            )
            self._upsert_candidate(best_candidates, document, score, match.start())

        for line_index, line in enumerate(lines):
            normalized_line = normalize_search_text(line)
            if re.fullmatch(self._DOC_TYPE_PATTERN, normalized_line):
                if line_index + 1 < len(lines):
                    document = normalize_document_number(lines[line_index + 1])
                    if document and not is_probable_mobile_number(document):
                        score = self._score_candidate(
                            lines=lines,
                            line_index=line_index + 1,
                            document=document,
                            context=f"{line} {lines[line_index + 1]}",
                        )
                        self._upsert_candidate(best_candidates, document, score, line_index)

        for line_index, line in enumerate(lines):
            for match in re.finditer(r"[0-9OoIl\.\-\s]{6,24}", line):
                document = normalize_document_number(match.group(0))
                if not document or is_probable_mobile_number(document):
                    continue
                score = self._score_candidate(
                    lines=lines,
                    line_index=line_index,
                    document=document,
                    context=line,
                )
                self._upsert_candidate(best_candidates, document, score, line_index)

        if not best_candidates:
            return None

        best = max(best_candidates.values(), key=lambda item: (item.score, len(item.document), -item.start))
        return best.document

    def _extract_from_identification_blocks(self, lines: list[str]) -> str | None:
        anchor_indexes = [
            idx
            for idx, line in enumerate(lines[:140])
            if "IDEN" in normalize_search_text(line)
        ]
        if not anchor_indexes:
            return None

        for anchor_index in anchor_indexes:
            end = min(len(lines), anchor_index + 24)
            for line_index in range(anchor_index + 1, end):
                line = lines[line_index]
                normalized_line = normalize_search_text(line)
                if any(token in normalized_line for token in self._NEGATIVE_CONTEXT_TOKENS):
                    continue
                if "/" in line:
                    continue
                if "*" in line:
                    continue

                matches = re.findall(r"\d[\d\.\-\s]{5,24}", line)
                normalized_candidates: list[str] = []
                for match in matches:
                    document = normalize_document_number(match)
                    if not document or is_probable_mobile_number(document):
                        continue
                    if len(set(document)) == 1:
                        continue
                    normalized_candidates.append(document)

                if len(normalized_candidates) != 1:
                    continue
                candidate = normalized_candidates[0]
                if 7 <= len(candidate) <= 11:
                    return candidate
        return None

    def _score_candidate(
        self,
        lines: list[str],
        line_index: int,
        document: str,
        context: str,
    ) -> int:
        score = 50
        length = len(document)
        if 8 <= length <= 11:
            score += 30
        elif length == 7:
            score += 18
        elif 12 <= length <= 15:
            score += 20
        elif length == 6:
            score += 8

        normalized_context = normalize_search_text(context)
        if re.search(self._DOC_TYPE_PATTERN, normalized_context):
            score += 24
        if any(token in normalized_context for token in self._IDENTIFICATION_TOKENS):
            score += 16

        window_start = max(0, line_index - 2)
        window_end = min(len(lines), line_index + 3)
        window_text = normalize_search_text(" ".join(lines[window_start:window_end]))
        if any(token in window_text for token in self._IDENTIFICATION_TOKENS):
            score += 24
        if re.search(self._DOC_TYPE_PATTERN, window_text):
            score += 18

        if line_index <= 20 and re.fullmatch(r"[0-9\.\-\s]+", lines[line_index]):
            score += 26
        elif line_index >= 80:
            score -= 52
        elif line_index >= 55:
            score -= 30

        if any(token in window_text for token in self._NEGATIVE_CONTEXT_TOKENS):
            score -= 34

        unique_digits = set(document)
        if len(unique_digits) == 1:
            score -= 90
        elif len(unique_digits) <= 2:
            score -= 10
        return score

    def _upsert_candidate(
        self,
        candidates: dict[str, DocumentCandidate],
        document: str,
        score: int,
        start: int,
    ) -> None:
        candidate = DocumentCandidate(document=document, score=score, start=start)
        current = candidates.get(document)
        if current is None or candidate.score > current.score:
            candidates[document] = candidate

    def _line_index_from_offset(self, lines: list[str], offset: int) -> int:
        running = 0
        for idx, line in enumerate(lines):
            next_running = running + len(line) + 1
            if offset < next_running:
                return idx
            running = next_running
        return max(0, len(lines) - 1)


class PdxPatientDocumentExtractor(PatientDocumentExtractorContract):
    def extract(self, text: str) -> str | None:
        if not text:
            return None

        # Strict PDX rule:
        # extract only from the "Identificacion" patient line,
        # and only the value before "Tel/Cel".
        lines = [line.strip().replace("\x00", " ") for line in text.splitlines() if line.strip()]
        for idx, line in enumerate(lines[:40]):
            normalized_line = normalize_search_text(line)
            if "IDEN" not in normalized_line:
                continue

            window = line
            if idx + 1 < len(lines):
                # OCR can split the identification row into two lines.
                window = f"{line} {lines[idx + 1]}"

            candidate = self._extract_from_identification_window(window)
            if candidate:
                return candidate

        return None

    def _extract_from_identification_window(self, window: str) -> str | None:
        if not window:
            return None

        id_section = window
        label_match = re.search(
            r"IDEN[^0-9:\n]{0,30}[:\-]?\s*",
            id_section,
            re.IGNORECASE,
        )
        if label_match:
            id_section = id_section[label_match.end() :]

        # Strict cutoff: ignore any number after telephone/cellular marker.
        id_section = re.split(
            r"\b(?:TEL(?:EFONO)?|CEL(?:ULAR)?)\b",
            id_section,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        typed_match = re.search(
            r"\b(?:CC|TI|CE|RC|PA)\b\W*([0-9OoIl\.\-\s]{5,24})",
            id_section,
            re.IGNORECASE,
        )
        if typed_match:
            candidate = normalize_document_number(normalize_whitespace(typed_match.group(1)))
            if candidate and not is_probable_mobile_number(candidate):
                return candidate

        fallback_match = re.search(r"([0-9OoIl\.\-\s]{6,24})", id_section)
        if fallback_match:
            candidate = normalize_document_number(normalize_whitespace(fallback_match.group(1)))
            if candidate and not is_probable_mobile_number(candidate):
                return candidate

        return None


class PdxHybridPatientDocumentExtractor(PatientDocumentExtractorContract):
    def __init__(
        self,
        strict_extractor: PatientDocumentExtractorContract | None = None,
        table_extractor: PatientDocumentExtractorContract | None = None,
        fallback_extractor: PatientDocumentExtractorContract | None = None,
    ) -> None:
        self._strict_extractor = strict_extractor or PdxPatientDocumentExtractor()
        self._table_extractor = table_extractor or PdxHighlightedPatientDocumentExtractor()
        self._fallback_extractor = fallback_extractor or AdditionalPatientDocumentExtractor()

    def extract(self, text: str) -> str | None:
        strict_candidate = self._strict_extractor.extract(text)
        if strict_candidate:
            return strict_candidate
        table_candidate = self._table_extractor.extract(text)
        if table_candidate:
            return table_candidate
        return self._fallback_extractor.extract(text)


class HaoPatientDocumentExtractor(BasePatternPatientDocumentExtractor):
    _MAX_LINES = 130
    _STOP_PATTERNS = (
        r"\bFIRMA\b",
        r"\bBACTERIOLOG",
        r"\bPROFESIONAL\b",
    )
    _PRIMARY_PATTERNS = (
        r"IDENTIFIC(?:ACION)?\s*[:=\-]?\s*(?:CC|TI|CE|RC|PA)?[\s\-\.:]*(\d[\d\.\-\s]{5,24})",
        r"(?:PACIENTE|USUARIO)[^\n]{0,120}\b(?:CC|TI|CE|RC|PA)\W{0,4}(\d[\d\.\-\s]{5,24})",
    )


class AdditionalPatientDocumentExtractor(BasePatternPatientDocumentExtractor):
    _MAX_LINES = 130
    _STOP_PATTERNS = (
        r"\bFIRMA\b",
        r"\bBACTERIOLOG",
        r"\bPROFESIONAL\b",
    )
    _PRIMARY_PATTERNS = (
        r"IDENTIFIC(?:ACION)?\s*[:=\-]?\s*(?:CC|TI|CE|RC|PA)?[\s\-\.:]*(\d[\d\.\-\s]{5,24})",
        r"(?:NUMERO|N[UUM]MERO)\s+DE\s+DOCUMENTO\s*[:=\-]?\s*(\d[\d\.\-\s]{5,24})",
        r"DOCUMENTO\s+IDENTIDAD\s*[:=\-]?\s*(\d[\d\.\-\s]{5,24})",
        r"Documento\s*:\s*(\d{6,15})",
    )


class CrcAnchorPatientDocumentExtractor(PatientDocumentExtractorContract):
    def extract(self, text: str) -> str | None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return None

        anchor_tokens = (
            "NUMERO DE IDENTIFIC",
            "NUMERO DOCUMENTO",
            "NUMERO DE DOCUMENTO",
            "DOCUMENTO IDENTIDAD",
            "NUMERO DE ID",
        )
        anchor_indexes = [
            idx
            for idx, line in enumerate(lines)
            if any(token in normalize_search_text(line) for token in anchor_tokens)
        ]
        if not anchor_indexes:
            return None

        strong_negative_tokens = ("CELULAR", "TELEFONO")
        generic_negative_tokens = (
            "CUPS",
            "CODIGO",
            "VERSION",
            "NIT",
            "CUFE",
            "AUTORIZACION",
            "FACTURA",
        )
        per_document_best: dict[str, DocumentCandidate] = {}

        for anchor_idx in anchor_indexes:
            anchor_line = normalize_search_text(lines[anchor_idx])
            for offset in range(0, 18):
                line_idx = anchor_idx + offset
                if line_idx >= len(lines):
                    break

                candidate_line = lines[line_idx]
                local_context = " ".join(
                    lines[max(0, line_idx - 1) : min(len(lines), line_idx + 2)]
                )
                normalized_context = normalize_search_text(local_context)

                for match in re.finditer(r"\d[\d\.\-\s]{5,24}", candidate_line):
                    normalized_document = normalize_document_number(match.group(0))
                    if not normalized_document:
                        continue

                    if (
                        "NIT" in normalized_context
                        and normalized_document.startswith("9")
                        and len(normalized_document) >= 9
                    ):
                        continue
                    if any(token in normalized_context for token in ("CUPS", "CODIGO")) and len(
                        normalized_document
                    ) <= 6:
                        continue

                    score = 72
                    if "IDENTIFIC" in anchor_line:
                        score += 24
                    if "DOCUMENTO" in anchor_line:
                        score += 16
                    score += max(0, 28 - (offset * 2))

                    if re.fullmatch(r"\d{6,15}", candidate_line):
                        score += 16
                    if is_probable_mobile_number(normalized_document):
                        score -= 22
                    if any(token in normalized_context for token in strong_negative_tokens):
                        score -= 26
                    if any(token in normalized_context for token in generic_negative_tokens):
                        score -= 12
                    if len(set(normalized_document)) <= 2:
                        score -= 8

                    candidate = DocumentCandidate(
                        document=normalized_document,
                        score=score,
                        start=(anchor_idx * 1000) + line_idx,
                    )
                    current_best = per_document_best.get(normalized_document)
                    if current_best is None or candidate.score > current_best.score:
                        per_document_best[normalized_document] = candidate

        if not per_document_best:
            return None

        candidates = list(per_document_best.values())
        best = max(candidates, key=lambda item: (item.score, -item.start, len(item.document)))
        if is_probable_mobile_number(best.document):
            non_mobile_candidates = [
                item for item in candidates if not is_probable_mobile_number(item.document)
            ]
            if non_mobile_candidates:
                best_non_mobile = max(
                    non_mobile_candidates,
                    key=lambda item: (item.score, -item.start, len(item.document)),
                )
                if best_non_mobile.score >= best.score - 15:
                    return best_non_mobile.document

        return best.document


class CrcPatientDocumentExtractor(PatientDocumentExtractorContract):
    def __init__(
        self,
        generic_extractor: PatientDocumentExtractorContract | None = None,
        anchor_extractor: PatientDocumentExtractorContract | None = None,
    ) -> None:
        self._generic_extractor = generic_extractor or PatternScoredPatientDocumentExtractor()
        self._anchor_extractor = anchor_extractor or CrcAnchorPatientDocumentExtractor()

    def extract(self, text: str) -> str | None:
        generic_document = self._generic_extractor.extract(text)
        crc_document = self._anchor_extractor.extract(text)

        if crc_document is None:
            return generic_document
        if generic_document is None:
            return crc_document
        if generic_document == crc_document:
            return generic_document

        if is_probable_mobile_number(generic_document) and not is_probable_mobile_number(
            crc_document
        ):
            return crc_document
        if len(generic_document) <= 6 and len(crc_document) >= 7:
            return crc_document
        if (
            generic_document.startswith("9")
            and len(generic_document) >= 9
            and not crc_document.startswith("9")
        ):
            return crc_document
        if self._has_crc_noise_context(text, generic_document) and not self._has_crc_noise_context(
            text, crc_document
        ):
            return crc_document

        return generic_document

    def _has_crc_noise_context(self, text: str, document: str) -> bool:
        normalized_document = re.sub(r"\D", "", document)
        if not normalized_document:
            return False

        for line in text.splitlines():
            if normalized_document not in re.sub(r"\D", "", line):
                continue
            normalized_line = normalize_search_text(line)
            if any(
                token in normalized_line
                for token in ("CUPS", "CODIGO", "VERSION", "NIT", "CUFE", "AUTORIZACION")
            ):
                return True
        return False


class CrcHighlightedPatientDocumentExtractor(PatientDocumentExtractorContract):
    _ANCHOR_TOKENS: tuple[str, ...] = ("IDENTIFIC", "DOCUMENTO")

    def extract(self, text: str) -> str | None:
        lines = [normalize_whitespace(line) for line in text.splitlines() if line.strip()]
        if not lines:
            return None

        anchor_indexes = [
            idx
            for idx, line in enumerate(lines)
            if any(token in normalize_search_text(line) for token in self._ANCHOR_TOKENS)
        ]
        frequencies: dict[str, int] = {}
        best_by_document: dict[str, DocumentCandidate] = {}

        for line_index, line in enumerate(lines):
            for match in re.finditer(r"\d[\d\.\-\s]{4,24}", line):
                document = normalize_document_number(match.group(0))
                if not document or is_probable_mobile_number(document):
                    continue

                frequencies[document] = frequencies.get(document, 0) + 1
                score = self._score_candidate(
                    lines=lines,
                    line_index=line_index,
                    document=document,
                    anchor_indexes=anchor_indexes,
                )
                candidate = DocumentCandidate(
                    document=document,
                    score=score,
                    start=line_index,
                )
                current = best_by_document.get(document)
                if current is None or candidate.score > current.score:
                    best_by_document[document] = candidate

        if not best_by_document:
            return None

        weighted_candidates: list[DocumentCandidate] = []
        for document, candidate in best_by_document.items():
            frequency_bonus = min(frequencies.get(document, 0), 3) * 8
            weighted_candidates.append(
                DocumentCandidate(
                    document=document,
                    score=candidate.score + frequency_bonus,
                    start=candidate.start,
                )
            )

        best = max(weighted_candidates, key=lambda item: (item.score, len(item.document), -item.start))
        return best.document

    def _score_candidate(
        self,
        lines: list[str],
        line_index: int,
        document: str,
        anchor_indexes: list[int],
    ) -> int:
        line = lines[line_index]
        normalized_line = normalize_search_text(line)

        score = 50
        document_length = len(document)
        if 8 <= document_length <= 11:
            score += 30
        elif document_length == 7:
            score += 22
        elif document_length == 6:
            score += 10
        elif 12 <= document_length <= 15:
            score += 16

        if re.fullmatch(r"[0-9\.\-\s]+", line):
            score += 12
        if any(token in normalized_line for token in self._ANCHOR_TOKENS):
            score += 24

        if anchor_indexes:
            distance = min(abs(line_index - anchor_idx) for anchor_idx in anchor_indexes)
            score += max(0, 36 - (distance * 10))

        if "NIT" in normalized_line and document.startswith("9") and document_length >= 9:
            score -= 34
        if len(set(document)) <= 2:
            score -= 10

        return score
