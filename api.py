"""The server behind the admin app.

Everything the app can do is a route under ``/api``, guarded by a session
cookie. There is one password and one person; there is no user table.

Two shapes here are worth knowing before reading on.

**Mutations do not build.** Every endpoint used to fire an unsynchronised
``build.py`` subprocess, so two quick edits raced each other over
``images/_d/manifest.json`` and a build could read a data file halfway through
being rewritten. Building happens once, at publish time, behind a lock.

**Drafts are the working tree.** A mutation writes ``src/data/*.json`` and
``images/`` in a real git checkout. "Unpublished" means the tree differs from
HEAD. There is no staging copy to keep in step, and no second source of truth
about what has changed — ``git status`` is the answer. ``.mari/pending.json``
holds only the Czech sentences the banner and the commit message are written
from; git decides whether anything is pending at all.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import tempfile
import time
import unicodedata
from collections import deque
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict
from starlette.middleware.sessions import SessionMiddleware

# Registers the HEIC opener as a side effect, so an iPhone photograph can be
# opened here as well as in the build.
import media as media_module

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
BASE_DIR = Path(os.environ.get("SITE_ROOT", Path(__file__).resolve().parent)).resolve()
IMAGES_DIR = BASE_DIR / "images"
DATA_DIR = BASE_DIR / "src" / "data"
DIST_DIR = BASE_DIR / "dist"
ASSETS_DIR = BASE_DIR / "assets"

# Server-side working state, gitignored: the pending log and the thumbnail
# cache. Nothing in here is ever published.
STATE_DIR = BASE_DIR / ".mari"
PENDING_LOG = STATE_DIR / "pending.json"
THUMB_CACHE = STATE_DIR / "thumbs"

SESSION_COOKIE = "mari_session"
SESSION_MAX_AGE = 365 * 24 * 3600  # A year. She should never see a login again.

# Login attempts allowed per IP per window, and the window in seconds.
LOGIN_ATTEMPTS = 5
LOGIN_WINDOW = 60


class Resource(str, Enum):
    """The four things the app edits.

    An enum rather than a string, so a path parameter can never name a file
    outside this set. The previous upload endpoint took the resource verbatim
    and joined it onto a directory, which let an unauthenticated caller choose
    where to write.
    """

    paintings = "paintings"
    galerie = "galerie"
    projekty = "projekty"
    vystavy = "vystavy"


# Where each resource keeps its records, and where its images live.
DATA_FILE = {
    Resource.paintings: DATA_DIR / "paintings.json",
    Resource.galerie: DATA_DIR / "galerie.json",
    Resource.projekty: DATA_DIR / "projekty.json",
    Resource.vystavy: DATA_DIR / "vystavy.json",
}
IMAGE_DIR = {
    Resource.paintings: IMAGES_DIR / "obrazy",
    Resource.galerie: IMAGES_DIR / "galerie",
    Resource.projekty: IMAGES_DIR / "projekty",
    Resource.vystavy: IMAGES_DIR / "vystavy",
}

# Paintings and gallery plates carry a bare filename and the page prepends the
# directory; projects and exhibitions carry a repo-relative path in `image`.
STORES_BARE_FILENAME = {Resource.paintings, Resource.galerie}


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
# scrypt from the standard library, so there is no password dependency to keep
# up to date. Parameters are the interactive-login figures from RFC 7914.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P
    )
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N,
        SCRYPT_R,
        SCRYPT_P,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
        )
    except (ValueError, TypeError):
        return False
    # Constant time, so a wrong password cannot be narrowed down by timing.
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


# --------------------------------------------------------------------------- #
# Data files
# --------------------------------------------------------------------------- #
def load_records(resource: Resource) -> list[dict[str, Any]]:
    path = DATA_FILE[resource]
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # A torn or hand-mangled file must not read as "no paintings", because
        # saving on top of that would publish an empty page.
        raise HTTPException(500, f"Datový soubor {path.name} je poškozený.")
    return data if isinstance(data, list) else []


def save_records(resource: Resource, records: list[dict[str, Any]]) -> None:
    """Write atomically.

    The build reads these files, and a reader that catches a half-written file
    renders a page with nothing on it.
    """
    path = DATA_FILE[resource]
    path.parent.mkdir(parents=True, exist_ok=True)
    # Matches how the files are already formatted, so a save by the app makes
    # the same shape of diff as an edit by hand: two-space indent, real Czech
    # characters rather than escapes, and no trailing newline.
    payload = json.dumps(records, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def next_id(records: list[dict[str, Any]]) -> int:
    return max((r.get("id", 0) for r in records), default=0) + 1


def find_index(records: list[dict[str, Any]], item_id: int) -> int:
    index = next((i for i, r in enumerate(records) if r.get("id") == item_id), -1)
    if index == -1:
        raise HTTPException(404, "Položka nenalezena.")
    return index


def renumber(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make `order` a dense 0..N-1 run in list order.

    `order` ascends with the page, so index 0 is what a visitor sees first.
    """
    for position, record in enumerate(records):
        record["order"] = position
    return records


