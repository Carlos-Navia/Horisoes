from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from auditoria_pdf.batch import PdfCaseScanner

try:
    import fitz  # type: ignore
except Exception:  # pragma: no cover
    fitz = None


@unittest.skipIf(fitz is None, "PyMuPDF no disponible")
class PdfCaseScannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.addCleanup(self.temp_dir.cleanup)
        self.scanner = PdfCaseScanner()

    def test_groups_by_case_id_and_prefers_files_with_annotations(self) -> None:
        self._create_pdf(
            self.root / "FEV" / "FEV_901011395_FVEP1001.pdf",
            with_highlight=True,
        )
        self._create_pdf(
            self.root / "PDE" / "PDE_901011395_FVEP1001.pdf",
            with_highlight=True,
        )
        self._create_pdf(
            self.root / "CRC" / "CRC_901011395_FVEP1001.pdf",
            with_highlight=True,
        )
        self._create_pdf(
            self.root / "Nueva carpeta" / "FVEP1001" / "FEV_901011395_FVEP1001.pdf",
            with_highlight=False,
        )
        self._create_pdf(
            self.root / "Nueva carpeta" / "FVEP1001" / "PDE_901011395_FVEP1001.pdf",
            with_highlight=False,
        )
        self._create_pdf(
            self.root / "Nueva carpeta" / "FVEP1001" / "CRC_901011395_FVEP1001.pdf",
            with_highlight=False,
        )

        folder_map = self.scanner.find_case_folders(self.root)
        self.assertIn(self.root / "FVEP1001", folder_map)

        selected_paths = folder_map[self.root / "FVEP1001"]
        selected_parents = sorted(path.parent.name for path in selected_paths)
        self.assertEqual(selected_parents, ["CRC", "FEV", "PDE"])

    def test_falls_back_to_parent_folder_when_names_are_not_parseable(self) -> None:
        self._create_pdf(self.root / "caso_a" / "archivo_a.pdf", with_highlight=False)
        self._create_pdf(self.root / "caso_b" / "archivo_b.pdf", with_highlight=False)

        folder_map = self.scanner.find_case_folders(self.root)
        self.assertIn(self.root / "caso_a", folder_map)
        self.assertIn(self.root / "caso_b", folder_map)

    def test_ignores_backup_pdf_unidos_folder(self) -> None:
        self._create_pdf(
            self.root / "FVEP1001" / "FEV_901011395_FVEP1001.pdf",
            with_highlight=False,
        )
        self._create_pdf(
            self.root / "FVEP1001" / "PDE_901011395_FVEP1001.pdf",
            with_highlight=False,
        )
        self._create_pdf(
            self.root / "BACKUP_PDF_UNIDOS" / "FVEP1001" / "VAL.pdf",
            with_highlight=False,
        )

        folder_map = self.scanner.find_case_folders(self.root)

        self.assertIn(self.root / "FVEP1001", folder_map)
        self.assertNotIn(self.root / "BACKUP_PDF_UNIDOS" / "FVEP1001", folder_map)

    def _create_pdf(self, path: Path, with_highlight: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "CC 12345678")

        if with_highlight:
            for rect in page.search_for("12345678"):
                page.add_highlight_annot(rect)

        document.save(str(path))
        document.close()


if __name__ == "__main__":
    unittest.main()
