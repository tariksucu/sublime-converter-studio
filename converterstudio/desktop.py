"""Handing files over to the Converter Studio desktop app.

The plugin opens `converter-studio://convert?to=<format>&from=sublime-text&file=<path>[&file=…]`
with the operating system and expects no reply. The desktop app (version DESKTOP_MIN_VERSION or
later) shows a card "Files from Sublime Text"; after Continue it preselects the format and waits
for the user to press Convert, and it converts on this computer. Older versions only come to the
front. Nothing is uploaded by this hand-over.

The app takes up to 200 files per hand-over and merges links with the same `from` and `to` that
arrive within 15 seconds, so a long selection is sent as several links of at most 2,000
characters (Windows' limit for opening an address).
"""

import os
import subprocess
from urllib.parse import quote

from . import CLIENT

SCHEME = "converter-studio"
MAX_FILES = 200
MAX_URL = 2000

# File systems whose files the desktop app cannot open as local files (Linux, /proc/mounts).
REMOTE_FILESYSTEMS = (
    "nfs",
    "nfs4",
    "cifs",
    "smb3",
    "smbfs",
    "9p",
    "afs",
    "davfs",
    "fuse.sshfs",
    "fuse.gvfsd-fuse",
    "fuse.rclone",
    "fuse.s3fs",
)


def _encode(value):
    # Every reserved character is encoded (`+ # & %` included), so no value can end the query.
    return quote(value, safe="")


def handoff_urls(to, paths, client=CLIENT, max_length=MAX_URL):
    """The addresses that hand `paths` to the desktop app with `to` chosen, each short enough."""
    head = "%s://convert?to=%s&from=%s" % (SCHEME, _encode(to), _encode(client))
    urls = []
    current = head
    for path in paths:
        part = "&file=" + _encode(os.path.abspath(path))
        if current != head and len(current) + len(part) > max_length:
            urls.append(current)
            current = head
        current += part
    if current != head:
        urls.append(current)
    return urls


def handoff_url(to, paths, client=CLIENT):
    """One address for all `paths` (however long)."""
    return handoff_urls(to, paths, client, max_length=10**9)[0]


def _mount_types(read=None):
    """[(mount point, file system type)] from /proc/mounts, the longest mount point first."""
    try:
        if read is None:
            with open("/proc/mounts", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        else:
            text = read()
    except OSError:
        return []
    mounts = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 3:
            point = fields[1].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
            mounts.append((point, fields[2]))
    return sorted(mounts, key=lambda m: len(m[0]), reverse=True)


def is_local_file(path, platform, mounts=None):
    """Whether a file is on this computer's own disk (not a network share or a remote mount)."""
    if platform == "windows":
        return not (path.startswith("\\\\") or path.startswith("//"))
    if "/gvfs/" in path or "/.gvfs/" in path:
        return False
    if platform != "linux":
        return True
    mounts = _mount_types() if mounts is None else mounts
    real = os.path.realpath(path)
    for point, kind in mounts:
        if real == point or real.startswith(point.rstrip("/") + "/"):
            return kind not in REMOTE_FILESYSTEMS
    return True


def open_argv(url, platform):
    """The command that opens an address on Linux and macOS (Windows uses os.startfile)."""
    if platform == "osx":
        return ["open", url]
    if platform == "linux":
        return ["xdg-open", url]
    return None


def is_installed(platform, run=None, exists=os.path.isdir, home=None):
    """Whether this computer knows the converter-studio:// address: True, False, or None (unknown).

    Linux asks xdg-mime for the handler; Windows reads the registry; macOS looks for the app in
    the Applications folders (the app may live elsewhere, so not finding it is "unknown").
    """
    if platform == "linux":
        run = run or _run
        code, out = run(["xdg-mime", "query", "default", "x-scheme-handler/" + SCHEME])
        if code is None:
            return None
        return bool(out.strip())
    if platform == "windows":
        try:
            import winreg
        except ImportError:
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, SCHEME + "\\shell\\open\\command"):
                return True
        except OSError:
            return False
    if platform == "osx":
        home = home or os.path.expanduser("~")
        for folder in ("/Applications", os.path.join(home, "Applications")):
            if exists(os.path.join(folder, "Converter Studio.app")):
                return True
        return None
    return None


def _run(argv):
    try:
        done = subprocess.run(  # noqa: S603 (an argument list, no shell)
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return done.returncode, done.stdout.decode("utf-8", "replace")


def open_url(url, platform, run=None, startfile=None):
    """Opens a hand-over address with the system; returns None, or a reason it failed.

    Never through a shell or cmd.exe (which would split the address at `&`).
    """
    if platform == "windows":
        startfile = startfile or getattr(os, "startfile", None)
        if startfile is None:
            return "this system cannot open converter-studio:// addresses"
        try:
            startfile(url)
        except OSError as error:
            return "Windows could not open it (%s)" % (error.strerror or error)
        return None
    argv = open_argv(url, platform)
    if argv is None:
        return "this system cannot open converter-studio:// addresses"
    if run is None:

        def run(argv):
            try:
                done = subprocess.run(  # noqa: S603 (an argument list, no shell)
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except (OSError, subprocess.SubprocessError) as error:
                return None, str(error)
            return done.returncode, done.stderr.decode("utf-8", "replace")

    code, err = run(argv)
    if code == 0:
        return None
    if code is None:
        return "%s could not be started (%s)" % (argv[0], err)
    return "no app opened it (%s exit code %s)" % (argv[0], code)
