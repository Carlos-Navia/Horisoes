from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

from auditoria_pdf.batch import BatchAuditRunner, CaseAuditResult
from auditoria_pdf.domain import AuditReport
from auditoria_pdf.eps_profiles import EpsAuditProfile, EpsAuditProfileFactory, EpsProfileKey
from auditoria_pdf.excel_exporter import AuditExcelExporter
from auditoria_pdf.extractor import PdfTextExtractor
from auditoria_pdf.service import PdfAuditService


class CliArgumentFactory:
    def build(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Auditoria OOP de PDFs de facturacion en salud."
        )
        parser.add_argument(
            "--pdf-dir",
            type=Path,
            help="Carpeta con PDFs del mismo caso (se esperan 2 a 6 PDFs).",
        )
        parser.add_argument(
            "--root-dir",
            type=Path,
            help="Carpeta principal para modo masivo (busca subcarpetas con PDFs).",
        )
        parser.add_argument("--fev", type=Path, help="Ruta PDF factura (FEV_*.pdf).")
        parser.add_argument(
            "--pde", type=Path, help="Ruta PDF autorizacion opcional (PDE_*.pdf)."
        )
        parser.add_argument("--crc", type=Path, help="Ruta PDF soporte (CRC_*.pdf).")
        parser.add_argument(
            "--hev",
            type=Path,
            help="Ruta PDF adicional HEV (opcional, se trata como documento adicional).",
        )
        parser.add_argument(
            "--extra",
            type=Path,
            nargs="*",
            default=[],
            help="Rutas de PDFs adicionales (HAO, PDX, HEV u otros).",
        )
        parser.add_argument(
            "--eps",
            type=str,
            default=None,
            help=(
                "Perfil EPS a ejecutar. "
                "Valores: 1/coosalud, 2/nueva_eps, 3/sanitas, 4/salud_total. "
                "Si no se indica, se solicita antes de ejecutar."
            ),
        )
        parser.add_argument(
            "--tesseract-cmd",
            type=str,
            default=None,
            help="Ruta de tesseract.exe si no se detecta automaticamente.",
        )
        parser.add_argument(
            "--min-pdfs",
            type=int,
            default=2,
            help="Cantidad minima de PDFs permitida por lote (default: 2).",
        )
        parser.add_argument(
            "--max-pdfs",
            type=int,
            default=6,
            help="Cantidad maxima de PDFs permitida por lote (default: 6).",
        )
        parser.add_argument(
            "--output-json",
            type=Path,
            help="Archivo de salida para guardar reporte completo en JSON.",
        )
        parser.add_argument(
            "--output-excel",
            type=Path,
            default=None,
            help="Archivo Excel de salida (.xlsx). Si no se indica, se genera automaticamente en ./salidas.",
        )
        return parser


class PdfInputPathCollector:
    def collect(self, args: argparse.Namespace) -> list[Path]:
        paths: list[Path] = []

        if args.pdf_dir:
            paths.extend(sorted(args.pdf_dir.glob("*.pdf")))

        explicit_paths = [args.fev, args.pde, args.crc, args.hev]
        paths.extend(path for path in explicit_paths if path is not None)
        paths.extend(args.extra)

        return list(dict.fromkeys(paths))


class OutputPathBuilder:
    def build_single_excel_path(self, pdf_paths: list[Path]) -> Path:
        case_name = "auditoria"
        if pdf_paths:
            first_parent = pdf_paths[0].parent.name.strip()
            if first_parent:
                case_name = first_parent.replace(" ", "_")
        return Path("salidas") / f"reporte_{case_name}.xlsx"

    def build_batch_excel_path(self, root_dir: Path) -> Path:
        safe_name = root_dir.name.strip().replace(" ", "_") or "masivo"
        return root_dir / f"reporte_masivo_{safe_name}.xlsx"


