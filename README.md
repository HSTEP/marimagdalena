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

2.  **Static Site Generator (`build.py`)**:
    -   A Python script that generates the public-facing static website.
    -   Reads data from `src/data/` (JSON files).
    -   Uses **Jinja2** templates located in `src/` to render HTML files.
    -   Outputs the generated HTML files to the root directory.

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
-   `src/data/`: JSON data files (`paintings.json`, `projekty.json`, `vystavy.json`).
-   `src/*.html`: Jinja2 templates for the website.
-   `mariadmin/`: Source code for the Admin React app.
-   `assets/`: CSS, JS, and font resources for the public site.
-   `images/`: Uploaded images and static assets.

## 🛠 How to Make Changes

### Content Data
*   **Recommended**: Use the **Admin Interface** to add paintings, projects, or exhibitions.
*   **Manual**: Edit JSON files in `src/data/`.

### Design & Layout
*   **HTML**: Edit the Jinja2 templates in `src/`. e.g., `src/container.html` for the main layout.
*   **CSS**: Edit `assets/css/main.css`.
*   **JS**: Edit `assets/js/main.js`.
