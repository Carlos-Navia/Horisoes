from __future__ import annotations

import re

from auditoria_pdf.parsing.common import normalize_patient_name, normalize_search_text
from auditoria_pdf.parsing.contracts import PatientNameExtractorContract


class GenericPatientNameExtractor(PatientNameExtractorContract):
    _STRUCTURED_LABELS = {
        "PRIMER NOMBRE": ("first_name",),
        "SEGUNDO NOMBRE": ("middle_name",),
        "PRIMER APELLIDO": ("first_last_name",),
        "SEGUNDO APELLIDO": ("second_last_name",),
    }
    _FIELD_LABEL_TOKENS = (
        "APELLIDO",
        "AUTORIZA",
        "COBERTURA",
        "CODIGO",
        "DEPARTAMENTO",
        "DIRECCION",
        "DOCUMENTO",
        "EDAD",
        "EPS",
        "FACTURA",
        "FECHA",
        "IDENTIFICACION",
        "MUNICIPIO",
        "NOMBRE",
        "NUMERO",
        "PACIENTE",
        "REGIMEN",
        "SEXO",
        "TELEFONO",
        "TIPO",
    )
    _DIRECT_LABELS = (
        "NOMBRE",
        "NOMBRES",
        "NOMBRE DEL PACIENTE",
        "NOMBRE PACIENTE",
        "NOMBRE USUARIO",
        "NOMBRE COMPLETO",
    )

    def extract(self, text: str) -> str | None:
        if not text:
            return None

        lines = [line.strip() for line in text.splitlines() if line.strip()]

        patient_header_name = self._extract_from_patient_header(lines)
        if patient_header_name:
            return patient_header_name

        structured_name = self._extract_from_structured_fields(lines)
        if structured_name:
            return structured_name

        combined_name = self._extract_from_combined_names(text)
        if combined_name:
            return combined_name

        direct_name = self._extract_from_direct_labels(lines)
        if direct_name:
            return direct_name

        return None

    def _extract_from_patient_header(self, lines: list[str]) -> str | None:
        for index, line in enumerate(lines[:120]):
            if normalize_search_text(line) != "PACIENTE":
                continue

            parts: list[str] = []
            for candidate in lines[index + 1 : index + 9]:
                normalized_candidate = normalize_search_text(candidate)
                if normalized_candidate in {"CC", "TI", "CE", "RC", "PA", "-"}:
                    continue
                if re.fullmatch(r"[\d\-\.\s]+", candidate):
                    continue
                if self._looks_like_field_label(normalized_candidate):
                    break

                cleaned = self._clean_name_part(candidate)
                if cleaned:
                    parts.append(cleaned)
                    joined = normalize_patient_name(" ".join(parts))
                    if joined and len(joined.split()) >= 3:
                        return joined

            joined = normalize_patient_name(" ".join(parts))
            if joined:
                return joined
        return None

    def _extract_from_structured_fields(self, lines: list[str]) -> str | None:
        values: dict[str, str] = {}
        for label, target_keys in self._STRUCTURED_LABELS.items():
            value = self._find_value_after_label(lines, label)
            if value:
                values[target_keys[0]] = value

        ordered_parts = [
            values.get("first_name"),
            values.get("middle_name"),
            values.get("first_last_name"),
            values.get("second_last_name"),
        ]
        joined = " ".join(part for part in ordered_parts if part)
        return normalize_patient_name(joined)

    def _extract_from_combined_names(self, text: str) -> str | None:
        patterns = (
            r"NOMBRES?\s+Y\s+APELLIDOS?\s*[:=\-]?\s*([^\n]{5,100})",
            r"NOMBRES?\s*[:=\-]?\s*([^\n]{2,80}?)\s+APELLIDOS?\s*[:=\-]?\s*([^\n]{2,80})",
            r"NOMBRES?\s*([^\n]{2,80}?)APELLIDOS?\s*([^\n]{2,80})",
            # ADRES format where table columns are combined by OCR
            r"Nombres\s+([^\d\n]{2,60}?)\s+Apellidos\s+([^\d\n]{2,60})",
            r"NOMBRE\s+Y\s+APELLIDOS?\s*[:=\-]?\s*([^\n]{5,100})",
            r"NOMBRE\s+COMPLETO\s*[:=\-]?\s*([^\n]{5,100})",
            r"NOMBRE\s+DEL\s+PACIENTE\s*[:=\-]?\s*([^\n]{5,100})",
            r"NOMBRE\s+USUARIO\s*[:=\-]?\s*([^\n]{5,100})",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                if match.lastindex and match.lastindex >= 2:
                    candidate = f"{match.group(1)} {match.group(2)}"
                else:
                    candidate = match.group(1)
                normalized = normalize_patient_name(candidate)
                if normalized:
                    return normalized
        return None

    def _extract_from_direct_labels(self, lines: list[str]) -> str | None:
        for index, line in enumerate(lines[:260]):
            normalized_line = normalize_search_text(line)
            for label in self._DIRECT_LABELS:
                if normalized_line == label:
                    candidate = self._next_name_line(lines, index + 1)
                    if candidate:
                        return candidate
                    continue

                if normalized_line.startswith(f"{label} "):
                    raw_candidate = line[len(label) :].lstrip(" :=-\t")
                    normalized = normalize_patient_name(raw_candidate)
                    if normalized:
                        return normalized

                if f"{label}:" in normalized_line or f"{label} -" in normalized_line:
                    raw_candidate = re.split(r"[:=\-]", line, maxsplit=1)[-1]
                    normalized = normalize_patient_name(raw_candidate)
                    if normalized:
                        return normalized
        return None

    def _next_name_line(self, lines: list[str], start_index: int) -> str | None:
        parts: list[str] = []
        for candidate in lines[start_index : start_index + 4]:
            normalized_candidate = normalize_search_text(candidate)
            if self._looks_like_field_label(normalized_candidate):
                break
            if re.search(r"\d", candidate):
                continue
            normalized = normalize_patient_name(candidate)
            if normalized:
                parts.append(candidate)
                joined = normalize_patient_name(" ".join(parts))
                if joined and len(joined.split()) >= 2:
                    return joined
        return normalize_patient_name(" ".join(parts))

    def _find_value_after_label(self, lines: list[str], label: str) -> str | None:
        for index, line in enumerate(lines[:260]):
            normalized_line = normalize_search_text(line)
            if label not in normalized_line:
                continue

            after_label = re.split(re.escape(label), line, maxsplit=1, flags=re.IGNORECASE)
            if len(after_label) > 1:
                same_line_value = after_label[1].lstrip(" :=-\t")
                cleaned = self._clean_name_part(same_line_value)
                if cleaned:
                    return cleaned

            for candidate in lines[index + 1 : index + 3]:
                normalized_candidate = normalize_search_text(candidate)
                if self._looks_like_field_label(normalized_candidate):
                    break
                cleaned = self._clean_name_part(candidate)
                if cleaned:
                    return cleaned
        return None

    def _looks_like_field_label(self, normalized_line: str) -> bool:
        if not normalized_line:
            return False
        if len(normalized_line.split()) > 4:
            return False
        return any(token in normalized_line for token in self._FIELD_LABEL_TOKENS)

    def _clean_name_part(self, value: str) -> str | None:
        normalized = normalize_search_text(value)
        if not normalized or re.search(r"\d", normalized):
            return None
        if self._looks_like_field_label(normalized):
            return None
        tokens = [token for token in normalized.split() if len(token) > 1]
        if not tokens:
            return None
        return " ".join(tokens)


class FevPatientNameExtractor(GenericPatientNameExtractor):
    pass


class PdePatientNameExtractor(GenericPatientNameExtractor):
    pass


class CrcPatientNameExtractor(GenericPatientNameExtractor):
    pass


class HevPatientNameExtractor(GenericPatientNameExtractor):
    pass


class PdxPatientNameExtractor(GenericPatientNameExtractor):
    pass


class HaoPatientNameExtractor(GenericPatientNameExtractor):
    pass


class AdditionalPatientNameExtractor(GenericPatientNameExtractor):
    pass
