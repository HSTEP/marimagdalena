import os
import re
import shutil
import subprocess
import asyncio
import json # Import json
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Path as FastApiPath, Response, Body
from pydantic import BaseModel, Field, HttpUrl
from starlette.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# --- Configuration ---
# Use Path objects relative to this script's location
BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / "images/obrazy"
BUILD_SCRIPT_PATH = BASE_DIR / "build.py"
DATA_DIR = BASE_DIR / "src/data" # Directory for JSON data files
PROJEKTY_JSON_PATH = DATA_DIR / "projekty.json"
VYSTAVY_JSON_PATH = DATA_DIR / "vystavy.json"
PYTHON_EXECUTABLE = "python3" # Or just "python"

# Create directories if they don't exist
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- Pydantic Models ---

# == Painting Models (Existing - Based on Filenames) ==
class PaintingBase(BaseModel):
    """Base model for painting data, used for responses."""
    id: int # Unique identifier
    order: int # Sorting order
    title: str
    sold: bool
    filename: str
    url: str # URL path to access the image

class PaintingCreateUpdate(BaseModel):
    """Model for data expected from forms (subset used for create/update)."""
    title: Optional[str] = Field(None, description="Title of the painting")
    sold: Optional[bool] = Field(None, description="Is the painting sold?")
    order: Optional[int] = Field(None, description="Display order of the painting")

# == Link Model (Used in Project and Exhibition) ==
class Link(BaseModel):
    url: str # Can be HttpUrl if validation is strict, but str allows relative paths too
    text: str

# == Project Models (Based on projekty.json) ==
class ProjectBase(BaseModel):
    id: int
    date: Optional[str] = None
    title: str
    image: Optional[str] = None # Relative path to image
    description: Optional[str] = None
    links: List[Link] = []
    video_url: Optional[str] = None # Optional URL for video iframe

class ProjectCreate(BaseModel):
    # ID is generated automatically
    date: Optional[str] = Field(None, description="Date of the project (e.g., 'Prosinec 2021, Dobřany')")
    title: str = Field(..., description="Title of the project (HTML allowed)")
    image: Optional[str] = Field(None, description="Relative path to the project image (e.g., 'images/projekty/kytky_koksina.jpg')")
    description: Optional[str] = Field(None, description="Description of the project")
    links: List[Link] = Field([], description="List of links related to the project")
    video_url: Optional[str] = Field(None, description="URL for the video iframe, if applicable")

class ProjectUpdate(ProjectCreate): # Inherits fields from Create
    pass # For PUT, we expect all fields (except ID)

# == Exhibition Models (Based on vystavy.json) ==
class ExhibitionBase(BaseModel):
    id: int
    date: Optional[str] = None
    title: str
    image: Optional[str] = None # Relative path to image
    links: List[Link] = []

class ExhibitionCreate(BaseModel):
    # ID is generated automatically
    date: Optional[str] = Field(None, description="Date of the exhibition (e.g., '3. Srpna, 2024' or 'Připravuje se')")
    title: str = Field(..., description="Title of the exhibition")
    image: Optional[str] = Field(None, description="Relative path to the exhibition image (e.g., 'images/vystavy/nausova.jpg')")
    links: List[Link] = Field([], description="List of links related to the exhibition")

class ExhibitionUpdate(ExhibitionCreate): # Inherits fields from Create
    pass # For PUT, we expect all fields (except ID)


# --- Helper Functions ---

# == JSON Data Handling ==
def load_data(filepath: Path) -> List[Dict[str, Any]]:
    """Loads JSON data from a file, ensuring it's a list."""
    if not filepath.is_file():
        print(f"Data file not found: {filepath}. Returning empty list.")
        return []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, list):
            print(f"Warning: Data in {filepath} is not a list. Returning empty list.")
            return []
        # Ensure all items have an 'id' - assign if missing (simple approach)
        next_id = 1
        seen_ids = set()
        for item in data:
            if isinstance(item, dict):
                item_id = item.get('id')
                if item_id is None or not isinstance(item_id, int) or item_id in seen_ids:
                    while next_id in seen_ids:
                        next_id += 1
                    item['id'] = next_id
                    print(f"Assigned new ID {next_id} to item in {filepath}")
                seen_ids.add(item['id'])
                if item['id'] >= next_id:
                    next_id = item['id'] + 1
            else:
                 print(f"Warning: Found non-dict item in {filepath}: {item}")

        # Ensure uniqueness again after potential assignments
        final_data = []
        final_ids = set()
        for item in data:
             if isinstance(item, dict) and item.get('id') not in final_ids:
                 final_data.append(item)
                 final_ids.add(item['id'])
             elif isinstance(item, dict):
                 print(f"Warning: Duplicate ID {item.get('id')} found after assignment in {filepath}. Skipping duplicate.")
        return final_data

    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {filepath}. Returning empty list.")
        return []
    except Exception as e:
        print(f"Error loading data from {filepath}: {e}")
        return []

