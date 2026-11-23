"""The conversion tools already installed on this computer: where they are and what they can do.

A tool is looked for at the path given in the settings, then on PATH, then in the folders its
installers usually use (an editor started from the Dock or the Start menu often has a shorter PATH
than a terminal). What a tool can do is asked from the tool itself (`ffmpeg -encoders`,
`magick -list format`…), never assumed: an FFmpeg without libx264 cannot make H.264, an
ImageMagick without libheif cannot read HEIC.

Every command is an argument list run without a shell.
"""

import glob
import os
import re
import shutil
import subprocess

# Seconds a tool may take to say what it can do.
PROBE_TIMEOUT = 15


class Spec:
    """A tool this package knows how to use."""

    __slots__ = ("id", "name", "what", "url", "names", "windows_names", "folders")

    def __init__(self, tool_id, name, what, url, names, windows_names, folders):
        self.id = tool_id
        self.name = name
        self.what = what
        self.url = url
        self.names = names
        self.windows_names = windows_names
        # {platform: [folder, …]}; folders may hold environment variables, ~ and * patterns.
        self.folders = folders


_PACKAGE_MANAGERS = {
    "linux": ["/usr/bin", "/usr/local/bin", "/snap/bin", "~/.local/bin", "/home/linuxbrew/.linuxbrew/bin"],
    "osx": ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"],
    "windows": [
        "%LOCALAPPDATA%\\Microsoft\\WinGet\\Links",
        "%ProgramData%\\chocolatey\\bin",
        "%USERPROFILE%\\scoop\\shims",
    ],
}


def _folders(linux=(), osx=(), windows=()):
    return {
        "linux": _PACKAGE_MANAGERS["linux"] + list(linux),
        "osx": _PACKAGE_MANAGERS["osx"] + list(osx),
        "windows": _PACKAGE_MANAGERS["windows"] + list(windows),
    }


SPECS = (
    Spec(
        "ffmpeg",
        "FFmpeg",
        "video and audio",
        "https://ffmpeg.org/download.html",
        ["ffmpeg"],
        ["ffmpeg.exe"],
        _folders(
            windows=[
                "%ProgramFiles%\\ffmpeg\\bin",
                "C:\\ffmpeg\\bin",
                "%LOCALAPPDATA%\\Microsoft\\WinGet\\Packages\\Gyan.FFmpeg*\\ffmpeg-*\\bin",
            ]
        ),
    ),
    Spec(
        "soffice",
        "LibreOffice",
        "Word, Excel, PowerPoint and OpenDocument files, to PDF and to each other",
        "https://www.libreoffice.org/download/",
        ["soffice", "libreoffice"],
        ["soffice.exe"],
        _folders(
            linux=["/opt/libreoffice*/program"],
            osx=["/Applications/LibreOffice.app/Contents/MacOS", "~/Applications/LibreOffice.app/Contents/MacOS"],
            windows=["%ProgramFiles%\\LibreOffice\\program", "%ProgramFiles(x86)%\\LibreOffice\\program"],
        ),
    ),
    Spec(
        "pandoc",
        "Pandoc",
        "Markdown, HTML, Word, OpenDocument and EPUB",
        "https://pandoc.org/installing.html",
        ["pandoc"],
        ["pandoc.exe"],
        _folders(windows=["%LOCALAPPDATA%\\Pandoc", "%ProgramFiles%\\Pandoc"]),
    ),
    Spec(
        "magick",
        "ImageMagick",
        "pictures",
        "https://imagemagick.org/script/download.php",
        # ImageMagick 7 is `magick`; ImageMagick 6 is `convert` (never on Windows, where
        # convert.exe is the system's disk tool).
        ["magick", "convert"],
        ["magick.exe"],
        _folders(windows=["%ProgramFiles%\\ImageMagick-*"]),
    ),
    Spec(
        "gs",
        "Ghostscript",
        "smaller PDFs and PDF pages as pictures",
        "https://ghostscript.com/releases/gsdnld.html",
        ["gs"],
        ["gswin64c.exe", "gswin32c.exe"],
        _folders(windows=["%ProgramFiles%\\gs\\gs*\\bin", "%ProgramFiles(x86)%\\gs\\gs*\\bin"]),
    ),
    Spec(
        "tesseract",
        "Tesseract",
        "text recognition (OCR) of pictures",
        "https://tesseract-ocr.github.io/tessdoc/Installation.html",
        ["tesseract"],
        ["tesseract.exe"],
        _folders(
            windows=[
                "%ProgramFiles%\\Tesseract-OCR",
                "%LOCALAPPDATA%\\Programs\\Tesseract-OCR",
                "%ProgramFiles(x86)%\\Tesseract-OCR",
            ]
        ),
    ),
)