# --------------------------------------------------------------------------- #
# The pending log
# --------------------------------------------------------------------------- #
def note_pending(text_cs: str) -> None:
    """Record one human sentence about a change that has not been published.

    Only ever used for display and for the commit message. Whether anything is
    actually pending is git's business, so losing this file costs a nicely
    worded banner and nothing else.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        entries = json.loads(PENDING_LOG.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            entries = []
    except (OSError, json.JSONDecodeError):
        entries = []
    entries.append({"ts": int(time.time()), "text_cs": text_cs})
    fd, tmp = tempfile.mkstemp(dir=STATE_DIR, prefix=".pending-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(entries, handle, ensure_ascii=False)
        os.replace(tmp, PENDING_LOG)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_pending() -> list[dict[str, Any]]:
    try:
        entries = json.loads(PENDING_LOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return entries if isinstance(entries, list) else []


# --------------------------------------------------------------------------- #
# Images
# --------------------------------------------------------------------------- #
# Formats kept as uploaded. Everything else — HEIC above all, which is what an
# iPhone actually sends — is re-encoded to JPEG, because the site's derivation
# and every browser have to be able to read it.
KEEP_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
JPEG_QUALITY = 90
MAX_UPLOAD_BYTES = 60 * 1024 * 1024


def decode_upload(raw: bytes) -> tuple[bytes, str]:
    """Validate an uploaded image and return the bytes to store, plus extension.

    Opening it here is the validation: a file that Pillow cannot read would
    otherwise be stored happily and then vanish from the page at build time,
    with nothing anywhere saying why.
    """
    if not raw:
        raise HTTPException(400, "Soubor je prázdný.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Fotka je příliš velká (nejvýše 60 MB).")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            fmt = (im.format or "").upper()
            im.load()
            if fmt in KEEP_FORMATS:
                # Store the original bytes: re-encoding a JPEG that is already
                # fine only loses quality. Orientation is applied downstream,
                # by media.py, which reads the same EXIF.
                return raw, KEEP_FORMATS[fmt]
            # Anything else becomes a JPEG. Orientation has to be baked in
            # here, because it is being re-encoded and the EXIF goes away.
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            buffer = io.BytesIO()
            im.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True)
            return buffer.getvalue(), ".jpg"
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "Tento soubor se nepodařilo přečíst jako obrázek.")


def safe_stem(name: str) -> str:
    """A filename that is safe to put in a URL and on any filesystem.

    Diacritics are folded rather than stripped, so `Šárka.jpg` becomes
    `sarka` and not `rka`.
    """
    stem = Path(name or "").stem
    folded = unicodedata.normalize("NFKD", stem)
    ascii_only = folded.encode("ascii", "ignore").decode("ascii").lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    return cleaned[:60] or "foto"


def store_image(
    resource: Resource,
    upload_name: str,
    raw: bytes,
    stem: str | None = None,
    replace: bool = False,
) -> str:
    """Write an uploaded image into the resource's directory. Returns filename.

    ``replace`` allows writing over the name that is already there, which is
    what swapping a photograph wants: the filename stays put, so the
    derivative slugs stay put and git records a modified file rather than an
    addition and a deletion. Browsers are handled by the `?v=` content version
    in the built page, not by moving the file about.
    """
    body, extension = decode_upload(raw)
    directory = IMAGE_DIR[resource]
    directory.mkdir(parents=True, exist_ok=True)

    base = stem or safe_stem(upload_name)
    filename = f"{base}{extension}"
    # Otherwise a new upload could land on another painting's photograph.
    if not replace and (directory / filename).exists():
        filename = f"{base}-{secrets.token_hex(3)}{extension}"

    target = directory / filename
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".upload-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return filename


def resolve_under_images(rel_path: str) -> Path:
    """Resolve a repo-relative path, refusing anything outside images/."""
    candidate = (BASE_DIR / rel_path).resolve()
    if not candidate.is_relative_to(IMAGES_DIR):
        raise HTTPException(400, "Neplatná cesta k obrázku.")
    if not candidate.is_file():
        raise HTTPException(404, "Obrázek nenalezen.")
    return candidate


def record_image_path(resource: Resource, record: dict[str, Any]) -> str | None:
    """The repo-relative path of a record's image, whatever field holds it."""
    if resource in STORES_BARE_FILENAME:
        name = record.get("filename")
        return f"{IMAGE_DIR[resource].relative_to(BASE_DIR)}/{name}" if name else None
    return record.get("image") or None


