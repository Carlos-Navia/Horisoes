from __future__ import annotations

from abc import ABC, abstractmethod
import unicodedata

from auditoria_pdf.domain import AuditContext, DocumentType, RuleResult
from auditoria_pdf.parsing.common import normalize_patient_name


def _normalize_text(value: str | None) -> str | None:
    if not value:
        return None
    without_accents = "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )
    return " ".join(without_accents.upper().split())


def _normalize_regimen(value: str | None) -> str | None:
    token = _normalize_text(value)
    if not token:
        return None
    if "SUBSIDI" in token:
        return "SUBSIDIADO"
    if "CONTRIBUT" in token:
        return "CONTRIBUTIVO"
    return None


def _find_document(context: AuditContext, doc_type: DocumentType):
    document = context.get_mandatory(doc_type)
    if document is not None:
        return document

    for candidate in context.additional_documents:
        if candidate.doc_type == doc_type:
            return candidate
    return None


class AuditRule(ABC):
    rule_id: str
    description: str

    @abstractmethod
    def evaluate(self, context: AuditContext) -> RuleResult:
        raise NotImplementedError


class FileSetComplianceRule(AuditRule):
    rule_id = "R0_ESTRUCTURA_LOTE"
    description = "Validar estructura del lote: FEV obligatorio y al menos otro PDF permitido."

    REQUIRED = (
        DocumentType.FACTURA,
    )

    def evaluate(self, context: AuditContext) -> RuleResult:
        total_parsed = len(context.all_documents())
        effective_min_pdfs = max(context.min_pdfs, 2)
        missing_required = [
            doc_type.value
            for doc_type in self.REQUIRED
            if context.get_mandatory(doc_type) is None
        ]
        factura = context.get_mandatory(DocumentType.FACTURA)
        has_companion_pdf = (
            factura is not None
            and any(doc.source_path != factura.source_path for doc in context.all_documents())
        )

        details: list[str] = []
        if total_parsed < effective_min_pdfs or total_parsed > context.max_pdfs:
            details.append(
                f"Cantidad invalida de PDFs: {total_parsed}. Permitido: {effective_min_pdfs}-{context.max_pdfs}."
            )
        if missing_required:
            details.append(
                f"Faltan documentos obligatorios: {', '.join(missing_required)}."
            )
        if factura is not None and not has_companion_pdf:
            details.append(
                "Debe existir al menos un PDF adicional permitido junto a FEV."
            )
        if not details:
            details.append("Estructura del lote valida.")

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            passed=len(details) == 1 and details[0] == "Estructura del lote valida.",
            expected=(
                f"{effective_min_pdfs}-{context.max_pdfs} PDFs con FEV obligatorio y "
                "al menos un adicional (PDE/CRC/HEV/HAO/PDX u otro permitido)"
            ),
            actual=(
                "total="
                f"{total_parsed}, obligatorios="
                + ",".join(
                    doc_type.value
                    for doc_type in sorted(
                        context.mandatory_documents.keys(), key=lambda d: d.value
                    )
                )
                + ", "
                f"adicionales={len(context.additional_documents)}"
            ),
            details=details,
        )


class CupsMatchRule(AuditRule):
    rule_id = "R1_CODIGO_FEV_VS_PDE"
    description = "Validar que el codigo/CUPS en FEV coincida con el codigo/CUPS en PDE."

    def evaluate(self, context: AuditContext) -> RuleResult:
        factura = _find_document(context, DocumentType.FACTURA)
        autorizacion = _find_document(context, DocumentType.AUTORIZACION)

        if not factura:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                passed=False,
                details=["Falta FEV para ejecutar la comparacion."],
            )

        if not autorizacion:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                passed=True,
                expected="N/A",
                actual="N/A",
                details=[
                    "No se encontro PDE; comparacion de codigo/CUPS omitida porque PDE es opcional."
                ],
            )

        cups_factura = factura.cups_codes
        cups_autorizacion = autorizacion.cups_codes

        if not cups_factura:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                passed=False,
                details=["No se detecto codigo/CUPS en FEV."],
            )
        if not cups_autorizacion:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                passed=False,
                details=["No se detecto codigo/CUPS en PDE."],
            )

        missing_in_pde = sorted(cups_factura - cups_autorizacion)
        extra_in_pde = sorted(cups_autorizacion - cups_factura)
        passed = len(missing_in_pde) == 0 and len(extra_in_pde) == 0

        details: list[str] = []
        if missing_in_pde:
            details.append(
                f"Codigos en FEV sin soporte en PDE: {', '.join(missing_in_pde)}."
            )
        if extra_in_pde:
            details.append(
                f"Codigos en PDE no presentes en FEV: {', '.join(extra_in_pde)}."
            )
        if not details:
            details.append("Codigo/CUPS consistente entre FEV y PDE.")

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            passed=passed,
            expected=", ".join(sorted(cups_autorizacion)),
            actual=", ".join(sorted(cups_factura)),
            details=details,
        )


