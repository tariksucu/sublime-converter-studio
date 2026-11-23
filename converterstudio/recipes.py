"""What can be converted on this computer, and the command line for each conversion.

These are Converter Studio's own, deliberately simple recipes for tools the user already has.
Each one writes into an empty working folder; the caller moves the result next to the source.
Every command is an argument list: no shell, no quoting.
"""

import os
from pathlib import Path

from . import builtin
from . import formats as fmt

LOCAL = "local"
DESKTOP = "desktop"
CLOUD = "cloud"

# Variants of a conversion with the same target format.
PLAIN = ""
OCR = "ocr"  # text recognition
COMPRESS = "compress"  # PDF → smaller PDF
PAGES = "pages"  # one picture per PDF page

TOOL_NAMES = {
    "python": "Python (built in)",
    "ffmpeg": "FFmpeg",
    "soffice": "LibreOffice",
    "pandoc": "Pandoc",
    "pandoc+soffice": "Pandoc and LibreOffice",
    "magick": "ImageMagick",
    "gs": "Ghostscript",
    "tesseract": "Tesseract",
}

# The tools each local conversion needs.
TOOLS_OF = {"pandoc+soffice": ("pandoc", "soffice")}


def tools_of(tool_id):
    return TOOLS_OF.get(tool_id, (tool_id,))


VIDEO = ("mp4", "mov", "mkv", "webm", "avi", "wmv", "flv", "3gp")
AUDIO = ("mp3", "m4a", "wav", "flac", "ogg", "opus", "aac", "aiff", "wma")
VIDEO_TARGETS = ("mp4", "webm", "mov", "mkv", "gif")
AUDIO_TARGETS = ("mp3", "m4a", "wav", "flac", "ogg", "opus", "aac", "aiff")

