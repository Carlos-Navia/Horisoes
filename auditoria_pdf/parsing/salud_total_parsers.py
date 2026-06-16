"""
Extractores y parsers especializados para documentos de SALUD TOTAL EPS.

Formatos soportados:
  CRC: Recibo de Satisfaccion del Servicio de Salud en Unidad Movil
       (Codigo FO-GS-UM-06-HS).
       Campo objetivo: "Numero de identificacion{valor}" (sin separador).

  PDE: Documento multi-pagina que puede contener:
         1. Consulta ADRES BDUA: "NUMERO DE IDENTIFICACION {numero}"
         2. Direccionamiento Salud Total: "Documento : {numero}"
         3. Portal transaccional Salud Total: numero solo antes de "NOMBRE"
       CUPS: codigos de 10 digitos en seccion SERVICIOS DIRECCIONADOS,
             normalizados a 6 digitos para comparar con FEV.

  PDX: Dos formatos:
         1. SGIRD RESULTADOS POCT: "DOCUMENTO DE IDENTIFICACION: CC-{numero}"
         2. Laboratorio externo (COLCAN, etc.): "Identificacion: CC {numero}"
"""
from __future__ import annotations

import re

from auditoria_pdf.domain import DocumentType
from auditoria_pdf.parsing.common import (
    is_probable_mobile_number,
    normalize_document_number,
    normalize_patient_name,
    normalize_regimen,
    normalize_search_text,
)
from auditoria_pdf.parsing.contracts import (
    CupsExtractorContract,
    PatientDocumentExtractorContract,
    PatientNameExtractorContract,
    RegimenExtractorContract,
)
from auditoria_pdf.parsing.cups_extractors import NoCupsExtractor


class NoPatientNameExtractor(PatientNameExtractorContract):
    """Extractor nulo: el perfil Salud Total no compara nombres de paciente."""

    def extract(self, text: str) -> str | None:  # noqa: ARG002
        return None
from auditoria_pdf.parsing.document_parsers import BaseDocumentParser
from auditoria_pdf.parsing.metadata_extractors import EmptyMetadataExtractor
from auditoria_pdf.parsing.patient_document_type_extractors import (
    GenericPatientDocumentTypeExtractor,
)
from auditoria_pdf.parsing.patient_name_extractors import PdePatientNameExtractor
from auditoria_pdf.parsing.pipelines import DocumentFieldExtractionPipeline
from auditoria_pdf.parsing.regimen_extractors import NoRegimenExtractor


# ─────────────────────────────────────────────────────────────────────────────
# CRC – Recibo de Satisfaccion FO-GS-UM-06-HS
# ─────────────────────────────────────────────────────────────────────────────

class SaludTotalCrcPatientDocumentExtractor(PatientDocumentExtractorContract):
    """
    Extrae el documento del paciente del CRC de Salud Total.

    El formato imprime el valor inmediatamente despues del label sin separador:
        "Numero de identificacion2374759"
    Tambien soporta el formato con "CC-" como prefijo del tipo de documento.
    """

    _PATTERNS: tuple[str, ...] = (
        r"N[uú]mero\s+de\s+identificaci[oó]n\s*[:=\-]?\s*(\d{6,15})",
        r"N[uú]mero\s+de\s+ID\s*[:=\-]?\s*(\d{6,15})",
        r"N[uú]mero\s+de\s+Documento\s*[:=\-]?\s*(\d{6,15})",
        # Fallback: numero solitario en una linea (para cuando el OCR separa en columnas)
        r"^\s*(\d{6,15})\s*$",
        # Fallback: CC seguido de guion o espacio y digitos
        r"\bCC[-/\s]+(\d{6,15})\b",
    )

    def extract(self, text: str) -> str | None:
        for pattern in self._PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                candidate = normalize_document_number(match.group(1))
                if candidate and not is_probable_mobile_number(candidate):
                    return candidate
        return None


