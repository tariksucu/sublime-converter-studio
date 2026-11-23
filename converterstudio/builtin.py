"""Conversions done in plain Python, with nothing installed: CSV ↔ JSON and subtitles.

Each converter reads the source file and writes the target file; it raises ConversionError with
a sentence for the user when the source is not what it should be.
"""

import csv
import io
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


def _delimiter(text):
    """The separator of a CSV file: the most frequent of , ; tab | on its first line (, on a tie)."""
    first = next((line for line in text.splitlines() if line.strip()), "")
    counts = [(first.count(d), -i, d) for i, d in enumerate(",;\t|")]
    best = max(counts)
    return best[2] if best[0] else ","


def csv_to_json(source, target):
    """A CSV file with a header row → a JSON array of objects (values stay text)."""
    text = _read_text(source)
    reader = csv.reader(io.StringIO(text), delimiter=_delimiter(text))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise ConversionError("The CSV file is empty.")
    header = [name.strip() or "column%d" % (i + 1) for i, name in enumerate(rows[0])]
    seen = {}
    for i, name in enumerate(header):
        if name in seen:
            seen[name] += 1
            header[i] = "%s_%d" % (name, seen[name])
        else:
            seen[name] = 1
    records = []
    for row in rows[1:]:
        row = row + [""] * (len(header) - len(row))
        record = dict(zip(header, row))
        if len(row) > len(header):
            record["_extra"] = row[len(header) :]
        records.append(record)
    _write_text(target, json.dumps(records, ensure_ascii=False, indent=2) + "\n")


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def json_to_csv(source, target):
    """A JSON array of objects (or one object, or an object holding one such array) → CSV."""
    try:
        data = json.loads(_read_text(source))
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
    columns = []
    for item in data:
        if isinstance(item, dict):
            for key in item:
                if key not in columns:
                    columns.append(key)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    if columns:
        writer.writerow(columns)
        for item in data:
            if isinstance(item, dict):
                writer.writerow([_cell(item.get(key)) for key in columns])
            else:
                writer.writerow([_cell(item)] + [""] * (len(columns) - 1))
    else:
        # An array of plain values or of arrays.
        for item in data:
            writer.writerow([_cell(v) for v in item] if isinstance(item, list) else [_cell(item)])
    _write_text(target, out.getvalue())


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
