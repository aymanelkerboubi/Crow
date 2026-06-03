"""
═══════════════════════════════════════════════════════════════════════════════
  pipeline_v11.py — Pipeline OCR UCA bilingue FR/AR
  Module unique intégrant : preprocessing, OCR hybride, post-correction,
  extraction NLP, scoring de confiance.

  Auteur     : Ayman EL KERBOUBI — DUT IDIA — UCA Marrakech 2025/2026
  Version    : v11 (single-file, production-ready)

  USAGE :
    from app.services.pipeline_v11 import OCRPipeline

    pipeline = OCRPipeline()
    result = pipeline.process("/path/to/courrier.pdf")
    print(result["numero"], result["date"], result["objet"])

  DÉPENDANCES :
    pip install opencv-python-headless numpy Pillow pytesseract \
                easyocr PyMuPDF python-bidi arabic-reshaper

  PERFORMANCE CIBLE : <10s/document (PDF mono-page)
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

import pytesseract
import os
import shutil
import platform
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# ─── Configuration automatique Tesseract PATH ──────────────────────────────
def _configure_tesseract():
    """Détecte et configure Tesseract automatiquement (Windows + Linux/Mac)."""
    # 1. Déjà dans le PATH système ?
    if shutil.which("tesseract"):
        return  # Tout va bien

    # 2. Chercher dans les emplacements Windows courants
    if platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for path in candidates:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                tessdata = os.path.join(os.path.dirname(path), "tessdata")
                if os.path.isdir(tessdata):
                    os.environ["TESSDATA_PREFIX"] = tessdata
                logger.info(f"Tesseract trouvé et configuré : {path}")
                return
        logger.warning(
            "Tesseract introuvable. Installez-le depuis : "
            "https://github.com/UB-Mannheim/tesseract/wiki"
        )

_configure_tesseract()


# ═══════════════════════════════════════════════════════════════════════════
# 1. RÉFÉRENTIELS — institutions UCA, titres, mois, types de documents
# ═══════════════════════════════════════════════════════════════════════════

# Institutions UCA — patterns FR + AR avec priorité (10 = très fiable, 5 = fallback)
INSTITUTIONS = [
    # ─── FRANÇAIS ───
    (r"[Cc]entre\s+R[eé]gional\s+d[''']?[Ii]nvestissement.{0,30}?Marrakech|"
     r"CRI[\s\-\.]*RMS|CRI[\s\-]+Marrakech",
     "CRI Marrakech-Safi", 10),
    (r"Facult[eé]\s+des\s+Sciences\s+Semlalia|FSSM|FSS\s*Semlalia|Sciences\s+Semlalia",
     "FSS Semlalia", 10),
    (r"Facult[eé]\s+des\s+Sciences\s+Juridiques.{0,40}?[Mm]arrakech|FSJES|"
     r"Sciences\s+Juridiques.{0,40}?[eE]conomiques",
     "FSJES Marrakech", 10),
    (r"Facult[eé]\s+des\s+Sciences\s+et\s+Techniques|FSTG?\b|"
     r"Sciences\s+et\s+Techniques.{0,20}?Marrakech",
     "FST Marrakech", 10),
    (r"Facult[eé]\s+Polydisciplinaire.{0,20}?Safi|FP\s*Safi|FPS\b",
     "FP Safi", 10),
    (r"Facult[eé]\s+de\s+M[eé]decine\s+et\s+de\s+Pharmacie|FMPM\b|Médecine\s+et\s+Pharmacie",
     "FMP Marrakech", 10),
    (r"Facult[eé]\s+des\s+Lettres\s+et\s+des?\s+Sciences\s+Humaines|FLSH\b",
     "FLSH Marrakech", 10),
    (r"[EÉ]cole\s+Nationale\s+des\s+Sciences\s+Appliqu[eé]es|ENSA\b",
     "ENSA Marrakech", 10),
    (r"[EÉ]cole\s+Sup[eé]rieure\s+de\s+Technologie.{0,20}?Essaouira|"
     r"EST.{0,5}?Essaouira|ESTE\b",
     "EST Essaouira", 10),
    (r"[EÉ]cole\s+Sup[eé]rieure\s+de\s+Technologie.{0,20}?Safi|EST.{0,5}?Safi",
     "EST Safi", 10),
    (r"Pr[eé]sidence.{0,30}?(?:Cadi\s+Ay?yad|Université)|La\s+Pr[eé]sidence|"
     r"Royaume\s+du\s+Maroc.{0,30}?Pr[eé]sidence",
     "Présidence UCA", 8),
    (r"Universit[eé]\s+Cadi\s+Ay?yad|UCAM",
     "Université Cadi Ayyad", 5),
    # ─── ARABE ───
    (r"رئاسة\s+جامعة\s+القاض[يى]\s+عياض|^\s*الرئاسة\s*$|الرئاسة\b",
     "Présidence UCA", 10),
    (r"كلية\s+العلوم\s+القانونية\s+والاقتصادية\s+والاجتماعية", "FSJES Marrakech", 10),
    (r"كلية\s+العلوم\s+القانونية", "FSJES Marrakech", 9),
    (r"كلية\s+العلوم\s+والتقنيات", "FST Marrakech", 10),
    (r"كلية\s+العلوم\s+السملالية|كلية\s+العلوم\s+سملالية", "FSS Semlalia", 10),
    (r"كلية\s+الطب\s+والصيدلة", "FMP Marrakech", 10),
    (r"كلية\s+الآداب\s+والعلوم\s+الإنسانية", "FLSH Marrakech", 10),
    (r"الكلية\s+المتعددة\s+التخصصات\s+بآسفي|الكلية\s+المتعددة\s+التخصصات", "FP Safi", 10),
    (r"المدرسة\s+الوطنية\s+للعلوم\s+التطبيقية", "ENSA Marrakech", 10),
    (r"المدرسة\s+العليا\s+للتكنولوجيا.{0,15}?الصويرة", "EST Essaouira", 10),
    (r"المدرسة\s+العليا\s+للتكنولوجيا.{0,15}?[آا]سفي", "EST Safi", 10),
    (r"المركز\s+الجهوي\s+ل[لإا]*ستثمار", "CRI Marrakech-Safi", 10),
    (r"جامعة\s+القاض[يى]\s+عياض", "Université Cadi Ayyad", 5),
]

# Titres hiérarchiques — patterns FR/AR mappés vers libellés FR uniformes
TITRES_EMETTEUR = [
    # ─── FR (priorité aux formes spécifiques) ───
    (r"Le\s+Doyen\s+par\s+[Ii]nt[eé]rim", "Le Doyen par Intérim"),
    (r"Pour\s+le\s+Pr[eé]sident\s*[\n\r]+\s*Le\s+Vice[\s\-]?Pr[eé]sident",
     "Pour le Président, Le Vice-Président"),
    (r"Le\s+Vice[\s\-]?Pr[eé]sident", "Le Vice-Président"),
    (r"Le\s+Pr[eé]sident\b", "Le Président"),
    (r"La\s+Pr[eé]sidente\b", "La Présidente"),
    (r"Le\s+Directeur\s+G[eé]n[eé]ral", "Le Directeur Général"),
    (r"Le\s+Directeur\b", "Le Directeur"),
    (r"La\s+Directrice\b", "La Directrice"),
    (r"Le\s+Doyen\b", "Le Doyen"),
    (r"La\s+Doyenne\b", "La Doyenne"),
    (r"Le\s+Secr[eé]taire\s+G[eé]n[eé]ral", "Le Secrétaire Général"),
    # ─── AR mappés vers FR ───
    (r"العميد\s+بالنيابة", "Le Doyen par Intérim"),
    (r"رئيس\s+الجامعة", "Le Président"),
    (r"نائب\s+رئيس\s+الجامعة", "Le Vice-Président"),
    (r"العميد\b", "Le Doyen"),
    (r"العميدة\b", "La Doyenne"),
    (r"المدير\s+العام", "Le Directeur Général"),
    (r"المدير\b", "Le Directeur"),
    (r"المديرة\b", "La Directrice"),
    (r"الأمين\s+العام", "Le Secrétaire Général"),
]

# Mois arabes (calendrier marocain + variantes Levant)
MOIS_AR = {
    "يناير": "janvier", "فبراير": "février", "مارس": "mars",
    "أبريل": "avril", "ابريل": "avril", "إبريل": "avril",
    "ماي": "mai", "مايو": "mai",
    "يونيو": "juin", "يونيه": "juin",
    "يوليوز": "juillet", "يوليو": "juillet", "يوليه": "juillet",
    "غشت": "août", "أغسطس": "août", "اغسطس": "août",
    "شتنبر": "septembre", "سبتمبر": "septembre",
    "أكتوبر": "octobre", "اكتوبر": "octobre",
    "نونبر": "novembre", "نوفمبر": "novembre",
    "دجنبر": "décembre", "ديسمبر": "décembre",
}

# Mois français (textuel + abréviations cachets)
MOIS_FR_ABBR = {
    "JAN": "janvier", "FEV": "février", "FÉV": "février", "MAR": "mars",
    "AVR": "avril", "MAI": "mai", "JUI": "juin", "JUIN": "juin",
    "JUL": "juillet", "JUIL": "juillet", "AOU": "août", "AOÛ": "août",
    "SEP": "septembre", "SEPT": "septembre",
    "OCT": "octobre", "NOV": "novembre", "DEC": "décembre", "DÉC": "décembre",
}

# Types de documents — bilingue FR/AR
TYPES_DOCUMENT = {
    "bordereau": [
        r"[Bb]ordereau\s+d[''']?envoi", r"BORDEREAU\s+D[''']?ENVOI",
        r"BORDERAU|BORDEREAtJ", r"ورقة\s+الإرسال",
        r"بيان\s+الإرسال", r"كشف\s+الإرسال", r"إرسالية",
    ],
    "note": [r"[Nn]ote\s+(?:de\s+service|interne|d[''']?information)",
             r"NOTE\s+DE\s+SERVICE", r"مذكرة\s+(?:إدارية|داخلية|خدمة)?"],
    "circulaire": [r"[Cc]irculaire\b", r"CIRCULAIRE", r"منشور\b", r"دورية\b"],
    "invitation": [r"\b[Ii]nvitation\b", r"\b[Cc]onvocation\b",
                   r"دعوة\s+لحضور", r"استدعاء",
                   r"يشرفنا\s+أن\s+ندعوكم", r"نتشرف\s+بدعوتكم"],
    "pv": [r"[Pp]roc[eè]s[\s\-]verbal", r"\bPV\b", r"محضر\s+اجتماع|\bمحضر\b"],
    "convention": [r"\b[Cc]onvention\b", r"\b[Cc]ontrat\b", r"اتفاقية", r"\bعقد\b"],
    "attestation": [r"[Aa]ttestation\b", r"شهادة\b"],
    "demande": [r"\b[Dd]emande\s+(?:de\b|d['']|d')", r"طلب\b", r"التماس\b"],
    "rapport": [r"\b[Rr]apport\b", r"تقرير\b"],
    "decision": [r"\b[Dd]écision\b", r"قرار\b"],
}


# ═══════════════════════════════════════════════════════════════════════════
# 2. PRÉ-TRAITEMENT D'IMAGES — arabe-aware multi-variantes
# ═══════════════════════════════════════════════════════════════════════════

class ArabicAwarePreprocessor:
    """
    Pré-traitement adapté aux scans bilingues FR/AR de l'administration marocaine.

    Préserve les diacritiques arabes (ـَـ ـِـ ـُـ), les ligatures, l'épaisseur
    du trait. Génère 3 variantes pour donner à l'OCR le meilleur input ;
    la variante la plus confiante l'emporte.
    """

    def preprocess(self, image_path: str) -> list[np.ndarray]:
        """Retourne 3 variantes pré-traitées (numpy arrays binaires)."""
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Image illisible : {image_path}")

        # 1. Suppression bordures noires
        img = self._remove_black_borders(img)

        # 2. Upscaling x2 si scan basse résolution (diacritiques < 2px sinon)
        h, w = img.shape[:2]
        if min(h, w) < 1500:
            img = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

        # 3. Niveaux de gris
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 4. Correction d'orientation (CRITIQUE pour l'arabe RTL)
        gray = self._fix_orientation(gray)

        # 5. Deskew sur petits angles (≤ 15°)
        gray = self._deskew(gray)

        # 6. Correction gamma adaptative
        gray = self._gamma_correction(gray)

        # 7. CLAHE (préserve les diacritiques)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

        # 8. Génération de 3 variantes
        return [
            self._adaptive_threshold(gray),  # Texte clair, fond bruité
            self._otsu_threshold(gray),       # Cas standard
            self._unsharp_mask(gray),         # Texte fin / diacritiques
        ]

    def _remove_black_borders(self, img: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
        coords = cv2.findNonZero(thresh)
        if coords is None:
            return img
        x, y, w, h = cv2.boundingRect(coords)
        return img[y:y + h, x:x + w]

    def _fix_orientation(self, gray: np.ndarray) -> np.ndarray:
        """Détection orientation 0/90/180/270° via Tesseract OSD."""
        try:
            import pytesseract
            osd = pytesseract.image_to_osd(gray, output_type=pytesseract.Output.DICT)
            angle = osd.get("rotate", 0)
            if angle == 90:
                return cv2.rotate(gray, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif angle == 180:
                return cv2.rotate(gray, cv2.ROTATE_180)
            elif angle == 270:
                return cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE)
        except Exception as e:
            logger.debug(f"OSD échec (continue sans rotation) : {e}")
        return gray

    def _deskew(self, gray: np.ndarray) -> np.ndarray:
        """Redressement angles légers (≤ 15°) via Hough."""
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180, 100,
            minLineLength=100, maxLineGap=10,
        )
        if lines is None:
            return gray
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if -15 < angle < 15:
                angles.append(angle)
        if not angles:
            return gray
        median_angle = np.median(angles)
        if abs(median_angle) > 0.5:
            h, w = gray.shape
            M = cv2.getRotationMatrix2D((w // 2, h // 2), median_angle, 1.0)
            gray = cv2.warpAffine(
                gray, M, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
        return gray

    def _gamma_correction(self, gray: np.ndarray) -> np.ndarray:
        mean = float(np.mean(gray))
        if mean < 100:
            gamma = 0.7
        elif mean > 200:
            gamma = 1.3
        else:
            return gray
        inv_gamma = 1.0 / gamma
        table = np.array(
            [((i / 255.0) ** inv_gamma) * 255 for i in range(256)]
        ).astype("uint8")
        return cv2.LUT(gray, table)

    def _adaptive_threshold(self, gray: np.ndarray) -> np.ndarray:
        """Seuillage adaptatif (préserve les ligatures arabes)."""
        return cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=31, C=10,
        )

    def _otsu_threshold(self, gray: np.ndarray) -> np.ndarray:
        """Seuillage Otsu avec léger blur préalable."""
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        _, binary = cv2.threshold(
            blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )
        return binary

    def _unsharp_mask(self, gray: np.ndarray) -> np.ndarray:
        """Renforce les diacritiques arabes flous (sans binarisation)."""
        gaussian = cv2.GaussianBlur(gray, (0, 0), sigmaX=2)
        return cv2.addWeighted(gray, 1.5, gaussian, -0.5, 0)


# ═══════════════════════════════════════════════════════════════════════════
# 3. MOTEUR OCR HYBRIDE — Tesseract + EasyOCR avec routage automatique
# ═══════════════════════════════════════════════════════════════════════════

class OCRMode(Enum):
    AUTO = "auto"
    TESSERACT = "tesseract"
    EASYOCR = "easyocr"
    HYBRID = "hybrid"


class HybridOCREngine:
    """
    Moteur OCR hybride avec routage intelligent FR/AR.

    Stratégie :
      1. Quick-scan Tesseract sur miniature (200ms) → détection langue
      2. Routing :
         - FR pur     → Tesseract tessdata_best
         - AR pur     → EasyOCR
         - Bilingue   → Lance les deux et garde le meilleur par champ
      3. Cache SHA-256 (50 entrées max FIFO)
    """

    def __init__(self):
        self._easyocr = None  # Lazy-loaded
        self._cache: dict[str, dict] = {}
        self._cache_max = 50

    def extract(self, image_paths: list[str],
                mode: OCRMode = OCRMode.AUTO) -> dict:
        """
        Args:
            image_paths : liste d'images (variantes pré-traitées d'une page,
                          ou pages multiples).
            mode        : AUTO / TESSERACT / EASYOCR / HYBRID

        Returns:
            {text, language, engine, confidence}
        """
        if not image_paths:
            return {"text": "", "language": "unknown", "engine": "none", "confidence": 0.0}

        # Cache check
        cache_key = self._compute_cache_key(image_paths)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Détection automatique du mode
        if mode == OCRMode.AUTO:
            mode = self._detect_best_mode(image_paths[0])
            logger.info(f"OCR mode auto-détecté : {mode.value}")

        # Exécution
        if mode == OCRMode.TESSERACT:
            result = self._run_tesseract(image_paths)
        elif mode == OCRMode.EASYOCR:
            result = self._run_easyocr(image_paths)
        elif mode == OCRMode.HYBRID:
            result = self._run_hybrid(image_paths)
        else:
            result = self._run_tesseract(image_paths)

        # Cache (FIFO)
        if len(self._cache) >= self._cache_max:
            self._cache.pop(next(iter(self._cache)))
        self._cache[cache_key] = result
        return result

    def _detect_best_mode(self, image_path: str) -> OCRMode:
        """Détection langue rapide via Tesseract sur miniature (200ms)."""
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            return OCRMode.TESSERACT

        try:
            img = Image.open(image_path)
            thumbnail = img.copy()
            thumbnail.thumbnail((800, 800))
            text = pytesseract.image_to_string(
                thumbnail, lang="fra+ara", config="--psm 6",
            )
        except Exception as e:
            logger.debug(f"Quick-scan échec : {e}")
            return OCRMode.TESSERACT

        ar = len(re.findall(r"[\u0600-\u06FF]", text))
        fr = len(re.findall(r"[A-Za-zÀ-ÿ]", text))
        total = ar + fr
        if total < 20:
            return OCRMode.TESSERACT
        ratio = ar / total
        if ratio > 0.6:
            return OCRMode.EASYOCR
        elif ratio < 0.15:
            return OCRMode.TESSERACT
        return OCRMode.HYBRID

    def _run_tesseract(self, image_paths: list[str]) -> dict:
        """Tesseract OEM 3 PSM 6 lang=fra+ara."""
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            logger.error("pytesseract / PIL non installés")
            return {"text": "", "language": "unknown", "engine": "none", "confidence": 0.0}

        all_text = []
        confidences = []

        for img_path in image_paths:
            try:
                img = Image.open(img_path)
                config = "--oem 3 --psm 6 -l fra+ara"
                data = pytesseract.image_to_data(
                    img, config=config,
                    output_type=pytesseract.Output.DICT,
                )
                page_text = self._reconstruct_lines_from_data(data)
                all_text.append(page_text)

                conf_values = []
                for c in data["conf"]:
                    try:
                        ci = int(c)
                        if ci > 0:
                            conf_values.append(ci)
                    except (ValueError, TypeError):
                        pass
                if conf_values:
                    confidences.append(np.mean(conf_values) / 100.0)
            except Exception as e:
                logger.warning(f"Tesseract échec sur {img_path} : {e}")

        full_text = "\n\n".join(all_text)

        return {
            "text": full_text,
            "language": self._detect_language(full_text),
            "engine": "tesseract",
            "confidence": float(np.mean(confidences)) if confidences else 0.5,
        }

    def _run_easyocr(self, image_paths: list[str]) -> dict:
        """EasyOCR — meilleur pour l'arabe."""
        if self._easyocr is None:
            try:
                import easyocr
                self._easyocr = easyocr.Reader(
                    ["ar", "fr"],
                    gpu=False,
                    verbose=False,
                )
            except ImportError:
                logger.error("EasyOCR non installé")
                return {"text": "", "language": "unknown", "engine": "none", "confidence": 0.0}

        all_text = []
        all_confs = []

        for img_path in image_paths:
            try:
                results = self._easyocr.readtext(
                    img_path,
                    detail=1,
                    paragraph=False,
                    width_ths=0.7, height_ths=0.7,
                    contrast_ths=0.1, adjust_contrast=0.5,
                    text_threshold=0.6, low_text=0.3,
                    link_threshold=0.4, mag_ratio=1.5,
                )
                results = self._sort_easyocr_results(results)
                page_lines = []
                for _bbox, text, conf in results:
                    page_lines.append(text)
                    all_confs.append(conf)
                all_text.append("\n".join(page_lines))
            except Exception as e:
                logger.warning(f"EasyOCR échec sur {img_path} : {e}")

        full_text = "\n\n".join(all_text)
        return {
            "text": full_text,
            "language": self._detect_language(full_text),
            "engine": "easyocr",
            "confidence": float(np.mean(all_confs)) if all_confs else 0.5,
        }

    def _run_hybrid(self, image_paths: list[str]) -> dict:
        """Lance les deux moteurs et garde le meilleur."""
        tess = self._run_tesseract(image_paths)
        easy = self._run_easyocr(image_paths)
        tess_ar = len(re.findall(r"[\u0600-\u06FF]", tess["text"]))
        easy_ar = len(re.findall(r"[\u0600-\u06FF]", easy["text"]))
        if easy_ar > tess_ar * 1.3:
            easy["engine"] = "easyocr (hybrid)"
            return easy
        if tess["confidence"] >= easy["confidence"]:
            tess["engine"] = "tesseract (hybrid)"
            return tess
        easy["engine"] = "easyocr (hybrid)"
        return easy

    def _sort_easyocr_results(self, results: list) -> list:
        """Tri spatial top-bottom puis RTL pour l'arabe (LTR pour le latin)."""
        if not results:
            return results
        annotated = []
        for r in results:
            bbox = r[0]
            ys = [p[1] for p in bbox]
            xs = [p[0] for p in bbox]
            annotated.append((sum(ys) / 4, max(xs), r))
        annotated.sort(key=lambda a: a[0])

        # Grouper par ligne (tolérance ±20px)
        lines = []
        current_line = [annotated[0]]
        for ann in annotated[1:]:
            if abs(ann[0] - current_line[-1][0]) < 20:
                current_line.append(ann)
            else:
                lines.append(current_line)
                current_line = [ann]
        lines.append(current_line)

        sorted_results = []
        for line in lines:
            sample = " ".join(a[2][1] for a in line)
            is_arabic = bool(re.search(r"[\u0600-\u06FF]", sample))
            if is_arabic:
                line.sort(key=lambda a: -a[1])  # RTL
            else:
                line.sort(key=lambda a: a[1])    # LTR
            sorted_results.extend([a[2] for a in line])
        return sorted_results

    def _reconstruct_lines_from_data(self, data: dict) -> str:
        """Reconstruit les lignes via block_num/par_num/line_num."""
        lines = defaultdict(list)
        for i, word in enumerate(data["text"]):
            if not word.strip():
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines[key].append((data["left"][i], word))
        result = []
        for key in sorted(lines.keys()):
            words = sorted(lines[key], key=lambda x: x[0])
            result.append(" ".join(w[1] for w in words))
        return "\n".join(result)

    def _detect_language(self, text: str) -> str:
        ar = len(re.findall(r"[\u0600-\u06FF]", text))
        fr = len(re.findall(r"[A-Za-zÀ-ÿ]", text))
        total = ar + fr
        if total < 10:
            return "unknown"
        ratio = ar / total
        if ratio > 0.7:
            return "ar"
        elif ratio < 0.2:
            return "fr"
        return "fr+ar"

    def _compute_cache_key(self, paths: list[str]) -> str:
        h = hashlib.sha256()
        for p in paths:
            try:
                with open(p, "rb") as f:
                    h.update(f.read())
            except Exception:
                h.update(p.encode())
        return h.hexdigest()


