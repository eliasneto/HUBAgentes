import csv
import io
import json
from itertools import zip_longest
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
from zipfile import ZIP_DEFLATED, ZipFile

from apps.processamentos.models import ProcessingOutputFormat


class OutputRendererError(Exception):
    pass


def render_output_file(parsed_output, output_format, output_basename):
    normalized_basename = Path(output_basename).stem or "resultado"
    if output_format == ProcessingOutputFormat.JSON:
        return (
            f"{normalized_basename}.json",
            json.dumps(parsed_output, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    if output_format == ProcessingOutputFormat.TXT:
        return f"{normalized_basename}.txt", _render_txt_bytes(parsed_output)
    if output_format == ProcessingOutputFormat.CSV:
        return f"{normalized_basename}.csv", _render_csv_bytes(parsed_output)
    if output_format == ProcessingOutputFormat.XLSX:
        return f"{normalized_basename}.xlsx", _render_xlsx_bytes(parsed_output)
    if output_format == ProcessingOutputFormat.PDF:
        return f"{normalized_basename}.pdf", _render_pdf_bytes(parsed_output)
    raise OutputRendererError("Formato de saida nao suportado pelo renderer.")


def _rows_from_output(parsed_output):
    if isinstance(parsed_output, list):
        if all(isinstance(item, dict) for item in parsed_output):
            return parsed_output
        return [{"valor": json.dumps(item, ensure_ascii=False)} for item in parsed_output]

    if isinstance(parsed_output, dict):
        list_entry = next(
            (
                (key, value)
                for key, value in parsed_output.items()
                if isinstance(value, list) and all(isinstance(item, dict) for item in value)
            ),
            None,
        )
        if list_entry is not None:
            list_key, list_value = list_entry
            shared_columns = {
                key: _stringify_value(value)
                for key, value in parsed_output.items()
                if key != list_key and not isinstance(value, (list, dict))
            }
            return [{**shared_columns, **item} for item in list_value]
        return [{"campo": key, "valor": _stringify_value(value)} for key, value in parsed_output.items()]

    return [{"valor": _stringify_value(parsed_output)}]


def _render_csv_bytes(parsed_output):
    rows = _rows_from_output(parsed_output)
    headers = _collect_headers(rows)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow({header: _stringify_value(row.get(header, "")) for header in headers})
    return stream.getvalue().encode("utf-8-sig")


def _render_txt_bytes(parsed_output):
    pretty_text = json.dumps(parsed_output, ensure_ascii=False, indent=2)
    return pretty_text.encode("utf-8")


def _render_xlsx_bytes(parsed_output):
    rows = _rows_from_output(parsed_output)
    headers = _collect_headers(rows)
    table_rows = [headers]
    for row in rows:
        table_rows.append([row.get(header, "") for header in headers])

    workbook = io.BytesIO()
    with ZipFile(workbook, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml())
        archive.writestr("_rels/.rels", _root_rels_xml())
        archive.writestr("xl/workbook.xml", _workbook_xml())
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml())
        archive.writestr("xl/worksheets/sheet1.xml", _worksheet_xml(table_rows))
    return workbook.getvalue()


def _render_pdf_bytes(parsed_output):
    pretty_json = json.dumps(parsed_output, ensure_ascii=False, indent=2)
    lines = [line[:120] for line in pretty_json.splitlines()] or ["{}"]
    pages = list(_chunked(lines, 42))

    objects = []
    font_object_id = 1
    page_object_ids = []
    content_object_ids = []

    for index, page_lines in enumerate(pages, start=0):
        content_object_id = 2 + (index * 2)
        page_object_id = content_object_id + 1
        content_object_ids.append(content_object_id)
        page_object_ids.append(page_object_id)
        objects.append((content_object_id, _pdf_content_stream(page_lines)))

    pages_object_id = 2 + (len(pages) * 2)
    catalog_object_id = pages_object_id + 1

    objects.insert(0, (font_object_id, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))
    for content_object_id, page_object_id in zip(content_object_ids, page_object_ids):
        page_payload = (
            f"<< /Type /Page /Parent {pages_object_id} 0 R /MediaBox [0 0 595 842] "
            f"/Contents {content_object_id} 0 R /Resources << /Font << /F1 {font_object_id} 0 R >> >> >>"
        ).encode("latin-1")
        objects.append((page_object_id, page_payload))

    kids = " ".join(f"{page_id} 0 R" for page_id in page_object_ids)
    objects.append((pages_object_id, f"<< /Type /Pages /Count {len(page_object_ids)} /Kids [{kids}] >>".encode("latin-1")))
    objects.append((catalog_object_id, f"<< /Type /Catalog /Pages {pages_object_id} 0 R >>".encode("latin-1")))
    objects = sorted(objects, key=lambda item: item[0])

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, payload in objects:
        offsets.append(buffer.tell())
        buffer.write(f"{object_id} 0 obj\n".encode("latin-1"))
        buffer.write(payload)
        buffer.write(b"\nendobj\n")

    xref_offset = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode("latin-1"))
    buffer.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_object_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("latin-1")
    )
    return buffer.getvalue()


def _pdf_content_stream(lines):
    commands = ["BT", "/F1 10 Tf", "50 790 Td", "14 TL"]
    for line in lines:
        safe_text = (
            line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        )
        commands.append(f"({safe_text}) Tj")
        commands.append("T*")
    commands.append("ET")
    content = "\n".join(commands).encode("latin-1", errors="replace")
    return f"<< /Length {len(content)} >>\nstream\n".encode("latin-1") + content + b"\nendstream"


def _content_types_xml():
    return """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""


def _root_rels_xml():
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _workbook_xml():
    return """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Resultado" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""


def _workbook_rels_xml():
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""


def _worksheet_xml(table_rows):
    rows_xml = []
    for row_index, row in enumerate(table_rows, start=1):
        cells_xml = []
        for col_index, value in enumerate(row, start=1):
            cell_ref = f"{_excel_column_name(col_index)}{row_index}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells_xml.append(f'<c r="{cell_ref}"><v>{value}</v></c>')
                continue
            safe_value = xml_escape(_stringify_value(value))
            cells_xml.append(
                f'<c r="{cell_ref}" t="inlineStr"><is><t>{safe_value}</t></is></c>'
            )
        rows_xml.append(f'<row r="{row_index}">{"".join(cells_xml)}</row>')

    return (
        """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>"""
        + "".join(rows_xml)
        + """</sheetData>
</worksheet>"""
    )


def _excel_column_name(index):
    result = []
    while index:
        index, remainder = divmod(index - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))


def _collect_headers(rows):
    headers = []
    for row in rows:
        for key in row.keys():
            if key not in headers:
                headers.append(key)
    return headers or ["valor"]


def _stringify_value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def _chunked(iterable, size):
    args = [iter(iterable)] * size
    for chunk in zip_longest(*args, fillvalue=None):
        yield [item for item in chunk if item is not None]
