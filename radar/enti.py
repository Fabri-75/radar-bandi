"""Costruisce l'elenco degli enti di una provincia, dalle fonti ufficiali + i siti aggiunti a mano."""
import csv
import io
import re
import zipfile
from urllib.parse import urlparse

from .rete import normalizza_url
from .testo import semplice

ISTAT = "https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.csv"
IPA = ("https://indicepa.gov.it/ipa-dati/dataset/502ff370-1b2c-4310-94c7-f39ceb7500e3/resource/"
       "3ed63523-ff9c-41f6-a6fe-980f3d9e501f/download/amministrazioni.txt")
MIUR_PAGINA = "https://dati.istruzione.it/opendata/opendata/catalogo/elements1/leaf/?area=Scuole&datasetId={}"
MIUR_FILE = "https://dati.istruzione.it/opendata/opendata/catalogo/elements1/leaf/{}"
ICCU = "https://opendata.anagrafe.iccu.sbn.it/opendata.zip"


def host(u):
    h = urlparse(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def nome_provincia(rete, sigla):
    """Dal file ISTAT: nome della provincia (es. 'Monza e della Brianza') e codici ISTAT dei suoi comuni."""
    r, err = rete.get(ISTAT, controlla_robots=False, timeout=90)
    if err:
        raise RuntimeError(f"ISTAT non raggiungibile: {err}")
    righe = list(csv.reader(io.StringIO(r.content.decode("latin-1")), delimiter=";"))
    testa = righe[0]
    i_sigla = next(i for i, c in enumerate(testa) if "Sigla automobilistica" in c)
    i_uts = next(i for i, c in enumerate(testa) if c.startswith("Denominazione dell'Unit"))
    i_com = next(i for i, c in enumerate(testa) if c.strip() == "Denominazione in italiano")
    mie = [x for x in righe[1:] if len(x) > i_sigla and x[i_sigla].strip().upper() == sigla]
    if not mie:
        raise RuntimeError(f"Provincia {sigla} non trovata nel file ISTAT")
    return mie[0][i_uts].strip(), [x[i_com].strip() for x in mie]


def _stesso_nome(a, b):
    a, b = semplice(a), semplice(b)
    a = re.sub(r"\b(e della|della|e|di|del)\b", " ", a); b = re.sub(r"\b(e della|della|e|di|del)\b", " ", b)
    return a.split() == b.split() or a.replace(" ", "") == b.replace(" ", "")


def carica(rete, sigla, imp, extra_csv="siti_extra.csv"):
    """Ritorna (enti, note). Ogni ente: id, nome, tipo, cf, sito, comune, fonte."""
    note = []
    nome_prov, comuni = nome_provincia(rete, sigla)
    enti = {}

    def aggiungi(e):
        e["sito"] = normalizza_url(e.get("sito", ""))
        k = (e["tipo"], host(e["sito"]) if e["sito"] else semplice(e["nome"]))
        if k in enti:
            vecchio = enti[k]
            for c in ("cf", "comune"):
                vecchio[c] = vecchio.get(c) or e.get(c)
            return
        e["id"] = f"{e['tipo'][:3].lower()}-{len(enti) + 1}"
        enti[k] = e

    # --- IndicePA: Comuni, scuole, Unioni e consorzi ---
    r, err = rete.get(IPA, controlla_robots=False, timeout=120)
    ipa_scuole = {}
    if err:
        note.append(f"IndicePA non raggiungibile ({err})")
    else:
        rd = csv.DictReader(io.StringIO(r.content.decode("utf-8-sig", "replace")), delimiter="\t")
        for x in rd:
            if (x.get("Provincia") or "").strip().upper() != sigla:
                continue
            tip, nome = x.get("tipologia_istat") or "", (x.get("des_amm") or "").strip()
            base = {"nome": nome, "cf": (x.get("cf") or "").strip(), "sito": x.get("sito_istituzionale") or "",
                    "comune": (x.get("Comune") or "").title(), "fonte": "IndicePA"}
            if tip.startswith("Comuni") and nome.lower().startswith("comune di"):
                aggiungi({**base, "tipo": "Comune"})
            elif tip.startswith("Istituti di Istruzione"):
                ipa_scuole[host(normalizza_url(base["sito"]))] = base
            elif re.match(r"(Unioni di Comuni|Consorzi tra Amministrazioni|Comuni e loro Consorzi)", tip):
                if not re.search(r"in liquidazione", nome, re.I):
                    aggiungi({**base, "tipo": "Altro ente"})

    # --- Ministero: scuole statali (una riga per istituto) ---
    def miur(ds, paritarie=False):
        r, err = rete.get(MIUR_PAGINA.format(ds), controlla_robots=False, timeout=60)
        if err:
            note.append(f"Open data Ministero ({ds}) non raggiungibili ({err})"); return
        files = sorted(set(re.findall(r"SCUANAGRAFE\w+\.csv", r.text)))
        if not files:
            note.append(f"Open data Ministero ({ds}): nessun file trovato"); return
        r, err = rete.get(MIUR_FILE.format(files[-1]), controlla_robots=False, timeout=180)
        if err:
            note.append(f"File {files[-1]} non scaricabile ({err})"); return
        visti = set()
        for x in csv.DictReader(io.StringIO(r.content.decode("utf-8-sig", "replace"))):
            if not _stesso_nome(x.get("PROVINCIA", ""), nome_prov):
                continue
            cod = x.get("CODICEISTITUTORIFERIMENTO") or x.get("CODICESCUOLA")
            if cod in visti:
                continue
            visti.add(cod)
            sito = normalizza_url(x.get("SITOWEBSCUOLA", ""))
            nome = x.get("DENOMINAZIONEISTITUTORIFERIMENTO") or x.get("DENOMINAZIONESCUOLA")
            ip = ipa_scuole.pop(host(sito), None) if sito else None
            comune = (x.get("DESCRIZIONECOMUNE") or "").title()
            nome = (nome or "").strip()
            if comune and semplice(comune) not in semplice(nome):
                nome += f" ({comune})"
            alt = normalizza_url(ip["sito"]) if ip else ""
            aggiungi({"tipo": "Scuola", "nome": nome + ("" if not paritarie else " – paritaria"),
                      "cf": ip["cf"] if ip else "", "sito": sito or alt, "sito_alt": alt if alt and host(alt) != host(sito) else "",
                      "comune": (x.get("DESCRIZIONECOMUNE") or "").title(), "codice": cod,
                      "fonte": "Ministero" + (" + IndicePA" if ip else "")})
    miur("DS0400SCUANAGRAFESTAT")
    if str(imp.get("paritarie", "no")).lower() in ("si", "sì", "true", "yes"):
        miur("DS0410SCUANAGRAFEPAR", paritarie=True)
    for ip in ipa_scuole.values():   # scuole in IndicePA ma non trovate nel file del Ministero
        aggiungi({**ip, "tipo": "Scuola"})

    # --- ICCU: biblioteche pubbliche/comunali ---
    r, err = rete.get(ICCU, controlla_robots=False, timeout=240)
    if err:
        note.append(f"Anagrafe biblioteche ICCU non raggiungibile ({err})")
    else:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        leggi = lambda n: list(csv.DictReader(io.StringIO(z.read(n).decode("utf-8-sig", "replace")), delimiter=";"))
        tipi = {x["codice isil"]: x for x in leggi("tipologie.csv")}
        for x in leggi("territorio.csv"):
            if not _stesso_nome(x.get("provincia", ""), nome_prov):
                continue
            t = tipi.get(x["codice-isil"], {})
            amm, fun = semplice(t.get("tipologia amministrativa", "")), semplice(t.get("tipologia funzionale", ""))
            if not ("comun" in amm or "pubblica" in fun or "consorz" in amm or "sistem" in amm):
                continue
            aggiungi({"tipo": "Biblioteca", "nome": x["denominazione"].strip(), "cf": "", "sito": x.get("url", ""),
                      "comune": x.get("comune", "").strip(), "fonte": "ICCU"})

    # --- Siti aggiunti o tolti a mano ---
    try:
        with open(extra_csv, encoding="utf-8") as f:
            for x in csv.DictReader(f):
                if (x.get("provincia_ricerca") or "").strip().upper() != sigla:
                    continue
                if (x.get("azione") or "").strip().lower().startswith("togli"):
                    h = host(normalizza_url(x.get("sito", "")))
                    for k in [k for k, e in enti.items() if (h and host(e["sito"]) == h) or semplice(e["nome"]) == semplice(x.get("nome", ""))]:
                        enti.pop(k)
                else:
                    aggiungi({"tipo": (x.get("tipo") or "Altro ente").strip(), "nome": x["nome"].strip(),
                              "cf": (x.get("codice_fiscale") or "").strip(), "sito": x.get("sito", ""),
                              "comune": "", "fonte": "aggiunto a mano"})
    except FileNotFoundError:
        pass

    lista = list(enti.values())
    # Una biblioteca senza sito proprio pubblica sul sito del Comune: lo segnalo
    siti_comuni = {semplice(e["comune"] or e["nome"].replace("Comune di ", "")): e for e in lista if e["tipo"] == "Comune"}
    host_comuni = {host(e["sito"]): e for e in lista if e["tipo"] == "Comune" and e["sito"]}
    for e in lista:
        if e["tipo"] == "Biblioteca" and e["sito"] and host(e["sito"]) in host_comuni:
            e["nota"] = f"pubblica sul sito del {host_comuni[host(e['sito'])]['nome']} (letto con il Comune)"
            e["sito"] = ""
            e["coperto"] = True
            continue
        if e["tipo"] == "Biblioteca" and not e["sito"]:
            c = siti_comuni.get(semplice(e["comune"]))
            e["nota"] = f"senza sito proprio: avvisi sul sito del {c['nome']}" if c else "senza sito proprio"
    return nome_prov, lista, note