class DirectoryPathResolver:
    _INVISIBLE_CHARACTERS = ("\ufeff", "\u200b", "\u200e", "\u200f")

    def parse(self, raw_value: str) -> Path:
        cleaned = raw_value.strip().strip('"').strip("'")
        for character in self._INVISIBLE_CHARACTERS:
            cleaned = cleaned.replace(character, "")

        if not cleaned:
            raise ValueError("Debes ingresar una ruta de carpeta principal.")

        expanded = os.path.expandvars(os.path.expanduser(cleaned))
        normalized = expanded.replace("/", "\\") if os.name == "nt" else expanded
        return Path(normalized)

    def resolve_existing_dir(self, path: Path) -> Path | None:
        candidates: list[Path] = []
        seen: set[str] = set()

        def add_candidate(candidate: Path) -> None:
            candidate_key = str(candidate)
            if candidate_key in seen:
                return
            seen.add(candidate_key)
            candidates.append(candidate)

        add_candidate(path)
        expanded = Path(os.path.expandvars(os.path.expanduser(str(path))))
        add_candidate(expanded)

        if os.name == "nt":
            raw = str(expanded).replace("/", "\\")
            add_candidate(Path(raw))
            long_raw = self._to_windows_long_path(raw)
            if long_raw:
                add_candidate(Path(long_raw))

        for candidate in candidates:
            try:
                if candidate.exists() and candidate.is_dir():
                    return candidate
            except OSError:
                continue

        return None

    def _to_windows_long_path(self, raw: str) -> str | None:
        if not raw:
            return None
        if raw.startswith("\\\\?\\"):
            return raw
        if raw.startswith("\\\\"):
            return f"\\\\?\\UNC\\{raw.lstrip('\\')}"
        if len(raw) >= 3 and raw[1] == ":":
            return f"\\\\?\\{raw}"
        return None


class RootDirectoryPrompter:
    def __init__(
        self, directory_path_resolver: DirectoryPathResolver | None = None
    ) -> None:
        self._directory_path_resolver = directory_path_resolver or DirectoryPathResolver()

    def prompt(self) -> Path:
        while True:
            raw = input("Ingrese la ruta de la carpeta principal: ")
            try:
                entered_path = self._directory_path_resolver.parse(raw)
            except ValueError as exc:
                print(str(exc))
                continue

            resolved = self._directory_path_resolver.resolve_existing_dir(entered_path)
            if resolved is not None:
                return resolved

            print(f"Ruta invalida para carpeta principal: {entered_path}")


class EpsMethodPrompter:
    _SUPPORTED = {item.value for item in EpsProfileKey}
    _ALIASES = {
        "1": EpsProfileKey.COOSALUD.value,
        "2": EpsProfileKey.NUEVA_EPS.value,
        "3": EpsProfileKey.SANITAS.value,
        "4": EpsProfileKey.SALUD_TOTAL.value,
        "coosalud": EpsProfileKey.COOSALUD.value,
        "nuevaeps": EpsProfileKey.NUEVA_EPS.value,
        "nueva_eps": EpsProfileKey.NUEVA_EPS.value,
        "nueva eps": EpsProfileKey.NUEVA_EPS.value,
        "sanitas": EpsProfileKey.SANITAS.value,
        "salud_total": EpsProfileKey.SALUD_TOTAL.value,
        "saludtotal": EpsProfileKey.SALUD_TOTAL.value,
        "salud total": EpsProfileKey.SALUD_TOTAL.value,
    }

    def normalize(self, value: str) -> str:
        raw = value.strip().strip('"').strip("'")
        token = raw.lower().replace("-", "_").replace(" ", "_")
        if token.endswith(")") and token[:-1].isdigit():
            token = token[:-1]
        if token.endswith(".") and token[:-1].isdigit():
            token = token[:-1]
        normalized = self._ALIASES.get(token, token)
        if normalized in self._SUPPORTED:
            return normalized
        raise ValueError(
            "Valor EPS invalido. Opciones: 1) COOSALUD, 2) NUEVA EPS, 3) SANITAS, 4) SALUD TOTAL."
        )

    def prompt(self) -> str:
        while True:
            print("Seleccione metodo EPS:")
            print("1) COOSALUD")
            print("2) NUEVA EPS")
            print("3) SANITAS")
            print("4) SALUD TOTAL")
            raw = input("Ingrese opcion [1/2/3/4]: ")
            try:
                return self.normalize(raw)
            except ValueError as exc:
                print(str(exc))


