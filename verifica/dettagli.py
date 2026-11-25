import os, sys, json
sys.path.insert(0, ".")
from radar.rete import Rete
from radar.lettori.generico import testo_e_allegati
from radar.testo import testo_pdf, trova_scadenza, trova_importo, trova_destinatari
os.makedirs("verifica/out", exist_ok=True)
out = open("verifica/out/log.txt", "w")
rete = Rete()
for u in ["https://nuvola.madisoft.it/bacheca-digitale/15969/documento/MBIC8EY00R",
          "https://web.spaggiari.eu/sdg2/Documenti/MIME0267/ilc6cuavg1",
          "https://www.iccervilimbiate.edu.it/albo-pretorio/?action=visatto&id=399",
          "https://bernareggio.trasparenza-valutazione-merito.it/web/trasparenza/albo-pretorio/-/papca/display/10660916",
          "http://www.sintel.regione.lombardia.it/eprocdata/auctionDetail.xhtml?id=227022251"]:
    r, err = rete.get(u)
    out.write(f"\n##### {u}\n{err} {r.status_code if r is not None else ''} {r.headers.get('content-type') if r is not None else ''} final={r.url if r is not None else ''}\n")
    if r is None: continue
    if b"%PDF" in r.content[:1024]:
        t = testo_pdf(r.content); alls = []
    else:
        t, alls = testo_e_allegati(r.text, r.url)
        out.write("RAW-LINKS: " + json.dumps(alls[:10]) + "\n")
    out.write("TESTO: " + t[:1500].replace("\n", " ") + "\n")
    for a in alls[:3]:
        ra, e = rete.get(a)
        if ra is not None:
            out.write(f"  ALL {a} {e} {ra.headers.get('content-type')} pdf={b'%PDF' in ra.content[:1024]}\n")
            if b"%PDF" in ra.content[:1024]:
                tp = testo_pdf(ra.content); t += tp
                out.write("  PDF: " + tp[:800].replace("\n", " ") + "\n")
    out.write(f"=> scad={trova_scadenza(t)} imp={trova_importo(t)} chi={trova_destinatari(t)}\n")
