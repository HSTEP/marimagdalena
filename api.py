import os
import re
import shutil
import subprocess
import asyncio
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Path as FastApiPath
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


# --- Configuration ---
# Adjust these paths as necessary
IMAGES_DIR = Path("./images/obrazy")
BUILD_SCRIPT_PATH = Path("./build.py")
PYTHON_EXECUTABLE = "python3" # Or just "python" depending on your system

# Create images directory if it doesn't exist
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# --- Pydantic Models ---
class PaintingBase(BaseModel):
    """Base model for painting data, used for responses."""
    id: int
    title: str
    sold: bool
    filename: str
    url: str # URL path to access the image

class PaintingCreate(BaseModel):
    """Model for creating a painting (data from form)."""
    title: str = Field(..., description="Title of the painting")
    sold: bool = Field(False, description="Is the painting sold?")

# --- Helper Functions ---

def sanitize_filename(name: str) -> str:
    """Removes characters potentially problematic in filenames."""
    # Remove leading/trailing whitespace
    name = name.strip()
    # Replace spaces and problematic characters with underscores
    name = re.sub(r'[\\/*?:"<>|\s]+', '_', name)
    # Remove any remaining non-alphanumeric characters except underscore and hyphen
    name = re.sub(r'[^a-zA-Z0-9_-]', '', name)
    return name

def parse_filename(filename: str) -> Optional[PaintingBase]:
    """Parses the filename to extract painting details."""
    # Regex to capture SOLD status (optional), ID, Title, and extension
    # Allows SOLD_, sold_, etc. at the start
    match = re.match(r"^(?:(SOLD|sold)_)?(\d+)_(.+)\.(jpg|jpeg|png|gif)$", filename, re.IGNORECASE)
    if match:
        sold_status_str, id_str, title_part, extension = match.groups()
        sold = bool(sold_status_str) # True if SOLD/sold prefix exists
        painting_id = int(id_str)
        # Replace underscores back to spaces for display title (optional)
        # title = title_part.replace('_', ' ')
        title = title_part # Keep underscores in title if preferred, or handle display elsewhere
        url_path = f"/{IMAGES_DIR.name}/{filename}" # Construct URL path relative to web server root

        return PaintingBase(
            id=painting_id,
            title=title,
            sold=sold,
            filename=filename,
            url=url_path
        )
    return None

def get_paintings_list() -> List[PaintingBase]:
    """Reads the image directory, parses filenames, and returns a sorted list."""
    paintings = []
    if not IMAGES_DIR.is_dir():
        return [] # Return empty list if directory doesn't exist

    for filename in os.listdir(IMAGES_DIR):
        file_path = IMAGES_DIR / filename
        if file_path.is_file():
            parsed = parse_filename(filename)
            if parsed:
                paintings.append(parsed)

    # Sort paintings by ID, descending (newest first)
    paintings.sort(key=lambda p: p.id, reverse=True)
    return paintings

def find_painting_file(painting_id: int) -> Optional[Path]:
    """Finds the file corresponding to a given painting ID."""
    if not IMAGES_DIR.is_dir():
        return None

    for filename in os.listdir(IMAGES_DIR):
        # Regex to match ID at the start or after SOLD_
        match = re.match(r"^(?:(?:SOLD|sold)_)?(\d+)_", filename, re.IGNORECASE)
        if match:
            current_id = int(match.group(1))
            if current_id == painting_id:
                return IMAGES_DIR / filename
    return None

def get_next_painting_id() -> int:
    """Determines the next available painting ID."""
    max_id = 0
    paintings = get_paintings_list() # Reuse existing function to get parsed data
    if paintings:
        max_id = max(p.id for p in paintings)
    return max_id + 1

