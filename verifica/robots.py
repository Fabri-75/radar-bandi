import requests, os
os.makedirs("verifica/out", exist_ok=True)
out = open("verifica/out/log.txt", "w")
for s in ["https://www.comune.aicurzio.mb.it", "https://www.comune.lesmo.mb.it", "https://www.scuolarodari.edu.it", "https://www.icstoppaniseregno.edu.it",
          "https://www.liceozucchi.edu.it", "https://www.frisimonza.edu.it", "https://www.comune.sulbiate.mb.it", "https://www.comune.bovisiomasciago.mb.it",
          "https://iclissoneprimo.edu.it", "https://www.comune.lissone.mb.it"]:
    try:
        r = requests.get(s + "/robots.txt", timeout=20, headers={"User-Agent": "RadarBandi/1.0"}, verify=False)
        out.write(f"\n##### {s} [{r.status_code}] {r.headers.get('content-type')}\n{r.text[:1500]}\n")
    except Exception as e:
        out.write(f"\n##### {s} ERR {e}\n")
    try:
        r = requests.get(s + "/", timeout=40, headers={"User-Agent": "Mozilla/5.0 RadarBandi/1.0"}, verify=False)
        out.write(f"HOME [{r.status_code}] {len(r.content)} {r.url}\n")
    except Exception as e:
        out.write(f"HOME ERR {e}\n")