class SaludTotalCrcRegimenExtractor(RegimenExtractorContract):
    """
    Extrae el regimen del CRC de Salud Total.

    El formato puede presentarse como:
        "RégimenSUBSIDIADO"  (sin espacio entre label y valor)
        "Régimen SUBSIDIADO"
        "Régimen CONTRIBUTIVO"
    """

    _PATTERN: str = r"R[eé]gimen\s*(SUBSIDIADO|CONTRIBUTIVO)"

    def extract(self, text: str) -> str | None:
        match = re.search(self._PATTERN, text, re.IGNORECASE)
        if match:
            return normalize_regimen(match.group(1))
        return None


class SaludTotalCrcPatientNameExtractor(PatientNameExtractorContract):
    """
    Extrae el nombre del paciente del CRC de Salud Total.

    El formato es:
        "NombresPABLO EMILIO ApellidosRIOS SANCHEZ"
    Los labels estan pegados al valor sin separador.
    """

    _PATTERN: str = (
        r"Nombres\s*([^\d\n]{2,60}?)(?=Apellidos)"
        r"Apellidos\s*([^\d\n]{2,60})"
        r"(?=\n|Tipo|Fecha|Eps|Sexo|Departamento|\Z)"
    )

    def extract(self, text: str) -> str | None:
        match = re.search(self._PATTERN, text, re.IGNORECASE | re.MULTILINE)
        if match:
            nombres = match.group(1).strip()
            apellidos = match.group(2).strip()
            return normalize_patient_name(f"{nombres} {apellidos}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PDE – ADRES BDUA + Salud Total Direccionamiento
# ─────────────────────────────────────────────────────────────────────────────

class SaludTotalPdePatientDocumentExtractor(PatientDocumentExtractorContract):
    """
    Extrae el documento del paciente del PDE de Salud Total.

    El PDE es un archivo multi-pagina con tres posibles secciones:

    1. Consulta ADRES BDUA:
          "NUMERO DE
           IDENTIFICACION 2374759"

    2. Direccionamiento Salud Total (PROCEDIMIENTO DIAGNOSTICO / LABORATORIO CLINICO):
          "Documento :
           2374759"
       o  "Documento : 2374759"

    3. Portal transaccional Salud Total (transaccional.saludtotal.com.co):
          "65807993
           NOMBRE
           ROSALBINA TAMAYO MOSQUERA"
    """

    _PATTERNS: tuple[str, ...] = (
        # ADRES BDUA: label en dos lineas, valor en la siguiente
        r"N[UÚ]MERO\s+DE\s+IDENTIFICACI[OÓ]N\s+(\d{6,15})",
        # Direccionamiento Salud Total: "Documento : {numero}" (puede tener salto de linea)
        r"Documento\s*:\s*\n?\s*(\d{6,15})",
        # Portal Grupo Familiar Salud Total
        r"C[EÉ]DULA\s+DE\s+CIUDADAN[IÍ]A\s*(\d{6,15})",
    )

    def extract(self, text: str) -> str | None:
        for pattern in self._PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                candidate = normalize_document_number(match.group(1))
                if candidate and not is_probable_mobile_number(candidate):
                    return candidate

        # Portal Salud Total: numero de ID solo en una linea,
        # seguido de labels como NOMBRE o CONSULTAR.
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for idx, line in enumerate(lines[:40]):
            if not re.fullmatch(r"\d{6,15}", line):
                continue
            window = " ".join(lines[max(0, idx - 2) : idx + 5])
            window_upper = window.upper()
            if any(token in window_upper for token in ("NOMBRE", "CONSULTAR", "REGIMEN", "ESTADO")):
                candidate = normalize_document_number(line)
                if candidate and not is_probable_mobile_number(candidate):
                    return candidate

        return None


class SaludTotalPdeRegimenExtractor(RegimenExtractorContract):
    """
    Extrae el regimen del PDE de Salud Total.

    Tres fuentes posibles dentro del mismo PDF:

    1. Direccionamiento Salud Total:
          "Regimen : Subsidiado - FOMENTO - Evento"

    2. Portal Salud Total:
          "REGIMEN PROTEGIDO  Subsidiado"

    3. ADRES BDUA (tabla): el regimen aparece concatenado con la fecha de afiliacion:
          "SUBSIDIADO17/03/2022"
    """

    _DIRECT_PATTERNS: tuple[str, ...] = (
        # Salud Total Direccionamiento
        r"Regimen\s*:\s*(Subsidiado|Contributivo)",
        # Portal transaccional
        r"R[EÉ]GIMEN\s+PROTEGIDO\s+(Subsidiado|Contributivo)",
        # ADRES BDUA: "SUBSIDIADO17/03/2022" (regime pegado a fecha)
        r"(SUBSIDIADO|CONTRIBUTIVO)\d{2}/\d{2}/\d{4}",
        # Portal Grupo Familiar
        r"\b(COTIZANTE|BENEFICIARIO)\b",
        # CRC / fallback generico
        r"R[eé]gimen\s*(SUBSIDIADO|CONTRIBUTIVO)",
    )

    def extract(self, text: str) -> str | None:
        for pattern in self._DIRECT_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).upper()
                if value in ("COTIZANTE", "BENEFICIARIO"):
                    return "CONTRIBUTIVO"
                return normalize_regimen(value)
        return None


