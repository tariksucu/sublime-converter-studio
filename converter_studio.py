"""Converter Studio for Sublime Text: convert files from the Command Palette.

Conversions run on this computer first (the tools already installed here), then, if the user
turned it on, in the Converter Studio desktop app, and in the Converter Studio cloud only when the
user picks it. Everything that takes time runs on a worker thread; the editor never waits.
"""

import html
import os
import threading
import time

import sublime
import sublime_plugin

from .converterstudio import (
    API_KEY_ENV,
    DESKTOP_MIN_VERSION,
    DOWNLOAD_PAGE,
    KEYS_PAGE,
    PRIVACY_PAGE,
    VERSION,
    api,
    cloud,
    desktop,
    local,
    recipes,
    tools,
)
from .converterstudio import formats as fmt

SETTINGS_FILE = "Converter Studio.sublime-settings"
SETTING_KEYS = (
    "tool_paths",
    "timeout_seconds",
    "ocr_language",
    "use_desktop_app",
    "list_cloud_formats",
    "api_key",
    "api_url",
    "max_credits",
)
PANEL = "converter_studio"
STATUS = "Converter Studio"

# The package's folder name, whatever Package Control installed it as.
PACKAGE = __package__ or "Converter Studio"

KIND_LOCAL = (sublime.KIND_ID_COLOR_GREENISH, "L", "On this computer")
KIND_DESKTOP = (sublime.KIND_ID_COLOR_BLUISH, "D", "Desktop app")
KIND_CLOUD = (sublime.KIND_ID_COLOR_ORANGISH, "C", "Cloud")
KIND_MORE = (sublime.KIND_ID_COLOR_ORANGISH, "…", "Cloud")

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def platform():
    return sublime.platform()


def read_settings():
    settings = sublime.load_settings(SETTINGS_FILE)
    values = {key: settings.get(key) for key in SETTING_KEYS}
    values["soffice_profile"] = os.path.join(sublime.cache_path(), PACKAGE, "libreoffice-profile")
    return values


def on_main(callback, delay=0):
    sublime.set_timeout(callback, delay)


def ask_on_main(question):
    """Runs `question()` (a dialog) on the main thread and returns its answer to a worker."""
    answer = {}
    ready = threading.Event()

    def ask():
        try:
            answer["value"] = question()
        finally:
            ready.set()

    on_main(ask)
    ready.wait()
    return answer.get("value")


# -- the tools on this computer ----------------------------------------------------------------


class ToolCache:
    """What was found on this computer, asked once per session or after a settings change."""

    def __init__(self):
        self.lock = threading.Lock()
        self.found = None
        self.paths = None

    def get(self, settings, refresh=False):
        paths = dict(settings.get("tool_paths") or {})
        with self.lock:
            if refresh or self.found is None or self.paths != paths:
                self.found = tools.discover(platform(), dict(os.environ), paths)
                self.paths = paths
            return self.found

    def clear(self):
        with self.lock:
            self.found = None


TOOLS = ToolCache()


# -- one conversion at a time ------------------------------------------------------------------


class Job:
    def __init__(self, window, paths, row):
        self.window = window
        self.paths = list(paths)
        self.row = row
        self.cancel = threading.Event()
        self.started = time.monotonic()
        self.index = 0
        self.step = ""
        self.done = False

    def status(self, tick):
        name = os.path.basename(self.paths[min(self.index, len(self.paths) - 1)])
        count = " [%d/%d]" % (self.index + 1, len(self.paths)) if len(self.paths) > 1 else ""
        where = self.row.where_text()
        seconds = int(time.monotonic() - self.started)
        if self.cancel.is_set():
            return "%s: stopping…" % STATUS
        step = (" " + self.step) if self.step else ""
        return "%s %s %s → %s%s (%s)%s %ds" % (
            SPINNER[tick % len(SPINNER)],
            STATUS,
            name,
            self.row.label,
            count,
            where,
            step,
            seconds,
        )


_job_lock = threading.Lock()
_job = None


def current_job():
    with _job_lock:
        return _job if _job is not None and not _job.done else None


def _claim(job):
    global _job
    with _job_lock:
        if _job is not None and not _job.done:
            return False
        _job = job
        return True