def save_data(filepath: Path, data: List[Dict[str, Any]]):
    """Saves data list to a JSON file."""
    try:
        # Ensure parent directory exists
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False) # Use indent for readability
        print(f"Data successfully saved to {filepath}")
    except Exception as e:
        print(f"Error saving data to {filepath}: {e}")
        # Consider raising an exception here to signal failure in API endpoints
        raise HTTPException(status_code=500, detail=f"Failed to save data to {filepath}")

def get_next_id(data: List[Dict[str, Any]]) -> int:
    """Calculates the next available ID."""
    if not data:
        return 1
    max_id = 0
    for item in data:
        if isinstance(item, dict) and isinstance(item.get('id'), int):
             max_id = max(max_id, item['id'])
    return max_id + 1

# == Build Script Trigger ==
async def run_build_script():
    """Executes the build.py script asynchronously."""
    # Ensure data files are potentially saved before building
    # (Saving happens synchronously in the endpoint before calling this)
    try:
        print(f"Triggering build script: {BUILD_SCRIPT_PATH}...")
        process = await asyncio.create_subprocess_exec(
            PYTHON_EXECUTABLE,
            str(BUILD_SCRIPT_PATH),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=BASE_DIR # Run build script from the base directory
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


# == Painting Filename Helpers (Existing) ==
def sanitize_filename(name: str) -> str:
    """Removes characters potentially problematic in filenames."""
    name = name.strip()
    # name = re.sub(r'[\\/*?:"<>|\s]+', '_', name) # Example stricter sanitization
    # name = re.sub(r'[^a-zA-Z0-9_-]', '', name)
    return name[:100]

def parse_filename(filename: str) -> Optional[PaintingBase]:
    """
    Parses the filename to extract painting details.
    Expected format: [SOLD_]<id>_<order>_<title>.<ext>
    """
    match = re.match(
        r"^(?:(SOLD|sold)_)?(\d+)_(\d+)_(.+)\.(jpg|jpeg|png|gif)$",
        filename,
        re.IGNORECASE
    )
    if match:
        sold_status_str, id_str, order_str, title_part, extension = match.groups()
        sold = bool(sold_status_str)
        painting_id = int(id_str)
        painting_order = int(order_str)
        title = title_part
        # Use Path object methods for URL construction if possible, or stick to string formatting
        url_path = f"/{IMAGES_DIR.name}/{filename}"

        return PaintingBase(
            id=painting_id,
            order=painting_order,
            title=title,
            sold=sold,
            filename=filename,
            url=url_path
        )
    print(f"Warning: Could not parse filename: {filename}")
    return None

def get_paintings_list() -> List[PaintingBase]:
    """Reads the image directory, parses filenames, and returns a list sorted by order."""
    # NOTE: This relies on filenames. Consider migrating painting data to JSON as well.
    paintings = []
    if not IMAGES_DIR.is_dir():
        return []
    for filename in os.listdir(IMAGES_DIR):
        file_path = IMAGES_DIR / filename
        if file_path.is_file():
            parsed = parse_filename(filename)
            if parsed:
                paintings.append(parsed)
    paintings.sort(key=lambda p: (p.order, -p.id))
    return paintings

def find_painting_file(painting_id: int) -> Optional[Path]:
    """Finds the file corresponding to a given unique painting ID."""
    # NOTE: Relies on filename structure.
    if not IMAGES_DIR.is_dir():
        return None
    pattern = re.compile(r"^(?:(?:SOLD|sold)_)?(" + str(painting_id) + r")_\d+_.*", re.IGNORECASE)
    for filename in os.listdir(IMAGES_DIR):
        if pattern.match(filename):
            return IMAGES_DIR / filename
    return None

def get_next_painting_id() -> int:
    """Determines the next available unique painting ID based on filenames."""
    # NOTE: Relies on filename structure.
    max_id = 0
    if not IMAGES_DIR.is_dir():
        return 1
    ids = set()
    id_pattern = re.compile(r"^(?:(?:SOLD|sold)_)?(\d+)_\d+_.*", re.IGNORECASE)
    for filename in os.listdir(IMAGES_DIR):
        match = id_pattern.match(filename)
        if match:
            ids.add(int(match.group(1)))
    if ids:
        max_id = max(ids)
    return max_id + 1

# --- FastAPI Application ---
app = FastAPI(title="Maří Magdalena Content API")

# --- CORS Middleware ---
origins = ["*"] # Allow all for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Endpoints ---

# == Painting Endpoints (Existing - Filename Based) ==
# NOTE: These endpoints manage paintings based on filenames in the images/obrazy directory.
# Consider refactoring to use a JSON file (e.g., data/paintings.json) for metadata
# similar to projects and exhibitions for better consistency and management.

@app.get("/paintings", response_model=List[PaintingBase], summary="List all paintings (from filenames)")
async def list_paintings():
    """Retrieves a list of paintings by parsing filenames in the images directory."""
    return get_paintings_list()

@app.get("/paintings/{painting_id}", response_model=PaintingBase, summary="Get a specific painting by ID (from filename)")
async def get_painting(painting_id: int = FastApiPath(..., description="The unique ID of the painting")):
    """Retrieves details for a single painting by finding and parsing its filename."""
    painting_file = find_painting_file(painting_id)
    if not painting_file:
        raise HTTPException(status_code=404, detail=f"Painting with ID {painting_id} not found.")
    parsed = parse_filename(painting_file.name)
    if not parsed:
        raise HTTPException(status_code=500, detail="Internal server error: Failed to parse painting filename.")
    return parsed

@app.post("/paintings", response_model=PaintingBase, status_code=201, summary="Add a new painting (saves image, updates filename)")
async def create_painting(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    order: int = Form(...),
    sold: bool = Form(False),
    image: UploadFile = File(...)
):
    """Adds a new painting, saving the image with an encoded filename."""
    allowed_extensions = {".jpg", ".jpeg", ".png", ".gif"}
    file_extension = Path(image.filename).suffix.lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Invalid image file type: {file_extension}")
    if order < 0:
        raise HTTPException(status_code=400, detail="Order must be non-negative.")

    painting_id = get_next_painting_id()
    sanitized_title = sanitize_filename(title)
    prefix = "SOLD_" if sold else ""
    new_filename = f"{prefix}{painting_id}_{order}_{sanitized_title}{file_extension}"
    file_location = IMAGES_DIR / new_filename

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
        raise HTTPException(status_code=500, detail="Internal server error: Failed to process newly created painting.")
    # Use model_dump() for Pydantic v2 if needed, dict() works for v1/v2 basic cases
    return JSONResponse(status_code=201, content=created_painting_data.model_dump())


@app.put("/paintings/{painting_id}", response_model=PaintingBase, summary="Update a painting by ID (renames file)")
async def update_painting(
    background_tasks: BackgroundTasks,
    painting_id: int = FastApiPath(...),
    title: Optional[str] = Form(None),
    order: Optional[int] = Form(None),
    sold: Optional[bool] = Form(None)
):
    """Updates painting details by renaming the corresponding image file."""
    if title is None and sold is None and order is None:
        raise HTTPException(status_code=400, detail="No update data provided.")
    if order is not None and order < 0:
        raise HTTPException(status_code=400, detail="Order must be non-negative.")

    current_file_path = find_painting_file(painting_id)
    if not current_file_path:
        raise HTTPException(status_code=404, detail=f"Painting with ID {painting_id} not found.")

    current_details = parse_filename(current_file_path.name)
    if not current_details:
        raise HTTPException(status_code=500, detail="Internal server error: Failed to parse current painting filename.")

    new_title_sanitized = sanitize_filename(title) if title is not None else current_details.title
    new_order = order if order is not None else current_details.order
    new_sold_status = sold if sold is not None else current_details.sold

    if (new_title_sanitized == current_details.title and
            new_order == current_details.order and
            new_sold_status == current_details.sold):
        return current_details # No changes needed

    new_prefix = "SOLD_" if new_sold_status else ""
    file_extension = current_file_path.suffix
    new_filename = f"{new_prefix}{painting_id}_{new_order}_{new_title_sanitized}{file_extension}"
    new_file_path = IMAGES_DIR / new_filename

    if new_file_path != current_file_path:
        try:
            print(f"Renaming '{current_file_path.name}' to '{new_filename}'")
            os.rename(current_file_path, new_file_path)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Failed to rename painting file: {e}")

    trigger_build(background_tasks)
    updated_details = parse_filename(new_filename)
    if not updated_details:
        raise HTTPException(status_code=500, detail="Internal server error: Failed to parse updated painting filename.")
    return updated_details

@app.delete("/paintings/{painting_id}", status_code=204, summary="Delete a painting by ID (deletes file)")
async def delete_painting(
    background_tasks: BackgroundTasks,
    painting_id: int = FastApiPath(...)
):
    """Deletes a painting file by its unique ID."""
    painting_file = find_painting_file(painting_id)
    if not painting_file:
        raise HTTPException(status_code=404, detail=f"Painting with ID {painting_id} not found.")

    try:
        print(f"Deleting painting file: {painting_file}")
        os.remove(painting_file)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete painting file: {e}")

    trigger_build(background_tasks)
    return Response(status_code=204)


# == Project Endpoints (JSON Based) ==

@app.get("/projekty", response_model=List[ProjectBase], summary="List all projects (from JSON)")
async def list_projekty():
    """Retrieves the list of all projects from projekty.json."""
    # Add potential sorting/filtering params here if needed later
    projekty = load_data(PROJEKTY_JSON_PATH)
    return projekty

@app.get("/projekty/{projekt_id}", response_model=ProjectBase, summary="Get a specific project by ID (from JSON)")
async def get_projekt(projekt_id: int = FastApiPath(..., description="The unique ID of the project")):
    """Retrieves a single project by its ID from projekty.json."""
    projekty = load_data(PROJEKTY_JSON_PATH)
    projekt = next((p for p in projekty if isinstance(p, dict) and p.get('id') == projekt_id), None)
    if projekt is None:
        raise HTTPException(status_code=404, detail=f"Project with ID {projekt_id} not found.")
    return projekt

@app.post("/projekty", response_model=ProjectBase, status_code=201, summary="Add a new project (to JSON)")
async def create_projekt(
    projekt_data: ProjectCreate, # Receive data as JSON body
    background_tasks: BackgroundTasks
):
    """Adds a new project to projekty.json and triggers a build."""
    projekty = load_data(PROJEKTY_JSON_PATH)
    new_id = get_next_id(projekty)
    # Create the new project dictionary including the generated ID
    new_projekt = projekt_data.model_dump() # Use model_dump() for Pydantic v2+
    new_projekt['id'] = new_id
    projekty.append(new_projekt)
    try:
        save_data(PROJEKTY_JSON_PATH, projekty)
    except HTTPException as e:
        # Propagate save error
        raise e
    trigger_build(background_tasks)
    return new_projekt # Return the created project with its ID

@app.put("/projekty/{projekt_id}", response_model=ProjectBase, summary="Update a project by ID (in JSON)")
async def update_projekt(
    projekt_id: int,
    projekt_update_data: ProjectUpdate, # Receive data as JSON body
    background_tasks: BackgroundTasks
):
    """Updates an existing project in projekty.json."""
    projekty = load_data(PROJEKTY_JSON_PATH)
    projekt_index = -1
    for i, p in enumerate(projekty):
         if isinstance(p, dict) and p.get('id') == projekt_id:
            projekt_index = i
            break

    if projekt_index == -1:
        raise HTTPException(status_code=404, detail=f"Project with ID {projekt_id} not found.")

    # Create the updated project dictionary, keeping the original ID
    updated_projekt = projekt_update_data.model_dump()
    updated_projekt['id'] = projekt_id # Ensure ID remains the same
    projekty[projekt_index] = updated_projekt # Replace the item in the list

    try:
        save_data(PROJEKTY_JSON_PATH, projekty)
    except HTTPException as e:
        raise e
    trigger_build(background_tasks)
    return updated_projekt

@app.delete("/projekty/{projekt_id}", status_code=204, summary="Delete a project by ID (from JSON)")
async def delete_projekt(
    projekt_id: int,
    background_tasks: BackgroundTasks
):
    """Deletes a project from projekty.json by its ID."""
    projekty = load_data(PROJEKTY_JSON_PATH)
    original_length = len(projekty)
    # Filter out the project with the given ID
    projekty_filtered = [p for p in projekty if not (isinstance(p, dict) and p.get('id') == projekt_id)]

    if len(projekty_filtered) == original_length:
        # If the length hasn't changed, the ID wasn't found
        raise HTTPException(status_code=404, detail=f"Project with ID {projekt_id} not found.")

    try:
        save_data(PROJEKTY_JSON_PATH, projekty_filtered)
    except HTTPException as e:
        raise e
    trigger_build(background_tasks)
    return Response(status_code=204)


# == Exhibition Endpoints (JSON Based) ==

@app.get("/vystavy", response_model=List[ExhibitionBase], summary="List all exhibitions (from JSON)")
async def list_vystavy():
    """Retrieves the list of all exhibitions from vystavy.json."""
    vystavy = load_data(VYSTAVY_JSON_PATH)
    return vystavy

@app.get("/vystavy/{vystava_id}", response_model=ExhibitionBase, summary="Get a specific exhibition by ID (from JSON)")
async def get_vystava(vystava_id: int = FastApiPath(..., description="The unique ID of the exhibition")):
    """Retrieves a single exhibition by its ID from vystavy.json."""
    vystavy = load_data(VYSTAVY_JSON_PATH)
    vystava = next((v for v in vystavy if isinstance(v, dict) and v.get('id') == vystava_id), None)
    if vystava is None:
        raise HTTPException(status_code=404, detail=f"Exhibition with ID {vystava_id} not found.")
    return vystava

@app.post("/vystavy", response_model=ExhibitionBase, status_code=201, summary="Add a new exhibition (to JSON)")
async def create_vystava(
    vystava_data: ExhibitionCreate, # Receive data as JSON body
    background_tasks: BackgroundTasks
):
    """Adds a new exhibition to vystavy.json and triggers a build."""
    vystavy = load_data(VYSTAVY_JSON_PATH)
    new_id = get_next_id(vystavy)
    new_vystava = vystava_data.model_dump()
    new_vystava['id'] = new_id
    vystavy.append(new_vystava)
    try:
        save_data(VYSTAVY_JSON_PATH, vystavy)
    except HTTPException as e:
        raise e
    trigger_build(background_tasks)
    return new_vystava

@app.put("/vystavy/{vystava_id}", response_model=ExhibitionBase, summary="Update an exhibition by ID (in JSON)")
async def update_vystava(
    vystava_id: int,
    vystava_update_data: ExhibitionUpdate, # Receive data as JSON body
    background_tasks: BackgroundTasks
):
    """Updates an existing exhibition in vystavy.json."""
    vystavy = load_data(VYSTAVY_JSON_PATH)
    vystava_index = -1
    for i, v in enumerate(vystavy):
        if isinstance(v, dict) and v.get('id') == vystava_id:
            vystava_index = i
            break

    if vystava_index == -1:
        raise HTTPException(status_code=404, detail=f"Exhibition with ID {vystava_id} not found.")

    updated_vystava = vystava_update_data.model_dump()
    updated_vystava['id'] = vystava_id
    vystavy[vystava_index] = updated_vystava

    try:
        save_data(VYSTAVY_JSON_PATH, vystavy)
    except HTTPException as e:
        raise e
    trigger_build(background_tasks)
    return updated_vystava

@app.delete("/vystavy/{vystava_id}", status_code=204, summary="Delete an exhibition by ID (from JSON)")
async def delete_vystava(
    vystava_id: int,
    background_tasks: BackgroundTasks
):
    """Deletes an exhibition from vystavy.json by its ID."""
    vystavy = load_data(VYSTAVY_JSON_PATH)
    original_length = len(vystavy)
    vystavy_filtered = [v for v in vystavy if not (isinstance(v, dict) and v.get('id') == vystava_id)]

    if len(vystavy_filtered) == original_length:
        raise HTTPException(status_code=404, detail=f"Exhibition with ID {vystava_id} not found.")

    try:
        save_data(VYSTAVY_JSON_PATH, vystavy_filtered)
    except HTTPException as e:
        raise e
    trigger_build(background_tasks)
    return Response(status_code=204)


# == Build Trigger Endpoint ==
@app.post("/build", status_code=202, summary="Manually trigger build script")
async def trigger_manual_build(background_tasks: BackgroundTasks):
    """Manually triggers the build.py script execution in the background."""
    # NOTE: Ensure any pending data saves are complete before triggering if needed.
    # Here, save_data is called synchronously before trigger_build in CRUD endpoints.
    trigger_build(background_tasks)
    return JSONResponse(content={"message": "Build process triggered."}, status_code=202)


# --- Static File Serving ---
# Serve the 'obrazy' directory under the '/obrazy' path
# Ensure the path exists relative to where the API is run
if IMAGES_DIR.is_dir():
     app.mount(f"/{IMAGES_DIR.name}", StaticFiles(directory=IMAGES_DIR), name="painting_images")
else:
     print(f"Warning: Static directory for paintings not found at {IMAGES_DIR}")

# --- How to Run (using uvicorn) ---
# Save this code as api.py
# Ensure data/projekty.json and data/vystavy.json exist (can be empty lists initially [])
# Run in terminal: uvicorn api:app --reload --host 0.0.0.0 --port 8000
# Access API docs at http://127.0.0.1:8000/docs
