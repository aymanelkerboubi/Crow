"""
Service d'extraction NLP — Entraîné sur 10 courriers réels UCA (avril 2026).
v2 — Ajouts : FMPM, FLSH, ENSA, ENCG, types docs enrichis, mois arabes complets,
     pattern العدد, robustesse expéditeur/établissement pour nouveaux établissements.

Stratégie :
  1. Normalisation du texte (OCR corrections communes).
  2. Extraction multi-patterns avec fallbacks.
  3. Règles métiers spécifiques UCA (institutions reconnues, formules types).
  4. Scoring de confiance basé sur la validation structurelle.
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# RÉFÉRENTIELS
# ═══════════════════════════════════════════════════════════════════════════

MOIS_FR = {
    'JAN': 'janvier', 'JANV': 'janvier', 'JANVIER': 'janvier',
    'FEV': 'février', 'FEVR': 'février', 'FEVRIER': 'février', 'FÉVRIER': 'février',
    'MAR': 'mars', 'MARS': 'mars',
    'AVR': 'avril', 'AVRI': 'avril', 'AVRIL': 'avril',
    'MAI': 'mai',
    'JUN': 'juin', 'JUIN': 'juin', 'JUI': 'juin',
    'JUL': 'juillet', 'JUIL': 'juillet', 'JUILLET': 'juillet',
    'AOU': 'août', 'AOUT': 'août', 'AOÛT': 'août', 'AOÛ': 'août',
    'SEP': 'septembre', 'SEPT': 'septembre', 'SEPTEMBRE': 'septembre',
    'OCT': 'octobre', 'OCTOBRE': 'octobre',
    'NOV': 'novembre', 'NOVEMBRE': 'novembre',
    'DEC': 'décembre', 'DECEMBRE': 'décembre', 'DÉCEMBRE': 'décembre', 'DÉC': 'décembre',
}

# Mois arabes — versions Maroc + Machrek + variantes OCR
MOIS_AR = {
    'يناير': 'janvier',
    'فبراير': 'février',
    'مارس': 'mars',
    'أبريل': 'avril', 'ابريل': 'avril', 'إبريل': 'avril',
    'ماي': 'mai', 'مايو': 'mai',
    'يونيو': 'juin', 'يونيه': 'juin',
    'يوليوز': 'juillet', 'يوليو': 'juillet', 'يوليه': 'juillet',
    'غشت': 'août', 'أغسطس': 'août', 'اغسطس': 'août',
    'شتنبر': 'septembre', 'سبتمبر': 'septembre',
    'أكتوبر': 'octobre', 'اكتوبر': 'octobre',
    'نونبر': 'novembre', 'نوفمبر': 'novembre',
    'دجنبر': 'décembre', 'ديسمبر': 'décembre',
}

MOIS_NUM = ['', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
            'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']

# Regex de tous les mois arabes pour _find_date_in()
_MOIS_AR_REGEX = (
    r'يناير|فبراير|مارس|أبريل|ابريل|إبريل|ماي|مايو'
    r'|يونيو|يونيه|يوليوز|يوليو|يوليه'
    r'|غشت|أغسطس|اغسطس|شتنبر|سبتمبر'
    r'|أكتوبر|اكتوبر|نونبر|نوفمبر|دجنبر|ديسمبر'
)

# Institutions UCA — patterns FR + AR avec priorité
INSTITUTIONS = [
    # ─── FRANÇAIS ───
    (r"[Cc]entre\s+R[eé]gional\s+d[''']?[Ii]nvestissement.{0,30}?Marrakech|CRI[\s\-\.]*RMS|CRI[\s\-]+Marrakech",
     "CRI Marrakech-Safi", 10),
    (r"Facult[eé]\s+des\s+Sciences\s+Semlalia|FSSM|FSS\s*Semlalia|Sciences\s+Semlalia",
     "FSS Semlalia", 10),
    (r"Facult[eé]\s+des\s+Sciences\s+Juridiques.{0,40}?[Mm]arrakech|FSJES|Sciences\s+Juridiques.{0,40}?[eE]conomiques",
     "FSJES Marrakech", 10),
    (r"Facult[eé]\s+des\s+Sciences\s+et\s+Techniques|FSTG?\b|Sciences\s+et\s+Techniques.{0,20}?Marrakech",
     "FST Marrakech", 10),
    (r"Facult[eé]\s+Polydisciplinaire.{0,20}?Safi|FP\s*Safi|FPS\b",
     "FP Safi", 10),
    (r"Facult[eé]\s+de\s+M[eé]decine\s+et\s+de\s+Pharmacie|FMPM?\b|M[eé]decine\s+et\s+de\s+Pharmacie",
     "FMP Marrakech", 10),
    (r"Facult[eé]\s+des\s+Lettres\s+et\s+des?\s+Sciences\s+Humaines|FLSH\b",
     "FLSH Marrakech", 10),
    (r"[EÉ]cole\s+Nationale\s+des\s+Sciences\s+Appliqu[eé]es|ENSA\b",
     "ENSA Marrakech", 10),
    (r"[EÉ]cole\s+Nationale\s+de\s+Commerce\s+et\s+de\s+Gestion|ENCG\b",
     "ENCG Marrakech", 10),
    (r"[EÉ]cole\s+Sup[eé]rieure\s+de\s+Technologie.{0,20}?Essaouira|EST.{0,5}?Essaouira|ESTE\b",
     "EST Essaouira", 10),
    (r"[EÉ]cole\s+Sup[eé]rieure\s+de\s+Technologie.{0,20}?Safi|EST.{0,5}?Safi",
     "EST Safi", 10),
    (r"Pr[eé]sidence.{0,30}?(?:Cadi\s+Ay?yad|Université)|La\s+Pr[eé]sidence|Royaume\s+du\s+Maroc.{0,30}?Pr[eé]sidence",
     "Présidence UCA", 8),
    (r"Universit[eé]\s+Cadi\s+Ay?yad|UCAM",
     "Université Cadi Ayyad", 5),
    # ─── ARABE ───
    (r"رئاسة\s+جامعة\s+القاضي\s+عياض|الرئاسة",
     "Présidence UCA", 10),
    (r"كلية\s+العلوم\s+القانونية\s+والاقتصادية\s+والاجتماعية|كلية\s+العلوم\s+القانونية",
     "FSJES Marrakech", 10),
    (r"كلية\s+العلوم\s+والتقنيات",
     "FST Marrakech", 10),
    (r"كلية\s+العلوم\s+السملالية|كلية\s+العلوم\s+سملالية",
     "FSS Semlalia", 10),
    (r"كلية\s+الطب\s+والصيدلة",
     "FMP Marrakech", 10),
    (r"كلية\s+الآداب\s+والعلوم\s+الإنسانية",
     "FLSH Marrakech", 10),
    (r"المدرسة\s+الوطنية\s+للعلوم\s+التطبيقية",
     "ENSA Marrakech", 10),
    (r"المدرسة\s+الوطنية\s+للتجارة\s+والتسيير",
     "ENCG Marrakech", 10),
    (r"الكلية\s+المتعددة\s+التخصصات.{0,20}?[آا]سفي|الكلية\s+المتعددة\s+التخصصات",
     "FP Safi", 10),
    (r"المدرسة\s+العليا\s+للتكنولوجيا.{0,15}?الصويرة",
     "EST Essaouira", 10),
    (r"المدرسة\s+العليا\s+للتكنولوجيا.{0,15}?[آا]سفي",
     "EST Safi", 10),
    (r"المركز\s+الجهوي\s+ل[لإا]*ستثمار",
     "CRI Marrakech-Safi", 10),
    (r"جامعة\s+القاضي\s+عياض",
     "Université Cadi Ayyad", 5),
]

# Titres hiérarchiques (émetteur possible)
TITRES_EMETTEUR = [
    (r"Le\s+Doyen\s+par\s+[Ii]nt[eé]rim", "Le Doyen par Intérim"),
    (r"Pour\s+le\s+Pr[eé]sident\s*[\n\r]+\s*Le\s+Vice[\s\-]?Pr[eé]sident", "Pour le Président, Le Vice-Président"),
    (r"Le\s+Vice[\s\-]?Pr[eé]sident", "Le Vice-Président"),
    (r"Le\s+Pr[eé]sident\b", "Le Président"),
    (r"La\s+Pr[eé]sidente\b", "La Présidente"),
    (r"Le\s+Directeur\s+G[eé]n[eé]ral", "Le Directeur Général"),
    (r"Le\s+Directeur\b", "Le Directeur"),
    (r"La\s+Directrice\b", "La Directrice"),
    (r"Le\s+Doyen\b", "Le Doyen"),
    (r"La\s+Doyenne\b", "La Doyenne"),
    (r"Le\s+Secr[eé]taire\s+G[eé]n[eé]ral", "Le Secrétaire Général"),
    # Arabes mappés vers FR
    (r"العميد\s+بالنيابة", "Le Doyen par Intérim"),
    (r"رئيس\s+الجامعة", "Le Président"),
    (r"نائب\s+رئيس\s+الجامعة", "Le Vice-Président"),
    (r"العميد\b", "Le Doyen"),
    (r"العميدة\b", "La Doyenne"),
    (r"المدير\s+العام", "Le Directeur Général"),
    (r"المدير\b", "Le Directeur"),
    (r"الأمين\s+العام", "Le Secrétaire Général"),
]


# ═══════════════════════════════════════════════════════════════════════════
# EXTRACTEUR
# ═══════════════════════════════════════════════════════════════════════════

class NLPExtractor:
    """Extracteur NLP robuste pour courriers UCA scannés."""

    def __init__(self, spacy_model: str = "fr_core_news_md"):
        self.nlp = None
        try:
            import spacy
            self.nlp = spacy.load(spacy_model)
            logger.info(f"spaCy chargé: {spacy_model}")
        except Exception as e:
            logger.warning(f"spaCy indisponible ({e}); fallback sur regex seul.")

    # ─── POINT D'ENTRÉE ────────────────────────────────────────────────────
    def extract_fields(self, text: str) -> dict:
        if not text:
            return {"fields": self._empty_fields(), "confidence": {}}

        norm = self._normalize(text)

        fields = {
            "numero":        self._extract_numero(norm, text),
            "date":          self._extract_date(norm),
            "objet":         self._extract_objet(norm),
            "expediteur":    self._extract_expediteur(norm, text),
            "destinataire":  self._extract_destinataire(norm),
            "type_document": self._extract_type(norm),
            "etablissement": self._extract_etablissement(norm),
            "corps":         self._extract_corps(norm, text),
        }
        confidence = {
            k: self._score_confidence(k, v, norm)
            for k, v in fields.items() if k != "corps"
        }
        return {"fields": fields, "confidence": confidence}

    def _empty_fields(self) -> dict:
        return {k: None for k in
                ("numero", "date", "objet", "expediteur",
                 "destinataire", "type_document", "etablissement", "corps")}

    def _zone_entete(self, text: str) -> str:
        markers = [
            r"\n\s*[AÀ]\s*\n\s*(?:Monsieur|Madame|Mesdames|Messieurs|MONSIEUR)",
            r"\n\s*إلى\s*\n",
            r"إلى\s*\n+\s*(?:السيد|السيدة|السيدتين|السادة|السيدات|الأستاذ|رؤساء|عمداء|مديري)",
            r"Objet\s*:",
            r"الموضوع\s*[:.]",
            r"ال[مم]و[ضصظط]و[عغ]\s*[:.]",
            r"[Vv]euillez\s+trouver\s+ci[\-\s]?joint",
            r"تجدون\s+طيه",
            r"نوع\s+المراسل",
            r"سلام\s+تام\s+بوجود",
            r"وبعد\s*[,،]?\s*\n",
        ]
        limite = len(text)
        for m in markers:
            found = re.search(m, text)
            if found and found.start() < limite:
                limite = found.start()
        return text[:max(800, min(limite + 200, 3000))]

    # ─── NORMALISATION ─────────────────────────────────────────────────────
    def _normalize(self, text: str) -> str:
        t = text
        t = t.replace("\u2019", "'").replace("\u2018", "'")
        t = t.replace("\u201C", '"').replace("\u201D", '"')
        t = re.sub(r"[\u2010-\u2015\u2212]", "-", t)

        nb_nl = t.count("\n")
        nb_multi_space = len(re.findall(r"  +", t))
        if nb_multi_space >= 3 and nb_multi_space > nb_nl:
            t = re.sub(r" {2,}", "\n", t)

        # Corrections OCR françaises communes
        # Correction années OCR : 2076→2026 (swap 0↔7), 7026→2026
        t = re.sub(r'\b20[6-9]6\b', '2026', t)
        t = re.sub(r'\b[6-9]026\b', '2026', t)
        # Correction 4YYYY (ex: 42026 → 2026 — préfixe '4' parasite)
        t = re.sub(r'(?<![\d])4(20[2-9]\d)\b', r'\1', t)
        t = re.sub(r"CADI\s+AW?A?Y?A?D", "CADI AYYAD", t, flags=re.IGNORECASE)
        t = re.sub(r"\bCRl[\s\-]", "CRI-", t)
        t = re.sub(r"\bN\s*['\"`´]\s*(?=[\s:.]*\d)", "N° ", t)
        t = re.sub(r"(\b\d{1,2}\s+)AR(\.|\\s)", r"\1AVR\2", t)
        # Fix v3 : variantes OCR du mois AVRIL — À/Â au lieu de A, "MR" / "AYR" / "AVA"
        t = re.sub(r"\b[ÀÂA][VY]R(?:IL)?\b", "AVR", t, flags=re.IGNORECASE)
        t = re.sub(r"\b(\d{1,2})\s+MR\.?\s+(20\d{2})\b", r"\1 AVR \2", t)
        # Fix v3 : '0 2 AVR' / '0 2 ÀVR' avec espaces parasites
        t = re.sub(r"\b(\d)\s+(\d)\s+(AVR|JAN|FEV|MAR|MAI|JUIN|JUIL|AOU|SEP|OCT|NOV|DEC)\b",
                   r"\1\2 \3", t, flags=re.IGNORECASE)
        t = re.sub(
            r"(\b(?:JAN|FEV|MAR|AVR|AOU|SEP|OCT|NOV|DEC|AVRI|AVRIL|FEVR|MARS|JUIN|JUIL|JUILLET|AOUT|SEPT|OCTOBRE|NOVEMBRE|DECEMBRE|janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\.?\s+)9(0\d{2})\b",
            r"\g<1>2\g<2>", t, flags=re.IGNORECASE,
        )

        # ─── CORRECTIONS OCR ARABES ──────────────────────────────────────
        # 1. ى/ي confusions
        t = re.sub(r"القاض[ى]\s+عياض", "القاضي عياض", t)
        t = re.sub(r"(?<=\s)إلي(?=\s)", "إلى", t)
        t = re.sub(r"(?<=\s)علي(?=\s)", "على", t)

        # 2. ة/ه (teh marbuta) — mots institutionnels
        # PAS de \b initial car les préfixes arabes (ال، وال، بال) collent au mot
        # ex: "الرئاسه" → \bرئاسه\b échoue car "ل" précède "ر"
        for wrong, right in [("رئاسه", "رئاسة"), ("جامعه", "جامعة"), ("كليه", "كلية"),
                               ("مدرسه", "مدرسة"), ("مدينه", "مدينة"), ("لجنه", "لجنة"),
                               ("رسالـ?ه", "رسالة")]:
            t = re.sub(wrong + r"\b", right, t)

        # 3. ض/ص/ظ/ذ confusions
        t = re.sub(r"\bعيا[دظذ]\b", "عياض", t)
        t = re.sub(r"\bالموضوغ\b", "الموضوع", t)
        t = re.sub(r"\bالموصوع\b", "الموضوع", t)
        t = re.sub(r"\bالموظوع\b", "الموضوع", t)

        # 4. همزة manquante
        for wrong, right in [("ابريل", "أبريل"), ("اكتوبر", "أكتوبر"),
                               ("اغسطس", "أغسطس"), ("استاذ", "أستاذ")]:
            t = re.sub(r"\b" + wrong + r"\b", right, t)

        # 5. و/ؤ et ي/ئ rares
        t = re.sub(r"\bرئاسئ\b", "رئاسة", t)

        # 6. Chiffres arabes/indiens → 0-9
        t = t.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
        t = t.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))

        # 7. Tatweel (kashida)
        t = re.sub(r"ـ+", "", t)

        # 8. Diacritiques (harakat)
        t = re.sub(r"[ً-ٰٟ]", "", t)

        # 9. Ligatures arabes rares
        t = t.replace("﷽", "بسم الله الرحمن الرحيم")

        # 10. Ponctuation arabe
        t = re.sub(r"\s*،\s*", "، ", t)
        t = re.sub(r"\s*؛\s*", "؛ ", t)
        t = re.sub(r"\s*؟\s*", "؟ ", t)

        # Nettoyage général
        t = re.sub(r"^[\s\-_.=·•]+$", "", t, flags=re.MULTILINE)
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n{4,}", "\n\n\n", t)
        return t

    # ─── CACHET D'ARRIVÉE PRÉSIDENCE ───────────────────────────────────────
    def _find_cachet_zone(self, norm: str) -> Optional[str]:
        def _has_cachet_markers(zone: str) -> bool:
            has_date = bool(re.search(
                r"\d\s*\d?\s*\d?\s+(?:AVR|AVRIL|JAN|JANVIER|FEV|FEVRIER|"
                r"MAR|MARS|MAI|JUIN|JUIL|JUILLET|AOU|AOUT|SEP|SEPTEMBRE|"
                r"OCT|OCTOBRE|NOV|NOVEMBRE|DEC|DECEMBRE|Avri|Avril|ÀVR)"
                r"\.?\s*,?\s*(?:\d{4}|IR|iR|I[RN])?",
                zone, re.IGNORECASE,
            ))
            has_markers = bool(re.search(
                r"Arriv[eé]e?\s+(?:le|ie|1e|Je|[il]e?)\b|"
                r"S[oc0]us\s+[NhHn][°ºoO'\"]?|"
                r"S[ce]us\s+[NhHn]|"
                r"ورد\s+يوم|رقم",
                zone, re.IGNORECASE,
            ))
            return has_date or has_markers

        for m in re.finditer(
            r"PR[EÉ]SIDENCE\s+DE\s+L[''`´\s]*UN\w*[\s\S]{0,80}?"
            r"CADI\s+AYY?A[DP][\s\S]{0,50}?MAR\w*",
            norm, re.IGNORECASE,
        ):
            start = max(0, m.start() - 50)
            end = min(len(norm), m.end() + 400)
            zone = norm[start:end]
            if _has_cachet_markers(zone):
                return zone

        # Fix v3 : OCR fragmenté — "PRESIDENCE DE LUN" sur une ligne,
        # "CADI AYYAD ' MAR" sur la suivante, avec bruit entre les deux
        for m in re.finditer(
            r"PR[EÉ]SIDENCE\s+DE\s+L\w{0,5}\b[\s\S]{0,150}?"
            r"CADI\s+AYY?A[DP\b][\s\S]{0,40}?MAR\b",
            norm, re.IGNORECASE,
        ):
            start = max(0, m.start() - 50)
            end = min(len(norm), m.end() + 500)
            zone = norm[start:end]
            if _has_cachet_markers(zone):
                return zone

        for m in re.finditer(
            r"CADI\s+AYY?A[DP]\s*[\-',]?\s*MAR\w*",
            norm, re.IGNORECASE,
        ):
            start = max(0, m.start() - 200)
            end = min(len(norm), m.end() + 400)
            zone = norm[start:end]
            if re.search(r"Royaume\s+du\s+Maroc|La\s+Pr[eé]sidence\b(?!\s+de\s+l)|Code\s*:",
                         zone, re.IGNORECASE):
                continue
            zone_apres = norm[m.end():min(len(norm), m.end() + 300)]
            if _has_cachet_markers(zone_apres):
                return zone

        for m in re.finditer(r"PR[EÉ]SIDENCE\s+DE\s+L[''`´\s]*UN\w*", norm, re.IGNORECASE):
            zone_apres = norm[m.end():min(len(norm), m.end() + 300)]
            if _has_cachet_markers(zone_apres):
                start = max(0, m.start() - 50)
                end = min(len(norm), m.end() + 400)
                return norm[start:end]

        for m in re.finditer(
            r"ر[ئي]اس[ةه]\s+جامع[ةه]\s+القاض[ىي]\s+عياض|"
            r"الرئاسة\s+جامع[ةه]\s+القاض[ىي]",
            norm,
        ):
            start = max(0, m.start() - 50)
            end = min(len(norm), m.end() + 400)
            zone = norm[start:end]
            if _has_cachet_markers(zone):
                return zone

        m = re.search(
            r"Arriv[eé]e?\s+le[\s\S]{0,150}?Sous\s+N[°ºoO'\"]?",
            norm, re.IGNORECASE,
        )
        if m:
            return norm[max(0, m.start() - 200):min(len(norm), m.end() + 200)]

        m = re.search(r"ورد\s+يوم[\s\S]{0,150}?رقم", norm)
        if m:
            return norm[max(0, m.start() - 200):min(len(norm), m.end() + 200)]

        return None

    def _extract_from_cachet(self, cachet_zone: str) -> tuple:
        numero = None
        date = None

        # Pattern simple — groupes FIXES : (d1)(d2)?(d3)?(mois)(année)?
        # isdigit() évite que le mois glisse dans jour_raw si grp déborde
        m = re.search(
            r"(\d)\s*(\d)?\s*(\d)?\s+"
            r"(AVR|AVRIL|JAN|JANVIER|FEV|FEVRIER|MAR|MARS|MAI|JUIN|JUIL|JUILLET|"
            r"AOU|AOUT|SEP|SEPTEMBRE|OCT|OCTOBRE|NOV|NOVEMBRE|DEC|DECEMBRE|"
            r"Avri|Avril|Jan|Fev|Mar|Mai|Juin|Juil|Aou|Sep|Oct|Nov|Dec|AVR)"
            r"\.?\s*,?\s*(\d{4}|IR|iR|I[RN])?",
            cachet_zone, re.IGNORECASE,
        )
        if m:
            jour_raw = "".join(g for g in (m.group(1), m.group(2), m.group(3)) if g and g.isdigit())
            if len(jour_raw) > 2:
                for candidate in (jour_raw[-2:], jour_raw[:2], jour_raw[1:]):
                    try:
                        if 1 <= int(candidate) <= 31:
                            jour_raw = candidate
                            break
                    except ValueError:
                        continue
            jour_int = int(jour_raw) if jour_raw.isdigit() else 0
            g4 = m.group(4)
            g5 = m.group(5)
            if 1 <= jour_int <= 31:
                mois = self._normaliser_mois(g4)
                annee_raw = g5 or ""
                if annee_raw and annee_raw.isdigit() and 2000 <= int(annee_raw) <= 2099:
                    annee = annee_raw
                else:
                    m_year = re.search(r"\b(20\d{2})\b", cachet_zone)
                    annee = m_year.group(1) if m_year else "2026"
                if mois:
                    date = f"{str(jour_int).zfill(2)} {mois} {annee}"

        # Numéro — stratégie 1
        m = re.search(
            r"(?:Arriv[eé]e?\s+(?:le|ie|1e|Je|[il]e?)|ورد\s+يوم)[:.\\s]*([^\n]{1,60})",
            cachet_zone, re.IGNORECASE,
        )
        if m:
            zone_ascii = re.sub(r"[\u0660-\u0669\u06F0-\u06F9]", "", m.group(1))
            digits = re.sub(r"[^\d]", "", zone_ascii)
            if 3 <= len(digits) <= 6:
                numero = digits.lstrip("0") or digits

        # Stratégie 1b : Sous N
        if not numero:
            m_sous = re.search(
                r"S[oc0]us\s+[NhHn][\u00b0\u00ba oO]?\s*[.\s]*\n?\s*([^\n]{1,40})",
                cachet_zone, re.IGNORECASE,
            )
            if m_sous:
                zone_ascii = re.sub(r"[\u0660-\u0669\u06F0-\u06F9]", "", m_sous.group(1))
                if not re.match(r"^[\s.\-_]+$", zone_ascii):
                    digits = re.sub(r"[^\d]", "", zone_ascii)
                    if 3 <= len(digits) <= 6:
                        numero = digits.lstrip("0") or digits

        # Stratégie 1c : arabes ورد يوم / رقم (ordre RTL variable)
        if not numero:
            for ar_pat in [
                r"ورد\s+يوم\s*[:.]?\s*([^\n]{1,30})",
                r"رقم\s*[:.]?\s*([^\n]{1,30})",
            ]:
                m_ar = re.search(ar_pat, cachet_zone)
                if m_ar:
                    z = re.sub(r"[\u0660-\u0669\u06F0-\u06F9]", "", m_ar.group(1))
                    d = re.sub(r"[^\d]", "", z)
                    if 3 <= len(d) <= 6 and d not in ("2025", "2026", "2027"):
                        numero = d.lstrip("0") or d
                        break

        # Stratégie 2 : bloc 4-5 chiffres espacés
        if not numero:
            marker_match = re.search(
                r"Arriv[eé]e?\s+(?:le|ie|1e|Je|[il]e?)\b|ورد\s+يوم",
                cachet_zone, re.IGNORECASE,
            )
            if marker_match:
                start_win = max(0, marker_match.start() - 80)
                end_win = min(len(cachet_zone), marker_match.end() + 80)
                near_zone = cachet_zone[start_win:end_win]
                near_zone = re.sub(r"\b\d{2,4}[\s\-]\d{2,3}[\s\-]\d{2,3}[\s\-]\d{2,3}\b", " " * 20, near_zone)
                near_zone = re.sub(r"\b[BD]\.?\s*[PÉé]\.?\s*[:.]?\s*\d+\b", " " * 15, near_zone, flags=re.IGNORECASE)
                near_zone = re.sub(r"\b20(?:2[5-7])\b", "    ", near_zone)
                candidats = []
                for mm in re.finditer(r"(?:\d\s*){3,6}(?!\d*[/\-])", near_zone):
                    txt = mm.group(0)
                    digits = re.sub(r"\s", "", txt)
                    if digits in ("2025", "2026", "2027") or not (3 <= len(digits) <= 5):
                        continue
                    candidats.append((digits, mm.start()))
                if candidats:
                    candidats.sort(key=lambda x: (-len(x[0]), x[1]))
                    numero = candidats[0][0].lstrip("0") or candidats[0][0]

        # Stratégie 3 : رقم direct
        if not numero:
            m = re.search(r"رقم\s*[:.]?\s*([^\n]{1,40})", cachet_zone)
            if m:
                digits = re.sub(r"[^\d]", "", re.sub(r"[\u0660-\u0669\u06F0-\u06F9]", "", m.group(1)))
                if 3 <= len(digits) <= 6:
                    numero = digits.lstrip("0") or digits

        return numero, date

    # ─── NUMERO ────────────────────────────────────────────────────────────
    def _extract_numero(self, norm: str, raw: str) -> Optional[str]:
        # PRIORITÉ : cachet d'arrivée
        cachet = self._find_cachet_zone(norm)
        if cachet:
            numero_cachet, _ = self._extract_from_cachet(cachet)
            if numero_cachet:
                return numero_cachet
            # Fix v3: NE PAS court-circuiter si le cachet n'a rien donné
            # (OCR trop dégradé) — laisser les patterns classiques tenter

        # FALLBACK : patterns classiques
        candidates = []

        # (1) "Code : 221 / XXXX" — Présidence UCA
        # Cherche d'abord le numéro encadré (=NNNN-) dans les 100 chars après "Code"
        m_code = re.search(r"[Cc]ode\s*[:.]?\s*(\d{2,4})\s*/", norm)
        if m_code:
            code_num = m_code.group(1)
            # Zone de 200 chars après "Code :" pour trouver l'ID arrivée
            zone_code = norm[m_code.start():min(len(norm), m_code.end() + 200)]
            # Chercher numéro encadré =NNNN- ou \u202bNNN (bidi)
            m_enc = re.search(r"[=_\[]\s*(\d{3,5})\s*[=_\]\-]", zone_code)
            if m_enc:
                candidates.append((f"{code_num}/{m_enc.group(1)}", 96))
            else:
                # Fallback: chercher 4 chiffres != année dans la zone
                m_enc2 = re.search(r"(?<!\d)(\d{4})(?!\d)", zone_code)
                if m_enc2 and m_enc2.group(1) not in ("2025", "2026", "2027"):
                    candidates.append((f"{code_num}/{m_enc2.group(1)}", 95))
        m = re.search(
            r"[Cc]ode\s*[:.]?\s*(\d{2,4})\s*/[\s\S]{0,40}?[=\-\s]*(\d{4})[\s=\-]",
            norm,
        )
        if m and m.group(2) not in ("2025", "2026", "2027"):
            candidates.append((f"{m.group(1)}/{m.group(2)}", 90))

        # (2) N° NNNNNN/YY/INST
        m = re.search(
            r"N[°ºoO'\"]\\s*[:.]?\\s*([\d\s]{3,10})[\s/\-]+(\d{2})[\s/\-]+([A-Z]{2,5}[\-\s]?[A-Z]{2,5})",
            norm,
        )
        if m:
            num = re.sub(r"\s+", "", m.group(1)).lstrip("0") or "0"
            candidates.append((f"{num.zfill(6)}/{m.group(2)}/{m.group(3).replace(' ', '-')}", 90))

        # (2bis) version brute
        m = re.search(
            r"(?:N[°ºoO'\"]|Ng[\s\.\d]{0,20})\s*[:.\s]*[\s\w\.]{0,10}(\d{4,6})\s*/\s*(\d{2})[\s/\-]+([A-Z]{2,5}[\-\s]?[A-Z]{2,5})",
            raw,
        )
        if m and not candidates:
            num = m.group(1).lstrip("0")
            candidates.append((f"{num.zfill(6)}/{m.group(2)}/{m.group(3).replace(' ', '-')}", 80))

        # (3) N° NNN/YY
        for p in [
            r"N[°ºoO'\"]\s*[:.]?\s*(\d{2,5})\s*/\s*(\d{2,4})\b",
            r"[Rr][eé]f[eé]?r[eé]?nc[eé]?\s*[:.]?\s*(\d{2,5})\s*/\s*(\d{2,4})",
        ]:
            m = re.search(p, norm)
            if m:
                candidates.append((f"{m.group(1)}/{m.group(2)}", 85))
                break

        # (4) Arabe رقم NNN/NNNN
        m = re.search(
            r"رقم\s*[:.]?\s*[/\\]?\s*(\d{2,4})[\s/\\]{0,10}[=\-_]?\s*(\d{2,5})",
            norm,
        )
        if m and len(m.group(2)) >= 3:
            candidates.append((f"{m.group(1)}/{m.group(2)}", 85))
        else:
            m2 = re.search(
                r"رقم\s*[:.]?\s*/\s*(\d{2,4})[\s.]{0,30}[=\-]\s*(\d{3,5})[=\-]?",
                norm,
            )
            if m2:
                candidates.append((f"{m2.group(1)}/{m2.group(2)}", 85))
            else:
                m3 = re.search(r"رقم\s*[:.]?\s*[/\\]?\s*(\d{3,5})", norm)
                if m3:
                    candidates.append((m3.group(1), 60))

        # (4b) العدد (numérotation arabe alternative)
        m = re.search(r"العدد\s*[:.]?\s*(\d{3,6})\s*[/\\\-]\s*(\d{2,4})", norm)
        if m:
            candidates.append((f"{m.group(1)}/{m.group(2)}", 75))

        # (4c) Présidence AR: "رقم: /220 =2 4 4 3-=" — chiffres espacés
        m_sp = re.search(
            r"رقم\s*[:.]?\s*/\s*(\d{2,4})[^\n\d]{0,25}([\d][\d\s]{2,10}[\d])[=\-]",
            norm)
        if m_sp:
            d2 = re.sub(r"\s", "", m_sp.group(2))
            if d2.isdigit() and 3 <= len(d2) <= 6:
                candidates.append((f"{m_sp.group(1)}/{d2}", 88))

        # (5) Numéros encadrés =NNNN-
        zone_entete_tmp = self._zone_entete(norm)
        m = re.search(r"[=_\[]\s*(\d{4,5})\s*[=_\]\-]", zone_entete_tmp)
        if m and not candidates:
            candidates.append((m.group(1), 60))

        # (6) N° isolé en zone entête
        zone_entete = self._zone_entete(norm)
        m = re.search(
            r"(?:N[°ºoO'\"]\s*[:.]?\s*|رقم\s*[:.]?\s*)[\s\n]*(\d{3,5})\b(?!\s*/)",
            zone_entete,
        )
        if m:
            candidates.append((m.group(1), 70))

        # (6bis) Nombre isolé sur ligne avant "Monsieur le Président/Doyen..."
        m = re.search(
            r"\n\s*(\d{3,5})\s*\n"
            r"(?:[^\n]{0,25}\n){0,3}"
            r"[^\n]{0,30}(?:Monsieur|Madame|MONSIEUR|MADAME)\s+(?:le|la|LE|LA)\s+"
            r"(?:Pr[eé]sident|Doyen|Directeur)",
            norm,
        )
        if m:
            candidates.append((m.group(1), 82))

        # (6ter) V---NNN (OCR arabe, bordereau)
        m = re.search(r"V\s*[\-\s]+(\d)\s*(\d)\s*(\d)\b", norm)
        if m:
            num = "".join(m.groups())
            if 100 <= int(num) <= 9999:
                candidates.append((num, 80))

        # (7) NNN/26
        m = re.search(r"\b(\d{3,5})\s*/\s*(?:20)?26\b", zone_entete)
        if m and not candidates:
            candidates.append((f"{m.group(1)}/26", 65))

        # (8) NNN/FSJES etc.
        # Fix v3: refuser si le numéro est précédé immédiatement par un point/chiffres
        # de bruit (ex: "g.?...9236/CRI-RMS" → 9236 est un artefact OCR)
        m = re.search(
            r"(?:^|[\s\n])(\d{3,6})\s*/\s*(CRI[\s\-]?RMS|FSJES|FSSM?|FST|FPS|ESTE?|UCAM?)\b",
            norm, re.IGNORECASE,
        )
        if m and not candidates:
            num = m.group(1).lstrip("0") or "0"
            # Vérification anti-bruit: max 4 chiffres pour un numéro non-encadré
            if len(num) <= 4:
                inst = m.group(2).upper().replace(" ", "-")
                candidates.append((f"{num.zfill(6)}/26/{inst}", 55))

        if not candidates:
            return None
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]

    # ─── DATE ──────────────────────────────────────────────────────────────
    def _extract_date(self, text: str) -> Optional[str]:
        cachet = self._find_cachet_zone(text)
        if cachet:
            _, date_cachet = self._extract_from_cachet(cachet)
            if date_cachet:
                return date_cachet
            # Fix v3: NE PAS court-circuiter si le cachet n'a rien donné

        zone = self._zone_entete(text)
        reste = text[len(zone):]
        for z in (zone, reste):
            d = self._find_date_in(z)
            if d:
                return d
        return None

    def _find_date_in(self, text: str) -> Optional[str]:
        # (1) Date arabe — avec validation année et jour
        m = re.search(
            r"(\d{1,2})\s+(" + _MOIS_AR_REGEX + r")\s+(\d{4})",
            text,
        )
        if m:
            mois_fr = MOIS_AR.get(m.group(2))
            annee_ar = m.group(3)
            jour_ar = int(m.group(1))
            # Corriger les années OCR fréquentes : 4202→ne pas capturer, 42026→2026
            if mois_fr and 2000 <= int(annee_ar) <= 2099 and 1 <= jour_ar <= 31:
                return f"{str(jour_ar).zfill(2)} {mois_fr} {annee_ar}"

        # (2) Date textuelle française avec espaces bruités
        for m in re.finditer(
            r"(\d)\s*(\d)?\s*(\d)?\s+([A-Za-zÀ-ÿ]{3,12})\.?\s*,?\s*(\d{4})",
            text,
        ):
            context_avant = text[max(0, m.start() - 50):m.start()].lower()
            if re.search(r"\b(du|envoi\s+n|suite\s+à|[eé]diter|imprim)\s*$", context_avant):
                continue
            # Ignorer les dates d'heure (rendez-vous dans le corps de lettre)
            context_apres = text[m.end():min(len(text), m.end() + 30)]
            if re.search(r"\s+à\s+\d{1,2}h|\s+à\s+\d{2}:\d{2}", context_apres):
                continue
            context_proche = (text[max(0, m.start() - 80):m.start()] +
                              text[m.end():min(len(text), m.end() + 80)])
            if re.search(r"Arriv[eé]e?\s+le|Sous\s+N[°ºoO'\"]?|ورد\s+يوم",
                         context_proche, re.IGNORECASE):
                continue
            if re.search(
                r"PR[EÉ]SIDENCE\s+DE\s+L[''']?UNIVERSIT[EÉ][\s\S]{0,80}$",
                text[max(0, m.start() - 80):m.start()], re.IGNORECASE,
            ):
                continue
            jour_raw = "".join(g for g in (m.group(1), m.group(2), m.group(3)) if g)
            jour_int = int(jour_raw)
            if not (1 <= jour_int <= 31):
                continue
            mois = self._normaliser_mois(m.group(4))
            annee = m.group(5)
            if mois and 2000 <= int(annee) <= 2099:
                return f"{str(jour_int).zfill(2)} {mois} {annee}"

        # (3) "le 15 avril 2026" — avec filtres Editer et rendez-vous
        for m in re.finditer(
            r"(?:le|Le)\s*[:.]?\s*(\d{1,2})\s+(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre)\s+(\d{4})",
            text, re.IGNORECASE,
        ):
            ctx_av = text[max(0, m.start() - 50):m.start()].lower()
            if re.search(r"\b(du|suite\s+à|[eé]diter)\b", ctx_av):
                continue
            ctx_ap = text[m.end():min(len(text), m.end() + 30)]
            if re.search(r"\s+à\s+\d{1,2}h|\s+à\s+\d{2}:\d{2}", ctx_ap):
                continue
            return f"{m.group(1).zfill(2)} {m.group(2).lower()} {m.group(3)}"

        # (4) Format numérique
        for m in re.finditer(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b", text):
            context_avant = text[max(0, m.start() - 30):m.start()].lower()
            if re.search(r"\b(du|envoi\s+n|suite\s+à|réf)\s*$", context_avant):
                continue
            j, mo, a = m.groups()
            if 1 <= int(mo) <= 12 and 1 <= int(j) <= 31 and 2000 <= int(a) <= 2099:
                return f"{j.zfill(2)} {MOIS_NUM[int(mo)]} {a}"

        return None

    def _normaliser_mois(self, raw: str) -> Optional[str]:
        import unicodedata
        u = "".join(
            c for c in unicodedata.normalize("NFD", raw.upper().rstrip('.').strip())
            if unicodedata.category(c) != "Mn"
        )
        if u in MOIS_FR:
            return MOIS_FR[u]
        for k, v in MOIS_FR.items():
            if len(u) >= 3 and u.startswith(k[:3]):
                return v
        if raw in MOIS_AR:
            return MOIS_AR[raw]
        if raw.lower() in MOIS_NUM:
            return raw.lower()
        return None

    # ─── OBJET ─────────────────────────────────────────────────────────────
    def _extract_objet(self, text: str) -> Optional[str]:
        objet_word = r"[_\*\[\]\s]*(?:OBJET|[O0Ø][bB][jJiI][eE][tTlL])[_\*\[\]\s]*"
        separator = r"\s*[:;.,\-=]\s*"

        # (1) Multi-lignes
        m = re.search(
            rf"(?:^|\n|[\.\\!\\?]\s+){objet_word}{separator}(.+?)"
            rf"(?:\n\n|\n\s*(?:Monsieur|Madame|Mesdames|Messieurs|Cher|· |\* )|$)",
            text, re.IGNORECASE | re.DOTALL,
        )
        if m:
            cand = self._nettoyer_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        # (2) Ligne unique
        m = re.search(
            rf"(?:^|\n){objet_word}{separator}(.+?)(?:\n|$)",
            text, re.MULTILINE | re.IGNORECASE,
        )
        if m:
            cand = self._nettoyer_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        # (2b) Milieu de ligne (texte aplati)
        m = re.search(
            rf"(?:CADI\s+AYYAD|UNIVERSIT[EÉ]|Cher|Madame|Monsieur)\s+"
            rf"{objet_word}{separator}(.+?)(?:\n|$)",
            text, re.IGNORECASE,
        )
        if m:
            cand = self._nettoyer_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        # (2c) Concerne / Concernant
        m = re.search(
            r"(?:^|\n)\s*[_\*]*\s*[Cc]oncern(?:e|ant)[_\*]*\s*[:;.\-]\s*(.+?)(?:\n|$)",
            text, re.MULTILINE,
        )
        if m:
            cand = self._nettoyer_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        # (3) Arabe : الموضوع multi-lignes
        m = re.search(
            r"ال[مم]و[ضصظط]و[عغ]\s*[:.]?\s*(.+?)"
            r"(?:\n\n|\n\s*(?:سلام|وبعد|في\s+إطار|بناء\s+على|نتشرف|يشرفنا))",
            text, re.DOTALL,
        )
        if m:
            cand = self._nettoyer_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        # (3b) Arabe ligne unique
        m = re.search(r"ال[مم]و[ضصظط]و[عغ]\s*[:.]?\s*(.+?)(?:\n|$)", text)
        if m:
            cand = self._nettoyer_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        # (4) Bordereau FR — Veuillez trouver ci-joint
        m = re.search(
            r"[Vv]euillez\s+trouver\s+ci[\-\s]?joint\s*[,:.]?\s*\n((?:[^\n]*(?:\n|$)){1,8})",
            text,
        )
        if m:
            rejeter = ("nature", "nombre", "observations", "observation", "pièces",
                       "pieces", "atoute", "a toute", "en retour", "pour attribution",
                       "président :", "directeur :", "doyen :", "email", "tél", "tel",
                       "fax", "site web", "http", "editer", "éditer", "avenue", "av ")
            lignes_brutes = m.group(1).split("\n")
            for idx, l in enumerate(lignes_brutes):
                cand = self._nettoyer_objet(l)
                if not cand or len(cand) < 6:
                    continue
                if sum(c.isalpha() for c in cand) < 4:
                    continue
                if any(cand.lower().startswith(r) for r in rejeter):
                    continue
                if re.match(r"^\d+\s*$", cand.strip()):
                    continue
                nb_digits = sum(c.isdigit() for c in cand)
                if nb_digits > sum(c.isalpha() for c in cand):
                    continue
                # Fix v3: si l'objet finit par ':' chercher le bénéficiaire à la ligne suivante
                if cand.rstrip().endswith(":") and idx + 1 < len(lignes_brutes):
                    next_l = self._nettoyer_objet(lignes_brutes[idx + 1])
                    if next_l and len(next_l) >= 3 and sum(c.isalpha() for c in next_l) >= 3:
                        # Refuser si la ligne suivante est un autre item (commence par marqueur)
                        if not any(next_l.lower().startswith(r) for r in rejeter):
                            cand = cand.rstrip(": ").rstrip() + " : " + next_l
                return cand

        # (5) Arabe : تجدون طيه
        m = re.search(r"تجدون\s+طيه\s*[:.]?\s*\n+\s*(.+?)(?:\n\n|$)", text, re.DOTALL)
        if m:
            cand = self._nettoyer_objet(m.group(1))
            if cand and len(cand) > 5:
                return cand

        # (5b) ورقة الإرسال
        mots_doc_ar = (
            r"شهادة|طلب|استمارة|دبلوم|قائمة|برنامج|وثيقة|محضر|تقرير"
            r"|مراسلة|مذكرة|اتفاقية|عقد|ملف|بطاقة|نسخة|صورة|تقديم|إشعار"
        )
        m = re.search(
            r"ورقة\s+الإرسال[\s\S]{0,300}?(" + mots_doc_ar + r")[^\n]{5,200}",
            text,
        )
        if m:
            start = m.start(1)
            end_line = text.find("\n", start)
            ligne = text[start:end_line if end_line > 0 else start + 200]
            cand = self._nettoyer_objet(ligne)
            if cand and len(cand) > 8:
                return cand

        # (6) Bordereau sans "Veuillez trouver ci-joint" (OCR dégradé)
        m = re.search(
            r"[Bb]ordereau\s+d[''']?envoi[\s\S]{0,200}?"
            r"((?:Demande|Envoi|Transmission|Formulaire|Dossier|Copie|Liste|Diplôme|Convention|Programme|Nomination|Rapport)"
            r"[^\n]{8,200})",
            text,
        )
        if m:
            cand = self._nettoyer_objet(m.group(1))
            if cand and len(cand) > 8 and sum(c.isalpha() for c in cand) >= 8:
                return cand

        # (7) Nature | Nombre | Observations (tableau bordereau ESTE)
        m = re.search(
            r"(?:Nature|Nombre|Observations)[^\n]*\n"
            r"(?:[^\n]{0,50}\n){0,3}"
            r"([^\n]{15,200})",
            text,
        )
        if m:
            cand = self._nettoyer_objet(m.group(1))
            if cand and len(cand) > 10:
                nb_alpha = sum(c.isalpha() for c in cand)
                if nb_alpha >= 10 and not re.match(
                    r"(?:Nature|Nombre|Obs|Pour|En retour|Suite)", cand, re.IGNORECASE
                ):
                    return cand

        return None

    def _nettoyer_objet(self, raw: str) -> Optional[str]:
        s = raw.strip()
        s = re.sub(r"^[_\-=:*\s\|\.]+", "", s)
        s = re.sub(r"[_\-=\s]+$", "", s)
        s = re.sub(r"\s+", " ", s)
        return s if len(s) > 3 else None

    # ─── EXPÉDITEUR ────────────────────────────────────────────────────────
    def _extract_expediteur(self, norm: str, raw: str) -> Optional[str]:
        # 1. Patterns spécifiques UCA — priorité absolue
        m = re.search(
            r"Doyen\s*[:.,]?\s*par\s*[\"']?\s*[Ii]nt[eé]rim\s+de\s+la\s+[Ff]acult[eé]\s+des\s+Sciences[\s\S]{0,200}?Sociales",
            norm, re.DOTALL,
        )
        if m:
            t = m.group(0)
            parts = ["Le Doyen par Intérim de la faculté des Sciences"]
            sous = []
            if re.search(r"[Jj]uridiques?", t): sous.append("Juridiques")
            if re.search(r"[EÉé]conomiques?", t): sous.append("Economiques")
            if re.search(r"[Ss]ociales?", t): sous.append("et Sociales")
            if sous:
                # Fix v3: "Juridiques, Economiques, et Sociales" (virgule oxford courante UCA)
                if len(sous) >= 3:
                    parts.append(", ".join(sous[:-1]) + ", " + sous[-1])
                elif len(sous) == 2:
                    parts.append(sous[0] + " " + sous[1])
                else:
                    parts.append(sous[0])
            return " ".join(parts).replace("  ", " ")

        m = re.search(r"Le\s+Doyen\s+de\s+la\s+[Ff]acult[eé]\s+des\s+Sciences\s+Semlalia", norm)
        if m: return "Le Doyen de la Faculté des Sciences Semlalia"

        m = re.search(r"Le\s+Doyen\s+de\s+la\s+[Ff]acult[eé]\s+des\s+Sciences\s+et\s+Techniques", norm)
        if m: return "Le Doyen de la Faculté des Sciences et Techniques - Marrakech"

        m = re.search(r"Le\s+Doyen\s+de\s+la\s+[Ff]acult[eé]\s+de\s+M[eé]decine\s+et\s+de\s+Pharmacie", norm)
        if m: return "Le Doyen de la Faculté de Médecine et de Pharmacie - Marrakech"

        m = re.search(r"Le\s+Doyen\s+de\s+la\s+[Ff]acult[eé]\s+des\s+Lettres", norm)
        if m: return "Le Doyen de la Faculté des Lettres et des Sciences Humaines - Marrakech"

        m = re.search(
            r"LE\s+DIRECTEUR\s+DU\s+CENTRE\s+REGIONAL\s+D['''\s]\s*INVESTISSEMENT\s+DE\s+MARRAKECH[\s\-]SAFI",
            norm, re.IGNORECASE,
        )
        if m: return "Le Directeur du CRI Marrakech-Safi"

        if re.search(r"[EÉ]cole\s+Sup[eé]rieure\s+de\s+Technologie.{0,20}?Essaouira|ESTE\b", norm[:1000], re.IGNORECASE):
            if re.search(r"Le\s+Directeur\b", norm[:2000]):
                return "Le Directeur de l'EST Essaouira"

        if re.search(r"[EÉ]cole\s+Nationale\s+des\s+Sciences\s+Appliqu[eé]es|ENSA\b", norm[:1000], re.IGNORECASE):
            if re.search(r"Le\s+Directeur\b", norm[:2000]):
                return "Le Directeur de l'ENSA Marrakech"

        if re.search(r"[EÉ]cole\s+Nationale\s+de\s+Commerce\s+et\s+de\s+Gestion|ENCG\b", norm[:1000], re.IGNORECASE):
            if re.search(r"Le\s+Directeur\b", norm[:2000]):
                return "Le Directeur de l'ENCG Marrakech"

        # ─── Patterns arabes ────────────────────────────────────────────
        if re.search(r"من\s+السيد\s+رئيس\s+الجامعة", norm):
            return "Le Président de l'Université Cadi Ayyad"

        m = re.search(
            r"من\s*\n*\s*(?:السيد|السيدة|الأستاذ|الدكتور)?\s*"
            r"(عميد|مدير|رئيس|نائب\s+رئيس)\s+"
            r"([^\n]{5,150})",
            norm,
        )
        if m:
            titre_ar = re.sub(r"\s+", " ", m.group(1)).strip()
            inst_ar = m.group(2).strip()
            return f"{titre_ar} {inst_ar}"

        m = re.search(r"(عميد\s+كلية\s+العلوم[^\n]{0,80})", norm)
        if m: return re.sub(r"\s+", " ", m.group(1)).strip()

        if re.search(r"رئيس\s+الجامعة", norm[:1500]) and re.search(
            r"رئاسة|الرئاسة|جامعة\s+القاضي\s+عياض", norm[:1500]
        ):
            return "Le Président de l'Université Cadi Ayyad"

        # 2. Fallback générique : titre + institution
        haut = norm[:1500]
        is_presidence_emettrice = bool(
            re.search(
                r"(?:Royaume\s+du\s+Maroc\s+)?[^\n]*Universit[eé]\s+Cadi\s+Ayyad.{0,60}?La\s+Pr[eé]sidence",
                haut, re.IGNORECASE,
            )
            or re.search(r"^\s*La\s+Pr[eé]sidence\s*$", haut, re.MULTILINE | re.IGNORECASE)
        )

        destinataire_match = re.search(
            r"(?:^|\n)\s*(?:[AÀ]\s*[\n\s]+(?:Monsieur|Madame|Mesdames|Messieurs)|"
            r"إلى\s*[\n\s]+(?:السيد|السيدة|السيدتين|السادة|السيدات|الأستاذ|رؤساء|عمداء|مديري))",
            norm,
        )
        zone_expediteur = (
            norm[:destinataire_match.start()] if destinataire_match else norm[:1500]
        )

        institution = None
        if not is_presidence_emettrice:
            best_prio = -1
            for pattern, nom, priorite in INSTITUTIONS:
                if re.search(pattern, zone_expediteur, re.IGNORECASE):
                    if priorite > best_prio:
                        institution = nom
                        best_prio = priorite

        titre = None
        for pattern, nom in TITRES_EMETTEUR:
            if re.search(pattern, zone_expediteur):
                titre = nom
                break

        # Inférer le titre depuis le type d'institution si manquant
        if not titre and institution:
            inst_up = institution.upper()
            if any(k in inst_up for k in ("FST", "FSS", "FSJES", "FMP", "FLSH")):
                titre = "Le Doyen"
            elif any(k in inst_up for k in ("EST", "CRI", "ENSA", "ENCG")):
                titre = "Le Directeur"
            elif "PRÉSIDENCE" in inst_up or "PRESIDENCE" in inst_up:
                titre = "Le Président"

        parts = [p for p in (titre, institution) if p]
        if parts:
            return " — ".join(parts)

        # 3. Déduction depuis établissement
        etab = self._extract_etablissement(norm)
        if etab:
            if any(etab.startswith(p) for p in ("FST-", "FSS-", "FSJES-", "FMP-", "FLSH-")):
                return "Le Doyen"
            if any(etab.startswith(p) for p in ("EST-", "CRI-", "ENSA-", "ENCG-")):
                return "Le Directeur"
            if "Présidence" in etab or "Presidence" in etab:
                return "Le Président"
        return None

    # ─── DESTINATAIRE ──────────────────────────────────────────────────────
    def _extract_destinataire(self, text: str) -> Optional[str]:
        flat = re.sub(r"(\b\w[\w'\-]{0,24})\n(?=\w)", r"\1 ", text)

        for zone, pattern in [
            (flat, r"(?:^|\n|\s)\s*[AÀ]\s+((?:Monsieur|Madame|Mesdames|Messieurs|MONSIEUR|MADAME)"
                   r"(?:\s+(?:le|la|les|LE|LA|LES))?\s+"
                   r"(?:Pr[eé]sident[e]?|Doyen[e]?|Directeur|Directrice|Recteur|Vice[\s\-]?Pr[eé]sident|PR[EÉ]SIDENT|DOYEN|DIRECTEUR)"
                   r"[^\n]{5,200})"),
            (text, r"(?:^|\n)\s*[AÀ]\s*[\n\s]+((?:Monsieur|Madame|Mesdames|Messieurs|MONSIEUR|MADAME)"
                   r"(?:\s+(?:le|la|les|LE|LA|LES))?\s+"
                   r"(?:Pr[eé]sident[e]?|Doyen[e]?|Directeur|Directrice|Recteur|Vice[\s\-]?Pr[eé]sident|PR[EÉ]SIDENT|DOYEN|DIRECTEUR)"
                   r"[^\n]{5,200})"),
        ]:
            m = re.search(pattern, zone, re.DOTALL)
            if m:
                cand = self._nettoyer_destinataire(m.group(1))
                if cand:
                    return cand

        for zone in (flat, text):
            for m in re.finditer(
                r"(?:^|\n|\s)(Monsieur|Madame|Mesdames|Messieurs)\s+le\s+"
                r"(Pr[eé]sident|Doyen|Directeur|Vice[\s\-]?Pr[eé]sident|Recteur)"
                r"[^\n]{3,200}",
                zone, re.IGNORECASE,
            ):
                candidat = m.group(0).strip()
                if re.match(r"^(Monsieur|Madame|Mesdames|Messieurs)\s+le\s+\w+\s*,",
                            candidat, re.IGNORECASE):
                    continue
                if "honneur" in candidat.lower():
                    continue
                result = self._nettoyer_destinataire(candidat)
                if result:
                    return result

        # Arabe : إلى\n<destinataire>
        m = re.search(
            r"إلى\s*[\n\s]+("
            r"(?:السيد|السيدة|السيدتين|السادة|السيدات|الأستاذ|الأستاذة|الدكتور|"
            r"رؤساء|عمداء|مديري|أعضاء)"
            r"[^\n]{5,250}"
            r"(?:\n[^\n]{3,150})?"
            r")",
            text,
        )
        if m:
            cand = self._nettoyer_destinataire(m.group(1))
            if cand:
                return cand

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
                cleaned = self._nettoyer_destinataire(cand)
                if cleaned:
                    return cleaned

        m = re.search(r"(?:^|\n)\s*(السيد\s+رئيس\s+جامعة[^\n]{0,100})", text)
        if m: return self._nettoyer_destinataire(m.group(1))

        m = re.search(
            r"(?:^|\n)\s*[AÀ]\s*\n\s*([^\n]{10,200}(?:\n[^\n]{5,80}){0,2})",
            text,
        )
        if m:
            candidat = m.group(1).strip()
            if re.search(r"Pr[eé]sident|Doyen|Directeur|Universit[eé]", candidat, re.IGNORECASE):
                return self._nettoyer_destinataire(candidat)

        m = re.search(r"[Dd]estinataire\s*[:.]\\s*(.+?)(?:\n|$)", text)
        if m: return self._nettoyer_destinataire(m.group(1))

        return None

    def _nettoyer_destinataire(self, raw: str) -> Optional[str]:
        s = raw.strip()
        s = re.sub(r"^[\|\s«»\-,]+", "", s)
        s = re.sub(r"\n+", ", ", s)
        s = re.sub(r"\s+", " ", s)
        s = re.sub(r"[\s,]+$", "", s)
        s = re.sub(r"^[,\s\-]+", "", s)
        s = re.sub(r",\s*-\s*Marrakech\s*-?\s*$", " - Marrakech", s)

        arabic_chars = len(re.findall(r"[\u0600-\u06FF]", s))
        latin_chars = len(re.findall(r"[a-zA-ZÀ-ÿ]", s))
        is_arabic_dest = arabic_chars > 3 and arabic_chars >= latin_chars

        if not is_arabic_dest:
            s = re.sub(r"[\u0600-\u06FF]+", "", s)
            s = re.sub(r"[«»\"]+", "", s)
            s = re.sub(r"\s+EE\s+He\s+", " ", s, flags=re.IGNORECASE)
            s = re.sub(r"\s+", " ", s).strip()
            m = re.search(
                r"(Cadi\s+Ayy?ad|Cadi\s+Ayyap|CADI\s+AYY?AD|CADI\s+AYYAP)"
                r"(?:\s*[,\-\s]*Marrakech)?",
                s, re.IGNORECASE,
            )
            if m:
                s = s[:m.end()]

        s = re.split(
            r"\s+(?:Objet|OBJET|Bordereau|BORDEREAU|BORDERAU|BORDEREAtJ|"
            r"الموضوع|ال[مم]و[ضصظط]و[عغ]|"
            r"ورقة|Nature|Nombre|Observations|Veuillez)\s*[:\s]",
            s, maxsplit=1
        )[0]
        s = re.sub(r"\s+D[''']?ENVOI.*$", "", s, flags=re.IGNORECASE)
        s = re.sub(
            r"[,\s]+(PR[EÉ]SIDENCE\s+DE\s+L[''']?UNIVERSIT[EÉ].*|EE\s+He\s+.*)$",
            "", s, flags=re.IGNORECASE,
        )
        s = re.sub(r"\ble\s+e\s+pr[eé]sident", "le président", s, flags=re.IGNORECASE)
        s = s.strip(" ,-«»|")

        if s.isupper() and len(s) > 10:
            kept_upper = {"UCA", "FST", "FSS", "FSJES", "CRI", "EST", "ENSA", "ENCG", "FMP", "FLSH"}
            result = []
            for w in s.split():
                if w in kept_upper:
                    result.append(w)
                elif w in {"LE", "LA", "LES", "DE", "DU", "DES", "D'L"}:
                    result.append(w.lower())
                else:
                    result.append(w.capitalize())
            s = " ".join(result)
            if s:
                s = s[0].upper() + s[1:]
        return s.strip() if len(s) > 5 else None

    # ─── TYPE DE DOCUMENT ──────────────────────────────────────────────────
    def _extract_type(self, text: str) -> str:
        zone = text[:3000]

        # Bordereau (priorité absolue)
        if re.search(
            r"[Bb]ORDE[RE]E?[AR]?[UtJ]+\s*[Dd]['''\s]?[Ee][Nn][Vv][Oo][Ii]|"
            r"[Bb]order?[ae]u\s*d['''\s]?envoi|"
            r"BORDERAU|BORDEREAtJ|"
            r"Bordereau\s*d['''\s]?envoi",
            zone
        ):
            return "bordereau"
        if re.search(
            r"ورقة\s+الإرسال|بيان\s+الإرسال|كشف\s+الإرسال|إرسالية|"
            r"ورف[ةه]\s+[اإ]لإرسال|ورفه\s+الار\s+سال|ور[قف]\w+\s+[اإ]ل[اإ]رسال",
            zone):
            return "bordereau"

        # Note de service
        if re.search(r"[Nn]ote\s+de\s+service|NOTE\s+DE\s+SERVICE|مذكرة\s+(?:إدارية|داخلية|خدمة)?", zone):
            return "note"

        # Circulaire
        if re.search(r"[Cc]irculaire|CIRCULAIRE|منشور\b|دورية\b", zone):
            return "circulaire"

        # Invitation / Convocation
        # "دعوة لحضور" dans الموضوع = invitation; dans le corps seul = pas suffisant
        zone_short = zone[:1500]
        if re.search(
            r"\b[Ii]nvitation\b|\b[Cc]onvocation\b|استدعاء|"
            r"يشرفنا\s+أن\s+ندعوكم|نتشرف\s+بدعوتكم|"
            r"بطاقة\s+دعوة|دعوة\s+رسمية|"
            r"الموضوع[^\n]{0,20}دعوة\s+لحضور|دعوة\s+لحضور[^\n]{0,80}مهرجان|دعوة\s+لحضور[^\n]{0,50}ندو",
            zone_short
        ):
            return "invitation"

        # Procès-verbal / PV
        if re.search(r"[Pp]roc[eè]s[\s\-]verbal|\bPV\b|محضر\s+اجتماع|\bمحضر\b", zone):
            return "pv"

        # Convention / Contrat
        if re.search(r"\b[Cc]onvention\b|\b[Cc]ontrat\b|اتفاقية|\bعقد\b", zone):
            return "convention"

        # Attestation — restreint au titre (pas dans corps bordereau)
        if re.search(r"[Aa]ttestation\b", zone[:2000]) or re.search(r"شهادة\b", zone[:400]):
            return "attestation"

        # Demande — uniquement si titre explicite, pas juste un mot dans le corps
        if re.search(r"(?:^|\n)\s*DEMANDE\s+DE\b|طلب\s+(?:الحصول|التسجيل|الدعم)|التماس\b", zone[:800]):
            return "demande"

        # Rapport
        if re.search(r"\b[Rr]apport\b|تقرير\b", zone):
            return "rapport"

        # Décision
        if re.search(r"\b[Dd][eé]cision\b|قرار\b", zone):
            return "decision"

        return "lettre"

    # ─── ÉTABLISSEMENT ÉMETTEUR ────────────────────────────────────────────
    def _extract_etablissement(self, text: str) -> Optional[str]:
        destinataire_match = re.search(
            r"(?:^|\n)\s*[AÀ]\s*[\n\s]+(?:Monsieur|Madame|Mesdames|Messieurs|السيد|إلى)",
            text,
        )
        zone = (
            text[:destinataire_match.start()] if destinataire_match else text[:1500]
        )

        # Présidence (priorité)
        if re.search(
            r"(?:Royaume\s+du\s+Maroc\s+)?[^\n]*Universit[eé]\s+Cadi\s+Ayyad.{0,80}?La\s+Pr[eé]sidence",
            zone, re.IGNORECASE | re.DOTALL,
        ):
            return "La Présidence - Marrakech"
        if re.search(r"^\s*La\s+Pr[eé]sidence\s*$", zone, re.MULTILINE | re.IGNORECASE):
            return "La Présidence - Marrakech"
        # Cas OCR: bruit avant "La Présidence" sur la même ligne (ex: "‏ل‎ La Présidence Cemmémeratien")
        if re.search(r"^.{0,15}La\s+Pr[eé]sidence\b", zone, re.MULTILINE | re.IGNORECASE):
            return "La Présidence - Marrakech"

        # CRI
        if re.search(
            r"[Cc]entre\s+R[eé]gional\s+d[''']?[Ii]nvestissement[\s\S]{0,30}?Marrakech|CRI[\s\-\.]*R?M?S?",
            zone, re.IGNORECASE,
        ):
            return "CRI-Marrakech-Safi"

        # FSS Semlalia
        if re.search(r"Facult[eé]\s+des\s+Sciences\s+Semlalia|FSSM?|FSS\s*Semlalia|Sciences\s+Semlalia",
                     zone, re.IGNORECASE):
            return "FSS-Marrakech"

        # FSJES
        if re.search(
            r"Facult[eé]\s+des\s+Sciences\s+[JjIi]uridiques|FSJES|"
            r"Sciences\s+[JjIi]uridiques.{0,40}?[eE]conomiques|"
            r"[jJ]URIDIQUES[\.,\s]+[EÉ]CONOMIQUES",
            zone, re.IGNORECASE,
        ):
            return "FSJES-Marrakech"

        # FMP (avant FST pour éviter confusion)
        if re.search(
            r"Facult[eé]\s+de\s+M[eé]decine\s+et\s+de\s+Pharmacie|FMPM?\b",
            zone, re.IGNORECASE,
        ):
            return "FMP-Marrakech"

        # FLSH
        if re.search(r"Facult[eé]\s+des\s+Lettres\s+et\s+des?\s+Sciences\s+Humaines|FLSH\b",
                     zone, re.IGNORECASE):
            return "FLSH-Marrakech"

        # ENSA
        if re.search(r"[EÉ]cole\s+Nationale\s+des\s+Sciences\s+Appliqu[eé]es|ENSA\b",
                     zone, re.IGNORECASE):
            return "ENSA-Marrakech"

        # ENCG
        if re.search(r"[EÉ]cole\s+Nationale\s+de\s+Commerce\s+et\s+de\s+Gestion|ENCG\b",
                     zone, re.IGNORECASE):
            return "ENCG-Marrakech"

        # EST Essaouira (avant FST)
        if re.search(
            r"[EÉ]cole\s+Sup[eé]rieure\s+de\s+Technologie[\s\S]{0,30}?Essaouira|"
            r"ECOLE\s+SUP[EÉ]RIEURE\s+D[EC]?\s*TECHNOLOGIE\s+ESS?AOUIRA|"
            r"EST[\s\-\.]*Essaouira|\bESTE\b|"
            r"المدرسة\s+العليا\s+للتكنولوجيا[\s\S]{0,20}?الصويرة",
            zone, re.IGNORECASE,
        ):
            return "EST-Essaouira"

        # EST Safi
        if re.search(r"[EÉ]cole\s+Sup[eé]rieure\s+de\s+Technologie[\s\S]{0,20}?Safi|EST.{0,5}?Safi",
                     zone, re.IGNORECASE):
            return "EST-Safi"

        # FST Marrakech
        if re.search(
            r"Facult[eé]\s+des?\s*Sciences\s+et\s+Techniques|"
            r"FACULL?TE\s+DES\s*SCIENCES[\s\S]{0,30}?ET\s+TECHNIQUES|"
            r"SCIENCES[\s\S]{0,20}?ET\s+TECHNIQUES[\s\S]{0,20}?MARRAKECH|"
            r"FSTG?\b|Sciences\s+et\s+Techniques[\s\S]{0,30}?Marrakech|"
            r"والتقنيات\s*[-–]\s*مراكش|كلية\s+العلوم\s+والتقنيات",
            zone, re.IGNORECASE,
        ):
            return "FST-Marrakech"

        # FP Safi
        if re.search(r"Facult[eé]\s+Polydisciplinaire.{0,20}?Safi|FP\s*Safi|FPS\b",
                     zone, re.IGNORECASE):
            return "FP-Safi"

        # Versions arabes — institutions spécifiques AVANT Présidence
        if re.search(r"كلية\s+العلوم\s+القانونية", zone):
            return "FSJES-Marrakech"
        if re.search(r"كلية\s+العلوم\s+والتقنيات", zone):
            return "FST-Marrakech"
        if re.search(r"كلية\s+العلوم.{0,20}?سملالية", zone):
            return "FSS-Marrakech"
        if re.search(r"كلية\s+الطب\s+والصيدلة", zone):
            return "FMP-Marrakech"
        if re.search(r"كلية\s+الآداب\s+والعلوم\s+الإنسانية", zone):
            return "FLSH-Marrakech"
        if re.search(r"الكلية\s+المتعددة\s+التخصصات", zone):
            return "FP-Safi"
        if re.search(r"رئاس[ةه]\s+جامع[ةه]\s+القاضي|الرئاس[ةه]\b", zone):
            return "La Présidence - Marrakech"
        return None

    # ─── CORPS ─────────────────────────────────────────────────────────────
    def _extract_corps(self, norm: str, raw: str) -> Optional[str]:
        lines = norm.split("\n")
        start_idx = 0
        end_idx = len(lines)

        debut_patterns = [
            (r"^\s*Monsieur\s+le\s+Pr[eé]sident\s*,", "salutation"),
            (r"^\s*Madame\s+la\s+Pr[eé]sidente\s*,", "salutation"),
            (r"^\s*Monsieur\s+le\s+Doyen\s*,", "salutation"),
            (r"^\s*Monsieur\s*,", "salutation"),
            (r"^\s*Madame\s*,", "salutation"),
            (r"^\s*Cher\(e\)s?\s", "salutation"),
            (r"^\s*[Vv]euillez\s+trouver\s+ci[\-\s]joint", "bordereau"),
            (r"^\s*[Bb]ordereau\s+d[''']?envoi", "bordereau_titre"),
            (r"^\s*[Oo]bjet\s*:", "objet_ligne"),
            (r"^\s*سلام\s+تام", "salutation_ar"),
            (r"^\s*وبعد\s*,?", "salutation_ar"),
            (r"^\s*في\s+إطار", "corps_direct_ar"),
            (r"^\s*بناء\s+على", "corps_direct_ar"),
            (r"^\s*نتشرف|^\s*يشرفنا|^\s*نحيطكم", "corps_direct_ar"),
            (r"^\s*تجدون\s+طيه", "bordereau_ar"),
            (r"^\s*ورقة\s+الإرسال", "bordereau_ar_titre"),
            (r"^\s*(?:Dans\s+le\s+cadre|À\s+cet\s+effet|A\s+cet\s+effet|"
             r"J[''']?ai\s+l[''']?honneur|Nous\s+avons\s+l[''']?honneur|"
             r"Suite\s+à|Conform[eé]ment)", "corps_direct"),
        ]

        found_start = False
        for i, line in enumerate(lines):
            for p, kind in debut_patterns:
                if re.match(p, line, re.IGNORECASE):
                    start_idx = i if kind not in ("salutation", "salutation_ar") else i + 1
                    found_start = True
                    break
            if found_start:
                break

        if not found_start:
            doc_keywords_ar = re.compile(
                r"^\s*(?:تجدون\s+طيه|ورقة\s+الإرسال|شهادة|طلب|"
                r"استمارة|دبلوم|برنامج|قائمة|وثيقة|محضر|تقرير|"
                r"في\s+إطار|بناء\s+على|نتشرف|يشرفنا)"
            )
            for i, line in enumerate(lines):
                if doc_keywords_ar.match(line):
                    start_idx = i
                    found_start = True
                    break

        fin_patterns = [
            r"^\s*[Vv]euillez\s+agr[eé]er",
            r"^\s*Nous\s+vous\s+prions",
            r"^\s*Dans\s+l[''']?attente\s+de",
            r"^\s*Le\s+Pr[eé]sident\s*$",
            r"^\s*Le\s+Directeur\s*$",
            r"^\s*Le\s+Doyen\s*$",
            r"^\s*La\s+Pr[eé]sidente\s*$",
            r"^\s*Pour\s+le\s+Pr[eé]sident",
            r"^\s*وتقبلوا",
            r"^\s*العميد\s*$",
            r"^\s*Point\s+de\s+contact",
            r"^\s*Pi[eè]ces?\s+joint",
            r"^\s*المرفقات\s*[:\.\s]",
            r"^\s*ملاحظة\s*[:\.\s]",
            r"^\s*قصد\s+التوقيع",
            r"^\s*المدير\s*$",
            r"^\s*الرئيس\s*$",
            r"^\s*نائب\s+الرئيس\s*$",
            r"^\s*العميد\s+بالنيابة",
            r"^\s*وتقبلوا\s+أزكى|^\s*وتقبلوا\s+التحيات",
            # Fix v3 : marqueurs de fin supplémentaires (cachets, adresses, OCR de signatures)
            r"^\s*PR[EÉ]SIDENCE\s+DE\s+L",            # cachet présidence
            r"^\s*Achraf\s+JANI",                      # signature spécifique FSJES
            r"^\s*Mallfouc|^\s*Mahfoud\s+MOUSSAID",   # signature CRI
            r"^\s*Adresse\s*:",                        # bas de page
            r"^\s*Email\s*:",
            r"^\s*Tél\.?\s*:|^\s*Mobile\s*:",
            r"^\s*Avenue\s+",
            r"^\s*\d{4}-\d{2}-\d{2}-\d{2}",            # numéros téléphone formatés
            r"^\s*\+\s*212",                            # téléphone international Maroc
            r"^\s*http[s]?://",                         # URLs
            r"^\s*Centre\s+R[eé]gional\s+d['']?Investissement\s+de\s+Marrakech",  # footer CRI
        ]
        for i in range(len(lines) - 1, max(start_idx, 0), -1):
            line = lines[i].strip()
            for p in fin_patterns:
                if re.match(p, line, re.IGNORECASE):
                    end_idx = i
                    break
            if end_idx != len(lines):
                break

        corpus_lines = [l.strip() for l in lines[start_idx:end_idx] if l.strip()]
        if not corpus_lines:
            return None

        corpus_lines = self._clean_corps_lines(corpus_lines)
        if not corpus_lines:
            return None

        corps = "\n".join(corpus_lines)
        corps = re.sub(r"\n{3,}", "\n\n", corps).strip()
        return corps if len(corps) > 15 else None

    def _clean_corps_lines(self, lines: list) -> list:
        cleaned = []
        for line in lines:
            l = line.strip()
            l = re.sub(r"^[\s\|\[\]\{\}\<\>=_\-\*\+\.,\:\;\'\"` ´\~\^\\\\/]+", "", l)
            l = re.sub(r"[\|\[\]\{\}\<\>=_\*\+`´\~\^\\\\/]+$", "", l).strip()
            if not l:
                continue
            nb_alpha_lat = sum(1 for c in l if c.isalpha() and ord(c) < 0x0600)
            nb_alpha_ar = sum(1 for c in l if 0x0600 <= ord(c) <= 0x06FF)
            nb_alpha = nb_alpha_lat + nb_alpha_ar
            total = len(l)
            if total < 3 or nb_alpha == 0:
                continue
            nb_special = sum(1 for c in l if not c.isalnum() and not c.isspace())
            if total > 0 and nb_special / total > 0.6:
                continue
            nb_digits = sum(1 for c in l if c.isdigit())
            if total > 5 and nb_digits / total > 0.7 and nb_alpha < 3:
                continue
            if re.search(r"[\u2D30-\u2D7F]", l) and nb_alpha_lat < 10:
                continue
            if total < 30 and nb_alpha_ar > 0 and nb_alpha_lat < 8:
                continue
            if total < 20:
                mots = l.split()
                tokens_valides = sum(1 for m in mots if len(m) >= 4 and sum(c.isalpha() for c in m) >= 3)
                if tokens_valides == 0:
                    continue
            mots = l.split()
            if len(mots) >= 4:
                tokens_1char = sum(1 for m in mots if len(m) == 1)
                if tokens_1char / len(mots) > 0.4:
                    continue
            cleaned.append(l)
        return cleaned

    # ─── SCORE DE CONFIANCE ────────────────────────────────────────────────
    def _score_confidence(self, field: str, value, text: str) -> float:
        if value is None or value == "":
            return 0.0

        base = 0.55
        v = str(value)

        if field == "numero":
            if re.match(r"^\d{2,6}/\d{2,4}(/[A-Z\-]+)?$", v):
                base = 0.90
            elif re.match(r"^\d{3,5}$", v):
                base = 0.70

        elif field == "date":
            if re.match(r"^\d{2}\s+\w+\s+\d{4}$", v):
                base = 0.95

        elif field == "objet":
            if 10 <= len(v) <= 200:
                base = 0.80
            elif len(v) > 200:
                base = 0.60

        elif field == "expediteur":
            has_titre = bool(re.search(
                r"Pr[eé]sident|Doyen|Directeur|Vice|Secr[eé]taire|رئيس|العميد|المدير", v))
            has_inst = bool(re.search(
                r"Facult[eé]|Universit[eé]|CRI|EST|FST|FSJES|FSS|FMP|FLSH|ENSA|ENCG|"
                r"Pr[eé]sidence|كلية|جامعة|المدرسة", v))
            if has_titre and has_inst:
                base = 0.90
            elif has_titre or has_inst:
                base = 0.70

        elif field == "destinataire":
            if re.search(
                r"Pr[eé]sident|Doyen|Directeur|Universit[eé]|Facult[eé]|رئيس|جامعة|كلية", v):
                base = 0.85
            else:
                base = 0.60

        elif field == "type_document":
            base = 0.85 if v in ("bordereau", "note", "circulaire", "invitation",
                                  "pv", "convention", "attestation", "demande",
                                  "rapport", "decision") else 0.55

        elif field == "etablissement":
            known = ("FSJES-Marrakech", "FSS-Marrakech", "FST-Marrakech",
                     "EST-Essaouira", "EST-Safi", "FP-Safi", "CRI-Marrakech-Safi",
                     "La Présidence - Marrakech", "FMP-Marrakech", "FLSH-Marrakech",
                     "ENSA-Marrakech", "ENCG-Marrakech")
            if v in known:
                base = 0.90

        return round(min(base, 0.99), 2)
