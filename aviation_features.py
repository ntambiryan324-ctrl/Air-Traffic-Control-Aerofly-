import csv
import glob
import math
import os
import re
import struct
import threading
import time
import urllib.request
from io import BytesIO

from kivy.clock import Clock
from kivy.core.image import Image as CoreImage


REGION_VOICE_PROFILES = (
    # min_lat, max_lat, min_lon, max_lon, locale
    (35, 72, -25, 45, "en-GB"),
    (-36, 15, 20, 55, "en-GB"),
    (15, 38, -130, -60, "en-US"),
    (24, 50, 60, 150, "en-US"),
    (-48, -10, 110, 180, "en-AU"),
    (35, 72, 45, 180, "en-GB"),
    (-40, 15, -20, 55, "en-GB"),
)


def region_voice_locale(lat, lon, country=None):
    """Select an available TTS locale from country first, then a coarse region."""
    country_map = {
        "US": "en-US", "CA": "en-CA", "GB": "en-GB", "IE": "en-IE",
        "AU": "en-AU", "NZ": "en-NZ", "IN": "en-IN", "ZA": "en-ZA",
        "UG": "en-GB", "KE": "en-GB", "TZ": "en-GB", "NG": "en-GB",
        "FR": "fr-FR", "BE": "fr-FR", "DE": "de-DE", "AT": "de-DE",
        "ES": "es-ES", "PT": "pt-PT", "BR": "pt-BR", "IT": "it-IT",
        "NL": "nl-NL", "CH": "de-CH", "SE": "sv-SE", "NO": "nb-NO",
        "DK": "da-DK", "FI": "fi-FI", "PL": "pl-PL", "TR": "tr-TR",
        "AE": "en-GB", "SA": "en-GB", "EG": "en-GB",
    }
    if country and str(country).upper() in country_map:
        return country_map[str(country).upper()]
    lat, lon = float(lat or 0), float(lon or 0)
    for a, b, c, d, locale in REGION_VOICE_PROFILES:
        if a <= lat <= b and c <= lon <= d:
            return locale
    return "en-GB"


def _coord(token):
    token = token.strip().upper()
    m = re.match(r"^(\d{1,3}):(\d{1,2})(?::(\d{1,2}(?:\.\d+)?))?([NSEW])$", token)
    if not m:
        try:
            return float(token)
        except ValueError:
            return 0.0
    deg, minute, sec, hemi = m.groups()
    value = float(deg) + float(minute) / 60.0 + (float(sec or 0) / 3600.0)
    return -value if hemi in ("S", "W") else value


def parse_openair(text):
    """Parse useful OpenAir v1/v2 polygon airspace records without third-party libs."""
    result, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        code, _, value = line.partition(" ")
        code = code.upper()
        value = value.strip()
        if code == "AC":
            if cur and cur.get("points"):
                result.append(cur)
            cur = {"class": value, "name": "", "type": "", "frequency": "",
                   "floor": "", "ceiling": "", "points": []}
        elif cur is None:
            continue
        elif code == "AN":
            cur["name"] = value
        elif code == "AY":
            cur["type"] = value
        elif code == "AF":
            cur["frequency"] = value
        elif code == "AL":
            cur["floor"] = value
        elif code == "AH":
            cur["ceiling"] = value
        elif code == "DP":
            parts = value.replace(",", " ").split()
            # OpenAir commonly writes: latitude hemisphere longitude hemisphere.
            if len(parts) >= 4 and parts[1].upper() in ("N", "S") and parts[3].upper() in ("E", "W"):
                cur["points"].append((_coord(parts[0] + parts[1]), _coord(parts[2] + parts[3])))
            elif len(parts) >= 2:
                cur["points"].append((_coord(parts[0]), _coord(parts[1])))
    if cur and cur.get("points"):
        result.append(cur)
    return result


class AirspaceStore:
    """Loads user-provided OpenAir files from the app's airspace directory."""
    def __init__(self, base_dir):
        self.base_dir = os.path.join(base_dir, "airspace")
        os.makedirs(self.base_dir, exist_ok=True)
        self.airspaces = []

    def load(self):
        self.airspaces = []
        for path in glob.glob(os.path.join(self.base_dir, "*")):
            if not path.lower().endswith((".txt", ".openair", ".air")):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    self.airspaces.extend(parse_openair(fh.read()))
            except OSError:
                continue
        return len(self.airspaces)

    @staticmethod
    def contains(poly, lat, lon):
        inside = False
        pts = poly.get("points", [])
        if len(pts) < 3:
            return False
        j = len(pts) - 1
        for i in range(len(pts)):
            xi, yi = pts[i][1], pts[i][0]
            xj, yj = pts[j][1], pts[j][0]
            if ((yi > lat) != (yj > lat)) and (
                lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            ):
                inside = not inside
            j = i
        return inside

    def active_at(self, lat, lon, altitude_ft=0):
        hits = []
        for a in self.airspaces:
            if self.contains(a, lat, lon):
                hits.append(a)
        return hits


