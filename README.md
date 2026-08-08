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
    -   A **React** application built with **Vite**. A git submodule, so it has
        its own history: `git@github.com:basta/mariadmin.git`.
    -   Four tabs in Czech — Obrazy, Galerie, Projekty, Výstavy — sized for a
        phone, dressed in the site's own faces and colours. No component
        library and no router; four tabs do not need one.
    -   A photograph chosen in the edit sheet is *held* until Uložit, so
        changing her mind leaves nothing behind in `images/`. Reordering
        happens by dragging in the grid itself and moves under her finger
        before the server is asked.
    -   Nothing reaches the website until **Publikovat**; a banner counts what
        is waiting.

## 🚀 Quick Start

### 1. Set a password
There are no accounts — one shared password, hashed with `hashlib.scrypt`:
```bash
python3 api.py hash-password        # prompts, prints scrypt:16384:8:1:…:…
export MARI_PASSWORD_HASH='scrypt:16384:8:1:…:…'
export SESSION_SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
```
Colon-separated rather than the `$` every other scrypt encoding uses: this value
lives in environment files, and docker compose reads `$` as the start of a
variable name — it would quietly rewrite the hash and the right password would
stop working with nothing said.
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
| `ADMIN_DIST` | the admin's compiled bundle; defaults to `mariadmin/dist`. The container builds it in an earlier stage and copies it outside the checkout |
| `MARI_HOST`, `MARI_PORT` | where to listen; `127.0.0.1:8000` |

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
```bash
cd mariadmin
npm ci
npm run dev        # http://localhost:5173/admin/
```
Vite serves the app and proxies `/api`, `/images` and `/assets` to `api.py` on
:8000, so the session cookie stays first-party and there is no CORS to
configure. Run `api.py` alongside it. `npm run build` type-checks first, so a
build that succeeds is a build that compiled.

## 🐳 Deployment

One container, one process: `api.py` serving `/api`, `/admin` and the site's
assets. The image carries the Python environment, git and the compiled admin
app; **the checkout is bind-mounted at `/app`** and everything else is read from
there — it has to be, because publishing means committing and pushing that very
checkout.

```bash
cp .env.example .env        # fill it in; it is gitignored
docker compose up -d --build
```

`.env.example` documents every setting. Four of them have no default and the
container will not start without them: the password hash, the session secret,
the uid/gid that own the checkout, and the path to an SSH deploy key.

-   **The deploy key** is an SSH key with write access to
    `HSTEP/marimagdalena`, mounted read-only at `/run/secrets/deploy_key`,
    mode 400 or 600. Scoped to the one repository by construction, and never
    part of a URL, so it cannot leak into `.git/config` or a log line. GitHub's
    host key is baked into the image rather than accepted on first use — a
    background push has nobody to ask.
-   **`MARI_UID`/`MARI_GID`** must be the owner of the checkout, or the server
    writes files as root that the next `git pull` on the host cannot touch.
    They are build arguments, not just a `user:` mapping — an unmapped uid has
    no `/etc/passwd` entry and ssh refuses to start without one, which would
    surface as a publish that dies at the push. Changing them means
    `docker compose up -d --build`.
-   **`PUBLISH_BRANCH` has no default in `.env.example`.** Point it at a scratch
    branch and watch a whole publish land before it ever says `main`.
-   Nothing is built at startup. The generated HTML is committed — GitHub Pages
    serves it from the repository — so a build on every restart would rewrite
    committed files before anyone had asked for anything.

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
-   `Dockerfile`, `docker-compose.yaml`, `entrypoint.sh`, `.env.example`: the
    deployment. `.dockerignore` is an allowlist — the build context is three
    entries, because the image copies almost nothing from the checkout.

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
| `POST /api/pending/discard` | throw all of them away — `git checkout` plus `git clean` over the same paths |
| `POST /api/publish`, `GET /api/publish/status` | publish, and follow along in Czech while it happens |

Uploads are opened with Pillow and rejected if that fails, so a `.php` named
`.jpg` never lands on disk. JPEG, PNG and WebP are stored as they arrive;
anything else — an iPhone's HEIC — is re-encoded to JPEG with the EXIF
rotation applied, because the browser cannot display the original. Names are
sanitised and diacritics folded, so `Šárka.jpg` becomes `sarka.jpg`.

### Publishing

One press of **Publikovat** produces exactly one commit:

1. Stage `src/data/` and `images/` — an explicit list, never `git add -A`, so a
   stray file in the checkout cannot ride along. `images/_d/` is excluded here,
   because it is build output and not her work.
2. Commit, with a message written from the pending log.
3. `git pull --rebase` onto the publish branch.
4. `python build.py --strict`.
5. Stage the generated files — the rendered pages, `sitemap.xml`, `robots.txt`,
   `images/_d/` — and `git commit --amend`, so the data and the site it
   produces land together.
6. Push; a rejection sends it back to step 3, up to three times.

Nothing is published if the build fails: the commit is undone with a mixed
reset, the generated files are restored, and the changes go back to being
unpublished drafts with an explanation in Czech. Publishing when nothing has
changed does nothing at all rather than committing a fresh `<lastmod>` in the
sitemap.

| variable | default | meaning |
| --- | --- | --- |
| `PUBLISH_BRANCH` | `main` | point it at a scratch branch until you trust it |
| `PUBLISH_REMOTE` | `origin` | |
| `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL` | `Maří Magdalena` | passed to git per command, so the container needs no global config |

Merging a branch that touched a template against one that touched content
conflicts in the generated HTML every time. `.gitattributes` marks those files
with a `generated` merge driver that resolves to either side, so the merge
completes and the build supplies the real answer afterwards — the resolution is
never a blend of the two, it is whatever `python build.py` produces. A driver is
a command, so git will not take it from a repository file: `api.py` passes it
on every git invocation, but **your own clone needs it configured once**, as
described at the top of `.gitattributes`.

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
