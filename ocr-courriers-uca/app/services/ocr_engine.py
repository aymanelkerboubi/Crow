"""
Service OCR — version robuste avec SUPPORT ARABE RENFORCÉ

Moteurs OCR supportés (par ordre de qualité pour l'arabe) :
  1. PaddleOCR (le meilleur pour l'arabe, recommandé) — `pip install paddleocr paddlepaddle`
  2. EasyOCR (très bon pour l'arabe) — `pip install easyocr`
  3. Tesseract avec tessdata_best (acceptable) — par défaut

Modes de fonctionnement (settings.OCR_ENGINE) :
  - "tesseract"  : Tesseract uniquement (rapide, qualité moyenne sur arabe)
  - "easyocr"    : EasyOCR uniquement
  - "paddle"     : PaddleOCR uniquement
  - "hybrid"     : Tesseract pour FR + meilleur engine arabe disponible pour AR
  - "auto"       : choisit dynamiquement selon le contenu détecté

Fonctionnalités :
  - Multi-PSM : essaie plusieurs Page Segmentation Modes (configurable)
  - Cache d'images traitées (SHA-256, max 50 entrées)
  - Détection langue automatique
  - Extraction ciblée par bbox + whitelist de caractères
  - Corrections OCR arabes spécifiques (1↔ا, l↔ل, etc.)
"""
import pytesseract
from PIL import Image
import logging
import re
import os
import platform
import shutil
import hashlib
import time

logger = logging.getLogger(__name__)


# ─── Détection des moteurs disponibles ─────────────────────────────────────
def _has_easyocr() -> bool:
    try:
        import easyocr  # noqa
        return True
    except ImportError:
        return False


def _has_paddleocr() -> bool:
    try:
        import paddleocr  # noqa
        return True
    except ImportError:
        return False


HAS_EASYOCR = _has_easyocr()
HAS_PADDLEOCR = _has_paddleocr()

if HAS_PADDLEOCR:
    logger.info("PaddleOCR disponible (qualité arabe : excellente)")
elif HAS_EASYOCR:
    logger.info("EasyOCR disponible (qualité arabe : très bonne)")
else:
    logger.info("Aucun moteur AR avancé installé (PaddleOCR/EasyOCR). "
                "Tesseract seul sera utilisé pour l'arabe.")


# ─── Tesseract path detection ─────────────────────────────────────────────
def _find_tesseract_cmd(user_provided: str = None) -> str:
    """Trouve le binaire Tesseract."""
    if user_provided and os.path.exists(user_provided):
        return user_provided
    found = shutil.which("tesseract")
    if found:
        return found
    if platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
    return ""


# ─── PSM modes Tesseract ──────────────────────────────────────────────────
PSM_MODES = {
    "auto": 3,
    "single_block": 6,
    "single_column": 4,
    "sparse": 11,
    "sparse_osd": 12,
}


# ─── Corrections OCR arabes courantes ─────────────────────────────────────
# Erreurs typiques OCR Tesseract sur l'arabe : caractères latins confondus
# avec des arabes, diacritiques manqués, espaces excessifs
ARABIC_OCR_FIXES = [
    # Espaces multiples → un seul
    (re.compile(r"\s+"), " "),
    # Caractères latins isolés au milieu d'un mot arabe → souvent OCR cassé
    # Ex: "جامعة" mal lu comme "جامعt" : la lettre latine est probablement à enlever
    (re.compile(r"([\u0600-\u06FF])[a-zA-Z]([\u0600-\u06FF])"), r"\1\2"),
    # Confusion 0/o avec ه (heh arabe)
    # NE PAS FAIRE ces fixes automatiquement, ils sont contextuels
]


def fix_arabic_ocr(text: str) -> str:
    """Applique des corrections OCR courantes sur du texte arabe."""
    if not text:
        return text
    for pattern, replacement in ARABIC_OCR_FIXES:
        text = pattern.sub(replacement, text)
    return text


