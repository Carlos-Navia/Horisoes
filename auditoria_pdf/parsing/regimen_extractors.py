from __future__ import annotations

import re

from auditoria_pdf.parsing.common import (
    compact_search_text,
    extract_first_match,
    extract_literal_regimen,
    normalize_ocr_digit_noise,
    normalize_regimen,
    normalize_search_text,
)
from auditoria_pdf.parsing.contracts import RegimenExtractorContract
from auditoria_pdf.parsing.fev_invoice_field_extractor import FevInvoiceFieldExtractor


class LiteralAnchorRegimenExtractor(RegimenExtractorContract):
    def __init__(self, anchor_patterns: list[str]) -> None:
        self._anchor_patterns = anchor_patterns

    def extract(self, text: str) -> str | None:
        return extract_literal_regimen(text, self._anchor_patterns)


class NoRegimenExtractor(RegimenExtractorContract):
    def extract(self, text: str) -> str | None:
        return None


class FevRegimenExtractor(RegimenExtractorContract):
    def __init__(
        self,
        fev_field_extractor: FevInvoiceFieldExtractor | None = None,
    ) -> None:
        self._fev_field_extractor = fev_field_extractor or FevInvoiceFieldExtractor()

    def extract(self, text: str) -> str | None:
        return self._fev_field_extractor.extract_regimen(text)


class PdeRegimenExtractor(LiteralAnchorRegimenExtractor):
    _SISBEN_FIELD_TOKENS: tuple[str, ...] = (
        "TIPO AFILIADO",
        "TIPO DE AFILIADO",
        "CATEGORIA AFILIADO",
        "CATEGORIA AFILIADA",
        "CATEGORIA A FILIADO",
        "CATEGORIA A FILIADA",
        "NIVEL SISBEN",
    )

    def __init__(self) -> None:
        super().__init__(
            [
                r"IPS\s+PRIMARIA:\s*(SUBSIDIADO|CONTRIBUTIVO)",
                r"R\w*GIMEN\s+DE\s+AFILIACI\w*N:\s*(SUBSIDIADO|CONTRIBUTIVO)",
                r"R\w*GIMEN\s*[:\-]\s*(SUBSIDIADO|CONTRIBUTIVO)",
            ]
        )

    def extract(self, text: str) -> str | None:
        anchored = extract_first_match(self._anchor_patterns, text)
        normalized_anchor = normalize_regimen(anchored)
        if normalized_anchor:
            return normalized_anchor

        # ADRES BDUA table format where columns might stick together
        adres_regimen = extract_first_match([r"(SUBSIDIADO|CONTRIBUTIVO)\s*\d{2}/\d{2}/\d{4}"], text)
        if adres_regimen:
            return normalize_regimen(adres_regimen)

        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # NUEVA EPS format seen in PDE_*_FVEA*.pdf:
        # explicit subsidiado marker in header.
        for line in lines[:120]:
            normalized_line = normalize_search_text(line)
            if "BRIGADA MOVIL" in normalized_line and "SUBSIDIADO" in normalized_line:
                return "SUBSIDIADO"

        if self._has_sisben_affiliation_marker(lines):
            return "SUBSIDIADO"

        if self._has_empty_semanas_cotizadas(lines):
            return "SUBSIDIADO"

        # NUEVA EPS format where regimen is implicit through affiliation type.
        for line in lines[:180]:
            normalized_line = normalize_search_text(line)
            if "TIPO AFILIADO" not in normalized_line:
                continue
            if "COTIZANTE" in normalized_line:
                return "CONTRIBUTIVO"
            if "BENEFICIARIO" in normalized_line:
                return "CONTRIBUTIVO"

        for line in lines[:160]:
            compact_line = compact_search_text(line)
            if "CONTRIBUT" in compact_line:
                return "CONTRIBUTIVO"
            if "SUBSIDI" in compact_line:
                return "SUBSIDIADO"

        anchored = extract_first_match([r"\b(SUBSIDIADO|CONTRIBUTIVO)\b"], text)
        if anchored:
            return normalize_regimen(anchored)

        return normalize_regimen(text)

    def _has_sisben_affiliation_marker(self, lines: list[str]) -> bool:
        for index, line in enumerate(lines[:220]):
            normalized_line = normalize_search_text(line)
            if "SISBEN" not in normalized_line:
                continue

            if any(token in normalized_line for token in self._SISBEN_FIELD_TOKENS):
                return True

            for neighbor_index in (index - 1, index + 1):
                if neighbor_index < 0 or neighbor_index >= len(lines):
                    continue
                neighbor_line = normalize_search_text(lines[neighbor_index])
                if any(token in neighbor_line for token in self._SISBEN_FIELD_TOKENS):
                    return True
        return False

    def _has_empty_semanas_cotizadas(self, lines: list[str]) -> bool:
        for index, line in enumerate(lines[:240]):
            normalized_line = normalize_search_text(line)
            if "SEMANAS COTIZADAS" not in normalized_line:
                continue

            value_fragment = normalized_line.split("SEMANAS COTIZADAS", maxsplit=1)[1]
            value_fragment = value_fragment.lstrip(":- ").strip()
            if re.search(r"\d", value_fragment):
                continue

            next_line = self._next_non_empty_line(lines, index + 1, max_distance=2)
            if next_line and re.fullmatch(r"\d{1,4}", normalize_search_text(next_line)):
                continue

            return True
        return False

    def _next_non_empty_line(
        self,
        lines: list[str],
        start_index: int,
        max_distance: int,
    ) -> str | None:
        end = min(len(lines), start_index + max_distance + 1)
        for index in range(start_index, end):
            candidate = lines[index].strip()
            if candidate:
                return candidate
        return None


