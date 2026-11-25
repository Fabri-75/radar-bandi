"""Prova tecnica: controlla che le fonti siano raggiungibili e cosa contengono."""
import csv, io, json, os, re, time, zipfile
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

UA = "RadarBandi/0.1 (strumento di ricerca avvisi pubblici; github.com/Fabri-75/radar-bandi)"
S = requests.Session(); S.headers["User-Agent"] = UA
OUT = "verifica/out"; os.makedirs(OUT, exist_ok=True)
LOG = open(f"{OUT}/log.txt", "w")
def log(*a):
    t = " ".join(str(x) for x in a); print(t); LOG.write(t + "\n"); LOG.flush()

def get(url, **kw):
    try:
        r = S.get(url, timeout=kw.pop("timeout", 40), **kw)
        log(f"[{r.status_code}] {len(r.content):>9}B {r.headers.get('content-type','')[:40]} {url}")
        return r
    except Exception as e:
        log(f"[ERR] {url} {type(e).__name__}: {e}"); return None

def links(r, pat):
    if not r or not r.ok: return []
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        h = urljoin(r.url, a["href"])
        if re.search(pat, h + " " + a.get_text(" "), re.I): out.append((a.get_text(" ", strip=True)[:80], h))
    return out

def sezione(t): log("\n" + "=" * 70 + "\n" + t + "\n" + "=" * 70)

# ---------- ISTAT ----------
sezione("ISTAT elenco comuni")
r = get("https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.csv")
if r and r.ok:
    txt = r.content.decode("latin-1")
    rows = list(csv.reader(io.StringIO(txt), delimiter=";"))
    log("intestazione:", rows[0][:16])
    mb = [x for x in rows[1:] if "Monza" in ";".join(x)]
    log("righe MB:", len(mb)); log(mb[:2])

# ---------- IndicePA ----------
sezione("IndicePA (CKAN)")
r = get("https://indicepa.gov.it/ipa-dati/api/3/action/package_list")
if r and r.ok: log(r.text[:1500])
for pid in ["enti", "amministrazioni"]:
    r = get(f"https://indicepa.gov.it/ipa-dati/api/3/action/package_show?id={pid}")
    if r and r.ok:
        for res in r.json()["result"]["resources"]:
            log("  risorsa:", res.get("name"), res.get("format"), res.get("url"))
ipa_enti = None
try:
    r = S.get("https://indicepa.gov.it/ipa-dati/api/3/action/package_show?id=enti", timeout=40)
    for res in r.json()["result"]["resources"]:
        if (res.get("format") or "").lower() == "csv":
            rr = get(res["url"], timeout=120)
            if rr and rr.ok:
                ipa_enti = list(csv.DictReader(io.StringIO(rr.content.decode("utf-8-sig"))))
                log("colonne IPA:", list(ipa_enti[0].keys()))
                break
except Exception as e:
    log("IPA errore", e)
mb_ipa = []
if ipa_enti:
    for e in ipa_enti:
        if (e.get("Provincia") or "").upper() in ("MB",) or "MONZA" in (e.get("Provincia") or "").upper():
            mb_ipa.append(e)
    log("enti IPA in MB:", len(mb_ipa))
    from collections import Counter
    log(Counter(e.get("Codice_Categoria") or e.get("Tipologia") for e in mb_ipa).most_common(30))
    json.dump(mb_ipa, open(f"{OUT}/ipa_mb.json", "w"), ensure_ascii=False, indent=1)

# ---------- MIUR ----------
sezione("Ministero Istruzione - anagrafe scuole")
for u in ["https://dati.istruzione.it/opendata/opendata/catalogo/elements1/leaf/?area=Scuole&datasetId=DS0400SCUANAGRAFESTAT",
          "https://dati.istruzione.it/opendata/opendata/catalogo/elements1/leaf/?area=Scuole&datasetId=DS0410SCUANAGRAFEPAR"]:
    r = get(u)
    if r and r.ok:
        csvs = sorted(set(re.findall(r'[\w/.:-]*SCUANAGRAFE\w*\.csv', r.text)))
        log("csv trovati:", csvs[-6:])
        if csvs:
            uu = urljoin(u, csvs[-1])
            rr = get(uu, timeout=120)
            if rr and rr.ok:
                t = rr.content.decode("utf-8-sig", "replace")
                rd = list(csv.DictReader(io.StringIO(t)))
                log("colonne:", list(rd[0].keys()))
                mbs = [x for x in rd if (x.get("PROVINCIA") or "").upper().startswith("MONZA")]
                log("scuole MB:", len(mbs), "con sito:", sum(1 for x in mbs if (x.get("SITOWEBSCUOLA") or "").strip() not in ("", "Non Disponibile")))
                log(mbs[:2])
                json.dump(mbs, open(f"{OUT}/" + os.path.basename(uu) + ".mb.json", "w"), ensure_ascii=False, indent=1)

