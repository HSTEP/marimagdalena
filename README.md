# Maří Magdalena Website & Admin

This repository cointains the source code for the **Maří Magdalena** website and its administration interface.

## 🏗 Architecture

The system consists of three main components:

1.  **Backend (`api.py`)**:
    -   A FastAPI application running on Python.
    -   Every endpoint lives under `/api`, behind a session cookie. It serves
        the admin app at `/admin/`, plus `/images` and `/assets`; `/` redirects
        to the admin. It does **not** serve the generated site — GitHub Pages
        does that, and a second copy would only ever disagree with the first.
    -   Manages `src/data/*.json` and the files under `images/`, writing both
        atomically (temp file, then `os.replace`) so a build never reads a
        half-written file.
    -   **Mutations do not build.** Editing changes the working tree and
        nothing else; the site is rebuilt once, at publish time. Every mutation
        firing its own unsynchronised build was how `manifest.json` got
        corrupted and how a page could render with no paintings in it.
    -   **Drafts are the working tree.** "Unpublished" means the checkout
        differs from `HEAD`, so undo is `git checkout` and history is `git log`.
        There is no second store to fall out of step.

2.  **Static Site Generator (`build.py` + `media.py`)**:
    -   A Python script that generates the public-facing static website.
    -   Reads data from `src/data/` (JSON files).
    -   Uses **Jinja2** templates located in `src/` to render HTML files.
    -   Outputs the generated HTML files, plus `sitemap.xml` and `robots.txt`, to the root directory.
    -   `media.py` derives responsive WebP versions of every referenced image
        into `images/_d/`, recording intrinsic size and average colour so pages
        never reflow while loading. Results are cached in
        `images/_d/manifest.json`, keyed by the source's content hash, so a
        rebuild only re-encodes what actually changed and a fresh clone
        re-encodes nothing. Derivatives of images the site no longer
        references are deleted at the end of a full build. Run
        `python build.py --images-only` to regenerate derivatives without
        rendering (this skips the pruning, which needs the render to know
        which images the templates reach).

3.  **Admin Interface (`mariadmin/`)**:
    -   A **React** application built with **Vite**.
    -   Being rewritten as a phone-first, four-tab app in Czech — Obrazy,
        Galerie, Projekty, Výstavy — for the artist to run herself. The
        `react-admin` version still in this directory predates the endpoints
        above and does not talk to them; it will not work until that rewrite
        lands.

## 🚀 Quick Start

### 1. Set a password
There are no accounts — one shared password, hashed with `hashlib.scrypt`:
```bash
python3 api.py hash-password        # prompts, prints scrypt$…
export MARI_PASSWORD_HASH='scrypt$…'
export SESSION_SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
```
`SESSION_SECRET` must be a fixed value: leave it out and one is generated at
startup, which signs cookies fine but logs everybody out on every restart.
Over plain HTTP on localhost also set `MARI_INSECURE_COOKIE=1`, since the
cookie is otherwise `Secure` and the browser will not send it back.

| variable | meaning |
| --- | --- |
| `MARI_PASSWORD_HASH` | scrypt hash from `hash-password`; without it nobody can log in |
| `SESSION_SECRET` | signs the session cookie |
| `MARI_INSECURE_COOKIE` | drops `Secure` for local HTTP development |
| `SITE_ROOT` | the checkout to edit and build; defaults to the file's own directory |

### 2. Start the API/Backend
```bash
python3 api.py
```
*   Admin Interface: `http://localhost:8000/admin/` (served from `mariadmin/dist`)
*   The public site is at www.marimagdalena.cz, built by `build.py` and hosted
    by GitHub Pages from the repository root.

### 3. Manual Rebuild
If you manually edit data or templates, you can trigger a rebuild:
```bash
python3 build.py
```

### 4. Develop Admin App
To work on the React Admin interface:
```bash
cd mariadmin
npm install
npm run dev
```

## 📂 Project Structure

-   `api.py`: Backend server and logic.
-   `build.py`: Static site generator script.
-   `media.py`: Responsive image derivation.
-   `src/data/`: JSON data files (`paintings.json`, `galerie.json`,
    `projekty.json`, `vystavy.json`). One file per admin tab.
-   `src/*.html`: Jinja2 page templates. Files starting with `_` are partials
    and are never rendered on their own:
    -   `_base.html` — the shared layout (head, nav, menu, footer, lightbox).
    -   `_icons.html` — inline SVG icon macros.
    -   `_parts.html` — blocks shared by more than one page (the price list).
-   `mariadmin/`: Source code for the Admin React app.
-   `assets/css/site.css`: The whole stylesheet.
-   `assets/js/site.js`: The whole script (no framework, no jQuery).
-   `assets/fonts/`: Self-hosted Bodoni Moda + Jost, `latin` and `latin-ext`
    subsets, so Czech diacritics render without a third-party request.
