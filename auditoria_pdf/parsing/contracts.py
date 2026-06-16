from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PatientDocumentExtractorContract(ABC):
    @abstractmethod
    def extract(self, text: str) -> str | None:
        raise NotImplementedError


class PatientDocumentTypeExtractorContract(ABC):
    @abstractmethod
    def extract(self, text: str) -> str | None:
        raise NotImplementedError


class PatientNameExtractorContract(ABC):
    @abstractmethod
    def extract(self, text: str) -> str | None:
        raise NotImplementedError


class RegimenExtractorContract(ABC):
    @abstractmethod
    def extract(self, text: str) -> str | None:
        raise NotImplementedError


class CupsExtractorContract(ABC):
    @abstractmethod
    def extract(self, text: str) -> set[str]:
        raise NotImplementedError


class MetadataExtractorContract(ABC):
    @abstractmethod
    def extract(self, text: str) -> dict[str, Any]:
        raise NotImplementedError
