#!/usr/bin/env python3
"""Bake the certificate's fonts out of the site's own web fonts.

A PDF cannot use `assets/fonts/*.woff2` as they stand, for two reasons. They are
variable, and the optical-size axis matters here: a browser quietly picks the
high-contrast cut for a 50px title and the sturdier one for body text, and a PDF
writer does neither. And each face is split into `latin` and `latin-ext`, with
"á" in one file and "ř" in the other, which only works because a browser reads
`unicode-range`.

So this pins each cut the certificate uses and merges the two halves into one
static TrueType file, written to `assets/fonts/certificate/`. The results are
committed, so this only needs running again if the cuts below change:

    uv run --with brotli python certificate_fonts.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fontTools.merge import Merger
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

FONTS = Path(__file__).resolve().parent / "assets" / "fonts"
OUT = FONTS / "certificate"

# name -> (source stem, pinned axes). `opsz` is the size in CSS px each is set at.
CUTS = {
    "bodoni-title": ("bodoni-moda-italic", {"wght": 400, "opsz": 48}),
    "bodoni-italic": ("bodoni-moda-italic", {"wght": 400, "opsz": 22}),
    "bodoni-text": ("bodoni-moda-normal", {"wght": 400, "opsz": 16}),
    "jost": ("jost-normal", {"wght": 400}),
    "jost-medium": ("jost-normal", {"wght": 500}),
}


def bake(name: str, stem: str, axes: dict[str, float]) -> Path:
    with tempfile.TemporaryDirectory() as work:
        halves = []
        for subset in ("latin", "latin-ext"):
            font = TTFont(FONTS / f"{stem}-{subset}.woff2")
            font = instancer.instantiateVariableFont(font, axes, inplace=False)
            font.flavor = None
            half = Path(work) / f"{subset}.ttf"
            font.save(half)
            halves.append(str(half))

        merged = Merger().merge(halves)
        target = OUT / f"{name}.ttf"
        merged.save(target)
    return target


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (stem, axes) in CUTS.items():
        target = bake(name, stem, axes)
        cmap = TTFont(target).getBestCmap()
        missing = [c for c in "áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ·×–" if ord(c) not in cmap]
        print(f"{target.name}: {target.stat().st_size // 1024} kB, missing {missing or 'nothing'}")


if __name__ == "__main__":
    main()
