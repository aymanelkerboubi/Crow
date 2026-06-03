"""
Service de pré-traitement des images — version robuste et adaptative.

Améliorations majeures :
- Upscaling automatique des scans basse résolution
- Détection qualité de l'image et choix du pipeline adapté
- Correction d'orientation à 90°/180°/270°
- Unsharp mask pour récupérer les caractères flous
- Correction gamma automatique pour scans sous/sur-exposés
- Morphologie pour recoller les caractères cassés
- Suppression de bordures noires (scan mal cadré)
- Multi-variantes pour OCR multi-pipeline (return_variants=True)
"""
import cv2
import numpy as np
from PIL import Image
from pathlib import Path
import tempfile
import logging
import os
import platform
import shutil
import math

logger = logging.getLogger(__name__)


# ─── DÉTECTION POPPLER ─────────────────────────────────────────────────────
def _find_poppler_path() -> str:
    """Localise Poppler automatiquement sur Windows."""
    if platform.system() != "Windows":
        return ""
    if shutil.which("pdftoppm"):
        return ""

    candidates = [
        r"C:\poppler\Library\bin",
        r"C:\Program Files\poppler\Library\bin",
        r"C:\Program Files (x86)\poppler\Library\bin",
    ]
    import glob
    for base in [r"C:\poppler-*", r"C:\Program Files\poppler-*"]:
        for d in glob.glob(base):
            candidates.append(os.path.join(d, "Library", "bin"))
            candidates.append(os.path.join(d, "bin"))

    for p in candidates:
        if os.path.exists(os.path.join(p, "pdftoppm.exe")):
            logger.info(f"Poppler détecté : {p}")
            return p
    return ""


POPPLER_PATH = _find_poppler_path()


# ─── ANALYSE DE QUALITÉ D'IMAGE ────────────────────────────────────────────
class ImageQualityAnalyzer:
    """Analyse la qualité d'une image pour choisir le bon pipeline OCR."""

    @staticmethod
    def analyze(gray: np.ndarray) -> dict:
        """
        Retourne un dict avec métriques de qualité.
        """
        h, w = gray.shape[:2]
        min_dim = min(h, w)

        if min_dim < 1000:
            resolution = "low"
        elif min_dim < 2000:
            resolution = "medium"
        else:
            resolution = "high"

        blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        contrast = float(gray.std())
        brightness = float(gray.mean())

        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        noise = float((gray.astype(float) - blurred.astype(float)).std())
        if noise < 5:
            noise_level = "low"
        elif noise < 15:
            noise_level = "medium"
        else:
            noise_level = "high"

        return {
            "resolution": resolution,
            "width": w,
            "height": h,
            "blur": blur,
            "contrast": contrast,
            "brightness": brightness,
            "noise_level": noise_level,
            "needs_upscale": resolution == "low",
            "is_low_quality": blur < 100 or contrast < 30
                              or brightness < 80 or brightness > 200,
        }