-   `images/`: Uploaded images and static assets.
-   `images/_d/`: **Generated.** Responsive derivatives; commit these, the
    static host serves them directly.
-   `.mari/`: **Machine-local, gitignored.** The pending-changes log the
    publish banner reads, and the on-the-fly thumbnail cache.

## 🔌 API

Everything is under `/api` and everything except `/api/login` requires the
session cookie. `resource` is one of `paintings`, `galerie`, `projekty`,
`vystavy` — an enum, so an unknown one is a 422 rather than a write to an
arbitrary directory.

| route | does |
| --- | --- |
| `POST /api/login`, `POST /api/logout`, `GET /api/me` | one shared password, rate-limited to 5 attempts a minute per address; the cookie lasts a year so a phone never sees the login screen twice |
| `GET/POST /api/{resource}` | list (by `order`) and create |
| `GET/PUT/DELETE /api/{resource}/{id}` | one record; `PUT` merges only the fields sent, so a form that submits `sold` alone cannot blank the title |
| `POST /api/{resource}/photo` | create straight from a photograph, title left empty — the camera-roll path |
| `PUT /api/{resource}/{id}/image` | swap the photograph, keeping the record and the filename |
| `POST /api/{resource}/reorder` | `{ids: […]}`; ids not mentioned keep their order and go last, so a stale list cannot drop a painting |
| `GET /api/thumb?path=…&w=…` | small JPEG for the grid, from `images/_d/` when a derivative already fits, otherwise cached under `.mari/thumbs/` |
| `GET /api/pending` | how many unpublished changes there are, and a Czech sentence for each |

Uploads are opened with Pillow and rejected if that fails, so a `.php` named
`.jpg` never lands on disk. JPEG, PNG and WebP are stored as they arrive;
anything else — an iPhone's HEIC — is re-encoded to JPEG with the EXIF
rotation applied, because the browser cannot display the original. Names are
sanitised and diacritics folded, so `Šárka.jpg` becomes `sarka.jpg`.

## 🛠 How to Make Changes

### Content Data
*   **Recommended**: Use the **Admin Interface** to add paintings, projects, or exhibitions.
*   **Manual**: Edit JSON files in `src/data/`.

### Copy, contact details, services and prices
These live in `build.py` as `SITE`, `NAV`, `SERVICES`, `PRICING` and `PARTNERS`.
`SERVICES` quotes a "from" price for each group — keep it in step with `PRICING`.

### Design & Layout
*   **HTML**: Edit the Jinja2 templates in `src/`; `src/_base.html` is the layout.
*   **CSS**: Edit `assets/css/site.css`. Colour, type and spacing are all
    custom properties at the top of the file; `.on-paper` flips a section from
    the dark ground to the light one.
*   **JS**: Edit `assets/js/site.js`.

### Adding an image to a template
Use the `img()` helper rather than a raw `<img>`, so the picture gets a
`srcset`, intrinsic dimensions and a placeholder colour:

```jinja
{{ img('images/obrazy/1.jpg', alt='Název', sizes='(max-width:960px) 100vw, 40vw') }}
```

`big(path)` returns the largest derivative (used for lightbox links) and
`ratio(path)` the intrinsic aspect ratio (used to size frames without cropping).

Derivative URLs carry a `?v=` content version. A derivative is named after its
source file, so replacing a photograph keeps the URL identical and a browser
holding the old picture would go on showing it; the version changes whenever
the bytes do.

An image the build cannot read renders as an `<!-- MISSING IMAGE: … -->`
comment and is listed on stderr, rather than vanishing silently. Build with
`python build.py --strict` to exit non-zero instead — this is what the publish
pipeline uses, so a page with a hole in it is never pushed.

### Content coming from the admin
The admin JSON is edited by hand as well as by the app, so `build.py` repairs
and normalises it on the way through rather than trusting it:

| helper | what it does |
| --- | --- |
| `normalise_links()` | adds a missing `https://`, and swaps `url`/`text` when they were filled in the wrong order |
| `link_label()` | shows a hostname when a link's label is a bare URL |
| `cz_date()` | one date format — lowercase Czech months, genitive after a day number, en dash for ranges |
| `date_key()` | sorts exhibitions chronologically from prose dates |
| `video_embed()` | only YouTube/Vimeo get an `<iframe>`; Facebook refuses framing, so those become link-out cards |
| `plural_cz()` | Czech 1 / 2–4 / 5+ plural forms |
| `typeset_cz()` | binds single-letter prepositions and day numbers to the next word with a non-breaking space, over the rendered HTML |

Long lists (the paintings grid, the project archive) render in full into the
HTML and are then revealed in batches by `data-batch` in `site.js`, so the
pages stay short without losing anything for search engines or for readers
without scripting.