async def run_build_script():
    """Executes the build.py script."""
    try:
        print(f"Triggering build script: {BUILD_SCRIPT_PATH}...")
        # Use asyncio.create_subprocess_exec for non-blocking execution
        process = await asyncio.create_subprocess_exec(
            PYTHON_EXECUTABLE,
            str(BUILD_SCRIPT_PATH),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            print("Build script executed successfully.")
            # print(stdout.decode()) # Uncomment to see build output
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



origins = [
"*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allows specified origins
    allow_credentials=True, # Allows cookies/authorization headers
    allow_methods=["*"],    # Allows all standard methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],    # Allows all headers
)

# --- API Endpoints ---

@app.get("/paintings", response_model=List[PaintingBase], summary="List all paintings")
async def list_paintings():
    """Retrieves a list of all paintings, sorted by ID descending."""
    return get_paintings_list()

@app.get("/paintings/{painting_id}", response_model=PaintingBase, summary="Get a specific painting")
async def get_painting(painting_id: int = FastApiPath(..., description="The ID of the painting to retrieve")):
    """Retrieves details for a single painting by its ID."""
    painting_file = find_painting_file(painting_id)
    if not painting_file:
        raise HTTPException(status_code=404, detail=f"Painting with ID {painting_id} not found.")
    parsed = parse_filename(painting_file.name)
    if not parsed:
         # Should not happen if find_painting_file worked, but good practice
         raise HTTPException(status_code=500, detail="Failed to parse painting filename.")
    return parsed


@app.post("/paintings", response_model=PaintingBase, status_code=201, summary="Add a new painting")
async def create_painting(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    sold: bool = Form(False),
    image: UploadFile = File(...)
):
    """
    Adds a new painting. Requires form data with 'title', 'sold' status,
    and an 'image' file upload. Triggers the build script in the background.
    """
    # Basic validation for uploaded file type
    allowed_extensions = {".jpg", ".jpeg", ".png", ".gif"}
    file_extension = Path(image.filename).suffix.lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Invalid image file type. Allowed types: {', '.join(allowed_extensions)}")

    painting_id = get_next_painting_id()
    sanitized_title = sanitize_filename(title) # Sanitize title for filename use
    prefix = "SOLD_" if sold else ""
    new_filename = f"{prefix}{painting_id}_{sanitized_title}{file_extension}"
    file_location = IMAGES_DIR / new_filename

    # Save the uploaded file
    try:
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(image.file, file_object)
    except Exception as e:
        # Handle potential file system errors
        raise HTTPException(status_code=500, detail=f"Failed to save image file: {e}")
    finally:
        await image.close() # Ensure the file buffer is closed

    # Trigger the build script in the background
    trigger_build(background_tasks)

    # Return the details of the newly created painting
    created_painting = parse_filename(new_filename)
    if not created_painting:
         # This indicates an internal issue with filename generation/parsing
         raise HTTPException(status_code=500, detail="Failed to parse newly created painting filename.")

    return JSONResponse(status_code=201, content=created_painting.model_dump())


@app.put("/paintings/{painting_id}", response_model=PaintingBase, summary="Update a painting")
async def update_painting(
    background_tasks: BackgroundTasks,
    painting_id: int = FastApiPath(..., description="The ID of the painting to update"),
    title: Optional[str] = Form(None), # Allow updating title
    sold: Optional[bool] = Form(None)  # Allow updating sold status
):
    """
    Updates a painting's title or sold status by renaming the file.
    Triggers the build script in the background.
    Provide 'title' and/or 'sold' in the form data.
    """
    if title is None and sold is None:
        raise HTTPException(status_code=400, detail="No update data provided. Provide 'title' or 'sold'.")

    current_file_path = find_painting_file(painting_id)
    if not current_file_path:
        raise HTTPException(status_code=404, detail=f"Painting with ID {painting_id} not found.")

    current_details = parse_filename(current_file_path.name)
    if not current_details:
        raise HTTPException(status_code=500, detail="Failed to parse current painting filename.")

    # Determine new details
    new_title_part = sanitize_filename(title) if title is not None else current_details.title
    new_sold_status = sold if sold is not None else current_details.sold

    # Check if update is necessary (no change)
    if new_title_part == current_details.title and new_sold_status == current_details.sold:
        return current_details # No changes needed, return current details

    # Construct new filename
    new_prefix = "SOLD_" if new_sold_status else ""
    file_extension = current_file_path.suffix # Keep original extension
    new_filename = f"{new_prefix}{painting_id}_{new_title_part}{file_extension}"
    new_file_path = IMAGES_DIR / new_filename

    # Rename the file
    if new_file_path != current_file_path: # Only rename if filename actually changes
        try:
            os.rename(current_file_path, new_file_path)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Failed to rename painting file: {e}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred during rename: {e}")

    # Trigger the build script in the background
    trigger_build(background_tasks)

    # Return the updated painting details
    updated_details = parse_filename(new_filename)
    if not updated_details:
        raise HTTPException(status_code=500, detail="Failed to parse updated painting filename.")

    return updated_details


@app.delete("/paintings/{painting_id}", status_code=204, summary="Delete a painting")
async def delete_painting(
    background_tasks: BackgroundTasks,
    painting_id: int = FastApiPath(..., description="The ID of the painting to delete")
):
    """
    Deletes a painting file by its ID.
    Triggers the build script in the background. Returns No Content on success.
    """
    painting_file = find_painting_file(painting_id)
    if not painting_file:
        raise HTTPException(status_code=404, detail=f"Painting with ID {painting_id} not found.")

    # Delete the file
    try:
        os.remove(painting_file)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete painting file: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during delete: {e}")

    # Trigger the build script in the background
    trigger_build(background_tasks)

    # No content to return on successful deletion
    return Response(status_code=204)


@app.post("/build", status_code=202, summary="Manually trigger build script")
async def trigger_manual_build(background_tasks: BackgroundTasks):
    """
    Manually triggers the build.py script execution in the background.
    Returns Accepted immediately.
    """
    trigger_build(background_tasks)
    return {"message": "Build process triggered."}


# --- Optional: Add static file serving for images if needed for testing ---
# from fastapi.staticfiles import StaticFiles
app.mount("/obrazy", StaticFiles(directory=IMAGES_DIR), name="painting_images")

# --- How to Run (using uvicorn) ---
# Save this code as main.py
# Run in terminal: uvicorn main:app --reload
# Access API docs at http://127.0.0.1:8000/docs
