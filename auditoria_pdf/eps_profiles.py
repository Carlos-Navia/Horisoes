from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from auditoria_pdf.domain import DocumentType
from auditoria_pdf.parsing import BaseDocumentParser
from auditoria_pdf.parsing.document_parsers import NuevaEpsPdeDocumentParser, SanitasPdeDocumentParser
from auditoria_pdf.parsing.salud_total_parsers import (
    SaludTotalCrcDocumentParser,
    SaludTotalPdeDocumentParser,
    SaludTotalPdxDocumentParser,
)
from auditoria_pdf.rules import (
    AuditRule,
    CupsMatchRule,
    CupsMatchSkippedRule,
    FileSetComplianceRule,
    PatientDocumentConsistencyRule,
    RegimenConsistencyRule,
)


class EpsProfileKey(str, Enum):
    COOSALUD = "coosalud"
    NUEVA_EPS = "nueva_eps"
    SANITAS = "sanitas"
    SALUD_TOTAL = "salud_total"


class EpsAuditProfile(ABC):
    key: EpsProfileKey
    display_name: str

    @abstractmethod
    def build_rules(self) -> list[AuditRule]:
        raise NotImplementedError

    def page_limits(self) -> dict[DocumentType, int | None]:
        return {
            DocumentType.FACTURA: None,
            DocumentType.AUTORIZACION: None,
            DocumentType.SOPORTE: None,
            DocumentType.VALIDADOR: None,
            DocumentType.ADICIONAL: None,
        }

    def render_fallback_types(self) -> set[DocumentType]:
        return {
            DocumentType.FACTURA,
            DocumentType.AUTORIZACION,
            DocumentType.SOPORTE,
            DocumentType.VALIDADOR,
            DocumentType.ADICIONAL,
        }

    def parser_overrides(self) -> dict[DocumentType, BaseDocumentParser]:
        return {
            DocumentType.SOPORTE: SaludTotalCrcDocumentParser(),
            DocumentType.ADICIONAL: SaludTotalPdxDocumentParser(),
        }


def _build_shared_rules(cups_rule: AuditRule) -> list[AuditRule]:
    return [
        FileSetComplianceRule(),
        cups_rule,
        PatientDocumentConsistencyRule(),
        RegimenConsistencyRule(),
    ]


class CoosaludAuditProfile(EpsAuditProfile):
    key = EpsProfileKey.COOSALUD
    display_name = "COOSALUD"

    def build_rules(self) -> list[AuditRule]:
        return _build_shared_rules(
            CupsMatchSkippedRule(eps_name=self.display_name),
        )

    def parser_overrides(self) -> dict[DocumentType, BaseDocumentParser]:
        from auditoria_pdf.parsing.coosalud_parsers import (
            CoosaludCrcDocumentParser,
            CoosaludHevDocumentParser,
            CoosaludPdeDocumentParser,
            CoosaludPdxDocumentParser,
        )

        overrides = super().parser_overrides()
        overrides[DocumentType.SOPORTE] = CoosaludCrcDocumentParser()
        overrides[DocumentType.AUTORIZACION] = CoosaludPdeDocumentParser()
        overrides[DocumentType.VALIDADOR] = CoosaludHevDocumentParser()
        overrides[DocumentType.ADICIONAL] = CoosaludPdxDocumentParser()
        return overrides


class NuevaEpsAuditProfile(EpsAuditProfile):
    key = EpsProfileKey.NUEVA_EPS
    display_name = "NUEVA EPS"

    def build_rules(self) -> list[AuditRule]:
        return _build_shared_rules(CupsMatchRule())

    def parser_overrides(self) -> dict[DocumentType, BaseDocumentParser]:
        overrides = super().parser_overrides()
        overrides[DocumentType.AUTORIZACION] = NuevaEpsPdeDocumentParser()
        return overrides


