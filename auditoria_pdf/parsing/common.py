from __future__ import annotations

import re
import unicodedata


def normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    without_accents = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return " ".join(without_accents.upper().split())


def compact_search_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", normalize_search_text(value))


def normalize_ocr_digit_noise(value: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in {"O", "o"}:
            return "0"
        return "1"

    return re.sub(r"(?<=\d)[OoIl|]|[OoIl|](?=\d)", _replace, value)


def normalize_document_number(value: str | None) -> str | None:
    if not value:
        return None

    normalized_value = normalize_ocr_digit_noise(value)
    chunks = re.findall(r"\d+", normalized_value)
    for chunk in chunks:
        if 6 <= len(chunk) <= 15:
            return chunk

    digits = "".join(chunks)
    if 6 <= len(digits) <= 15:
        return digits
    return None


def extract_first_match(
    patterns: list[str],
    text: str,
    flags: int = re.IGNORECASE | re.MULTILINE,
) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return normalize_whitespace(match.group(1))
    return None


def normalize_document_type(value: str | None) -> str | None:
    if not value:
        return None

    compact = normalize_whitespace(value)
    token = normalize_search_text(compact)
    mapping = {
        "CC": "CC",
        "TI": "TI",
        "CE": "CE",
        "RC": "RC",
        "PA": "PA",
        "CEDULA DE CIUDADANIA": "CC",
        "TARJETA IDENTIDAD": "TI",
        "CEDULA DE EXTRANJERIA": "CE",
        "REGISTRO CIVIL": "RC",
        "PASAPORTE": "PA",
    }
    if token in mapping:
        return mapping[token]
    if len(token) <= 2:
        return None
    return compact


def normalize_patient_name(value: str | None) -> str | None:
    if not value:
        return None

    repaired = (
        value.replace("Ã‘", "Ñ")
        .replace("Ã±", "ñ")
        .replace("Â", "")
        .replace("\u200b", " ")
    )
    normalized = unicodedata.normalize("NFD", repaired)
    without_accents = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    letters_only = re.sub(r"[^A-Za-zÑñ]+", " ", without_accents)
    compact = " ".join(letters_only.upper().split())
    if not compact:
        return None

    stop_tokens = {
        "AFILIADO",
        "APELLIDO",
        "APELLIDOS",
        "AUTORIZACION",
        "CODIGO",
        "CONSULTA",
        "DEPARTAMENTO",
        "DIRECCION",
        "DOCUMENTO",
        "EDAD",
        "ELECTRONICA",
        "EPS",
        "FACTURA",
        "FECHA",
        "IDENTIFICACION",
        "INFORMACION",
        "MUNICIPIO",
        "NOMBRE",
        "NOMBRES",
        "NUMERO",
        "PACIENTE",
        "PAGINA",
        "PRESTADOR",
        "REGIMEN",
        "SALIR",
        "TELEFONO",
        "TIPO",
        "USUARIO",
    }
    tokens = compact.split()
    for index, token in enumerate(tokens):
        if token in stop_tokens:
            tokens = tokens[:index]
            break

    name_tokens = [token for token in tokens if token not in stop_tokens]

    if len(name_tokens) < 2:
        return None
    if len(name_tokens) > 8:
        name_tokens = name_tokens[:8]

    return " ".join(name_tokens)


def normalize_regimen(value: str | None) -> str | None:
    if not value:
        return None

    token = normalize_search_text(value)
    compact_token = re.sub(r"[^A-Z0-9]+", "", token)
    if "SUBSIDI" in token or "SUBSIDI" in compact_token:
        return "SUBSIDIADO"
    if "CONTRIBUT" in token or "CONTRIBUT" in compact_token:
        return "CONTRIBUTIVO"
    return None


def extract_literal_regimen(text: str, anchor_patterns: list[str]) -> str | None:
    anchored = extract_first_match(anchor_patterns, text)
    normalized = normalize_regimen(anchored)
    if normalized:
        return normalized

    fallback = extract_first_match([r"\b(SUBSIDIADO|CONTRIBUTIVO)\b"], text)
    return normalize_regimen(fallback)


def is_probable_mobile_number(value: str | None) -> bool:
    if not value:
        return False
    return re.fullmatch(r"3\d{9}", value) is not None
