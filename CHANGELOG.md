# Changelog

## 1.0.1 - 2026-11-25

The built-in CSV and JSON conversions no longer lose or change data.

- CSV to JSON: every column gets a name of its own, checked against every other name: `id,id,id_2`
  lost a value before, now it gives `id`, `id_3`, `id_2`. Cells beyond the header are columns
  (`column4`) in every object, instead of an `_extra` list in some of them. A row of spaces or of
  separators only is a record too.
- CSV is read by the plugin's own reader, the same as in the other editors: a quote that never ends
  is refused (Python's reader took the rest of the file as one value), and the separator is the one
  the first line uses most outside quotes.
- JSON to CSV: numbers are written as the file writes them (1.50 became 1.5 and 1e400 became
  `inf`); NaN and Infinity, which are not JSON, are refused. A value with a space or tab at either
  end is quoted.
- The four editor plugins (VS Code, JetBrains, Sublime Text, Neovim) now follow the same rules and run the same test cases, so a file gives the same result in each.

## 1.0.0 - 2026-11-23

- Converter Studio: Convert Current File… and Convert File… from the Command Palette, with a list of
  target formats that says where each conversion runs.
- On this computer: FFmpeg, LibreOffice, Pandoc, ImageMagick, Ghostscript and Tesseract when they are
  installed, and CSV ↔ JSON and SRT, VTT and ASS subtitles in plain Python. Nothing is uploaded.
- Hand-over to the Converter Studio desktop app (version 0.1.11 or later), when turned on.
- The Converter Studio cloud, only when you pick it; a failed local conversion offers it, never uses it
  on its own.
- Progress in the status bar, Cancel Conversion, results saved next to the original without
  overwriting anything.