class SRTMElevation:
    """Reads optional 1-arc-second/3-arc-second SRTM HGT tiles stored locally."""
    def __init__(self, base_dir):
        self.base_dir = os.path.join(base_dir, "terrain")
        os.makedirs(self.base_dir, exist_ok=True)

    def elevation_ft(self, lat, lon):
        lat_i = math.floor(lat)
        lon_i = math.floor(lon)
        ns = "N" if lat_i >= 0 else "S"
        ew = "E" if lon_i >= 0 else "W"
        path = os.path.join(self.base_dir, f"{ns}{abs(lat_i):02d}{ew}{abs(lon_i):03d}.hgt")
        if not os.path.exists(path):
            return None
        size = os.path.getsize(path)
        samples = 3601 if size == 3601 * 3601 * 2 else 1201
        try:
            row = (lat_i + 1.0 - lat) * (samples - 1)
            col = (lon - lon_i) * (samples - 1)
            r, c = int(round(row)), int(round(col))
            r = max(0, min(samples - 1, r))
            c = max(0, min(samples - 1, c))
            with open(path, "rb") as fh:
                fh.seek((r * samples + c) * 2)
                value = struct.unpack(">h", fh.read(2))[0]
            return None if value == -32768 else value * 3.280839895
        except (OSError, struct.error):
            return None


class CabinCrewEngine:
    """Phase-driven cabin crew announcements and two-way interphone replies."""
    ANNOUNCEMENTS = {
        "GROUND": "Ladies and gentlemen, welcome aboard. Please make sure your seat belt is fastened.",
        "TAKEOFF": "Cabin crew, prepare for departure. Please be seated for takeoff.",
        "DEPARTURE": "Cabin crew, we are climbing. You may begin your cabin service when safe.",
        "CENTER": "Ladies and gentlemen, we are now in cruise. Cabin service will begin shortly.",
        "APPROACH": "Cabin crew, prepare the cabin for arrival. Please ensure all passengers are seated and secured.",
        "LANDING": "Ladies and gentlemen, we have landed. Please remain seated with your seat belt fastened until the aircraft is parked.",
    }

    def __init__(self):
        self.last_phase = None
        self.last_announcement = 0
        self.last_reply = 0

    def update(self, phase):
        now = time.time()
        if phase == self.last_phase or phase not in self.ANNOUNCEMENTS:
            return None
        if now - self.last_announcement < 20:
            return None
        self.last_phase = phase
        self.last_announcement = now
        return self.ANNOUNCEMENTS[phase]

    def call_reply(self, request):
        now = time.time()
        if now - self.last_reply < 3:
            return "Cabin crew: Stand by, please."
        self.last_reply = now
        text = (request or "").lower()
        if "service" in text:
            return "Cabin crew: We will begin service when conditions permit."
        if "seat" in text or "cabin" in text:
            return "Cabin crew: Cabin status is normal."
        if "prepare" in text or "arrival" in text:
            return "Cabin crew: Understood. We are preparing the cabin."
        return "Cabin crew: We copy. How can we assist?"

    def stage_voice(self, lat, lon):
        return region_voice_locale(lat, lon)


class OSMTileCache:
    """On-demand OpenStreetMap base-map tiles with compliant identification and caching."""
    TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    USER_AGENT = "AeroflyATC/1.2 (+https://github.com/ntambiryan324-ctrl/Air-Traffic-Control-Aerofly-)"

    def __init__(self, base_dir):
        self.cache_dir = os.path.join(base_dir, "map_tiles")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.pending = set()
        self.lock = threading.Lock()

    @staticmethod
    def tile_xy(lat, lon, zoom):
        lat = max(-85.05112878, min(85.05112878, float(lat)))
        n = 2 ** zoom
        x = int((lon + 180.0) / 360.0 * n)
        y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
        return x % n, max(0, min(n - 1, y))

    def request(self, lat, lon, zoom, callback):
        x, y = self.tile_xy(lat, lon, zoom)
        key = f"{zoom}_{x}_{y}"
        path = os.path.join(self.cache_dir, key + ".png")
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
            callback(path, key)
            return
        with self.lock:
            if key in self.pending:
                return
            self.pending.add(key)

        def worker():
            try:
                req = urllib.request.Request(
                    self.TILE_URL.format(z=zoom, x=x, y=y),
                    headers={"User-Agent": self.USER_AGENT},
                )
                with urllib.request.urlopen(req, timeout=8) as response:
                    data = response.read()
                tmp = path + ".tmp"
                with open(tmp, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, path)
                Clock.schedule_once(lambda *_: callback(path, key))
            except Exception:
                pass
            finally:
                with self.lock:
                    self.pending.discard(key)
        threading.Thread(target=worker, daemon=True).start()


class AirportData:
    """Optional global airport/runway/frequency database using public-domain OurAirports CSVs."""
    AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

    def __init__(self, base_dir):
        self.path = os.path.join(base_dir, "airports.csv")
        self.rows = []

    def load_local(self):
        if not os.path.exists(self.path):
            return 0
        try:
            with open(self.path, newline="", encoding="utf-8") as fh:
                self.rows = list(csv.DictReader(fh))
            return len(self.rows)
        except (OSError, csv.Error):
            self.rows = []
            return 0

    def update(self, callback=None):
        def worker():
            count = 0
            try:
                req = urllib.request.Request(self.AIRPORTS_URL, headers={"User-Agent": OSMTileCache.USER_AGENT})
                with urllib.request.urlopen(req, timeout=20) as response:
                    data = response.read()
                tmp = self.path + ".tmp"
                with open(tmp, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, self.path)
                count = self.load_local()
            except Exception:
                pass
            if callback:
                Clock.schedule_once(lambda *_: callback(count))
        threading.Thread(target=worker, daemon=True).start()

    def nearest(self, lat, lon):
        if not self.rows:
            return None
        best, best_d = None, float("inf")
        for row in self.rows:
            try:
                a, b = float(row["latitude_deg"]), float(row["longitude_deg"])
                d = ((lat-a)*110540.0)**2 + ((lon-b)*111320.0*math.cos(math.radians(lat)))**2
                if d < best_d:
                    best_d, best = d, row
            except (KeyError, TypeError, ValueError):
                continue
        return best
