"""Rinforzi: ANAC (pubblicità a valore legale) e Sintel (Regione Lombardia, open data)."""
import json
from datetime import date, datetime

from .testo import semplice

ANAC = "https://pubblicitalegale.anticorruzione.it/api/v0/avvisi-full-text-specializzata"
ANAC_LINK = "https://pubblicitalegale.anticorruzione.it/bandi/{}"
SINTEL = "https://www.dati.lombardia.it/resource/8txy-zjw2.json"
SINTEL_ESITI = "https://www.dati.lombardia.it/resource/exjq-zwsd.json"
CPV_ANAC = ["92312000", "92312100", "92312200", "92300000", "79952100", "79952000", "92310000", "92511000", "80500000"]


def _d(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except ValueError:
        return None


def anac(rete, per_cf, flt, limite):
    """Avvisi ANAC con CPV utili, pubblicati dopo 'limite', di enti della provincia."""
    out, visti = [], set()
    for cpv in CPV_ANAC:
        token = None
        for pagina in range(10):
            par = {"page": pagina, "pageSize": 50, "cpv": cpv, "operatore": "AND", "sortField": "dataPubblicazione",
                   "sortDirection": "desc", "dataPubblicazioneStart": limite.strftime("%d/%m/%Y"),
                   "dataPubblicazioneEnd": date.today().strftime("%d/%m/%Y")}
            if token:
                par.update({"direzionePaginazione": "AVANTI", "tokenPaginazione": token})
            r, err = rete.get(ANAC, controlla_robots=False, params=par, timeout=60)
            if err:
                if pagina == 0 and cpv == CPV_ANAC[0]:
                    raise RuntimeError(f"ANAC non risponde ({err})")
                break
            d = r.json()
            righe = d.get("content") or []
            for a in righe:
                if a.get("idAvviso") in visti:
                    continue
                visti.add(a.get("idAvviso"))
                v = _da_anac(a, per_cf)
                if v:
                    out.append(v)
            token = d.get("lastPaginationToken")
            if not righe or not token or len(righe) < 50:
                break
    return out


def _da_anac(a, per_cf):
    cfs, titolo, desc, cig, link_doc, luogo = [], None, None, None, None, ""
    for t in a.get("templates") or []:
        tpl = t.get("template") or {}
        meta = tpl.get("metadata") or {}
        titolo = titolo or meta.get("titolo")
        desc = desc or meta.get("descrizione")
        for s in tpl.get("sections") or []:
            f = s.get("fields") or {}
            for sa in f.get("soggetti_sa") or []:
                cfs.append(str(sa.get("codice_fiscale", "")).strip())
            if f.get("codice_fiscale_sa"):
                cfs.append(str(f["codice_fiscale_sa"]).strip())
            link_doc = link_doc or f.get("documenti_di_gara_link")
            for it in s.get("items") or []:
                cig = cig or it.get("cig")
                luogo = luogo or it.get("luogo_istat") or ""
    ente = next((per_cf[c] for c in cfs if c in per_cf), None)
    if not ente:
        return None
    tit = titolo or desc or ""
    if not tit:
        return None
    tipo = (a.get("tipologia") or "").upper()
    return {"ente": ente["nome"], "tipo": ente["tipo"], "cf": ente.get("cf"), "titolo": tit,
            "link": ANAC_LINK.format(a["idAvviso"]), "pubblicazione": _d(a.get("dataPubblicazione")),
            "scadenza": _d(a.get("dataScadenza")), "cig": cig, "testo": (desc or "") + " " + tipo,
            "fonte": "ANAC", "cpv": None, "allegati": [], "apri_dettaglio": False,
            "esito_anac": tipo.startswith(("AFFIDAMENTI", "ESITO", "AGGIUDIC"))}


def sintel(rete, per_cf, flt, limite):
    """Procedure Sintel degli enti della provincia, iniziate dopo 'limite'."""
    if not per_cf:
        return []
    out = []
    cfs = list(per_cf)
    for i in range(0, len(cfs), 80):
        lista = ",".join(f"'{c}'" for c in cfs[i:i + 80])
        par = {"$where": f"cf_stazione_appaltante in({lista}) AND data_inizio_negoziazione >= '{limite.isoformat()}T00:00:00'",
               "$limit": 5000}
        r, err = rete.get(SINTEL, controlla_robots=False, params=par, timeout=90)
        if err:
            raise RuntimeError(f"Sintel non risponde ({err})")
        for p in r.json():
            ente = per_cf.get(p.get("cf_stazione_appaltante"))
            if not ente:
                continue
            tit = p.get("nome_lotto") or p.get("nome_procedura") or ""
            if p.get("nome_procedura") and p.get("nome_lotto") and semplice(p["nome_lotto"]) != semplice(p["nome_procedura"]):
                tit = p["nome_procedura"] + " – " + p["nome_lotto"]
            imp = p.get("base_asta_lotto") or p.get("valore_economico_procedura")
            try:
                imp = "€ " + f"{float(imp):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if imp else None
            except ValueError:
                imp = None
            stato = semplice(p.get("stato_lotto") or p.get("stato_procedura") or "")
            out.append({"ente": ente["nome"], "tipo": ente["tipo"], "cf": ente.get("cf"), "titolo": tit,
                        "link": (p.get("link_lotto") or {}).get("url") if isinstance(p.get("link_lotto"), dict) else (p.get("link_lotto") or p.get("link_procedura") or ""),
                        "pubblicazione": _d(p.get("data_inizio_negoziazione")),
                        "scadenza": _d(p.get("data_fine_negoziazione")), "cig": p.get("cig"),
                        "cpv": p.get("codice_cpv"), "importo": imp,
                        "testo": " ".join(str(p.get(k) or "") for k in ("ambito_merceologico", "categoria_merceologiche", "modalita_scelta_contraente")),
                        "fonte": "Sintel", "allegati": [], "apri_dettaglio": False,
                        "esito_anac": "aggiudicat" in stato or "conclus" in stato})
    for v in out:
        if isinstance(v["link"], dict):
            v["link"] = v["link"].get("url", "")
    return [v for v in out if v["link"]]