class SaludTotalPdeCupsExtractor(CupsExtractorContract):
    """
    Extrae codigos CUPS del PDE de Salud Total.

    Salud Total usa codigos de 10 digitos en la seccion SERVICIOS DIRECCIONADOS:
        9066100000   (equiv. CUPS 906610)
        9070090000   (equiv. CUPS 907009)
        9088900000   (equiv. CUPS 908890)

    Se normalizan a 6 digitos (los primeros 6) para que la comparacion
    con la FEV (que presenta codigos de 6 digitos) sea correcta.
    """

    _TEN_DIGIT = re.compile(r"\b([89]\d{9})\b")
    _SIX_DIGIT = re.compile(r"\b([89]\d{5})\b")

    def extract(self, text: str) -> set[str]:
        cups: set[str] = set()
        in_section = False

        for line in text.splitlines():
            line_upper = line.upper().strip()
            if "SERVICIOS DIRECCIONADOS" in line_upper:
                in_section = True
                continue

            if in_section:
                # Extraer codigos de 10 digitos y normalizar a 6
                for match in self._TEN_DIGIT.finditer(line):
                    cups.add(match.group(1)[:6])
                # Extraer codigos de 6 digitos directamente
                for match in self._SIX_DIGIT.finditer(line):
                    cups.add(match.group(1))
                # Fin de seccion si aparece otro encabezado de bloque
                if re.match(r"^[A-Z\s]{15,}$", line_upper) and line_upper not in {
                    "SERVICIOS DIRECCIONADOS",
                    "CODIGO  CANT  NOMBRE",
                    "CODIGO CANT NOMBRE",
                }:
                    in_section = False

        if not cups:
            # Fallback: buscar en todo el texto
            for match in self._TEN_DIGIT.finditer(text):
                cups.add(match.group(1)[:6])
            for match in self._SIX_DIGIT.finditer(text):
                cups.add(match.group(1))

        return cups


# ─────────────────────────────────────────────────────────────────────────────
# PDX – Resultados de examenes (SGIRD / Laboratorio externo)
# ─────────────────────────────────────────────────────────────────────────────

class SaludTotalPdxPatientDocumentExtractor(PatientDocumentExtractorContract):
    """
    Extrae el documento del paciente del PDX de Salud Total.

    Dos formatos:
    1. SGIRD RESULTADOS POCT:
          "DOCUMENTO DE IDENTIFICACION: CC-2374759"
          "DOCUMENTO DE IDENTIFICACION: CC/2374759"
    2. Laboratorio externo (COLCAN, etc.):
          "Identificacion: CC 65807993"
    """

    _PATTERNS: tuple[str, ...] = (
        # SGIRD RESULTADOS POCT
        r"DOCUMENTO\s+DE\s+IDENTIFICACION\s*:\s*(?:CC|TI|CE|RC|PA)[-/\s]*(\d{6,15})",
        # Laboratorio externo con tipo de documento
        r"Identificaci[oó]n\s*:\s*(?:CC|TI|CE|RC|PA)\s+(\d{6,15})",
        # Nuevo formato (ej. ATRYS): "Documento: 24394278"
        r"Documento\s*:\s*(\d{6,15})",
        # Fallback: CC/guion/espacio seguido de numero
        r"\bCC[-/\s]+(\d{6,15})\b",
    )

    def extract(self, text: str) -> str | None:
        for pattern in self._PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                candidate = normalize_document_number(match.group(1))
                if candidate and not is_probable_mobile_number(candidate):
                    return candidate
        return None