class AuditReportPrinter:
    def print(self, report: AuditReport) -> None:
        print("=" * 90)
        print("RESULTADO AUDITORIA:", "APROBADO" if report.success else "RECHAZADO")
        print("=" * 90)

        if report.errors:
            print("Errores de procesamiento:")
            for error in report.errors:
                print(f"  - {error}")
            print()

        print("Reglas:")
        for result in report.rule_results:
            status = "OK" if result.passed else "FAIL"
            print(f"  [{status}] {result.rule_id} - {result.description}")
            if result.expected is not None or result.actual is not None:
                print(f"     Esperado: {result.expected or 'N/D'}")
                print(f"     Actual:   {result.actual or 'N/D'}")
            for detail in result.details:
                print(f"     - {detail}")

        print()
        print("Datos extraidos por documento:")
        for parsed in sorted(report.parsed_documents, key=lambda item: item.source_path.name):
            cups = ", ".join(sorted(parsed.cups_codes)) if parsed.cups_codes else "N/D"
            print(f"  - {parsed.source_path.name} [{parsed.prefix}]")
            print(f"     Tipo interno:        {parsed.doc_type.value}")
            print(f"     Documento paciente:  {parsed.patient_document or 'N/D'}")
            print(f"     Nombre paciente:     {parsed.patient_name or 'N/D'}")
            print(f"     Tipo documento:      {parsed.patient_document_type or 'N/D'}")
            print(f"     Regimen:             {parsed.regimen or 'N/D'}")
            print(f"     Codigo/CUPS:         {cups}")


