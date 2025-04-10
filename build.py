#! python3
import os
import time
import re
import json # Import the json library
from jinja2 import Environment, FileSystemLoader
from pathlib import Path # Use pathlib for consistency

# --- Configuration ---
# Use Path objects for directories
BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR_OBRAZY = BASE_DIR / "images/obrazy"
IMAGES_DIR_GALERIE = BASE_DIR / "images/galerie"
SRC_DIR = BASE_DIR / "src"
OUTPUT_DIR = BASE_DIR # Output HTML files to the root directory
TEMPLATES_DIR = SRC_DIR # Templates are in the src directory
DATA_DIR = SRC_DIR / "data" # Directory for JSON data files

# --- Setup Jinja2 Environment ---
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))

# --- Helper Function for Sorting Obrazy ---
def get_obrazy_sort_key(filename):
    """
    Extracts the order number from the obrazy filename.
    Expected format: [SOLD_]<id>_<order>_<title>.<ext>
    Returns the order number as an integer for sorting.
    Returns a large number if parsing fails, putting malformed names last.
    """
    # Regex to capture the order number (second number)
    match = re.match(r"^(?:(?:SOLD|sold)_)?\d+_(\d+)_", filename, re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except (ValueError, IndexError):
            print(f"Warning: Could not parse order number from filename: {filename}")
            return float('inf') # Put invalid filenames at the end
    else:
        print(f"Warning: Filename does not match expected format: {filename}")
        return float('inf') # Put invalid filenames at the end

# --- Helper Function for Sorting Galerie ---
def get_galerie_sort_key(filename):
    """
    Extracts the sorting key (assumed to be the first part before '_') from galerie filenames.
    Handles potential float conversion errors.
    """
    try:
        # Assuming format like '1.5_someimage.jpg' or '10_another.png'
        key_part = filename.split("_")[0]
        return float(key_part)
    except (ValueError, IndexError):
        print(f"Warning: Could not parse sort key from galerie filename: {filename}")
        return float('inf') # Put invalid filenames at the end

# --- Function to load JSON data ---
def load_json_data(filename: Path):
    """Loads JSON data from a file."""
    if not filename.is_file():
        print(f"Warning: Data file not found: {filename}")
        return [] # Return empty list if file doesn't exist
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, list):
                print(f"Warning: JSON data in {filename} is not a list.")
                return []
            return data
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from file: {filename}")
        return []
    except Exception as e:
        print(f"Error loading data from {filename}: {e}")
        return []

# --- Main Build Logic ---
if __name__ == "__main__":
    print("Starting build process...")
    start_time = time.time()

    # Create output and data directories if they don't exist
    OUTPUT_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True) # Ensure data directory exists

    # --- Get Image Lists ---
    obrazy_images = []
    if IMAGES_DIR_OBRAZY.is_dir():
        obrazy_files = [
            f for f in os.listdir(IMAGES_DIR_OBRAZY)
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')) and (IMAGES_DIR_OBRAZY / f).is_file()
        ]
        # Sort obrazy images based on the extracted order number
        obrazy_files.sort(key=get_obrazy_sort_key, reverse=True)
        # Use relative paths suitable for HTML
        obrazy_images = [f"{IMAGES_DIR_OBRAZY.name}/{name}" for name in obrazy_files]
        print(f"Found {len(obrazy_images)} obrazy images.")
    else:
        print(f"Warning: Obrazy directory not found: {IMAGES_DIR_OBRAZY}")

    galerie_images = []
    if IMAGES_DIR_GALERIE.is_dir():
        galerie_files = [
            f for f in os.listdir(IMAGES_DIR_GALERIE)
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')) and (IMAGES_DIR_GALERIE / f).is_file()
        ]
         # Sort galerie images based on the extracted key (descending as per original logic)
        galerie_files.sort(key=get_galerie_sort_key, reverse=True)
        # Use relative paths suitable for HTML
        galerie_images = [f"{IMAGES_DIR_GALERIE.name}/{name}" for name in galerie_files]
        print(f"Found {len(galerie_images)} galerie images.")
    else:
        print(f"Warning: Galerie directory not found: {IMAGES_DIR_GALERIE}")

    # --- Load Data from JSON ---
    projekty_data = load_json_data(DATA_DIR / "projekty.json")
    vystavy_data = load_json_data(DATA_DIR / "vystavy.json")
    print(f"Loaded {len(projekty_data)} projects from JSON.")
    print(f"Loaded {len(vystavy_data)} exhibitions from JSON.")

    # --- Render Templates ---
    if not SRC_DIR.is_dir():
        print(f"Error: Source directory not found: {SRC_DIR}")
        exit(1)

    print(f"Rendering templates from '{SRC_DIR}' to '{OUTPUT_DIR}'...")
    rendered_files = 0
    for filename in os.listdir(SRC_DIR):
        template_source_path = SRC_DIR / filename
        if template_source_path.is_file() and filename.endswith(".html"): # Process only HTML files as templates
            template_name = filename # Relative to TEMPLATES_DIR (which is SRC_DIR)
            output_path = OUTPUT_DIR / filename

            try:
                template = env.get_template(template_name)
                context = {} # Default empty context

                # Add specific context for known templates
                if filename == "galerie.html":
                    context['images'] = galerie_images
                    print(f"  - Rendering {filename} with {len(galerie_images)} galerie images...")
                elif filename == "obrazy.html":
                    context['images'] = obrazy_images
                    print(f"  - Rendering {filename} with {len(obrazy_images)} obrazy images...")
                elif filename == "projekty.html":
                    # Pass the loaded projects data to the template
                    context['projekty'] = projekty_data
                    print(f"  - Rendering {filename} with {len(projekty_data)} projects...")
                elif filename == "vystavy.html":
                    # Pass the loaded exhibitions data to the template
                    context['vystavy'] = vystavy_data
                    print(f"  - Rendering {filename} with {len(vystavy_data)} exhibitions...")
                else:
                    # Render other HTML files with no specific context (or add generic context if needed)
                    print(f"  - Rendering {filename}...")

                html_content = template.render(context)

                # Write the rendered HTML to the output directory
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                rendered_files += 1

            except Exception as e:
                print(f"Error rendering template {filename}: {e}")

    end_time = time.time()
    print(f"Build process finished in {end_time - start_time:.2f} seconds. Rendered {rendered_files} files.")
