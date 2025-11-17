import os
import re
import shutil
import asyncio
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Path as FastApiPath, Response, Body
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / "images"
PAINTING_IMAGES_DIR = IMAGES_DIR / "obrazy"
DATA_DIR = BASE_DIR / "src/data"
PROJEKTY_JSON_PATH = DATA_DIR / "projekty.json"
VYSTAVY_JSON_PATH = DATA_DIR / "vystavy.json"
PAINTINGS_JSON_PATH = DATA_DIR / "paintings.json"
PYTHON_EXECUTABLE = "python3"
BUILD_SCRIPT_PATH = BASE_DIR / "build.py"

# Create directories
PAINTING_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
(IMAGES_DIR / "projekty").mkdir(parents=True, exist_ok=True)
(IMAGES_DIR / "vystavy").mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- Pydantic Models (UPDATED & CORRECTED) ---

class ReorderPayload(BaseModel):
    ids: List[int]

class Link(BaseModel):
    url: str
    text: str

class PaintingBase(BaseModel):
    id: int
    order: int
    title: str
    sold: bool
    filename: str
    url: str

class PaintingUpdate(BaseModel):
    title: Optional[str] = Field(None)
    sold: Optional[bool] = Field(None)

class ProjectBase(BaseModel):
    id: int
    order: int
    date: Optional[str] = None
    title: str
    image: Optional[str] = None
    description: Optional[str] = None
    links: List[Link] = []
    video_url: Optional[str] = None

class ProjectCreate(BaseModel):
    title: str = Field(...)
    date: Optional[str] = None
    image: Optional[str] = None
    description: Optional[str] = None
    links: List[Link] = []
    video_url: Optional[str] = None

class ProjectUpdate(ProjectCreate): # <-- ADDED BACK
    pass

class ExhibitionBase(BaseModel):
    id: int
    order: int
    date: Optional[str] = None
    title: str
    image: Optional[str] = None
    links: List[Link] = []

class ExhibitionCreate(BaseModel):
    title: str = Field(...)
    date: Optional[str] = None
    image: Optional[str] = None
    links: List[Link] = []

class ExhibitionUpdate(ExhibitionCreate): # <-- ADDED BACK
    pass

# --- Helper Functions ---
def load_data(filepath: Path) -> List[Dict[str, Any]]:
    if not filepath.is_file(): return []
    try:
        with open(filepath, 'r', encoding='utf-8') as f: data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError): return []

def save_data(filepath: Path, data: List[Dict[str, Any]]):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_next_id(data: List[Dict[str, Any]]) -> int:
    if not data: return 1
    return max(item.get('id', 0) for item in data) + 1

