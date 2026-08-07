"""Responsive image derivation for the Maří Magdalena site.

Source photography is straight out of the camera (single files up to 25 MB), which
is unusable on the web.  For every image the site references we emit a ladder of
WebP derivatives plus the intrinsic size and an average colour, so templates can
render `<img>` tags that never shift layout and always download a sensible byte
count.

Results are cached in ``images/_d/manifest.json`` keyed by source mtime+size, so
a rebuild after a content edit only touches what actually changed.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps

BASE_DIR = Path(__file__).resolve().parent
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
            if not dest.exists():
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

    def _load_manifest(self) -> dict:
        if self.manifest_path.is_file():
            try:
                return json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {}

    def save(self):
        self.manifest_path.write_text(
            json.dumps(self.manifest, indent=0, sort_keys=True), encoding="utf-8"
        )

    @staticmethod
    def _stamp(path: Path) -> str:
        st = path.stat()
        return f"{int(st.st_mtime)}:{st.st_size}"

    def _normalise(self, rel_path: str) -> str:
        return str(rel_path).replace("\\", "/").lstrip("./")

    def stale(self, rel_paths) -> list[str]:
        """Which of these need (re)encoding?"""
        todo = []
        for rel in rel_paths:
            rel = self._normalise(rel)
            src = BASE_DIR / rel
            if not src.is_file():
                self.missing.add(rel)
                continue
            entry = self.manifest.get(rel)
            if entry and entry.get("stamp") == self._stamp(src):
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
                data["stamp"] = self._stamp(BASE_DIR / rel)
                self.manifest[rel] = data
                done += 1
                if done % 25 == 0:
                    print(f"    …{done}/{len(todo)}")
        self.save()
        return done

    def get(self, rel_path: str):
        rel = self._normalise(rel_path)
        entry = self.manifest.get(rel)
        if entry:
            return entry
        src = BASE_DIR / rel
        if not src.is_file():
            self.missing.add(rel)
            return None
        # Referenced by a template but not pre-scanned — do it inline.
        _, data = _render_one((rel, self.widths, str(self.out_dir)))
        data["stamp"] = self._stamp(src)
        self.manifest[rel] = data
        return data
