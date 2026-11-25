"""Ricostruisce docs/dati/province.json dai file delle singole province."""
import glob
import json
import os
import sys


def scrivi_indice(cartella="docs/dati"):
    prov = []
    for f in glob.glob(os.path.join(cartella, "??.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
            prov.append({"sigla": d["provincia"]["sigla"], "nome": d["provincia"]["nome"], "aggiornato": d["aggiornato"],
                         "avvisi": len(d["righe"])})
        except Exception:
            pass
    prov.sort(key=lambda p: p["nome"])
    json.dump(prov, open(os.path.join(cartella, "province.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return prov


if __name__ == "__main__":
    print(scrivi_indice(sys.argv[1] if len(sys.argv) > 1 else "docs/dati"))