def _ticker(job, tick=0):
    if job.done:
        return
    job.window.status_message(job.status(tick))
    on_main(lambda: _ticker(job, tick + 1), 400)


# -- the picker --------------------------------------------------------------------------------


class Row:
    """One row of the picker: a target, where it runs, and the choice for each source format."""

    def __init__(self, layer, target, variant, label, choices=None, more=False):
        self.layer = layer
        self.target = target
        self.variant = variant
        self.label = label
        self.choices = choices or {}
        self.more = more

    def tools_text(self):
        return " / ".join(sorted({recipes.TOOL_NAMES[c.tool] for c in self.choices.values()}))

    def where_text(self):
        if self.layer == recipes.LOCAL:
            return "on this computer, " + self.tools_text()
        if self.layer == recipes.DESKTOP:
            return "desktop app"
        return "cloud"

    def item(self):
        if self.more:
            return sublime.QuickPanelItem(
                "More formats in the cloud…",
                ["Converter Studio cloud: uploads the file to converter.studio and uses credits"],
                "cloud",
                KIND_MORE,
            )
        if self.layer == recipes.LOCAL:
            details = "On this computer with %s. Nothing is uploaded." % html.escape(self.tools_text())
            return sublime.QuickPanelItem(self.label, [details], "on this computer", KIND_LOCAL)
        if self.layer == recipes.DESKTOP:
            details = "Hands the file to the Converter Studio desktop app; you press Convert there."
            return sublime.QuickPanelItem(self.label, [details], "desktop app", KIND_DESKTOP)
        details = "Converter Studio cloud: uploads the file to converter.studio and uses credits."
        return sublime.QuickPanelItem(self.label, [details], "cloud", KIND_CLOUD)


def local_rows(sources, found, settings):
    """Local rows that every selected file can take (one per target and variant)."""
    per_source = {}
    for source in sources:
        per_source[source] = {
            c.key: c for c in recipes.local_choices(source, found, settings.get("ocr_language") or "eng")
        }
    first = recipes.local_choices(sources[0], found, settings.get("ocr_language") or "eng")
    rows = []
    for choice in first:
        if all(choice.key in per_source[s] for s in sources):
            choices = {s: per_source[s][choice.key] for s in sources}
            rows.append(Row(recipes.LOCAL, choice.target, choice.variant, choice.label, choices))
    return rows


def remote_rows(sources, layer):
    return [
        Row(layer, target, recipes.PLAIN, recipes.label(target, recipes.PLAIN, sources[0]))
        for target in fmt.cloud_targets(sources)
    ]


def build_rows(sources, found, settings, desktop_state, local_files=True):
    rows = local_rows(sources, found, settings)
    # The desktop app opens files from this computer's own disk only.
    if settings.get("use_desktop_app") and desktop_state is not False and local_files:
        rows += remote_rows(sources, recipes.DESKTOP)
    cloud_rows = remote_rows(sources, recipes.CLOUD)
    if cloud_rows:
        if settings.get("list_cloud_formats"):
            rows += cloud_rows
        else:
            rows.append(Row(recipes.CLOUD, None, recipes.PLAIN, "", more=True))
    return rows


def describe_sources(paths):
    if len(paths) == 1:
        return os.path.basename(paths[0])
    return "%d files" % len(paths)


def start(window, paths, to=None, where=None):
    """Looks for the tools (on a worker thread), then shows the picker or runs `to` at once."""
    if current_job():
        window.status_message(
            "%s: a conversion is running. Run “Converter Studio: Cancel Conversion” to stop it." % STATUS
        )
        return
    paths = [os.path.abspath(p) for p in paths if p]
    missing = [p for p in paths if not os.path.isfile(p)]
    if not paths or missing:
        sublime.error_message("Converter Studio: this file does not exist:\n\n%s" % (missing or ["(none)"])[0])
        return
    sources = []
    for path in paths:
        source = fmt.detect(path)
        if not source:
            sublime.error_message(
                "Converter Studio does not know the format of %s, so it cannot convert it." % os.path.basename(path)
            )
            return
        sources.append(source)
    window.status_message("%s: looking for conversion tools on this computer…" % STATUS)

    def work():
        settings = read_settings()
        found = TOOLS.get(settings)
        desktop_state = None
        local_files = False
        if settings.get("use_desktop_app"):
            desktop_state = desktop.is_installed(platform())
            local_files = len(paths) <= desktop.MAX_FILES and all(desktop.is_local_file(p, platform()) for p in paths)
        rows = build_rows(sources, found, settings, desktop_state, local_files)
        on_main(lambda: show_picker(window, paths, sources, rows, settings, desktop_state, to, where))

    threading.Thread(target=work, name="converter-studio-tools", daemon=True).start()


