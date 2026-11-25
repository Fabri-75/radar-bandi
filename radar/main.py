"""Radar Bandi: ricerca degli avvisi utili per una provincia.

Uso:  python -m radar.main MB
Scrive docs/dati/<SIGLA>.json (risultati + copertura) e aggiorna docs/dati/province.json.
"""
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import yaml

from . import enti as E
from .filtro import Filtro
from .lettori import leggi_ente
from .fonti_nazionali import anac, sintel
from .rete import Rete
from .testo import semplice, testo_pdf, trova_cig, trova_date, trova_destinatari, trova_importo, trova_scadenza

DATI = "docs/dati"
MAX_DETTAGLI = 25   # pagine di dettaglio/PDF aperte al massimo per ente


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def _id(ente, titolo, link):
    base = semplice(ente) + "|" + re.sub(r"[^a-z0-9]", "", semplice(titolo))[:90]
    return hashlib.sha1(base.encode()).hexdigest()[:12]


def arricchisci(rete, v, flt):
    """Apre la pagina di dettaglio e i PDF per leggere scadenza, importo e destinatari."""
    testi, pdf = [], []
    allegati = list(v.get("allegati") or [])
    aperti = 0
    if v.get("link") and not v["link"].lower().split("?")[0].endswith(".pdf") and v.get("apri_dettaglio", True):
        r, err = rete.get(v["link"])
        aperti += 1
        if r is not None and not err:
            ct = r.headers.get("content-type", "")
            if "pdf" in ct:
                pdf.append(testo_pdf(r.content))
            elif "html" in ct or "text" in ct:
                from .lettori.generico import testo_e_allegati
                t, alls = testo_e_allegati(r.text, r.url)
                testi.append(t)
                allegati += alls
    elif v.get("link", "").lower().split("?")[0].endswith(".pdf"):
        allegati.insert(0, v["link"])
    for a in allegati[:3]:
        r, err = rete.get(a)
        aperti += 1
        if r is not None and not err and (b"%PDF" in r.content[:1024]):
            pdf.append(testo_pdf(r.content))
    v["testo_dettaglio"] = "\n".join(t for t in testi if t)
    v["testo_pdf"] = "\n".join(t for t in pdf if t)
    return aperti


def valuta(v, flt, oggi, limite):
    """Decide se tenere l'avviso. Ritorna la riga per la tabella oppure None."""
    tit = re.sub(r"\s*[–-]\s*N/?D\s*$", "", v["titolo"]).strip()
    if flt.scartato(tit):
        return None
    # Testo dell'atto: PDF e pagina di dettaglio (senza menu del sito). Il testo della riga d'elenco serve solo per le date.
    testo = "\n".join(x for x in (tit, v.get("testo_pdf"), v.get("testo_dettaglio")) if x)
    arg_tit = flt.argomenti(tit)
    arg_txt = []
    if not arg_tit and flt.generico(tit):
        arg_txt = flt.argomenti_forti("\n".join(x for x in (v.get("testo_pdf"), v.get("testo_dettaglio")) if x)[:30000])
    cpv_ok = flt.cpv_utile(v.get("cpv"))
    if not (arg_tit or arg_txt or cpv_ok):
        return None
    # Dai siti tengo solo atti e avvisi, non le notizie sugli eventi
    if v.get("fonte", "").startswith("sito") and not flt.e_atto(tit):
        return None
    pub = v.get("pubblicazione")
    scad = v.get("scadenza") or trova_scadenza(testo, dopo=pub)
    if scad and pub and (scad - pub).days > 400:
        scad = None
    if pub and pub < limite and not (scad and scad >= oggi):
        return None
    motivi = list(dict.fromkeys(arg_tit + arg_txt + flt.forme(tit)))
    if cpv_ok:
        motivi.append(f"CPV {v.get('cpv')}")
    tipo = v["tipo"]
    if tipo == "Comune" and re.search(r"bibliotec", semplice(tit)):
        tipo = "Biblioteca"
    return {
        "ente": v["ente"], "tipo": tipo, "titolo": tit[:300],
        "pubblicazione": pub.isoformat() if pub else None,
        "scadenza": scad.isoformat() if scad else None,
        "importo": v.get("importo") or trova_importo(testo),
        "partecipanti": trova_destinatari(testo),
        "motivi": motivi[:8],
        "temi": flt.temi(tit + " " + " ".join(arg_txt)) or (["Teatro e spettacoli"] if cpv_ok else []),
        "link": v["link"],
        "fonti": [{"nome": v.get("fonte", "sito"), "link": v["link"]}],
        "esito": flt.e_esito(tit) or bool(v.get("esito_anac")),
        "cig": v.get("cig") or trova_cig(tit + " " + testo[:5000]),
        "cf": v.get("cf"),
    }


