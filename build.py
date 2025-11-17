#! python3
import os
import time
import json
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
OUTPUT_DIR = BASE_DIR
TEMPLATES_DIR = SRC_DIR
DATA_DIR = SRC_DIR / "data"
IMAGES_DIR = BASE_DIR / "images"  # General images directory

# --- Setup Jinja2 Environment ---
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))


# --- Helper Function to load and sort JSON data ---
def load_and_sort_data(filename: Path):
    """Loads JSON data from a file and sorts it by the 'order' field."""
    if not filename.is_file():
        print(f"Warning: Data file not found: {filename}")
        return []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, list):
            print(f"Warning: JSON data in {filename} is not a list.")
            return []
        # Sort the data based on the 'order' key, from low to high.
        return sorted(data, key=lambda x: x.get('order', float('inf')), reverse=True)
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from file: {filename}")
        return []
    except Exception as e:
        print(f"Error loading data from {filename}: {e}")
        return []


# --- Helper Function for Sorting Galerie Images ---
def get_galerie_sort_key(filename):
    """
    Extracts the sorting key from galerie filenames.
    This logic is kept as 'galerie' is not managed by the CMS.
    """
    try:
        key_part = filename.split("_")[0]
        return float(key_part)
    except (ValueError, IndexError):
        print(f"Warning: Could not parse sort key from galerie filename: {filename}")
        return float('inf')


# --- Main Build Logic ---
if __name__ == "__main__":
    print("Starting build process...")
    start_time = time.time()

    OUTPUT_DIR.mkdir(exist_ok=True)

    # --- Load All Data from JSON ---
    paintings_data = load_and_sort_data(DATA_DIR / "paintings.json")
    projekty_data = load_and_sort_data(DATA_DIR / "projekty.json")
    vystavy_data = load_and_sort_data(DATA_DIR / "vystavy.json")

    # --- Process Paintings Data ---
    # Add the full relative URL to each painting record for use in the template.
    for painting in paintings_data:
        if 'filename' in painting:
            painting['url'] = f"{IMAGES_DIR.name}/obrazy/{painting['filename']}"
    print(f"Loaded and processed {len(paintings_data)} paintings.")
    print(f"Loaded {len(projekty_data)} projects.")
    print(f"Loaded {len(vystavy_data)} exhibitions.")

    # --- Get Galerie Image List (unchanged logic) ---
    galerie_images = []
    galerie_dir = IMAGES_DIR / "galerie"
    if galerie_dir.is_dir():
        galerie_files = [f for f in os.listdir(galerie_dir) if (galerie_dir / f).is_file()]
        galerie_files.sort(key=get_galerie_sort_key, reverse=True)
        galerie_images = [f"images/galerie/{name}" for name in galerie_files]
        print(f"Found {len(galerie_images)} galerie images.")
    else:
        print(f"Warning: Galerie directory not found: {galerie_dir}")

    # --- Render Templates ---
    if not TEMPLATES_DIR.is_dir():
        print(f"Error: Templates directory not found: {TEMPLATES_DIR}")
        exit(1)

    print(f"Rendering templates from '{TEMPLATES_DIR}' to '{OUTPUT_DIR}'...")
    rendered_files = 0
    for filename in os.listdir(TEMPLATES_DIR):
        if filename.endswith(".html"):
            template_path = TEMPLATES_DIR / filename
            output_path = OUTPUT_DIR / filename
            try:
                template = env.get_template(filename)

                # Base context available to all templates
                context = {
                    'projekty': projekty_data,
                    'vystavy': vystavy_data,
                }

                # Add specific context keys that individual pages expect
                if filename == "obrazy.html":
                    context['paintings'] = paintings_data
                elif filename == "galerie.html":
                    context['images'] = galerie_images

                html_content = template.render(context)
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                rendered_files += 1
                print(f"  - Rendered {filename}")
            except Exception as e:
                print(f"Error rendering template {filename}: {e}")

    end_time = time.time()
    print(f"\nBuild process finished in {end_time - start_time:.2f} seconds. Rendered {rendered_files} files.")