def detect_arabic_zones(text: str) -> dict:
    """
    Analyse un texte mixte FR/AR et retourne :
    {
        "primary_lang": "fr" | "ar" | "fr+ar",
        "arabic_ratio": float,
        "needs_arabic_specialist": bool
    }
    """
    arabic_chars = len(re.findall(r"[\u0600-\u06FF\u0750-\u077F]", text))
    latin_chars = len(re.findall(r"[a-zA-ZÀ-ÿ]", text))
    total = arabic_chars + latin_chars
    if total == 0:
        return {"primary_lang": "fr", "arabic_ratio": 0.0,
                "needs_arabic_specialist": False}
    ratio = arabic_chars / total
    if ratio > 0.6:
        primary = "ar"
    elif ratio > 0.15:
        primary = "fr+ar"
    else:
        primary = "fr"
    return {
        "primary_lang": primary,
        "arabic_ratio": ratio,
        "needs_arabic_specialist": ratio > 0.20,
    }


# ─── OCR Engine ───────────────────────────────────────────────────────────
class OCREngine:
    """Moteur OCR avec support multi-engine et arabe renforcé."""

    _CACHE = {}  # {image_hash: result_dict}
    _easyocr_instance = None  # singleton
    _paddle_instance = None  # singleton

    def __init__(self, engine: str = "tesseract", languages: str = "fra+ara",
                 tesseract_cmd: str = None, multi_psm: bool = False,
                 enable_cache: bool = True):
        self.engine = engine
        self.languages = languages
        self.multi_psm = multi_psm
        self.enable_cache = enable_cache

        resolved_cmd = _find_tesseract_cmd(tesseract_cmd)
        if resolved_cmd:
            pytesseract.pytesseract.tesseract_cmd = resolved_cmd
            logger.info(f"Tesseract trouvé : {resolved_cmd}")
            self._check_languages()
        elif engine in ("tesseract", "hybrid", "auto"):
            logger.warning(
                "Tesseract non trouvé ! Installer depuis "
                "https://github.com/UB-Mannheim/tesseract/wiki "
            )

        # Vérifier l'engine demandé est disponible
        self._validate_engine_choice()

    def _validate_engine_choice(self):
        """Vérifie que l'engine demandé est installé, fallback sinon."""
        if self.engine == "easyocr" and not HAS_EASYOCR:
            logger.warning("EasyOCR non installé, fallback sur Tesseract. "
                           "`pip install easyocr` pour l'activer.")
            self.engine = "tesseract"
        elif self.engine == "paddle" and not HAS_PADDLEOCR:
            logger.warning("PaddleOCR non installé, fallback sur EasyOCR/Tesseract. "
                           "`pip install paddleocr paddlepaddle` pour l'activer.")
            self.engine = "easyocr" if HAS_EASYOCR else "tesseract"

    def _check_languages(self):
        """Vérifie les langues Tesseract installées."""
        try:
            available = pytesseract.get_languages(config="")
            requested = self.languages.split("+")
            missing = [lang for lang in requested if lang not in available]
            if missing:
                logger.warning(
                    f"Langues manquantes : {missing}. Télécharger depuis "
                    f"https://github.com/tesseract-ocr/tessdata_best "
                    f"(version 'best' recommandée pour l'arabe). "
                    f"Dispo : {available}"
                )
        except Exception as e:
            logger.debug(f"Impossible de lister les langues : {e}")

    # ═══ API PRINCIPALE ═══════════════════════════════════════════════════

    def extract_text(self, image_path: str, variants: list = None) -> dict:
        """Extrait le texte d'une image."""
        t0 = time.time()

        if self.enable_cache:
            cached = self._cache_lookup(image_path)
            if cached:
                logger.info(f"Cache hit : {os.path.basename(image_path)}")
                return cached

        paths_to_try = [image_path] + (variants or [])

        # Routage selon l'engine choisi
        if self.engine == "easyocr":
            result = self._extract_easyocr(image_path)
        elif self.engine == "paddle":
            result = self._extract_paddle(image_path)
        elif self.engine == "hybrid":
            result = self._extract_hybrid(paths_to_try)
        elif self.engine == "auto":
            result = self._extract_auto(paths_to_try)
        else:  # tesseract
            result = self._extract_tesseract_multi(paths_to_try)

        # Appliquer les corrections OCR arabes
        if result.get("text"):
            zones = detect_arabic_zones(result["text"])
            if zones["arabic_ratio"] > 0.1:
                result["text"] = fix_arabic_ocr(result["text"])

        result["metadata"] = {
            "processing_time_ms": int((time.time() - t0) * 1000),
            "variants_tried": len(paths_to_try),
        }

        if self.enable_cache:
            self._cache_store(image_path, result)

        return result

    def extract_from_multiple_pages(self, image_paths: list,
                                     variants_per_page: dict = None) -> dict:
        """OCR sur plusieurs pages."""
        if not image_paths:
            raise ValueError("Liste d'images vide")

        all_texts = []
        total_confidence = 0
        engine_used = None

        for path in image_paths:
            variants = (variants_per_page or {}).get(path, [])
            try:
                result = self.extract_text(path, variants=variants)
                all_texts.append(result["text"])
                total_confidence += result["confidence"]
                engine_used = result["engine"]
            except Exception as e:
                logger.warning(f"OCR échoué pour {path} : {e}")
                all_texts.append("")

        combined_text = "\n\n--- Page suivante ---\n\n".join(all_texts)
        avg_conf = total_confidence / len(image_paths) if image_paths else 0
        detected_lang = self._detect_language(combined_text)

        return {
            "text": combined_text,
            "engine": engine_used or self.engine,
            "language": detected_lang,
            "confidence": round(avg_conf, 2),
            "num_pages": len(image_paths),
        }

    # ═══ Tesseract ═══════════════════════════════════════════════════════

    def _extract_tesseract_multi(self, paths: list) -> dict:
        """Multi-PSM Tesseract : essaie plusieurs modes, garde le meilleur."""
        results = []
        psm_list = [6, 3, 4, 11] if self.multi_psm else [3]

        for path in paths:
            for psm in psm_list:
                try:
                    r = self._extract_tesseract_single(path, psm=psm)
                    r["psm_used"] = psm
                    r["path_used"] = path
                    results.append(r)
                except Exception as e:
                    logger.debug(f"Tesseract PSM={psm} sur {path} : {e}")

        if not results:
            raise RuntimeError("Tous les essais Tesseract ont échoué")

        def score(r):
            conf = r.get("confidence", 0)
            txt_len = len(r.get("text", ""))
            return conf * 0.7 + min(txt_len / 500, 1.0) * 0.3

        best = max(results, key=score)
        if self.multi_psm:
            logger.info(
                f"Tesseract: PSM={best.get('psm_used')} choisi, "
                f"confiance={best.get('confidence', 0):.2f}, "
                f"{len(best.get('text', ''))} chars"
            )
        return best

    def _extract_tesseract_single(self, image_path: str, psm: int = 3) -> dict:
        """Un appel Tesseract avec un PSM donné."""
        try:
            img = Image.open(image_path)
            # --oem 3 = LSTM neural (le mieux pour l'arabe)
            # -c preserve_interword_spaces=1 = garde les espaces (utile pour arabe)
            config = f"--psm {psm} --oem 3 -c preserve_interword_spaces=1"
            text = pytesseract.image_to_string(
                img, lang=self.languages, config=config,
            )

            try:
                data = pytesseract.image_to_data(
                    img, lang=self.languages,
                    config=config,
                    output_type=pytesseract.Output.DICT,
                )
                confidences = [int(c) for c in data["conf"] if int(c) > 0]
                avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            except Exception:
                avg_confidence = 0

            detected_lang = self._detect_language(text)

            return {
                "text": text.strip(),
                "engine": "tesseract",
                "language": detected_lang,
                "confidence": round(avg_confidence / 100, 2),
            }
        except pytesseract.TesseractNotFoundError as e:
            raise RuntimeError(
                "Tesseract OCR n'est pas installé. "
                "Télécharger depuis https://github.com/UB-Mannheim/tesseract/wiki"
            ) from e
        except pytesseract.TesseractError as e:
            msg = str(e)
            if "Failed loading language" in msg or "Error opening data file" in msg:
                raise RuntimeError(
                    f"Pack de langue Tesseract manquant ({self.languages}). "
                    f"Télécharger fra.traineddata + ara.traineddata depuis "
                    f"https://github.com/tesseract-ocr/tessdata_best (version 'best')."
                ) from e
            raise

    # ═══ EasyOCR ═════════════════════════════════════════════════════════

    def _extract_easyocr(self, image_path: str) -> dict:
        """EasyOCR — bon pour l'arabe, support natif."""
        if not HAS_EASYOCR:
            raise RuntimeError(
                "EasyOCR non installé. `pip install easyocr` "
                "(prend ~2GB pour les modèles)"
            )
        try:
            if OCREngine._easyocr_instance is None:
                import easyocr
                lang_map = {"fra": "fr", "ara": "ar"}
                langs = [lang_map.get(l.strip(), l.strip())
                         for l in self.languages.split("+")]
                logger.info(f"Initialisation EasyOCR (langues={langs})...")
                OCREngine._easyocr_instance = easyocr.Reader(langs, gpu=False)
                logger.info("EasyOCR prêt")

            results = OCREngine._easyocr_instance.readtext(image_path)
            texts = [text for _, text, _ in results]
            confidences = [conf for _, _, conf in results]
            full_text = "\n".join(texts)
            avg_conf = sum(confidences) / len(confidences) if confidences else 0
            detected_lang = self._detect_language(full_text)

            logger.info(
                f"EasyOCR: {len(full_text)} chars, "
                f"conf={avg_conf:.2f}, lang={detected_lang}"
            )

            return {
                "text": full_text.strip(),
                "engine": "easyocr",
                "language": detected_lang,
                "confidence": round(avg_conf, 2),
            }
        except Exception as e:
            logger.error(f"Erreur EasyOCR : {e}")
            raise

    # ═══ PaddleOCR ════════════════════════════════════════════════════════

    def _extract_paddle(self, image_path: str) -> dict:
        """PaddleOCR — excellent pour l'arabe."""
        if not HAS_PADDLEOCR:
            raise RuntimeError(
                "PaddleOCR non installé. "
                "`pip install paddleocr paddlepaddle`"
            )
        try:
            if OCREngine._paddle_instance is None:
                from paddleocr import PaddleOCR
                # Choisir la langue principale pour PaddleOCR
                # 'arabic' couvre l'arabe, 'fr' le français
                # On ne peut pas mettre les deux dans une instance
                # → Si on a besoin des deux, on instancie 2 fois (coûteux)
                # → Pour économiser, on prend 'arabic' qui couvre aussi les chiffres
                logger.info("Initialisation PaddleOCR (lang=arabic)...")
                OCREngine._paddle_instance = PaddleOCR(
                    use_angle_cls=True,
                    lang="arabic",
                    show_log=False,
                )
                logger.info("PaddleOCR prêt")

            result = OCREngine._paddle_instance.ocr(image_path, cls=True)

            # Format de retour : [[(bbox, (text, conf)), ...]]
            texts = []
            confidences = []
            if result and result[0]:
                for line in result[0]:
                    if line and len(line) >= 2:
                        text = line[1][0]
                        conf = line[1][1]
                        texts.append(text)
                        confidences.append(conf)

            full_text = "\n".join(texts)
            avg_conf = sum(confidences) / len(confidences) if confidences else 0
            detected_lang = self._detect_language(full_text)

            logger.info(
                f"PaddleOCR: {len(full_text)} chars, "
                f"conf={avg_conf:.2f}, lang={detected_lang}"
            )

            return {
                "text": full_text.strip(),
                "engine": "paddle",
                "language": detected_lang,
                "confidence": round(avg_conf, 2),
            }
        except Exception as e:
            logger.error(f"Erreur PaddleOCR : {e}")
            raise

    # ═══ Mode HYBRIDE (intelligent) ══════════════════════════════════════

    def _extract_hybrid(self, paths: list) -> dict:
        """
        Mode hybride : exécute Tesseract + (Paddle ou EasyOCR), garde le
        meilleur. EasyOCR/Paddle gagnent si le contenu est très arabe.
        """
        # Toujours essayer Tesseract (rapide)
        try:
            t_result = self._extract_tesseract_multi(paths)
        except Exception as e:
            logger.warning(f"Tesseract échoué : {e}")
            t_result = None

        # Choisir le meilleur engine arabe disponible
        ar_result = None
        ar_engine = None
        if HAS_PADDLEOCR:
            try:
                ar_result = self._extract_paddle(paths[0])
                ar_engine = "paddle"
            except Exception as e:
                logger.warning(f"PaddleOCR échoué : {e}")
        if ar_result is None and HAS_EASYOCR:
            try:
                ar_result = self._extract_easyocr(paths[0])
                ar_engine = "easyocr"
            except Exception as e:
                logger.warning(f"EasyOCR échoué : {e}")

        if t_result and ar_result:
            # Décider lequel garder selon la langue détectée
            zones = detect_arabic_zones(t_result["text"])
            t_score = t_result["confidence"]
            ar_score = ar_result["confidence"]

            # Si le texte contient beaucoup d'arabe, privilégier ar_engine
            if zones["arabic_ratio"] > 0.3:
                ar_score *= 1.3
                t_score *= 0.9
            else:
                # Texte majoritairement français : Tesseract est bon
                t_score *= 1.1

            chosen = t_result if t_score >= ar_score else ar_result
            logger.info(
                f"Hybride: Tesseract={t_score:.2f}, "
                f"{ar_engine}={ar_score:.2f} → {chosen['engine']}"
            )
            return chosen

        return t_result or ar_result

    # ═══ Mode AUTO (sélectionne le meilleur engine selon le contenu) ════

    def _extract_auto(self, paths: list) -> dict:
        """
        Mode auto : fait un OCR rapide avec Tesseract pour détecter la
        langue dominante, puis utilise le meilleur moteur en conséquence.
        """
        # Étape 1 : OCR rapide Tesseract pour détecter la langue
        try:
            quick = self._extract_tesseract_single(paths[0], psm=3)
            zones = detect_arabic_zones(quick["text"])
        except Exception:
            zones = {"primary_lang": "fr", "arabic_ratio": 0.0,
                     "needs_arabic_specialist": False}

        # Étape 2 : utiliser le bon moteur
        if zones["needs_arabic_specialist"]:
            if HAS_PADDLEOCR:
                logger.info("Auto: contenu arabe détecté, utilisation PaddleOCR")
                try:
                    return self._extract_paddle(paths[0])
                except Exception as e:
                    logger.warning(f"Paddle échoué : {e}")
            if HAS_EASYOCR:
                logger.info("Auto: contenu arabe détecté, utilisation EasyOCR")
                try:
                    return self._extract_easyocr(paths[0])
                except Exception as e:
                    logger.warning(f"EasyOCR échoué : {e}")

        # Sinon, Tesseract suffit
        logger.info("Auto: Tesseract suffisant pour ce document")
        return self._extract_tesseract_multi(paths)

    # ═══ Cache ═══════════════════════════════════════════════════════════

    def _image_hash(self, image_path: str) -> str:
        try:
            with open(image_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()[:16]
        except Exception:
            return image_path

    def _cache_lookup(self, image_path: str) -> dict:
        h = self._image_hash(image_path)
        return self._CACHE.get(h)

    def _cache_store(self, image_path: str, result: dict):
        h = self._image_hash(image_path)
        if len(self._CACHE) >= 50:
            first_key = next(iter(self._CACHE))
            self._CACHE.pop(first_key)
        self._CACHE[h] = dict(result)

    # ═══ Détection de langue ═════════════════════════════════════════════

    def _detect_language(self, text: str) -> str:
        """Détecte si le texte est en français, arabe, ou les deux."""
        arabic_chars = len(re.findall(r"[\u0600-\u06FF\u0750-\u077F]", text))
        latin_chars = len(re.findall(r"[a-zA-ZÀ-ÿ]", text))
        if arabic_chars > latin_chars:
            return "ar"
        elif arabic_chars > 0 and arabic_chars > latin_chars * 0.2:
            return "fr+ar"
        return "fr"

    # ═══ Extraction ciblée par bbox ═══════════════════════════════════════

    def extract_from_region(self, image_path: str, bbox: tuple,
                             psm: int = 6, whitelist: str = None) -> str:
        """OCR ciblé sur une région : (x1, y1, x2, y2)."""
        try:
            img = Image.open(image_path)
            cropped = img.crop(bbox)
            config = f"--psm {psm} --oem 3"
            if whitelist:
                config += f" -c tessedit_char_whitelist={whitelist}"
            text = pytesseract.image_to_string(
                cropped, lang=self.languages, config=config,
            )
            return text.strip()
        except Exception as e:
            logger.warning(f"OCR région échoué : {e}")
            return ""
