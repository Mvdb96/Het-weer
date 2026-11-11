#!/usr/bin/env python3
"""Het weer: vorstmelding en fietsadvies via ntfy-pushmeldingen.

Instellingen staan in config.json. Het ntfy-onderwerp komt uit de
omgevingsvariabele NTFY_TOPIC (op GitHub: een repository secret).

Gebruik:
  python vorstwacht.py          # elk uur: doet alleen iets op de ingestelde uren
  python vorstwacht.py --nu     # vorstcontrole meteen, ongeacht het tijdstip
  python vorstwacht.py --fiets  # fietsadvies meteen versturen
  python vorstwacht.py --test   # stuur een testmelding
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Amsterdam")
CONFIG = Path(__file__).with_name("config.json")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
DAGNAMEN = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]

NIVEAUS = ["fiets", "regenkleding", "auto"]

MELDING_STANDAARD = {
    "naam": "Werk",
    "aan": True,
    "tijdstip": "06:00",           # wanneer de melding komt (hele uren)
    "dag_ervoor": False,           # True: melding de dag vóór de reisdag
    "dagen": [1, 2, 3, 4, 5],      # 1 = maandag ... 7 = zondag
    "heen": "07:30",
    "terug": "17:00",              # leeg laten ("") als je alleen heen gaat
    "reistijd_min": 30,
    "melden_bij": NIVEAUS + ["krabben"],  # bij welk advies je een melding wilt;
                                   # "krabben": ook melden als je waarschijnlijk moet krabben
}

GRENZEN_STANDAARD = {
    "max_regen_mm": 1.0,           # buien heviger dan dit (mm per uur)
    "max_regen_min": 15,           # langer regen tijdens de rit dan dit (minuten)
    "max_regenkans": 70,           # procent
    "max_wind_kmh": 40,
    "max_windstoten_kmh": 65,
    "min_temp": 0,                 # bij deze temperatuur of kouder: kans op gladheid
    "krab_temp": 2,                # ruiten krabben: 's nachts deze temperatuur of kouder
    # Welke weersfactoren meetellen (false = uitgeschakeld)
    "gebruik": {"regen": True, "regenduur": True, "regenkans": True, "wind": True,
                "windstoten": True, "gladheid": True, "onweer": True, "sneeuw": True, "ijzel": True, "krabben": True},
}


def fietsinstellingen(c):
    """Leest fietsmeldingen en -grenzen, ook uit de oude vorm 'fietsadvies'."""
    oud = c.get("fietsadvies") or {}
    grenzen = dict(GRENZEN_STANDAARD)
    grenzen.update({k: oud[k] for k in GRENZEN_STANDAARD if k in oud})
    grenzen.update(c.get("fietsgrenzen") or {})
    grenzen["gebruik"] = {**GRENZEN_STANDAARD["gebruik"], **(grenzen.get("gebruik") or {})}
    lijst = c.get("fietsmeldingen")
    if lijst is None and oud:
        m = {k: oud[k] for k in MELDING_STANDAARD if k in oud}
        m["melden_bij"] = ["auto"] if oud.get("melding") == "alleen_auto" else NIVEAUS
        lijst = [m]
    meldingen = []
    for m in lijst or []:
        x = dict(MELDING_STANDAARD)
        x.update(m)
        meldingen.append(x)
    return meldingen, grenzen


def tijd(s, standaard="00:00"):
    s = str(s or standaard)
    uur, minuut = (int(x) for x in s.split(":"))
    if not (0 <= uur <= 23 and 0 <= minuut <= 59):
        raise ValueError(f"tijd '{s}' moet de vorm UU:MM hebben")
    return uur, minuut


def lees_config():
    with open(CONFIG, encoding="utf-8") as f:
        c = json.load(f)
    meldingen, grenzen = fietsinstellingen(c)
    return {
        "locatie": str(c["locatie"]).strip(),
        "uur": tijd(c.get("tijdstip"), "17:00")[0],
        "drempel": float(c.get("drempel_celsius", 0)),
        "uren_vooruit": max(1, min(int(c.get("uren_vooruit", 24)), 72)),
        "aan": bool(c.get("aan", True)),
        "lat": c.get("latitude"),
        "lon": c.get("longitude"),
        "fietsmeldingen": meldingen,
        "fietsgrenzen": grenzen,
    }


def haal_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "het-weer"})
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


def verwachting(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,precipitation,precipitation_probability,"
                  "weather_code,wind_speed_10m,wind_gusts_10m,"
                  "relative_humidity_2m,cloud_cover",
        "timezone": "Europe/Amsterdam",
        "minutely_15": "precipitation",
        "forecast_days": 4,
    })
    data = haal_json(url)
    h = data["hourly"]
    uren = {}
    for i, s in enumerate(h["time"]):
        uren[datetime.fromisoformat(s)] = {k: h[k][i] for k in h if k != "time"}
    m = data.get("minutely_15") or {}
    kwartieren = {datetime.fromisoformat(s): p for s, p in zip(m.get("time", []), m.get("precipitation", []))
                  if p is not None}
    return uren, kwartieren


def regen_tijdens(uren, kwartieren, begin, eind):
    """Minuten regen, zwaarste intensiteit (mm/uur) en totaal (mm) tijdens [begin, eind).
    Open-Meteo geeft neerslag als som over het voorgaande kwartier (of uur)."""
    if kwartieren:
        reeks, lengte = kwartieren, 15
    else:
        reeks, lengte = {t: v["precipitation"] or 0 for t, v in uren.items()}, 60
    minuten = intensiteit = totaal = 0.0
    for t, p in reeks.items():
        vanaf = t - timedelta(minutes=lengte)
        if vanaf >= eind or t <= begin:
            continue
        overlap = (min(t, eind) - max(vanaf, begin)).total_seconds() / 60
        totaal += p * overlap / lengte
        if p >= 0.1:
            minuten += overlap
            intensiteit = max(intensiteit, p * 60 / lengte)
    return round(minuten), intensiteit, totaal


# ---------------- Vorst ----------------

def laagste_temperatuur(uren, aantal):
    nu = datetime.now(TZ).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    eind = nu + timedelta(hours=aantal)
    kandidaten = [(v["temperature_2m"], t) for t, v in uren.items()
                  if v["temperature_2m"] is not None and nu <= t <= eind]
    if not kandidaten:
        raise RuntimeError("Geen verwachting ontvangen van Open-Meteo.")
    return min(kandidaten)


def kort(dt):
    return f"{DAGNAMEN[dt.weekday()][:2]} {dt:%H:%M}"


def vorstcontrole(c, uren, label):
    temp, moment = laagste_temperatuur(uren, c["uren_vooruit"])
    print(f"Vorst: laagste {temp:.1f} °C om {kort(moment)} "
          f"(komende {c['uren_vooruit']} uur, drempel {c['drempel']:g} °C)")
    if temp <= c["drempel"]:
        stuur_melding("Vorst verwacht",
                      f"{label}: het wordt {temp:.1f} °C ({kort(moment)}). "
                      f"Dat is op of onder je grens van {c['drempel']:g} °C.",
                      tags="snowflake")
        print("Vorstmelding verstuurd.")


# ---------------- Fietsadvies ----------------

def nl(x):
    return f"{x:.1f}".replace(".", ",")


def rituren(dag, start, minuten):
    """Hele uren die een rit van `minuten` vanaf `start` (UU:MM) raakt."""
    u, m = tijd(start)
    begin = datetime.combine(dag, datetime.min.time()).replace(hour=u, minute=m)
    eind = begin + timedelta(minutes=max(1, minuten) - 1)
    t = begin.replace(minute=0)
    while t <= eind:
        yield t
        t += timedelta(hours=1)


def beoordeel(uren, dag, f, g, kwartieren=None):
    """Geeft (niveau, redenen) per rit. niveau: 'fiets', 'regenkleding' of 'auto'."""
    ritten = [("heen", f["heen"])]
    if f.get("terug"):
        ritten.append(("terug", f["terug"]))
    resultaat = []
    for naam, start in ritten:
        data = [uren[t] for t in rituren(dag, start, int(f["reistijd_min"])) if t in uren]
        if not data:
            continue
        hard, zacht = [], []
        aan = g["gebruik"]
        u, m = tijd(start)
        begin = datetime.combine(dag, datetime.min.time()).replace(hour=u, minute=m)
        eind = begin + timedelta(minutes=int(f["reistijd_min"]))
        regenmin, intensiteit, regenmm = regen_tijdens(uren, kwartieren, begin, eind)
        kans = max(d["precipitation_probability"] or 0 for d in data)
        wind = max(d["wind_speed_10m"] or 0 for d in data)
        stoot = max(d["wind_gusts_10m"] or 0 for d in data)
        temp = min(d["temperature_2m"] for d in data)
        codes = {d["weather_code"] for d in data}
        if aan["onweer"] and codes & {95, 96, 99}:
            hard.append("onweer")
        if aan["sneeuw"] and codes & {71, 73, 75, 77, 85, 86}:
            hard.append("sneeuw")
        if aan["ijzel"] and codes & {56, 57, 66, 67}:
            hard.append("ijzel")
        if aan["gladheid"] and temp <= float(g["min_temp"]):
            hard.append(f"kans op gladheid ({temp:.0f} °C)")
        regen_hard = False
        if aan["regen"] and intensiteit > float(g["max_regen_mm"]):
            hard.append(f"buien tot {nl(intensiteit)} mm/uur")
            regen_hard = True
        if aan["regenduur"] and regenmin > float(g["max_regen_min"]):
            hard.append(f"ca. {regenmin} min regen tijdens je rit")
            regen_hard = True
        if not regen_hard:
            if aan["regenkans"] and kans >= float(g["max_regenkans"]) and regenmin == 0:
                hard.append(f"{kans:.0f}% kans op regen")
            elif (aan["regen"] or aan["regenduur"]) and regenmin > 0:
                zacht.append(f"ca. {regenmin} min lichte regen ({nl(regenmm)} mm)")
            elif aan["regenkans"] and kans >= 30:
                zacht.append(f"kans op een bui ({kans:.0f}%)")
        if aan["wind"] and wind >= float(g["max_wind_kmh"]):
            hard.append(f"harde wind ({wind:.0f} km/u)")
        elif aan["windstoten"] and stoot >= float(g["max_windstoten_kmh"]):
            hard.append(f"windstoten tot {stoot:.0f} km/u")
        niveau = "auto" if hard else ("regenkleding" if zacht else "fiets")
        resultaat.append((naam, start, niveau, hard or zacht, round(temp)))
    return resultaat


def krabben(uren, dag, heen, g):
    """Moet je de autoruiten krabben voor de rit heen? Kijkt naar de 8 uur ervoor."""
    if not g["gebruik"].get("krabben"):
        return None
    u, m = tijd(heen)
    vertrek = datetime.combine(dag, datetime.min.time()).replace(hour=u, minute=m)
    nacht = [v for t, v in uren.items() if vertrek - timedelta(hours=8) <= t <= vertrek]
    if not nacht:
        return None
    grens = float(g.get("krab_temp", 2))
    laagste = min(v["temperature_2m"] for v in nacht)
    codes = {v["weather_code"] for v in nacht}
    if codes & {56, 57, 66, 67}:
        return f"ijzel vannacht, ruiten waarschijnlijk bevroren ({laagste:.0f} °C)"
    if codes & {71, 73, 75, 77, 85, 86} and laagste <= 1:
        return f"sneeuw vannacht: sneeuw vegen en krabben ({laagste:.0f} °C)"
    def rv(v): return v.get("relative_humidity_2m") or 0
    def wolk(v): return 100 if v.get("cloud_cover") is None else v["cloud_cover"]
    if any(v["temperature_2m"] <= min(grens, 0) and rv(v) >= 70 for v in nacht):
        return f"vriest vannacht ({laagste:.0f} °C), vochtige lucht"
    if any(v["temperature_2m"] <= grens and rv(v) >= 80 and wolk(v) < 60 for v in nacht):
        return f"koud ({laagste:.0f} °C), helder en vochtig: kans op rijp"
    return None


def doeldag(f, nu):
    """Morgen bij 'dag_ervoor'; anders vandaag als de melding vóór vertrek komt, of morgen."""
    if f.get("dag_ervoor"):
        return nu.date() + timedelta(days=1)
    hu, hm = tijd(f["heen"])
    mu, _ = tijd(f["tijdstip"])
    return nu.date() if mu * 60 <= hu * 60 + hm else nu.date() + timedelta(days=1)


def fietsadvies(f, g, uren, label, geforceerd=False, kwartieren=None):
    nu = datetime.now(TZ)
    dag = doeldag(f, nu)
    if geforceerd:
        # Handmatig: vandaag zolang de laatste rit nog moet komen, anders morgen.
        laatste = max(tijd(x) for x in (f["heen"], f.get("terug")) if x)
        dag = nu.date() if (nu.hour, nu.minute) < laatste else nu.date() + timedelta(days=1)
    if not geforceerd and dag.isoweekday() not in [int(x) for x in f["dagen"]]:
        print(f"Fietsadvies {f['naam']}: {DAGNAMEN[dag.weekday()]} is geen reisdag.")
        return
    ritten = beoordeel(uren, dag, f, g, kwartieren)
    if not ritten:
        print("Fietsadvies: geen verwachting voor de reistijden.")
        return
    volgorde = {"fiets": 0, "regenkleding": 1, "auto": 2}
    slechtst = max(ritten, key=lambda r: volgorde[r[2]])[2]
    wanneer = "vandaag" if dag == nu.date() else "morgen"
    titel, tags = {
        "fiets": (f"Fietsweer {wanneer}", "bicyclist"),
        "regenkleding": (f"Fietsen {wanneer}, met regenkleding", "bicyclist,umbrella"),
        "auto": (f"Beter de auto {wanneer}", "car"),
    }[slechtst]
    if f.get("naam"):
        titel = f"{f['naam']}: {titel[0].lower()}{titel[1:]}"
    regels = []
    for naam, start, niveau, redenen, temp in ritten:
        icoon = {"fiets": "🚲", "regenkleding": "🚲☂️", "auto": "🚗"}[niveau]
        uitleg = ", ".join(redenen) if redenen else "droog, weinig wind"
        regels.append(f"{icoon} {naam.capitalize()} {start}: {uitleg} · {temp} °C")
    krab = krabben(uren, dag, f["heen"], g)
    if krab:
        regels.append(f"🧊 Auto krabben: {krab}")
    tekst = f"{label}\n" + "\n".join(regels)
    print(titel + "\n" + tekst)
    bij = f.get("melden_bij") or NIVEAUS
    if not geforceerd and slechtst not in bij and not (krab and "krabben" in bij):
        print(f"Geen melding: advies '{slechtst}' staat niet aan bij deze melding.")
        return
    if krab and slechtst not in bij:
        titel, tags = f"{f.get('naam') or 'Auto'}: ruiten krabben {wanneer}", "ice_cube"
    stuur_melding(titel, tekst, prioriteit="default", tags=tags)
    print("Fietsadvies verstuurd.")


# ---------------- Melding ----------------

def stuur_melding(titel, tekst, prioriteit="high", tags="snowflake"):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("NTFY_TOPIC is niet ingesteld; melding niet verstuurd.")
        return False
    req = urllib.request.Request(
        f"{NTFY_SERVER}/{urllib.parse.quote(topic)}",
        data=tekst.encode("utf-8"),
        method="POST",
        # Emoji in de titel komen via Tags; de titel zelf blijft gewone tekst.
        headers={"Title": titel, "Priority": prioriteit, "Tags": tags},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()
    return True


def main(args):
    c = lees_config()

    if "--test" in args:
        stuur_melding("Het weer: test", f"Testmelding voor {c['locatie']}. Het werkt!", "default", "white_check_mark")
        print("Testmelding verstuurd.")
        return 0

    nu = datetime.now(TZ)
    vorst_nu = "--nu" in args or (c["aan"] and nu.hour == c["uur"])
    geforceerd = "--fiets" in args
    fiets_nu = [f for f in c["fietsmeldingen"]
                if (geforceerd and f.get("aan")) or (f.get("aan") and nu.hour == tijd(f["tijdstip"])[0])]
    if geforceerd and not fiets_nu:
        print("Er staat geen fietsmelding aan.")
    if "--nu" in args and not c["aan"]:
        print("Let op: vorstmelding staat uit, maar wordt nu toch gecontroleerd.")

    if not (vorst_nu or fiets_nu):
        print(f"Het is {nu:%H:%M}; niets te doen op dit uur.")
        return 0

    if c["lat"] is not None and c["lon"] is not None:
        lat, lon, label = float(c["lat"]), float(c["lon"]), c["locatie"]
    else:
        lat, lon, label = zoek_locatie(c["locatie"])
    uren, kwartieren = verwachting(lat, lon)

    if vorst_nu:
        vorstcontrole(c, uren, label)
    for f in fiets_nu:
        fietsadvies(f, c["fietsgrenzen"], uren, label, geforceerd=geforceerd, kwartieren=kwartieren)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
