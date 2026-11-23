"""Where a result is written: next to its source, never over an existing file.

`photo.jpg` is taken → `photo (2).jpg`, then `photo (3).jpg`… The name is claimed by creating the
file (or folder) exclusively, so two conversions finishing at once cannot pick the same one.
"""

import errno
import os
import shutil

# A file name longer than this is shortened (most file systems allow 255 bytes).
MAX_NAME = 240


def _name(stem, number, extension):
    suffix = "" if number == 1 else " (%d)" % number
    ext = "." + extension if extension else ""
    room = MAX_NAME - len(suffix) - len(ext)
    return stem[:room] + suffix + ext


def candidate_names(stem, extension, limit=10000):
    for number in range(1, limit + 1):
        yield _name(stem, number, extension)


def claim_file(directory, stem, extension):
    """Creates an empty file with the first free name and returns its path."""
    for name in candidate_names(stem, extension):
        path = os.path.join(directory, name)
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        except OSError as error:
            if error.errno == errno.EEXIST or os.path.exists(path):
                continue
            raise
        os.close(handle)
        return path
    raise OSError(errno.EEXIST, "no free name", os.path.join(directory, stem))


def claim_folder(directory, name):
    """Creates an empty folder with the first free name and returns its path."""
    for candidate in candidate_names(name, ""):
        path = os.path.join(directory, candidate)
        try:
            os.mkdir(path)
        except OSError as error:
            if error.errno == errno.EEXIST or os.path.exists(path):
                continue
            raise
        return path
    raise OSError(errno.EEXIST, "no free name", os.path.join(directory, name))


def place(produced, directory, stem, extension):
    """Copies a finished file to a free name in `directory`; returns the new path."""
    path = claim_file(directory, stem, extension)
    try:
        shutil.copyfile(produced, path)
    except BaseException:
        _remove(path)
        raise
    return path


def place_many(produced, directory, folder_name):
    """Copies several finished files into a new folder in `directory`; returns the folder."""
    folder = claim_folder(directory, folder_name)
    try:
        for path in sorted(produced):
            shutil.copyfile(path, os.path.join(folder, os.path.basename(path)))
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return folder


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
