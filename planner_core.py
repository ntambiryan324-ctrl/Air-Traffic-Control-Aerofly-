"""Planning core for AeroflyATC: pure Python, no Kivy, safe to unit test.

Covers the FlyCharts-style planning features that can be built from public
data: distance/ETE, climb/descent profile, fuel estimate, METAR decoding,
SimBrief import and GPX export. Performance numbers are rough, sim-only values.
"""
import math
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

NM_PER_KM = 0.539957

# ICAO -> (lat, lon, name). Small built-in fallback; advanced_features.KNOWN_AIRPORTS wins if present.
AIRPORT_DB = {
    "HKJK": (-1.3192, 36.9278, "Nairobi Jomo Kenyatta"), "HUEN": (0.0424, 32.4435, "Entebbe"),
    "HTDA": (-6.8781, 39.2026, "Dar es Salaam"), "HAAB": (8.9779, 38.7993, "Addis Ababa Bole"),
    "HECA": (30.1219, 31.4056, "Cairo"), "OERK": (24.9576, 46.6988, "Riyadh King Khalid"),
    "OMDB": (25.2528, 55.3644, "Dubai"), "VABB": (19.0887, 72.8679, "Mumbai"),
    "VIDP": (28.5665, 77.1031, "Delhi"), "WSSS": (1.3644, 103.9915, "Singapore Changi"),
    "RJTT": (35.5523, 139.7798, "Tokyo Haneda"), "ZBAA": (40.0801, 116.5846, "Beijing Capital"),
    "EGLL": (51.4700, -0.4543, "London Heathrow"), "LFPG": (49.0097, 2.5479, "Paris CDG"),
    "EDDF": (50.0379, 8.5622, "Frankfurt"), "EHAM": (52.3105, 4.7683, "Amsterdam Schiphol"),
    "LEMD": (40.4719, -3.5626, "Madrid Barajas"), "LIRF": (41.8003, 12.2389, "Rome Fiumicino"),
    "KJFK": (40.6398, -73.7789, "New York JFK"), "KLAX": (33.9425, -118.4081, "Los Angeles"),
    "KSFO": (37.6188, -122.3750, "San Francisco"), "CYYZ": (43.6772, -79.6306, "Toronto Pearson"),
    "SBGR": (-23.4356, -46.4731, "Sao Paulo Guarulhos"), "FAOR": (-26.1392, 28.2460, "Johannesburg OR Tambo"),
    "FACT": (-33.9648, 18.6017, "Cape Town"), "DNMM": (6.5774, 3.3212, "Lagos"),
    "GOBD": (14.6700, -17.0733, "Dakar Blaise Diagne"), "LPPT": (38.7742, -9.1342, "Lisbon"),
    "LOWW": (48.1103, 16.5697, "Vienna"), "LTFM": (41.2753, 28.7519, "Istanbul"),
    "UUDD": (55.4088, 37.9063, "Moscow Domodedovo"), "YSSY": (-33.9461, 151.1772, "Sydney"),
    "NZAA": (-37.0082, 174.7850, "Auckland"),
}

# type -> (cruise TAS kt, climb ft/min, descent ft/min, cruise burn kg/h, max FL). Approximate.
AIRCRAFT = {
    "C172": (110, 700, 500, 23, 130), "BE58": (180, 1500, 800, 65, 200),
    "DH8D": (285, 1500, 1500, 1000, 250), "LJ45": (450, 3000, 2500, 900, 510),
    "CRJ9": (430, 2500, 2000, 2100, 410), "A320": (450, 2200, 2000, 2500, 390),
    "B738": (450, 2200, 2000, 2500, 410), "A359": (490, 2000, 2000, 5800, 410),
    "A35K": (490, 2000, 2000, 6000, 410), "B789": (490, 2000, 2000, 5400, 430),
    "B77W": (490, 1800, 2000, 7500, 430), "A388": (490, 1500, 2000, 11500, 430),
}
ALIASES = {
    "A350": "A35K", "A350-1000": "A35K", "A350-900": "A359", "A380": "A388",
    "B777": "B77W", "777": "B77W", "B787": "B789", "787": "B789", "Q400": "DH8D",
    "DASH 8": "DH8D", "LEARJET 45": "LJ45", "CESSNA 172": "C172", "BARON 58": "BE58",
    "CRJ-900": "CRJ9", "CRJ900": "CRJ9", "B737": "B738", "737": "B738",
}


