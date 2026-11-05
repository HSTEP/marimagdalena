"""Certificates of authenticity for sold paintings, as A4 landscape PDFs.

Everything is drawn at fixed positions, in the CSS pixels of the approved design
(1123 x 794), rather than through an HTML-to-PDF engine. WeasyPrint would need
Pango in the image and headless Chrome several hundred megabytes of it, all for
one page whose layout never changes. These dependencies are plain wheels.

The on-screen preview is this same PDF rasterised, so what she checks on her
phone is what prints. A separate HTML preview would have been a second layout to
keep in step with this one.

Nothing here writes to disk. A certificate carries a buyer's name and this
repository is public, so names must never end up in `src/data/`.
"""

from __future__ import annotations

import io
import itertools
import math
import re
import threading
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pypdfium2
from fpdf import FPDF
from PIL import Image, ImageOps

from build import SITE

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "assets" / "fonts" / "certificate"

# The design's canvas, and how many PDF points one of its pixels is.
PAGE_W, PAGE_H = 1123, 794
PT = 841.89 / PAGE_W

INK = (0x14, 0x11, 0x0D)
MUTED = (0x5B, 0x53, 0x47)
PAPER = (0xFB, 0xF9, 0xF5)
GOLD = (0x9C, 0x83, 0x38)
WHITE = (0xFF, 0xFF, 0xFF)

TITLE, ITALIC, TEXT, SANS, SANS_MEDIUM = (
    "bodoni-title",
    "bodoni-italic",
    "bodoni-text",
    "jost",
    "jost-medium",
)
FACES = (TITLE, ITALIC, TEXT, SANS, SANS_MEDIUM)

PANEL_W = 440
LEFT = PANEL_W + 60  # Where the text column starts.
RIGHT = PAGE_W - 64
COLUMN = RIGHT - LEFT

# Every painting gets the area of the design's 300 x 380 frame, so a wide one
# and a tall one weigh the same on the page, within what the panel can hold.
PHOTO_AREA = 300 * 380
PHOTO_MAX_W, PHOTO_MAX_H = 340, 480
MAT = 12
# 300 dpi at the largest. The sources run to 8 MB and nobody can print the rest.
PHOTO_PIXELS = (1063, 1500)
LOGO_W = 150

# What the logo says. SITE's tagline keeps "Hair" for page titles and schema.
SALON = "Art Salon"

STATEMENT = "Tímto potvrzuji, že toto dílo je původní originál, který jsem vlastnoručně namalovala."

# PDFium may only ever be entered from one thread at a time, and FastAPI runs
# these routes on a pool: two previews at once would take the whole server down.
_PDFIUM = threading.Lock()


class Unprintable(ValueError):
    """Text the certificate's typefaces cannot draw.

    Refused rather than drawn, because the alternative is an empty box in the
    middle of a buyer's name, on a document she has already signed.
    """


@dataclass(frozen=True)
class Certificate:
    number: int
    title: str
    year: str = ""
    technique: str = ""
    size: str = ""
    buyer: str = ""
    date: str = ""


def clean(text: str) -> str:
    """One line of NFC text: an iPhone can send "ř" as "r" plus a loose caron."""
    return " ".join(unicodedata.normalize("NFC", text or "").split())


def tidy_size(text: str) -> str:
    """`60x80` and `60 x 80 cm` both become `60 × 80 cm`. Anything else is left alone."""
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*[xX×*/]\s*(\d+(?:[.,]\d+)?)(?:\s*cm)?", text)
    return f"{match[1]} × {match[2]} cm" if match else text


def _mix(colour: tuple[int, int, int], over: tuple[int, int, int], amount: float):
    """`colour` at `amount` opacity on `over`. Solid, so no printer has to blend."""
    return tuple(round(c * amount + o * (1 - amount)) for c, o in zip(colour, over))


@lru_cache(maxsize=1)
def _logo() -> tuple[bytes, float]:
    """The logo at twice its printed resolution, and its height per unit width."""
    with Image.open(HERE / SITE["logo_dark"]) as logo:
        logo.thumbnail((940, 940))
        out = io.BytesIO()
        logo.save(out, "PNG", optimize=True)
        return out.getvalue(), logo.height / logo.width