class SemanasCotizadasRegimenInferenceExtractor(RegimenExtractorContract):
    _NEXT_FIELD_TOKENS: tuple[str, ...] = (
        "IPS PRIMARIA",
        "TIPO AFILIADO",
        "CATEGORIA AFILIADO",
        "CATEGORIA AFILIADA",
    )
    _NON_VALUE_TOKENS: tuple[str, ...] = (
        "IPS PRIMARIA",
        "TIPO AFILIADO",
        "CATEGORIA AFILIADO",
        "CATEGORIA AFILIADA",
        "MUNICIPIO",
        "DEPARTAMENTO",
        "TELEFONO",
        "DIRECCION",
        "RETORNAR",
        "RED SALUD",
        "SUBSIDIADO",
    )

    def extract(self, text: str) -> str | None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        found_semanas_field = False
        found_semanas_content = False

        for index, line in enumerate(lines[:260]):
            normalized_line = normalize_search_text(line)
            if "SEMANAS COTIZADAS" not in normalized_line:
                continue

            found_semanas_field = True
            value_fragment = normalized_line.split("SEMANAS COTIZADAS", maxsplit=1)[1]
            value_fragment = value_fragment.lstrip(":- ").strip()
            if self._is_probable_semanas_value(value_fragment):
                found_semanas_content = True
                continue

            next_line = self._next_non_empty_line(lines, index + 1, max_distance=2)
            if not next_line:
                continue

            normalized_next_line = normalize_search_text(next_line)
            if any(token in normalized_next_line for token in self._NEXT_FIELD_TOKENS):
                continue

            if self._is_probable_semanas_value(normalized_next_line):
                found_semanas_content = True

        if found_semanas_content:
            return "CONTRIBUTIVO"
        if found_semanas_field:
            return "SUBSIDIADO"
        return None

    def _is_probable_semanas_value(self, value: str) -> bool:
        denoised = normalize_ocr_digit_noise(value)
        normalized_value = normalize_search_text(denoised)
        if not normalized_value:
            return False
        if ":" in denoised:
            return False
        if len(normalized_value) > 25:
            return False
        if any(token in normalized_value for token in self._NON_VALUE_TOKENS):
            return False
        return True

    def _next_non_empty_line(
        self,
        lines: list[str],
        start_index: int,
        max_distance: int,
    ) -> str | None:
        end = min(len(lines), start_index + max_distance + 1)
        for index in range(start_index, end):
            candidate = lines[index].strip()
            if candidate:
                return candidate
        return None


