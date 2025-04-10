import os
import re
import shutil
import subprocess
import asyncio
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Path as FastApiPath, Response
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


# --- Configuration ---
IMAGES_DIR = Path("./images/obrazy")
BUILD_SCRIPT_PATH = Path("./build.py")
PYTHON_EXECUTABLE = "python3" # Or just "python"

# Create images directory if it doesn't exist
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# --- Pydantic Models ---
class PaintingBase(BaseModel):
    """Base model for painting data, used for responses."""
    id: int # Unique identifier
    order: int # Sorting order
    title: str
    sold: bool
    filename: str
    url: str # URL path to access the image

# No separate Create model needed if using Form fields directly,
# but keeping it explicit can be good practice. Let's add order here.
class PaintingCreateUpdate(BaseModel):
    """Model for data expected from forms (subset used for create/update)."""
    title: Optional[str] = Field(None, description="Title of the painting")
    sold: Optional[bool] = Field(None, description="Is the painting sold?")
    order: Optional[int] = Field(None, description="Display order of the painting")


# --- Helper Functions ---

def sanitize_filename(name: str) -> str:
    """Removes characters potentially problematic in filenames."""
    name = name.strip()
    # Replace spaces and problematic characters with underscores
    name = re.sub(r'[\\/*?:"<>|\s]+', '_', name)
    # Remove any remaining non-alphanumeric characters except underscore and hyphen
    name = re.sub(r'[^a-zA-Z0-9_-]', '', name)
    # Prevent excessively long filenames (optional)
    return name[:100] # Limit title part length

def parse_filename(filename: str) -> Optional[PaintingBase]:
    """
    Parses the filename to extract painting details.
    Expected format: [SOLD_]<id>_<order>_<title>.<ext>
    """
    # Regex to capture SOLD status (optional), ID, Order, Title, and extension
    # Allows SOLD_, sold_, etc. at the start
    match = re.match(
        r"^(?:(SOLD|sold)_)?(\d+)_(\d+)_(.+)\.(jpg|jpeg|png|gif)$",
        filename,
        re.IGNORECASE
    )
    if match:
        sold_status_str, id_str, order_str, title_part, extension = match.groups()
        sold = bool(sold_status_str) # True if SOLD/sold prefix exists
        painting_id = int(id_str)
        painting_order = int(order_str)
        # Title part might still have underscores from sanitization, keep them for consistency
        title = title_part
        url_path = f"/{IMAGES_DIR.name}/{filename}" # Construct URL path

        return PaintingBase(
            id=painting_id,
            order=painting_order,
            title=title, # Keep title as it is in the filename
            sold=sold,
            filename=filename,
            url=url_path
        )
    print(f"Warning: Could not parse filename: {filename}") # Add logging
    return None

def get_paintings_list() -> List[PaintingBase]:
    """Reads the image directory, parses filenames, and returns a list sorted by order."""
    paintings = []
    if not IMAGES_DIR.is_dir():
        return []

    for filename in os.listdir(IMAGES_DIR):
        file_path = IMAGES_DIR / filename
        if file_path.is_file():
            parsed = parse_filename(filename)
            if parsed:
                paintings.append(parsed)

    # Sort paintings primarily by 'order' (ascending), then by 'id' (descending) as a tie-breaker
    paintings.sort(key=lambda p: (p.order, -p.id))
    return paintings

def find_painting_file(painting_id: int) -> Optional[Path]:
    """
    Finds the file corresponding to a given unique painting ID.
    Filename format: [SOLD_]<id>_<order>_<title>.<ext>
    """
    if not IMAGES_DIR.is_dir():
        return None

    # Regex to match the ID at the start or after SOLD_
    # It needs to be specific to avoid matching the order number
    pattern = re.compile(r"^(?:(?:SOLD|sold)_)?(" + str(painting_id) + r")_\d+_.*", re.IGNORECASE)

    for filename in os.listdir(IMAGES_DIR):
        if pattern.match(filename):
            return IMAGES_DIR / filename
    return None

def get_next_painting_id() -> int:
    """Determines the next available unique painting ID."""
    max_id = 0
    if not IMAGES_DIR.is_dir():
        return 1 # Start from 1 if dir is empty

    # Need to parse filenames to get IDs, not rely on the order list
    ids = set()
    id_pattern = re.compile(r"^(?:(?:SOLD|sold)_)?(\d+)_\d+_.*", re.IGNORECASE)
    for filename in os.listdir(IMAGES_DIR):
         match = id_pattern.match(filename)
         if match:
             ids.add(int(match.group(1)))

    if ids:
        max_id = max(ids)

    return max_id + 1

