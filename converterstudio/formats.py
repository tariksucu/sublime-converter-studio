"""Formats by id and by file extension, from the catalogue snapshot (catalog.py)."""

import os

from .catalog import FORMATS


class Format:
    __slots__ = ("id", "name", "category", "extensions", "targets")

    def __init__(self, format_id, name, category, extensions, targets):
        self.id = format_id
        self.name = name
        self.category = category
        self.extensions = extensions
        self.targets = targets

    @property
    def extension(self):
        """The extension a file of this format is written with (`jpg`, `tar.gz`)."""
        return self.extensions[0]


BY_ID = {row[0]: Format(*row) for row in FORMATS}

# Extension (lower case, no dot) → format id; the longest first so that `tar.gz` wins over `gz`.
_BY_EXTENSION = {}
for _format in BY_ID.values():
    for _extension in _format.extensions:
        _BY_EXTENSION.setdefault(_extension, _format.id)
_EXTENSIONS = sorted(_BY_EXTENSION, key=len, reverse=True)


def get(format_id):
    """The Format with this id, or None."""
    return BY_ID.get(format_id)


def detect(path):
    """The format id of a file, from its name (`photo.JPEG` → `jpg`), or None."""
    name = os.path.basename(path).lower()
    for extension in _EXTENSIONS:
        if name.endswith("." + extension) and len(name) > len(extension) + 1:
            return _BY_EXTENSION[extension]
    return None


def stem(path, format_id=None):
    """The file name without its extension (`report.tar.gz` → `report` for `tgz`)."""
    name = os.path.basename(path)
    known = BY_ID.get(format_id) if format_id else None
    if known:
        lower = name.lower()
        for extension in sorted(known.extensions, key=len, reverse=True):
            if lower.endswith("." + extension) and len(name) > len(extension) + 1:
                return name[: -len(extension) - 1]
    root, _ = os.path.splitext(name)
    return root or name


def label(format_id):
    """How a format is called in the picker: the catalogue's name, or the id in capitals."""
    known = BY_ID.get(format_id)
    return known.name if known else format_id.upper()


def extension(format_id):
    """The extension a result of this format gets."""
    known = BY_ID.get(format_id)
    return known.extension if known else format_id


def cloud_targets(source_ids):
    """What every one of these formats can become at Converter Studio, the most used first."""
    if not source_ids:
        return ()
    first = BY_ID.get(source_ids[0])
    if not first:
        return ()
    shared = list(first.targets)
    for source in source_ids[1:]:
        known = BY_ID.get(source)
        allowed = set(known.targets) if known else set()
        shared = [t for t in shared if t in allowed]
    return tuple(shared)
