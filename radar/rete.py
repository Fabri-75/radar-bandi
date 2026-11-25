"""Accesso rispettoso ai siti: pause per sito, tempi massimi, robots.txt, user agent riconoscibile."""
import threading
import time
import re
from urllib.parse import urlparse, urljoin

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

UA = "RadarBandi/1.0 (ricerca avvisi pubblici per artisti; +https://github.com/Fabri-75/radar-bandi)"


class Rete:
    def __init__(self, pausa=1.5, timeout=25, max_byte=15_000_000):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
        self.pausa, self.timeout, self.max_byte = pausa, timeout, max_byte
        self._ultimo = {}       # host -> momento dell'ultima richiesta
        self._robots = {}       # host -> RobotFileParser oppure None
        self._lock = threading.Lock()
        self._lock_host = {}
        self.richieste = 0

    def _attendi(self, host):
        with self._lock:
            lk = self._lock_host.setdefault(host, threading.Lock())
        with lk:
            t = self._ultimo.get(host)
            if t is not None:
                dt = time.time() - t
                if dt < self.pausa:
                    time.sleep(self.pausa - dt)
            self._ultimo[host] = time.time()

    def permesso(self, url):
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            regole = None
            try:
                self._attendi(p.netloc)
                r = self.s.get(base + "/robots.txt", timeout=10, verify=False)
                if r.status_code == 200 and "html" not in r.headers.get("content-type", "text/plain"):
                    regole = leggi_robots(r.text)
            except Exception:
                regole = None
            self._robots[base] = regole
        regole = self._robots[base]
        if not regole:
            return True
        percorso = (p.path or "/") + (("?" + p.query) if p.query else "")
        return robots_permette(regole, percorso)

    def get(self, url, controlla_robots=True, **kw):
        """Ritorna (risposta, errore). L'errore è una frase breve in italiano."""
        if controlla_robots and not self.permesso(url):
            return None, "bloccato da robots.txt"
        host = urlparse(url).netloc
        self._attendi(host)
        self.richieste += 1
        try:
            r = self.s.get(url, timeout=kw.pop("timeout", self.timeout), verify=kw.pop("verify", False),
                           stream=True, **kw)
            dati = b""
            for pezzo in r.iter_content(65536):
                dati += pezzo
                if len(dati) > self.max_byte:
                    break
            r._content = dati
            r._content_consumed = True
            if r.status_code >= 400:
                return r, f"errore {r.status_code}"
            return r, None
        except requests.exceptions.Timeout:
            return None, "sito troppo lento (tempo scaduto)"
        except requests.exceptions.SSLError:
            return None, "certificato di sicurezza non valido"
        except requests.exceptions.ConnectionError:
            return None, "sito irraggiungibile"
        except Exception as e:  # noqa
            return None, f"errore: {type(e).__name__}"

    def post(self, url, **kw):
        host = urlparse(url).netloc
        self._attendi(host)
        self.richieste += 1
        try:
            r = self.s.post(url, timeout=kw.pop("timeout", self.timeout), verify=False, **kw)
            return r, (None if r.status_code < 400 else f"errore {r.status_code}")
        except Exception as e:  # noqa
            return None, f"errore: {type(e).__name__}"


def normalizza_url(u):
    """Corregge gli indirizzi scritti male negli open data (es. 'https//', spazi, maiuscole)."""
    if not u:
        return ""
    u = u.strip().strip('"').replace(" ", "")
    if u.lower() in ("nondisponibile", "-", "n.d.", "nd"):
        return ""
    for rotto, giusto in (("https//", "https://"), ("http//", "http://"), ("https:/", "https://"), ("http:/", "http://")):
        if u.lower().startswith(rotto) and not u.lower().startswith(giusto):
            u = giusto + u[len(rotto):]
    if not u.lower().startswith("http"):
        u = "https://" + u.lstrip("/")
    p = urlparse(u)
    return f"{p.scheme.lower()}://{p.netloc.lower()}{p.path or '/'}" + (f"?{p.query}" if p.query else "")


def assoluto(base, href):
    return urljoin(base, href)


def leggi_robots(testo):
    """Regole robots.txt che valgono per noi: quelle per 'radarbandi' se ci sono, altrimenti quelle per '*'."""
    gruppi, attuali, regole_attuali, ultimo_ua = {}, [], None, False
    for riga in testo.splitlines():
        riga = riga.split("#", 1)[0].strip()
        if ":" not in riga:
            continue
        k, v = [x.strip() for x in riga.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if not ultimo_ua:
                attuali, regole_attuali = [], []
            attuali.append(v.lower())
            for a in attuali:
                gruppi.setdefault(a, regole_attuali)
            ultimo_ua = True
        elif k in ("allow", "disallow") and regole_attuali is not None:
            ultimo_ua = False
            if v or k == "allow":
                regole_attuali.append((k == "allow", v))
        else:
            ultimo_ua = False
    for a, r in gruppi.items():
        if a != "*" and a.startswith("radarbandi"):
            return r
    return gruppi.get("*", [])


def _schema(v):
    rx = re.escape(v).replace(r"\*", ".*")
    if rx.endswith(r"\$"):
        rx = rx[:-2] + "$"
    return re.compile(rx)


def robots_permette(regole, percorso):
    """Semantica di Google: vince la regola più lunga che corrisponde; a parità vince Allow."""
    migliore = None
    for allow, v in regole:
        if not v:
            continue
        if _schema(v).match(percorso):
            lung = len(v)
            if migliore is None or lung > migliore[0] or (lung == migliore[0] and allow):
                migliore = (lung, allow)
    return True if migliore is None else migliore[1]
