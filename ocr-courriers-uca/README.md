# Module OCR Courriers — Université Cadi Ayyad

## Description
Module de lecture automatique des courriers scannés et extraction du texte, développé pour le Pôle Digitalisation de l'Université Cadi Ayyad – Marrakech.

Ce module permet de :
1. **Importer** des courriers scannés (PDF, JPG, PNG)
2. **Extraire le texte** via OCR (Tesseract / EasyOCR) — support français + arabe
3. **Identifier automatiquement** les champs : numéro, date, objet, expéditeur, destinataire, type, corps
4. **Pré-remplir** le formulaire de la plateforme existante (validation humaine conservée)
5. **Rechercher** en plein texte dans le contenu des courriers indexés

## Architecture

```
Courrier scanné (PDF/IMG)
    → Pré-traitement image (redressement, contraste)
    → OCR (Tesseract fra+ara / EasyOCR)
    → Analyse NLP (spaCy + regex + règles métiers)
    → Extraction des champs structurés
    → Réponse JSON via API REST
```

## Stack technologique

| Composant        | Technologie                          |
|------------------|--------------------------------------|
| OCR              | Tesseract OCR v5 (fra+ara), EasyOCR  |
| NLP              | spaCy (fr_core_news_md), regex       |
| API              | FastAPI (Python 3.10+)               |
| Base de données  | SQLite (dev) / PostgreSQL (prod)     |
| Frontend         | HTML/CSS/JS (style Laravel/Blade)    |
| Pré-traitement   | OpenCV, Pillow, deskew               |

## Installation

### Prérequis
- Python 3.10+
- Tesseract OCR v5 installé sur le système
- Git

### 1. Cloner le dépôt
```bash
git clone https://github.com/uca-pole-digitalisation/ocr-courriers.git
cd ocr-courriers
```

### 2. Créer l'environnement virtuel
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows
```

### 3. Installer les dépendances
```bash
pip install -r requirements.txt
```

### 4. Installer Tesseract OCR
```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr tesseract-ocr-fra tesseract-ocr-ara

# macOS
brew install tesseract tesseract-lang
```

### 5. Télécharger le modèle spaCy
```bash
python -m spacy download fr_core_news_md
```

### 6. Lancer le serveur
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 7. Accéder à l'application
- **Interface web** : http://localhost:8000
- **API docs (Swagger)** : http://localhost:8000/docs
- **API docs (ReDoc)** : http://localhost:8000/redoc

## Endpoints API

| Méthode | Endpoint                    | Description                              |
|---------|-----------------------------|------------------------------------------|
| POST    | `/api/ocr/process`          | Traiter un document et extraire les champs |
| GET     | `/api/courriers`            | Lister tous les courriers traités        |
| GET     | `/api/courriers/{id}`       | Récupérer un courrier par ID             |
| PUT     | `/api/courriers/{id}`       | Mettre à jour (validation agent)         |
| DELETE  | `/api/courriers/{id}`       | Supprimer un courrier                    |
| GET     | `/api/courriers/search`     | Recherche plein texte                    |
| GET     | `/api/stats`                | Statistiques du module                   |

## Structure du projet

```
ocr-courriers-uca/
├── app/
│   ├── __init__.py
│   ├── main.py                 # Point d'entrée FastAPI
│   ├── config.py               # Configuration
│   ├── database.py             # Connexion SQLite/PostgreSQL
│   ├── models/
│   │   ├── __init__.py
│   │   └── courrier.py         # Modèle SQLAlchemy
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── ocr.py              # Endpoints OCR
│   │   └── courriers.py        # Endpoints CRUD + recherche
│   └── services/
│       ├── __init__.py
│       ├── preprocessing.py    # Pré-traitement image (OpenCV)
│       ├── ocr_engine.py       # Moteur OCR (Tesseract/EasyOCR)
│       ├── nlp_extractor.py    # Extraction NLP (spaCy + regex)
│       └── pipeline.py         # Pipeline complet
├── static/                     # CSS, JS, images
├── templates/                  # Templates HTML (Jinja2)
│   └── index.html              # Interface principale
├── tests/
│   └── test_pipeline.py        # Tests unitaires
├── uploads/                    # Fichiers uploadés (créé auto)
├── docs/
│   └── rapport_technique.md    # Rapport technique
├── requirements.txt
├── .gitignore
└── README.md
```

## Critères de réussite
- ≥ 80% des champs correctement détectés
- Pré-remplissage fonctionnel
- Recherche plein texte opérationnelle
- Déployable sur serveur Linux

## Licence
Projet interne — Université Cadi Ayyad, Pôle Digitalisation
