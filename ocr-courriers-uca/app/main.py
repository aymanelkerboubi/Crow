"""
Module OCR Courriers — Point d'entrée FastAPI
Université Cadi Ayyad — Pôle Digitalisation
"""
import logging
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from app.config import settings
from app.database import init_db
from app.routes import ocr, courriers

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Application FastAPI ───
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Module de lecture automatique des courriers scannés et extraction du texte. "
        "Développé pour le Pôle Digitalisation — Université Cadi Ayyad, Marrakech."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS ───
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Fichiers statiques + Templates ───
BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ─── Routes API ───
app.include_router(ocr.router)
app.include_router(courriers.router)


# ─── Page d'accueil (Interface web) ───
@app.get("/", include_in_schema=False)
async def index(request: Request):
    """Servir l'interface web principale."""
    return templates.TemplateResponse(request, "index.html")


# ─── Événements ───
@app.on_event("startup")
async def startup():
    logger.info(f"Démarrage {settings.APP_NAME} v{settings.APP_VERSION}")
    init_db()
    logger.info("Base de données initialisée")
    logger.info(f"OCR Engine: {settings.OCR_ENGINE}")
    logger.info(f"Langues OCR: {settings.OCR_LANGUAGES}")
    logger.info(f"Upload dir: {settings.UPLOAD_DIR}")


@app.on_event("shutdown")
async def shutdown():
    logger.info("Arrêt du module OCR")


# ─── Health check ───
@app.get("/api/health", tags=["System"])
async def health():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "ocr_engine": settings.OCR_ENGINE,
        "languages": settings.OCR_LANGUAGES,
    }