# --------------------------------------------------------------------------- #
# Thumbnails
# --------------------------------------------------------------------------- #
# The grid shows 87 paintings whose sources run to 8 MB each. Sending those to
# a phone on cellular data is the difference between an app and a wait.
THUMB_WIDTHS = (200, 400, 800)


def thumbnail(rel_path: str, width: int) -> Path:
    """Return a file of about `width` px for this image, making one if needed.

    Prefers a derivative the site build already produced, so the common case
    costs a manifest lookup and no image work at all.
    """
    source = resolve_under_images(rel_path)
    rel = str(source.relative_to(BASE_DIR))

    entry = _manifest().get(rel)
    if entry:
        wide_enough = [s for s in entry.get("sources", []) if s["w"] >= width]
        chosen = min(wide_enough, key=lambda s: s["w"]) if wide_enough else None
        if chosen:
            candidate = BASE_DIR / chosen["url"]
            if candidate.is_file():
                return candidate

    # No derivative yet — an image uploaded since the last publish. Cache by
    # content, so replacing the photograph invalidates the thumbnail.
    digest = media_module.Media._hash(source)
    THUMB_CACHE.mkdir(parents=True, exist_ok=True)
    cached = THUMB_CACHE / f"{digest}-{width}.jpg"
    if cached.is_file():
        return cached

    with Image.open(source) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.thumbnail((width, width * 4), Image.LANCZOS)
        fd, tmp = tempfile.mkstemp(dir=THUMB_CACHE, prefix=".thumb-")
        try:
            with os.fdopen(fd, "wb") as handle:
                im.save(handle, "JPEG", quality=82, optimize=True)
            os.replace(tmp, cached)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return cached


_MANIFEST_CACHE: dict[str, Any] = {"mtime": None, "data": {}}


def _manifest() -> dict[str, Any]:
    """The build's image manifest, re-read when it changes underneath us."""
    path = IMAGES_DIR / media_module.DERIVED_DIRNAME / "manifest.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _MANIFEST_CACHE["mtime"] != mtime:
        try:
            _MANIFEST_CACHE["data"] = json.loads(path.read_text(encoding="utf-8"))
            _MANIFEST_CACHE["mtime"] = mtime
        except (OSError, json.JSONDecodeError):
            return _MANIFEST_CACHE["data"]
    return _MANIFEST_CACHE["data"]


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
_login_attempts: dict[str, deque[float]] = {}


