"""Prova tecnica 3: scarica pagine campione delle piattaforme (HTML grezzo e, se serve, renderizzato)."""
import csv, io, json, os, re, time, zipfile
from urllib.parse import urljoin
import requests
UA = "RadarBandi/0.1 (+https://github.com/Fabri-75/radar-bandi)"
S = requests.Session(); S.headers["User-Agent"] = UA
OUT = "verifica/out"; os.makedirs(f"{OUT}/html", exist_ok=True)
LOG = open(f"{OUT}/log.txt", "w")
def log(*a):
    t = " ".join(str(x) for x in a); print(t); LOG.write(t + "\n"); LOG.flush()
def salva(nome, url, js=False):
    time.sleep(1.5)
    try:
        r = S.get(url, timeout=40)
        open(f"{OUT}/html/{nome}.html", "wb").write(r.content)
        log(f"[{r.status_code}] {len(r.content):>8} {nome} {r.url[:160]}")
        return r
    except Exception as e:
        log(f"[ERR] {nome} {url} {e}")

C = {
 "jcity_albiate": "https://albiate.trasparenza-valutazione-merito.it/web/trasparenza/albo-pretorio",
 "jcity_bernareggio": "https://bernareggio.trasparenza-valutazione-merito.it/web/trasparenza/albo-pretorio",
 "jcity_bandi_bernareggio": "https://bernareggio.trasparenza-valutazione-merito.it/web/trasparenza/papca-ap/-/papca/igrid/1/0",
 "jcity_trasp_bernareggio": "https://bernareggio.trasparenza-valutazione-merito.it/web/trasparenza/trasparenza",
 "urbi_agrate": "https://cloud.urbi.it/urbi/progs/urp/ur1ME001.sto?DB_NAME=n202182&w3cbt=S",
 "urbi_mezzago": "https://asp.urbi.it/urbi/progs/urp/ur1ME002.sto?DB_NAME=n200476",
 "dge_meda": "https://dgegovpa.it/meda/albo/albo",
 "dge_cavenago": "https://dgegovpa.it/Cavenagobrianza/albo/albo",
 "halley_camparada": "https://servizi.comune.camparada.mb.it/EG0/EGHOMEPAGE.HBL?ss=1&freeze=1&F=MC09",
 "halley_aicurzio": "https://www.halleyweb.com/c108002/zf/index.php/trasparenza/index/index/categoria/135",
 "halley_aicurzio_albo": "https://www.halleyweb.com/c108002/mc/mc_p_ricerca.php",
 "sicap_triuggio": "https://servizionline.hspromilaprod.hypersicapp.net/cmstriuggio/portale/albopretorio/albopretorioconsultazione.aspx?P=400",
 "sicap_biassono": "https://servizionline.biassono.org/cmsbiassono/portale/albopretorio/albopretorioconsultazione.aspx?P=400",
 "monza_albo": "https://www.comune.monza.it/it/page/albo-pretorio",
 "desio_albo": "https://www.comune.desio.mb.it/it/page/albo-pretorio-ddee5c69-eb3c-4763-8790-41a7cb287f5f",
 "cesano_albo": "https://www.comune.cesano-maderno.mb.it/albo-pretorio/",
 "seregno_albo": "https://servizi.comune.seregno.mb.it/openweb/albo/albo_pretorio.php",
 "seregno_home": "https://www.comune.seregno.mb.it/it",
 "bovisio_home": "https://comune.bovisiomasciago.mb.it/",
 "bovisio_avvisi": "https://comune.bovisiomasciago.mb.it/novita/notizia/tipologia/avviso/",
 "lissone_home": "https://www.comune.lissone.mb.it/",
 "limbiate_home": "https://www.comune.limbiate.mb.it/",
 "meda_home": "https://www.comune.meda.mb.it/home/index.html",
 "sc_rodari_albo": "https://www.scuolarodari.edu.it/albo-online",
 "sc_stoppani_albo": "https://www.icstoppaniseregno.edu.it/albo-online",
 "sc_cervi_albo": "https://www.iccervilimbiate.edu.it/albo-pretorio/",
 "sc_lentate_albo": "https://www.iclentate.edu.it/novita/albo-pretorio",
 "sc_trasparenzascuole": "https://www.trasparenzascuole.it/Public/APDPublic_ExtV2.aspx?CF=94581360156",
 "sc_trasparenzascuole_at": "https://www.trasparenzascuole.it/Public/AmministrazioneTrasparenteV2.aspx?Customer_ID=8c0ca9a6-f7b9-4d35-b430-1ed306c2cb9e",
 "sc_nuvola": "https://nuvola.madisoft.it/bacheca-digitale/bacheca/MIIC8EY003/1",
 "sc_argo": "https://www.portaleargo.it/albopretorio/online/#/?customerCode=SC9761",
 "sc_lissone1": "https://iclissoneprimo.edu.it/",
 "sc_lissone2": "https://www.iclissonesecondo.edu.it/",
 "sc_lissone3": "https://www.icdeamicislissone.edu.it/",
 "sc_lissone4": "https://www.icmonelissone.edu.it/",
 "sc_biassono": "https://www.iscobiassono.edu.it/",
 "sc_lesmo": "https://icslesmo.edu.it/",
 "mi_home": "https://www.comune.milano.it/",
 "mi_albo": "https://www.comune.milano.it/servizi/albo-pretorio-online",
 "mi_bandi": "https://www.comune.milano.it/aree-tematiche/bandi",
 "mi_municipio1": "https://www.comune.milano.it/municipi/municipio-1",
 "mi_avvisi": "https://www.comune.milano.it/web/bandi-e-avvisi",
 "brianzabiblio": "https://www.brianzabiblioteche.it/",
 "cubi": "https://www.cubinrete.it/",
 "anac_main": "https://pubblicitalegale.anticorruzione.it/main.115dac93231b9e02.js",
}
for k, u in C.items(): salva(k, u)

# ANAC: prova parametri
for q in ["avvisi?page=0&size=3", "avvisi?page=0&size=3&cfStazioneAppaltante=00870790151", "avvisi?page=0&size=3&codiceFiscale=00870790151",
          "avvisi?page=0&size=3&cpv=92312000", "avvisi?page=0&size=3&denominazioneStazioneAppaltante=SEREGNO"]:
    salva("anac_" + re.sub(r"\W", "_", q)[:60], "https://pubblicitalegale.anticorruzione.it/api/v0/" + q)

# ICCU: biblioteche MB con url
r = S.get("https://opendata.anagrafe.iccu.sbn.it/territorio.zip", timeout=120)
z = zipfile.ZipFile(io.BytesIO(r.content)); t = z.read(z.namelist()[0]).decode("utf-8-sig", "replace")
rows = [x for x in csv.DictReader(io.StringIO(t), delimiter=";") if x["provincia"].startswith("Monza")]
json.dump(rows, open(f"{OUT}/iccu_mb.json", "w"), ensure_ascii=False, indent=1)
log("biblioteche MB", len(rows))

# Pagine JS con browser automatico
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(user_agent=UA)
        for k in ["sc_argo", "seregno_albo", "dge_meda", "mi_albo"]:
            try:
                pg.goto(C[k], timeout=60000, wait_until="networkidle"); time.sleep(3)
                open(f"{OUT}/html/{k}_render.html", "w").write(pg.content()); log("render ok", k, pg.url)
            except Exception as e: log("render ERR", k, e)
        b.close()
except Exception as e:
    log("playwright ERR", e)
log("FINE")