def show_picker(window, paths, sources, rows, settings, desktop_state, to=None, where=None):
    if to:
        layer = where or recipes.LOCAL
        if layer == recipes.CLOUD:
            matches = [r for r in remote_rows(sources, recipes.CLOUD) if r.target == to]
        else:
            matches = [r for r in rows if r.target == to and r.layer == layer and not r.more]
        if matches:
            run_row(window, paths, matches[0], settings)
            return
        window.status_message(
            "%s: %s cannot become %s %s; pick another way."
            % (
                STATUS,
                describe_sources(paths),
                fmt.label(to),
                "on this computer" if layer == recipes.LOCAL else "there",
            )
        )
    if not rows:
        sublime.message_dialog(
            "Converter Studio cannot convert %s on this computer.\n\n"
            "Run “Converter Studio: Show Local Tools” to see which tools were found." % describe_sources(paths)
        )
        return
    if settings.get("use_desktop_app") and desktop_state is False:
        window.status_message(
            "%s: the desktop app is turned on in the settings but not installed (version %s or later: %s)."
            % (STATUS, DESKTOP_MIN_VERSION, DOWNLOAD_PAGE)
        )

    def on_select(index):
        if index < 0:
            return
        row = rows[index]
        if row.more:
            show_cloud_picker(window, paths, sources, settings)
        else:
            run_row(window, paths, row, settings)

    window.show_quick_panel(
        [row.item() for row in rows],
        on_select,
        selected_index=0,
        placeholder="Convert %s to…" % describe_sources(paths),
    )


def show_cloud_picker(window, paths, sources, settings):
    rows = remote_rows(sources, recipes.CLOUD)

    def on_select(index):
        if index >= 0:
            run_row(window, paths, rows[index], settings)

    window.show_quick_panel(
        [row.item() for row in rows],
        on_select,
        selected_index=0,
        placeholder="In the cloud: %s is uploaded to converter.studio. Convert to…" % describe_sources(paths),
    )


# -- running a choice --------------------------------------------------------------------------


def run_row(window, paths, row, settings):
    if row.layer == recipes.DESKTOP:
        hand_over(window, paths, row)
    elif row.layer == recipes.CLOUD:
        run_cloud(window, paths, row, settings)
    else:
        run_local(window, paths, row, settings)


def log(window, text):
    panel = window.find_output_panel(PANEL) or window.create_output_panel(PANEL)
    panel.run_command("append", {"characters": text + "\n", "force": True, "scroll_to_end": True})


def finished(job, written, note=""):
    job.done = True
    names = [os.path.basename(p) for p in written]
    if names:
        text = "%s: saved %s%s" % (STATUS, ", ".join(names), note)
    else:
        text = "%s: nothing was saved%s" % (STATUS, note)
    job.window.status_message(text)
    log(job.window, "%s  %s" % (time.strftime("%H:%M:%S"), text))


def show_failure(job, written, text):
    finished(job, written, " (failed)")
    log(job.window, text)
    sublime.error_message(text)


def run_local(window, paths, row, settings):
    job = Job(window, paths, row)
    if not _claim(job):
        window.status_message("%s: a conversion is running." % STATUS)
        return

    def work():
        written = []
        try:
            found = TOOLS.get(settings)
            for index, path in enumerate(job.paths):
                job.index = index
                choice = row.choices[fmt.detect(path)]
                written += local.convert(choice, path, found, settings, cancelled=job.cancel.is_set)
        except local.Canceled:
            on_main(lambda: finished(job, written, " (canceled)"))
            return
        except local.LocalFailure as error:
            remaining = job.paths[job.index :]
            failure = error  # `error` itself is gone once this block ends
            on_main(lambda: local_failed(job, written, remaining, failure, settings))
            return
        except Exception as error:  # noqa: BLE001 (shown to the user, never swallowed)
            remaining = job.paths[job.index :]
            failure = local.LocalFailure("The conversion stopped with an error: %s" % error)
            on_main(lambda: local_failed(job, written, remaining, failure, settings))
            return
        on_main(lambda: finished(job, written))

    _ticker(job)
    threading.Thread(target=work, name="converter-studio-local", daemon=True).start()