def _photo(path: Path) -> tuple[bytes, float, tuple[int, int, int]]:
    """The photograph as print-sized JPEG, its aspect ratio, and its panel colour.

    The panel is the painting's commonest colour let down heavily into the paper,
    which is what makes each certificate its own painting's. Commonest and not
    average, because the average of a colourful canvas is mud.
    """
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    palette = image.resize((64, 64), Image.Resampling.BOX).quantize(8)
    _, index = max(palette.getcolors())
    commonest = tuple(palette.getpalette()[index * 3 : index * 3 + 3])
    image.thumbnail(PHOTO_PIXELS, Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue(), image.width / image.height, _mix(commonest, PAPER, 0.16)


class _Page:
    """FPDF, spoken to in the design's pixels and baselines."""

    def __init__(self) -> None:
        self.pdf = FPDF(orientation="L", unit=PT, format=(PAGE_H, PAGE_W))
        self.pdf.set_auto_page_break(False)
        self.pdf.set_margin(0)
        self.pdf.c_margin = 0
        for face in FACES:
            self.pdf.add_font(face, fname=FONT_DIR / f"{face}.ttf")
        # Kerning. Without it a 50px Bodoni title has visible holes in it.
        self.pdf.set_text_shaping(True, direction="ltr", script="latn", language="ces")
        self.pdf.add_page()

    def font(self, face: str, size: float, spacing: float = 0) -> None:
        self.pdf.set_font(face, size=size * PT)
        self.pdf.set_char_spacing(spacing * PT)

    def width(self, text: str, face: str, size: float, spacing: float = 0) -> float:
        self.font(face, size, spacing)
        return self.pdf.get_string_width(text)

    def text(self, x, baseline, text, face, size, colour=INK, spacing: float = 0) -> None:
        """One line, kerned, with its baseline at `baseline`.

        Through `cell()` because `FPDF.text()` skips text shaping: no kerning, and
        a line that comes out wider than `get_string_width` said it would. A cell
        as tall as its font sets the baseline 0.8 of the way down.
        """
        self.font(face, size, spacing)
        self.pdf.set_text_color(*colour)
        height = self.pdf.font_size
        self.pdf.set_xy(x, baseline - 0.8 * height)
        self.pdf.cell(self.pdf.get_string_width(text), height, text)

    def baseline(self, top: float, line_height: float, face: str, size: float) -> float:
        """Where CSS would put the baseline of a line box starting at `top`."""
        self.font(face, size)
        desc = self.pdf.current_font.desc
        ascent, descent = desc.ascent / 1000 * size, -desc.descent / 1000 * size
        return top + (line_height - ascent - descent) / 2 + ascent

    def fit(self, text: str, face: str, size: float, room: float, spacing: float = 0) -> float:
        """The largest size up to `size` at which one line of `text` fits in `room`."""
        return size * min(1, room / max(self.width(text, face, size, spacing), 1))

    def fill(self, x, y, w, h, colour) -> None:
        self.pdf.set_fill_color(*colour)
        self.pdf.rect(x, y, w, h, style="F")

    def hairline(self, x1, y, x2, colour, weight: float = 1) -> None:
        self.pdf.set_draw_color(*colour)
        self.pdf.set_line_width(weight)
        self.pdf.line(x1, y, x2, y)

    def ring(self, x, y, radius, colour, weight: float) -> None:
        self.pdf.set_draw_color(*colour)
        self.pdf.set_line_width(weight)
        self.pdf.circle(x, y, radius, style="D")


def _lines(
    page: _Page, text: str, face: str, size: float, room: float, at_least: int = 1, at_most: int = 3
) -> list[str] | None:
    """Break `text` into the fewest lines that fit, as evenly as they will go.

    Some breaks are only taken if nothing else fits: after a one-letter Czech
    preposition, before a dash, and through the middle of a name, which is what
    keeps "Lilie pro / Maří Magdalenu" from becoming "Lilie pro Maří / Magdalenu".
    None if it cannot be done in `at_most` lines.
    """
    words = text.split()

    def width(line: list[str]) -> float:
        return page.width(" ".join(line), face, size)

    for count in range(min(at_least, len(words)), min(at_most, len(words)) + 1):
        fitting = []
        for cuts in itertools.combinations(range(1, len(words)), count - 1):
            edges = (0, *cuts, len(words))
            lines = [words[a:b] for a, b in zip(edges, edges[1:])]
            if all(width(line) <= room for line in lines):
                ugly = sum(
                    (len(before[-1]) == 1 and before[-1].isalpha())
                    + (not after[0][0].isalnum())
                    + (before[-1][0].isupper() and after[0][0].isupper())
                    for before, after in zip(lines, lines[1:])
                )
                fitting.append((ugly, max(width(line) for line in lines), lines))
        if fitting:
            return [" ".join(line) for line in min(fitting, key=lambda f: f[:2])[2]]
    return None


def _title(page: _Page, title: str, top: float) -> float:
    """The title, shrinking only as far as it takes to stay on two lines.

    A long title goes on two lines even where one would fit: the design is drawn
    around that, and a single line running the full width of the column looks
    like a heading on a form.
    """
    for size in (50, 44, 38, 32, 28, 24):
        at_least = 2 if page.width(title, TITLE, size) > COLUMN * 0.75 else 1
        lines = _lines(page, title, TITLE, size, COLUMN, at_least, 3 if size == 24 else 2)
        if lines:
            break
    else:
        # One unbroken run of letters wider than the page. It still has to print.
        size, lines = page.fit(title, TITLE, 24, COLUMN), [title]
    leading = size * 1.06
    for line in lines:
        page.text(LEFT, page.baseline(top, leading, TITLE, size), line, TITLE, size)
        top += leading
    return top


def _seal(page: _Page, x: float, y: float, number: int) -> None:
    """The round stamp, drawn around its centre.

    The lettering goes on a character at a time with the spacing worked out so
    that it closes the ring exactly, whatever the name adds up to.
    """
    ring = f"{SITE['person']} · ORIGINÁL · {SITE['city']} · ".upper()
    size, radius = 11, 52
    cx, cy = x + 75, y + 75

    page.ring(cx, cy, 73, GOLD, 1.5)
    page.ring(cx, cy, 68, GOLD, 1)
    page.ring(cx, cy, 40, GOLD, 1)

    advances = [page.width(char, SANS, size) for char in ring]
    gap = (2 * math.pi * radius - sum(advances)) / len(ring)
    # Starts at nine o'clock and runs clockwise, over the top.
    travelled = 0.0
    for char, advance in zip(ring, advances):
        angle = math.pi + (travelled + advance / 2) / radius
        travelled += advance + gap
        if char == " ":
            continue
        px, py = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
        with page.pdf.rotation(-math.degrees(angle) - 90, px, py):
            page.text(px - advance / 2, py, char, SANS, size, GOLD)

    width = page.width("MM", ITALIC, 30)
    page.text(cx - width / 2, y + 80, "MM", ITALIC, 30, GOLD)
    code = f"{number:03d}"
    width = page.width(code, SANS, 12, 1.5)
    page.text(cx - width / 2, y + 98, code, SANS, 12, GOLD, 1.5)


def render_pdf(certificate: Certificate, photo: Path) -> bytes:
    """One A4 landscape page. Raises `Unprintable` for text the fonts lack."""
    page = _Page()
    pdf = page.pdf
    title = clean(certificate.title)
    year, technique = clean(certificate.year), clean(certificate.technique)
    size, buyer = tidy_size(clean(certificate.size)), clean(certificate.buyer)
    date = clean(certificate.date)

    # Everything she can type is checked before any of it is drawn.
    printable = set.intersection(*(set(pdf.fonts[face].cmap) for face in FACES))
    for char in title + year + technique + size + buyer + date:
        if not char.isspace() and ord(char) not in printable:
            raise Unprintable(char)

    pdf.set_title(f"Certifikát pravosti — {title}")
    pdf.set_author(SITE["person"])
    pdf.set_creator(f"{SITE['name']} — {SALON}")
    pdf.set_lang("cs")

    jpeg, ratio, panel = _photo(photo)

    page.fill(0, 0, PAGE_W, PAGE_H, PAPER)
    page.fill(0, 0, PANEL_W, PAGE_H, panel)

    # The whole painting, in its own proportions. Cropping to fit a frame would
    # be an odd thing to do on the one document that says what the painting is.
    w = min(math.sqrt(PHOTO_AREA * ratio), PHOTO_MAX_W, PHOTO_MAX_H * ratio)
    h = w / ratio
    x, y = (PANEL_W - w) / 2, (PAGE_H - h) / 2
    page.fill(x - MAT, y - MAT, w + 2 * MAT, h + 2 * MAT, WHITE)
    pdf.set_draw_color(*_mix(INK, panel, 0.14))
    pdf.set_line_width(1)
    pdf.rect(x - MAT, y - MAT, w + 2 * MAT, h + 2 * MAT, style="D")
    pdf.image(io.BytesIO(jpeg), x=x, y=y, w=w, h=h)

    # Header: the kicker on the left, the logo on the right, centred on each other.
    logo, logo_ratio = _logo()
    logo_h = LOGO_W * logo_ratio
    header_mid = 56 + logo_h / 2
    pdf.set_fill_color(*GOLD)
    pdf.circle(LEFT + 4, header_mid, 4, style="F")
    page.text(
        LEFT + 20,
        page.baseline(header_mid - 10, 20, SANS, 13),
        "CERTIFIKÁT PRAVOSTI",
        SANS,
        13,
        MUTED,
        3.9,
    )
    pdf.image(io.BytesIO(logo), x=RIGHT - LOGO_W, y=56, w=LOGO_W, h=logo_h)

    top = _title(page, title, 56 + logo_h + 40)

    # What the painting is.
    top += 20
    details = [
        (SITE["person"], SANS_MEDIUM),
        (" · ".join(part for part in (year, technique) if part), SANS),
        (
            " · ".join(
                part for part in (size, f"evidenční č. MM-{certificate.number:03d}") if part
            ),
            SANS,
        ),
    ]
    for line, face in details:
        if line:
            page.text(LEFT, page.baseline(top, 25.6, face, 16), line, face, 16)
            top += 25.6

    top += 24
    page.hairline(LEFT, top, RIGHT, _mix(INK, PAPER, 0.22))
    top += 1 + 22

    for line in _lines(page, STATEMENT, TEXT, 16, 520):
        page.text(LEFT, page.baseline(top, 24.8, TEXT, 16), line, TEXT, 16)
        top += 24.8

    if buyer:
        top += 12
        line = f"Vystaveno pro {buyer}"
        lines = _lines(page, line, ITALIC, 22, COLUMN, at_most=2)
        fitted = 22 if lines else page.fit(line, ITALIC, 22, COLUMN)
        for line in lines or [line]:
            page.text(LEFT, page.baseline(top, 30, ITALIC, fitted), line, ITALIC, fitted)
            top += 30

    # The bottom block hangs from the foot of the page, whatever is above it.
    footer = (
        f"{SITE['name']} · {SALON} · {SITE['street']}, {SITE['zip']} {SITE['city']}"
        f" · {SITE['url'].removeprefix('https://')}"
    )
    footer_size = page.fit(footer, SANS, 12, COLUMN, 0.48)
    footer_top = PAGE_H - 48 - 17
    page.text(
        LEFT,
        page.baseline(footer_top, 17, SANS, footer_size),
        footer,
        SANS,
        footer_size,
        MUTED,
        0.48,
    )

    seal_top = footer_top - 22 - 150
    _seal(page, LEFT, seal_top, certificate.number)

    # Place and date on one rule, the blank one for her signature on the other.
    columns_left = LEFT + 150 + 36
    column = (RIGHT - columns_left - 36) / 2
    label_top = seal_top + 150 - 4 - 17
    rule = label_top - 8
    place = ", ".join(part for part in (SITE["city"], date) if part)
    place_size = page.fit(place, TEXT, 17, column)
    page.text(columns_left, rule - 8, place, TEXT, place_size)
    for x, label in (
        (columns_left, "MÍSTO A DATUM"),
        (columns_left + column + 36, "PODPIS AUTORKY"),
    ):
        page.hairline(x, rule, x + column, INK)
        page.text(x, page.baseline(label_top, 17, SANS, 12), label, SANS, 12, MUTED, 1.92)

    return bytes(pdf.output())


def render_preview(pdf: bytes, width: int = 1100) -> bytes:
    """The PDF's page as a JPEG. A phone cannot be relied on to show a PDF inline."""
    with _PDFIUM:
        document = pypdfium2.PdfDocument(pdf)
        try:
            page = document[0]
            image = page.render(scale=width / page.get_width()).to_pil().convert("RGB")
        finally:
            document.close()
    out = io.BytesIO()
    image.save(out, "JPEG", quality=82)
    return out.getvalue()