class JsonReportWriter:
    def write(self, payload: dict, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class AuditServiceFactory:
    def __init__(
        self,
        profile_factory: EpsAuditProfileFactory | None = None,
    ) -> None:
        self._profile_factory = profile_factory or EpsAuditProfileFactory()

    def create(self, args: argparse.Namespace) -> PdfAuditService:
        selected_eps = getattr(args, "eps", EpsProfileKey.COOSALUD.value)
        if selected_eps == EpsProfileKey.NUEVA_EPS.value:
            return self.create_for_nueva_eps(args)
        if selected_eps == EpsProfileKey.SANITAS.value:
            return self.create_for_sanitas(args)
        if selected_eps == EpsProfileKey.SALUD_TOTAL.value:
            return self.create_for_salud_total(args)
        if selected_eps == EpsProfileKey.COOSALUD.value:
            return self.create_for_coosalud(args)
        raise ValueError(
            "EPS no soportada: "
            f"{selected_eps}. Valores permitidos: {EpsProfileKey.COOSALUD.value}, "
            f"{EpsProfileKey.NUEVA_EPS.value}, {EpsProfileKey.SANITAS.value}, "
            f"{EpsProfileKey.SALUD_TOTAL.value}."
        )

    def create_for_coosalud(self, args: argparse.Namespace) -> PdfAuditService:
        profile = self._profile_factory.create_for_coosalud()
        return self._create_with_profile(args, profile)

    def create_for_nueva_eps(self, args: argparse.Namespace) -> PdfAuditService:
        profile = self._profile_factory.create_for_nueva_eps()
        return self._create_with_profile(args, profile)

    def create_for_sanitas(self, args: argparse.Namespace) -> PdfAuditService:
        profile = self._profile_factory.create_for_sanitas()
        return self._create_with_profile(args, profile)

    def create_for_salud_total(self, args: argparse.Namespace) -> PdfAuditService:
        profile = self._profile_factory.create_for_salud_total()
        return self._create_with_profile(args, profile)

    def _create_with_profile(
        self,
        args: argparse.Namespace,
        profile: EpsAuditProfile,
    ) -> PdfAuditService:
        extractor = PdfTextExtractor(tesseract_cmd=args.tesseract_cmd)
        return PdfAuditService(
            extractor=extractor,
            min_pdfs=args.min_pdfs,
            max_pdfs=args.max_pdfs,
            profile=profile,
        )


@dataclass(slots=True)
class BatchAuditSummary:
    approved: int
    rejected: int
    export_payload: list[tuple[str, AuditReport]]
    json_payload: list[dict]


class BatchResultAggregator:
    def aggregate(self, root_dir: Path, case_results: list[CaseAuditResult]) -> BatchAuditSummary:
        approved = 0
        rejected = 0
        export_payload: list[tuple[str, AuditReport]] = []
        json_payload: list[dict] = []

        for item in case_results:
            relative_folder = item.case_folder.relative_to(root_dir)
            folder_label = str(relative_folder).replace("\\", "/")
            if folder_label in {"", "."}:
                folder_label = item.case_folder.name

            if item.success:
                approved += 1
            else:
                rejected += 1

            export_payload.append((folder_label, item.report))
            json_payload.append(
                {
                    "carpeta": folder_label,
                    "pdf_count": len(item.pdf_paths),
                    "report": item.report.to_dict(),
                }
            )

        return BatchAuditSummary(
            approved=approved,
            rejected=rejected,
            export_payload=export_payload,
            json_payload=json_payload,
        )


class SingleAuditExecutor:
    def __init__(
        self,
        service_factory: AuditServiceFactory,
        report_printer: AuditReportPrinter,
        excel_exporter: AuditExcelExporter,
        output_path_builder: OutputPathBuilder,
        json_report_writer: JsonReportWriter,
    ) -> None:
        self._service_factory = service_factory
        self._report_printer = report_printer
        self._excel_exporter = excel_exporter
        self._output_path_builder = output_path_builder
        self._json_report_writer = json_report_writer

    def execute(self, args: argparse.Namespace, pdf_paths: list[Path]) -> int:
        print(f"Metodo EPS seleccionado: {args.eps}")
        service = self._service_factory.create(args)
        report = service.audit(pdf_paths)

        self._report_printer.print(report)

        excel_output = args.output_excel or self._output_path_builder.build_single_excel_path(
            pdf_paths
        )
        self._excel_exporter.export(report, excel_output)
        print()
        print(f"Reporte Excel guardado en: {excel_output}")

        if args.output_json:
            self._json_report_writer.write(report.to_dict(), args.output_json)
            print()
            print(f"Reporte JSON guardado en: {args.output_json}")

        return 0 if report.success else 2


class BatchAuditExecutor:
    def __init__(
        self,
        service_factory: AuditServiceFactory,
        excel_exporter: AuditExcelExporter,
        output_path_builder: OutputPathBuilder,
        json_report_writer: JsonReportWriter,
        batch_aggregator: BatchResultAggregator,
        directory_path_resolver: DirectoryPathResolver | None = None,
    ) -> None:
        self._service_factory = service_factory
        self._excel_exporter = excel_exporter
        self._output_path_builder = output_path_builder
        self._json_report_writer = json_report_writer
        self._batch_aggregator = batch_aggregator
        self._directory_path_resolver = directory_path_resolver or DirectoryPathResolver()

    def execute(self, args: argparse.Namespace, root_dir: Path) -> int:
        resolved_root_dir = self._directory_path_resolver.resolve_existing_dir(root_dir)
        if resolved_root_dir is None:
            raise ValueError(f"Ruta invalida para carpeta principal: {root_dir}")
        root_dir = resolved_root_dir

        print(f"Metodo EPS seleccionado: {args.eps}")
        service = self._service_factory.create(args)
        runner = BatchAuditRunner(service)
        case_results = runner.run(root_dir)

        if not case_results:
            raise ValueError(f"No se encontraron subcarpetas con PDFs en: {root_dir}")

        print("=" * 90)
        print(f"RESULTADO AUDITORIA MASIVA - CARPETA PRINCIPAL: {root_dir}")
        print("=" * 90)

        for item in case_results:
            relative_folder = item.case_folder.relative_to(root_dir)
            folder_label = str(relative_folder).replace("\\", "/")
            if folder_label in {"", "."}:
                folder_label = item.case_folder.name
            status = "APROBADO" if item.success else "RECHAZADO"
            print(
                f"[{status}] {folder_label} | PDFs: {len(item.pdf_paths)} | Errores: {len(item.report.errors)}"
            )

        summary = self._batch_aggregator.aggregate(root_dir, case_results)

        print("-" * 90)
        print(f"Total carpetas evaluadas: {len(case_results)}")
        print(f"Aprobadas: {summary.approved}")
        print(f"Rechazadas: {summary.rejected}")

        excel_output = args.output_excel or self._output_path_builder.build_batch_excel_path(
            root_dir
        )
        self._excel_exporter.export_many(summary.export_payload, excel_output)
        print(f"Reporte Excel consolidado guardado en: {excel_output}")

        if args.output_json:
            self._json_report_writer.write(
                {
                    "root_dir": str(root_dir),
                    "total_cases": len(case_results),
                    "approved": summary.approved,
                    "rejected": summary.rejected,
                    "cases": summary.json_payload,
                },
                args.output_json,
            )
            print(f"Reporte JSON consolidado guardado en: {args.output_json}")

        return 0 if summary.rejected == 0 else 2


class AuditCliApplication:
    def __init__(
        self,
        argument_factory: CliArgumentFactory | None = None,
        path_collector: PdfInputPathCollector | None = None,
        eps_method_prompter: EpsMethodPrompter | None = None,
        root_directory_prompter: RootDirectoryPrompter | None = None,
        single_executor: SingleAuditExecutor | None = None,
        batch_executor: BatchAuditExecutor | None = None,
    ) -> None:
        self._argument_factory = argument_factory or CliArgumentFactory()
        self._path_collector = path_collector or PdfInputPathCollector()
        self._eps_method_prompter = eps_method_prompter or EpsMethodPrompter()
        directory_path_resolver = DirectoryPathResolver()
        self._root_directory_prompter = root_directory_prompter or RootDirectoryPrompter(
            directory_path_resolver
        )

        service_factory = AuditServiceFactory()
        output_path_builder = OutputPathBuilder()
        json_report_writer = JsonReportWriter()
        excel_exporter = AuditExcelExporter()

        self._single_executor = single_executor or SingleAuditExecutor(
            service_factory=service_factory,
            report_printer=AuditReportPrinter(),
            excel_exporter=excel_exporter,
            output_path_builder=output_path_builder,
            json_report_writer=json_report_writer,
        )
        self._batch_executor = batch_executor or BatchAuditExecutor(
            service_factory=service_factory,
            excel_exporter=excel_exporter,
            output_path_builder=output_path_builder,
            json_report_writer=json_report_writer,
            batch_aggregator=BatchResultAggregator(),
            directory_path_resolver=directory_path_resolver,
        )

    def run(self, argv: list[str] | None = None) -> int:
        parser = self._argument_factory.build()
        args = parser.parse_args(argv)
        selected_eps = args.eps if args.eps is not None else self._eps_method_prompter.prompt()
        try:
            args.eps = self._eps_method_prompter.normalize(selected_eps)
        except ValueError as exc:
            parser.error(str(exc))

        # Configurar exporter segun EPS: Salud Total no usa columnas de nombre
        include_names = args.eps != EpsProfileKey.SALUD_TOTAL.value
        eps_exporter = AuditExcelExporter(include_name_columns=include_names)
        self._single_executor._excel_exporter = eps_exporter
        self._batch_executor._excel_exporter = eps_exporter

        pdf_paths = self._path_collector.collect(args)

        if args.min_pdfs < 2:
            parser.error("--min-pdfs debe ser >= 2.")
        if args.max_pdfs < args.min_pdfs:
            parser.error("--max-pdfs debe ser >= --min-pdfs.")

        single_inputs_provided = bool(pdf_paths)
        root_mode_provided = args.root_dir is not None

        if single_inputs_provided and root_mode_provided:
            parser.error(
                "Usa modo unico (pdf-dir/fev/pde/crc/extra) o modo masivo (root-dir), no ambos."
            )

        if single_inputs_provided:
            return self._single_executor.execute(args, pdf_paths)

        try:
            root_dir = args.root_dir or self._root_directory_prompter.prompt()
            return self._batch_executor.execute(args, root_dir)
        except ValueError as exc:
            parser.error(str(exc))