class SaludTotalPdxPatientNameExtractor(PatientNameExtractorContract):
    """
    Extrae el nombre del paciente del PDX de Salud Total.

    Dos formatos:
    1. SGIRD: "NOMBRES Y APELLIDOS: PABLO EMILIO RIOS SANCHEZ"
    2. Lab externo: "Nombre: ROSALBINA TAMAYO MOSQUERA" seguido de otro campo
    """

    _PATTERNS: tuple[str, ...] = (
        r"NOMBRES\s+Y\s+APELLIDOS\s*:\s*([^\n]{5,100})",
        r"Nombre\s*:\s*([A-Za-z\xc0-\xff ]{5,100})(?=\n|N[uú]|Iden|Tel|Edad|M[eé]|Empr)",
    )

    def extract(self, text: str) -> str | None:
        for pattern in self._PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                candidate = normalize_patient_name(match.group(1).strip())
                if candidate:
                    return candidate
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Parsers de Documento completos para Salud Total
# ─────────────────────────────────────────────────────────────────────────────

class SaludTotalCrcDocumentParser(BaseDocumentParser):
    """Parser para CRC de Salud Total: Recibo de Satisfaccion FO-GS-UM-06-HS."""

    doc_type = DocumentType.SOPORTE

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=SaludTotalCrcPatientDocumentExtractor(),
                patient_document_type_extractor=GenericPatientDocumentTypeExtractor(),
                patient_name_extractor=NoPatientNameExtractor(),
                regimen_extractor=SaludTotalCrcRegimenExtractor(),
                cups_extractor=NoCupsExtractor(),
                metadata_extractor=EmptyMetadataExtractor(),
            )
        )


class SaludTotalPdeDocumentParser(BaseDocumentParser):
    """
    Parser para PDE de Salud Total.

    Maneja el documento multi-pagina que combina:
    - Consulta ADRES BDUA (pagina 1)
    - Uno o varios Direccionamientos de Salud Total (paginas siguientes)
    - O el portal transaccional de Salud Total
    """

    doc_type = DocumentType.AUTORIZACION

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=SaludTotalPdePatientDocumentExtractor(),
                patient_document_type_extractor=GenericPatientDocumentTypeExtractor(),
                patient_name_extractor=NoPatientNameExtractor(),
                regimen_extractor=SaludTotalPdeRegimenExtractor(),
                cups_extractor=SaludTotalPdeCupsExtractor(),
                metadata_extractor=EmptyMetadataExtractor(),
            )
        )


class SaludTotalPdxDocumentParser(BaseDocumentParser):
    """
    Parser para PDX de Salud Total.

    Soporta:
    - SGIRD RESULTADOS POCT (Horizonte Social)
    - Resultados de laboratorio externo (COLCAN, etc.)
    """

    doc_type = DocumentType.ADICIONAL

    def __init__(self) -> None:
        super().__init__(
            DocumentFieldExtractionPipeline(
                patient_document_extractor=SaludTotalPdxPatientDocumentExtractor(),
                patient_document_type_extractor=GenericPatientDocumentTypeExtractor(),
                patient_name_extractor=NoPatientNameExtractor(),
                regimen_extractor=NoRegimenExtractor(),
                cups_extractor=NoCupsExtractor(),
                metadata_extractor=EmptyMetadataExtractor(),
            )
        )