def lavora_ente(rete, ente, flt, oggi, limite):
    t0 = time.time()
    voci, pagine, errore = leggi_ente(rete, ente, limite)
    righe, aperti = [], 0
    for v in voci:
        v.setdefault("ente", ente["nome"]); v.setdefault("tipo", ente["tipo"]); v.setdefault("cf", ente.get("cf"))
        if flt.scartato(v["titolo"]):
            continue
        if v.get("pubblicazione") and v["pubblicazione"] < limite and not (v.get("scadenza") and v["scadenza"] >= oggi):
            continue
        promettente = flt.argomenti(v["titolo"]) or flt.generico(v["titolo"])
        if promettente and aperti < MAX_DETTAGLI:
            aperti += arricchisci(rete, v, flt)
        r = valuta(v, flt, oggi, limite)
        if r:
            righe.append(r)
    cop = {"nome": ente["nome"], "tipo": ente["tipo"], "sito": ente.get("sito"),
           "esito": "letto" if pagine else "non letto",
           "motivo": errore or ente.get("nota") or ("" if pagine else "sezione avvisi non trovata"),
           "pagine": pagine[:6], "voci": len(voci), "trovati": len(righe), "secondi": round(time.time() - t0)}
    return righe, cop


def unisci(righe):
    """Elimina i doppioni (stesso CIG, oppure stesso ente e titolo)."""
    out, per_chiave = [], {}
    for r in righe:
        cig_ok = r.get("cig") and re.fullmatch(r"[0-9A-Z]{10}", str(r["cig"]).upper())
        chiavi = [k for k in (("cig", r["cig"]) if cig_ok else None,
                              ("t", semplice(r["ente"])[:30], re.sub(r"[^a-z0-9]", "", semplice(r["titolo"]))[:70])) if k]
        gia = next((per_chiave[k] for k in chiavi if k in per_chiave), None)
        if gia:
            for f in r["fonti"]:
                if f["link"] not in [x["link"] for x in gia["fonti"]]:
                    gia["fonti"].append(f)
            for c in ("scadenza", "importo", "partecipanti", "pubblicazione"):
                gia[c] = gia.get(c) or r.get(c)
            gia["motivi"] = list(dict.fromkeys(gia["motivi"] + r["motivi"]))[:8]
            gia["temi"] = list(dict.fromkeys(gia.get("temi", []) + r.get("temi", [])))
            gia["esito"] = gia["esito"] and r["esito"]
        else:
            out.append(r); gia = r
        for k in chiavi:
            per_chiave[k] = gia
    return out


