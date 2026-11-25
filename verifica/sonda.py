"""Prova tecnica 2: IndicePA, ANAC, Sintel, ICCU e piattaforme di albo dei siti MB."""
import csv, io, json, os, re, time, zipfile
from collections import Counter
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

UA = "RadarBandi/0.1 (+https://github.com/Fabri-75/radar-bandi)"
BUA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15 RadarBandi/0.1"
S = requests.Session(); S.headers["User-Agent"] = UA
OUT = "verifica/out"; os.makedirs(OUT, exist_ok=True)
LOG = open(f"{OUT}/log.txt", "w")
def log(*a):
    t = " ".join(str(x) for x in a); print(t); LOG.write(t + "\n"); LOG.flush()
def get(url, ua=None, **kw):
    try:
        h = {"User-Agent": ua} if ua else {}
        r = S.get(url, timeout=kw.pop("timeout", 40), headers=h, **kw)
        log(f"[{r.status_code}] {len(r.content):>9}B {r.headers.get('content-type','')[:35]} {url[:200]}")
        return r
    except Exception as e:
        log(f"[ERR] {url[:200]} {type(e).__name__}: {str(e)[:150]}"); return None
def sezione(t): log("\n" + "=" * 70 + "\n" + t + "\n" + "=" * 70)

# ---------- IndicePA ----------
sezione("IndicePA amministrazioni.txt")
r = get("https://indicepa.gov.it/ipa-dati/dataset/502ff370-1b2c-4310-94c7-f39ceb7500e3/resource/3ed63523-ff9c-41f6-a6fe-980f3d9e501f/download/amministrazioni.txt", timeout=120)
ipa = []
if r and r.ok:
    t = r.content.decode("utf-8-sig", "replace")
    first = t.splitlines()[0]; log("intestazione:", first[:600])
    delim = "\t" if "\t" in first else (";" if ";" in first else ",")
    ipa = list(csv.DictReader(io.StringIO(t), delimiter=delim))
    log("righe:", len(ipa), "colonne:", list(ipa[0].keys()))
prov_key = next((k for k in (ipa[0].keys() if ipa else []) if "prov" in k.lower()), None)
mb = [e for e in ipa if (e.get(prov_key) or "").strip().upper() == "MB"]
log("enti in MB:", len(mb))
cat_key = next((k for k in (ipa[0].keys() if ipa else []) if "categ" in k.lower()), None)
tip_key = next((k for k in (ipa[0].keys() if ipa else []) if "tipolog" in k.lower()), None)
log(Counter(e.get(cat_key) for e in mb).most_common(40))
log(Counter(e.get(tip_key) for e in mb).most_common(20))
json.dump(mb, open(f"{OUT}/ipa_mb.json", "w"), ensure_ascii=False, indent=1)

# ---------- ANAC ----------
sezione("ANAC")
for ua in (UA, BUA):
    get("https://dati.anticorruzione.it/opendata/api/3/action/package_list", ua=ua)
    get("https://dati.anticorruzione.it/opendata/dataset", ua=ua)
r = get("https://pubblicitalegale.anticorruzione.it/main.115dac93231b9e02.js")
if r and r.ok:
    js = r.text
    for m in sorted(set(re.findall(r'["\'`](/[a-zA-Z0-9_/${}.-]{4,90})["\'`]', js))):
        if re.search(r"avvis|bando|ricerca|search|atti|pubblic|esiti|cpv|stazion|api", m, re.I): log("  path:", m)
    i = js.find("api/v0")
    while i != -1 and i < len(js):
        log("  ctx:", js[max(0, i - 200): i + 300].replace("\n", " "))
        i = js.find("api/v0", i + 1)
        if i > 0 and js.count("api/v0", 0, i) > 6: break
for u in ["https://pubblicitalegale.anticorruzione.it/api/v0/avvisi?page=0&size=5",
          "https://pubblicitalegale.anticorruzione.it/api/v0/avvisi/search?page=0&size=5",
          "https://pubblicitalegale.anticorruzione.it/api/v0/atti?page=0&size=5"]:
    r = get(u)
    if r is not None: log("   ", r.text[:600])

# ---------- Sintel ----------
sezione("Sintel open data")
for ds in ["8txy-zjw2", "exjq-zwsd"]:
    r = get(f"https://www.dati.lombardia.it/resource/{ds}.json?$limit=3&$order=:updated_at DESC")
    if r and r.ok:
        d = r.json(); log("campi:", list(d[0].keys()) if d else d); log(json.dumps(d[:2], ensure_ascii=False)[:2500])
r = get("https://www.dati.lombardia.it/resource/8txy-zjw2.json?$limit=50000&$where=" + requests.utils.quote("upper(provincia_ente) like '%MONZA%' OR upper(provincia) like '%MONZA%'"), timeout=120)
if r is not None: log(r.text[:800])

# ---------- ICCU ----------
sezione("ICCU biblioteche MB")
r = get("https://opendata.anagrafe.iccu.sbn.it/opendata.zip", timeout=180)
if r and r.ok:
    z = zipfile.ZipFile(io.BytesIO(r.content))
    for n in z.namelist(): log("  file:", n, z.getinfo(n).file_size)
    for n in z.namelist():
        if n.lower().endswith(".csv"):
            t = z.read(n).decode("utf-8-sig", "replace")
            log(" ", n, "->", t.splitlines()[0][:400])
    for n in z.namelist():
        if re.search(r"bibliotech|territor|contatt|indirizz", n, re.I) and n.lower().endswith(".csv"):
            t = z.read(n).decode("utf-8-sig", "replace")
            righe = [l for l in t.splitlines() if "Monza" in l or ";MB;" in l or ",MB," in l]
            log(f"  {n}: righe MB {len(righe)}"); [log("    ", l[:300]) for l in righe[:4]]

