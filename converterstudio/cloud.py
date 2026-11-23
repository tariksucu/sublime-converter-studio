"""One cloud conversion from start to finish: upload, convert, wait, download.

Runs only when the user picked the cloud. The file is uploaded to converter.studio and the
conversion uses credits of the user's account. Runs without Sublime Text: the caller passes what
to do on progress, how to tell it was cancelled, and how to ask when a file costs more credits
than allowed.
"""

import os
import tempfile
import time
import uuid

from . import KEYS_PAGE, PRICING_PAGE, naming
from . import formats as fmt
from .api import (
    FINAL,
    INSECURE_URL,
    NETWORK,
    NO_KEY,
    TLS,
    UNEXPECTED_URL,
    ApiError,
    Canceled,
)

# Seconds the API may hold one status request open while it waits for the conversion.
POLL_WAIT = 10

# A conversion that takes longer than this is given up (the API keeps working).
DEADLINE = 3 * 3600

UPLOAD = "uploading"
CONVERT = "converting"
DOWNLOAD = "downloading"


def message(error):
    """A sentence for the user. The API's own message first; never the key."""
    if error.message:
        text = error.message
    elif error.code == NO_KEY:
        text = (
            "A cloud conversion needs your Converter Studio API key. Create one at %s and put it in "
            "the setting api_key, or in the environment variable CONVERTER_STUDIO_API_KEY." % KEYS_PAGE
        )
    elif error.code == INSECURE_URL:
        text = "The setting api_url must be an https:// address (http:// only for this computer)."
    elif error.code == NETWORK:
        text = "Converter Studio could not be reached. Check the internet connection and try again."
    elif error.code == TLS:
        text = "The connection to Converter Studio could not be verified (certificate check failed)."
    elif error.code == UNEXPECTED_URL:
        text = "Converter Studio answered with an address on another server; nothing was sent there."
    elif error.code == "invalidApiKey":
        text = "Converter Studio did not accept the API key. Check it at %s." % KEYS_PAGE
    elif error.code == "notEnoughCredits":
        text = "Your Converter Studio account has not enough credits for this conversion. See %s." % PRICING_PAGE
    elif error.code == "fileChanged":
        text = "The file changed while it was being uploaded. Try again."
    elif error.code == "fileExpired":
        text = "The converted file is no longer available at Converter Studio. Convert it again."
    elif error.code == "conversionFailed":
        text = "Converter Studio could not convert this file."
    else:
        text = "Converter Studio answered with an error (%s)." % error.code
    return text


def run(
    client,
    path,
    to,
    max_credits,
    progress=None,
    cancelled=None,
    confirm=None,
    clock=time.monotonic,
    poll_wait=POLL_WAIT,
    deadline=DEADLINE,
):
    """Converts the file at `path` to `to` at Converter Studio; returns the path written.

    `progress(step, done, total)` is told how far it got; `cancelled()` is asked between
    requests; `confirm(credits)` is asked when the price is above `max_credits` and returns True
    to go on (no answer: nothing is charged).
    """
    report = progress or (lambda step, done, total: None)
    stop = cancelled or (lambda: False)

    def check():
        if stop():
            raise Canceled()

    name = os.path.basename(path)
    size = os.path.getsize(path)
    if size <= 0:
        raise ApiError(0, "emptyFile", "The file is empty.")
    check()
    upload = client.create_upload(name, size)
    client.send_file(upload, path, size, lambda done, total: report(UPLOAD, done, total), stop)
    check()
    view = client.convert(upload["id"], to, max_credits, str(uuid.uuid4()))
    started = clock()
    asked = False
    while True:
        status = view.get("status")
        report(CONVERT, int(view.get("progress") or 0), 100)
        if status == "done":
            break
        if status in FINAL:
            raise ApiError.from_view(view)
        if status == "quoted" and not asked:
            asked = True
            credits = view.get("credits")
            if confirm is None or not confirm(credits):
                raise Canceled()
            check()
            view = client.confirm(view["id"])
            continue
        if clock() - started > deadline:
            raise ApiError(0, "timeout", "The conversion did not finish in time; it goes on at Converter Studio.")
        check()
        view = client.conversion(view["id"], wait=poll_wait)

    check()
    output_name = view.get("outputName") or "%s.%s" % (fmt.stem(path), fmt.extension(to))
    stem, extension = _split(output_name, to)
    directory = os.path.dirname(os.path.abspath(path))
    handle, temporary = tempfile.mkstemp(prefix="converter-studio-", suffix="." + (extension or "out"))
    os.close(handle)
    try:
        client.download(
            view.get("downloadUrl") or "",
            temporary,
            lambda done, total: report(DOWNLOAD, done, total),
            stop,
        )
        check()
        return naming.place(temporary, directory, stem, extension)
    finally:
        try:
            os.remove(temporary)
        except OSError:
            pass


def _split(file_name, to):
    """(stem, extension) of the API's output name; a ZIP stays a ZIP."""
    file_name = os.path.basename(file_name)
    extension = fmt.extension(to)
    if file_name.lower().endswith("." + extension):
        return file_name[: -len(extension) - 1], extension
    root, ext = os.path.splitext(file_name)
    return root or "converted", ext.lstrip(".")
