from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from auditoria_pdf.domain import AuditReport
from auditoria_pdf.mupdf_runtime import configure_mupdf_logging
from auditoria_pdf.service import PdfAuditService

try:
    import fitz  # type: ignore
except Exception:  # pragma: no cover
    fitz = None
else:
    configure_mupdf_logging(fitz)


_NAME_WITH_CASE_ID_PATTERN = re.compile(
    r"^(?P<prefix>[A-Za-z0-9]+)_(?P<body>.+)_(?P<case_id>[A-Za-z0-9\-]+)$",
    re.IGNORECASE,
)
_NAME_SIMPLE_CASE_ID_PATTERN = re.compile(
    r"^(?P<prefix>[A-Za-z0-9]+)_(?P<case_id>[A-Za-z0-9\-]+)$",
    re.IGNORECASE,
)
_VALID_CASE_ID_PATTERN = re.compile(r"[^A-Za-z0-9\-]+")


def rename_cuv_file(pdf_path: Path, case_id: str) -> Path:
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"El archivo debe ser PDF: {pdf_path}")
    if not pdf_path.exists():
        raise FileNotFoundError(f"No existe archivo: {pdf_path}")

    normalized_case_id = _VALID_CASE_ID_PATTERN.sub("", case_id.strip().upper())
    if not normalized_case_id:
        raise ValueError("El case_id/CUV no es valido.")

    stem = pdf_path.stem
    if not stem.upper().startswith("CUV"):
        raise ValueError(f"El archivo no tiene prefijo CUV: {pdf_path.name}")

    match = _NAME_WITH_CASE_ID_PATTERN.match(stem)
    if match:
        new_stem = f"{match.group('prefix').upper()}_{match.group('body')}_{normalized_case_id}"
    else:
        simple_match = _NAME_SIMPLE_CASE_ID_PATTERN.match(stem)
        if simple_match:
            new_stem = f"{simple_match.group('prefix').upper()}_{normalized_case_id}"
        else:
            new_stem = f"CUV_{normalized_case_id}"

    target = pdf_path.with_name(f"{new_stem}{pdf_path.suffix}")
    if target == pdf_path:
        return pdf_path
    if target.exists():
        raise FileExistsError(f"Ya existe el archivo destino: {target}")

    return pdf_path.rename(target)


@dataclass(slots=True)
class CaseAuditResult:
    case_folder: Path
    pdf_paths: list[Path]
    report: AuditReport

    @property
    def success(self) -> bool:
        return self.report.success


class PdfCaseScanner:
    EXCLUDED_DIR_NAMES = frozenset(
        {
            ".git",
            ".tmp_tests",
            ".venv",
            ".venv_auditoria_ips",
            "__pycache__",
            "BACKUP_PDF_UNIDOS",
            "build",
            "build_script_original",
            "dist",
            "dist_script_original",
            "salidas",
            "spec_script_original",
        }
    )
    _NAME_PATTERN = re.compile(
        r"^(?P<prefix>[A-Za-z0-9]+)_.+_(?P<case_id>[A-Za-z0-9\-]+)$",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self._annotation_cache: dict[Path, bool] = {}

    def find_case_folders(self, root_dir: Path) -> dict[Path, list[Path]]:
        pdf_paths = sorted(self._iter_pdf_paths(root_dir))
        grouped_by_case_id = self._group_by_case_id(root_dir, pdf_paths)
        if grouped_by_case_id:
            return grouped_by_case_id
        return self._group_by_parent_folder(pdf_paths)

    def _iter_pdf_paths(self, root_dir: Path) -> list[Path]:
        pdf_paths: list[Path] = []
        for pdf_path in root_dir.rglob("*.pdf"):
            if self._is_excluded_path(root_dir, pdf_path):
                continue
            pdf_paths.append(pdf_path)
        return pdf_paths

    def _is_excluded_path(self, root_dir: Path, pdf_path: Path) -> bool:
        try:
            relative_parts = pdf_path.relative_to(root_dir).parts[:-1]
        except ValueError:
            relative_parts = pdf_path.parts[:-1]
        excluded = {part.upper() for part in self.EXCLUDED_DIR_NAMES}
        return any(part.upper() in excluded for part in relative_parts)

    def _group_by_parent_folder(self, pdf_paths: list[Path]) -> dict[Path, list[Path]]:
        grouped: dict[Path, list[Path]] = {}
        for pdf_path in pdf_paths:
            grouped.setdefault(pdf_path.parent, []).append(pdf_path)
        return dict(sorted(grouped.items(), key=lambda item: str(item[0]).upper()))

    def _group_by_case_id(self, root_dir: Path, pdf_paths: list[Path]) -> dict[Path, list[Path]]:
        case_prefix_map: dict[str, dict[str, list[Path]]] = {}
        parseable_files = 0

        for pdf_path in pdf_paths:
            parsed = self._parse_filename_tokens(pdf_path)
            if parsed is None:
                continue

            parseable_files += 1
            case_id, prefix = parsed
            case_prefix_map.setdefault(case_id, {}).setdefault(prefix, []).append(pdf_path)

        if parseable_files < max(4, int(len(pdf_paths) * 0.7)):
            return {}

        grouped: dict[Path, list[Path]] = {}
        for case_id, prefix_paths in case_prefix_map.items():
            if len(prefix_paths) < 2:
                continue

            selected_paths = [self._select_best_path(paths) for paths in prefix_paths.values()]
            grouped[root_dir / case_id] = sorted(selected_paths, key=lambda path: path.name.upper())

        if not grouped:
            return {}

        return dict(sorted(grouped.items(), key=lambda item: str(item[0]).upper()))

    def _parse_filename_tokens(self, pdf_path: Path) -> tuple[str, str] | None:
        match = self._NAME_PATTERN.match(pdf_path.stem)
        if not match:
            return None
        prefix = match.group("prefix").upper()
        case_id = match.group("case_id").upper()
        return case_id, prefix

    def _select_best_path(self, paths: list[Path]) -> Path:
        if len(paths) == 1:
            return paths[0]

        def sort_key(path: Path) -> tuple[int, int, str]:
            annotation_score = 1 if self._has_annotations(path) else 0
            return (-annotation_score, len(path.parts), str(path).upper())

        return sorted(paths, key=sort_key)[0]

    def _has_annotations(self, pdf_path: Path) -> bool:
        cached = self._annotation_cache.get(pdf_path)
        if cached is not None:
            return cached

        if fitz is None:
            self._annotation_cache[pdf_path] = False
            return False

        try:
            document = fitz.open(str(pdf_path))
        except Exception:
            self._annotation_cache[pdf_path] = False
            return False

        try:
            has_annotations = False
            for page in document:
                if page.first_annot is not None:
                    has_annotations = True
                    break
        finally:
            document.close()

        self._annotation_cache[pdf_path] = has_annotations
        return has_annotations


class BatchAuditRunner:
    def __init__(
        self, audit_service: PdfAuditService, scanner: PdfCaseScanner | None = None
    ) -> None:
        self.audit_service = audit_service
        self.scanner = scanner or PdfCaseScanner()

    def run(self, root_dir: Path) -> list[CaseAuditResult]:
        folder_map = self.scanner.find_case_folders(root_dir)
        results: list[CaseAuditResult] = []
        for folder, pdf_paths in folder_map.items():
            report = self.audit_service.audit(pdf_paths)
            results.append(
                CaseAuditResult(
                    case_folder=folder,
                    pdf_paths=pdf_paths,
                    report=report,
                )
            )
        return results
