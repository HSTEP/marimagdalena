#! python3
"""Static site generator for marimagdalena.cz.

Renders the Jinja2 templates in ``src/`` to HTML in the repository root (which is
what GitHub Pages and the nginx container serve), pulling content from the JSON
files that the admin app in ``mariadmin/`` writes to ``src/data/``.

Templates whose name starts with ``_`` are partials and are never rendered on
their own.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from media import Media

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
OUTPUT_DIR = BASE_DIR
TEMPLATES_DIR = SRC_DIR
DATA_DIR = SRC_DIR / "data"
IMAGES_DIR = BASE_DIR / "images"

SITE = {
    "name": "Maří Magdalena",
    "tagline": "Hair & Art Salon",
    "founded": 2011,
    "city": "Dobřany",
    "street": "Císaře Karla 1139",
    "zip": "334 41",
    "person": "Marie Baštařová",
    "person_gen": "Marie Baštařové",  # genitive — "obrazy Marie Baštařové"
    "phone_display": "+420 607 067 778",
    "phone_href": "+420607067778",
    "email": "marie@marimagdalena.cz",
    "instagram": "https://www.instagram.com/marimagdalenakadernickysalon/",
    "instagram_handle": "@marimagdalenakadernickysalon",
    "facebook": "https://www.facebook.com/marie.bastarova.1",
    "zahrada": "https://instagram.com/zahradamarimagdaleny?igshid=MzRlODBiNWFlZA==",
    "maps": (
        "https://maps.google.com/maps?width=600&height=420&hl=cs"
        "&q=C%C3%ADsa%C5%99e%20Karla%201139%20Dobrany"
        "+(Kade%C5%99nictv%C3%AD%20Ma%C5%99%C3%AD%20Magdalena)"
        "&t=&z=15&ie=UTF8&iwloc=B&output=embed"
    ),
    "maps_link": "https://maps.google.com/?q=C%C3%ADsa%C5%99e+Karla+1139+Dob%C5%99any",
    "url": "https://www.marimagdalena.cz",
    "logo_gold": "images/logo_w.png",
    "logo_dark": "images/logo_b.png",
}

NAV = [
    {"slug": "salon", "href": "index.html", "label": "Salon"},
    {"slug": "hair", "href": "galerie.html", "label": "Hair&nbsp;&amp;&nbsp;Styling"},
    {"slug": "obrazy", "href": "obrazy.html", "label": "Obrazy"},
    {"slug": "vystavy", "href": "vystavy.html", "label": "Výstavy"},
    {"slug": "projekty", "href": "projekty.html", "label": "Projekty"},
    # "What does a cut cost" is the first question a salon gets on a phone.
    # It was reachable only from the footer and one mid-page button.
    {"slug": "cenik", "href": "cenik.html", "label": "Ceník"},
    {"slug": "partneri", "href": "partneri.html", "label": "Partneři"},
    {"slug": "zahrada", "href": SITE["zahrada"], "label": "Zahrada", "external": True},
]

# Portraits from the salon's own studio session, used as full-bleed plates.
PLATES = {
    "hero": "images/bg/1C5A1152.jpg",
    "salon": "images/bg/1C5A1096.jpg",
    "atelier": "images/bg/1C5A1173.jpg",
    "contact": "images/bg/1C5A1120.jpg",
}


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def load_and_sort_data(filename: Path):
    """Load a JSON list and sort it by its 'order' field (newest first)."""
    if not filename.is_file():
        print(f"Warning: Data file not found: {filename}")
        return []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            print(f"Warning: JSON data in {filename} is not a list.")
            return []
        return sorted(data, key=lambda x: x.get("order", float("inf")), reverse=True)
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from file: {filename}")
        return []
    except Exception as e:
        print(f"Error loading data from {filename}: {e}")
        return []


def get_galerie_sort_key(filename):
    """Galerie filenames are prefixed with their display order (``12_centered_…``)."""
    try:
        return float(filename.split("_")[0])
    except (ValueError, IndexError):
        print(f"Warning: Could not parse sort key from galerie filename: {filename}")
        return float("inf")


URL_RE = re.compile(r"^(https?://|mailto:|tel:)", re.I)
BARE_DOMAIN_RE = re.compile(r"^[\w-]+(\.[\w-]+)+(/|$)")


def looks_like_url(value):
    value = (value or "").strip()
    return bool(URL_RE.match(value) or BARE_DOMAIN_RE.match(value))


# Corrections to admin-entered copy, applied at load time so a title, its alt
# text and its lightbox caption can never disagree. Kept here rather than
# edited into the JSON: the source data stays exactly as the owner typed it,
# and every change the site makes to their words is listed in one place.
TEXT_FIXES = [
    # A proper noun typed lower-case: "Večer pro klášter chotěšov".
    (re.compile(r"\bchotěšov\b"), "Chotěšov"),
    # Her own site and domain spell it without diacritics
    # (irynabidasova.com), and "s" takes the instrumental case.
    (re.compile(r"\bs\s+Iryna\s+Bidašová\b"), "s Irynou Bidasovou"),
    (re.compile(r"\bIryna\s+Bidašová\b"), "Iryna Bidasova"),
]

TEXT_FIELDS = ("title", "description")


def repair_text(records):
    """Trim stray whitespace and apply the corrections above."""
    fixed = 0
    for record in records:
        for field in TEXT_FIELDS:
            value = record.get(field)
            if not isinstance(value, str):
                continue
            original = value
            value = value.strip()
            for pattern, replacement in TEXT_FIXES:
                value = pattern.sub(replacement, value)
            if value != original:
                fixed += 1
            record[field] = value
    return fixed


def normalise_links(records):
    """Repair link records coming out of the admin JSON.

    Two failure modes exist in the live data: a URL saved without its scheme
    (which the browser then resolves against our own domain and 404s), and a
    record where the url and text fields were filled in the wrong order.
    """
    fixed = 0
    for record in records:
        for link in record.get("links") or []:
            url = (link.get("url") or "").strip()
            text = (link.get("text") or "").strip()

            if not looks_like_url(url) and looks_like_url(text):
                url, text = text, url
                fixed += 1

            if url and not URL_RE.match(url):
                url = "https://" + url.lstrip("/")
                fixed += 1

            link["url"] = url
            link["text"] = text
    return fixed


def is_document(path):
    """True when an image is a poster or graphic rather than a photograph.

    Aspect ratio was the wrong signal: it letterboxed portrait photographs
    while a poster that happened to be square was cropped straight through its
    own headline. In this archive the distinction is carried by file type —
    every scanned or exported poster is a PNG, every camera photograph is a
    JPEG — so a poster is never cropped and a photograph never floats.
    """
    return (path or "").lower().endswith(".png")


def link_label(text, url=""):
    """Readable label for a link.

    Some records carry a bare URL as their link text, which sets in the site's
    letterspaced caps as an unbreakable 400 px word. Fall back to the host.
    """
    text = (text or "").strip()
    if not text or text.startswith(("http://", "https://", "www.")):
        source = text or url or ""
        host = re.sub(r"^https?://", "", source).split("/")[0]
        host = host.removeprefix("www.")
        return host or "Odkaz"
    return text


def date_key(record):
    """Sortable (year, month, day) from a free-text Czech date.

    The admin stores dates as prose ("22. listopadu, 2024", "Červen - Srpen
    2024"), and the `order` field they were being listed by is only loosely
    chronological — so the calendar ran out of sequence from row 8 down.
    Missing parts sort to the start of the year.
    """
    text = (record.get("date") or "").lower()
    year = re.search(r"(19|20)\d{2}", text)
    year = int(year.group(0)) if year else 0

    month = 0
    for index, (nom, gen) in enumerate(MONTHS.items(), start=1):
        if nom in text or gen in text:
            month = max(month, index)  # a range sorts by the month it ends in
    day = re.search(r"\b(\d{1,2})\.", text)
    day = int(day.group(1)) if day else 0
    return (year, month, day, record.get("order", 0))


def cz_title(value):
    """Sentence-case a title that was typed in all caps.

    One record in eleven is shouting, which makes the index look like a data
    dump. Only touched when the string contains no lower-case letter at all,
    so acronyms and normally-cased titles pass through untouched.
    """
    text = (value or "").strip()
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 4 or any(c.islower() for c in letters):
        return text
    return text[:1].upper() + text[1:].lower()


def plural_cz(n, one, few, many):
    """Czech has three plural forms: 1 / 2–4 / 5+ (and 0 takes the last)."""
    if n == 1:
        return f"{n} {one}"
    if 2 <= n <= 4:
        return f"{n} {few}"
    return f"{n} {many}"


def year_of(record):
    """Pull a four digit year out of a free-text Czech date for grouping."""
    match = re.search(r"(19|20)\d{2}", record.get("date") or "")
    return match.group(0) if match else ""


# --------------------------------------------------------------------------- #
# Czech typesetting
# --------------------------------------------------------------------------- #
NBSP = " "

# Czech orthography sets month names in lower case, and puts the month in the
# genitive after a day number ("8. května", not "8. Květen").
MONTHS = {
    "leden": "ledna", "únor": "února", "březen": "března", "duben": "dubna",
    "květen": "května", "červen": "června", "červenec": "července",
    "srpen": "srpna", "září": "září", "říjen": "října",
    "listopad": "listopadu", "prosinec": "prosince",
}
MONTH_FORMS = set(MONTHS) | set(MONTHS.values())
MONTH_RE = re.compile("|".join(sorted(MONTH_FORMS, key=len, reverse=True)), re.I)

# Single-letter prepositions and conjunctions must not end a line in Czech.
# The lookbehind rejects only a preceding word character (so "slova a slovo"
# matches but "3a b" does not); also rejecting a preceding space would skip
# the one case that actually occurs.
ORPHAN_RE = re.compile(r"(?<!\w)([KkSsVvZzOoUuAaIi])[ 	]+(?=[^\s<])")
# Nor should a day number be split from its month: "8. kvetna".
DAY_RE = re.compile(r"(\d{1,2}\.)[ 	]+(?=[^\s<])")

# A spaced hyphen typed where a dash was meant. The site sets em dashes
# everywhere else, so a single record read "Flower Day - styling" beside
# twelve that used "—". Bounded by whitespace, so hyphenated words and
# URLs are never touched.
DASH_RE = re.compile(r"(?<=\s)-(?=\s)")
SKIP_TAGS = re.compile(r"^</?(script|style|title)\b", re.I)


def cz_date(value):
    """Normalise a free-text Czech date so eleven records read as one system."""
    if not value:
        return value
    text = value.strip()
    text = MONTH_RE.sub(lambda m: m.group(0).lower(), text)
    # "Leden, 2025" -> "leden 2025"
    text = re.sub(r",\s*(?=(19|20)\d{2})", " ", text)
    # "1. červen 2024" -> "1. června 2024"
    text = re.sub(
        r"(\d{1,2}\.\s*)(" + "|".join(MONTHS) + r")\b",
        lambda m: m.group(1) + MONTHS[m.group(2)],
        text,
    )
    # Ranges take an en dash, unspaced — including the spelled-out "až".
    text = re.sub(r"\s+až\s+", "–", text)
    text = re.sub(r"\s*[-–—]\s*", "–", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text


def typeset_cz(html):
    """Bind single-letter Czech prepositions to the word that follows them.

    Runs over the rendered document rather than the source copy so it also
    covers text coming from the admin JSON. Only text nodes are touched —
    tags, scripts and stylesheets are passed through untouched.
    """
    parts = re.split(r"(<[^>]*>)", html)
    skipping = False
    out = []
    for part in parts:
        if part.startswith("<"):
            if SKIP_TAGS.match(part):
                skipping = not part.startswith("</")
            out.append(part)
        elif skipping or not part.strip():
            out.append(part)
        else:
            part = DASH_RE.sub("—", part)
            part = ORPHAN_RE.sub(r"\1" + NBSP, part)
            out.append(DAY_RE.sub(r"\1" + NBSP, part))
    return "".join(out)


# YouTube and Vimeo allow framing; Facebook sends X-Frame-Options: deny, so an
# fb.com URL in an <iframe> renders a permanently empty box.
def video_embed(url):
    """Return a frameable embed URL, or None if the host refuses framing."""
    if not url:
        return None
    if re.search(r"(youtube\.com|youtu\.be|player\.vimeo\.com|vimeo\.com/video)", url, re.I):
        return url
    return None


# --------------------------------------------------------------------------- #
# Template helpers
# --------------------------------------------------------------------------- #
def make_img_helper(media: Media):
    def img(path, alt="", sizes="100vw", cls="", loading="lazy", cover=False,
            width_attr=True, fetchpriority=None):
        """Render a responsive <img> for a repo-relative image path."""
        if not path:
            return Markup("")
        data = media.get(path)
        if not data:
            return Markup("")
        srcset = ", ".join(f"{s['url']} {s['w']}w" for s in data["sources"])
        fallback = data["sources"][-1]["url"] if data["sources"] else path
        classes = " ".join(c for c in ["ph", "is-cover" if cover else "", cls] if c)
        attrs = [
            f'class="{escape(classes)}"',
            f'src="{escape(fallback)}"',
            f'srcset="{escape(srcset)}"',
            f'sizes="{escape(sizes)}"',
            f'alt="{escape(alt)}"',
            f'loading="{loading}"',
            'decoding="async"',
        ]
        # A flat placeholder colour holds the space while a photo loads; on a
        # transparent asset it would just be a visible box, so skip it there.
        if not data.get("alpha"):
            attrs.append(f'style="background-color:{data["color"]}"')
        if width_attr:
            attrs.insert(4, f'width="{data["w"]}" height="{data["h"]}"')
        if fetchpriority:
            attrs.append(f'fetchpriority="{fetchpriority}"')
        return Markup("<img " + " ".join(attrs) + ">")

    return img


def make_big_helper(media: Media):
    def big(path):
        """Largest derivative — what the lightbox loads, never the raw original."""
        data = media.get(path)
        if not data or not data["sources"]:
            return path
        return data["sources"][-1]["url"]

    return big


def make_feature_helper(media: Media):
    def feature(records, min_side=900, count=1):
        """Pick records good enough to run large on the homepage.

        Some records carry a phone screenshot of a flyer — a few hundred pixels
        square, with the flyer's own headline already cut off in the file. Those
        are fine in the archive at thumbnail size but must not be the one thing
        the homepage features, so require a real resolution.
        """
        picked = []
        for record in records:
            data = media.get(record.get("image")) if record.get("image") else None
            if data and max(data["w"], data["h"]) >= min_side:
                picked.append(record)
            if len(picked) == count:
                break
        return picked

    return feature


def make_ratio_helper(media: Media):
    def ratio(path, default=1.0):
        data = media.get(path)
        if not data or not data["h"]:
            return default
        return round(data["w"] / data["h"], 4)

    return ratio


def collect_image_paths(paintings, projekty, vystavy, galerie_images, partners):
    paths = set(PLATES.values())
    paths.update(galerie_images)
    paths.update([SITE["logo_gold"], SITE["logo_dark"]])
    for p in paintings:
        if p.get("url"):
            paths.add(p["url"])
    for rec in list(projekty) + list(vystavy):
        if rec.get("image"):
            paths.add(rec["image"])
    for partner in partners:
        paths.add(partner["photo"])
        if partner.get("logo"):
            paths.add(partner["logo"])
    return {p for p in paths if p}


PARTNERS = [
    {
        "name": "Jirka Krejčík",
        "role": "Fotograf",
        "url": "http://jirkakrejcik.cz",
        "photo": "images/loga/jirkaf.jpg",
        "logo": "images/loga/jirka.png",
    },
    {
        "name": "Lydie Bernklauová",
        "role": "Floristika",
        "studio": "LB Design",
        "url": "https://www.instagram.com/lydie_bernklauova/",
        "photo": "images/loga/lidaf.png",
        "logo": "images/loga/lida.png",
    },
    {
        "name": "Iryna Bidasova",
        "role": "Výtvarnice",
        "url": "https://www.irynabidasova.com",
        "photo": "images/loga/irinaf.jpg",
        "logo": "images/loga/irina.png",
    },
    {
        "name": "Michaela Naušová",
        "role": "Módní návrhářka",
        "url": "http://michaelanausova.com",
        "photo": "images/loga/nausovaf.png",
        "logo": "images/loga/michaela.png",
    },
    {
        "name": "Slávka Štrbová",
        "role": "Autorka loga",
        "url": (
            "https://domazlicky.denik.cz/lide-odvedle/slavka-strbova-lasku-k-malovani-"
            "mi-sudicky-i-s-pastelkami-vlozily-do-kolebky-20200118.html?cast=1"
        ),
        "photo": "images/loga/slavka.jpg",
        "logo": None,
    },
    {
        "name": "Lenka Koščo",
        "role": "Fotografka",
        "url": "https://www.lenkakosco.cz",
        "photo": "images/loga/lenkaf.jpg",
        "logo": "images/loga/lenka.png",
    },
    {
        "name": "Renata Divišková",
        "role": "Výtvarnice",
        "studio": "RED",
        "url": "https://www.instagram.com/red_renata_diviskova_art/",
        "photo": "images/loga/renataf.jpg",
        "logo": "images/loga/renata.png",
    },
]

# Headline services. The "from" price of each is the cheapest row of the matching
# group in PRICING below — keep the two in step when prices change.
SERVICES = [
    ("Střih", "Konzultace, mytí, střih a foukaná. Dámský i pánský.", "od 490 Kč"),
    ("Barva & melír", "Odrost, celá barva, melír s tónováním, stahování barvy.", "od 1 790 Kč"),
    ("Regenerace", "Malibu C, kolagen, keratin, botox, metal detox, Wella plex.", "od 1 790 Kč"),
    ("Účes", "Společenské a svatební účesy.", "od 990 Kč"),
    ("Líčení", "Večerní a svatební líčení.", "od 990 Kč"),
    ("Fotoportrét", "Celodenní proměna zakončená focením v ateliéru.", "3 990 Kč"),
]

# Price list, previously duplicated inline across two templates.
PRICING = [
    {
        "title": "Pánské",
        "columns": [],
        "rows": [
            ("Střih bez mytí", ["490 Kč"]),
            ("Střih s mytím", ["590 Kč"]),
        ],
    },
    {
        "title": "Dámské",
        "columns": ["Krátké", "Polodlouhé", "Dlouhé"],
        "rows": [
            ("Střih, péče, mytí, foukání", ["1 590 Kč", "1 790 Kč", "1 990 Kč"]),
            ("Barva (odrost) + střih", ["1 790 Kč", "1 990 Kč", "2 190 Kč"]),
            ("Barva (celá) + střih", ["1 990 Kč", "2 190 Kč", "2 790 Kč"]),
            ("Melír + tónování + střih", ["2 590 Kč", "2 790 Kč", "3 590 Kč"]),
            ("Stahování barvy + střih", ["2 990 Kč", "4 590 Kč", "7 990 Kč"]),
            ("Malibu C — čištění vlasů", ["1 990 Kč", "2 190 Kč", "2 790 Kč"]),
            ("Kolagen", ["2 190 Kč", "2 590 Kč", "3 190 Kč"]),
            ("Keratin", ["2 590 Kč", "3 590 Kč", "4 590 Kč"]),
            ("Botox", ["1 790 Kč", "3 190 Kč", "3 990 Kč"]),
            ("Metal detox", ["+300 Kč", "+350 Kč", "+500 Kč"]),
            ("Wella plex", ["+500 Kč", "+550 Kč", "+700 Kč"]),
        ],
    },
    {
        "title": "Proměny & focení",
        "columns": [],
        "rows": [
            ("Večerní líčení", ["990 Kč"]),
            ("Společenský účes", ["990 Kč"]),
            ("Svatební líčení", ["1 990 Kč"]),
            ("Svatební účes", ["2 990 Kč"]),
            ("Fotoportrét", ["3 990 Kč"]),
        ],
    },
]


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("Starting build process...")
    start_time = time.time()

    OUTPUT_DIR.mkdir(exist_ok=True)

    paintings_data = load_and_sort_data(DATA_DIR / "paintings.json")
    projekty_data = load_and_sort_data(DATA_DIR / "projekty.json")
    vystavy_data = load_and_sort_data(DATA_DIR / "vystavy.json")

    for painting in paintings_data:
        if "filename" in painting:
            painting["url"] = f"{IMAGES_DIR.name}/obrazy/{painting['filename']}"
    # Stamp each project with its year so the archive can be broken into
    # chapters instead of running as one 41-item strip. The admin's `order`
    # field is only roughly chronological, so sort by year first — otherwise
    # a year heading opens, closes and opens again further down. Records keep
    # their curated order within a year; undated ones go last.
    for record in projekty_data:
        record["year"] = year_of(record)
    projekty_data.sort(
        key=lambda r: (int(r["year"]) if r["year"] else -1, r.get("order", 0)),
        reverse=True,
    )
    # Group into chapters so the archive can be revealed a year at a time
    # rather than as one 44 000 px scroll.
    projekty_years = []
    for record in projekty_data:
        if not projekty_years or projekty_years[-1][0] != record["year"]:
            projekty_years.append((record["year"], []))
        projekty_years[-1][1].append(record)

    vystavy_data.sort(key=date_key, reverse=True)

    repaired = normalise_links(projekty_data) + normalise_links(vystavy_data)
    if repaired:
        print(f"Repaired {repaired} malformed link field(s) from the admin data.")

    corrected = repair_text(projekty_data) + repair_text(vystavy_data)
    if corrected:
        print(f"Corrected {corrected} text field(s) from the admin data.")

    print(f"Loaded and processed {len(paintings_data)} paintings.")
    print(f"Loaded {len(projekty_data)} projects.")
    print(f"Loaded {len(vystavy_data)} exhibitions.")

    galerie_images = []
    galerie_dir = IMAGES_DIR / "galerie"
    if galerie_dir.is_dir():
        galerie_files = [f for f in os.listdir(galerie_dir) if (galerie_dir / f).is_file()]
        galerie_files.sort(key=get_galerie_sort_key, reverse=True)
        galerie_images = [f"images/galerie/{name}" for name in galerie_files]
        print(f"Found {len(galerie_images)} galerie images.")
    else:
        print(f"Warning: Galerie directory not found: {galerie_dir}")

    # --- Derive responsive images ------------------------------------------ #
    media = Media(IMAGES_DIR)
    wanted = collect_image_paths(
        paintings_data, projekty_data, vystavy_data, galerie_images, PARTNERS
    )
    print(f"Checking {len(wanted)} source images…")
    encoded = media.build(sorted(wanted))
    print(f"Encoded {encoded} image(s); {len(media.manifest)} in manifest.")

    if "--images-only" in sys.argv:
        print(f"Images done in {time.time() - start_time:.2f}s (--images-only).")
        raise SystemExit(0)

    # --- Render templates --------------------------------------------------- #
    if not TEMPLATES_DIR.is_dir():
        print(f"Error: Templates directory not found: {TEMPLATES_DIR}")
        raise SystemExit(1)

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals.update(
        site=SITE,
        nav=NAV,
        plates=PLATES,
        partners=PARTNERS,
        pricing=PRICING,
        services=SERVICES,
        img=make_img_helper(media),
        big=make_big_helper(media),
        feature=make_feature_helper(media),
        ratio=make_ratio_helper(media),
        year_of=year_of,
        link_label=link_label,
        is_document=is_document,
        cz_date=cz_date,
        video_embed=video_embed,
        plural_cz=plural_cz,
        cz_title=cz_title,
        build_year=time.strftime("%Y"),
    )

    print(f"Rendering templates from '{TEMPLATES_DIR}' to '{OUTPUT_DIR}'...")
    rendered_files = 0
    public_pages = []
    for filename in sorted(os.listdir(TEMPLATES_DIR)):
        if not filename.endswith(".html") or filename.startswith("_"):
            continue
        try:
            template = env.get_template(filename)
            context = {
                "projekty": projekty_data,
                "vystavy": vystavy_data,
                "paintings": paintings_data,
                "images": galerie_images,
                "projekty_years": projekty_years,
            }
            html_content = typeset_cz(template.render(context))
            (OUTPUT_DIR / filename).write_text(html_content, encoding="utf-8")
            rendered_files += 1
            if filename != "404.html":
                public_pages.append(filename)
            print(f"  - Rendered {filename}")
        except Exception as e:
            print(f"Error rendering template {filename}: {e}")
            raise

    # --- sitemap + robots --------------------------------------------------- #
    today = time.strftime("%Y-%m-%d")
    urls = "\n".join(
        "  <url><loc>{}/{}</loc><lastmod>{}</lastmod><priority>{}</priority></url>".format(
            SITE["url"], "" if name == "index.html" else name, today,
            "1.0" if name == "index.html" else "0.7",
        )
        for name in public_pages
    )
    (OUTPUT_DIR / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n</urlset>\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {SITE['url']}/sitemap.xml\n",
        encoding="utf-8",
    )
    print(f"  - Wrote sitemap.xml ({len(public_pages)} urls) and robots.txt")

    media.save()
    if media.missing:
        print(f"\nMissing image sources ({len(media.missing)}):")
        for m in sorted(media.missing):
            print(f"  ! {m}")

    end_time = time.time()
    print(
        f"\nBuild process finished in {end_time - start_time:.2f} seconds. "
        f"Rendered {rendered_files} files."
    )
