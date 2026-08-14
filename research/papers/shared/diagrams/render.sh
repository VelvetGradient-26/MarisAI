#!/usr/bin/env bash
# Render every .mmd diagram to PDF (for LaTeX) and SVG (for the web artifact).
#
# The .mmd files are the single source of truth: the manuscript and the
# published artifact draw the same diagram from the same text, so the two
# cannot drift. Requires `npm install -g @mermaid-js/mermaid-cli`.
set -euo pipefail

cd "$(dirname "$0")"

for source in *.mmd; do
    name="${source%.mmd}"
    echo "rendering ${name}"
    # White background rather than the default transparent: a transparent PDF
    # over a white page is fine, but the SVG is embedded in a themed artifact
    # where transparent lets a dark background bleed through the labels.
    mmdc --input "${source}" --output "${name}.svg" --backgroundColor white --quiet
    mmdc --input "${source}" --output "${name}.pdf" --backgroundColor white --pdfFit --quiet
done

echo "done: $(ls -1 ./*.pdf | wc -l | tr -d ' ') PDF, $(ls -1 ./*.svg | wc -l | tr -d ' ') SVG"
