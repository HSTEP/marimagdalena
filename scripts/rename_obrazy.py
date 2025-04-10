import os
import re
import sys

# --- Configuration ---
# Set the directory containing the images you want to process
IMAGE_DIRECTORY = "./images/obrazy" # <--- CHANGE THIS PATH IF NEEDED

# Regex to find files ending with '_sold' before the extension
# It captures the part before '_sold' (group 1) and the extension (group 2)
# Case-insensitive matching for '_sold' and extensions
sold_suffix_pattern = re.compile(r"^(.*?)_sold(\.(?:jpg|jpeg|png|gif))$", re.IGNORECASE)

# --- Main Renaming Logic ---
def rename_sold_images(directory):
    """
    Scans the specified directory and renames image files
    from '<name>_sold.<ext>' to 'SOLD_<name>.<ext>'.
    """
    print(f"Scanning directory: {directory}")

    # Check if the directory exists
    if not os.path.isdir(directory):
        print(f"Error: Directory not found - '{directory}'")
        sys.exit(1) # Exit if directory is invalid

    renamed_count = 0
    skipped_count = 0
    error_count = 0

    # Iterate through all items in the directory
    for filename in os.listdir(directory):
        # Construct the full path for the current item
        old_path = os.path.join(directory, filename)

        # Process only files (skip subdirectories)
        if os.path.isfile(old_path):
            # Check if the filename matches the '_sold' suffix pattern
            match = sold_suffix_pattern.match(filename)
            if match:
                # Extract the parts from the matched filename
                base_name = match.group(1)
                extension = match.group(2)

                # Construct the new filename with the 'SOLD_' prefix
                new_filename = f"SOLD_{base_name}{extension}"
                # Construct the full path for the new filename
                new_path = os.path.join(directory, new_filename)

                # Avoid renaming if the target already exists (optional check)
                if os.path.exists(new_path):
                    print(f"Skipping rename: Target file '{new_filename}' already exists.")
                    skipped_count += 1
                    continue

                # Avoid renaming if the base_name itself starts with SOLD_
                # (prevents SOLD_SOLD_...) - unlikely with suffix logic but safe check
                if base_name.upper().startswith("SOLD_"):
                     print(f"Skipping rename: File '{filename}' seems to already have a SOLD prefix in base.")
                     skipped_count += 1
                     continue


                # Attempt to rename the file
                try:
                    os.rename(old_path, new_path)
                    print(f"Renamed: '{filename}' -> '{new_filename}'")
                    renamed_count += 1
                except OSError as e:
                    print(f"Error renaming '{filename}': {e}")
                    error_count += 1
                except Exception as e:
                    print(f"An unexpected error occurred while renaming '{filename}': {e}")
                    error_count += 1
            # else:
                # Optional: Print files that don't match the pattern
                # print(f"Skipping non-matching file: {filename}")
                # skipped_count += 1

    # Print summary
    print("\n--- Renaming Summary ---")
    print(f"Files renamed: {renamed_count}")
    print(f"Files skipped: {skipped_count}")
    print(f"Errors encountered: {error_count}")
    print("------------------------")

# --- Run the script ---
if __name__ == "__main__":
    rename_sold_images(IMAGE_DIRECTORY)