def local_failed(job, written, remaining, error, settings):
    """A local conversion failed: say why, and offer the cloud, never use it silently."""
    finished(job, written, " (failed)")
    name = os.path.basename(remaining[0])
    text = "Converter Studio could not convert %s on this computer.\n\n%s" % (name, error.message)
    if error.details:
        text += "\n\n" + error.details
    log(job.window, text)
    sources = [fmt.detect(p) for p in remaining]
    if job.row.target not in fmt.cloud_targets(sources):
        sublime.error_message(text)
        return
    text += (
        "\n\nConverter Studio's cloud can convert it instead: the file is uploaded to converter.studio and "
        "the conversion uses credits of your account."
    )
    if sublime.ok_cancel_dialog(text, "Try in the Cloud (Uses Credits)"):
        target = job.row.target
        cloud_row = Row(recipes.CLOUD, target, recipes.PLAIN, recipes.label(target, recipes.PLAIN, sources[0]))
        run_cloud(job.window, remaining, cloud_row, settings)


def hand_over(window, paths, row):
    # A long selection goes as several links; the app merges those that arrive within 15 s.
    urls = desktop.handoff_urls(row.target, paths)

    def work():
        problem = None
        for url in urls:
            problem = desktop.open_url(url, platform())
            if problem:
                break
        on_main(lambda: handed_over(window, paths, problem))

    threading.Thread(target=work, name="converter-studio-desktop", daemon=True).start()


def handed_over(window, paths, problem):
    if problem:
        sublime.error_message(
            "The Converter Studio desktop app did not open: %s.\n\n"
            "Handing files over needs Converter Studio for desktop, version %s or later: %s"
            % (problem, DESKTOP_MIN_VERSION, DOWNLOAD_PAGE)
        )
        return
    text = "%s: %s sent to the desktop app. Press Continue, then Convert there." % (STATUS, describe_sources(paths))
    window.status_message(text)
    log(window, "%s  %s" % (time.strftime("%H:%M:%S"), text))


def cloud_client(settings):
    """An API client from the settings, or None after telling the user what is missing."""
    key = api.api_key(settings)
    if not key:
        text = (
            "A cloud conversion needs your Converter Studio API key.\n\n"
            "Create one at %s, then either put it in the setting “api_key” (your settings file "
            "keeps it in plain text) or set the environment variable %s and restart Sublime Text."
            % (KEYS_PAGE, API_KEY_ENV)
        )
        if sublime.ok_cancel_dialog(text, "Open Settings"):
            edit_settings(sublime.active_window())
        return None
    try:
        base = api.base_url(settings)
    except api.ApiError as error:
        sublime.error_message("Converter Studio: " + cloud.message(error))
        return None
    context = api.urllib_transport(_tls_context())
    return api.Client(base, key, context, str(sublime.version()))


def _tls_context():
    from .converterstudio import tls

    return tls.make_context()