def lookup_airport(icao):
    """Return dict(icao, lat, lon, name) or None."""
    code = (icao or "").strip().upper()
    try:
        import advanced_features as adv  # optional, from the existing repo
        known = getattr(adv, "KNOWN_AIRPORTS", {})
        if code in known:
            lat, lon, name = known[code]
            return {"icao": code, "lat": lat, "lon": lon, "name": name}
    except Exception:
        pass
    if code in AIRPORT_DB:
        lat, lon, name = AIRPORT_DB[code]
        return {"icao": code, "lat": lat, "lon": lon, "name": name}
    return None


def resolve_aircraft(text):
    key = (text or "").strip().upper()
    if key in AIRCRAFT:
        return key
    if key in ALIASES:
        return ALIASES[key]
    for name, code in ALIASES.items():
        if name in key:
            return code
    return "A320"


def distance_nm(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def route_distance(points):
    return sum(distance_nm(a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:]))


def plan_flight(points, aircraft="A320", cruise_fl=None, reserve_min=45, contingency=0.05,
                speed_override_kt=None):
    """Simple three-phase estimate. points = [(lat, lon), ...]. Returns a dict.

    speed_override_kt optionally replaces the aircraft profile's nominal TAS for
    this estimate; it must be a finite value between 40 and 700 knots.
    """
    code = resolve_aircraft(aircraft)
    tas, climb_fpm, desc_fpm, burn, max_fl = AIRCRAFT[code]
    if speed_override_kt is not None:
        try:
            requested_tas = float(speed_override_kt)
            if math.isfinite(requested_tas) and 40.0 <= requested_tas <= 700.0:
                tas = requested_tas
        except (TypeError, ValueError):
            pass
    dist = route_distance(points)
    fl = int(cruise_fl) if cruise_fl else min(max_fl, 360 if tas > 400 else 100)
    fl = max(20, min(fl, max_fl))
    # Shrink cruise level on short routes so climb + descent always fit.
    while True:
        alt = fl * 100.0
        t_climb = alt / climb_fpm / 60.0
        t_desc = alt / desc_fpm / 60.0
        d_climb = t_climb * tas * 0.80
        d_desc = t_desc * tas * 0.85
        if d_climb + d_desc <= dist or fl <= 20:
            break
        fl -= 10
    d_cruise = max(0.0, dist - d_climb - d_desc)
    t_cruise = d_cruise / tas
    ete = t_climb + t_cruise + t_desc
    fuel_trip = burn * (t_climb * 1.6 + t_cruise + t_desc * 0.4)
    fuel_reserve = burn * reserve_min / 60.0
    fuel_cont = fuel_trip * contingency
    return {
        "aircraft": code, "distance_nm": dist, "cruise_fl": fl, "tas_kt": tas,
        "toc_nm": d_climb, "tod_nm": dist - d_desc, "ete_min": ete * 60.0,
        "fuel_trip_kg": fuel_trip, "fuel_reserve_kg": fuel_reserve,
        "fuel_contingency_kg": fuel_cont,
        "fuel_total_kg": fuel_trip + fuel_reserve + fuel_cont,
    }


def vertical_profile(plan, step_nm=10.0):
    """[(distance_nm, altitude_ft), ...] from a plan_flight() result."""
    dist, fl = plan["distance_nm"], plan["cruise_fl"]
    toc, tod = plan["toc_nm"], plan["tod_nm"]
    pts, d = [], 0.0
    while d < dist:
        if d < toc:
            alt = fl * 100.0 * (d / toc if toc > 0 else 1.0)
        elif d > tod:
            alt = fl * 100.0 * ((dist - d) / (dist - tod) if dist > tod else 0.0)
        else:
            alt = fl * 100.0
        pts.append((d, max(0.0, alt)))
        d += step_nm
    pts.append((dist, 0.0))
    return pts


def format_plan(plan, origin, dest):
    h, m = divmod(int(round(plan["ete_min"])), 60)
    return (
        f"{origin} > {dest}   {plan['aircraft']}\n"
        f"DIST {plan['distance_nm']:.0f} NM   CRUISE FL{plan['cruise_fl']}   TAS {plan['tas_kt']} KT\n"
        f"ETE {h}:{m:02d}   TOC {plan['toc_nm']:.0f} NM   TOD {plan['tod_nm']:.0f} NM\n"
        f"FUEL trip {plan['fuel_trip_kg']:.0f}  res {plan['fuel_reserve_kg']:.0f}  "
        f"cont {plan['fuel_contingency_kg']:.0f}  total {plan['fuel_total_kg']:.0f} KG\n"
        "Approximate, simulator use only."
    )