SPEC_BY_ID = {spec.id: spec for spec in SPECS}


class Tool:
    """A tool found on this computer and what it said it can do."""

    def __init__(self, tool_id, path, version=None, problem=None):
        self.id = tool_id
        self.path = path
        self.version = version
        # Set when the tool was found but did not answer as expected; it is then not used.
        self.problem = problem
        # ffmpeg: encoders; pandoc: "in:<format>" and "out:<format>"; tesseract: languages.
        self.features = set()
        # ImageMagick: {"JPEG": "rw+", …}.
        self.formats = {}
        # ImageMagick: "magick" (7) or "convert" (6).
        self.flavor = None

    @property
    def usable(self):
        return self.path is not None and self.problem is None

    def can(self, feature):
        return feature in self.features

    def magick_mode(self, name):
        return self.formats.get(name, "---")

    def __repr__(self):
        return "Tool(%r, %r, %r)" % (self.id, self.path, self.version)


def _natural_key(path):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path)]


def expand(folder, env):
    """A folder pattern with its variables and ~ replaced; [] when a variable is not set."""
    missing = []

    def windows_variable(match):
        value = env.get(match.group(1))
        if value is None:
            # Windows names its variables without regard to case.
            for key, candidate in env.items():
                if key.upper() == match.group(1).upper():
                    value = candidate
                    break
        if value is None:
            missing.append(match.group(1))
            return ""
        return value

    result = re.sub(r"%([^%]+)%", windows_variable, folder)
    if missing:
        return []
    if result.startswith("~"):
        home = env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")
        result = home + result[1:]
    if "*" in result:
        # The newest version first (ImageMagick-7.1.2 before ImageMagick-7.1.1).
        return sorted(glob.glob(result), key=_natural_key, reverse=True)
    return [result]


def _is_program(path, platform):
    if not os.path.isfile(path):
        return False
    return platform == "windows" or os.access(path, os.X_OK)


def candidates(spec, platform, env, which=shutil.which):
    """Where a tool may be, in the order it is looked for: PATH, then the usual folders."""
    names = spec.windows_names if platform == "windows" else spec.names
    found = []
    for name in names:
        hit = which(name, path=env.get("PATH") or env.get("Path"))
        if hit:
            found.append(hit)
    for folder in spec.folders.get(platform, []):
        for directory in expand(folder, env):
            for name in names:
                found.append(os.path.join(directory, name))
    unique = []
    for path in found:
        if path not in unique:
            unique.append(path)
    return unique


def configured_path(configured, env):
    """The path given in the settings, with its variables and ~ replaced."""
    expanded = expand(configured.strip(), env)
    return expanded[0] if expanded else configured.strip()