# ---------- ICCU ----------
sezione("ICCU anagrafe biblioteche")
for u in ["https://opendata.anagrafe.iccu.sbn.it/", "https://anagrafe.iccu.sbn.it/it/open-data/", "https://anagrafe.iccu.sbn.it/opendata/"]:
    r = get(u)
    for t, h in links(r, r"\.(csv|zip|json|xml)")[:20]: log("  ", t, h)

# ---------- ANAC ----------
sezione("ANAC open data e pubblicità legale")
r = get("https://dati.anticorruzione.it/opendata/api/3/action/package_list")
if r and r.ok: log(r.text[:3000])
r = get("https://pubblicitalegale.anticorruzione.it/")
if r and r.ok:
    log(r.text[:1500])
    for s in re.findall(r'src="([^"]+\.js)"', r.text)[:10]:
        rj = get(urljoin(r.url, s))
        if rj and rj.ok:
            for m in sorted(set(re.findall(r'["\'](/?api[^"\']{3,80})["\']', rj.text)))[:40]: log("   api:", m)
            for m in sorted(set(re.findall(r'https?://[a-z0-9.-]*anticorruzione[^"\'\s]{0,80}', rj.text)))[:30]: log("   host:", m)

# ---------- Sintel / Lombardia ----------
sezione("Sintel / Open data Lombardia")
get("https://www.sintel.regione.lombardia.it/eprocdata/sintelSearch.xhtml")
get("https://www.sintel.regione.lombardia.it/eprocdata/auctionSearch.xhtml")
r = get("https://www.dati.lombardia.it/api/catalog/v1?q=sintel&limit=20")
if r and r.ok:
    for x in r.json().get("results", []):
        log("  ", x["resource"]["name"], x["resource"]["id"], x["resource"].get("updatedAt"))

# ---------- Siti dei Comuni MB: piattaforme ----------
sezione("Comuni MB: homepage e link albo/trasparenza")
FIRME = {"halley": r"halley", "maggioli": r"maggioli|jcityweb|albo\.?pretorio\.?online", "pa digitale": r"padigitale|pa-digitale|urbi",
         "kibernetes/municipium": r"municipium|kibernetes", "gruppo spaggiari": r"spaggiari|scuoladigitale|scuolanext",
         "argo": r"argo(software|next)?\.", "axios": r"axios", "trasparenza-valutazione-merito": r"trasparenza-valutazione-merito|amministrazionetrasparente",
         "golem/nuvola": r"nuvola|madisoft", "dedagroup/civilia": r"civilia|deda", "insiel/apsystems": r"apsystems|insiel", "sielte": r"sielte",
         "portaleamministrazionetrasparente": r"portaleamministrazionetrasparente", "studio k": r"studiok|sk-", "eldasoft": r"eldasoft", "anthesi/comunica": r"anthesi"}
comuni = [e for e in mb_ipa if (e.get("Codice_Categoria") or "") in ("L6",) or "Comune" in (e.get("Tipologia_istat") or e.get("Categoria") or "")]
log("comuni trovati in IPA:", len(comuni))
rep = []
for e in comuni[:60]:
    site = (e.get("Sito_istituzionale") or "").strip()
    if not site: rep.append({"ente": e.get("Denominazione_ente"), "sito": "", "esito": "nessun sito"}); continue
    if not site.startswith("http"): site = "https://" + site
    time.sleep(1)
    r = get(site, timeout=25)
    rec = {"ente": e.get("Denominazione_ente"), "cf": e.get("Codice_fiscale_ente"), "sito": site, "stato": r.status_code if r else "ERR"}
    if r is not None and r.ok:
        low = r.text.lower()
        rec["piattaforme"] = [k for k, p in FIRME.items() if re.search(p, low)]
        rec["albo"] = [h for t, h in links(r, r"albo")][:3]
        rec["trasparenza"] = [h for t, h in links(r, r"trasparen")][:3]
        rec["bandi"] = [h for t, h in links(r, r"bandi|avvisi")][:4]
        rec["robots"] = None
        rb = get(urljoin(r.url, "/robots.txt"), timeout=15)
        if rb is not None and rb.ok: rec["robots"] = rb.text[:300]
        # Seguo il primo link all'albo per riconoscere la piattaforma
        if rec["albo"]:
            ra = get(rec["albo"][0], timeout=25)
            if ra is not None and ra.ok:
                rec["albo_finale"] = ra.url
                rec["albo_piattaforme"] = [k for k, p in FIRME.items() if re.search(p, (ra.url + ra.text).lower())]
                rec["albo_js"] = len(BeautifulSoup(ra.text, "html.parser").find_all("a")) < 15
    rep.append(rec)
json.dump(rep, open(f"{OUT}/comuni_mb.json", "w"), ensure_ascii=False, indent=1)
for x in rep: log(json.dumps({k: x.get(k) for k in ("ente", "stato", "piattaforme", "albo_finale", "albo_piattaforme", "albo_js")}, ensure_ascii=False))
log("\nFINE")
