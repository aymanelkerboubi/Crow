"""
Routes API — CRUD Courriers + Recherche plein texte
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.database import get_db
from app.models.courrier import Courrier

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/courriers", tags=["Courriers"])


@router.get("")
def list_courriers(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status: str = Query(default=None),
    db: Session = Depends(get_db),
):
    """Lister tous les courriers traités avec pagination."""
    query = db.query(Courrier)
    if status:
        query = query.filter(Courrier.status == status)

    total = query.count()
    courriers = (
        query.order_by(Courrier.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "courriers": [c.to_dict() for c in courriers],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


@router.get("/search")
def search_courriers(
    q: str = Query(..., min_length=1, description="Mot-clé de recherche"),
    field: str = Query(default="all", description="Champ: all, objet, contenu, expediteur, destinataire"),
    db: Session = Depends(get_db),
):
    """
    Recherche plein texte dans les courriers indexés.

    - **q**: Mot-clé à rechercher
    - **field**: Champ cible (all, objet, contenu, expediteur, destinataire)
    """
    search_term = f"%{q}%"

    if field == "objet":
        query = db.query(Courrier).filter(Courrier.objet.ilike(search_term))
    elif field == "contenu":
        query = db.query(Courrier).filter(
            or_(Courrier.texte_complet.ilike(search_term), Courrier.corps.ilike(search_term))
        )
    elif field == "expediteur":
        query = db.query(Courrier).filter(Courrier.expediteur.ilike(search_term))
    elif field == "destinataire":
        query = db.query(Courrier).filter(Courrier.destinataire.ilike(search_term))
    else:  # all
        query = db.query(Courrier).filter(
            or_(
                Courrier.objet.ilike(search_term),
                Courrier.numero.ilike(search_term),
                Courrier.expediteur.ilike(search_term),
                Courrier.destinataire.ilike(search_term),
                Courrier.texte_complet.ilike(search_term),
                Courrier.corps.ilike(search_term),
            )
        )

    results = query.order_by(Courrier.created_at.desc()).limit(50).all()

    return {
        "query": q,
        "field": field,
        "results": [c.to_dict() for c in results],
        "total": len(results),
    }


@router.get("/{courrier_id}")
def get_courrier(courrier_id: int, db: Session = Depends(get_db)):
    """Récupérer un courrier par son ID."""
    courrier = db.query(Courrier).filter(Courrier.id == courrier_id).first()
    if not courrier:
        raise HTTPException(status_code=404, detail="Courrier non trouvé")
    return courrier.to_dict()


@router.put("/{courrier_id}")
def update_courrier(courrier_id: int, data: dict, db: Session = Depends(get_db)):
    """
    Mettre à jour un courrier (validation par l'agent).
    L'agent peut corriger les champs extraits et valider.
    """
    courrier = db.query(Courrier).filter(Courrier.id == courrier_id).first()
    if not courrier:
        raise HTTPException(status_code=404, detail="Courrier non trouvé")

    # Champs modifiables
    updatable = ["numero", "date_courrier", "objet", "expediteur",
                 "destinataire", "type_document", "corps", "status"]
    for field in updatable:
        if field in data:
            setattr(courrier, field, data[field])

    if "validated_by" in data:
        courrier.validated_by = data["validated_by"]

    db.commit()
    db.refresh(courrier)

    logger.info(f"Courrier #{courrier_id} mis à jour (status={courrier.status})")
    return courrier.to_dict()


@router.delete("/{courrier_id}")
def delete_courrier(courrier_id: int, db: Session = Depends(get_db)):
    """Supprimer un courrier."""
    courrier = db.query(Courrier).filter(Courrier.id == courrier_id).first()
    if not courrier:
        raise HTTPException(status_code=404, detail="Courrier non trouvé")
    db.delete(courrier)
    db.commit()
    return {"message": f"Courrier #{courrier_id} supprimé"}


@router.get("/stats/overview")
def get_stats(db: Session = Depends(get_db)):
    """Statistiques globales du module OCR."""
    total = db.query(Courrier).count()
    validated = db.query(Courrier).filter(Courrier.status == "validated").count()
    pending = db.query(Courrier).filter(Courrier.status == "pending").count()

    # Confiance moyenne
    courriers = db.query(Courrier).all()
    if courriers:
        all_confs = []
        for c in courriers:
            if c.confidence:
                vals = [v for v in c.confidence.values() if isinstance(v, (int, float))]
                if vals:
                    all_confs.append(sum(vals) / len(vals))
        avg_confidence = sum(all_confs) / len(all_confs) if all_confs else 0
    else:
        avg_confidence = 0

    # Temps moyen de traitement
    avg_time = db.query(func.avg(Courrier.processing_time_ms)).scalar() or 0

    return {
        "total_documents": total,
        "validated": validated,
        "pending": pending,
        "rejected": total - validated - pending,
        "avg_confidence": round(avg_confidence, 1),
        "avg_processing_time_ms": round(avg_time),
    }