class NuevaEpsPdeRegimenExtractor(RegimenExtractorContract):
    def __init__(
        self,
        semanas_inference_extractor: RegimenExtractorContract | None = None,
        fallback_extractor: RegimenExtractorContract | None = None,
    ) -> None:
        self._semanas_inference_extractor = (
            semanas_inference_extractor or SemanasCotizadasRegimenInferenceExtractor()
        )
        self._fallback_extractor = fallback_extractor or PdeRegimenExtractor()

    def extract(self, text: str) -> str | None:
        from_semanas = self._semanas_inference_extractor.extract(text)
        if from_semanas:
            return from_semanas
        return self._fallback_extractor.extract(text)


class SanitasPdeRegimenExtractor(RegimenExtractorContract):
    _ANCHOR_PATTERNS: list[str] = [
        r"MOTIVO\s+DEL\s+ESTADO\s+DEL\s+USUARIO\s*[:=\-]?\s*(?:\r?\n\s*)?(SUBSIDIADO|CONTRIBUTIVO)",
        r"MOTIVO\s+DEL\s+ESTADO\s+DEL\s+USUARIO[^\n]{0,120}\b(SUBSIDIADO|CONTRIBUTIVO)\b",
    ]

    def __init__(self, fallback_extractor: RegimenExtractorContract | None = None) -> None:
        self._fallback_extractor = fallback_extractor or PdeRegimenExtractor()

    def extract(self, text: str) -> str | None:
        anchored = normalize_regimen(extract_first_match(self._ANCHOR_PATTERNS, text))
        if anchored:
            return anchored

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines[:260]):
            normalized_line = normalize_search_text(line)
            if (
                "MOTIVO DEL ESTADO DEL USUARIO" not in normalized_line
                and "ESTADO DEL USUARIO" not in normalized_line
            ):
                continue

            start = max(0, index - 1)
            end = min(len(lines), index + 3)
            nearby_text = "\n".join(lines[start:end])
            nearby_regimen = normalize_regimen(
                extract_first_match([r"\b(SUBSIDIADO|CONTRIBUTIVO)\b"], nearby_text)
            )
            if nearby_regimen:
                return nearby_regimen

        return self._fallback_extractor.extract(text)


class CrcRegimenExtractor(LiteralAnchorRegimenExtractor):
    def __init__(self) -> None:
        super().__init__([r"R\w*GIMEN\s*[:\-]?\s*(SUBSIDIADO|CONTRIBUTIVO)"])


class HevRegimenExtractor(LiteralAnchorRegimenExtractor):
    def __init__(self) -> None:
        super().__init__([r"R\w*GIMEN\s*[:\-]?\s*(SUBSIDIADO|CONTRIBUTIVO)"])


class PdxRegimenExtractor(LiteralAnchorRegimenExtractor):
    def __init__(self) -> None:
        super().__init__([r"R\w*GIMEN\s*[:\-]?\s*(SUBSIDIADO|CONTRIBUTIVO)"])


class HaoRegimenExtractor(LiteralAnchorRegimenExtractor):
    def __init__(self) -> None:
        super().__init__([r"R\w*GIMEN\s*[:\-]?\s*(SUBSIDIADO|CONTRIBUTIVO)"])


class AdditionalRegimenExtractor(LiteralAnchorRegimenExtractor):
    def __init__(self) -> None:
        super().__init__([r"R\w*GIMEN\s*[:\-]?\s*(SUBSIDIADO|CONTRIBUTIVO)"])