# ---------------- METAR ----------------
def fetch_metar(icao, timeout=10):
    """Raw METAR text from the AviationWeather.gov Data API (raw is its default format)."""
    url = "https://aviationweather.gov/api/data/metar?ids=" + urllib.parse.quote(icao.upper()) + "&format=raw"
    req = urllib.request.Request(url, headers={"User-Agent": "AeroflyATC/4.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", "replace").strip()
    return text.splitlines()[0].strip() if text else ""


def fetch_taf(icao, timeout=10):
    """Fetch raw TAF forecast text from AviationWeather.gov."""
    code = (icao or "").strip().upper()
    if not code or not re.fullmatch(r"[A-Z0-9]{3,4}", code):
        raise ValueError("Enter a valid 3- or 4-character airport identifier.")
    url = "https://aviationweather.gov/api/data/taf?ids=" + urllib.parse.quote(code) + "&format=raw"
    req = urllib.request.Request(url, headers={"User-Agent": "AeroflyATC/4.1 (flight simulator companion)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", "replace").strip()
    return text.splitlines()[0].strip() if text else ""


def decode_metar(raw):
    """Pull out the fields ATC needs. Missing fields come back as None."""
    out = {"raw": raw, "wind_dir": None, "wind_kt": None, "gust_kt": None,
           "vis": None, "temp_c": None, "dew_c": None, "qnh_hpa": None, "altim_inhg": None,
           "time_z": None}
    m = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", raw)
    if m:
        out["time_z"] = f"{m.group(2)}{m.group(3)}Z"
    m = re.search(r"\b(VRB|\d{3})(\d{2,3})(?:G(\d{2,3}))?KT\b", raw)
    if m:
        out["wind_dir"] = None if m.group(1) == "VRB" else int(m.group(1))
        out["wind_kt"] = int(m.group(2))
        out["gust_kt"] = int(m.group(3)) if m.group(3) else None
    m = re.search(r"\b(\d{1,2}(?: \d/\d)?)SM\b", raw)
    if m:
        out["vis"] = m.group(1) + " SM"
    else:
        m = re.search(r"\b(\d{4})\b(?!/)", raw.split("KT", 1)[-1])
        if m:
            out["vis"] = ("10 KM" if m.group(1) == "9999" else f"{int(m.group(1))} M")
    m = re.search(r"\b(M?\d{2})/(M?\d{2})\b", raw)
    if m:
        conv = lambda s: -int(s[1:]) if s.startswith("M") else int(s)
        out["temp_c"], out["dew_c"] = conv(m.group(1)), conv(m.group(2))
    m = re.search(r"\bQ(\d{4})\b", raw)
    if m:
        out["qnh_hpa"] = int(m.group(1))
        out["altim_inhg"] = round(int(m.group(1)) * 0.02953, 2)
    else:
        m = re.search(r"\bA(\d{4})\b", raw)
        if m:
            out["altim_inhg"] = int(m.group(1)) / 100.0
            out["qnh_hpa"] = int(round(int(m.group(1)) / 100.0 / 0.02953))
    return out


# ---------------- SimBrief + export ----------------
def fetch_simbrief(username, timeout=20):
    """Latest OFP summary: (origin, dest, route, distance_nm)."""
    url = "https://www.simbrief.com/api/xml.fetcher.php?username=" + urllib.parse.quote(username)
    req = urllib.request.Request(url, headers={"User-Agent": "AeroflyATC/4.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        root = ET.fromstring(resp.read())
    return ((root.findtext("./origin/icao") or "").strip().upper(),
            (root.findtext("./destination/icao") or "").strip().upper(),
            (root.findtext("./general/route") or "").strip(),
            root.findtext("./general/route_distance") or "")


def export_gpx(name, waypoints):
    """waypoints = [(ident, lat, lon), ...] -> GPX 1.1 route text."""
    pts = "".join(
        f'    <rtept lat="{lat:.6f}" lon="{lon:.6f}"><name>{ident}</name></rtept>\n'
        for ident, lat, lon in waypoints)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<gpx version="1.1" creator="AeroflyATC" xmlns="http://www.topografix.com/GPX/1/1">\n'
            f"  <rte>\n    <name>{name}</name>\n{pts}  </rte>\n</gpx>\n")


def great_circle_points(lat1, lon1, lat2, lon2, step_nm=100.0):
    """Points along the great circle between two positions (inclusive), for map drawing."""
    d = distance_nm(lat1, lon1, lat2, lon2)
    n = max(1, int(math.ceil(d / step_nm)))
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    delta = d / 3440.065
    if delta < 1e-9:
        return [(lat1, lon1)]
    out = []
    for i in range(n + 1):
        f = i / n
        a = math.sin((1 - f) * delta) / math.sin(delta)
        b = math.sin(f * delta) / math.sin(delta)
        x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
        y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
        z = a * math.sin(p1) + b * math.sin(p2)
        out.append((math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))))
    return out
