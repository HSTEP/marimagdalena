
import os
import re
import json
from pathlib import Path

# --- Configuration (must match api.py) ---
BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / "images" / "obrazy"
DATA_DIR = BASE_DIR / "src/data"
PAINTINGS_JSON_PATH = DATA_DIR / "paintings.json"
PROJEKTY_JSON_PATH = DATA_DIR / "projekty.json"
VYSTAVY_JSON_PATH = DATA_DIR / "vystavy.json"

def parse_old_filename(filename: str):
    """Parses the old filename format: [SOLD_]<id>_<order>_<title>.<ext>"""
    match = re.match(
        r"^(?:(SOLD|sold)_)?(\d+)_(\d+)_(.+)\.(jpg|jpeg|png|gif)$",
        filename,
        re.IGNORECASE
    )
    if match:
        sold_str, id_str, order_str, title, ext = match.groups()
        return {
            "id": int(id_str),
            "order": int(order_str),
            "title": title,
            "sold": bool(sold_str),
            "ext": f".{ext}"
        }
    return None

def migrate_paintings():
    print("Starting painting migration...")
    if not IMAGES_DIR.is_dir():
        print(f"Error: Image directory not found at {IMAGES_DIR}")
        return

    paintings_data = []
    for old_filename in os.listdir(IMAGES_DIR):
        parsed_data = parse_old_filename(old_filename)
        if parsed_data:
            new_filename = f"{parsed_data['id']}{parsed_data['ext']}"

            # Create JSON record
            record = {
                "id": parsed_data['id'],
                "title": parsed_data['title'],
                "sold": parsed_data['sold'],
                "order": parsed_data['order'],
                "filename": new_filename
            }
            paintings_data.append(record)

            # Rename the file
            old_path = IMAGES_DIR / old_filename
            new_path = IMAGES_DIR / new_filename
            print(f"Renaming '{old_path.name}' to '{new_path.name}'")
            os.rename(old_path, new_path)

    # Save the new JSON file
    PAINTINGS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PAINTINGS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(paintings_data, f, indent=2, ensure_ascii=False)

    print(f"Migration complete! {len(paintings_data)} paintings migrated to {PAINTINGS_JSON_PATH}")

def add_order_to_json(filepath: Path):
    print(f"Updating {filepath.name} with order field...")
    if not filepath.is_file():
        print(f"File not found, skipping.")
        return

    with open(filepath, 'r+', encoding='utf-8') as f:
        data = json.load(f)
        for i, item in enumerate(data):
            if 'order' not in item:
                item['order'] = i
        f.seek(0)
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.truncate()
    print("Update complete.")


if __name__ == "__main__":
    # WARNING: RUN THIS SCRIPT ONLY ONCE!
    # It will rename your image files and create paintings.json.

    # Step 1: Migrate paintings from filenames to paintings.json
    migrate_paintings()

    # Step 2: Add 'order' field to projects and exhibitions if not present
    add_order_to_json(PROJEKTY_JSON_PATH)
    add_order_to_json(VYSTAVY_JSON_PATH)

    print("\nAll migrations finished.")