# ─── PIPELINE DE PRÉ-TRAITEMENT ────────────────────────────────────────────
class ImagePreprocessor:
    """
    Pré-traitement adaptatif des scans de courriers avant OCR.
    """

    def __init__(self, deskew_enabled=True, contrast_enabled=True,
                 aggressive=False, upscale_factor=2.0):
        self.deskew_enabled = deskew_enabled
        self.contrast_enabled = contrast_enabled
        self.aggressive = aggressive
        self.upscale_factor = upscale_factor

    def preprocess(self, image_path: str, return_variants: bool = False):
        """
        Applique la chaîne complète de pré-traitement.

        Args:
            image_path: chemin de l'image à traiter
            return_variants: si True, retourne plusieurs variantes de
                l'image traitée pour OCR multi-pipeline

        Returns:
            str (chemin) ou List[str] si return_variants=True
        """
        logger.info(f"Pré-traitement : {image_path}")

        img = self._read_image_robust(image_path)

        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img.copy()

        quality = ImageQualityAnalyzer.analyze(gray)
        logger.info(
            f"Qualité : résolution={quality['resolution']} "
            f"({quality['width']}x{quality['height']}), "
            f"blur={quality['blur']:.1f}, "
            f"contrast={quality['contrast']:.1f}, "
            f"brightness={quality['brightness']:.1f}, "
            f"bruit={quality['noise_level']}"
        )

        use_aggressive = self.aggressive or quality["is_low_quality"]

        # Pipeline de nettoyage
        gray = self._remove_black_borders(gray)
        if quality["needs_upscale"]:
            gray = self._upscale(gray, self.upscale_factor)
            logger.info(f"Upscaling ×{self.upscale_factor}")
        gray = self._correct_orientation(gray)
        if self.deskew_enabled:
            gray = self._deskew(gray)
        gray = self._auto_gamma_correction(gray, quality["brightness"])
        gray = self._denoise_adaptive(gray, quality["noise_level"])
        if self.contrast_enabled:
            gray = self._enhance_contrast(gray)

        if return_variants:
            return self._produce_variants(gray, use_aggressive)

        # Pipeline unique
        if use_aggressive:
            gray = self._unsharp_mask(gray)
            processed = self._binarize_adaptive(gray)
            processed = self._morphology_fix(processed)
        else:
            processed = self._binarize_adaptive(gray)

        output_path = tempfile.mktemp(suffix=".png")
        cv2.imwrite(output_path, processed)
        logger.info(f"Image pré-traitée : {output_path} "
                    f"(pipeline={'aggressive' if use_aggressive else 'standard'})")
        return output_path

    def _produce_variants(self, gray: np.ndarray, aggressive: bool) -> list:
        """
        Produit 2-3 variantes de l'image pour OCR multi-pipeline.
        """
        variants = []

        # V1 : binarisation adaptative classique
        v1 = self._binarize_adaptive(gray)
        p1 = tempfile.mktemp(suffix="_v1.png")
        cv2.imwrite(p1, v1)
        variants.append(p1)

        # V2 : Otsu + morphologie
        _, v2 = cv2.threshold(gray, 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        v2 = self._morphology_fix(v2)
        p2 = tempfile.mktemp(suffix="_v2.png")
        cv2.imwrite(p2, v2)
        variants.append(p2)

        # V3 : unsharp + adaptative (pour scans flous)
        if aggressive:
            sharp = self._unsharp_mask(gray)
            v3 = self._binarize_adaptive(sharp)
            p3 = tempfile.mktemp(suffix="_v3.png")
            cv2.imwrite(p3, v3)
            variants.append(p3)

        logger.info(f"Variantes : {len(variants)}")
        return variants

    # ═══ Primitives d'image ═══════════════════════════════════════════════

    def _read_image_robust(self, image_path: str) -> np.ndarray:
        """Lit une image avec cv2 puis PIL en fallback."""
        img = cv2.imread(image_path)
        if img is not None:
            return img
        try:
            pil_img = Image.open(image_path).convert("RGB")
            return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        except Exception as e:
            raise ValueError(f"Impossible de lire l'image {image_path} : {e}")

    def _remove_black_borders(self, image: np.ndarray) -> np.ndarray:
        """Retire les bordures noires d'un scan mal cadré."""
        try:
            h, w = image.shape[:2]
            mask_dark = image < 30
            top = 0
            for i in range(min(h, 50)):
                if mask_dark[i].sum() / w > 0.8:
                    top = i + 1
                else:
                    break
            bot = h
            for i in range(h - 1, max(h - 50, 0) - 1, -1):
                if mask_dark[i].sum() / w > 0.8:
                    bot = i
                else:
                    break
            left = 0
            for j in range(min(w, 50)):
                if mask_dark[:, j].sum() / h > 0.8:
                    left = j + 1
                else:
                    break
            right = w
            for j in range(w - 1, max(w - 50, 0) - 1, -1):
                if mask_dark[:, j].sum() / h > 0.8:
                    right = j
                else:
                    break

            if top > 5 or bot < h - 5 or left > 5 or right < w - 5:
                cropped = image[top:bot, left:right]
                logger.info(f"Bordures retirées : top={top} bot={h-bot} "
                            f"left={left} right={w-right}")
                return cropped
            return image
        except Exception as e:
            logger.warning(f"Suppression bordures échouée : {e}")
            return image

    def _upscale(self, image: np.ndarray, factor: float) -> np.ndarray:
        """Agrandit l'image avec interpolation cubique."""
        h, w = image.shape[:2]
        new_h = int(h * factor)
        new_w = int(w * factor)
        return cv2.resize(image, (new_w, new_h),
                          interpolation=cv2.INTER_CUBIC)

    def _correct_orientation(self, image: np.ndarray) -> np.ndarray:
        """Détecte et corrige les rotations 90°/180°/270°."""
        try:
            import pytesseract
            import re
            pil_img = Image.fromarray(image)
            osd = pytesseract.image_to_osd(pil_img, config="--psm 0")
            match = re.search(r"Rotate:\s*(\d+)", osd)
            if match:
                rotation = int(match.group(1))
                if rotation == 90:
                    image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
                    logger.info("Rotation 90° corrigée")
                elif rotation == 180:
                    image = cv2.rotate(image, cv2.ROTATE_180)
                    logger.info("Rotation 180° corrigée")
                elif rotation == 270:
                    image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
                    logger.info("Rotation 270° corrigée")
        except Exception as e:
            logger.debug(f"Détection orientation échouée : {e}")
        return image

    def _deskew(self, image: np.ndarray) -> np.ndarray:
        """Redresse un document incliné (petits angles)."""
        try:
            edges = cv2.Canny(image, 50, 150)
            lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
            if lines is None or len(lines) < 5:
                return image
            angles = []
            for line in lines[:50]:
                rho, theta = line[0]
                angle = (theta * 180 / np.pi) - 90
                if -15 < angle < 15:
                    angles.append(angle)
            if not angles:
                return image
            median_angle = float(np.median(angles))
            if abs(median_angle) < 0.5:
                return image
            (h, w) = image.shape[:2]
            M = cv2.getRotationMatrix2D((w // 2, h // 2), median_angle, 1.0)
            rotated = cv2.warpAffine(
                image, M, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
            logger.info(f"Deskew appliqué : {median_angle:.2f}°")
            return rotated
        except Exception as e:
            logger.warning(f"Deskew échoué : {e}")
            return image

    def _auto_gamma_correction(self, image: np.ndarray,
                                brightness: float) -> np.ndarray:
        """Correction gamma automatique pour scans sous/sur-exposés."""
        try:
            if 100 <= brightness <= 160:
                return image
            target = 128
            current_norm = brightness / 255
            if current_norm <= 0:
                return image
            gamma = math.log(target / 255) / math.log(current_norm)
            gamma = max(0.4, min(gamma, 2.5))

            inv_gamma = 1.0 / gamma
            table = np.array([
                ((i / 255.0) ** inv_gamma) * 255
                for i in range(256)
            ]).astype("uint8")
            corrected = cv2.LUT(image, table)
            logger.info(f"Gamma corrigé : γ={gamma:.2f} "
                        f"(luminosité {brightness:.0f} → ~128)")
            return corrected
        except Exception as e:
            logger.warning(f"Correction gamma échouée : {e}")
            return image

    def _denoise_adaptive(self, image: np.ndarray, noise_level: str) -> np.ndarray:
        """Dénoise adapté au niveau de bruit détecté."""
        if noise_level == "low":
            return image
        elif noise_level == "medium":
            return cv2.fastNlMeansDenoising(image, None, h=7,
                                            templateWindowSize=7,
                                            searchWindowSize=21)
        else:
            return cv2.fastNlMeansDenoising(image, None, h=12,
                                            templateWindowSize=7,
                                            searchWindowSize=21)

    def _enhance_contrast(self, image: np.ndarray) -> np.ndarray:
        """Améliore le contraste via CLAHE."""
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        return clahe.apply(image)

    def _unsharp_mask(self, image: np.ndarray, amount: float = 1.5,
                      radius: int = 2) -> np.ndarray:
        """Unsharp mask — rend le texte plus net, utile pour cachets flous."""
        blurred = cv2.GaussianBlur(image, (radius * 2 + 1, radius * 2 + 1), 0)
        sharpened = cv2.addWeighted(image, 1 + amount, blurred, -amount, 0)
        return np.clip(sharpened, 0, 255).astype(np.uint8)

    def _binarize_adaptive(self, image: np.ndarray) -> np.ndarray:
        """Binarisation adaptative (éclairage non uniforme)."""
        return cv2.adaptiveThreshold(
            image, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=15,
            C=3,
        )

    def _morphology_fix(self, binary: np.ndarray) -> np.ndarray:
        """Morphologie : recoller caractères cassés."""
        kernel = np.ones((2, 2), np.uint8)
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        return closed

    # ═══ PDF → Images ════════════════════════════════════════════════════

    def pdf_to_images(self, pdf_path: str, dpi: int = 300) -> list:
        """Convertir un PDF en images haute résolution."""
        try:
            import fitz  # noqa: F401
            return self._pdf_to_images_fitz(pdf_path, dpi=dpi)
        except ImportError:
            logger.info("PyMuPDF non installé, essai de pdf2image/Poppler")
        except Exception as e:
            logger.warning(f"PyMuPDF a échoué ({e}), essai de pdf2image/Poppler")

        try:
            return self._pdf_to_images_poppler(pdf_path, dpi=dpi)
        except Exception as e:
            logger.error(f"Poppler a aussi échoué : {e}")
            raise RuntimeError(
                f"Impossible de convertir le PDF en images. "
                f"Installer PyMuPDF (pip install PyMuPDF) ou Poppler. "
                f"Erreur : {e}"
            ) from e

    def _pdf_to_images_fitz(self, pdf_path: str, dpi: int = 300) -> list:
        """Conversion PDF → images via PyMuPDF."""
        import fitz
        doc = fitz.open(pdf_path)
        image_paths = []
        zoom = dpi / 72
        mat = fitz.Matrix(zoom, zoom)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            path = tempfile.mktemp(suffix=f"_page{i+1}.png")
            pix.save(path)
            image_paths.append(path)
        doc.close()
        logger.info(f"PDF → {len(image_paths)} pages @ {dpi} DPI (PyMuPDF)")
        return image_paths

    def _pdf_to_images_poppler(self, pdf_path: str, dpi: int = 300) -> list:
        """Conversion PDF → images via pdf2image + Poppler."""
        from pdf2image import convert_from_path
        kwargs = {"dpi": dpi}
        if POPPLER_PATH:
            kwargs["poppler_path"] = POPPLER_PATH
        images = convert_from_path(pdf_path, **kwargs)
        image_paths = []
        for i, img in enumerate(images):
            path = tempfile.mktemp(suffix=f"_page{i+1}.png")
            img.save(path, "PNG")
            image_paths.append(path)
        logger.info(f"PDF → {len(image_paths)} pages @ {dpi} DPI (Poppler)")
        return image_paths