# FFmpeg: the encoders each target needs, and its arguments after the input.
_H264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p"]
_EVEN = ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]
FFMPEG_TARGETS = {
    "mp4": (("libx264", "aac"), _H264 + _EVEN + ["-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]),
    "mov": (("libx264", "aac"), _H264 + _EVEN + ["-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]),
    "mkv": (("libx264", "aac"), _H264 + _EVEN + ["-c:a", "aac", "-b:a", "160k"]),
    "webm": (
        ("libvpx-vp9", "libopus"),
        ["-c:v", "libvpx-vp9", "-crf", "33", "-b:v", "0", "-row-mt", "1", "-c:a", "libopus", "-b:a", "128k"],
    ),
    "gif": (
        ("gif",),
        [
            "-an",
            "-vf",
            "fps=12,scale='min(640,iw)':-2:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
            "-loop",
            "0",
        ],
    ),
    "mp3": (("libmp3lame",), ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]),
    "m4a": (("aac",), ["-vn", "-c:a", "aac", "-b:a", "192k"]),
    "aac": (("aac",), ["-vn", "-c:a", "aac", "-b:a", "192k"]),
    "wav": (("pcm_s16le",), ["-vn", "-c:a", "pcm_s16le"]),
    "aiff": (("pcm_s16be",), ["-vn", "-c:a", "pcm_s16be"]),
    "flac": (("flac",), ["-vn", "-c:a", "flac"]),
    "ogg": (("libvorbis",), ["-vn", "-c:a", "libvorbis", "-q:a", "5"]),
    "opus": (("libopus",), ["-vn", "-c:a", "libopus", "-b:a", "128k"]),
}

# LibreOffice: documents by application, and the export filter of each target.
WRITER = ("docx", "doc", "odt", "rtf", "txt", "html")
CALC = ("xlsx", "xls", "ods", "csv")
IMPRESS = ("pptx", "ppt", "odp")
SOFFICE_FILTERS = {
    "pdf": "pdf",
    "docx": "docx:MS Word 2007 XML",
    "doc": "doc:MS Word 97",
    "odt": "odt",
    "rtf": "rtf",
    "txt": "txt:Text (encoded):UTF8",
    "html": "html",
    "epub": "epub",
    "xlsx": "xlsx:Calc MS Excel 2007 XML",
    "xls": "xls:MS Excel 97",
    "ods": "ods",
    # Comma, double quote, UTF-8, first line as it is.
    "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1",
    "pptx": "pptx:Impress MS PowerPoint 2007 XML",
    "ppt": "ppt:MS PowerPoint 97",
    "odp": "odp",
}
SOFFICE_TARGETS = {
    "writer": ("pdf", "docx", "odt", "rtf", "txt", "html", "doc", "epub"),
    "calc": ("pdf", "xlsx", "ods", "csv", "xls"),
    "impress": ("pdf", "pptx", "odp", "ppt"),
}

# Pandoc: our format ids and Pandoc's reader and writer names.
PANDOC_READERS = {"md": "markdown", "html": "html", "docx": "docx", "odt": "odt", "epub": "epub", "rtf": "rtf"}
PANDOC_WRITERS = {
    "md": "gfm",
    "html": "html5",
    "docx": "docx",
    "odt": "odt",
    "epub": "epub3",
    "rtf": "rtf",
    "txt": "plain",
}
# Where Pandoc is the better choice than LibreOffice: Markdown, HTML and EPUB on either side.
MARKUP = ("md", "html", "epub")

# ImageMagick: our format ids and ImageMagick's format names.
MAGICK_NAMES = {
    "jpg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "avif": "AVIF",
    "heic": "HEIC",
    "gif": "GIF",
    "bmp": "BMP",
    "tiff": "TIFF",
    "ico": "ICO",
    "pdf": "PDF",
    "cr2": "CR2",
    "nef": "NEF",
    "arw": "ARW",
    "dng": "DNG",
}
MAGICK_SOURCES = ("jpg", "png", "webp", "avif", "heic", "gif", "bmp", "tiff", "ico", "cr2", "nef", "arw", "dng")
MAGICK_TARGETS = ("jpg", "png", "webp", "avif", "gif", "tiff", "bmp", "ico", "pdf")
# Sources that may hold several frames or pages: only the first becomes a single picture.
MULTI_FRAME = ("gif", "tiff", "ico", "webp", "avif", "heic")
# Targets without transparency: transparent pixels become white, not black.
OPAQUE = ("jpg", "bmp")

# Tesseract reads these through Leptonica.
OCR_SOURCES = ("png", "jpg", "tiff", "bmp", "webp")

# Ghostscript's settings for a smaller PDF (pictures at 150 dpi).
GS_COMPRESS = "/ebook"
GS_PAGE_DPI = "150"


class Choice:
    """One row of the picker: a target format, where the conversion runs and with what."""

    __slots__ = ("source", "target", "layer", "tool", "variant", "reason")

    def __init__(self, source, target, layer, tool=None, variant=PLAIN, reason=None):
        self.source = source
        self.target = target
        self.layer = layer
        self.tool = tool
        self.variant = variant
        # Why a local conversion is not possible here (shown by "Show Local Tools").
        self.reason = reason

    @property
    def label(self):
        return label(self.target, self.variant, self.source)

    @property
    def key(self):
        return (self.target, self.variant)

    def __repr__(self):
        return "Choice(%s→%s %s %s %s)" % (self.source, self.target, self.layer, self.tool, self.variant)


def label(target, variant=PLAIN, source=None):
    """How a target is named in the picker: `PDF`, `PDF, smaller`, `TXT, text recognition`."""
    name = fmt.label(target)
    if variant == COMPRESS or (source == "pdf" and target == "pdf"):
        return name + ", smaller (compressed)"
    if variant == OCR:
        return name + (", searchable (text recognition)" if target == "pdf" else ", text recognition (OCR)")
    if variant == PAGES:
        return name + ", one picture per page"
    return name


# -- what is possible ------------------------------------------------------------------------


def _ffmpeg(source, tool):
    targets = []
    if source in VIDEO:
        targets = list(VIDEO_TARGETS) + list(AUDIO_TARGETS)
    elif source in AUDIO:
        targets = list(AUDIO_TARGETS)
    elif source == "gif":
        targets = ["mp4", "webm"]
    for target in targets:
        if target == source:
            continue
        needs = FFMPEG_TARGETS[target][0]
        missing = [encoder for encoder in needs if not tool.can(encoder)]
        yield target, PLAIN, ("this FFmpeg has no %s encoder" % ", ".join(missing)) if missing else None


def _soffice_app(source):
    if source in WRITER:
        return "writer"
    if source in CALC:
        return "calc"
    if source in IMPRESS:
        return "impress"
    return None


def _soffice(source, tool):
    app = _soffice_app(source)
    if not app:
        return
    for target in SOFFICE_TARGETS[app]:
        if target != source:
            yield target, PLAIN, None


def _pandoc(source, tool):
    if source not in PANDOC_READERS:
        return
    reader = PANDOC_READERS[source]
    for target, writer in PANDOC_WRITERS.items():
        if target == source:
            continue
        if not tool.can("in:" + reader):
            yield target, PLAIN, "this Pandoc cannot read %s" % fmt.label(source)
        elif not tool.can("out:" + writer):
            yield target, PLAIN, "this Pandoc cannot write %s" % fmt.label(target)
        else:
            yield target, PLAIN, None


def _pandoc_to_pdf(source, pandoc):
    """Markdown and EPUB to PDF without LaTeX: Pandoc writes Word, LibreOffice makes the PDF."""
    if source not in ("md", "epub"):
        return
    if not pandoc.can("in:" + PANDOC_READERS[source]):
        yield "pdf", PLAIN, "this Pandoc cannot read %s" % fmt.label(source)
    elif not pandoc.can("out:docx"):
        yield "pdf", PLAIN, "this Pandoc cannot write Word files"
    else:
        yield "pdf", PLAIN, None


def _magick(source, tool):
    if source not in MAGICK_SOURCES:
        return
    readable = "r" in tool.magick_mode(MAGICK_NAMES[source])[0]
    for target in MAGICK_TARGETS:
        if target == source:
            continue
        if not readable:
            yield target, PLAIN, "this ImageMagick cannot read %s" % fmt.label(source)
        elif tool.magick_mode(MAGICK_NAMES[target])[1] != "w":
            yield target, PLAIN, "this ImageMagick cannot write %s" % fmt.label(target)
        else:
            yield target, PLAIN, None


def _gs(source, tool):
    if source != "pdf":
        return
    yield "pdf", COMPRESS, None
    yield "png", PAGES, None
    yield "jpg", PAGES, None


def _tesseract(source, tool, language):
    if source not in OCR_SOURCES:
        return
    missing = [lang for lang in language.split("+") if lang and not tool.can(lang)]
    reason = "the Tesseract language %s is not installed" % "+".join(missing) if missing else None
    yield "txt", OCR, reason
    yield "pdf", OCR, reason


def _python(source, tool):
    for target in builtin.targets(source):
        yield target, PLAIN, None


def _rules(source, language):
    """(tool id, generator) in the order of preference for the same target."""
    pandoc_first = source in MARKUP
    order = ["python"]
    order += ["pandoc", "soffice"] if pandoc_first else ["soffice", "pandoc"]
    order += ["pandoc+soffice", "magick", "gs", "tesseract", "ffmpeg"]
    for tool_id in order:
        if tool_id == "python":
            yield tool_id, lambda tools: _python(source, None)
        elif tool_id == "pandoc":
            yield tool_id, lambda tools: _pandoc(source, tools[0])
        elif tool_id == "soffice":
            yield tool_id, lambda tools: _soffice(source, tools[0])
        elif tool_id == "pandoc+soffice":
            yield tool_id, lambda tools: _pandoc_to_pdf(source, tools[0])
        elif tool_id == "magick":
            yield tool_id, lambda tools: _magick(source, tools[0])
        elif tool_id == "gs":
            yield tool_id, lambda tools: _gs(source, tools[0])
        elif tool_id == "tesseract":
            yield tool_id, lambda tools: _tesseract(source, tools[0], language)
        elif tool_id == "ffmpeg":
            yield tool_id, lambda tools: _ffmpeg(source, tools[0])


def _order(source, choices):
    """The catalogue's order for this source (the most used first), then the rest."""
    known = fmt.get(source)
    ranking = {target: i for i, target in enumerate(known.targets if known else ())}
    variants = {PLAIN: 0, COMPRESS: 1, OCR: 2, PAGES: 3}
    return sorted(
        choices,
        key=lambda c: (ranking.get(c.target, len(ranking)), c.target, variants.get(c.variant, 9)),
    )


def local_choices(source, found, language="eng", with_unavailable=False):
    """The local conversions of a `source` format with the tools `found` ({id: Tool}).

    One choice per target and variant, from the preferred tool that can do it. With
    `with_unavailable`, conversions a found tool cannot do here are included with their reason.
    """
    chosen = {}
    blocked = {}
    for tool_id, rule in _rules(source, language or "eng"):
        needed = [] if tool_id == "python" else [found.get(t) for t in tools_of(tool_id)]
        if any(tool is None or not tool.usable for tool in needed):
            continue
        for target, variant, reason in rule(needed):
            key = (target, variant)
            if key in chosen:
                continue
            if reason:
                blocked.setdefault(key, Choice(source, target, LOCAL, tool_id, variant, reason))
            else:
                chosen[key] = Choice(source, target, LOCAL, tool_id, variant)
    result = _order(source, chosen.values())
    if with_unavailable:
        result += _order(source, [c for k, c in blocked.items() if k not in chosen])
    return result


def remote_choices(source, layer):
    """The desktop app's or the cloud's conversions of a `source` format (from the catalogue)."""
    known = fmt.get(source)
    if not known:
        return []
    return [Choice(source, target, layer) for target in known.targets]


# -- the command lines -------------------------------------------------------------------------


class Plan:
    """How to run one local conversion: commands run one after the other, or a Python function."""

    def __init__(self, steps=None, function=None, output=None, env=None, folders=None):
        # Argument lists; each step must succeed before the next one starts.
        self.steps = steps or []
        # Folders to make before the first step (in the working folder).
        self.folders = folders or []
        self.function = function
        # For a function: the file it writes. Commands write into the working folder.
        self.output = output
        self.env = env or {}


def _file_uri(path):
    return Path(os.path.abspath(path)).as_uri()


def _soffice_argv(soffice, source, target, source_path, out_dir, profile):
    argv = [
        soffice.path,
        "-env:UserInstallation=" + _file_uri(profile),
        "--headless",
        "--norestore",
        "--nologo",
        "--nodefault",
        "--nolockcheck",
    ]
    if source == "html":
        # Opened as a Writer document (not Writer/Web), so that PDF and Word export work.
        argv.append("--infilter=HTML (StarWriter)")
    return argv + ["--convert-to", SOFFICE_FILTERS[target], "--outdir", out_dir, source_path]


def _pandoc_argv(pandoc, source, target, source_path, out, stem):
    argv = [pandoc.path, "--from", PANDOC_READERS[source], "--to", PANDOC_WRITERS[target]]
    if target in ("html", "rtf", "epub"):
        argv.append("--standalone")
    if target == "html":
        argv += ["--metadata", "pagetitle=" + stem]
    if target == "epub":
        argv += ["--metadata", "title=" + stem]
    folder = os.path.dirname(os.path.abspath(source_path)) or "."
    return argv + ["--resource-path", folder, "--output", out, source_path]


def build(choice, source_path, work_dir, found=None, language="eng", profile_dir=None):
    """The Plan of a local conversion, writing into the empty folder `work_dir`.

    `found` is {tool id: Tool} (the tools of `choice.tool`); `profile_dir` a folder for
    LibreOffice's own settings (by default inside `work_dir`, made afresh each time).
    """
    found = found or {}
    stem = fmt.stem(source_path, choice.source)
    target_ext = fmt.extension(choice.target)
    out = os.path.join(work_dir, "%s.%s" % (stem, target_ext))
    t = choice.tool
    tool = found.get(t)
    profile = profile_dir or os.path.join(work_dir, ".profile")

    if t == "python":
        return Plan(function=builtin.converter(choice.source, choice.target), output=out)

    if t == "ffmpeg":
        args = FFMPEG_TARGETS[choice.target][1]
        argv = [tool.path, "-hide_banner", "-nostdin", "-loglevel", "error", "-n", "-i", source_path]
        return Plan([argv + list(args) + [out]])

    if t == "soffice":
        return Plan([_soffice_argv(tool, choice.source, choice.target, source_path, work_dir, profile)])

    if t == "pandoc":
        return Plan([_pandoc_argv(tool, choice.source, choice.target, source_path, out, stem)])

    if t == "pandoc+soffice":
        # Pandoc writes a Word file into a hidden step folder, LibreOffice turns it into a PDF.
        step = os.path.join(work_dir, ".step")
        docx = os.path.join(step, stem + ".docx")
        return Plan(
            [
                _pandoc_argv(found["pandoc"], choice.source, "docx", source_path, docx, stem),
                _soffice_argv(found["soffice"], "docx", "pdf", docx, work_dir, profile),
            ],
            folders=[step],
        )

    if t == "magick":
        # ImageMagick 6's `convert` and 7's `magick` take the same arguments here.
        source_arg = source_path
        if choice.source in MULTI_FRAME and choice.target not in ("gif", "pdf", "tiff"):
            source_arg += "[0]"
        argv = [tool.path, source_arg, "-auto-orient"]
        if choice.target in OPAQUE:
            argv += ["-background", "white", "-alpha", "remove", "-alpha", "off"]
        if choice.target in ("jpg", "webp", "avif"):
            argv += ["-quality", "88"]
        if choice.target == "ico":
            argv += ["-define", "icon:auto-resize=256,128,64,48,32,16"]
        # An explicit format prefix: the extension of `out` could be read as something else.
        return Plan([argv + ["%s:%s" % (MAGICK_NAMES[choice.target], out)]])

    if t == "gs":
        common = ["-dNOPAUSE", "-dBATCH", "-dSAFER", "-dQUIET"]
        if choice.variant == COMPRESS:
            out = os.path.join(work_dir, "%s-compressed.pdf" % stem)
            argv = [
                tool.path,
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.5",
                "-dPDFSETTINGS=" + GS_COMPRESS,
            ]
            return Plan([argv + common + ["-sOutputFile=" + out, source_path]])
        device = ["-sDEVICE=png16m"] if choice.target == "png" else ["-sDEVICE=jpeg", "-dJPEGQ=90"]
        pattern = os.path.join(work_dir, "%s-page-%%03d.%s" % (stem.replace("%", "%%"), target_ext))
        argv = [tool.path] + device + ["-r" + GS_PAGE_DPI] + common + ["-sOutputFile=" + pattern, source_path]
        return Plan([argv])

    if t == "tesseract":
        base = os.path.join(work_dir, stem)
        argv = [tool.path, source_path, base, "-l", language or "eng"]
        if choice.target == "pdf":
            argv.append("pdf")
        # One thread: several OpenMP threads make Tesseract slower on most machines.
        return Plan([argv], env={"OMP_THREAD_LIMIT": "1"})

    raise ValueError("no local recipe for %r" % (choice,))