def run_probe(argv, timeout=PROBE_TIMEOUT):
    """(exit code, output with stderr) of a short command; (None, reason) when it did not run."""
    try:
        done = subprocess.run(  # noqa: S603 (an argument list, no shell)
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        return None, "did not answer in %d seconds" % timeout
    except OSError as error:
        return None, "could not be started (%s)" % (error.strerror or error)
    return done.returncode, done.stdout.decode("utf-8", "replace")


_FFMPEG_ENCODER = re.compile(r"^ [VAS][.F][.S][.X][.B][.D] ([A-Za-z0-9][^\s]*)", re.M)
_MAGICK_FORMAT = re.compile(r"^\s*([A-Z0-9][A-Z0-9-]*)\*?\s+\S+\s+([r-][w-][+-])\s", re.M)


def _first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def probe(tool_id, path, run=run_probe):
    """Asks a found tool for its version and what it can do."""
    tool = Tool(tool_id, path)
    if tool_id == "soffice":
        # Starting LibreOffice only to read its version takes seconds; its converters are always
        # there, so it is trusted as found.
        return tool
    if tool_id == "ffmpeg":
        code, out = run([path, "-hide_banner", "-encoders"])
        if code != 0:
            tool.problem = out if code is None else "did not list its encoders"
            return tool
        tool.features = set(_FFMPEG_ENCODER.findall(out))
        code, out = run([path, "-version"])
        match = re.search(r"ffmpeg version (\S+)", out or "")
        tool.version = match.group(1) if match else None
        return tool
    if tool_id == "magick":
        code, out = run([path, "-version"])
        if code != 0 or "ImageMagick" not in (out or ""):
            # `convert` may be another program (or ImageMagick 7's own legacy shim that fails).
            tool.problem = out if code is None else "is not ImageMagick"
            return tool
        match = re.search(r"ImageMagick (\S+)", out)
        tool.version = match.group(1) if match else None
        name = os.path.basename(path).lower()
        tool.flavor = "convert" if name.startswith("convert") else "magick"
        code, out = run([path, "-list", "format"])
        if code != 0:
            tool.problem = out if code is None else "did not list its formats"
            return tool
        for fmt, mode in _MAGICK_FORMAT.findall(out):
            tool.formats[fmt] = mode
        return tool
    if tool_id == "pandoc":
        code, out = run([path, "--version"])
        if code != 0:
            tool.problem = out if code is None else "did not answer --version"
            return tool
        match = re.search(r"pandoc(?:\.exe)? (\S+)", out)
        tool.version = match.group(1) if match else None
        for direction, flag in (("in", "--list-input-formats"), ("out", "--list-output-formats")):
            code, out = run([path, flag])
            if code == 0:
                tool.features.update("%s:%s" % (direction, line.strip()) for line in out.splitlines() if line.strip())
        return tool
    if tool_id == "gs":
        code, out = run([path, "--version"])
        if code != 0:
            tool.problem = out if code is None else "did not answer --version"
            return tool
        tool.version = _first_line(out)
        return tool
    if tool_id == "tesseract":
        code, out = run([path, "--version"])
        if code != 0:
            tool.problem = out if code is None else "did not answer --version"
            return tool
        match = re.search(r"tesseract (\S+)", out)
        tool.version = match.group(1) if match else None
        code, out = run([path, "--list-langs"])
        if code == 0:
            for line in out.splitlines():
                line = line.strip()
                if line and not line.lower().startswith("list of available") and " " not in line:
                    tool.features.add(line)
        return tool
    tool.problem = "unknown tool"
    return tool


def discover(platform, env, configured=None, run=None, which=shutil.which, is_program=None):
    """{tool id: Tool} for every known tool; a tool that was not found has path None."""
    configured = configured or {}
    run = run or run_probe
    if is_program is None:

        def is_program(path):
            return _is_program(path, platform)

    found = {}
    for spec in SPECS:
        setting = configured.get(spec.id) or ""
        if setting.strip():
            # A path in the settings is the only one used: no silent fallback to another copy.
            path = configured_path(setting, env)
            if is_program(path):
                found[spec.id] = probe(spec.id, path, run)
            else:
                found[spec.id] = Tool(
                    spec.id, None, problem="not found at the path in the settings (%s)" % setting.strip()
                )
            continue
        tool = None
        for path in candidates(spec, platform, env, which):
            if not is_program(path):
                continue
            attempt = probe(spec.id, path, run)
            if attempt.problem is None:
                tool = attempt
                break
            # Keep the first problem, but try the next copy (`convert` may be another program).
            tool = tool or attempt
        found[spec.id] = tool or Tool(spec.id, None)
    return found
