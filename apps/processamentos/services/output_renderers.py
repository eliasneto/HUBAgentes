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
    workbook_sheets = _extract_workbook_sheets(parsed_output)
    if workbook_sheets:
        return workbook_sheets[0]["rows"]

    return _rows_from_generic_output(parsed_output)


def _rows_from_generic_output(parsed_output):
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
    if isinstance(parsed_output, str):
        return parsed_output.encode("utf-8")
    pretty_text = json.dumps(parsed_output, ensure_ascii=False, indent=2)
    return pretty_text.encode("utf-8")


def _render_xlsx_bytes(parsed_output):
    workbook_sheets = _extract_workbook_sheets(parsed_output)
    if not workbook_sheets:
        workbook_sheets = [
            {
                "name": "Resultado",
                "rows": _rows_from_generic_output(parsed_output),
            }
        ]

    workbook = io.BytesIO()
    with ZipFile(workbook, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml(len(workbook_sheets)))
        archive.writestr("_rels/.rels", _root_rels_xml())
        archive.writestr("xl/workbook.xml", _workbook_xml(workbook_sheets))
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            _workbook_rels_xml(len(workbook_sheets)),
        )
        for sheet_index, sheet in enumerate(workbook_sheets, start=1):
            rows = sheet["rows"]
            headers = _collect_headers(rows)
            data_rows = [[row.get(header, "") for header in headers] for row in rows]
            if len(headers) >= 2 and sheet.get("agrupar_primeira_coluna"):
                data_rows = _dedup_first_col(data_rows)
            table_rows = [headers] + data_rows
            archive.writestr(
                f"xl/worksheets/sheet{sheet_index}.xml",
                _worksheet_xml(table_rows),
            )
    return workbook.getvalue()


def _estruturar_como_texto(data, nivel=0):
    linhas = []
    indent = "  " * nivel
    if isinstance(data, dict):
        for chave, valor in data.items():
            rotulo = chave.replace("_", " ").upper() if nivel == 0 else chave.replace("_", " ").capitalize()
            if isinstance(valor, (dict, list)):
                linhas.append(f"{indent}{rotulo}:")
                linhas.extend(_estruturar_como_texto(valor, nivel + 1).splitlines())
            else:
                linhas.append(f"{indent}{rotulo}: {valor}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                linhas.extend(_estruturar_como_texto(item, nivel + 1).splitlines())
            else:
                linhas.append(f"{indent}- {item}")
    else:
        linhas.append(f"{indent}{data}")
    return "\n".join(linhas)


def _wrap_line(line, max_chars=90):
    if len(line) <= max_chars:
        return [line]
    stripped = line.lstrip()
    indent = line[: len(line) - len(stripped)]
    wrapped = []
    current = indent
    for word in stripped.split(" "):
        if current == indent:
            current += word
        elif len(current) + 1 + len(word) <= max_chars:
            current += " " + word
        else:
            wrapped.append(current)
            current = indent + word
    if current:
        wrapped.append(current)
    return wrapped or [line]


def _render_pdf_bytes(parsed_output):
    if isinstance(parsed_output, str):
        text = parsed_output
    elif isinstance(parsed_output, (dict, list)):
        text = _estruturar_como_texto(parsed_output)
    else:
        text = str(parsed_output)
    lines = []
    for raw_line in text.splitlines():
        lines.extend(_wrap_line(raw_line))
    if not lines:
        lines = [""]
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

    objects.insert(0, (font_object_id, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"))
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


def _extract_workbook_sheets(parsed_output):
    workbook_payload = parsed_output
    if isinstance(parsed_output, dict) and isinstance(parsed_output.get("arquivo"), dict):
        workbook_payload = parsed_output["arquivo"]

    if not isinstance(workbook_payload, dict):
        return []

    sheets_payload = workbook_payload.get("abas") or workbook_payload.get("sheets")
    if not isinstance(sheets_payload, list):
        return []

    workbook_sheets = []
    used_names = set()
    for index, sheet_payload in enumerate(sheets_payload, start=1):
        if not isinstance(sheet_payload, dict):
            continue

        raw_name = (
            sheet_payload.get("nome_aba")
            or sheet_payload.get("nome")
            or sheet_payload.get("name")
            or f"Resultado {index}"
        )
        sheet_name = _unique_sheet_name(raw_name, used_names)
        sheet_data = (
            sheet_payload.get("dados")
            or sheet_payload.get("linhas")
            or sheet_payload.get("rows")
            or []
        )
        workbook_sheets.append(
            {
                "name": sheet_name,
                "rows": _rows_from_generic_output(sheet_data),
                "agrupar_primeira_coluna": bool(sheet_payload.get("agrupar_primeira_coluna")),
            }
        )
    return workbook_sheets


def _unique_sheet_name(raw_name, used_names):
    base_name = _sanitize_sheet_name(raw_name)
    sheet_name = base_name
    counter = 2
    while sheet_name.lower() in used_names:
        suffix = f" {counter}"
        sheet_name = f"{base_name[:31 - len(suffix)]}{suffix}"
        counter += 1
    used_names.add(sheet_name.lower())
    return sheet_name


def _sanitize_sheet_name(raw_name):
    sanitized = str(raw_name or "Resultado").strip()
    for invalid_char in ("\\", "/", "?", "*", "[", "]", ":"):
        sanitized = sanitized.replace(invalid_char, "-")
    sanitized = sanitized.strip("'") or "Resultado"
    return sanitized[:31]


def _content_types_xml(sheet_count=1):
    worksheet_overrides = "".join(
        (
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        for index in range(1, sheet_count + 1)
    )
    return """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  """ + worksheet_overrides + """
</Types>"""


def _root_rels_xml():
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _workbook_xml(workbook_sheets=None):
    workbook_sheets = workbook_sheets or [{"name": "Resultado"}]
    sheets_xml = "".join(
        (
            f'<sheet name="{xml_escape(sheet["name"])}" '
            f'sheetId="{index}" r:id="rId{index}"/>'
        )
        for index, sheet in enumerate(workbook_sheets, start=1)
    )
    return """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>""" + sheets_xml + """</sheets>
</workbook>"""


def _workbook_rels_xml(sheet_count=1):
    relationships_xml = "".join(
        (
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
        for index in range(1, sheet_count + 1)
    )
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  """ + relationships_xml + """
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


def _dedup_first_col(data_rows):
    """Substitui valores iguais consecutivos na primeira coluna por string vazia.

    Cada valor de agrupamento aparece apenas na primeira linha do grupo,
    deixando as linhas seguintes com a célula em branco — padrão de tabela
    agrupada do Excel (ex.: parte/pergunta/resposta do prompt Aliança).
    """
    _sentinel = object()
    last_val = _sentinel
    result = []
    for row in data_rows:
        if not row:
            result.append(row)
            continue
        new_row = list(row)
        if new_row[0] == last_val:
            new_row[0] = ""
        else:
            last_val = new_row[0]
        result.append(new_row)
    return result


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
