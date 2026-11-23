"""One conversion on this computer, from start to finish.

The tool writes into a new, empty working folder; the result is then copied next to the source
under a free name, and the working folder is removed. Nothing is sent anywhere.
"""

import os
import shutil
import tempfile
import time

from . import builtin, naming, recipes, runner
from . import formats as fmt
from .tools import SPEC_BY_ID


class Canceled(Exception):
    """The user stopped the conversion; nothing was saved."""


class LocalFailure(Exception):
    """A local conversion did not work. `details` holds the tool's last lines, if any."""

    def __init__(self, message, details=""):
        super().__init__(message)
        self.message = message
        self.details = details


def _outputs(work_dir):
    found = []
    for name in os.listdir(work_dir):
        path = os.path.join(work_dir, name)
        if os.path.isfile(path) and not name.startswith("."):
            found.append(path)
    return sorted(found)


def convert(choice, source_path, found, settings, cancelled=None, run=runner.run):
    """Converts `source_path` as `choice` says; returns the paths written (files or a folder).

    `found` is {tool id: Tool}; `settings` a dict with `timeout_seconds`, `ocr_language` and
    `soffice_profile` (a folder for LibreOffice's own settings, kept between conversions).
    """
    stop = cancelled or (lambda: False)
    if choice.tool != "python":
        for tool_id in recipes.tools_of(choice.tool):
            tool = found.get(tool_id)
            if tool is None or not tool.usable:
                raise LocalFailure("%s is not available on this computer." % recipes.TOOL_NAMES[tool_id])
    directory = os.path.dirname(os.path.abspath(source_path))
    stem = fmt.stem(source_path, choice.source)
    work_dir = tempfile.mkdtemp(prefix="converter-studio-")
    try:
        plan = recipes.build(
            choice,
            os.path.abspath(source_path),
            work_dir,
            found,
            language=settings.get("ocr_language") or "eng",
            profile_dir=settings.get("soffice_profile"),
        )
        for folder in plan.folders:
            os.makedirs(folder, exist_ok=True)
        if plan.function is not None:
            if stop():
                raise Canceled()
            try:
                plan.function(source_path, plan.output)
            except builtin.ConversionError as error:
                raise LocalFailure(str(error))
            except (OSError, ValueError) as error:
                raise LocalFailure("The file could not be converted: %s" % error)
        timeout = float(settings.get("timeout_seconds") or 600)
        deadline = time.monotonic() + timeout
        for argv, tool_id in zip(plan.steps, recipes.tools_of(choice.tool)):
            name = SPEC_BY_ID[tool_id].name
            result = run(argv, max(1.0, deadline - time.monotonic()), stop, cwd=work_dir, env=plan.env)
            if result.canceled:
                raise Canceled()
            if result.error:
                raise LocalFailure("%s %s." % (name, result.error))
            if result.timed_out:
                raise LocalFailure(
                    "%s did not finish in %d seconds (the limit is the setting timeout_seconds)." % (name, timeout),
                    result.summary(),
                )
            if result.code != 0:
                raise LocalFailure(
                    "%s could not convert the file (exit code %s)." % (name, result.code), result.summary()
                )
        if stop():
            raise Canceled()
        produced = _outputs(work_dir)
        if not produced:
            tool_name = recipes.TOOL_NAMES[choice.tool]
            raise LocalFailure("%s finished without writing a %s file." % (tool_name, fmt.label(choice.target)))
        if len(produced) == 1:
            produced_name = os.path.basename(produced[0])
            out_stem, out_ext = _split(produced_name, choice.target)
            if choice.variant == recipes.PAGES:
                out_stem = stem
            return [naming.place(produced[0], directory, out_stem, out_ext)]
        folder = "%s (%s pages)" % (stem, fmt.label(choice.target))
        return [naming.place_many(produced, directory, folder)]
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _split(file_name, target):
    """(stem, extension) of a produced file, with the target's extension when it has it."""
    extension = fmt.extension(target)
    if file_name.lower().endswith("." + extension):
        return file_name[: -len(extension) - 1], extension
    root, ext = os.path.splitext(file_name)
    return root, ext.lstrip(".")
