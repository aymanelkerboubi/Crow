# Rapport Technique — Module OCR Courriers
## Université Cadi Ayyad — Pôle Digitalisation

### 1. Introduction

Ce rapport décrit la conception, l'implémentation et le déploiement du module de lecture
automatique des courriers scannés développé pour l'Université Cadi Ayyad – Marrakech.

Le module répond au cahier des charges qui identifie les problèmes suivants :
- Saisie manuelle longue et répétitive des informations des courriers
- Risque d'erreurs humaines
- Impossibilité de rechercher dans le contenu des courriers
- Charge de travail importante des agents du bureau d'ordre

### 2. Architecture

Le module est conçu comme un **service IA indépendant** en Python, exposé via une API REST (FastAPI).

**Chaîne de traitement :**
```
Document (PDF/IMG) → Pré-traitement image → OCR → NLP + Regex → JSON API
```

**Composants :**
- `preprocessing.py` : Redressement (deskew), débruitage, amélioration du contraste, binarisation
- `ocr_engine.py` : Extraction texte via Tesseract OCR (fra+ara) avec fallback EasyOCR
- `nlp_extractor.py` : Extraction des champs via spaCy NER + expressions régulières + règles métiers
- `pipeline.py` : Orchestration complète du traitement

### 3. Technologies utilisées

| Technologie | Rôle | Version |
|------------|------|---------|
| Python | Langage principal | 3.10+ |
| FastAPI | Framework API REST | 0.115.0 |
| Tesseract OCR | Moteur OCR principal | v5 |
| EasyOCR | Moteur OCR alternatif (arabe) | 1.7.2 |
| spaCy | NLP / NER | 3.7.6 |
| OpenCV | Pré-traitement image | 4.10.0 |
| SQLAlchemy | ORM base de données | 2.0.35 |
| SQLite/PostgreSQL | Stockage persistant | — |

### 4. Extraction des champs

Les 7 champs requis sont extraits via une combinaison de :

**Expressions régulières** adaptées aux formats administratifs marocains :
- N° courrier : `N° 400/UCA/2022/586`, `Réf: DB/2024/3201`, `BE/2024/RH/0042`
- Date : `le 27 JAN 2022`, `03 mars 2024`, `10/09/2024`
- Objet : ligne après `OBJET :` ou `Objet :`

**Règles métiers** :
- Détection du type : mot-clé "BORDEREAU D'ENVOI" → bordereau, "Note de service" → note
- Extraction du corps : filtrage automatique des en-têtes, signatures et mentions secondaires
- Expéditeur : combinaison du titre (Le Président), nom (Moulay Lhassan HBID) et institution

**spaCy NER** (fallback) :
- Entités DATE, PER, ORG utilisées quand les regex ne matchent pas

### 5. Scores de confiance

Chaque champ extrait est associé à un score de confiance (0-100%) calculé selon :
- Présence et cohérence du pattern regex
- Longueur et structure du champ extrait
- Confiance OCR globale du moteur Tesseract

### 6. API REST

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| POST | `/api/ocr/process` | Traiter un document scanné |
| GET | `/api/courriers` | Lister les courriers |
| GET | `/api/courriers/{id}` | Détail d'un courrier |
| PUT | `/api/courriers/{id}` | Valider/corriger un courrier |
| GET | `/api/courriers/search?q=...` | Recherche plein texte |
| GET | `/api/stats/overview` | Statistiques |

### 7. Interface web

L'interface est développée en HTML/CSS/JS avec l'identité visuelle de l'UCA :
- Palette terre cuite / orange (#C1512D, #E67E22)
- Typographie Playfair Display + Source Sans 3
- Structure sidebar type Laravel avec navigation par onglets

Pages : Tableau de bord, Import & OCR, Courriers traités, Recherche plein texte, API REST, Paramètres

### 8. Tests

Tests unitaires couvrant :
- Extraction du numéro, date, objet, expéditeur, destinataire
- Détection du type de document (lettre vs bordereau)
- Extraction du corps avec filtrage en-têtes/signatures
- Validation des scores de confiance

### 9. Déploiement

Le module est déployable sur serveur Linux via :
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Prérequis système : Python 3.10+, Tesseract OCR v5, paquets de langue fra+ara.

### 10. Conclusion

Le module répond aux critères de réussite définis dans le cahier des charges :
- ✅ ≥ 80% des champs correctement détectés (testé sur courriers UCA réels)
- ✅ Pré-remplissage fonctionnel avec validation humaine
- ✅ Recherche plein texte opérationnelle
- ✅ Déployable sur serveur Linux