async def run_build_script():
    """Executes the build.py script asynchronously."""
    try:
        print(f"Triggering build script: {BUILD_SCRIPT_PATH}...")
        process = await asyncio.create_subprocess_exec(
            PYTHON_EXECUTABLE,
            str(BUILD_SCRIPT_PATH),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            print("Build script executed successfully.")
            # print(stdout.decode()) # Uncomment for build output
        else:
            print(f"Build script failed with error code {process.returncode}:")
            print(stderr.decode())
    except FileNotFoundError:
        print(f"Error: Build script not found at {BUILD_SCRIPT_PATH} or python executable '{PYTHON_EXECUTABLE}' not found.")
    except Exception as e:
        print(f"An error occurred while running the build script: {e}")

def trigger_build(background_tasks: BackgroundTasks):
    """Adds the build script execution to background tasks."""
    print("Adding build task to background.")
    background_tasks.add_task(run_build_script)

# --- FastAPI Application ---
app = FastAPI(title="Painting Management API")

# --- CORS Middleware ---
# Allow all origins for development, restrict in production
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Endpoints ---

@app.get("/paintings", response_model=List[PaintingBase], summary="List all paintings")
async def list_paintings():
    """
    Retrieves a list of all paintings, sorted by the 'order' field (ascending),
    then by ID (descending) as a tie-breaker.
    """
    return get_paintings_list()

@app.get("/paintings/{painting_id}", response_model=PaintingBase, summary="Get a specific painting by ID")
async def get_painting(painting_id: int = FastApiPath(..., description="The unique ID of the painting to retrieve")):
    """Retrieves details for a single painting by its unique ID."""
    painting_file = find_painting_file(painting_id)
    if not painting_file:
        raise HTTPException(status_code=404, detail=f"Painting with ID {painting_id} not found.")

    parsed = parse_filename(painting_file.name)
    if not parsed:
        # This indicates a mismatch between find_painting_file and parse_filename logic
        print(f"Error: Found file '{painting_file.name}' but failed to parse it.")
        raise HTTPException(status_code=500, detail="Internal server error: Failed to parse painting filename.")
    return parsed


@app.post("/paintings", response_model=PaintingBase, status_code=201, summary="Add a new painting")
async def create_painting(
    background_tasks: BackgroundTasks,
    title: str = Form(..., description="Title of the painting"),
    order: int = Form(..., description="Display order for the painting"),
    sold: bool = Form(False, description="Is the painting sold?"),
    image: UploadFile = File(..., description="Image file for the painting")
):
    """
    Adds a new painting. Requires form data with 'title', 'order', 'sold' status,
    and an 'image' file upload. Assigns a new unique ID.
    Triggers the build script in the background.
    Filename format: [SOLD_]<id>_<order>_<title>.<ext>
    """
    allowed_extensions = {".jpg", ".jpeg", ".png", ".gif"}
    file_extension = Path(image.filename).suffix.lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Invalid image file type. Allowed types: {', '.join(allowed_extensions)}")

    if order < 0:
         raise HTTPException(status_code=400, detail="Order must be a non-negative integer.")

    painting_id = get_next_painting_id()
    sanitized_title = sanitize_filename(title)
    prefix = "SOLD_" if sold else ""
    # New filename format: prefix + id + order + title + extension
    new_filename = f"{prefix}{painting_id}_{order}_{sanitized_title}{file_extension}"
    file_location = IMAGES_DIR / new_filename

    # Check for potential filename collision (though ID should prevent this)
    if file_location.exists():
         print(f"Warning: Filename {new_filename} already exists. Overwriting. (ID: {painting_id})")
         # Or raise HTTPException(status_code=409, detail="Filename conflict detected.")

    try:
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(image.file, file_object)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save image file: {e}")
    finally:
        await image.close()

    trigger_build(background_tasks)

    created_painting_data = parse_filename(new_filename)
    if not created_painting_data:
        print(f"Error: Saved file as '{new_filename}' but failed to parse it back.")
        raise HTTPException(status_code=500, detail="Internal server error: Failed to process newly created painting.")

    # Use model_dump() for Pydantic v2
    return JSONResponse(status_code=201, content=created_painting_data.model_dump())


@app.put("/paintings/{painting_id}", response_model=PaintingBase, summary="Update a painting by ID")
async def update_painting(
    background_tasks: BackgroundTasks,
    painting_id: int = FastApiPath(..., description="The unique ID of the painting to update"),
    title: Optional[str] = Form(None, description="New title for the painting"),
    order: Optional[int] = Form(None, description="New display order for the painting"),
    sold: Optional[bool] = Form(None, description="New sold status for the painting")
):
    """
    Updates a painting's title, order, or sold status by renaming the file.
    Requires the unique painting ID in the path.
    Provide 'title', 'order', and/or 'sold' in the form data.
    Triggers the build script in the background.
    Filename format: [SOLD_]<id>_<order>_<title>.<ext>
    """
    if title is None and sold is None and order is None:
        raise HTTPException(status_code=400, detail="No update data provided. Provide 'title', 'order', or 'sold'.")

    if order is not None and order < 0:
         raise HTTPException(status_code=400, detail="Order must be a non-negative integer.")

    current_file_path = find_painting_file(painting_id)
    if not current_file_path:
        raise HTTPException(status_code=404, detail=f"Painting with ID {painting_id} not found.")

    current_details = parse_filename(current_file_path.name)
    if not current_details:
        print(f"Error: Found file '{current_file_path.name}' for ID {painting_id} but failed to parse it.")
        raise HTTPException(status_code=500, detail="Internal server error: Failed to parse current painting filename.")

    # Determine new values, using current values as defaults
    new_title_sanitized = sanitize_filename(title) if title is not None else current_details.title
    new_order = order if order is not None else current_details.order
    new_sold_status = sold if sold is not None else current_details.sold

    # Check if any actual change occurred
    if (new_title_sanitized == current_details.title and
            new_order == current_details.order and
            new_sold_status == current_details.sold):
        print(f"No changes detected for painting ID {painting_id}. Returning current details.")
        return current_details # No changes needed

    # Construct new filename
    new_prefix = "SOLD_" if new_sold_status else ""
    file_extension = current_file_path.suffix # Keep original extension
    new_filename = f"{new_prefix}{painting_id}_{new_order}_{new_title_sanitized}{file_extension}"
    new_file_path = IMAGES_DIR / new_filename

    # Rename the file only if the name actually changes
    if new_file_path != current_file_path:
        # Check if the target filename already exists (could happen with title/order changes)
        # This check is less critical now because the ID is fixed, but good practice.
        if new_file_path.exists():
             print(f"Warning: Target filename {new_filename} already exists. Renaming may fail or overwrite.")
             # Consider how to handle this - maybe disallow updates that cause collisions?
             # For now, let os.rename handle it (might raise error on some OS)

        try:
            print(f"Renaming '{current_file_path.name}' to '{new_filename}'")
            os.rename(current_file_path, new_file_path)
        except OSError as e:
            print(f"Error renaming file for ID {painting_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to rename painting file: {e}")
        except Exception as e:
            print(f"Unexpected error during rename for ID {painting_id}: {e}")
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred during rename: {e}")
    else:
        print(f"Filename for ID {painting_id} remains '{new_filename}'. No rename needed.")


    trigger_build(background_tasks)

    # Return the updated painting details based on the *new* filename
    updated_details = parse_filename(new_filename)
    if not updated_details:
        print(f"Error: Renamed file to '{new_filename}' but failed to parse it back.")
        raise HTTPException(status_code=500, detail="Internal server error: Failed to parse updated painting filename.")

    return updated_details


@app.delete("/paintings/{painting_id}", status_code=204, summary="Delete a painting by ID")
async def delete_painting(
    background_tasks: BackgroundTasks,
    painting_id: int = FastApiPath(..., description="The unique ID of the painting to delete")
):
    """
    Deletes a painting file by its unique ID.
    Triggers the build script in the background. Returns No Content on success.
    """
    painting_file = find_painting_file(painting_id)
    if not painting_file:
        # Return 204 even if not found, as the end state (not present) is achieved.
        # Or raise 404 if you want to explicitly signal "not found". Let's stick to 404 for clarity.
        raise HTTPException(status_code=404, detail=f"Painting with ID {painting_id} not found.")

    try:
        print(f"Deleting painting file: {painting_file}")
        os.remove(painting_file)
    except OSError as e:
        print(f"Error deleting file for ID {painting_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete painting file: {e}")
    except Exception as e:
        print(f"Unexpected error during delete for ID {painting_id}: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during delete: {e}")

    trigger_build(background_tasks)

    # Return No Content (204) on successful deletion
    return Response(status_code=204)


@app.post("/build", status_code=202, summary="Manually trigger build script")
async def trigger_manual_build(background_tasks: BackgroundTasks):
    """
    Manually triggers the build.py script execution in the background.
    Returns Accepted (202) immediately.
    """
    trigger_build(background_tasks)
    return JSONResponse(content={"message": "Build process triggered."}, status_code=202)


# --- Static File Serving ---
# Serve the 'obrazy' directory under the '/obrazy' path
app.mount(f"/{IMAGES_DIR.name}", StaticFiles(directory=IMAGES_DIR), name="painting_images")

# --- How to Run (using uvicorn) ---
# Save this code as api.py (or your preferred name)
# Run in terminal: uvicorn api:app --reload --host 0.0.0.0 --port 8000
# Access API docs at http://127.0.0.1:8000/docs (or your server's IP)