async def run_build_script(): # <-- ADDED BACK FULL FUNCTION
    try:
        process = await asyncio.create_subprocess_exec(
            PYTHON_EXECUTABLE, str(BUILD_SCRIPT_PATH),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=BASE_DIR
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            print("Build script executed successfully.")
        else:
            print(f"Build script failed with error code {process.returncode}:\n{stderr.decode()}")
    except Exception as e:
        print(f"An error occurred while running the build script: {e}")

def trigger_build(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_build_script)

def sanitize_filename(name: str) -> str:
    # Basic sanitize, can be improved
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()[:100]

def get_full_image_url(filename: str) -> str:
    # This now refers to the main /images mount point
    return f"/images/obrazy/{filename}"

# --- FastAPI Application ---
app = FastAPI(title="Maří Magdalena Content API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.mount("/assets", StaticFiles(directory="dist/assets"), name="static")
app.mount("/web", StaticFiles(directory="./", html=True), name="web")

@app.post("/build", status_code=202, summary="Manually trigger build script")
async def trigger_manual_build(background_tasks: BackgroundTasks):
    """
    Manually triggers the build.py script execution in the background.
    """
    trigger_build(background_tasks)
    return JSONResponse(content={"message": "Build process triggered."}, status_code=202)


# --- Generic Reorder Endpoint ---
def reorder_resource(filepath: Path, payload: ReorderPayload):
    data = load_data(filepath)
    data_map = {item['id']: item for item in data}
    reordered_data = []
    seen_ids = set()
    for i, item_id in enumerate(payload.ids):
        if item_id in data_map:
            item = data_map[item_id]
            item['order'] = i
            reordered_data.append(item)
            seen_ids.add(item_id)
    # Add any items that were not in the reorder payload to the end
    for item_id, item in data_map.items():
        if item_id not in seen_ids:
            item['order'] = len(reordered_data)
            reordered_data.append(item)
    save_data(filepath, reordered_data)

# --- Reorder Endpoints ---
@app.post("/{resource}/reorder", status_code=202)
async def reorder_items(resource: str, payload: ReorderPayload, background_tasks: BackgroundTasks):
    path_map = {
        "paintings": PAINTINGS_JSON_PATH,
        "projekty": PROJEKTY_JSON_PATH,
        "vystavy": VYSTAVY_JSON_PATH,
    }
    if resource not in path_map:
        raise HTTPException(status_code=404, detail="Resource not found")
    reorder_resource(path_map[resource], payload)
    trigger_build(background_tasks)
    return {"message": f"{resource.capitalize()} reordered successfully."}

# --- Painting Endpoints ---
@app.get("/paintings", response_model=List[PaintingBase])
async def list_paintings():
    paintings = sorted(load_data(PAINTINGS_JSON_PATH), key=lambda p: p.get('order', 0))
    for p in paintings: p['url'] = get_full_image_url(p.get('filename', ''))
    return paintings

@app.get("/paintings/{painting_id}", response_model=PaintingBase)
async def get_painting(painting_id: int):
    paintings = load_data(PAINTINGS_JSON_PATH)
    painting = next((p for p in paintings if p.get('id') == painting_id), None)
    if not painting: raise HTTPException(status_code=404, detail="Painting not found")
    painting['url'] = get_full_image_url(painting.get('filename', ''))
    return painting

@app.post("/paintings", response_model=PaintingBase, status_code=201)
async def create_painting(background_tasks: BackgroundTasks, title: str = Form(...), sold: bool = Form(False), image: UploadFile = File(...)):
    paintings = load_data(PAINTINGS_JSON_PATH)
    new_id = get_next_id(paintings)
    new_filename = f"{new_id}{Path(image.filename).suffix}"
    file_location = PAINTING_IMAGES_DIR / new_filename
    with open(file_location, "wb+") as file_object: shutil.copyfileobj(image.file, file_object)
    new_painting = {"id": new_id, "title": title, "sold": sold, "order": len(paintings), "filename": new_filename}
    paintings.append(new_painting)
    save_data(PAINTINGS_JSON_PATH, paintings)
    trigger_build(background_tasks)
    new_painting['url'] = get_full_image_url(new_filename)
    return new_painting

@app.put("/paintings/{painting_id}", response_model=PaintingBase)
async def update_painting(background_tasks: BackgroundTasks, painting_id: int, update_data: PaintingUpdate):
    paintings = load_data(PAINTINGS_JSON_PATH)
    painting_index = next((i for i, p in enumerate(paintings) if p.get('id') == painting_id), -1)
    if painting_index == -1: raise HTTPException(status_code=404, detail="Painting not found")
    painting = paintings[painting_index]
    painting.update(update_data.model_dump(exclude_unset=True))
    save_data(PAINTINGS_JSON_PATH, paintings)
    trigger_build(background_tasks)
    painting['url'] = get_full_image_url(painting.get('filename', ''))
    return painting

@app.delete("/paintings/{painting_id}", status_code=204)
async def delete_painting(background_tasks: BackgroundTasks, painting_id: int):
    paintings = load_data(PAINTINGS_JSON_PATH)
    painting_to_delete = next((p for p in paintings if p.get('id') == painting_id), None)
    if not painting_to_delete: raise HTTPException(status_code=404, detail="Painting not found")
    try: os.remove(PAINTING_IMAGES_DIR / painting_to_delete['filename'])
    except OSError as e: print(f"Could not delete image file: {e}")
    save_data(PAINTINGS_JSON_PATH, [p for p in paintings if p.get('id') != painting_id])
    trigger_build(background_tasks)
    return Response(status_code=204)

# --- Project & Exhibition Endpoints ---
# (Generic implementation for projekty and vystavy)
RESOURCE_PATHS = {"projekty": PROJEKTY_JSON_PATH, "vystavy": VYSTAVY_JSON_PATH}
RESOURCE_MODELS = {"projekty": (ProjectBase, ProjectUpdate), "vystavy": (ExhibitionBase, ExhibitionUpdate)}

@app.get("/{resource}", response_model=List[Dict])
async def list_resource(resource: str):
    if resource not in RESOURCE_PATHS: raise HTTPException(status_code=404, detail="Resource not found")
    return sorted(load_data(RESOURCE_PATHS[resource]), key=lambda p: p.get('order', 0))

@app.post("/{resource}", response_model=Dict, status_code=201)
async def create_resource(resource: str, data: Dict, background_tasks: BackgroundTasks):
    if resource not in RESOURCE_PATHS: raise HTTPException(status_code=404, detail="Resource not found")
    items = load_data(RESOURCE_PATHS[resource])
    new_item = data
    new_item['id'] = get_next_id(items)
    new_item['order'] = len(items)
    items.append(new_item)
    save_data(RESOURCE_PATHS[resource], items)
    trigger_build(background_tasks)
    return new_item

@app.get("/{resource}/{item_id}", response_model=Dict)
async def get_resource_item(resource: str, item_id: int):
    if resource not in RESOURCE_PATHS: raise HTTPException(status_code=404, detail="Resource not found")
    items = load_data(RESOURCE_PATHS[resource])
    item = next((p for p in items if p.get('id') == item_id), None)
    if not item: raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.put("/{resource}/{item_id}", response_model=Dict)
async def update_resource_item(resource: str, item_id: int, data: Dict, background_tasks: BackgroundTasks):
    if resource not in RESOURCE_PATHS: raise HTTPException(status_code=404, detail="Resource not found")
    items = load_data(RESOURCE_PATHS[resource])
    item_index = next((i for i, p in enumerate(items) if p.get('id') == item_id), -1)
    if item_index == -1: raise HTTPException(status_code=404, detail="Item not found")
    items[item_index].update(data)
    items[item_index]['id'] = item_id # Ensure ID is not changed
    save_data(RESOURCE_PATHS[resource], items)
    trigger_build(background_tasks)
    return items[item_index]

@app.delete("/{resource}/{item_id}", status_code=204)
async def delete_resource_item(resource: str, item_id: int, background_tasks: BackgroundTasks):
    if resource not in RESOURCE_PATHS: raise HTTPException(status_code=404, detail="Resource not found")
    items = load_data(RESOURCE_PATHS[resource])
    if not any(p.get('id') == item_id for p in items): raise HTTPException(status_code=404, detail="Item not found")
    save_data(RESOURCE_PATHS[resource], [p for p in items if p.get('id') != item_id])
    trigger_build(background_tasks)
    return Response(status_code=204)

# --- Upload & Static File Serving ---
@app.post("/upload/{resource_type}", summary="Upload an image")
async def upload_image_for_resource(resource_type: str, image: UploadFile = File(...)):
    upload_dir = IMAGES_DIR / resource_type
    upload_dir.mkdir(parents=True, exist_ok=True)
    sanitized_filename = Path(sanitize_filename(image.filename)).name
    file_location = upload_dir / sanitized_filename
    if file_location.exists():
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        sanitized_filename = f"{Path(sanitized_filename).stem}_{timestamp}{Path(sanitized_filename).suffix}"
        file_location = upload_dir / sanitized_filename
    with open(file_location, "wb+") as file_object: shutil.copyfileobj(image.file, file_object)
    relative_path = os.path.join("images", resource_type, sanitized_filename)
    return {"path": relative_path.replace("\\", "/")}

app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
app.mount("/", StaticFiles(directory="dist", html=True), name="admin")