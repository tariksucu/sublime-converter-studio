"""Conversions done in plain Python, with nothing installed: CSV ↔ JSON and subtitles.

Each converter reads the source file and writes the target file; it raises ConversionError with
a sentence for the user when the source is not what it should be.
"""

import json
import re


class ConversionError(Exception):
    """The file could not be converted; the message says why, in plain words."""


def _read_text(path):
    """A text file as UTF-8 (with or without BOM), UTF-16 with BOM, or else Windows-1252."""
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


def _write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


# -- CSV and JSON ------------------------------------------------------------------------------
#
# Nothing is dropped or changed on the way: every column gets a name of its own, numbers keep the
# digits they were written with (9007199254740993 stays exact), and keys keep their order. The
# Converter Studio extensions for VS Code, JetBrains IDEs and Neovim follow the same rules and run
# the same cases (tests/data-cases.json), so a file gives the same result in each.

_SEPARATORS = ",;\t|"


def _separator(text):
    """The field separator of a CSV: comma, semicolon, tab or |, whichever its first line uses most
    outside quotes (the earlier of them on a tie; a comma when there is none)."""
    counts = dict.fromkeys(_SEPARATORS, 0)
    quoted = False
    for char in text.lstrip("\ufeff").lstrip("\r\n"):
        if char == '"':
            quoted = not quoted
        elif not quoted and char in "\r\n":
            break
        elif not quoted and char in counts:
            counts[char] += 1
    best = ","
    for separator in _SEPARATORS[1:]:
        if counts[separator] > counts[best]:
            best = separator
    return best


def _parse_csv(text, separator):
    """The rows of a CSV (RFC 4180: quoted fields, doubled quotes, line breaks inside quotes)."""
    if text.startswith("\ufeff"):
        text = text[1:]
    rows, row, field = [], [], []
    quoted = was_quoted = False
    i, n = 0, len(text)
    while i < n:
        char = text[i]
        if quoted:
            if char != '"':
                field.append(char)
            elif i + 1 < n and text[i + 1] == '"':
                field.append('"')
                i += 1
            else:
                quoted = False
        elif char == '"' and not field and not was_quoted:
            quoted = was_quoted = True
        elif char == separator:
            row.append("".join(field))
            field, was_quoted = [], False
        elif char in "\r\n":
            if char == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append("".join(field))
            rows.append(row)
            row, field, was_quoted = [], [], False
        else:
            field.append(char)
        i += 1
    if quoted:
        raise ConversionError("The CSV file ends inside a quoted field.")
    if field or was_quoted or row:
        row.append("".join(field))
        rows.append(row)
    # Blank lines are not records.
    return [r for r in rows if r != [""]]


def _column_names(header, width):
    """A name for each of `width` columns, every one different, so that no value is lost:

    - the first column with a header name keeps it;
    - any other column (a repeated name, an empty header cell, a cell beyond the header) gets its
      header name, or column<N> (N counted from 1) when it has none, followed by _2, _3...: the
      first that no column has taken yet.

    `id,id` gives id, id_2; a header `column2` with a row `A,B` gives column2, column2_2.
    """
    names = [None] * width
    taken = set()
    for index, raw in enumerate(header):
        name = raw.strip(" \t\r\n")
        if name and name not in taken:
            names[index] = name
            taken.add(name)
    for index in range(width):
        if names[index] is not None:
            continue
        base = (header[index] if index < len(header) else "").strip(" \t\r\n") or "column%d" % (index + 1)
        name, n = base, 2
        while name in taken:
            name, n = "%s_%d" % (base, n), n + 1
        names[index] = name
        taken.add(name)
    return names


def csv_to_json(source, target):
    """A CSV file with a header row -> a JSON array of objects (values stay text). Every object has
    every column, in the file's order; a cell a row does not have is empty."""
    text = _read_text(source)
    rows = _parse_csv(text, _separator(text))
    if not rows:
        raise ConversionError("The CSV file is empty.")
    header, rows = rows[0], rows[1:]
    names = _column_names(header, max(len(row) for row in [header] + rows))
    records = [{name: (row[i] if i < len(row) else "") for i, name in enumerate(names)} for row in rows]
    _write_text(target, json.dumps(records, ensure_ascii=False, indent=2) + "\n")


class _Number:
    """A JSON number as the file writes it: its text is kept, so no digit is lost or changed."""

    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


def _no_constant(name):
    raise ValueError("%s is not a JSON value" % name)


