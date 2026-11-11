#!/usr/bin/env python3
"""Het weer (vorstmelding): stuurt een pushmelding (via ntfy) als er vorst verwacht wordt.

Instellingen staan in config.json. Het ntfy-onderwerp komt uit de
omgevingsvariabele NTFY_TOPIC (op GitHub: een repository secret).

Gebruik:
  python vorstwacht.py          # controleer alleen als het nu het ingestelde uur is
  python vorstwacht.py --nu     # controleer meteen, ongeacht het tijdstip
  python vorstwacht.py --test   # stuur een testmelding
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Amsterdam")
CONFIG = Path(__file__).with_name("config.json")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")


def lees_config():
    with open(CONFIG, encoding="utf-8") as f:
        c = json.load(f)
    uur, minuut = (int(x) for x in str(c.get("tijdstip", "17:00")).split(":"))
    if not (0 <= uur <= 23 and 0 <= minuut <= 59):
        raise ValueError("tijdstip moet de vorm UU:MM hebben, bijv. 17:00")
    return {
        "locatie": str(c["locatie"]).strip(),
        "uur": uur,
        "drempel": float(c.get("drempel_celsius", 0)),
        "uren_vooruit": max(1, min(int(c.get("uren_vooruit", 24)), 72)),
        "aan": bool(c.get("aan", True)),
        "lat": c.get("latitude"),
        "lon": c.get("longitude"),
    }


def haal_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "vorstwacht"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def zoek_locatie(naam):
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": naam, "count": 1, "language": "nl", "format": "json"}
    )
    res = haal_json(url).get("results") or []
    if not res:
        raise ValueError(f"Locatie '{naam}' niet gevonden. Probeer een plaatsnaam, "
                         "of zet latitude en longitude in config.json.")
    r = res[0]
    label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country_code")) if x)
    return r["latitude"], r["longitude"], label


def laagste_temperatuur(lat, lon, uren):
    dagen = min(16, uren // 24 + 2)
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m",
        "timezone": "Europe/Amsterdam",
        "forecast_days": dagen,
    })
    data = haal_json(url)["hourly"]
    nu = datetime.now(TZ).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    eind = nu + timedelta(hours=uren)
    kandidaten = [
        (t, datetime.fromisoformat(s))
        for s, t in zip(data["time"], data["temperature_2m"])
        if t is not None and nu <= datetime.fromisoformat(s) <= eind
    ]
    if not kandidaten:
        raise RuntimeError("Geen verwachting ontvangen van Open-Meteo.")
    return min(kandidaten)


def stuur_melding(titel, tekst, prioriteit="high"):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("NTFY_TOPIC is niet ingesteld; melding niet verstuurd:\n" + tekst)
        return False
    req = urllib.request.Request(
        f"{NTFY_SERVER}/{urllib.parse.quote(topic)}",
        data=tekst.encode("utf-8"),
        method="POST",
        headers={"Title": titel, "Priority": prioriteit, "Tags": "snowflake"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()
    return True


def dag(dt):
    namen = ["ma", "di", "wo", "do", "vr", "za", "zo"]
    return f"{namen[dt.weekday()]} {dt:%H:%M}"


def main(args):
    c = lees_config()

    if "--test" in args:
        stuur_melding("Het weer: test", f"Testmelding voor {c['locatie']}. Het werkt!", "default")
        print("Testmelding verstuurd.")
        return 0

    if not c["aan"]:
        print("Vorstmelding staat uit (\"aan\": false in config.json).")
        return 0

    nu = datetime.now(TZ)
    if "--nu" not in args and nu.hour != c["uur"]:
        print(f"Het is {nu:%H:%M}; controle pas om {c['uur']:02d}:00. Niets te doen.")
        return 0

    if c["lat"] is not None and c["lon"] is not None:
        lat, lon, label = float(c["lat"]), float(c["lon"]), c["locatie"]
    else:
        lat, lon, label = zoek_locatie(c["locatie"])

    temp, moment = laagste_temperatuur(lat, lon, c["uren_vooruit"])
    print(f"{label}: laagste {temp:.1f} °C om {dag(moment)} "
          f"(komende {c['uren_vooruit']} uur, drempel {c['drempel']:g} °C)")

    if temp <= c["drempel"]:
        tekst = (f"{label}: het wordt {temp:.1f} °C ({dag(moment)}). "
                 f"Dat is op of onder je grens van {c['drempel']:g} °C.")
        stuur_melding("Vorst verwacht", tekst)
        print("Melding verstuurd.")
    else:
        print("Geen vorst onder de drempel; geen melding.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