def run_cloud(window, paths, row, settings):
    client = cloud_client(settings)
    if client is None:
        return
    job = Job(window, paths, row)
    if not _claim(job):
        window.status_message("%s: a conversion is running." % STATUS)
        return
    try:
        max_credits = max(0, int(settings.get("max_credits") if settings.get("max_credits") is not None else 20))
    except (TypeError, ValueError):
        max_credits = 20

    def progress(step, done, total):
        percent = (" %d%%" % (100 * done // total)) if total else ""
        job.step = step + percent

    def confirm(credits):
        return ask_on_main(
            lambda: sublime.ok_cancel_dialog(
                "Converting %s in the cloud costs %s credits, more than your limit of %d (setting "
                "max_credits).\n\nNothing is charged unless you go ahead."
                % (
                    os.path.basename(job.paths[job.index]),
                    credits,
                    max_credits,
                ),
                "Convert (%s Credits)" % credits,
            )
        )

    def work():
        written = []
        try:
            for index, path in enumerate(job.paths):
                job.index = index
                job.step = ""
                written.append(cloud.run(client, path, row.target, max_credits, progress, job.cancel.is_set, confirm))
        except api.Canceled:
            note = " (canceled; a conversion already started at Converter Studio may still finish there)"
            on_main(lambda: finished(job, written, note))
            return
        except api.ApiError as error:
            text = "Converter Studio could not convert %s in the cloud.\n\n%s" % (
                os.path.basename(job.paths[job.index]),
                cloud.message(error),
            )
            on_main(lambda: show_failure(job, written, text))
            return
        except OSError as error:
            text = "Converter Studio could not save the result: %s" % (error.strerror or error)
            on_main(lambda: show_failure(job, written, text))
            return
        on_main(lambda: finished(job, written))

    _ticker(job)
    threading.Thread(target=work, name="converter-studio-cloud", daemon=True).start()


# -- commands ----------------------------------------------------------------------------------


class ConverterStudioConvertCurrentFileCommand(sublime_plugin.WindowCommand):
    """Converter Studio: Convert Current File…"""

    def run(self, to=None, where=None):
        view = self.window.active_view()
        path = view.file_name() if view else None
        if not path:
            self.window.status_message("%s: save the file first, then convert it." % STATUS)
            return
        if view.is_dirty():
            answer = sublime.yes_no_cancel_dialog(
                "%s has unsaved changes. Save it before converting?" % os.path.basename(path),
                "Save and Convert",
                "Convert the Saved File",
            )
            if answer == sublime.DIALOG_CANCEL:
                return
            if answer == sublime.DIALOG_YES:
                view.run_command("save")
        start(self.window, [path], to, where)

    def is_enabled(self):
        view = self.window.active_view()
        return bool(view and view.file_name())


class ConverterStudioConvertFileCommand(sublime_plugin.WindowCommand):
    """Converter Studio: Convert File… (asks for one or more files)."""

    def run(self, paths=None, to=None, where=None):
        if paths:
            start(self.window, paths, to, where)
            return
        view = self.window.active_view()
        folder = None
        if view and view.file_name():
            folder = os.path.dirname(view.file_name())
        elif self.window.folders():
            folder = self.window.folders()[0]

        def picked(selection):
            if selection:
                start(self.window, selection if isinstance(selection, list) else [selection], to, where)

        sublime.open_dialog(picked, directory=folder, multi_select=True)


class ConverterStudioCancelCommand(sublime_plugin.WindowCommand):
    """Converter Studio: Cancel Conversion"""

    def run(self):
        job = current_job()
        if job:
            job.cancel.set()
            self.window.status_message("%s: stopping…" % STATUS)

    def is_enabled(self):
        return current_job() is not None


class ConverterStudioShowToolsCommand(sublime_plugin.WindowCommand):
    """Converter Studio: Show Local Tools (what was found and what it enables)."""

    def run(self):
        self.window.status_message("%s: looking for conversion tools on this computer…" % STATUS)

        def work():
            settings = read_settings()
            found = TOOLS.get(settings, refresh=True)
            state = desktop.is_installed(platform()) if settings.get("use_desktop_app") else None
            text = tools_report(found, settings, state)
            on_main(lambda: self.show(text))

        threading.Thread(target=work, name="converter-studio-tools", daemon=True).start()

    def show(self, text):
        panel = self.window.create_output_panel(PANEL)
        panel.run_command("append", {"characters": text, "force": True})
        self.window.run_command("show_panel", {"panel": "output." + PANEL})


def tools_report(found, settings, desktop_state):
    """The text of "Show Local Tools": every tool, what it enables here, and the other layers."""
    language = settings.get("ocr_language") or "eng"
    lines = ["Converter Studio %s for Sublime Text" % VERSION, ""]
    lines.append("1. On this computer (nothing is uploaded)")
    lines.append("")
    lines.append("   Python (built in): CSV to JSON and back; SRT, VTT and ASS subtitles")
    for spec in tools.SPECS:
        tool = found.get(spec.id)
        if tool is None or tool.path is None:
            reason = tool.problem if tool and tool.problem else "not found"
            lines.append("   %s: %s. Install it (%s) or set tool_paths.%s." % (spec.name, reason, spec.url, spec.id))
            continue
        version = (" " + tool.version) if tool.version else ""
        if tool.problem:
            lines.append("   %s%s at %s: not used, it %s." % (spec.name, version, tool.path, tool.problem.strip()))
            continue
        lines.append("   %s%s at %s" % (spec.name, version, tool.path))
        sources, targets, blocked = set(), [], []
        only = {spec.id: tool}
        for known in fmt.BY_ID.values():
            for choice in recipes.local_choices(known.id, only, language, with_unavailable=True):
                if choice.tool != spec.id:
                    continue
                if choice.reason:
                    if choice.reason not in blocked:
                        blocked.append(choice.reason)
                    continue
                sources.add(fmt.label(known.id))
                if choice.label not in targets:
                    targets.append(choice.label)
        if targets:
            lines.append("     %s: from %s" % (spec.what, ", ".join(sorted(sources))))
            lines.append("     to %s" % ", ".join(targets))
        for reason in blocked:
            lines.append("     not here: %s" % reason)
    if found.get("pandoc") and found["pandoc"].usable and found.get("soffice") and found["soffice"].usable:
        lines.append("   Pandoc and LibreOffice together: Markdown and EPUB to PDF")
    lines.append("")
    lines.append("2. Converter Studio desktop app (converts on this computer too)")
    if not settings.get("use_desktop_app"):
        lines.append("   Off. Turn on the setting use_desktop_app to hand files over to it.")
    elif desktop_state is False:
        lines.append(
            "   On, but not installed. It needs version %s or later: %s" % (DESKTOP_MIN_VERSION, DOWNLOAD_PAGE)
        )
    else:
        lines.append(
            "   On. Files are handed over to Converter Studio for desktop (version %s or later)." % DESKTOP_MIN_VERSION
        )
    lines.append("")
    lines.append("3. Converter Studio cloud (only when you pick it: the file is uploaded and uses credits)")
    if str(settings.get("api_key") or "").strip():
        lines.append("   API key: in your settings file (kept there in plain text)")
    elif os.environ.get(API_KEY_ENV):
        lines.append("   API key: from the environment variable %s" % API_KEY_ENV)
    else:
        lines.append("   API key: not set (%s)" % KEYS_PAGE)
    lines.append("   API address: %s" % (settings.get("api_url") or "https://converter.studio/api"))
    lines.append("   Privacy: %s" % PRIVACY_PAGE)
    return "\n".join(lines) + "\n"


class ConverterStudioShowAccountCommand(sublime_plugin.WindowCommand):
    """Converter Studio: Show Plan and Credits (asks converter.studio; sends no file)."""

    def run(self):
        settings = read_settings()
        client = cloud_client(settings)
        if client is None:
            return
        self.window.status_message("%s: asking converter.studio…" % STATUS)

        def work():
            try:
                account = client.account()
            except api.ApiError as error:
                text = "Converter Studio: " + cloud.message(error)
                on_main(lambda: sublime.error_message(text))
                return
            allowance = account.get("allowance") or {}
            lines = [
                "Converter Studio plan: %s" % account.get("plan", "?"),
                "Credits left: %s" % account.get("credits", "?"),
            ]
            if allowance:
                lines.append(
                    "Used %s of %s this %s." % (allowance.get("used"), allowance.get("limit"), allowance.get("per"))
                )
            text = "\n".join(lines)
            on_main(lambda: sublime.message_dialog(text))

        threading.Thread(target=work, name="converter-studio-account", daemon=True).start()


def edit_settings(window):
    """The defaults and the user's settings side by side, as "Preferences: Converter Studio Settings"."""
    window.run_command(
        "edit_settings",
        {
            "base_file": "${packages}/%s/%s" % (PACKAGE, SETTINGS_FILE),
            "default": "// Converter Studio: your settings (the defaults are on the left)\n{\n\t$0\n}\n",
        },
    )


def plugin_loaded():
    # Nothing is looked for or started here: the tools are found on the first conversion.
    sublime.load_settings(SETTINGS_FILE).add_on_change(PACKAGE, TOOLS.clear)


def plugin_unloaded():
    job = current_job()
    if job:
        job.cancel.set()
    sublime.load_settings(SETTINGS_FILE).clear_on_change(PACKAGE)