def _compact(value):
    """A value as compact JSON (a list or object in a CSV cell), numbers as written."""
    if isinstance(value, _Number):
        return value.text
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ",".join(_compact(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(_compact(k) + ":" + _compact(v) for k, v in value.items()) + "}"
    return json.dumps(value, ensure_ascii=False)


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return _compact(value)


def _csv_field(text):
    """A CSV field, in double quotes when it holds a comma, a quote or a line break, or starts or ends
    with a space or tab."""
    if any(c in text for c in ',"\r\n') or text[:1] in (" ", "\t") or text[-1:] in (" ", "\t"):
        return '"' + text.replace('"', '""') + '"'
    return text


def json_to_csv(source, target):
    """A JSON array of objects (or one object, or an object holding one such array) -> CSV."""
    try:
        # Numbers keep their text: a float would change 0.1000000000000000055 and 1E400.
        data = json.loads(_read_text(source), parse_int=_Number, parse_float=_Number, parse_constant=_no_constant)
    except ValueError as error:
        raise ConversionError("The file is not valid JSON (%s)." % error)
    if isinstance(data, dict):
        # {"total": 2, "items": [{…}, {…}]}: the one array of objects is the table; any other
        # object is a single row.
        tables = [
            value
            for value in data.values()
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value)
        ]
        data = tables[0] if len(tables) == 1 else [data]
    if not isinstance(data, list) or not data:
        raise ConversionError('A table needs a JSON array of objects, such as [{"name": "Ada"}].')
    columns, seen = [], set()
    for item in data:
        if isinstance(item, dict):
            for key in item:
                if key not in seen:
                    seen.add(key)
                    columns.append(key)
    lines = []
    if columns:
        lines.append(columns)
        for item in data:
            if isinstance(item, dict):
                lines.append([_cell(item.get(key)) for key in columns])
            else:
                lines.append([_cell(item)] + [""] * (len(columns) - 1))
    else:
        # An array of plain values or of arrays.
        for item in data:
            lines.append([_cell(v) for v in item] if isinstance(item, list) else [_cell(item)])
    _write_text(target, "".join(",".join(_csv_field(c) for c in line) + "\r\n" for line in lines))


# -- subtitles ---------------------------------------------------------------------------------

_SRT_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")
_VTT_TIME = re.compile(r"(?:(\d{1,2}):)?(\d{2}):(\d{2})\.(\d{3})")


def _ms(h, m, s, frac):
    return ((int(h or 0) * 60 + int(m)) * 60 + int(s)) * 1000 + int((frac + "00")[:3])


def _stamp(ms, separator):
    h, rest = divmod(ms, 3600000)
    m, rest = divmod(rest, 60000)
    s, milli = divmod(rest, 1000)
    return "%02d:%02d:%02d%s%03d" % (h, m, s, separator, milli)


def _blocks(text):
    return [b for b in re.split(r"\r?\n\s*\r?\n", text.replace("\r\n", "\n").strip()) if b.strip()]


def _srt_cues(text):
    cues = []
    for block in _blocks(text):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            if "-->" in line:
                start, _, end = line.partition("-->")
                a, b = _SRT_TIME.search(start), _SRT_TIME.search(end)
                if a and b:
                    cues.append((_ms(*a.groups()), _ms(*b.groups()), "\n".join(lines[i + 1 :]).strip()))
                break
    return cues


def _vtt_cues(text):
    cues = []
    for block in _blocks(text):
        lines = block.split("\n")
        if lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        for i, line in enumerate(lines):
            if "-->" in line:
                start, _, end = line.partition("-->")
                a, b = _VTT_TIME.search(start), _VTT_TIME.search(end)
                if a and b:
                    body = "\n".join(lines[i + 1 :]).strip()
                    # Voice and class tags (<v Ada>, <c.red>) are WebVTT only; SubRip keeps b, i, u.
                    body = re.sub(r"</?(?:v|c|lang|ruby|rt)(?:[\s.][^>]*)?>", "", body)
                    body = re.sub(r"<\d{2}:[\d:.]+>", "", body)
                    cues.append((_ms(*a.groups()), _ms(*b.groups()), body))
                break
    return cues


def _ass_cues(text):
    cues = []
    fields = None
    in_events = False
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("["):
            in_events = stripped.lower() == "[events]"
            continue
        if not in_events:
            continue
        if stripped.lower().startswith("format:"):
            fields = [f.strip().lower() for f in stripped.split(":", 1)[1].split(",")]
        elif stripped.lower().startswith("dialogue:") and fields:
            values = stripped.split(":", 1)[1].split(",", len(fields) - 1)
            if len(values) < len(fields):
                continue
            row = dict(zip(fields, (v.strip() for v in values)))
            a = re.match(r"(\d+):(\d{2}):(\d{2})[.:](\d{1,3})", row.get("start", ""))
            b = re.match(r"(\d+):(\d{2}):(\d{2})[.:](\d{1,3})", row.get("end", ""))
            if not (a and b):
                continue
            body = re.sub(r"\{[^}]*\}", "", row.get("text", ""))
            body = body.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ").strip()
            cues.append((_ms(*a.groups()), _ms(*b.groups()), body))
    cues.sort(key=lambda cue: cue[0])
    return cues


def _write_srt(target, cues):
    out = []
    for n, (start, end, body) in enumerate(cues, 1):
        out.append("%d\n%s --> %s\n%s\n" % (n, _stamp(start, ","), _stamp(end, ","), body))
    _write_text(target, "\n".join(out))


def _write_vtt(target, cues):
    out = ["WEBVTT\n"]
    for start, end, body in cues:
        out.append("%s --> %s\n%s\n" % (_stamp(start, "."), _stamp(end, "."), body))
    _write_text(target, "\n".join(out))


def _subtitles(read, write, kind):
    def convert(source, target):
        cues = read(_read_text(source))
        if not cues:
            raise ConversionError("No subtitles were found in the %s file." % kind)
        write(target, cues)

    return convert


CONVERTERS = {
    ("csv", "json"): csv_to_json,
    ("json", "csv"): json_to_csv,
    ("srt", "vtt"): _subtitles(_srt_cues, _write_vtt, "SRT"),
    ("vtt", "srt"): _subtitles(_vtt_cues, _write_srt, "VTT"),
    ("ass", "srt"): _subtitles(_ass_cues, _write_srt, "ASS"),
    ("ass", "vtt"): _subtitles(_ass_cues, _write_vtt, "ASS"),
}


def targets(source):
    return [target for (s, target) in CONVERTERS if s == source]


def converter(source, target):
    return CONVERTERS[(source, target)]