class CupsMatchSkippedRule(AuditRule):
    rule_id = CupsMatchRule.rule_id
    description = CupsMatchRule.description

    def __init__(self, eps_name: str, reason: str = "regla de negocio") -> None:
        self._eps_name = eps_name
        self._reason = reason

    def evaluate(self, context: AuditContext) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            passed=True,
            expected="N/A",
            actual="N/A",
            details=[
                "Comparacion de codigo/CUPS omitida para "
                f"{self._eps_name} por {self._reason}."
            ],
        )


class PatientDocumentConsistencyRule(AuditRule):
    rule_id = "R2_DOCUMENTO_FEV_VS_TODOS"
    description = (
        "Verificar que el documento o nombre del paciente en FEV coincida contra todos los demas documentos del lote."
    )

    def evaluate(self, context: AuditContext) -> RuleResult:
        factura = _find_document(context, DocumentType.FACTURA)
        if not factura:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                passed=False,
                details=["No existe FEV para tomar documento de referencia."],
            )

        reference_document = factura.patient_document
        reference_name = normalize_patient_name(factura.patient_name)
        if not reference_document and not reference_name:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                passed=False,
                details=[
                    "No se pudo extraer documento ni nombre del paciente en FEV (referencia)."
                ],
            )

        targets = [
            doc
            for doc in context.all_documents()
            if doc.source_path != factura.source_path
        ]
        if not targets:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                passed=True,
                expected=self._format_identity(reference_document, reference_name),
                actual=f"FEV:{self._format_identity(reference_document, reference_name)}",
                details=["No hay documentos adicionales para comparar; regla omitida."],
            )

        details: list[str] = []
        mismatches: list[str] = []
        actual_tokens = [f"FEV:{self._format_identity(reference_document, reference_name)}"]

        for doc in targets:
            value = doc.patient_document
            name = normalize_patient_name(doc.patient_name)
            actual_tokens.append(f"{doc.prefix}:{self._format_identity(value, name)}")

            document_matches = (
                bool(reference_document) and bool(value) and value == reference_document
            )
            name_matches = bool(reference_name) and bool(name) and name == reference_name

            if document_matches or name_matches:
                if name_matches and not document_matches:
                    details.append(
                        f"Coincidencia por nombre exacto en {doc.source_path.name}: {name}."
                    )
                continue

            if not value and not name:
                mismatches.append(f"{doc.prefix}=N/D")
                details.append(
                    f"No se pudo extraer documento ni nombre del paciente en {doc.source_path.name}."
                )
                continue

            mismatches.append(f"{doc.prefix}={self._format_identity(value, name)}")
            details.append(
                "Diferencia detectada: "
                f"FEV={self._format_identity(reference_document, reference_name)} vs "
                f"{doc.prefix}={self._format_identity(value, name)} "
                f"({doc.source_path.name})."
            )

        passed = len(mismatches) == 0
        if passed:
            details.append(
                "Identidad del paciente consistente entre FEV y todos los demas PDFs."
            )

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            passed=passed,
            expected=self._format_identity(reference_document, reference_name),
            actual=" | ".join(actual_tokens),
            details=details,
        )

    def _format_identity(self, document: str | None, name: str | None) -> str:
        parts: list[str] = []
        if document:
            parts.append(f"doc={document}")
        if name:
            parts.append(f"nombre={name}")
        return ", ".join(parts) if parts else "N/D"


class RegimenConsistencyRule(AuditRule):
    rule_id = "R3_REGIMEN_FEV_VS_PDE"
    description = "Verificar regimen del paciente entre FEV y PDE (solo Subsidiado o Contributivo)."

    def evaluate(self, context: AuditContext) -> RuleResult:
        factura = _find_document(context, DocumentType.FACTURA)
        autorizacion = _find_document(context, DocumentType.AUTORIZACION)

        if not factura:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                passed=False,
                details=["Falta FEV para comparar regimen."],
            )

        if not autorizacion:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                passed=True,
                expected="N/A",
                actual="N/A",
                details=["No se encontro PDE; comparacion de regimen omitida porque PDE es opcional."],
            )

        regimen_factura = _normalize_regimen(factura.regimen)
        regimen_autorizacion = _normalize_regimen(autorizacion.regimen)

        if not regimen_factura or not regimen_autorizacion:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                passed=False,
                expected=regimen_autorizacion,
                actual=regimen_factura,
                details=[
                    "No se pudo extraer literalmente SUBSIDIADO/CONTRIBUTIVO en FEV o PDE.",
                    f"FEV: {factura.regimen or 'N/D'} | PDE: {autorizacion.regimen or 'N/D'}",
                ],
            )

        passed = regimen_factura == regimen_autorizacion
        details = (
            ["Regimen consistente entre FEV y PDE."]
            if passed
            else ["Regimen inconsistente entre FEV y PDE."]
        )

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            passed=passed,
            expected=regimen_autorizacion,
            actual=regimen_factura,
            details=details,
        )
