#!/bin/sh
# Builds the Word review copy of the install manual.
# Needs: pandoc, zip, python3, node with playwright (Chromium).
# Usage: sh docs/install/tools/build_docx.sh [output.docx]
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-$HERE/../Adab-logger-install-practical-DRAFT.docx}
B=$(mktemp -d)
mkdir -p "$B/img" "$B/ref"
node "$HERE/render_png.js" "$B/img" "$HERE"/../schematics/*.svg
pandoc -o "$B/ref.docx" --print-default-data-file reference.docx
(cd "$B/ref" && unzip -q ../ref.docx)
python3 "$HERE/build_docx.py" "$OUT" "$B"
rm -rf "$B"
