"""Visita il sito di un ente e raccoglie le voci dalle pagine di albo, bandi e avvisi."""
import re
import threading
from urllib.parse import urlparse

from .generico import link_pagina_successiva, link_sezioni, voci_da_html

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
              "Version/17.0 Safari/605.1.15 RadarBandi/1.0 (+https://github.com/Fabri-75/radar-bandi)")
MAX_PAGINE_ELENCO = 12   # pagine successive di uno stesso albo
MAX_SEZIONI = 6          # sezioni diverse lette per ente

# Pagine che si costruiscono con JavaScript: le apro con un browser automatico
RE_JS = re.compile(r"attendere prego|ng-app|<app-root|id=\"root\"></div>|__next|caricamento in corso|enable javascript|abilita(re)? javascript", re.I)
PIATTAFORME_JS = re.compile(r"portaleargo\.it|urbi\.it/urbi|halleyweb\.com|EGHOMEPAGE\.HBL|/EG0/", re.I)

class _Renderer:
    """Un solo browser per tutta la ricerca, in un thread dedicato (Playwright non è thread-safe)."""

    def __init__(self):
        import queue
        self.q = queue.Queue()
        self.t = None
        self.lock = threading.Lock()

    def _ciclo(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--disable-dev-shm-usage"])
            ctx = browser.new_context(user_agent=BROWSER_UA)
            while True:
                lavoro = self.q.get()
                if lavoro is None:
                    break
                url, risposta = lavoro
                try:
                    pg = ctx.new_page()
                    pg.goto(url, timeout=40000, wait_until="networkidle")
                    pg.wait_for_timeout(2000)
                    risposta.append((pg.content(), pg.url))
                    pg.close()
                except Exception:
                    risposta.append((None, None))
                    try:
                        pg.close()
                    except Exception:
                        pass
            browser.close()

    def rendi(self, url):
        with self.lock:
            if self.t is None:
                self.t = threading.Thread(target=self._ciclo, daemon=True)
                self.t.start()
        risposta = []
        ev = threading.Event()
        self.q.put((url, risposta))
        for _ in range(900):          # al massimo 90 secondi
            if risposta:
                return risposta[0]
            ev.wait(0.1)
        return None, None

    def chiudi(self):
        if self.t is not None:
            self.q.put(None)


RENDERER = _Renderer()


def rendi(url):
    """Apre la pagina con Chromium e ritorna (html, url finale) oppure (None, None)."""
    return RENDERER.rendi(url)


def scarica(rete, url, js_permesso=True):
    """HTML di una pagina, con i ripieghi: user agent da browser se il sito rifiuta, browser automatico se serve JS."""
    r, err = rete.get(url)
    if err and r is not None and r.status_code in (403, 406, 429, 503):
        r, err = rete.get(url, headers={"User-Agent": BROWSER_UA})
    if err:
        if err.startswith("errore 403") or err.startswith("errore 503"):
            return None, None, "il sito blocca le visite automatiche (errore %s)" % err[-3:]
        return None, None, err
    ct = r.headers.get("content-type", "")
    if "html" not in ct and "text" not in ct and "xml" not in ct:
        return None, None, "non è una pagina web"
    html = r.text
    if js_permesso and (PIATTAFORME_JS.search(r.url) or (RE_JS.search(html[:20000]) and len(re.sub(r"<[^>]+>", "", html)) < 8000)):
        h2, fin = rendi(r.url)
        if h2:
            return h2, fin, None
    return html, r.url, None


def _nome_pagina(tipo, url):
    return {"albo": "Albo", "bandi": "Bandi/avvisi", "trasparenza": "Trasparenza", "notizie": "Notizie", "cultura": "Cultura", "home": "Home"}.get(tipo, tipo)


def leggi_ente(rete, ente, limite):
    """Ritorna (voci, pagine_lette, errore)."""
    sito = ente["sito"]
    p = urlparse(sito)
    radice = f"{p.scheme}://{p.netloc}/"
    altro_host = p.netloc[4:] if p.netloc.startswith("www.") else "www." + p.netloc
    tentativi = [sito, radice, f"https://{altro_host}/", "http://" + p.netloc + "/"]
    if ente.get("sito_alt"):
        tentativi.insert(1, ente["sito_alt"])
    home, url_home, err, primo_err = None, None, None, None
    for t in dict.fromkeys(tentativi):
        home, url_home, err = scarica(rete, t)
        primo_err = primo_err or err
        if home:
            break
        if err and ("robots" in err or "blocca" in err):
            break
    if not home:
        return [], [], primo_err or err or "sito irraggiungibile"

    pagine, voci, visti = [], [], set()
    sez = link_sezioni(home, url_home)
    coda = [("home", url_home)]
    ordine = ["albo", "bandi", "notizie"] if ente["tipo"] != "Biblioteca" else ["bandi", "notizie", "cultura", "albo"]
    for k in ordine:
        coda += [(k, u) for u in sez[k][:2]]
    # Amministrazione trasparente: cerco dentro "Bandi di gara e contratti"
    if sez["trasparenza"]:
        coda.append(("trasparenza", sez["trasparenza"][0]))

    letti = 0
    while coda and letti < MAX_SEZIONI + 1:
        tipo, u = coda.pop(0)
        chiave = u.split("#")[0]
        if chiave in visti:
            continue
        visti.add(chiave)
        if tipo == "home":
            html, fin = home, url_home
        else:
            html, fin, e = scarica(rete, u)
            if not html:
                continue
        letti += 1
        nuove = voci_da_html(html, fin)
        if tipo != "home":
            pagine.append({"nome": _nome_pagina(tipo, fin), "url": fin})
        # Pagine di solo menu (es. albo che rimanda a una piattaforma esterna): seguo i link interni
        if tipo in ("albo", "bandi", "trasparenza") and len(nuove) < 3:
            s2 = link_sezioni(html, fin)
            interni = s2["albo"] + s2["bandi"] if tipo != "trasparenza" else s2["bandi"]
            for x in interni[:3]:
                if x.split("#")[0] not in visti:
                    coda.insert(0, (tipo, x))
        # Pagine successive dell'elenco, finché le voci sono recenti
        n = 0
        while tipo in ("albo", "bandi", "notizie") and n < MAX_PAGINE_ELENCO and nuove:
            date_ = [v["pubblicazione"] for v in nuove if v["pubblicazione"]]
            if date_ and min(date_) < limite:
                break
            succ = link_pagina_successiva(html, fin)
            if not succ or succ.split("#")[0] in visti:
                break
            visti.add(succ.split("#")[0])
            html, fin, e = scarica(rete, succ, js_permesso=False)
            if not html:
                break
            altre = voci_da_html(html, fin)
            if not altre:
                break
            voci += altre
            n += 1
        voci += nuove

    for v in voci:
        if v.get("senza_link"):
            v["apri_dettaglio"] = False   # il link porta all'elenco, non all'atto
        v["fonte"] = "sito " + urlparse(v["link"]).netloc.replace("www.", "")
    if not pagine and not voci:
        return [], [{"nome": "Home", "url": url_home}], "sezione avvisi non trovata"
    return voci, pagine or [{"nome": "Home", "url": url_home}], None