# ═══════════════════════════════════════════════════════════════════════════
# 4. POST-CORRECTION OCR — corrige les erreurs systématiques FR/AR
# ═══════════════════════════════════════════════════════════════════════════

class OCRPostCorrector:
    """Corrige les erreurs OCR récurrentes sur les documents administratifs."""

    def correct(self, text: str) -> str:
        text = self._normalize_unicode(text)
        text = self._convert_arabic_indic_digits(text)
        text = self._reconstruct_lines(text)
        text = self._fix_french_ocr(text)
        text = self._fix_arabic_ocr(text)
        text = self._fix_dates(text)
        text = self._fix_punctuation(text)
        return text

    def _normalize_unicode(self, t: str) -> str:
        t = unicodedata.normalize("NFC", t)
        t = t.replace("\u2019", "'").replace("\u2018", "'")
        t = t.replace("\u201C", '"').replace("\u201D", '"')
        t = re.sub(r"[\u2010-\u2015\u2212]", "-", t)
        return t

    def _convert_arabic_indic_digits(self, t: str) -> str:
        """٠١٢٣٤٥٦٧٨٩ → 0123456789"""
        ar_to_lat = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        per_to_lat = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
        return t.translate(ar_to_lat).translate(per_to_lat)

    def _reconstruct_lines(self, t: str) -> str:
        """Si le texte est aplati (peu de \\n, beaucoup d'espaces multiples),
        convertir les espaces multiples en \\n."""
        nb_nl = t.count("\n")
        nb_multi = len(re.findall(r"  +", t))
        if nb_multi >= 3 and nb_multi > nb_nl:
            t = re.sub(r" {2,}", "\n", t)
        return t

    def _fix_french_ocr(self, t: str) -> str:
        replacements = [
            (r"CADI\s+AW?A?Y?A?D", "CADI AYYAD"),
            (r"\bCRl(?=\s|\-|$)", "CRI"),
            (r"\bN\s*['\"`´]\s*(?=[\s:.]*\d)", "N° "),
            (r"(\b\d{1,2}\s+)AR(\.|\s)", r"\1AVR\2"),
            (r"\b(JAN|FEV|MAR|AVR|MAI|JUI|AOU|SEP|OCT|NOV|DEC)\.?\s+9(0\d{2})\b",
             r"\g<1>. 2\g<2>"),
        ]
        for pattern, repl in replacements:
            t = re.sub(pattern, repl, t, flags=re.IGNORECASE)
        return t

    def _fix_arabic_ocr(self, t: str) -> str:
        replacements = [
            # ة ↔ ه sur mots-clés institutionnels
            (r"\bرئاسه\b", "رئاسة"),
            (r"\bجامعه\b", "جامعة"),
            (r"\bكليه\b", "كلية"),
            (r"\bمدرسه\b", "مدرسة"),
            (r"\bرسالـ?ه\b", "رسالة"),
            # ى ↔ ي sur mots-clés
            (r"القاض[ى]\s+عياض", "القاضي عياض"),
            # ض variantes
            (r"\bعيا[دظذ]\b", "عياض"),
            # الموضوع : ع↔غ et ض↔ص↔ظ
            (r"\bالموضوغ\b", "الموضوع"),
            (r"\bالموصوع\b", "الموضوع"),
            (r"\bالموظوع\b", "الموضوع"),
            # إلى variantes
            (r"(?<=\s)إلي(?=\s)", "إلى"),
            # Mois — hamza fluctuante
            (r"\bابريل\b", "أبريل"),
            (r"\bاكتوبر\b", "أكتوبر"),
            (r"\bاغسطس\b", "أغسطس"),
        ]
        for pattern, repl in replacements:
            t = re.sub(pattern, repl, t)
        return t

    def _fix_dates(self, t: str) -> str:
        # Espaces parasites dans les jours : "0 2 AVR" → "02 AVR"
        t = re.sub(
            r"\b(\d)\s+(\d)\s+(AVR|JAN|FEV|MAR|MAI|JUI|AOU|SEP|OCT|NOV|DEC)",
            r"\1\2 \3", t, flags=re.IGNORECASE,
        )
        return t

    def _fix_punctuation(self, t: str) -> str:
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n{4,}", "\n\n\n", t)
        # Lignes de bruit pur (---, ===, ...)
        t = re.sub(r"^[\s\-_.=·•]+$", "", t, flags=re.MULTILINE)
        return t