class SanitasAuditProfile(EpsAuditProfile):
    key = EpsProfileKey.SANITAS
    display_name = "SANITAS"

    def build_rules(self) -> list[AuditRule]:
        return _build_shared_rules(CupsMatchRule())

    def parser_overrides(self) -> dict[DocumentType, BaseDocumentParser]:
        overrides = super().parser_overrides()
        overrides[DocumentType.AUTORIZACION] = SanitasPdeDocumentParser()
        return overrides


class SaludTotalAuditProfile(EpsAuditProfile):
    """
    Perfil de auditoria para SALUD TOTAL EPS.

    Documentos esperados:
      - FEV: Factura Electronica de Venta (igual para todas las EPS)
      - CRC: Recibo de Satisfaccion del Servicio de Salud en Unidad Movil
             (Codigo FO-GS-UM-06-HS)
      - PDE: Consulta ADRES BDUA + Direccionamiento Salud Total
             (puede contener multiples paginas con uno o varios servicios)
      - PDX: Resultado SGIRD / laboratorio externo (variable por IPS)
    """

    key = EpsProfileKey.SALUD_TOTAL
    display_name = "SALUD TOTAL"

    def build_rules(self) -> list[AuditRule]:
        # Salud Total: solo valida estructura del lote, documento del paciente y regimen.
        # La revision de CUPS y la comparacion de nombres NO aplican para este modelo.
        return [
            FileSetComplianceRule(),
            PatientDocumentConsistencyRule(),
            RegimenConsistencyRule(),
        ]

    def parser_overrides(self) -> dict[DocumentType, BaseDocumentParser]:
        overrides = super().parser_overrides()
        overrides[DocumentType.AUTORIZACION] = SaludTotalPdeDocumentParser()
        return overrides


class EpsAuditProfileFactory:
    def __init__(self) -> None:
        self._profiles: dict[EpsProfileKey, EpsAuditProfile] = {
            EpsProfileKey.COOSALUD: CoosaludAuditProfile(),
            EpsProfileKey.NUEVA_EPS: NuevaEpsAuditProfile(),
            EpsProfileKey.SANITAS: SanitasAuditProfile(),
            EpsProfileKey.SALUD_TOTAL: SaludTotalAuditProfile(),
        }

    def create(self, eps: str | EpsProfileKey) -> EpsAuditProfile:
        key = self._normalize_key(eps)
        return self._profiles[key]

    def create_for_coosalud(self) -> EpsAuditProfile:
        return self._profiles[EpsProfileKey.COOSALUD]

    def create_for_nueva_eps(self) -> EpsAuditProfile:
        return self._profiles[EpsProfileKey.NUEVA_EPS]

    def create_for_sanitas(self) -> EpsAuditProfile:
        return self._profiles[EpsProfileKey.SANITAS]

    def create_for_salud_total(self) -> EpsAuditProfile:
        return self._profiles[EpsProfileKey.SALUD_TOTAL]

    def _normalize_key(self, eps: str | EpsProfileKey) -> EpsProfileKey:
        if isinstance(eps, EpsProfileKey):
            return eps

        token = str(eps).strip().lower().replace("-", "_").replace(" ", "_")
        aliases: dict[str, EpsProfileKey] = {
            "1": EpsProfileKey.COOSALUD,
            "coosalud": EpsProfileKey.COOSALUD,
            "2": EpsProfileKey.NUEVA_EPS,
            "nueva_eps": EpsProfileKey.NUEVA_EPS,
            "nuevaeps": EpsProfileKey.NUEVA_EPS,
            "3": EpsProfileKey.SANITAS,
            "sanitas": EpsProfileKey.SANITAS,
            "4": EpsProfileKey.SALUD_TOTAL,
            "salud_total": EpsProfileKey.SALUD_TOTAL,
            "saludtotal": EpsProfileKey.SALUD_TOTAL,
            "salud total": EpsProfileKey.SALUD_TOTAL,
        }
        selected = aliases.get(token)
        if selected is None:
            supported = ", ".join(item.value for item in EpsProfileKey)
            raise ValueError(
                f"EPS no soportada: {eps}. Valores permitidos: {supported}."
            )
        return selected
