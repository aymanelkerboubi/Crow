"""
Configuration du module OCR Courriers — UCA
"""
from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # --- Application ---
    APP_NAME: str = "Module OCR Courriers — UCA"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # --- Base de données ---
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'courriers.db'}"

    # --- OCR ---
    OCR_ENGINE: str = "auto"  # ou "hybrid" pour mix intelligent   paddle        # "tesseract" ou "easyocr"
    OCR_LANGUAGES: str = "fra+ara"          # Langues Tesseract
    TESSERACT_CMD: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    OCR_TIMEOUT: int = 10                   # Secondes max par document
    OCR_TMP_DIR: str = "C:/temp/ocr_uca"
    TESSDATA_PREFIX: str = "C:/Program Files/Tesseract-OCR/tessdata"

    # --- Pré-traitement ---
    PREPROCESSING_ENABLED: bool = True
    DESKEW_ENABLED: bool = True
    CONTRAST_ENHANCEMENT: bool = True

    # --- NLP ---
    SPACY_MODEL: str = "fr_core_news_md"
    CONFIDENCE_THRESHOLD: float = 0.60      # Seuil minimal de confiance

    # --- Uploads ---
    UPLOAD_DIR: Path = BASE_DIR / "uploads"   #Path = BASE_DIR / "uploads"
    MAX_FILE_SIZE_MB: int = 20
    ALLOWED_EXTENSIONS: list = [".pdf", ".jpg", ".jpeg", ".png"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# Créer le dossier uploads s'il n'existe pas
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