# ═══════════════════════════════════════════════════════════════════════════
# 5. EXTRACTION NLP — extraction des 7 champs cibles
# ═══════════════════════════════════════════════════════════════════════════

class FieldExtractor:
    """
    Extracteur des 7 champs administratifs UCA depuis un texte normalisé.

    Champs : numero, date, objet, expediteur, destinataire,
             type_document, etablissement.
    """

    def extract(self, text: str) -> dict:
        """Retourne un dict avec les 7 champs + texte_complet + _confidence."""
        if not text or len(text.strip()) < 5:
            return self._empty_result(text)

        # Détection cachet d'arrivée → numero/date prioritaires
        cachet_zone = self._find_cachet_zone(text)
        cachet_num, cachet_date = (None, None)
        if cachet_zone:
            cachet_num, cachet_date = self._extract_from_cachet(cachet_zone)

        fields = {
            "numero": cachet_num or self._extract_numero(text),
            "date": cachet_date or self._extract_date(text),
            "objet": self._extract_objet(text),
            "expediteur": self._extract_expediteur(text),
            "destinataire": self._extract_destinataire(text),
            "type_document": self._extract_type(text),
            "etablissement": self._extract_etablissement(text),
        }

        # Scoring
        confidence = {
            k: self._score_confidence(k, v, text, cachet_zone is not None)
            for k, v in fields.items()
        }
        fields["_confidence"] = confidence
        return fields

    def _empty_result(self, text: str) -> dict:
        return {
            "numero": None, "date": None, "objet": None,
            "expediteur": None, "destinataire": None,
            "type_document": "lettre", "etablissement": None,
            "_confidence": {k: 0.0 for k in
                            ("numero", "date", "objet", "expediteur",
                             "destinataire", "type_document", "etablissement")},
        }

    # ─── Zone d'en-tête ───────────────────────────────────────────────────
    def _zone_entete(self, text: str) -> str:
        """Retourne la zone d'en-tête (avant le destinataire ou l'objet)."""
        markers = [
            r"\n\s*[AÀ]\s*\n\s*(?:Monsieur|Madame|Mesdames|Messieurs|MONSIEUR)",
            r"Objet\s*:",
            r"[Oo]b[ji]et\s*:",
            r"[Vv]euillez\s+trouver\s+ci[\-\s]?joint",
            r"[Cc]oncern(?:e|ant)\s*:",
            r"\n\s*إلى\s*\n",
            r"إلى\s*\n+\s*(?:السيد|السيدة|السيدتين|السادة|السيدات|الأستاذ|رؤساء|عمداء|مديري)",
            r"الموضوع\s*[:.]",
            r"ال[مم]و[ضصظط]و[عغ]\s*[:.]",
            r"تجدون\s+طيه|تجدونه\s+رفقته",
            r"سلام\s+تام\s+بوجود",
            r"وبعد\s*[,،]?\s*\n",
        ]
        limite = len(text)
        for m in markers:
            found = re.search(m, text)
            if found and found.start() < limite:
                limite = found.start()
        return text[:max(800, min(limite + 200, 3000))]

    # ─── Cachet d'arrivée ─────────────────────────────────────────────────
    def _find_cachet_zone(self, text: str) -> Optional[str]:
        """Détecte la zone du cachet d'arrivée (Présidence UCA, FR ou AR)."""
        patterns = [
            r"PR[EÉ]SIDENCE\s+DE\s+L['\u2018\u2019`\xb4\s]*UN\w*"
            r"[\s\S]{0,80}?CADI\s+AYY?A[DP]"
            r"[\s\S]{0,50}?MAR\w*",
            r"CADI\s+AYY?A[DP]\s*[\-',]?\s*MAR\w*",
            r"ر[ئي]اس[ةه]\s+جامع[ةه]\s+القاض[ىي]\s+عياض",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                start = max(0, m.start() - 50)
                end = min(len(text), m.end() + 400)
                zone = text[start:end]
                if self._has_cachet_markers(zone):
                    return zone
        return None

    def _has_cachet_markers(self, zone: str) -> bool:
        markers = [
            r"Arriv[eé]\s*(?:le)?",
            r"Sous\s+(?:N[°ºoO]|h)",
            r"ورد\s+يوم|رقم",
            r"\d{1,2}\s+(?:AVR|JAN|FEV|MAR|MAI|JUI|AOU|SEP|OCT|NOV|DEC)",
        ]
        return any(re.search(m, zone, re.IGNORECASE) for m in markers)

    def _extract_from_cachet(self, zone: str) -> tuple:
        """Extrait (numero, date) depuis la zone du cachet."""
        # Numéro : "Arrivé le : NNNN", "Sous N° : NNNN", "رقم : NNNN"
        num = None
        for pat in [
            r"Arriv[eé]\s*(?:le)?\s*[:.]?\s*(\d{3,5})",
            r"Sous\s+(?:N[°ºoO]|h)\s*[:.]?\s*(\d{3,5})",
            r"رقم\s*[:.]?\s*(\d{3,5})",
        ]:
            m = re.search(pat, zone, re.IGNORECASE)
            if m:
                num = m.group(1)
                break

        # Date : formats FR ("01 AVR. 2026") et AR ("02 أبريل 2026")
        date = self._find_date_in(zone)
        return num, date

    # ─── Numéro ───────────────────────────────────────────────────────────
    def _extract_numero(self, text: str) -> Optional[str]:
        zone = self._zone_entete(text)
        candidates = []

        # FR : N° NNN/YYYY
        m = re.search(r"N[°ºoO]\s*[:.]?\s*(\d{2,4})\s*/\s*(\d{3,5})", zone)
        if m:
            candidates.append((f"{m.group(1)}/{m.group(2)}", 90))

        # FR : N° NNN/YY/INST
        m = re.search(
            r"N[°ºoO]\s*[:.]?\s*(\d{3,6})\s*/\s*(\d{2})\s*/\s*([A-Z\-]{2,10})",
            zone,
        )
        if m:
            candidates.append((f"{m.group(1)}/{m.group(2)}/{m.group(3)}", 88))

        # AR : رقم NNN/NNNN
        m = re.search(
            r"رقم\s*[:.]?\s*[/\\]?\s*(\d{2,4})[\s/\\]{0,10}[=\-_]?\s*(\d{2,5})",
            text,
        )
        if m and len(m.group(2)) >= 3:
            candidates.append((f"{m.group(1)}/{m.group(2)}", 85))

        # AR : العدد ou مرجع
        m = re.search(r"العدد\s*[:.]?\s*(\d{3,6})\s*[/\\\-]\s*(\d{2,4})", text)
        if m:
            candidates.append((f"{m.group(1)}/{m.group(2)}", 75))

        # FR/AR : N° isolé (ex. bordereau "830")
        m = re.search(
            r"(?:N[°ºoO'\"]\s*[:.]?\s*|رقم\s*[:.]?\s*)[\s\n]*(\d{3,5})\b(?!\s*/)",
            zone,
        )
        if m:
            candidates.append((m.group(1), 70))

        # AR fallback : juste chiffre après رقم
        if not candidates:
            m = re.search(r"رقم\s*[:.]?\s*[/\\]?\s*(\d{3,5})", text)
            if m:
                candidates.append((m.group(1), 60))

        # Numéros encadrés (cachets : =NNNN-)
        m = re.search(r"[=_\[]\s*(\d{4,5})\s*[=_\]\-]", zone)
        if m and not candidates:
            candidates.append((m.group(1), 60))

        if not candidates:
            return None
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]

    # ─── Date ─────────────────────────────────────────────────────────────
    def _extract_date(self, text: str) -> Optional[str]:
        zone = self._zone_entete(text)
        d = self._find_date_in(zone)
        if d:
            return d
        return self._find_date_in(text[len(zone):])

    def _find_date_in(self, text: str) -> Optional[str]:
        # AR textuel
        m = re.search(
            r"(\d{1,2})\s+(يناير|فبراير|مارس|أبريل|ابريل|إبريل|"
            r"ماي|مايو|يونيو|يونيه|يوليوز|يوليو|يوليه|"
            r"غشت|أغسطس|اغسطس|شتنبر|سبتمبر|"
            r"أكتوبر|اكتوبر|نونبر|نوفمبر|دجنبر|ديسمبر)\s+(\d{4})",
            text,
        )
        if m:
            mois = MOIS_AR.get(m.group(2))
            if mois:
                return f"{m.group(1).zfill(2)} {mois} {m.group(3)}"

        # FR textuel
        m = re.search(
            r"(\d{1,2})(?:er)?\s+([a-zA-ZéèêûôîÉÈÊÛÔÎ]+)\.?\s+(\d{4})",
            text,
        )
        if m:
            mois_raw = m.group(2).lower().rstrip(".")
            mois_norm = self._normalize_mois_fr(mois_raw)
            if mois_norm:
                return f"{m.group(1).zfill(2)} {mois_norm} {m.group(3)}"

        # FR abrégé : "01 AVR. 2026"
        m = re.search(r"(\d{1,2})\s+([A-ZÉÈ]{3,4})\.?\s+(\d{4})", text)
        if m:
            mois = MOIS_FR_ABBR.get(m.group(2).upper())
            if mois:
                return f"{m.group(1).zfill(2)} {mois} {m.group(3)}"

        # Numérique : 01/04/2026
        m = re.search(r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})\b", text)
        if m:
            day, month, year = m.group(1), m.group(2), m.group(3)
            mi = int(month)
            if 1 <= mi <= 12 and 2020 <= int(year) <= 2030:
                mois_fr = ["", "janvier", "février", "mars", "avril", "mai",
                           "juin", "juillet", "août", "septembre", "octobre",
                           "novembre", "décembre"][mi]
                return f"{day.zfill(2)} {mois_fr} {year}"

        return None

    def _normalize_mois_fr(self, mois: str) -> Optional[str]:
        mapping = {
            "janvier": "janvier", "fevrier": "février", "février": "février",
            "mars": "mars", "avril": "avril", "mai": "mai", "juin": "juin",
            "juillet": "juillet", "aout": "août", "août": "août",
            "septembre": "septembre", "octobre": "octobre",
            "novembre": "novembre", "decembre": "décembre", "décembre": "décembre",
        }
        return mapping.get(mois)

    # ─── Objet ────────────────────────────────────────────────────────────
    def _extract_objet(self, text: str) -> Optional[str]:
        objet_word = r"[_\*\[\]\s]*(?:OBJET|[O0Ø][bB][jJiI][eE][tTlL])[_\*\[\]\s]*"
        separator = r"\s*[:;.,\-=]\s*"

        # FR : multi-lignes
        m = re.search(
            rf"(?:^|\n|[\.\!\?]\s+){objet_word}{separator}(.+?)"
            rf"(?:\n\n|\n\s*(?:Monsieur|Madame|Mesdames|Messieurs|Cher|· |\* )|$)",
            text, re.IGNORECASE | re.DOTALL,
        )
        if m:
            cand = self._clean_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        # FR : ligne unique
        m = re.search(
            rf"(?:^|\n){objet_word}{separator}(.+?)(?:\n|$)",
            text, re.MULTILINE | re.IGNORECASE,
        )
        if m:
            cand = self._clean_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        # FR : milieu de ligne (texte aplati)
        m = re.search(
            rf"(?:CADI\s+AYYAD|UNIVERSIT[EÉ]|Cher|Madame|Monsieur)\s+"
            rf"{objet_word}{separator}(.+?)(?:\n|$)",
            text, re.IGNORECASE,
        )
        if m:
            cand = self._clean_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        # FR : Concernant
        m = re.search(
            r"(?:^|\n)\s*[_\*]*\s*[Cc]oncern(?:e|ant)[_\*]*\s*[:;.\-]\s*(.+?)(?:\n|$)",
            text, re.MULTILINE,
        )
        if m:
            cand = self._clean_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        # AR : الموضوع multi-lignes
        m = re.search(
            r"ال[مم]و[ضصظط]و[عغ]\s*[:.]?\s*(.+?)"
            r"(?:\n\n|\n\s*(?:سلام|وبعد|في\s+إطار|بناء\s+على|نتشرف|يشرفنا|تحية))",
            text, re.DOTALL,
        )
        if m:
            cand = self._clean_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        # AR : ligne unique
        m = re.search(r"ال[مم]و[ضصظط]و[عغ]\s*[:.]?\s*(.+?)(?:\n|$)", text)
        if m:
            cand = self._clean_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        # Bordereau FR
        m = re.search(
            r"[Vv]euillez\s+trouver\s+ci[\-\s]?joint\s*[,:.]?\s*\n+\s*(.+?)(?:\n\n|$)",
            text, re.DOTALL,
        )
        if m:
            cand = self._clean_objet(m.group(1))
            if cand and len(cand) > 5 and not cand.lower().startswith(("nature", "nombre")):
                return cand

        # Bordereau AR
        m = re.search(r"تجدون(?:ه)?\s+(?:طيه|رفقته)\s*[:.]?\s*\n+\s*(.+?)(?:\n\n|$)",
                      text, re.DOTALL)
        if m:
            cand = self._clean_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        return None

    def _clean_objet(self, raw: str) -> Optional[str]:
        s = raw.strip()
        s = re.sub(r"^[_\-=:*\s\|\.]+", "", s)
        s = re.sub(r"[_\-=\s]+$", "", s)
        s = re.sub(r"\s+", " ", s)
        return s if len(s) > 3 else None

    # ─── Expéditeur ───────────────────────────────────────────────────────
    def _extract_expediteur(self, text: str) -> Optional[str]:
        # AR : "من السيد رئيس الجامعة" → Présidence UCA
        if re.search(r"من\s+السيد\s+رئيس\s+الجامعة", text):
            return "Le Président de l'Université Cadi Ayyad"

        # AR : "من + (titre) + (institution)"
        m = re.search(
            r"من\s+(?:السيد|السيدة)?\s*(عميد|عميدة|مدير|مديرة|رئيس|نائب\s+رئيس)\s+([^\n]{5,100})",
            text,
        )
        if m:
            mapping = {
                "عميد": "Le Doyen", "عميدة": "La Doyenne",
                "مدير": "Le Directeur", "مديرة": "La Directrice",
                "رئيس": "Le Président",
                "نائب رئيس": "Le Vice-Président",
            }
            titre_ar = m.group(1).strip()
            inst_ar = m.group(2).strip()
            titre_fr = mapping.get(titre_ar, titre_ar)
            return f"{titre_fr} de {inst_ar}"

        # AR : رئيس الجامعة + tag Présidence
        if re.search(r"رئيس\s+الجامعة", text[:1500]) and re.search(
            r"رئاسة|الرئاسة|جامعة\s+القاض[يى]\s+عياض", text[:1500]
        ):
            return "Le Président de l'Université Cadi Ayyad"

        # Zone expéditeur (avant destinataire)
        destinataire_match = re.search(
            r"(?:^|\n)\s*(?:[AÀ]\s*[\n\s]+(?:Monsieur|Madame|Mesdames|Messieurs)|"
            r"إلى\s*[\n\s]+(?:السيد|السيدة|السيدتين|السادة|السيدات|الأستاذ|"
            r"رؤساء|عمداء|مديري|أعضاء))",
            text,
        )
        zone = (text[:destinataire_match.start()] if destinataire_match
                else text[:1500])

        # Présidence émettrice détection
        is_presidence = bool(
            re.search(
                r"(?:Royaume\s+du\s+Maroc\s+)?[^\n]*Universit[eé]\s+Cadi\s+Ayyad[^\n]*\n\s*La\s+Pr[eé]sidence",
                zone, re.IGNORECASE,
            )
            or re.search(r"^\s*La\s+Pr[eé]sidence\s*$", zone, re.MULTILINE | re.IGNORECASE)
        )

        # Recherche institution (priorité haute)
        institution = None
        if not is_presidence:
            best_prio = -1
            for pattern, nom, priorite in INSTITUTIONS:
                if re.search(pattern, zone, re.IGNORECASE):
                    if priorite > best_prio:
                        institution = nom
                        best_prio = priorite

        # Recherche titre
        titre = None
        for pattern, nom in TITRES_EMETTEUR:
            if re.search(pattern, zone):
                titre = nom
                break

        parts = [p for p in (titre, institution) if p]
        if parts:
            return " — ".join(parts)

        # Fallback : déduire depuis l'établissement
        etab = self._extract_etablissement(text)
        if etab:
            if etab.startswith(("FST-", "FSS-", "FSJES-", "FMP-", "FLSH-")):
                return "Le Doyen"
            if etab.startswith(("EST-", "ENSA-", "CRI-")):
                return "Le Directeur"
            if "Présidence" in etab:
                return "Le Président"
        return None

    # ─── Destinataire ─────────────────────────────────────────────────────
    def _extract_destinataire(self, text: str) -> Optional[str]:
        # FR : "A\nMonsieur/Madame..."
        m = re.search(
            r"(?:^|\n)\s*[AÀ]\s*\n\s*"
            r"((?:Monsieur|Madame|Mesdames|Messieurs|MONSIEUR|MADAME)\s+"
            r"(?:le|la|les|LE|LA|LES)?\s*\w+[^\n]{0,200})",
            text,
        )
        if m:
            cand = self._clean_destinataire(m.group(1))
            if cand:
                return cand

        # AR : "إلى\n<titre><...>"
        m = re.search(
            r"إلى\s*[\n\s]+("
            r"(?:السيد|السيدة|السيدتين|السادة|السيدات|الأستاذ|الأستاذة|الدكتور|"
            r"رؤساء|عمداء|مديري|أعضاء)"
            r"[^\n]{5,250}(?:\n[^\n]{3,150})?"
            r")",
            text,
        )
        if m:
            cand = self._clean_destinataire(m.group(1))
            if cand:
                return cand

        # AR : إلى\n<destinataire libre>
        m = re.search(r"إلى\s*\n+\s*([^\n]{15,300})", text)
        if m:
            cand = m.group(1).strip()
            keywords = ("السيد", "السيدة", "السيدتين", "السادة", "السيدات",
                        "رئيس", "رؤساء", "عميد", "عمداء", "مدير", "مديري",
                        "المؤسسات", "الكليات", "الجامعة")
            if any(kw in cand for kw in keywords):
                start = m.end()
                next_line = re.match(r"\n([^\n]{5,200})", text[start:])
                if next_line and not re.match(
                    r"^\s*(?:الموضوع|ال[مم]و[ضصظط]و[عغ]|سلام|وبعد|في\s+إطار)",
                    next_line.group(1),
                ):
                    cand += " " + next_line.group(1).strip()
                cleaned = self._clean_destinataire(cand)
                if cleaned:
                    return cleaned

        # Label "Destinataire :"
        m = re.search(r"[Dd]estinataire\s*[:.]\s*(.+?)(?:\n|$)", text)
        if m:
            return self._clean_destinataire(m.group(1))

        return None

    def _clean_destinataire(self, raw: str) -> Optional[str]:
        s = raw.strip()
        s = re.sub(r"^[\|\s«»\-,]+", "", s)
        s = re.sub(r"\n+", ", ", s)
        s = re.sub(r"\s+", " ", s)
        s = re.sub(r"[\s,]+$", "", s)

        # Détection arabe → préserver
        ar = len(re.findall(r"[\u0600-\u06FF]", s))
        lat = len(re.findall(r"[A-Za-zÀ-ÿ]", s))
        is_arabic = ar > 3 and ar >= lat

        if not is_arabic:
            s = re.sub(r"[\u0600-\u06FF]+", "", s)
            s = re.sub(r"\s+", " ", s).strip()

        # Couper aux marqueurs de fin (objet, bordereau)
        s = re.split(
            r"\s+(?:Objet|OBJET|Bordereau|BORDEREAU|"
            r"الموضوع|ال[مم]و[ضصظط]و[عغ]|"
            r"Nature|Nombre|Veuillez)\s*[:\s]",
            s, maxsplit=1,
        )[0]

        # Capitalisation FR si tout en MAJ
        if not is_arabic and s.isupper() and len(s) > 10:
            words = s.split()
            kept_upper = {"UCA", "FST", "FSS", "FSJES", "CRI", "EST", "ENSA",
                          "FMP", "FLSH"}
            result = []
            for w in words:
                if w in kept_upper:
                    result.append(w)
                elif w in {"LE", "LA", "LES", "DE", "DU", "DES"}:
                    result.append(w.lower())
                else:
                    result.append(w.capitalize())
            s = " ".join(result)
            if s:
                s = s[0].upper() + s[1:]

        return s.strip() if len(s) > 5 else None

    # ─── Type de document ─────────────────────────────────────────────────
    def _extract_type(self, text: str) -> str:
        zone = text[:3000]
        for type_name, patterns in TYPES_DOCUMENT.items():
            for pat in patterns:
                if re.search(pat, zone):
                    return type_name
        return "lettre"

    # ─── Établissement ────────────────────────────────────────────────────
    def _extract_etablissement(self, text: str) -> Optional[str]:
        # Restreindre à la zone d'en-tête
        destinataire_match = re.search(
            r"(?:^|\n)\s*(?:[AÀ]\s*[\n\s]+(?:Monsieur|Madame|Mesdames|Messieurs)|"
            r"إلى\s*[\n\s]+(?:السيد|السيدة|السيدتين|السادة|السيدات|الأستاذ|"
            r"رؤساء|عمداء|مديري|أعضاء))",
            text,
        )
        zone = (text[:destinataire_match.start()] if destinataire_match
                else text[:1500])

        # Présidence (priorité)
        if re.search(
            r"(?:Royaume\s+du\s+Maroc\s+)?[^\n]*Universit[eé]\s+Cadi\s+Ayyad[^\n]*\n\s*La\s+Pr[eé]sidence",
            zone, re.IGNORECASE,
        ):
            return "La Présidence - Marrakech"
        if re.search(r"^\s*La\s+Pr[eé]sidence\s*$", zone, re.MULTILINE | re.IGNORECASE):
            return "La Présidence - Marrakech"

        # FR
        mapping = [
            (r"[Cc]entre\s+R[eé]gional\s+d[''']?[Ii]nvestissement[\s\S]{0,30}?Marrakech|CRI[\s\-\.]*R?M?S?",
             "CRI-Marrakech-Safi"),
            (r"Facult[eé]\s+des\s+Sciences\s+Semlalia|FSSM\b", "FSS-Marrakech"),
            (r"Facult[eé]\s+des\s+Sciences\s+Juridiques|FSJES\b", "FSJES-Marrakech"),
            (r"Facult[eé]\s+des\s+Sciences\s+et\s+Techniques|FSTG?\b", "FST-Marrakech"),
            (r"Facult[eé]\s+Polydisciplinaire.{0,20}?Safi|FP\s*Safi", "FP-Safi"),
            (r"Facult[eé]\s+de\s+M[eé]decine\s+et\s+de\s+Pharmacie|FMPM\b", "FMP-Marrakech"),
            (r"Facult[eé]\s+des\s+Lettres|FLSH\b", "FLSH-Marrakech"),
            (r"[EÉ]cole\s+Nationale\s+des\s+Sciences\s+Appliqu[eé]es|ENSA\b", "ENSA-Marrakech"),
            (r"[EÉ]cole\s+Sup[eé]rieure\s+de\s+Technologie.{0,15}?Essaouira", "EST-Essaouira"),
            (r"[EÉ]cole\s+Sup[eé]rieure\s+de\s+Technologie.{0,15}?Safi", "EST-Safi"),
        ]
        for pat, nom in mapping:
            if re.search(pat, zone, re.IGNORECASE):
                return nom

        # AR
        ar_mapping = [
            (r"رئاسة\s+جامعة\s+القاض[يى]\s+عياض", "La Présidence - Marrakech"),
            (r"كلية\s+العلوم\s+القانونية", "FSJES-Marrakech"),
            (r"كلية\s+العلوم\s+والتقنيات", "FST-Marrakech"),
            (r"كلية\s+العلوم[\s\S]{0,20}?سملالية", "FSS-Marrakech"),
            (r"كلية\s+الطب\s+والصيدلة", "FMP-Marrakech"),
            (r"كلية\s+الآداب\s+والعلوم\s+الإنسانية", "FLSH-Marrakech"),
            (r"الكلية\s+المتعددة\s+التخصصات[\s\S]{0,30}?[آا]سفي", "FP-Safi"),
            (r"المدرسة\s+الوطنية\s+للعلوم\s+التطبيقية", "ENSA-Marrakech"),
            (r"المدرسة\s+العليا\s+للتكنولوجيا[\s\S]{0,15}?الصويرة", "EST-Essaouira"),
            (r"المدرسة\s+العليا\s+للتكنولوجيا[\s\S]{0,15}?[آا]سفي", "EST-Safi"),
            (r"المركز\s+الجهوي\s+ل[لإا]*ستثمار", "CRI-Marrakech-Safi"),
        ]
        for pat, nom in ar_mapping:
            if re.search(pat, zone):
                return nom

        # Inférence Présidence depuis "رئيس الجامعة"
        if re.search(r"من\s+السيد(?:ة)?\s+رئيس\s+الجامعة", zone):
            return "La Présidence - Marrakech"
        if re.search(r"رئيس\s+الجامعة", zone) and re.search(
            r"جامعة\s+القاض[يى]\s+عياض", zone
        ):
            return "La Présidence - Marrakech"

        return None

    # ─── Score de confiance ───────────────────────────────────────────────
    def _score_confidence(self, field: str, value: Any, text: str,
                          has_cachet: bool) -> float:
        if value is None:
            return 0.0
        if field == "type_document":
            return 0.55 if value == "lettre" else 0.85

        base_score = {
            "numero": 0.90 if has_cachet else 0.70,
            "date": 0.95 if has_cachet else 0.85,
            "objet": 0.80,
            "expediteur": 0.85,
            "destinataire": 0.85,
            "etablissement": 0.90,
        }.get(field, 0.70)

        # Pénalités
        s = str(value)
        if len(s) < 5:
            base_score -= 0.15
        if len(s) > 200:
            base_score -= 0.05
        # Caractères suspects (artefacts OCR)
        nb_special = len(re.findall(r"[^\w\s\u0600-\u06FF\-,'.:/À-ÿ]", s))
        if nb_special > 3:
            base_score -= 0.10

        return max(0.0, min(1.0, base_score))


