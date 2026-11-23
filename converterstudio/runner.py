"""Runs one conversion tool: an argument list, a time limit, and a way to stop it.

The tool's output goes to a temporary file (a pipe nobody reads could fill up and stall it); only
its last lines are kept, to explain a failure. On cancel or timeout the tool and everything it
started are stopped: its own process group on Linux and macOS, `taskkill /T` on Windows.
"""

import os
import signal
import subprocess
import tempfile
import time

# How often the tool is checked on while it runs, in seconds.
POLL = 0.1

# How long a stopped tool gets to end before it is killed, in seconds.
GRACE = 3.0

# How much of the tool's output is kept for an error message.
TAIL_BYTES = 4000


class Result:
    def __init__(self, code, output, canceled=False, timed_out=False, error=None):
        self.code = code
        self.output = output
        self.canceled = canceled
        self.timed_out = timed_out
        # The tool could not be started at all (missing, not executable): a sentence.
        self.error = error

    @property
    def ok(self):
        return self.code == 0 and not self.canceled and not self.timed_out and self.error is None

    def summary(self, limit=600):
        """The last lines of the tool's output, for an error message."""
        text = (self.output or "").strip()
        if len(text) > limit:
            text = "…" + text[-limit:]
        return text


def _stop(process, windows):
    if process.poll() is not None:
        return
    if windows:
        try:
            taskkill = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "taskkill.exe")
            subprocess.run(  # noqa: S603 (Windows's own taskkill, an argument list)
                [taskkill, "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        if process.poll() is None:
            process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        process.terminate()
    deadline = time.monotonic() + GRACE
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(POLL)
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()


def run(argv, timeout, cancelled=None, cwd=None, env=None, windows=None, clock=time.monotonic):
    """Runs `argv` until it ends, `timeout` seconds pass, or `cancelled()` turns true."""
    windows = os.name == "nt" if windows is None else windows
    stop = cancelled or (lambda: False)
    full_env = None
    if env:
        full_env = dict(os.environ)
        full_env.update(env)
    with tempfile.TemporaryFile() as log:
        try:
            process = subprocess.Popen(  # noqa: S603 (an argument list, no shell)
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                env=full_env,
                # No console window on Windows; elsewhere its own process group, so that a stop
                # reaches the programs it starts (soffice.bin).
                creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if windows else 0,
                start_new_session=not windows,
            )
        except OSError as error:
            return Result(None, "", error="could not be started (%s)" % (error.strerror or error))
        deadline = clock() + timeout
        canceled = timed_out = False
        try:
            while process.poll() is None:
                if stop():
                    canceled = True
                    break
                if clock() >= deadline:
                    timed_out = True
                    break
                time.sleep(POLL)
        finally:
            if process.poll() is None:
                _stop(process, windows)
                try:
                    process.wait(timeout=GRACE)
                except subprocess.TimeoutExpired:
                    pass
        log.seek(0, os.SEEK_END)
        size = log.tell()
        log.seek(max(0, size - TAIL_BYTES))
        output = log.read().decode("utf-8", "replace")
    return Result(process.returncode, output, canceled=canceled, timed_out=timed_out)
