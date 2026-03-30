import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

load_dotenv()

app = FastAPI(title="NUMP Template Converter", version="1.0.0")

# Ensure data directories exist
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
for sub in ["uploads", "templates", "batch_sessions"]:
    (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)

# Initialize registry.json if not exists
registry_path = DATA_DIR / "registry.json"
if not registry_path.exists():
    import json
    registry_path.write_text(json.dumps({"forms": {}}, ensure_ascii=False, indent=2), encoding="utf-8")

# Routes
from api.routes import upload, batch, templates, preview, export

app.include_router(upload.router, prefix="/api")
app.include_router(batch.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(preview.router, prefix="/api")
app.include_router(export.router, prefix="/api")

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def index():
    return FileResponse("static/index.html")

@app.get("/download/templates")
async def download_templates():
    zip_path = Path("templates_export.zip")
    if zip_path.exists():
        return FileResponse(str(zip_path), filename="templates_export.zip", media_type="application/zip")
    return {"error": "파일 없음"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