# ---------- Siti ----------
FIRME = {"halley": r"halley", "maggioli": r"maggioli|jcityweb|sicraweb", "pa digitale": r"padigitale|pa-digitale|urbi\b|urbismart",
         "municipium": r"municipium", "spaggiari": r"spaggiari|scuoladigitale|sissiweb", "argo": r"argofamiglia|portaleargo|argosoft|albo.*argo|argo.*albo",
         "axios": r"axios", "nuvola/madisoft": r"nuvola\.madisoft|madisoft", "trasparenza-scuole PA": r"trasparenza-pa|portaleamministrazionetrasparente",
         "dedagroup/civilia": r"civilianext|civilia", "apsystems": r"apsystems", "eldasoft": r"eldasoft", "studiok": r"studiok",
         "gruppo zeta/ilcomune": r"ilcomune\.it|e-office", "golem": r"golem", "soluzionipa/servizipa": r"servizipa|soluzionipa", "proxima": r"proxima",
         "wordpress": r"wp-content", "drupal": r"drupal", "pasw/porte aperte": r"pasw|porte aperte sul web", "itcloud/mediaspot": r"mediaspot",
         "comunicaweb/insiel": r"insiel", "datagraph": r"datagraph", "albipretori.it/plugin": r"albo-pretorio|albopretorio"}
def sonda_sito(nome, site):
    if not site: return {"ente": nome, "esito": "nessun sito"}
    if not site.startswith("http"): site = "https://" + site.strip("/")
    time.sleep(1.5)
    r = get(site, timeout=25)
    if (r is None or not r.ok) and site.startswith("https://"):
        r = get("http://" + site[8:], timeout=25)
    rec = {"ente": nome, "sito": site, "stato": r.status_code if r is not None else "ERR"}
    if r is None or not r.ok: return rec
    rec["finale"] = r.url
    soup = BeautifulSoup(r.text, "html.parser")
    rec["piattaforme_home"] = [k for k, p in FIRME.items() if re.search(p, r.text, re.I)]
    al = []
    for a in soup.find_all("a", href=True):
        tx = (a.get_text(" ", strip=True) + " " + a["href"]).lower()
        if re.search(r"albo|trasparen|bandi|avvis", tx): al.append((a.get_text(" ", strip=True)[:50], urljoin(r.url, a["href"])))
    rec["link"] = al[:8]
    alb = next((h for t, h in al if "albo" in (t + h).lower()), None)
    if alb:
        time.sleep(1.5); ra = get(alb, timeout=25)
        if ra is not None:
            rec["albo"] = ra.url; rec["albo_stato"] = ra.status_code
            rec["albo_host"] = urlparse(ra.url).netloc
            rec["albo_piattaforme"] = [k for k, p in FIRME.items() if re.search(p, ra.url + ra.text[:200000], re.I)]
            s2 = BeautifulSoup(ra.text, "html.parser")
            rec["albo_n_link"] = len(s2.find_all("a")); rec["albo_iframe"] = [i.get("src") for i in s2.find_all("iframe")][:2]
            rec["albo_righe_tabella"] = len(s2.find_all("tr"))
    return rec

sezione("Comuni MB")
com = [e for e in mb if re.search(r"comun", (e.get(cat_key) or "") + (e.get(tip_key) or ""), re.I) and not re.search(r"unione", (e.get(cat_key) or ""), re.I)]
log("comuni:", len(com))
sito_key = next((k for k in (ipa[0].keys() if ipa else []) if "sito" in k.lower()), None)
den_key = next((k for k in (ipa[0].keys() if ipa else []) if "denomin" in k.lower()), None)
rep = [sonda_sito(e.get(den_key), e.get(sito_key)) for e in com[:60]]
json.dump(rep, open(f"{OUT}/comuni_mb.json", "w"), ensure_ascii=False, indent=1)
log(Counter(h for x in rep for h in x.get("albo_piattaforme", [])).most_common())
log(Counter(x.get("albo_host", "-") for x in rep).most_common(40))

sezione("Scuole statali MB (istituti principali, campione 40)")
sc = json.load(open("verifica/scuole_stat_mb.json")) if os.path.exists("verifica/scuole_stat_mb.json") else []
if not sc:
    r = get("https://dati.istruzione.it/opendata/opendata/catalogo/elements1/leaf/SCUANAGRAFESTAT20262720260901.csv", timeout=120)
    rd = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig", "replace"))))
    sc = [x for x in rd if x["PROVINCIA"].startswith("MONZA")]
ist = {}
for x in sc:
    k = x["CODICEISTITUTORIFERIMENTO"]
    if k not in ist and x.get("SITOWEBSCUOLA", "").strip() not in ("", "Non Disponibile"):
        ist[k] = (x["DENOMINAZIONEISTITUTORIFERIMENTO"], x["SITOWEBSCUOLA"].strip())
log("istituti con sito:", len(ist), "su", len({x['CODICEISTITUTORIFERIMENTO'] for x in sc}))
reps = [sonda_sito(n, s) for n, s in list(ist.values())[:40]]
json.dump(reps, open(f"{OUT}/scuole_mb.json", "w"), ensure_ascii=False, indent=1)
log(Counter(h for x in reps for h in x.get("albo_piattaforme", [])).most_common())
log(Counter(x.get("albo_host", "-") for x in reps).most_common(40))
log("\nFINE")