def rate_limit(request: Request) -> None:
    """Crude per-IP throttle on the login route.

    One password guarded by one process; a few attempts a minute is the
    difference between a password and a formality.
    """
    now = time.monotonic()
    client = request.client.host if request.client else "unknown"
    attempts = _login_attempts.setdefault(client, deque())
    while attempts and now - attempts[0] > LOGIN_WINDOW:
        attempts.popleft()
    if len(attempts) >= LOGIN_ATTEMPTS:
        raise HTTPException(429, "Příliš mnoho pokusů. Zkuste to za minutu.")
    attempts.append(now)


def require_session(request: Request) -> None:
    if not request.session.get("auth"):
        raise HTTPException(401, "Nejste přihlášena.")


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class LoginIn(BaseModel):
    password: str


class ReorderIn(BaseModel):
    ids: list[int]


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str = ""
    text: str = ""


class PaintingIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = ""
    sold: bool = False


class GalerieIn(BaseModel):
    # A gallery plate is only a photograph in a position; there is nothing to
    # write about it. The model exists so the route shape stays uniform.
    model_config = ConfigDict(extra="ignore")


class ProjektIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = ""
    date: str | None = None
    image: str | None = None
    description: str | None = None
    links: list[LinkIn] = []
    video_url: str | None = None


class VystavaIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = ""
    date: str | None = None
    image: str | None = None
    links: list[LinkIn] = []


BODY_MODEL: dict[Resource, type[BaseModel]] = {
    Resource.paintings: PaintingIn,
    Resource.galerie: GalerieIn,
    Resource.projekty: ProjektIn,
    Resource.vystavy: VystavaIn,
}

# What a change is called in the banner and in the commit message.
LABEL = {
    Resource.paintings: "obraz",
    Resource.galerie: "fotku v galerii",
    Resource.projekty: "projekt",
    Resource.vystavy: "výstavu",
}


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
# Everything the site publishes lives under one of these. The publish pipeline
# stages exactly this list, never `git add -A`, so a stray file in the checkout
# can never ride along into a commit.
PUBLISH_ALLOWLIST = ("src/data", "images")

public = APIRouter(prefix="/api")
api = APIRouter(prefix="/api", dependencies=[Depends(require_session)])


@public.post("/login")
def login(body: LoginIn, request: Request, _: None = Depends(rate_limit)):
    encoded = os.environ.get("MARI_PASSWORD_HASH", "")
    if not encoded:
        raise HTTPException(
            503, "Server nemá nastavené heslo (MARI_PASSWORD_HASH)."
        )
    if not verify_password(body.password, encoded):
        raise HTTPException(401, "Nesprávné heslo.")
    request.session["auth"] = True
    return {"ok": True}


@public.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@public.get("/me")
def me(request: Request):
    """Whether this browser is signed in, so the app knows what to show."""
    if not request.session.get("auth"):
        raise HTTPException(401, "Nejste přihlášena.")
    return {"ok": True}


@api.get("/thumb")
def get_thumb(path: str, w: int = 400):
    if w not in THUMB_WIDTHS:
        raise HTTPException(400, f"Nepodporovaná šířka (povolené: {THUMB_WIDTHS}).")
    file = thumbnail(path, w)
    # Keyed by content — a replaced photograph resolves to a different file —
    # so this can be cached hard by the browser.
    return FileResponse(file, headers={"Cache-Control": "private, max-age=86400"})


