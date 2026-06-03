"""
Routes API — Traitement OCR
    POST /api/ocr/process       → Upload PDF/image + OCR + NLP + DB
    POST /api/ocr/process-text  → Texte déjà extrait + NLP + DB (fallback pdf.js côté frontend)
"""
import os
import uuid
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.courrier import Courrier
from app.services.pipeline import OCRPipeline
from app.services.nlp_extractor import NLPExtractor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ocr", tags=["OCR"])

# ─── Initialisation des services (singleton) ───
pipeline = None
nlp_extractor = None


def get_pipeline():
    global pipeline
    if pipeline is None:
        pipeline = OCRPipeline()
    return pipeline


def get_nlp():
    """Instance NLPExtractor isolée (utilisée par /process-text, n'a pas
    besoin de Tesseract ni de Poppler)."""
    global nlp_extractor
    if nlp_extractor is None:
        nlp_extractor = NLPExtractor(spacy_model=settings.SPACY_MODEL)
    return nlp_extractor


# ═══════════════════════════════════════════════════════════════════════
# ROUTE 1 : upload + OCR complet + NLP
# ═══════════════════════════════════════════════════════════════════════
@router.post("/process")
async def process_document(
    file: UploadFile = File(...),
    language: str = Form(default="fra+ara"),
    db: Session = Depends(get_db),
):
    """
    Traiter un courrier scanné : PDF ou image → texte (via Tesseract) → champs.

    - **file**: Fichier PDF, JPG ou PNG du courrier scanné
    - **language**: Langues OCR (fra+ara par défaut)

    Retourne les champs extraits au format JSON.
    """
    # Validation du fichier
    ext = Path(file.filename).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Format non supporté: {ext}. Formats acceptés: {settings.ALLOWED_EXTENSIONS}"
        )

    file_type = "pdf" if ext == ".pdf" else "image"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = settings.UPLOAD_DIR / unique_name

    try:
        contents = await file.read()
        if len(contents) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail=f"Fichier trop volumineux (max {settings.MAX_FILE_SIZE_MB}MB)"
            )

        with open(file_path, "wb") as f:
            f.write(contents)
        logger.info(f"Fichier sauvegardé: {file_path}")

        # Lancer le pipeline OCR complet
        pipe = get_pipeline()
        result = pipe.process_document(str(file_path), file_type)

        # Sauvegarder en base de données
        courrier = Courrier(
            filename=file.filename,
            file_path=str(file_path),
            file_type=file_type,
            numero=result["numero"],
            date_courrier=result["date"],
            objet=result["objet"],
            expediteur=result["expediteur"],
            destinataire=result["destinataire"],
            type_document=result["type_document"],
            etablissement=result.get("etablissement"),
            corps=result["corps"],
            texte_complet=result["texte_complet"],
            langue_detectee=result["langue_detectee"],
            confidence=result["confidence"],
            processing_time_ms=result["metadata"]["processing_time_ms"],
            ocr_engine_used=result["metadata"]["ocr_engine"],
            status="pending",
        )
        db.add(courrier)
        db.commit()
        db.refresh(courrier)
        logger.info(f"Courrier #{courrier.id} créé en base")

        return {
            "id": courrier.id,
            "numero": result["numero"],
            "date": result["date"],
            "objet": result["objet"],
            "expediteur": result["expediteur"],
            "destinataire": result["destinataire"],
            "type_document": result["type_document"],
            "etablissement": result.get("etablissement"),
            "corps": result["corps"],
            "texte_complet": result["texte_complet"],
            "langue_detectee": result["langue_detectee"],
            "confidence": result["confidence"],
            "metadata": result["metadata"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur traitement: {e}", exc_info=True)
        if file_path.exists():
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Erreur de traitement OCR: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════
# ROUTE 2 : NLP uniquement (pour le fallback pdf.js du frontend)
# ═══════════════════════════════════════════════════════════════════════
@router.post("/process-text")
async def process_text(
    payload: dict,
    db: Session = Depends(get_db),
):
    """
    Appliquer uniquement l'extraction NLP sur un texte déjà extrait côté
    client (pdf.js par exemple). Utile quand Tesseract/Poppler n'est pas
    installé sur le serveur mais que le PDF contient du texte lisible.

    Body JSON attendu :
        {
          "text":     "...",               # obligatoire
          "filename": "courrier.pdf"        # optionnel
        }
    """
    text = payload.get("text", "")
    filename = payload.get("filename", "unknown.pdf")

    if not text or len(text.strip()) < 10:
        raise HTTPException(status_code=400, detail="Texte vide ou trop court")

    try:
        # Extraction NLP seule
        nlp = get_nlp()
        nlp_result = nlp.extract_fields(text)
        fields = nlp_result["fields"]
        confidence = nlp_result["confidence"]

        # Convertir en pourcentages
        confidence_pct = {k: int(v * 100) for k, v in confidence.items()}

        # Détection de langue simple
        import re
        arabic_chars = len(re.findall(r'[\u0600-\u06FF\u0750-\u077F]', text))
        latin_chars = len(re.findall(r'[a-zA-ZÀ-ÿ]', text))
        if arabic_chars > latin_chars:
            langue = "ar"
        elif arabic_chars > 0 and arabic_chars > latin_chars * 0.2:
            langue = "fr+ar"
        else:
            langue = "fr"

        # Sauvegarder en DB
        courrier = Courrier(
            filename=filename,
            file_path="(pdf.js - client extraction)",
            file_type="pdf",
            numero=fields["numero"],
            date_courrier=fields["date"],
            objet=fields["objet"],
            expediteur=fields["expediteur"],
            destinataire=fields["destinataire"],
            type_document=fields["type_document"],
            etablissement=fields.get("etablissement"),
            corps=fields["corps"],
            texte_complet=text,
            langue_detectee=langue,
            confidence=confidence_pct,
            processing_time_ms=0,
            ocr_engine_used="pdf.js (client)",
            status="pending",
        )
        db.add(courrier)
        db.commit()
        db.refresh(courrier)
        logger.info(f"Courrier #{courrier.id} créé (via /process-text)")

        return {
            "id": courrier.id,
            "numero": fields["numero"],
            "date": fields["date"],
            "objet": fields["objet"],
            "expediteur": fields["expediteur"],
            "destinataire": fields["destinataire"],
            "type_document": fields["type_document"],
            "etablissement": fields.get("etablissement"),
            "corps": fields["corps"],
            "texte_complet": text,
            "langue_detectee": langue,
            "confidence": confidence_pct,
            "metadata": {
                "ocr_engine": "pdf.js (client)",
                "processing_time_ms": 0,
                "num_pages": 1,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur /process-text: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur NLP: {str(e)}")
