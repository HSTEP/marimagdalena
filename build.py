#! python3
import os
import time
import re
from jinja2 import Environment, FileSystemLoader

# --- Configuration ---
IMAGES_DIR_OBRAZY = "images/obrazy"
IMAGES_DIR_GALERIE = "images/galerie" # Assuming this exists
SRC_DIR = "src"
OUTPUT_DIR = "." # Output HTML files to the root directory
TEMPLATES_DIR = "src" # Templates are in the src directory

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

# --- Main Build Logic ---
if __name__ == "__main__":
    print("Starting build process...")

    # --- Pre-processing/Cleanup (Optional) ---
    # Example: Rename files with invalid characters if needed (though API should prevent this now)
    # for filename in os.listdir(IMAGES_DIR_OBRAZY):
    #     if "|" in filename: # Example cleanup
    #         new_name = filename.replace("|", "_")
    #         try:
    #             os.rename(os.path.join(IMAGES_DIR_OBRAZY, filename), os.path.join(IMAGES_DIR_OBRAZY, new_name))
    #             print(f"Renamed: {filename} -> {new_name}")
    #         except OSError as e:
    #             print(f"Error renaming {filename}: {e}")

    # --- Get Image Lists ---
    obrazy_images = []
    if os.path.isdir(IMAGES_DIR_OBRAZY):
        obrazy_files = [
            f for f in os.listdir(IMAGES_DIR_OBRAZY)
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')) and os.path.isfile(os.path.join(IMAGES_DIR_OBRAZY, f))
        ]
        # Sort obrazy images based on the extracted order number
        obrazy_files.sort(key=get_obrazy_sort_key)
        obrazy_images = [f"{IMAGES_DIR_OBRAZY}/{name}" for name in obrazy_files]
        print(f"Found {len(obrazy_images)} obrazy images.")
    else:
        print(f"Warning: Obrazy directory not found: {IMAGES_DIR_OBRAZY}")

    galerie_images = []
    if os.path.isdir(IMAGES_DIR_GALERIE):
        galerie_files = [
            f for f in os.listdir(IMAGES_DIR_GALERIE)
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')) and os.path.isfile(os.path.join(IMAGES_DIR_GALERIE, f))
        ]
         # Sort galerie images based on the extracted key (descending as per original logic)
        galerie_files.sort(key=get_galerie_sort_key, reverse=True)
        galerie_images = [f"{IMAGES_DIR_GALERIE}/{name}" for name in galerie_files]
        print(f"Found {len(galerie_images)} galerie images.")
    else:
        print(f"Warning: Galerie directory not found: {IMAGES_DIR_GALERIE}")


    # --- Render Templates ---
    if not os.path.isdir(SRC_DIR):
        print(f"Error: Source directory not found: {SRC_DIR}")
        exit(1)

    print(f"Rendering templates from '{SRC_DIR}' to '{OUTPUT_DIR}'...")
    for filename in os.listdir(SRC_DIR):
        if filename.endswith(".html"): # Process only HTML files as templates
            template_path = filename # Relative to TEMPLATES_DIR (which is SRC_DIR)
            output_path = os.path.join(OUTPUT_DIR, filename)

            try:
                template = env.get_template(template_path)
                context = {} # Default empty context

                # Add specific context for known templates
                if filename == "galerie.html":
                    # Pass the pre-sorted list
                    context['images'] = galerie_images
                    print(f"  - Rendering {filename} with {len(galerie_images)} galerie images...")
                elif filename == "obrazy.html":
                     # Pass the pre-sorted list
                    context['images'] = obrazy_images
                    print(f"  - Rendering {filename} with {len(obrazy_images)} obrazy images...")
                else:
                    # Render other HTML files with no specific image context
                    print(f"  - Rendering {filename}...")

                html_content = template.render(context)

                # Write the rendered HTML to the output directory
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(html_content)

            except Exception as e:
                print(f"Error rendering template {filename}: {e}")

    print("Build process finished.")
