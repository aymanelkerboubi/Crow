"""
Tests unitaires — Module OCR Courriers
"""
import pytest
from app.services.nlp_extractor import NLPExtractor


# ═══════════════════════════════════════
# Exemple de texte OCR réel (courrier UCA)
# ═══════════════════════════════════════
SAMPLE_TEXT_UCA = """Royaume du Maroc
Université Cadi Ayyad – Marrakech
La Présidence
Présidence Université Cadi Ayyad – Bd. Abdelkarim El Khattabi, B.P. 511- Marrakech
Tél : 05.24.43.48.14/05.24.43.77.41 – Fax : 05.24.43.44.94 - Email : presidence@uca.ma

Marrakech, le 27 JAN 2022
N° 400/UCA/2022/586

Le Président
A
Mesdames et Messieurs les Professeurs,
Les Personnels administratif et technique et
Les Etudiants de l'Université

OBJET : Organisation des Assises régionales Marrakech – Safi 2021-2022

Cher(e)s collègues des corps enseignant, administratif et technique,
Cher(e)s étudiant(e)s,

Dans le cadre des préparatifs des Assises nationales de l'enseignement supérieur,
de la recherche scientifique et de l'innovation (ESRI), l'Université Cadi Ayyad
compte organiser au mois de mars prochain les Assises régionales de l'ESRI.

Veuillez agréer, Mesdames et Messieurs, l'expression de ma haute considération.

Le Président
Moulay Lhassan HBID
"""

SAMPLE_BORDEREAU = """Royaume du Maroc
Ministère de l'Enseignement Supérieur
Direction des Ressources Humaines

BORDEREAU D'ENVOI

N° BE/2024/RH/0042
Rabat, le 03 mars 2024

Expéditeur : Direction des Ressources Humaines
Destinataire : Service du Personnel, Présidence UCA

Objet : Transmission des dossiers de promotion — Session 2024

1. Liste enseignants proposés
2. PV commissions scientifiques

M. Karim ALAOUI
Directeur DRH
"""


class TestNLPExtractor:
    """Tests pour l'extracteur NLP."""

    def setup_method(self):
        # Initialiser sans spaCy pour les tests rapides
        self.extractor = NLPExtractor.__new__(NLPExtractor)
        self.extractor.nlp = None
        self.extractor.spacy_model = None

    def test_extract_numero_uca(self):
        result = self.extractor._extract_numero(SAMPLE_TEXT_UCA)
        assert result is not None
        assert "400" in result
        assert "UCA" in result or "2022" in result

    def test_extract_date_uca(self):
        result = self.extractor._extract_date(SAMPLE_TEXT_UCA)
        assert result is not None
        assert "27" in result
        assert "janvier" in result.lower() or "jan" in result.lower()

    def test_extract_objet_uca(self):
        result = self.extractor._extract_objet(SAMPLE_TEXT_UCA)
        assert result is not None
        assert "Assises" in result
        assert "régionales" in result.lower()

    def test_extract_expediteur_uca(self):
        result = self.extractor._extract_expediteur(SAMPLE_TEXT_UCA)
        assert result is not None
        assert "Président" in result or "HBID" in result

    def test_detect_type_lettre(self):
        result = self.extractor._detect_type(SAMPLE_TEXT_UCA)
        assert result == "lettre"

    def test_detect_type_bordereau(self):
        result = self.extractor._detect_type(SAMPLE_BORDEREAU)
        assert result == "bordereau"

    def test_extract_numero_bordereau(self):
        result = self.extractor._extract_numero(SAMPLE_BORDEREAU)
        assert result is not None
        assert "BE/2024" in result

    def test_extract_date_bordereau(self):
        result = self.extractor._extract_date(SAMPLE_BORDEREAU)
        assert result is not None
        assert "mars" in result.lower()
        assert "2024" in result

    def test_extract_corps(self):
        result = self.extractor._extract_corps(SAMPLE_TEXT_UCA)
        assert result is not None
        assert "Assises" in result or "préparatifs" in result

    def test_full_extraction_uca(self):
        result = self.extractor.extract_fields(SAMPLE_TEXT_UCA)
        assert "fields" in result
        assert "confidence" in result
        fields = result["fields"]
        assert fields["numero"] is not None
        assert fields["date"] is not None
        assert fields["objet"] is not None
        assert fields["type_document"] == "lettre"

    def test_confidence_scores(self):
        result = self.extractor.extract_fields(SAMPLE_TEXT_UCA)
        confidence = result["confidence"]
        for field, score in confidence.items():
            assert 0.0 <= score <= 1.0, f"Score invalide pour {field}: {score}"

    def test_empty_text(self):
        result = self.extractor.extract_fields("")
        fields = result["fields"]
        assert fields["numero"] is None
        assert fields["date"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
