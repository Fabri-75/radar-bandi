"""Accesso rispettoso ai siti: pause per sito, tempi massimi, robots.txt, user agent riconoscibile."""
import threading
import time
import urllib.robotparser
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
            rp = None
            try:
                self._attendi(p.netloc)
                r = self.s.get(base + "/robots.txt", timeout=10, verify=False)
                if r.status_code == 200 and "text" in r.headers.get("content-type", "text"):
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(r.text.splitlines())
            except Exception:
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(UA, url)

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
