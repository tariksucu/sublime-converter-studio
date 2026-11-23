"""Converter Studio for Sublime Text: the parts that do not need Sublime Text.

Nothing in this package imports ``sublime``: it runs (and is tested) with any Python 3.8 or
later. The plugin (``converter_studio.py`` at the package's root) holds everything that talks to
the editor.

Three ways to convert a file, in this order:

1. On this computer: a few conversions in plain Python, and the tools already installed here
   (FFmpeg, LibreOffice, Pandoc, ImageMagick, Ghostscript, Tesseract). Nothing leaves the computer.
2. The Converter Studio desktop app, when the user turns it on: the file is handed over to the
   app, which converts it on this computer too.
3. The Converter Studio cloud, only when the user picks it: the file is uploaded to
   converter.studio and the conversion uses credits of the user's account.
"""

# Kept equal to the newest version in CHANGELOG.md and the release tag (a unit test checks it).
VERSION = "1.0.0"

# Names this package to the API (X-Converter-Studio-Client), for converter.studio's statistics.
CLIENT = "sublime-text"

SITE = "https://converter.studio"
DEFAULT_BASE_URL = SITE + "/api"
KEYS_PAGE = SITE + "/account#api-keys"
PRIVACY_PAGE = SITE + "/privacy"
PRICING_PAGE = SITE + "/pricing"
DOWNLOAD_PAGE = SITE + "/download"

# The first Converter Studio desktop release that takes files from editors
# (converter-studio://convert). Older versions only come to the front.
DESKTOP_MIN_VERSION = "0.1.11"

# The environment variable that holds the API key when the settings file does not.
API_KEY_ENV = "CONVERTER_STUDIO_API_KEY"
