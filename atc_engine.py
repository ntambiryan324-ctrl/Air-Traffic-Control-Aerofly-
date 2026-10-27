"""Simulator ATC engine for AeroflyATC. Pure Python, no Kivy.

Design (modelled on how PocketSky-style companions behave): the pilot types or
speaks a request, the engine answers in standard phraseology, remembers what it
asked for, and checks the pilot's readback. Anything it cannot handle goes to an
optional local LLM (local_ai_agent.OfflineATCAgent) that is only given verified
context. No real frequencies or procedures are invented: missing data produces
"say again / unable", never made-up facts. Simulation only, not real ATC.
"""
import math
import random
import re

from planner_core import decode_metar, distance_nm, bearing_deg, lookup_airport

_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "tree": "3", "four": "4",
          "five": "5", "fife": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
          "niner": "9", "ten": "10", "left": "l", "right": "r", "center": "c", "centre": "c"}


def normalize(text):
    """Lower-case, turn spoken numbers/suffixes into compact tokens for readback matching."""
    s = (text or "").lower().replace(",", "")
    s = re.sub(r"flight\s*level", "fl", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = " ".join(_WORDS.get(w, w) for w in s.split())
    s = re.sub(r"(?<=\d) (?=\d)", "", s)
    s = re.sub(r"(?<=\d) (?=[lrc]\b)", "", s)
    s = re.sub(r"(\d+) thousand", lambda m: m.group(1) + "000", s)
    s = re.sub(r"fl (\d+)", r"fl\1", s)
    return s


def contains_token(norm_text, token):
    t = normalize(token)
    return re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", norm_text) is not None


class ATCEngine:
    def __init__(self, llm=None):
        self.llm = llm
        self.callsign = "N123AB"
        self.phase = "PARKED"
        self.origin = ""
        self.dest = ""
        self.cruise_fl = 360
        self.metar = {}
        self.metar_icao = ""
        self.squawk = None
        self.dep_runway = ""
        self.arr_runway = ""
        self.runways = {}
        self.pending = {}
        self.last_reply = ""

    # ----- setup -----
    def set_plan(self, origin, dest, cruise_fl=None):
        self.origin, self.dest = (origin or "").upper(), (dest or "").upper()
        if cruise_fl:
            self.cruise_fl = int(cruise_fl)
        self.squawk = None

    def set_callsign(self, callsign):
        if callsign and callsign.strip():
            self.callsign = callsign.strip().upper()

    def set_metar(self, icao, raw):
        self.metar_icao = (icao or "").upper()
        self.metar = decode_metar(raw or "")

    def set_runways(self, icao, idents):
        self.runways[icao.upper()] = list(idents)

    # ----- helpers -----
    def _make_squawk(self):
        rng = random.Random(f"{self.callsign}{self.origin}{self.dest}")
        while True:
            code = "".join(str(rng.randint(0, 7)) for _ in range(4))
            if code not in ("7500", "7600", "7700", "1200", "0000"):
                return code

    def _wind_phrase(self):
        m = self.metar
        if not m or m.get("wind_kt") is None:
            return "wind not available"
        if m["wind_kt"] == 0:
            return "wind calm"
        d = "variable" if m["wind_dir"] is None else f"{m['wind_dir']:03d}"
        g = f", gusting {m['gust_kt']}" if m.get("gust_kt") else ""
        return f"wind {d} at {m['wind_kt']}{g}"

    def _altimeter(self):
        """Return (phrase, readback_token) or (None, None)."""
        m = self.metar
        if not m or (m.get("qnh_hpa") is None and m.get("altim_inhg") is None):
            return None, None
        if re.search(r"\bQ\d{4}\b", m.get("raw", "")):
            return f"QNH {m['qnh_hpa']}", str(m["qnh_hpa"])
        code = f"{int(round(m['altim_inhg'] * 100)):04d}"
        return f"altimeter {code}", code

    def _pick_runway(self, icao, manual):
        if manual:
            return manual
        idents = self.runways.get(icao.upper())
        if not idents:
            return ""
        wd, ws = self.metar.get("wind_dir"), self.metar.get("wind_kt") or 0
        if wd is None or ws == 0:
            return idents[0]

        def headwind(r):
            hdg = int(re.match(r"\d+", r).group(0)) * 10
            return ws * math.cos(math.radians(wd - hdg))
        return max(idents, key=headwind)

    def event(self, name):
        """Proactive controller message for a flight event (takeoff, top_of_descent, approach, landing)."""
        cs = self.callsign
        if name == "takeoff":
            self.phase, self.pending = "AIRBORNE", {}
            return f"DEPARTURE: {cs}, radar contact. Continue climb, expect FL{self.cruise_fl}."
        if name == "top_of_descent":
            self.phase = "DESCENT"
            return (f"CENTER: {cs}, descend at pilot's discretion. Expect approach into {self.dest or 'destination'}. "
                    "Fetch destination weather in PLAN.")
        if name == "approach":
            return f"APPROACH: {cs}, radar contact. Say 'inbound' for approach instructions."
        if name == "landing":
            self.phase, self.pending = "PARKED", {}
            return f"GROUND: {cs}, welcome to {self.dest or 'the field'}. Taxi to the gate via taxiways as published."
        return ""

    def atis(self, icao=None):
        icao = (icao or self.metar_icao or self.origin).upper()
        if not self.metar:
            return "No weather loaded. Fetch weather in PLAN first."
        m = self.metar
        letter = chr(ord("A") + int((m.get("time_z") or "0000Z")[:2]) % 24)
        parts = [f"{icao} information {letter}", f"time {m.get('time_z') or 'unknown'}", self._wind_phrase()]
        if m.get("vis"):
            parts.append(f"visibility {m['vis']}")
        if m.get("temp_c") is not None:
            parts.append(f"temperature {m['temp_c']}, dew point {m['dew_c']}")
        alt, _ = self._altimeter()
        if alt:
            parts.append(alt)
        parts.append(f"advise on initial contact you have information {letter}")
        return "ATIS: " + ". ".join(parts) + "."

    # ----- main entry -----
    def handle(self, text, snapshot=None):
        raw = (text or "").strip()
        if not raw:
            return ""
        reply = self._dispatch(raw, normalize(raw), snapshot or {})
        self.last_reply = reply
        return reply

    def _dispatch(self, raw, n, snap):
        cs = self.callsign
        if any(k in n for k in ("mayday", "pan pan", "emergency")):
            kind = "mayday" if "mayday" in n else "pan-pan"
            rwy = self._pick_runway(self.dest or self.origin, self.arr_runway)
            tail = f" Runway {rwy} is available." if rwy else ""
            return (f"CONTROL: {cs}, roger {kind}. Say nature of emergency, souls on board and fuel remaining. "
                    f"All other traffic is being kept clear.{tail}")

        m = re.search(r"runway (\d{1,2}[lrc]?)\b", n)
        ident = None
        if m:
            ident = m.group(1).upper()
            if self.phase in ("PARKED", "CLEARED", "TAXI"):
                self.dep_runway = ident
            else:
                self.arr_runway = ident

        if self.pending:
            # A message that repeats any pending item is a readback, even if it
            # also contains words like "squawk" or "taxi".
            echoes = any(contains_token(n, v) for v in self.pending.values())
            explicit = "request" in n or "ready" in n
            if (echoes and not explicit) or not self._is_request(n):
                return self._check_readback(n)

        if ident and not self._is_request(n):
            return f"CONTROL: {cs}, runway {ident} noted."

        if "say again" in n or "repeat" in n:
            return self.last_reply or f"CONTROL: {cs}, nothing to repeat."
        if "radio check" in n:
            return f"CONTROL: {cs}, loud and clear."
        if "atis" in n or "weather" in n or n.strip() in ("wx", "metar"):
            return self.atis()
        if "altimeter" in n or "qnh" in n:
            alt, _ = self._altimeter()
            return f"CONTROL: {cs}, {alt}." if alt else f"CONTROL: {cs}, altimeter not available."
        if "squawk" in n:
            if not self.squawk:
                self.squawk = self._make_squawk()
            self.pending = {"squawk": self.squawk}
            return f"CONTROL: {cs}, squawk {self.squawk}."
        if "clearance" in n or "ifr" in n:
            return self._clearance()
        if "taxi" in n or "push" in n:
            return self._taxi()
        if any(k in n for k in ("ready", "takeoff", "take off", "departure")):
            return self._takeoff()
        if any(k in n for k in ("inbound", "approach", "ils", "visual")):
            return self._approach()
        if re.search(r"\bland(ing)?\b", n):
            return self._landing(snap)
        d = re.search(r"direct (?:to )?([a-z0-9]{2,7})", n)
        if d:
            return self._direct(d.group(1).upper(), snap)
        alt = re.search(r"\bfl(\d{2,3})\b", n) or re.search(r"\b(\d{4,5}) ?(?:ft|feet)\b", n)
        if alt and any(k in n for k in ("climb", "descend", "descent", "request", "level")):
            return self._altitude(alt.group(0))
        return self._fallback(raw, snap)

    @staticmethod
    def _is_request(n):
        keys = ("request", "ready", "inbound", "taxi", "atis", "weather", "altimeter", "qnh",
                "direct", "mayday", "pan pan", "say again", "repeat", "radio check",
                "clearance", "squawk", "approach", "land", "push", "takeoff")
        return any(k in n for k in keys)

    def _check_readback(self, n):
        cs = self.callsign
        missing = [f"{k} {v}" for k, v in self.pending.items() if not contains_token(n, v)]
        if missing:
            return f"CONTROL: {cs}, negative. I need a readback of: " + ", ".join(missing) + "."
        self.pending = {}
        return f"CONTROL: {cs}, readback correct."

    def _clearance(self):
        cs = self.callsign
        if not self.dest:
            return f"CLEARANCE: {cs}, say destination. Set it in PLAN first."
        self.squawk = self._make_squawk()
        self.phase = "CLEARED"
        self.pending = {"squawk": self.squawk, "altitude": "5000"}
        return (f"CLEARANCE: {cs}, cleared to {self.dest} airport as filed. Climb and maintain 5000, "
                f"expect FL{self.cruise_fl} ten minutes after departure. Squawk {self.squawk}.")

    def _taxi(self):
        cs = self.callsign
        rwy = self._pick_runway(self.origin, self.dep_runway)
        if not rwy:
            return f"GROUND: {cs}, runway in use is not known. Say 'runway 28L' (your runway) and request taxi again."
        self.dep_runway = rwy
        self.phase = "TAXI"
        alt, token = self._altimeter()
        self.pending = {"runway": rwy}
        extra = f" {alt}." if alt else ""
        return f"GROUND: {cs}, taxi to runway {rwy} via taxiways as published, hold short.{extra}"

    def _takeoff(self):
        cs = self.callsign
        rwy = self._pick_runway(self.origin, self.dep_runway)
        if not rwy:
            return f"TOWER: {cs}, say runway."
        self.phase = "DEPARTING"
        self.pending = {"runway": rwy}
        return f"TOWER: {cs}, {self._wind_phrase()}, runway {rwy}, cleared for takeoff."

    def _approach(self):
        cs = self.callsign
        self.phase = "APPROACH"
        rwy = self._pick_runway(self.dest, self.arr_runway)
        if not rwy:
            return f"APPROACH: {cs}, runway in use is not known. Say 'runway 28L' for your arrival runway."
        self.arr_runway = rwy
        alt, token = self._altimeter()
        self.pending = {"runway": rwy}
        if token:
            self.pending["altimeter"] = token
        extra = f" {alt}." if alt else ""
        return f"APPROACH: {cs}, expect runway {rwy}, report established.{extra}"

    def _landing(self, snap):
        cs = self.callsign
        rwy = self._pick_runway(self.dest, self.arr_runway)
        if not rwy:
            return f"TOWER: {cs}, say runway."
        dest = lookup_airport(self.dest)
        if dest and snap.get("lat") is not None and snap.get("lon") is not None:
            d = distance_nm(snap["lat"], snap["lon"], dest["lat"], dest["lon"])
            if d > 15:
                return f"TOWER: {cs}, continue approach, {d:.0f} miles out. Report 10 mile final."
        self.phase = "LANDING"
        self.pending = {"runway": rwy}
        return f"TOWER: {cs}, {self._wind_phrase()}, runway {rwy}, cleared to land."

    def _direct(self, ident, snap):
        cs = self.callsign
        ap = lookup_airport(ident)
        if not ap:
            return f"CENTER: {cs}, unable direct {ident}. It is not in the loaded database."
        if snap.get("lat") is not None and snap.get("lon") is not None:
            brg = bearing_deg(snap["lat"], snap["lon"], ap["lat"], ap["lon"])
            dist = distance_nm(snap["lat"], snap["lon"], ap["lat"], ap["lon"])
            return f"CENTER: {cs}, proceed direct {ident}. Bearing {brg:03.0f}, {dist:.0f} miles."
        return f"CENTER: {cs}, proceed direct {ident}."

    def _altitude(self, token):
        cs = self.callsign
        t = normalize(token)
        if t.startswith("fl"):
            level = int(t[2:])
            if level > 450 or level < 10:
                return f"CENTER: {cs}, unable FL{level:03d}."
            value = f"FL{level}"
        else:
            feet = int(re.sub(r"\D", "", t))
            if feet > 45000:
                return f"CENTER: {cs}, unable {feet}."
            value = str(feet)
        self.pending = {"altitude": value}
        return f"CENTER: {cs}, climb or descend and maintain {value}."

    def _fallback(self, raw, snap):
        cs = self.callsign
        if self.llm is not None:
            try:
                ctx = {"phase": self.phase, "origin": self.origin, "dest": self.dest,
                       "metar": self.metar.get("raw", ""), "squawk": self.squawk}
                answer = self.llm.respond(raw, aircraft=snap, context=ctx)
                if answer:
                    return answer
            except Exception:
                pass
        return f"CONTROL: {cs}, say again, request not understood."
