"""Responsive image derivation for the Maří Magdalena site.

Source photography is straight out of the camera (single files up to 25 MB), which
is unusable on the web.  For every image the site references we emit a ladder of
WebP derivatives plus the intrinsic size and an average colour, so templates can
render `<img>` tags that never shift layout and always download a sensible byte
count.

Results are cached in ``images/_d/manifest.json``, keyed by the source's
content hash.  Everything recorded there is derived from the bytes of the
image, so the file is identical on every machine and a fresh clone rebuilds
nothing.  It was keyed on mtime+size, which git does not preserve: every
clone looked entirely stale and re-encoded all 177 images to arrive back at
byte-identical output.  Hashing the lot costs about 0.2 s.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps

# Photographs off an iPhone arrive as HEIC, which Pillow cannot open unaided.
# Registered at module level so the ProcessPoolExecutor children, which
# re-import this module, get the opener too.
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover - the site still builds without it
    pass

# Kept in step with build.py: paths here are relative to the checkout being
# built, which is not necessarily the one this file lives in.
BASE_DIR = Path(os.environ.get("SITE_ROOT") or Path(__file__).resolve().parent).resolve()
DERIVED_DIRNAME = "_d"

# Width ladder.  Covers a 400 px phone at 3x through a 2560 px desktop at 1x.
DEFAULT_WIDTHS = (480, 800, 1280, 1920)
WEBP_QUALITY = 80
WEBP_METHOD = 5


def _slug(rel_path: str) -> str:
    """Flatten ``images/obrazy/1.jpg`` into ``obrazy-1``."""
    p = Path(rel_path)
    parts = list(p.parts)
    if parts and parts[0] == "images":
        parts = parts[1:]
    stem = "/".join(parts[:-1] + [p.stem])
    safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in stem)
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-").lower()


def _render_one(job):
    """Worker body.  Must be module level so it can be pickled to subprocesses."""
    rel_path, widths, out_dir = job
    src = BASE_DIR / rel_path
    out_dir = Path(out_dir)

    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        # Alpha is preserved: the wordmark and the partner logos are transparent
        # art that gets recoloured in CSS, so flattening them destroys the asset.
        has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
        im = im.convert("RGBA" if has_alpha else "RGB")

        width, height = im.size
        # Average colour, used as the placeholder behind a still-loading image.
        # Sampled over the opaque pixels only, so a logo doesn't average to grey.
        flat = im
        if has_alpha:
            flat = Image.new("RGB", im.size, (11, 10, 9))
            flat.paste(im, mask=im.getchannel("A"))
        avg = flat.resize((1, 1), Image.LANCZOS).getpixel((0, 0))
        colour = "#%02x%02x%02x" % avg[:3]

        slug = _slug(rel_path)
        ladder = [w for w in sorted(widths) if w < width] + [min(width, max(widths))]
        ladder = sorted(set(ladder))

        sources = []
        for w in ladder:
            h = max(1, round(height * w / width))
            name = f"{slug}-{w}.webp"
            dest = out_dir / name
            # Written unconditionally.  This used to skip whenever the file
            # was already there, which meant a photograph swapped for another
            # one under the same name kept its old derivatives for ever —
            # `stale()` is what decides whether we get here at all.
            resized = im.resize((w, h), Image.LANCZOS)
            resized.save(dest, "WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
            sources.append({"w": w, "url": f"images/{DERIVED_DIRNAME}/{name}"})

    return rel_path, {
        "w": width,
        "h": height,
        "color": colour,
        "alpha": has_alpha,
        "sources": sources,
    }


class Media:
    def __init__(self, images_dir: Path, widths=DEFAULT_WIDTHS):
        self.images_dir = images_dir
        self.out_dir = images_dir / DERIVED_DIRNAME
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.widths = tuple(widths)
        self.manifest_path = self.out_dir / "manifest.json"
        self.manifest = self._load_manifest()
        self.missing: set[str] = set()
        self.used: set[str] = set()
        # Sources whose hash has already been checked this run, so a page with
        # 87 `img()` calls doesn't hash the same file 87 times.
        self._checked: set[str] = set()

    def _load_manifest(self) -> dict:
        if self.manifest_path.is_file():
            try:
                return json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {}

    def save(self):
        """Write the manifest atomically.

        A torn manifest costs a full re-encode of every image, and the API
        writes to this tree while a build may be reading it.
        """
        payload = json.dumps(self.manifest, indent=0, sort_keys=True)
        fd, tmp = tempfile.mkstemp(dir=self.out_dir, prefix=".manifest-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, self.manifest_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.blake2b(digest_size=16)
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _normalise(self, rel_path: str) -> str:
        return str(rel_path).replace("\\", "/").lstrip("./")

    def stale(self, rel_paths) -> list[str]:
        """Which of these need (re)encoding?

        Decided purely on content: an image whose bytes hash to what the
        manifest recorded is done, whatever its mtime says.
        """
        todo = []
        for rel in rel_paths:
            rel = self._normalise(rel)
            self.used.add(rel)
            src = BASE_DIR / rel
            if not src.is_file():
                self.missing.add(rel)
                continue
            entry = self.manifest.get(rel)
            self._checked.add(rel)
            if entry and entry.get("hash") == self._hash(src):
                continue
            todo.append(rel)
        return todo

    def build(self, rel_paths, workers: int | None = None):
        """Derive every stale image, in parallel."""
        todo = self.stale(rel_paths)
        if not todo:
            return 0
        jobs = [(rel, self.widths, str(self.out_dir)) for rel in todo]
        workers = workers or min(8, (os.cpu_count() or 4))
        done = 0
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for rel, data in pool.map(_render_one, jobs, chunksize=4):
                data["hash"] = self._hash(BASE_DIR / rel)
                self.manifest[rel] = data
                done += 1
                if done % 25 == 0:
                    print(f"    …{done}/{len(todo)}")
        self.save()
        return done

    def get(self, rel_path: str):
        rel = self._normalise(rel_path)
        self.used.add(rel)
        src = BASE_DIR / rel
        entry = self.manifest.get(rel)
        if entry and rel in self._checked:
            return entry
        if not src.is_file():
            self.missing.add(rel)
            return None
        self._checked.add(rel)
        if entry and entry.get("hash") == self._hash(src):
            return entry
        # Either never derived, or derived from different bytes.  A template
        # can name an image the data scan never sees, so this is the only
        # staleness check some images ever get.
        _, data = _render_one((rel, self.widths, str(self.out_dir)))
        data["hash"] = self._hash(src)
        self.manifest[rel] = data
        return data

    def prune(self) -> tuple[int, int]:
        """Forget images the site no longer uses, and delete their derivatives.

        Nothing removed an entry before, so a deleted painting left its ladder
        in ``images/_d`` for ever — committed, and served to nobody.  The same
        goes for a width that drops off the ladder when an image is replaced
        by a narrower one.

        Only safe to call once everything has been asked for, so it belongs
        after rendering rather than after ``build()``: templates reach images
        through ``get()`` that the data scan never sees.
        """
        if not self.used:
            # Nothing asked for anything.  Far more likely a caller ordering
            # mistake than a site with no images, and the cost of being wrong
            # here is a full re-encode, so decline.
            return (0, 0)

        dropped = [rel for rel in self.manifest if rel not in self.used]
        for rel in dropped:
            del self.manifest[rel]

        keep = {
            Path(source["url"]).name
            for entry in self.manifest.values()
            for source in entry.get("sources", [])
        }
        removed = 0
        for path in self.out_dir.glob("*.webp"):
            if path.name not in keep:
                path.unlink()
                removed += 1

        if dropped or removed:
            self.save()
        return (len(dropped), removed)