def main(sigla):
    sigla = sigla.strip().upper()[:2]
    imp = yaml.safe_load(open("impostazioni.yml", encoding="utf-8"))
    flt = Filtro(imp)
    oggi = date.today()
    limite = oggi - timedelta(days=int(imp.get("giorni", 60)))
    rete = Rete(pausa=float(imp.get("pausa_secondi", 1.5)))
    t0 = time.time()

    nome_prov, enti, note = E.carica(rete, sigla, imp)
    log(f"{nome_prov}: {len(enti)} enti", {t: sum(1 for e in enti if e['tipo'] == t) for t in {e['tipo'] for e in enti}})

    righe, coperture = [], []
    with_site = [e for e in enti if e.get("sito")]
    for e in enti:
        if not e.get("sito"):
            coperture.append({"nome": e["nome"], "tipo": e["tipo"], "sito": "", "esito": "letto" if e.get("coperto") else "non letto",
                              "motivo": e.get("nota") or "nessun sito indicato negli open data", "pagine": [], "trovati": 0})
    with ThreadPoolExecutor(max_workers=int(imp.get("siti_in_parallelo", 10))) as ex:
        fut = {ex.submit(lavora_ente, rete, e, flt, oggi, limite): e for e in with_site}
        # (ogni ente ha comunque tempi massimi per pagina; il browser è uno solo)
        for i, f in enumerate(as_completed(fut), 1):
            e = fut[f]
            try:
                rr, cop = f.result()
            except Exception as ex_:  # un sito che si rompe non deve fermare la ricerca
                rr, cop = [], {"nome": e["nome"], "tipo": e["tipo"], "sito": e.get("sito"), "esito": "non letto",
                               "motivo": f"errore del lettore ({type(ex_).__name__})", "pagine": [], "trovati": 0}
            righe += rr; coperture.append(cop)
            log(f"[{i}/{len(with_site)}] {e['nome'][:45]:45} {cop['esito']:9} voci={cop.get('voci', 0):3} utili={cop['trovati']:2} {cop['motivo'][:60]}")

    fonti = []
    per_cf = {e["cf"]: e for e in enti if e.get("cf")}
    for nome, fn in (("ANAC pubblicità legale", anac), ("Sintel Lombardia", sintel)):
        try:
            voci = fn(rete, per_cf, flt, limite)
            n = 0
            for v in voci:
                r = valuta(v, flt, oggi, limite)
                if r:
                    righe.append(r); n += 1
            fonti.append({"nome": nome, "ok": True, "trovati": n, "letti": len(voci)})
            log(f"{nome}: {len(voci)} avvisi letti, {n} utili")
        except Exception as ex_:
            fonti.append({"nome": nome, "ok": False, "errore": f"{type(ex_).__name__}: {str(ex_)[:120]}"})
            log(f"{nome}: ERRORE {ex_}")

    from .lettori import RENDERER
    RENDERER.chiudi()
    righe = unisci(righe)
    # nuovi rispetto alla ricerca precedente
    os.makedirs(DATI, exist_ok=True)
    file = f"{DATI}/{sigla}.json"
    prima = set()
    if os.path.exists(file) and os.environ.get("RADAR_RIPARTI") != "1":
        try:
            prima = {r["id"] for r in json.load(open(file, encoding="utf-8"))["righe"]}
        except Exception:
            pass
    for r in righe:
        r["id"] = _id(r["ente"], r["titolo"], r["link"])
        r["nuovo"] = bool(prima) and r["id"] not in prima
    # Gli albi tolgono gli atti dopo 15 giorni: tengo gli avvisi trovati prima se sono ancora aperti
    if prima:
        ora = {r["id"] for r in righe}
        for r in json.load(open(file, encoding="utf-8"))["righe"]:
            if r["id"] in ora:
                continue
            if (r.get("scadenza") and r["scadenza"] >= oggi.isoformat()) or (r.get("pubblicazione") and r["pubblicazione"] >= limite.isoformat()):
                r["nuovo"] = False
                righe.append(r)
    righe.sort(key=lambda r: (r["scadenza"] or "9999", r["pubblicazione"] or ""))

    coperture.sort(key=lambda c: (c["esito"] == "letto", c["tipo"], c["nome"]))
    out = {"provincia": {"sigla": sigla, "nome": nome_prov}, "aggiornato": datetime.now(timezone.utc).isoformat(),
           "giorni": int(imp.get("giorni", 60)), "durata_minuti": round((time.time() - t0) / 60),
           "richieste": rete.richieste, "righe": righe,
           "copertura": {"enti": coperture, "fonti": fonti, "note": note}}
    json.dump(out, open(file, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)

    from .indice import scrivi_indice
    scrivi_indice(DATI)
    letti = sum(1 for c in coperture if c["esito"] == "letto")
    log(f"FINE: {len(righe)} avvisi utili, {letti}/{len(coperture)} siti letti, {rete.richieste} richieste, {out['durata_minuti']} min")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "MB")
