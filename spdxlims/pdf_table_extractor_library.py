from __future__ import annotations

import csv
import bisect
import json
import os
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from tempfile import gettempdir
from xml.sax.saxutils import escape

import fitz

SUPPORTED_EXTENSIONS = {'.pdf'}


@dataclass(slots=True)
class PdfRecord:
    name: str
    relative_path: str
    full_path: str
    original_source: str
    imported_at: str
    page_count: int


@dataclass(slots=True)
class DetectedTable:
    document_path: str
    page_index: int
    page_label: str
    table_index: int
    bbox: tuple[float, float, float, float]
    rows: int
    columns: int
    data: list[list[str]]
    method: str


@dataclass(slots=True)
class ManualGridProposal:
    bbox: tuple[float, float, float, float]
    region_size: tuple[float, float]
    row_guides: list[float]
    column_guides: list[float]


@dataclass(slots=True)
class ExtractionLogEntry:
    created_at: str
    action: str
    document_name: str
    document_path: str
    page_label: str
    rows: int
    columns: int
    method: str
    destination: str
    detail: str


class PdfLibrary:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.documents_dir = self.root_dir / 'working_pdf'
        self.index_path = self.root_dir / 'working_pdf_index.json'
        self.extraction_log_path = self.root_dir / 'extraction_log.json'
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.index = self._load_index()

    def list_documents(self) -> list[PdfRecord]:
        self.index = self._load_index()
        current = self._current_document_path()
        if current is None:
            return []
        relative_path = current.relative_to(self.documents_dir).as_posix()
        meta = self.index.get(relative_path, {})
        return [
            PdfRecord(
                name=current.stem,
                relative_path=relative_path,
                full_path=str(current),
                original_source=meta.get('original_source', ''),
                imported_at=meta.get('imported_at', ''),
                page_count=self._safe_page_count(current),
            )
        ]

    def import_files(self, file_paths: list[str]) -> int:
        valid_sources = []
        for raw_path in file_paths:
            source = Path(raw_path)
            if source.is_file() and source.suffix.lower() in SUPPORTED_EXTENSIONS:
                valid_sources.append(source)
        if not valid_sources:
            return 0

        source = valid_sources[-1]
        self._reset_working_document()
        target = self.documents_dir / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        self._update_index(target, str(source))
        self._save_index()
        return 1

    def import_folder(self, folder_path: str) -> int:
        return 0

    def delete_document(self, full_path: str) -> None:
        source = Path(full_path)
        if not source.exists():
            return

        relative_path = source.relative_to(self.documents_dir).as_posix()
        source.unlink()
        self.index.pop(relative_path, None)
        self._save_index()
        self._prune_empty_parents(source.parent)

    def detect_tables(self, full_path: str) -> list[DetectedTable]:
        document = fitz.open(full_path)
        try:
            tables: list[DetectedTable] = []
            for page_index in range(document.page_count):
                tables.extend(self._detect_tables_on_loaded_page(document.load_page(page_index), full_path, page_index))
            return tables
        finally:
            document.close()

    def detect_tables_on_page(self, full_path: str, page_index: int) -> list[DetectedTable]:
        document = fitz.open(full_path)
        try:
            return self._detect_tables_on_loaded_page(document.load_page(page_index), full_path, page_index)
        finally:
            document.close()

    def detect_tables_in_region(self, full_path: str, page_index: int, bbox: tuple[float, float, float, float]) -> list[DetectedTable]:
        document = fitz.open(full_path)
        try:
            page = document.load_page(page_index)
            clip = fitz.Rect(*bbox).normalize()
            tables: list[DetectedTable] = []

            finder = page.find_tables(clip=clip)
            for table_index, table in enumerate(finder.tables, start=1):
                data = self._normalize_matrix(table.extract())
                if not data:
                    continue
                tables.append(
                    DetectedTable(
                        document_path=full_path,
                        page_index=page_index,
                        page_label=str(page_index + 1),
                        table_index=table_index,
                        bbox=tuple(float(value) for value in table.bbox),
                        rows=len(data),
                        columns=max((len(row) for row in data), default=0),
                        data=data,
                        method='manual',
                    )
                )

            if tables:
                return tables

            data = self._extract_words_grid(page, clip)
            if not data:
                return []

            return [
                DetectedTable(
                    document_path=full_path,
                    page_index=page_index,
                    page_label=str(page_index + 1),
                    table_index=1,
                    bbox=(clip.x0, clip.y0, clip.x1, clip.y1),
                    rows=len(data),
                    columns=max((len(row) for row in data), default=0),
                    data=data,
                    method='manual-grid',
                )
            ]
        finally:
            document.close()

    def propose_manual_grid(self, full_path: str, page_index: int, bbox: tuple[float, float, float, float]) -> ManualGridProposal:
        document = fitz.open(full_path)
        try:
            page = document.load_page(page_index)
            clip = fitz.Rect(*bbox).normalize()
            words = self._extract_region_words(page, clip)
            row_guides, column_guides = self._propose_guides_from_words(words, clip)
            return ManualGridProposal(
                bbox=(clip.x0, clip.y0, clip.x1, clip.y1),
                region_size=(clip.width, clip.height),
                row_guides=row_guides,
                column_guides=column_guides,
            )
        finally:
            document.close()

    def render_region(self, full_path: str, page_index: int, bbox: tuple[float, float, float, float], max_width: int = 1200) -> tuple[bytes, tuple[float, float]]:
        document = fitz.open(full_path)
        try:
            page = document.load_page(page_index)
            clip = fitz.Rect(*bbox).normalize()
            scale = min(3.0, max(1.0, max_width / max(clip.width, 1)))
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
            return pixmap.tobytes('png'), (clip.width, clip.height)
        finally:
            document.close()

    def extract_table_with_guides(
        self,
        full_path: str,
        page_index: int,
        bbox: tuple[float, float, float, float],
        row_guides: list[float],
        column_guides: list[float],
    ) -> DetectedTable | None:
        document = fitz.open(full_path)
        try:
            page = document.load_page(page_index)
            clip = fitz.Rect(*bbox).normalize()
            rows = self._normalize_guides(row_guides, clip.height)
            columns = self._normalize_guides(column_guides, clip.width)
            if len(rows) < 2 or len(columns) < 2:
                return None
            data = self._extract_cells_from_guides(page, clip, rows, columns)
            if not any(any(value.strip() for value in row) for row in data):
                return None
            return DetectedTable(
                document_path=full_path,
                page_index=page_index,
                page_label=str(page_index + 1),
                table_index=1,
                bbox=(clip.x0, clip.y0, clip.x1, clip.y1),
                rows=len(data),
                columns=max((len(row) for row in data), default=0),
                data=self._normalize_matrix(data),
                method='manual-grid',
            )
        finally:
            document.close()

    def render_page(self, full_path: str, page_index: int, max_width: int = 1100) -> tuple[bytes, tuple[float, float]]:
        document = fitz.open(full_path)
        try:
            page = document.load_page(page_index)
            scale = min(2.0, max(1.0, max_width / max(page.rect.width, 1)))
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            return pixmap.tobytes('png'), (page.rect.width, page.rect.height)
        finally:
            document.close()

    def _detect_tables_on_loaded_page(self, page: fitz.Page, full_path: str, page_index: int) -> list[DetectedTable]:
        tables: list[DetectedTable] = []
        finder = page.find_tables()
        for table_index, table in enumerate(finder.tables, start=1):
            data = self._normalize_matrix(table.extract())
            if not data:
                continue
            rows = len(data)
            columns = max((len(row) for row in data), default=0)
            tables.append(
                DetectedTable(
                    document_path=full_path,
                    page_index=page_index,
                    page_label=str(page_index + 1),
                    table_index=table_index,
                    bbox=tuple(float(value) for value in table.bbox),
                    rows=rows,
                    columns=columns,
                    data=data,
                    method='auto',
                )
            )
        if tables and max((table.rows for table in tables), default=0) > 1:
            return tables

        fallback_table = self._detect_full_page_grid_table(page, full_path, page_index)
        if fallback_table is not None and fallback_table.rows > max((table.rows for table in tables), default=0):
            return [fallback_table]
        return tables

    def _detect_full_page_grid_table(self, page: fitz.Page, full_path: str, page_index: int) -> DetectedTable | None:
        clip = page.rect
        words = self._extract_region_words(page, clip)
        if not words:
            return None
        row_guides, column_guides = self._propose_guides_from_words(words, clip)
        rows = self._normalize_guides(row_guides, clip.height)
        columns = self._normalize_guides(column_guides, clip.width)
        if len(rows) < 2 or len(columns) < 2:
            return None
        data = self._extract_cells_from_guides(page, clip, rows, columns)
        normalized = self._normalize_matrix(data)
        if not normalized:
            return None
        return DetectedTable(
            document_path=full_path,
            page_index=page_index,
            page_label=str(page_index + 1),
            table_index=1,
            bbox=(clip.x0, clip.y0, clip.x1, clip.y1),
            rows=len(normalized),
            columns=max((len(row) for row in normalized), default=0),
            data=normalized,
            method='manual-grid',
        )

    def export_table_csv(self, table: DetectedTable, destination: str, delimiter: str = ',') -> None:
        with open(destination, 'w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.writer(handle, delimiter=delimiter)
            writer.writerows(table.data)

    def export_table_xlsx(self, table: DetectedTable, destination: str) -> None:
        rows = table.data or [['']]
        worksheet_xml = self._build_worksheet_xml(rows)
        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Table 1" sheetId="1" r:id="rId1"/></sheets></workbook>'
        )
        workbook_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/>'
            '</Relationships>'
        )
        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            '</Relationships>'
        )
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '</Types>'
        )
        styles_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border/></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
            '</styleSheet>'
        )

        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('[Content_Types].xml', content_types)
            archive.writestr('_rels/.rels', root_rels)
            archive.writestr('xl/workbook.xml', workbook_xml)
            archive.writestr('xl/_rels/workbook.xml.rels', workbook_rels)
            archive.writestr('xl/worksheets/sheet1.xml', worksheet_xml)
            archive.writestr('xl/styles.xml', styles_xml)

    def export_table_docx(self, table: DetectedTable, destination: str) -> None:
        rows = table.data or [['']]
        document_xml = self._build_word_document_xml(rows)
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '</Types>'
        )
        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>'
            '</Relationships>'
        )
        document_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/>'
            '</Relationships>'
        )
        styles_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
            '<w:name w:val="Normal"/>'
            '</w:style>'
            '</w:styles>'
        )

        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('[Content_Types].xml', content_types)
            archive.writestr('_rels/.rels', root_rels)
            archive.writestr('word/document.xml', document_xml)
            archive.writestr('word/_rels/document.xml.rels', document_rels)
            archive.writestr('word/styles.xml', styles_xml)

    def list_extraction_logs(self) -> list[ExtractionLogEntry]:
        try:
            raw = json.loads(self.extraction_log_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        entries: list[ExtractionLogEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            entries.append(
                ExtractionLogEntry(
                    created_at=str(item.get('created_at', '')),
                    action=str(item.get('action', '')),
                    document_name=str(item.get('document_name', '')),
                    document_path=str(item.get('document_path', '')),
                    page_label=str(item.get('page_label', '')),
                    rows=int(item.get('rows', 0) or 0),
                    columns=int(item.get('columns', 0) or 0),
                    method=str(item.get('method', '')),
                    destination=str(item.get('destination', '')),
                    detail=str(item.get('detail', '')),
                )
            )
        return entries

    def append_extraction_log(
        self,
        action: str,
        document_path: str,
        page_label: str = '',
        rows: int = 0,
        columns: int = 0,
        method: str = '',
        destination: str = '',
        detail: str = '',
    ) -> None:
        entries = self.list_extraction_logs()
        entries.insert(
            0,
            ExtractionLogEntry(
                created_at=datetime.now().isoformat(timespec='seconds'),
                action=action,
                document_name=Path(document_path).name if document_path else '',
                document_path=document_path,
                page_label=page_label,
                rows=rows,
                columns=columns,
                method=method,
                destination=destination,
                detail=detail,
            ),
        )
        serialized = [
            {
                'created_at': entry.created_at,
                'action': entry.action,
                'document_name': entry.document_name,
                'document_path': entry.document_path,
                'page_label': entry.page_label,
                'rows': entry.rows,
                'columns': entry.columns,
                'method': entry.method,
                'destination': entry.destination,
                'detail': entry.detail,
            }
            for entry in entries[:250]
        ]
        self.extraction_log_path.write_text(json.dumps(serialized, indent=2), encoding='utf-8')

    def _build_worksheet_xml(self, rows: list[list[str]]) -> str:
        row_parts: list[str] = []
        for row_index, row in enumerate(rows, start=1):
            cell_parts: list[str] = []
            for column_index, value in enumerate(row, start=1):
                cell_ref = f'{self._xlsx_column_name(column_index)}{row_index}'
                safe_value = escape(value or '')
                cell_parts.append(
                    f'<c r="{cell_ref}" t="inlineStr"><is><t xml:space="preserve">{safe_value}</t></is></c>'
                )
            row_parts.append(f'<row r="{row_index}">{"".join(cell_parts)}</row>')

        sheet_data = ''.join(row_parts) if row_parts else '<row r="1"><c r="A1" t="inlineStr"><is><t></t></is></c></row>'
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{sheet_data}</sheetData>'
            '</worksheet>'
        )

    def _build_word_document_xml(self, rows: list[list[str]]) -> str:
        table_rows: list[str] = []
        for row in rows:
            cells: list[str] = []
            for value in row:
                safe_value = escape(value or '')
                cells.append(
                    '<w:tc>'
                    '<w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>'
                    '<w:p><w:r><w:t xml:space="preserve">'
                    f'{safe_value}'
                    '</w:t></w:r></w:p>'
                    '</w:tc>'
                )
            table_rows.append('<w:tr>' + ''.join(cells) + '</w:tr>')

        table_xml = (
            '<w:tbl>'
            '<w:tblPr>'
            '<w:tblBorders>'
            '<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
            '<w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
            '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
            '<w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
            '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
            '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
            '</w:tblBorders>'
            '</w:tblPr>'
            + ''.join(table_rows) +
            '</w:tbl>'
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            f'{table_xml}'
            '<w:sectPr/>'
            '</w:body>'
            '</w:document>'
        )

    def _extract_words_grid(self, page: fitz.Page, clip: fitz.Rect) -> list[list[str]]:
        words = self._extract_region_words(page, clip)
        if not words:
            return []

        heights = [word['y1'] - word['y0'] for word in words]
        widths = [word['x1'] - word['x0'] for word in words]
        row_tolerance = max(4.0, median(heights) * 0.65 if heights else 6.0)
        column_tolerance = max(14.0, median(widths) * 1.25 if widths else 18.0)
        words = self._focus_words_on_dominant_block(words, row_tolerance, column_tolerance)

        grouped_rows = self._group_words_into_rows(words, row_tolerance)
        column_centers = self._collect_column_anchors(grouped_rows, column_tolerance)
        if not column_centers:
            column_centers = [clip.x0 + ((clip.x1 - clip.x0) / 2.0)]

        matrix: list[list[str]] = []
        for row in grouped_rows:
            values = ['' for _ in column_centers]
            ordered_words = sorted(list(row['words']), key=lambda item: item['x0'])
            for word in ordered_words:
                anchor_x = float(word['x0'])
                column_index = self._nearest_anchor(column_centers, anchor_x)
                existing = values[column_index]
                values[column_index] = f'{existing} {word["text"]}'.strip() if existing else word['text']
            if any(value.strip() for value in values):
                matrix.append(values)

        return self._normalize_matrix(matrix)

    def _extract_region_words(self, page: fitz.Page, clip: fitz.Rect) -> list[dict[str, float | str]]:
        raw_words = page.get_text('words', clip=clip, sort=True)
        if not raw_words:
            return []
        return [
            {
                'x0': float(item[0]),
                'y0': float(item[1]),
                'x1': float(item[2]),
                'y1': float(item[3]),
                'text': str(item[4]).strip(),
            }
            for item in raw_words
            if str(item[4]).strip()
        ]

    def _propose_guides_from_words(self, words: list[dict[str, float | str]], clip: fitz.Rect) -> tuple[list[float], list[float]]:
        if not words:
            return [0.0, clip.height], [0.0, clip.width]

        heights = [float(word['y1']) - float(word['y0']) for word in words]
        widths = [float(word['x1']) - float(word['x0']) for word in words]
        row_tolerance = max(4.0, median(heights) * 0.65 if heights else 6.0)
        column_tolerance = max(14.0, median(widths) * 1.25 if widths else 18.0)
        all_grouped_rows = self._group_words_into_rows(words, row_tolerance)
        all_column_gutters = self._collect_column_gutters(all_grouped_rows, widths, column_tolerance)
        words = self._focus_words_on_dominant_block(words, row_tolerance, column_tolerance)

        grouped_rows = self._group_words_into_rows(words, row_tolerance)
        column_centers = self._collect_column_anchors(grouped_rows, column_tolerance)
        if not column_centers:
            column_centers = [clip.x0 + (clip.width / 2.0)]

        row_centers = self._collect_driver_row_centers(grouped_rows, column_centers)
        row_guides = self._centers_to_guides([center - clip.y0 for center in row_centers], clip.height)
        column_gutters = all_column_gutters or self._collect_column_gutters(grouped_rows, widths, column_tolerance)
        if column_gutters:
            column_guides = self._normalize_guides([gutter - clip.x0 for gutter in column_gutters], clip.width)
        else:
            column_guides = self._centers_to_guides([center - clip.x0 for center in column_centers], clip.width)
        return row_guides, column_guides

    def _group_words_into_rows(self, words: list[dict[str, float | str]], row_tolerance: float) -> list[dict[str, object]]:
        grouped_rows: list[dict[str, object]] = []
        for word in sorted(words, key=lambda item: ((float(item['y0']) + float(item['y1'])) / 2.0, float(item['x0']))):
            center_y = (float(word['y0']) + float(word['y1'])) / 2.0
            if not grouped_rows:
                grouped_rows.append({'center_y': center_y, 'words': [word]})
                continue
            last_row = grouped_rows[-1]
            if abs(center_y - float(last_row['center_y'])) <= row_tolerance:
                row_words = list(last_row['words'])
                row_words.append(word)
                count = len(row_words)
                last_row['center_y'] = ((float(last_row['center_y']) * (count - 1)) + center_y) / count
                last_row['words'] = row_words
            else:
                grouped_rows.append({'center_y': center_y, 'words': [word]})
        return grouped_rows

    def _collect_column_anchors(self, grouped_rows: list[dict[str, object]], tolerance: float) -> list[float]:
        if not grouped_rows:
            return []

        clusters: list[dict[str, object]] = []
        for row_index, row in enumerate(grouped_rows):
            ordered_words = sorted(list(row['words']), key=lambda item: float(item['x0']))
            for word in ordered_words:
                anchor_x = float(word['x0'])
                match_index = self._match_anchor([float(cluster['anchor']) for cluster in clusters], anchor_x, tolerance)
                if match_index is None:
                    clusters.append({'anchor': anchor_x, 'count': 1, 'rows': {row_index}})
                    continue
                cluster = clusters[match_index]
                count = int(cluster['count']) + 1
                cluster['anchor'] = ((float(cluster['anchor']) * int(cluster['count'])) + anchor_x) / count
                cluster['count'] = count
                cluster_rows = set(cluster['rows'])
                cluster_rows.add(row_index)
                cluster['rows'] = cluster_rows

        min_row_hits = max(2, min(4, round(len(grouped_rows) * 0.25)))
        recurring = sorted(float(cluster['anchor']) for cluster in clusters if len(set(cluster['rows'])) >= min_row_hits)
        if recurring:
            return recurring
        return sorted(float(cluster['anchor']) for cluster in clusters)

    def _focus_words_on_dominant_block(
        self,
        words: list[dict[str, float | str]],
        row_tolerance: float,
        column_tolerance: float,
    ) -> list[dict[str, float | str]]:
        if len(words) < 8:
            return words

        grouped_rows = self._group_words_into_rows(words, row_tolerance)
        clusters = self._collect_anchor_clusters(grouped_rows, column_tolerance)
        if len(clusters) < 3:
            return words

        min_row_hits = max(2, min(4, round(len(grouped_rows) * 0.25)))
        candidate_clusters = [cluster for cluster in clusters if len(set(cluster['rows'])) >= min_row_hits]
        if len(candidate_clusters) < 2:
            return words

        block = self._select_dominant_anchor_block(candidate_clusters, column_tolerance)
        if len(block) < 2:
            return words

        pad = max(column_tolerance, 18.0)
        left = min(float(cluster['anchor']) for cluster in block) - pad
        right = max(float(cluster['anchor']) for cluster in block) + pad
        filtered = [
            word
            for word in words
            if float(word['x1']) >= left and float(word['x0']) <= right
        ]
        filtered_rows = self._group_words_into_rows(filtered, row_tolerance)
        if len(filtered) < 6 or len(filtered_rows) < 2:
            return words
        return filtered

    def _collect_anchor_clusters(self, grouped_rows: list[dict[str, object]], tolerance: float) -> list[dict[str, object]]:
        clusters: list[dict[str, object]] = []
        for row_index, row in enumerate(grouped_rows):
            ordered_words = sorted(list(row['words']), key=lambda item: float(item['x0']))
            for word in ordered_words:
                anchor_x = float(word['x0'])
                match_index = self._match_anchor([float(cluster['anchor']) for cluster in clusters], anchor_x, tolerance)
                if match_index is None:
                    clusters.append({'anchor': anchor_x, 'count': 1, 'rows': {row_index}})
                    continue
                cluster = clusters[match_index]
                count = int(cluster['count']) + 1
                cluster['anchor'] = ((float(cluster['anchor']) * int(cluster['count'])) + anchor_x) / count
                cluster['count'] = count
                cluster_rows = set(cluster['rows'])
                cluster_rows.add(row_index)
                cluster['rows'] = cluster_rows
        return sorted(clusters, key=lambda cluster: float(cluster['anchor']))

    def _collect_driver_row_centers(self, grouped_rows: list[dict[str, object]], column_centers: list[float]) -> list[float]:
        if not grouped_rows:
            return []
        if len(grouped_rows) <= 2 or len(column_centers) <= 1:
            return [float(row['center_y']) for row in grouped_rows]

        primary_limit = max(1, len(column_centers) - 1)
        driver_centers: list[float] = []
        for row in grouped_rows:
            occupied = set()
            for word in list(row['words']):
                anchor_x = float(word['x0'])
                occupied.add(self._nearest_anchor(column_centers, anchor_x))
            if any(index < primary_limit for index in occupied):
                driver_centers.append(float(row['center_y']))

        if len(driver_centers) >= max(2, int(len(grouped_rows) * 0.8)):
            return driver_centers
        return [float(row['center_y']) for row in grouped_rows]

    def _collect_column_gutters(
        self,
        grouped_rows: list[dict[str, object]],
        widths: list[float],
        tolerance: float,
    ) -> list[float]:
        if not grouped_rows:
            return []

        min_gap = max(18.0, (median(widths) * 0.9) if widths else 22.0)
        clusters: list[dict[str, object]] = []
        for row_index, row in enumerate(grouped_rows):
            ordered_words = sorted(list(row['words']), key=lambda item: float(item['x0']))
            for left_word, right_word in zip(ordered_words, ordered_words[1:]):
                gap = float(right_word['x0']) - float(left_word['x1'])
                if gap < min_gap:
                    continue
                gutter = float(left_word['x1']) + (gap / 2.0)
                match_index = self._match_anchor([float(cluster['anchor']) for cluster in clusters], gutter, tolerance)
                if match_index is None:
                    clusters.append({'anchor': gutter, 'rows': {row_index}})
                    continue
                cluster = clusters[match_index]
                cluster_rows = set(cluster['rows'])
                count = len(cluster_rows)
                cluster['anchor'] = ((float(cluster['anchor']) * count) + gutter) / (count + 1)
                cluster_rows.add(row_index)
                cluster['rows'] = cluster_rows

        min_row_hits = max(2, min(4, round(len(grouped_rows) * 0.2)))
        gutters = [
            float(cluster['anchor'])
            for cluster in clusters
            if len(set(cluster['rows'])) >= min_row_hits
        ]
        return sorted(gutters)

    def _centers_to_guides(self, centers: list[float], extent: float) -> list[float]:
        if not centers:
            return [0.0, extent]
        ordered = sorted(max(0.0, min(center, extent)) for center in centers)
        guides = [0.0]
        for left, right in zip(ordered, ordered[1:]):
            guides.append((left + right) / 2.0)
        guides.append(extent)
        return self._normalize_guides(guides, extent)

    def _normalize_guides(self, guides: list[float], extent: float) -> list[float]:
        if extent <= 0:
            return [0.0, 1.0]
        values = [0.0, extent]
        values.extend(max(0.0, min(float(guide), extent)) for guide in guides if 0.0 < float(guide) < extent)
        unique: list[float] = []
        for value in sorted(values):
            if not unique or abs(unique[-1] - value) > 1.0:
                unique.append(value)
        if len(unique) < 2:
            return [0.0, extent]
        return unique

    def _select_dominant_anchor_block(self, clusters: list[dict[str, object]], tolerance: float) -> list[dict[str, object]]:
        if not clusters:
            return []

        gap_threshold = max(48.0, tolerance * 2.5)
        blocks: list[list[dict[str, object]]] = [[clusters[0]]]
        for cluster in clusters[1:]:
            previous = blocks[-1][-1]
            gap = float(cluster['anchor']) - float(previous['anchor'])
            if gap > gap_threshold:
                blocks.append([cluster])
            else:
                blocks[-1].append(cluster)

        def block_score(block: list[dict[str, object]]) -> float:
            span = max(36.0, float(block[-1]['anchor']) - float(block[0]['anchor']) + tolerance)
            row_hits = sum(len(set(cluster['rows'])) for cluster in block)
            anchor_center = (float(block[0]['anchor']) + float(block[-1]['anchor'])) / 2.0
            cluster_count = len(block)
            return (span * max(1, row_hits) * max(1, cluster_count)) - (anchor_center * 1.35)

        substantial = [block for block in blocks if len(block) >= 3]
        if substantial:
            return max(substantial, key=block_score)
        return max(blocks, key=block_score)

    def _extract_cells_from_guides(self, page: fitz.Page, clip: fitz.Rect, row_guides: list[float], column_guides: list[float]) -> list[list[str]]:
        words = self._extract_region_words(page, clip)
        row_count = max(0, len(row_guides) - 1)
        column_count = max(0, len(column_guides) - 1)
        cells: list[list[list[tuple[float, float, str]]]] = [
            [[] for _ in range(column_count)] for _ in range(row_count)
        ]
        for word in words:
            center_x = ((float(word['x0']) + float(word['x1'])) / 2.0) - clip.x0
            center_y = ((float(word['y0']) + float(word['y1'])) / 2.0) - clip.y0
            row_index = bisect.bisect_right(row_guides, center_y) - 1
            column_index = bisect.bisect_right(column_guides, center_x) - 1
            if 0 <= row_index < row_count and 0 <= column_index < column_count:
                cells[row_index][column_index].append((float(word['y0']), float(word['x0']), str(word['text'])))

        matrix: list[list[str]] = []
        for row in cells:
            values: list[str] = []
            for cell_words in row:
                ordered = [text for _y0, _x0, text in self._sort_cell_words(cell_words)]
                values.append(' '.join(ordered).strip())
            matrix.append(values)
        return matrix

    def _sort_cell_words(self, cell_words: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
        if len(cell_words) <= 1:
            return sorted(cell_words)

        ordered_words = sorted(cell_words, key=lambda item: (item[0], item[1]))
        line_tolerance = 1.5
        lines: list[list[tuple[float, float, str]]] = []
        line_centers: list[float] = []
        for word in ordered_words:
            y0, x0, text = word
            placed = False
            for index, center_y in enumerate(line_centers):
                if abs(y0 - center_y) <= line_tolerance:
                    lines[index].append((y0, x0, text))
                    count = len(lines[index])
                    line_centers[index] = ((center_y * (count - 1)) + y0) / count
                    placed = True
                    break
            if not placed:
                lines.append([(y0, x0, text)])
                line_centers.append(y0)

        sorted_lines = sorted(zip(line_centers, lines), key=lambda item: item[0])
        flattened: list[tuple[float, float, str]] = []
        for _center_y, line_words in sorted_lines:
            flattened.extend(sorted(line_words, key=lambda item: item[1]))
        return flattened

    def _match_anchor(self, anchors: list[float], candidate: float, tolerance: float) -> int | None:
        for index, anchor in enumerate(anchors):
            if abs(anchor - candidate) <= tolerance:
                return index
        return None

    def _nearest_anchor(self, anchors: list[float], candidate: float) -> int:
        distances = [abs(anchor - candidate) for anchor in anchors]
        return distances.index(min(distances))

    def _normalize_matrix(self, rows: list[list[object]] | None) -> list[list[str]]:
        if not rows:
            return []

        normalized: list[list[str]] = []
        width = 0
        for row in rows:
            values = [self._stringify_cell(value) for value in row]
            if any(value.strip() for value in values):
                normalized.append(values)
                width = max(width, len(values))

        if not normalized or width == 0:
            return []

        return [row + ['' for _ in range(width - len(row))] for row in normalized]

    def _stringify_cell(self, value: object) -> str:
        if value is None:
            return ''
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            return str(value)
        return str(value).strip()

    def _safe_page_count(self, path: Path) -> int:
        try:
            document = fitz.open(path)
            try:
                return document.page_count
            finally:
                document.close()
        except Exception:
            return 0

    def _current_document_path(self) -> Path | None:
        for path in sorted(self.documents_dir.rglob('*')):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                return path
        return None

    def _reset_working_document(self) -> None:
        if self.documents_dir.exists():
            shutil.rmtree(self.documents_dir, ignore_errors=True)
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.index = {}

    def _unique_target_folder(self, base_dir: Path) -> Path:
        if not base_dir.exists():
            return base_dir

        counter = 2
        while True:
            candidate = base_dir.with_name(f'{base_dir.name}_{counter}')
            if not candidate.exists():
                return candidate
            counter += 1

    def _unique_target_path(self, base_path: Path) -> Path:
        if not base_path.exists():
            return base_path

        counter = 2
        while True:
            candidate = base_path.with_name(f'{base_path.stem}_{counter}{base_path.suffix}')
            if not candidate.exists():
                return candidate
            counter += 1

    def _load_index(self) -> dict[str, dict[str, str]]:
        if not self.index_path.exists():
            return {}

        try:
            data = json.loads(self.index_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return {}

        return data if isinstance(data, dict) else {}

    def _save_index(self) -> None:
        self.index_path.write_text(json.dumps(self.index, indent=2), encoding='utf-8')

    def _update_index(self, stored_path: Path, original_source: str) -> None:
        relative_path = stored_path.relative_to(self.documents_dir).as_posix()
        self.index[relative_path] = {
            'original_source': original_source,
            'imported_at': datetime.now().isoformat(timespec='seconds'),
        }

    def _prune_empty_parents(self, start_dir: Path) -> None:
        current = start_dir
        while current != self.documents_dir and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def _xlsx_column_name(self, index: int) -> str:
        letters: list[str] = []
        current = index
        while current > 0:
            current, remainder = divmod(current - 1, 26)
            letters.append(chr(65 + remainder))
        return ''.join(reversed(letters))


def default_export_directory() -> Path:
    export_dir = Path(gettempdir()) / 'SDXTableExtractor'
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir
