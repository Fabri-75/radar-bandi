"""Lettore generico: riconosce le righe di un albo o di un elenco di avvisi in qualsiasi pagina HTML.

Idea: ogni avviso ha una data vicino al titolo. Parto da ogni data nella pagina e salgo nell'HTML
fino al blocco che contiene un solo avviso (riga di tabella, voce di elenco, scheda). Da quel blocco
prendo titolo, link, allegati e date.
"""
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString

from ..testo import semplice, trova_date

RE_DATA = re.compile(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-](?:20)?\d{2}\b|\b\d{1,2}\s+(?:gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic)[a-z]*\.?\s+20\d{2}\b", re.I)
RE_PUB = re.compile(r"pubblicat|pubblicazione|data (?:di )?(?:affissione|inizio)|dal\b|inizio", re.I)
RE_ETICHETTE = re.compile(r"^(n\.?|numero|nr\.?|del|data|oggetto|tipo|tipologia|categoria|settore|ente|ufficio|atto|dettagli.*|scarica.*|visualizza.*|leggi.*|apri.*|"
                          r"pubblicat[oa] il|fine pubblicazione:?|inizio pubblicazione:?|richiedente:?|allegat.*|documento|\d+|[\d/\s.-]+|registro.*|anno.*)$", re.I)
RE_ESTENSIONI = re.compile(r"\.(pdf|p7m|docx?|odt|rtf|zip)(\?|$|#)", re.I)
RE_FILE_TESTO = re.compile(r"\.(pdf|p7m|docx?|odt|rtf|zip)\b|\(\s*[^)]*kb\s*\)", re.I)
TAG_RUMORE = ["script", "style", "noscript", "select", "option", "form", "nav", "header", "footer", "svg", "button"]


def pulisci(html):
    s = BeautifulSoup(html, "html.parser")
    for t in s(TAG_RUMORE):
        # i form a volte avvolgono l'intera lista (ASP.NET): tolgo solo i campi, non il contenuto
        if t.name == "form":
            t.unwrap()
        else:
            t.decompose()
    return s


def _testo(n):
    return re.sub(r"\s+", " ", n.get_text(" ", strip=True))


def _n_date(n):
    return len(RE_DATA.findall(n.get_text(" ")))


def blocchi(soup):
    """Elementi che contengono un solo avviso."""
    visti, out = set(), []
    for nodo in soup.find_all(string=RE_DATA):
        el = nodo.parent
        if el is None:
            continue
        cand = el
        while cand.parent is not None and cand.parent.name not in ("body", "html", "[document]"):
            p = cand.parent
            if cand.name in ("tr", "li", "article") and len(_testo(cand)) >= 25:
                break
            t = _testo(p)
            if _n_date(p) > 5 or len(t) > 3000 or len(p.find_all(["tr", "li", "article"], recursive=False)) > 1:
                break
            cand = p
        if _n_date(cand) > 6 or len(_testo(cand)) > 3000:
            continue
        if id(cand) in visti or any(id(a) in visti for a in cand.parents):
            continue
        visti.add(id(cand))
        out.append(cand)
    return out


def _titolo(blocco):
    righe = [re.sub(r"\s+", " ", x).strip() for x in blocco.get_text("\n").split("\n")]
    righe = [r for r in righe if len(r) >= 12 and not RE_ETICHETTE.match(r) and not RE_DATA.fullmatch(r)
             and not RE_FILE_TESTO.search(r) and not re.match(r"^\(.*kb\s*\)$", r, re.I)]
    # preferisco il testo di un link "parlante", poi la riga più lunga
    for a in blocco.find_all("a"):
        t = _testo(a)
        if len(t) >= 25 and not RE_FILE_TESTO.search(t) and not RE_DATA.fullmatch(t) and not RE_ETICHETTE.match(t):
            return t
    return max(righe, key=len) if righe else ""


def _link(blocco, base):
    allegati, dettaglio = [], None
    for a in blocco.find_all("a", href=True):
        h = a["href"].strip()
        if not h or h.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        u = urljoin(base, h)
        if RE_ESTENSIONI.search(u) or re.search(r"download|allegat|scarica|getfile|attachment|file=", u, re.I):
            allegati.append(u)
        elif dettaglio is None and urlparse(u).netloc:
            dettaglio = u
    return dettaglio, allegati


def _data_pubblicazione(testo):
    s = semplice(testo)
    date_ = trova_date(testo)
    if not date_:
        return None
    for m in RE_PUB.finditer(s):
        for pos, d in date_:
            if m.start() <= pos <= m.end() + 40:
                return d
    return date_[0][1]


def _fine(testo):
    s = semplice(testo)
    m = re.search(r"(fine pubblicazione|data fine|al\b|scadenz\w*|entro il)", s)
    if not m:
        return None
    for pos, d in trova_date(testo):
        if m.start() <= pos <= m.end() + 40:
            return d, m.group(1)
    return None