# ═══════════════════════════════════════════════════════════════════════════
# 6. ROUTAGE DE CONFIANCE — pour validation humaine en UI
# ═══════════════════════════════════════════════════════════════════════════

class ConfidenceRouter:
    """Routage des champs vers l'agent selon le score de confiance."""

    THRESHOLD_AUTO = 0.90
    THRESHOLD_REVIEW = 0.60

    def route(self, field: str, value: Any, confidence: float) -> dict:
        if value is None or confidence < self.THRESHOLD_REVIEW:
            return {
                "action": "manual", "color": "red",
                "message": "À saisir manuellement", "value": None,
            }
        elif confidence < self.THRESHOLD_AUTO:
            return {
                "action": "review", "color": "yellow",
                "message": f"Vérifier ({int(confidence * 100)}%)",
                "value": value,
            }
        return {
            "action": "auto", "color": "green",
            "message": f"OK ({int(confidence * 100)}%)",
            "value": value,
        }


# ═══════════════════════════════════════════════════════════════════════════
# 7. ORCHESTRATEUR PRINCIPAL — pipeline complet
# ═══════════════════════════════════════════════════════════════════════════

class OCRPipeline:
    """
    Pipeline complet : PDF/Image → JSON structuré.

    Étapes :
      1. PDF → Images (PyMuPDF, 300 DPI)
      2. Pré-traitement adaptatif (3 variantes par page)
      3. OCR hybride avec routage automatique FR/AR
      4. Post-correction OCR
      5. Extraction NLP des 7 champs
      6. Scoring de confiance + routage validation humaine

    Usage :
        pipeline = OCRPipeline()
        result = pipeline.process("/path/to/courrier.pdf")
    """

    def __init__(self, tmp_dir: str = "/tmp/ocr_uca"):
        self.preprocessor = ArabicAwarePreprocessor()
        self.ocr = HybridOCREngine()
        self.corrector = OCRPostCorrector()
        self.extractor = FieldExtractor()
        self.router = ConfidenceRouter()
        self.tmp_dir = Path(tmp_dir)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def process(self, file_path: str,
                force_engine: Optional[str] = None) -> dict:
        """
        Traite un document complet.

        Args:
            file_path     : chemin du fichier (PDF, JPG, PNG)
            force_engine  : 'tesseract' / 'easyocr' / 'hybrid' / None (auto)

        Returns:
            JSON structuré avec les 7 champs + métadonnées + UI hints.
        """
        return self._do_process(file_path, force_engine)

    def process_document(self, file_path: str, file_type: Optional[str] = None,
                         force_engine: Optional[str] = None) -> dict:
        """
        Alias de compatibilité avec l'ancienne API du module.
        Accepte le paramètre file_type (ignoré, détecté automatiquement).
        """
        return self._do_process(file_path, force_engine)

    def _do_process(self, file_path: str,
                    force_engine: Optional[str] = None) -> dict:
        t_start = time.time()
        timings: dict[str, float] = {}

        # 1. PDF → Images (ou image directe)
        t = time.time()
        if file_path.lower().endswith(".pdf"):
            image_paths = self._pdf_to_images(file_path)
        else:
            image_paths = [file_path]
        timings["pdf_to_images_ms"] = round((time.time() - t) * 1000)

        # 2. Pré-traitement (multi-variantes) — parallelisé par page
        t = time.time()
        page_variants: dict[str, list[str]] = {}
        def _proc_save(path: str):
            try:
                variants = self.preprocessor.preprocess(path)
                return self._save_variants(variants, path)
            except Exception as e:
                logger.warning(f"Préprocessing échoué pour {path} : {e}")
                return [path]

        max_workers = min(4, (os.cpu_count() or 2))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_proc_save, p): p for p in image_paths}
            for fut in as_completed(futures):
                p = futures[fut]
                try:
                    variant_paths = fut.result()
                except Exception as e:
                    logger.warning(f"Préprocessing exception pour {p}: {e}")
                    variant_paths = [p]
                page_variants[p] = variant_paths

        timings["preprocessing_ms"] = round((time.time() - t) * 1000)

        # 3. OCR — avec fallback automatique si moteur principal plante
        t = time.time()
        # Validate force_engine
        try:
            mode = OCRMode(force_engine) if force_engine else OCRMode.AUTO
        except Exception:
            logger.warning(f"force_engine invalide: {force_engine}, utilisation AUTO")
            mode = OCRMode.AUTO

        # OCR per page (parallel) — each page gets its variants
        page_results = {}
        ocr_errors = []
        max_workers = min(3, (os.cpu_count() or 2))
        def _ocr_for_page(variant_paths: list[str]):
            # Try in requested mode, then Tesseract, then EasyOCR
            res = None
            try:
                res = self.ocr.extract(variant_paths, mode=mode)
                if res and res.get("text", "").strip():
                    return res
            except Exception as e:
                logger.debug(f"OCR primary failed for page: {e}")
            # fallback sequence
            for fb in (OCRMode.TESSERACT, OCRMode.EASYOCR):
                if fb == mode:
                    continue
                try:
                    res = self.ocr.extract(variant_paths, mode=fb)
                    if res and res.get("text", "").strip():
                        return res
                except Exception as e:
                    logger.debug(f"Fallback {fb} failed: {e}")
            return {"text": "", "language": "unknown", "engine": "failed", "confidence": 0.0}

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut_to_page = {ex.submit(_ocr_for_page, page_variants[p]): p for p in image_paths}
            for fut in as_completed(fut_to_page):
                p = fut_to_page[fut]
                try:
                    page_results[p] = fut.result()
                except Exception as e:
                    logger.error(f"OCR failed for page {p}: {e}")
                    page_results[p] = {"text": "", "language": "unknown", "engine": "failed", "confidence": 0.0}

        # Merge page results in order
        ordered_texts = [page_results[p]["text"] for p in image_paths if p in page_results]
        ocr_text = "\n\n--- Page suivante ---\n\n".join(ordered_texts)
        # Aggregate language/confidence/engine info
        confidences = [page_results[p].get("confidence", 0.0) for p in page_results]
        engines = [page_results[p].get("engine") for p in page_results]
        ocr_result = {
            "text": ocr_text,
            "language": self.ocr._detect_language(ocr_text) if hasattr(self.ocr, '_detect_language') else 'unknown',
            "engine": ",".join(sorted(set(e for e in engines if e))),
            "confidence": float(sum(confidences) / len(confidences)) if confidences else 0.0,
        }
        timings["ocr_ms"] = round((time.time() - t) * 1000)

        # 4. Post-correction
        t = time.time()
        corrected_text = self.corrector.correct(ocr_result["text"])
        timings["post_correction_ms"] = round((time.time() - t) * 1000)

        # 5. Extraction NLP
        t = time.time()
        fields = self.extractor.extract(corrected_text)
        timings["nlp_extraction_ms"] = round((time.time() - t) * 1000)

        # Temps total de traitement
        total_ms = round((time.time() - t_start) * 1000)

        # 6. Routage validation humaine
        confidence = fields.pop("_confidence", {})
        ui_hints = {
            field: self.router.route(field, fields.get(field),
                                     confidence.get(field, 0.0))
            for field in ("numero", "date", "objet", "expediteur",
                          "destinataire", "type_document", "etablissement")
        }

        # Extraction du corps via le texte corrigé (séparation entête/corps)
        corps = self._extract_corps(corrected_text)

        return {
            # ─── Champs principaux ───
            "numero": fields.get("numero"),
            "date": fields.get("date"),
            "objet": fields.get("objet"),
            "expediteur": fields.get("expediteur"),
            "destinataire": fields.get("destinataire"),
            "type_document": fields.get("type_document"),
            "etablissement": fields.get("etablissement"),
            "corps": corps,

            # ─── Texte OCR + métadonnées langue ───
            "texte_complet": corrected_text,
            "texte_ocr_brut": corrected_text,           # Alias rétro-compat
            "langue_detectee": ocr_result["language"],

            # ─── Confiance ───
            "confidence": {k: int(v * 100) for k, v in confidence.items()},
            "ui_hints": ui_hints,

            # ─── Métadonnées techniques ───
            "ocr_engine_used": ocr_result["engine"],    # Alias rétro-compat
            "processing_time_ms": total_ms,             # Alias rétro-compat
            "metadata": {
                "ocr_engine": ocr_result["engine"],
                "ocr_confidence": int(ocr_result["confidence"] * 100),
                "processing_time_ms": total_ms,
                "page_count": len(image_paths),
                "timings": timings,
            },
        }

    def _extract_corps(self, text: str) -> Optional[str]:
        """Extraction simple du corps : ce qui reste après l'objet et avant les
        formules de politesse / signatures."""
        if not text or len(text) < 50:
            return None

        # Couper avant l'objet
        m = re.search(
            r"(?:Objet|الموضوع|ال[مم]و[ضصظط]و[عغ])\s*[:.]\s*[^\n]+\n+",
            text, re.IGNORECASE,
        )
        start = m.end() if m else 0

        # Couper avant les salutations finales
        end_markers = [
            r"\n\s*[Vv]euillez\s+agr[eé]er",
            r"\n\s*Nous\s+vous\s+prions",
            r"\n\s*Le\s+Pr[eé]sident\s*\n",
            r"\n\s*Le\s+Doyen\s*\n",
            r"\n\s*Le\s+Directeur\s*\n",
            r"\n\s*وتقبلوا",
            r"\n\s*وتفضلوا",
            r"\n\s*المرفقات",
            r"\n\s*Pi[eè]ces?\s+joint",
        ]
        end = len(text)
        for mk in end_markers:
            mm = re.search(mk, text[start:])
            if mm:
                end = min(end, start + mm.start())

        corps = text[start:end].strip()
        # Nettoyage des lignes vides multiples
        corps = re.sub(r"\n{3,}", "\n\n", corps)
        return corps if len(corps) > 30 else None

    def _pdf_to_images(self, pdf_path: str) -> list[str]:
        """Conversion PDF → PNG via PyMuPDF (300 DPI)."""
        try:
            import fitz
        except ImportError:
            logger.error("PyMuPDF non installé — impossible de traiter le PDF")
            return []

        out_dir = self.tmp_dir / "pages"
        out_dir.mkdir(parents=True, exist_ok=True)
        image_paths = []

        try:
            doc = fitz.open(pdf_path)
            stem = Path(pdf_path).stem
            for page_num, page in enumerate(doc):
                pix = page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72))
                img_path = out_dir / f"{stem}_p{page_num}.png"
                pix.save(str(img_path))
                image_paths.append(str(img_path))
            doc.close()
        except Exception as e:
            logger.error(f"Conversion PDF échouée : {e}")
        return image_paths

    def _save_variants(self, variants: list, base_path: str) -> list[str]:
        """Sauvegarde les variantes pré-traitées en PNG."""
        base = Path(base_path).stem
        out_dir = self.tmp_dir / "variants"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for i, variant in enumerate(variants):
            p = out_dir / f"{base}_v{i}.png"
            cv2.imwrite(str(p), variant)
            paths.append(str(p))
        return paths


# ═══════════════════════════════════════════════════════════════════════════
# 8. POINT D'ENTRÉE CLI POUR TESTS RAPIDES
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if len(sys.argv) < 2:
        print("Usage : python pipeline_v11.py <fichier.pdf|image>")
        sys.exit(1)

    file_path = sys.argv[1]
    force_engine = sys.argv[2] if len(sys.argv) > 2 else None

    pipeline = OCRPipeline()
    result = pipeline.process(file_path, force_engine=force_engine)

    print(json.dumps({
        "numero": result["numero"],
        "date": result["date"],
        "objet": result["objet"],
        "expediteur": result["expediteur"],
        "destinataire": result["destinataire"],
        "type_document": result["type_document"],
        "etablissement": result["etablissement"],
        "langue_detectee": result["langue_detectee"],
        "confidence": result["confidence"],
        "metadata": result["metadata"],
    }, indent=2, ensure_ascii=False))