@api.get("/pending")
def get_pending():
    """What is waiting to be published.

    The count comes from git, which is the truth. The sentences come from the
    log, which is only there to be readable; if it is missing or behind, the
    banner still shows the right count.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", *PUBLISH_ALLOWLIST],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        changed = [line for line in result.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        raise HTTPException(500, "Nepodařilo se zjistit neuložené změny.")

    return {
        "count": len(changed),
        "files": len(changed),
        "items": read_pending()[-50:],
    }


@api.get("/{resource}")
def list_items(resource: Resource):
    records = sorted(load_records(resource), key=lambda r: r.get("order", 1 << 30))
    for record in records:
        # The app should not have to know that paintings store a bare filename
        # while projects store a path.
        record["image_path"] = record_image_path(resource, record)
    return records


@api.post("/{resource}", status_code=201)
def create_item(resource: Resource, body: dict[str, Any]):
    """Create a record without a photograph (projects and exhibitions)."""
    model = BODY_MODEL[resource]
    fields = model(**body).model_dump()
    records = load_records(resource)
    record = {"id": next_id(records), **fields}
    records.append(record)
    save_records(resource, renumber(records))
    note_pending(f"Přidán {LABEL[resource]}: {fields.get('title') or 'bez názvu'}")
    record["image_path"] = record_image_path(resource, record)
    return record


@api.post("/{resource}/photo", status_code=201)
async def create_item_with_photo(resource: Resource, image: UploadFile = File(...)):
    """Create a record from a photograph — the camera-roll path.

    Title is left empty on purpose: she picks several pictures at once and
    names them afterwards, rather than being asked 12 times in a row.
    """
    raw = await image.read()
    records = load_records(resource)
    new_id = next_id(records)
    stem = str(new_id) if resource in STORES_BARE_FILENAME else None
    filename = store_image(resource, image.filename or "", raw, stem=stem)

    record: dict[str, Any] = {"id": new_id, **BODY_MODEL[resource]().model_dump()}
    if resource in STORES_BARE_FILENAME:
        record["filename"] = filename
    else:
        record["image"] = f"{IMAGE_DIR[resource].relative_to(BASE_DIR)}/{filename}"

    records.append(record)
    save_records(resource, renumber(records))
    note_pending(f"Přidána fotka: {LABEL[resource]}")
    record["image_path"] = record_image_path(resource, record)
    return record


@api.post("/{resource}/reorder")
def reorder(resource: Resource, body: ReorderIn):
    """Reorder by a list of ids in display order.

    Ids the caller did not mention keep their relative order and go to the
    end, so a stale list from a phone that missed an addition cannot silently
    drop a painting off the page.
    """
    records = load_records(resource)
    by_id = {r.get("id"): r for r in records}
    ordered = [by_id.pop(item_id) for item_id in body.ids if item_id in by_id]
    leftovers = sorted(by_id.values(), key=lambda r: r.get("order", 1 << 30))
    save_records(resource, renumber(ordered + leftovers))
    note_pending(f"Změněno pořadí: {LABEL[resource]}")
    return {"ok": True, "count": len(ordered) + len(leftovers)}


@api.put("/{resource}/{item_id}/image")
async def replace_image(resource: Resource, item_id: int, image: UploadFile = File(...)):
    """Swap the photograph on an existing record, keeping everything else.

    The site had no way to do this at all. It works now because the build
    keys its cache on content: writing different bytes is enough to make the
    derivatives, and the URLs that point at them, change.

    The new photograph keeps the old one's name. That is why cache busting had
    to exist first — the filename no longer carries the news that the picture
    changed, so the built page carries it instead, in `?v=`.
    """
    raw = await image.read()
    records = load_records(resource)
    index = find_index(records, item_id)
    record = records[index]

    old_path = record_image_path(resource, record)
    # Reuse the stem that is already there so the derivative slugs — and the
    # git history of this file — stay continuous across a swap.
    stem = Path(old_path).stem if old_path else None
    if not stem and resource in STORES_BARE_FILENAME:
        stem = str(item_id)
    filename = store_image(resource, image.filename or "", raw, stem=stem, replace=True)

    if resource in STORES_BARE_FILENAME:
        record["filename"] = filename
    else:
        record["image"] = f"{IMAGE_DIR[resource].relative_to(BASE_DIR)}/{filename}"

    # A different format changes the extension, and with it the name, leaving
    # the old file behind unreferenced. `samefile` because a case-insensitive
    # filesystem would otherwise let `.JPG` -> `.jpg` delete what we just wrote.
    new_path = record_image_path(resource, record)
    if old_path and old_path != new_path:
        try:
            old_file, new_file = resolve_under_images(old_path), resolve_under_images(new_path)
            if old_file.exists() and new_file.exists() and not old_file.samefile(new_file):
                old_file.unlink()
        except HTTPException:
            pass

    save_records(resource, records)
    note_pending(f"Vyměněna fotka: {LABEL[resource]}")
    record["image_path"] = record_image_path(resource, record)
    return record


@api.get("/{resource}/{item_id}")
def get_item(resource: Resource, item_id: int):
    records = load_records(resource)
    record = records[find_index(records, item_id)]
    record["image_path"] = record_image_path(resource, record)
    return record


@api.put("/{resource}/{item_id}")
def update_item(resource: Resource, item_id: int, body: dict[str, Any]):
    model = BODY_MODEL[resource]
    # exclude_unset, so a form that sends only `sold` does not blank the title.
    fields = model(**body).model_dump(exclude_unset=True)
    records = load_records(resource)
    index = find_index(records, item_id)
    records[index].update(fields)
    records[index]["id"] = item_id
    save_records(resource, records)
    note_pending(
        f"Upraven {LABEL[resource]}: {records[index].get('title') or 'bez názvu'}"
    )
    records[index]["image_path"] = record_image_path(resource, records[index])
    return records[index]


@api.delete("/{resource}/{item_id}", status_code=204)
def delete_item(resource: Resource, item_id: int):
    records = load_records(resource)
    index = find_index(records, item_id)
    record = records.pop(index)

    image_path = record_image_path(resource, record)
    if image_path:
        try:
            resolve_under_images(image_path).unlink()
        except HTTPException:
            pass

    save_records(resource, renumber(records))
    note_pending(f"Smazán {LABEL[resource]}: {record.get('title') or 'bez názvu'}")
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #
app = FastAPI(title="Maří Magdalena", docs_url=None, redoc_url=None)

# No CORS middleware: the app is served from this same origin, so allowing
# other origins to send credentialed requests would only ever help someone else.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET") or secrets.token_hex(32),
    session_cookie=SESSION_COOKIE,
    max_age=SESSION_MAX_AGE,
    same_site="lax",
    # Off only for local development over plain http, where a Secure cookie is
    # never stored and login appears to silently fail.
    https_only=os.environ.get("MARI_INSECURE_COOKIE") != "1",
)

app.include_router(public)
app.include_router(api)


@app.get("/")
def root():
    return RedirectResponse("/admin/")


# The site's own stylesheet, script and fonts, so the admin can be dressed in
# them rather than in a component library's idea of a form.
if ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")

# Note what is *not* here: the old server mounted the repository root at /web
# with directory listing, which served api.py, .git and every source file to
# anyone who asked.
if DIST_DIR.is_dir():
    app.mount("/admin", StaticFiles(directory=DIST_DIR, html=True), name="admin")


def _startup_checks() -> list[str]:
    """Configuration that must be present before this is worth starting."""
    problems = []
    if not os.environ.get("MARI_PASSWORD_HASH"):
        problems.append(
            "MARI_PASSWORD_HASH is not set — nobody can log in.\n"
            "    Generate one with:  python api.py hash-password"
        )
    if not os.environ.get("SESSION_SECRET"):
        problems.append(
            "SESSION_SECRET is not set — a random one is in use, so every\n"
            "    restart signs everyone out. Set it to a long random string."
        )
    if not DIST_DIR.is_dir():
        problems.append(
            f"{DIST_DIR} does not exist — the admin app has not been built,\n"
            "    so /admin/ will 404. Build it with:  cd mariadmin && npm run build"
        )
    return problems


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "hash-password":
        import getpass

        secret = getpass.getpass("New password: ")
        if secret != getpass.getpass("Repeat: "):
            raise SystemExit("Passwords do not match.")
        if len(secret) < 8:
            raise SystemExit("Use at least 8 characters.")
        print("\nMARI_PASSWORD_HASH=" + hash_password(secret))
        raise SystemExit(0)

    import uvicorn

    for problem in _startup_checks():
        print(f"  ! {problem}")

    uvicorn.run(
        app,
        host=os.environ.get("MARI_HOST", "127.0.0.1"),
        port=int(os.environ.get("MARI_PORT", "8000")),
    )