def voci_da_html(html, url):
    """Ritorna una lista di voci: titolo, link, pubblicazione, scadenza, testo, allegati."""
    soup = pulisci(html)
    out = []
    for b in blocchi(soup):
        testo = _testo(b)
        tit = _titolo(b)
        if len(tit) < 15 or len(testo) > 3000 or re.match(r"(ultimo aggiornamento|ultima modifica|riferimento normativo|data di pubblicazione|copyright)", tit, re.I):
            continue
        det, alls = _link(b, url)
        resto = testo.replace(tit, " ")
        pub = _data_pubblicazione(resto) or _data_pubblicazione(testo)
        fine = _fine(resto)
        scad = fine[0] if fine and fine[1].startswith(("scad", "entro")) else None
        out.append({"titolo": tit, "link": det or (alls[0] if alls else url), "pubblicazione": pub, "scadenza": scad,
                    "testo": testo, "allegati": alls, "senza_link": not (det or alls)})
    # tolgo doppioni (stesso titolo) e voci di menu ripetute
    vis, ris = set(), []
    for v in out:
        k = semplice(v["titolo"])[:120]
        if k not in vis:
            vis.add(k); ris.append(v)
    return ris


CONTORNO = ("menu", "sidebar", "footer", "breadcrumb", "cookie", "social", "share", "condividi", "navbar", "widget", "newsletter", "related", "correlat")


def _contorno(t):
    gettoni = [x.lower() for x in (t.get("class") or [])] + ([t.get("id").lower()] if t.get("id") else [])
    return any(g.startswith(CONTORNO) for g in gettoni)


def testo_e_allegati(html, url):
    """Testo principale di una pagina di dettaglio (senza menu e colonne laterali) e link agli allegati."""
    soup = pulisci(html)
    for t in soup.find_all(["aside"]):
        t.decompose()
    for t in soup.find_all(True, attrs={"class": True}):
        if t.attrs is not None and t.name not in ("body", "main", "html", "article") and _contorno(t):
            t.decompose()
    corpo = soup.find("article") or soup.find("main") or soup.find(id=re.compile("content|contenuto|main", re.I)) or soup.body or soup
    alls = []
    for a in corpo.find_all("a", href=True):
        u = urljoin(url, a["href"])
        if RE_ESTENSIONI.search(u) or re.search(r"download|allegat|scarica|getfile|attachment", u + " " + _testo(a), re.I):
            if u not in alls:
                alls.append(u)
    return _testo(corpo)[:30000], alls


RE_MENU = {
    "albo": re.compile(r"albo\s*(on.?line|pretorio|on line)|^albo$|pubblicit[aà] legale", re.I),
    "bandi": re.compile(r"bandi di gara|bandi e (?:gare|avvisi|contratti)|gare e appalti|bandi,? avvisi|^bandi$|^avvisi$|avvisi pubblici|bandi e concorsi", re.I),
    "trasparenza": re.compile(r"amministrazione trasparente", re.I),
    "notizie": re.compile(r"^(notizie|news|novit[aà]|comunicati|avvisi e notizie|bacheca)$", re.I),
    "cultura": re.compile(r"^(cultura|biblioteca|eventi|eventi e cultura)$", re.I),
}
RE_NO = re.compile(r"sindacal|storico|archivio|mappa|login|accedi|privacy|cookie|facebook|twitter|instagram|youtube|whatsapp", re.I)


def link_sezioni(html, url):
    """Link alle sezioni dove si pubblicano avvisi: {tipo: [url, ...]} in ordine di priorità."""
    s = BeautifulSoup(html, "html.parser")
    out = {k: [] for k in RE_MENU}
    for a in s.find_all("a", href=True):
        t = _testo(a) or a.get("title", "") or a.get("aria-label", "")
        h = a["href"].strip()
        if not h or h.startswith(("#", "javascript:", "mailto:", "tel:")) or RE_NO.search(t + " " + h):
            continue
        u = urljoin(url, h)
        for k, rx in RE_MENU.items():
            if rx.search(t) or (k == "albo" and re.search(r"albo.?pretorio|albo.?online|albopretorio|/albo/?$", h, re.I)):
                if u not in out[k]:
                    out[k].append(u)
                break
    return out


def link_pagina_successiva(html, url):
    s = BeautifulSoup(html, "html.parser")
    for a in s.find_all("a", href=True):
        t = _testo(a).lower()
        rel = " ".join(a.get("rel") or []) + " " + " ".join(a.get("class") or []) + " " + (a.get("aria-label") or "").lower()
        if t in ("avanti", "successiva", "pagina successiva", "»", "›", ">", "next", "succ.", "successivo") or "next" in rel or "successiv" in rel:
            h = a["href"]
            if h and not h.startswith(("#", "javascript:")):
                return urljoin(url, h)
    return None
