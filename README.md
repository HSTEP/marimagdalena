# Maří Magdalena Website & Admin

This repository cointains the source code for the **Maří Magdalena** website and its administration interface.

## 🏗 Architecture

The system consists of three main components:

1.  **Backend (`api.py`)**:
    -   A FastAPI application running on Python.
    -   Serves as the central control unit.
    -   Manages data stored in `src/data/*.json`.
    -   Handles image uploads and reordering.
    -   Triggers the site build process (`build.py`) automatically upon changes.
    -   Serves the generated static website and the admin interface.

2.  **Static Site Generator (`build.py` + `media.py`)**:
    -   A Python script that generates the public-facing static website.
    -   Reads data from `src/data/` (JSON files).
    -   Uses **Jinja2** templates located in `src/` to render HTML files.
    -   Outputs the generated HTML files, plus `sitemap.xml` and `robots.txt`, to the root directory.
    -   `media.py` derives responsive WebP versions of every referenced image
        into `images/_d/`, recording intrinsic size and average colour so pages
        never reflow while loading. Results are cached in
        `images/_d/manifest.json` and keyed by source mtime+size, so a rebuild
        only re-encodes what changed. Run `python build.py --images-only` to
        regenerate derivatives without rendering.

3.  **Admin Interface (`mariadmin/`)**:
    -   A **React** application (using `react-admin`, `vite`, `mui`).
    -   Provides a user-friendly GUI to manage Paintings, Projects, and Exhibitions.
    -   Communicates with `api.py` to fetch and update data.

## 🚀 Quick Start

### 1. Start the API/Backend
This command starts the backend server, which serves both the public site and the admin interface.
```bash
python3 api.py
```
*   Public Site: `http://localhost:8000/`
*   Admin Interface: `http://localhost:8000/admin/` (or similar, served from `dist`)

### 2. Manual Rebuild
If you manually edit data or templates, you can trigger a rebuild:
```bash
python3 build.py
```

### 3. Develop Admin App
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
-   `src/data/`: JSON data files (`paintings.json`, `projekty.json`, `vystavy.json`).
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
