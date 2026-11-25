"""Estrazione di date, scadenze, importi e destinatari dai testi (pagine e PDF)."""
import io
import re
import unicodedata
from datetime import date

MESI = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
        "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
        "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6, "lug": 7, "ago": 8, "set": 9,
        "ott": 10, "nov": 11, "dic": 12}


def semplice(t):
    """Minuscolo, senza accenti, spazi compattati."""
    t = unicodedata.normalize("NFKD", t or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.lower()).strip()


_RE_NUM = re.compile(r"\b(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4}|\d{2})\b")
_RE_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})")
_RE_LET = re.compile(r"\b(\d{1,2})(?:°|º)?\s+(" + "|".join(sorted(MESI, key=len, reverse=True)) + r")\.?\s+(\d{4})\b")


def _mk(g, m, a):
    try:
        a = int(a)
        if a < 100:
            a += 2000
        d = date(a, int(m), int(g))
        if 2015 <= d.year <= 2035:
            return d
    except ValueError:
        pass
    return None


def trova_date(t):
    """Tutte le date nel testo, con la loro posizione: [(pos, date)]."""
    s = semplice(t)
    out = []
    for m in _RE_NUM.finditer(s):
        d = _mk(m.group(1), m.group(2), m.group(3))
        if d:
            out.append((m.start(), d))
    for m in _RE_ISO.finditer(s):
        d = _mk(m.group(3), m.group(2), m.group(1))
        if d:
            out.append((m.start(), d))
    for m in _RE_LET.finditer(s):
        d = _mk(m.group(1), MESI[m.group(2)], m.group(3))
        if d:
            out.append((m.start(), d))
    return sorted(out)


_RE_SCAD = re.compile(
    r"(scadenz\w*|scade\b|entro (?:e non oltre )?(?:le ore|il|la data|e non oltre)|non oltre|termine (?:ultimo |perentorio )?(?:per|di|della|delle|entro)"
    r"|data (?:di )?(?:fine|chiusura)|termine di presentazione|pervenire entro|fino al|al giorno|presentazione delle (?:domande|candidature|offerte))")


def trova_scadenza(t, dopo=None):
    """Prima data che segue (entro ~160 caratteri) una parola di scadenza. None se non c'è."""
    s = semplice(t)
    date_ = trova_date(t)
    for m in _RE_SCAD.finditer(s):
        for pos, d in date_:
            if m.start() <= pos <= m.end() + 160:
                if dopo is None or d >= dopo:
                    return d
                break
    return None


_RE_EURO = re.compile(r"(?:€|euro|eur\.?)\s*([0-9]{1,3}(?:[.\s][0-9]{3})*(?:,[0-9]{1,2})?|[0-9]+(?:,[0-9]{1,2})?)"
                      r"|([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{1,2})?)\s*(?:€|euro)")
_RE_IMP_CTX = re.compile(r"importo|base d.asta|compenso|corrispettivo|valore|budget|massimo|complessiv|lordo|onnicomprensiv|spesa|contributo|finanziament")


def trova_importo(t):
    """Importo più plausibile (vicino a parole come importo/compenso). Ritorna testo tipo '€ 2.500,00' o None."""
    s = semplice(t)
    migliori = []
    for m in _RE_EURO.finditer(s):
        num = (m.group(1) or m.group(2) or "").replace(" ", "")
        try:
            v = float(num.replace(".", "").replace(",", "."))
        except ValueError:
            continue
        if v < 50 or v > 5_000_000:
            continue
        ctx = s[max(0, m.start() - 120): m.start()]
        punti = 2 if _RE_IMP_CTX.search(ctx) else 0
        migliori.append((punti, -m.start(), v))
    if not migliori:
        return None
    migliori.sort(reverse=True)
    if migliori[0][0] == 0:
        return None
    v = migliori[0][2]
    return "€ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


DESTINATARI = [
    ("Associazioni / ETS", r"associazion\w* (?:culturali|di promozione|senza scopo|no.?profit)|enti del terzo settore|\bets\b|terzo settore|\baps\b|\bodv\b"),
    ("Cooperative", r"cooperativ\w* social\w*|cooperative\b"),
    ("Esperti / persone fisiche", r"persone fisiche|esperti esterni|esperto esterno|liberi professionisti|lavoratori autonomi|professionisti"),
    ("Operatori economici", r"operatori economici|imprese|ditte|societa"),
    ("Personale interno / altre scuole", r"personale interno|collaborazioni plurime|personale in servizio presso altre"),
]
_RE_CHI = re.compile(r"possono (?:partecipare|presentare|candidarsi)|sono ammess|rivolt[oa] a|riservat[oa] a|soggetti (?:ammessi|interessati|destinatari)|destinatari|requisiti di partecipazione|chi puo")


def trova_destinatari(t):
    s = semplice(t)
    pezzi = [s[m.start(): m.start() + 500] for m in _RE_CHI.finditer(s)]
    if not pezzi:
        return None
    zona = " ".join(pezzi)
    trovati = [nome for nome, rx in DESTINATARI if re.search(rx, zona)]
    if not trovati:
        return None
    if re.search(r"(esclusivamente|solo|unicamente|riservat[oa]) (?:a |ad |agli |alle )?(?:associazion|enti del terzo|ets)", zona):
        return "solo Associazioni / ETS"
    return ", ".join(trovati)


_RE_CIG = re.compile(r"\bcig\s*[:n.°]*\s*([0-9A-Z]{10})\b", re.I)


def trova_cig(t):
    m = _RE_CIG.search(t or "")
    return m.group(1).upper() if m else None


import threading
_OCR = threading.Semaphore(1)   # una lettura ottica alla volta: consuma molta memoria


def testo_pdf(dati, max_pagine=8):
    """Testo di un PDF (prime pagine): pypdf, poi pdftotext, poi lettura ottica (OCR) per le scansioni."""
    t = ""
    if len(dati) > 12_000_000:      # PDF enormi (planimetrie, scansioni pesanti): li salto
        return ""
    try:
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(dati))
        t = "\n".join((p.extract_text() or "") for p in r.pages[:max_pagine])
    except Exception:
        t = ""
    if len(t.strip()) >= 200:
        return t
    import shutil, subprocess, tempfile, os
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "a.pdf")
        open(f, "wb").write(dati)
        if shutil.which("pdftotext"):
            try:
                t2 = subprocess.run(["pdftotext", "-l", str(max_pagine), "-layout", f, "-"], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
                if len(t2.strip()) > len(t.strip()):
                    t = t2
            except Exception:
                pass
        if len(t.strip()) < 200 and len(dati) < 6_000_000 and shutil.which("pdftoppm") and shutil.which("tesseract"):
            try:
              with _OCR:
                subprocess.run(["pdftoppm", "-r", "150", "-scale-to", "1800", "-l", "2", "-gray", "-png", f, os.path.join(d, "p")], timeout=120, capture_output=True)
                pezzi = []
                for img in sorted(x for x in os.listdir(d) if x.endswith(".png")):
                    pezzi.append(subprocess.run(["tesseract", os.path.join(d, img), "-", "-l", "ita"], capture_output=True, timeout=120,
                                                env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout.decode("utf-8", "replace"))
                if len("".join(pezzi).strip()) > len(t.strip()):
                    t = "\n".join(pezzi)
            except Exception:
                pass
    return t
