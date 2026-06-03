"""
Modèle de données — Courrier
"""
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, JSON
from sqlalchemy.sql import func
from app.database import Base


class Courrier(Base):
    """Table des courriers traités par OCR."""
    __tablename__ = "courriers"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- Fichier source ---
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(10), nullable=False)       # pdf, jpg, png

    # --- Champs extraits ---
    numero = Column(String(100), nullable=True)
    date_courrier = Column(String(100), nullable=True)
    objet = Column(String(500), nullable=True)
    expediteur = Column(String(300), nullable=True)
    destinataire = Column(String(300), nullable=True)
    type_document = Column(String(50), nullable=True)     # lettre, bordereau, note, circulaire
    etablissement = Column(String(100), nullable=True)    # FSJES-Marrakech, FST-Marrakech, etc.
    corps = Column(Text, nullable=True)

    # --- Texte OCR complet ---
    texte_complet = Column(Text, nullable=True)
    langue_detectee = Column(String(10), default="fr")    # fr, ar, fr+ar

    # --- Scores de confiance (0.0 à 1.0) ---
    confidence = Column(JSON, nullable=True)
    # Structure: {"numero": 0.88, "date": 0.95, "objet": 0.96, ...}

    # --- Statut ---
    status = Column(String(20), default="pending")        # pending, validated, rejected
    validated_by = Column(String(100), nullable=True)

    # --- Métadonnées ---
    processing_time_ms = Column(Integer, nullable=True)
    ocr_engine_used = Column(String(50), nullable=True)   # tesseract, easyocr
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        """Sérialiser en dictionnaire."""
        return {
            "id": self.id,
            "filename": self.filename,
            "file_type": self.file_type,
            "numero": self.numero,
            "date": self.date_courrier,
            "objet": self.objet,
            "expediteur": self.expediteur,
            "destinataire": self.destinataire,
            "type_document": self.type_document,
            "etablissement": self.etablissement,
            "corps": self.corps,
            "texte_complet": self.texte_complet,
            "langue_detectee": self.langue_detectee,
            "confidence": self.confidence or {},
            "status": self.status,
            "processing_time_ms": self.processing_time_ms,
            "ocr_engine_used": self.ocr_engine_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
