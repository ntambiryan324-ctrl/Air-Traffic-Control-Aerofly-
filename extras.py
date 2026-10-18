"""Logbook, checklists and flight-event monitor for AeroflyATC. Pure Python, no Kivy."""
import json
import os
import time

from planner_core import distance_nm

CHECKLISTS = {
    "BEFORE START": ["Flight plan and weather reviewed", "Fuel and weights set", "Parking brake SET",
                     "Battery / external power ON", "Beacon ON", "Altimeters set", "Avionics and FMS programmed"],
    "AFTER START": ["Engines running, parameters normal", "Flaps set for takeoff", "Flight controls free and correct",
                    "Anti-ice as required", "Taxi clearance received"],
    "TAXI": ["Brakes checked", "Taxi lights ON", "Flight instruments cross-checked", "Takeoff briefing done"],
    "BEFORE TAKEOFF": ["Runway confirmed", "Transponder ON / squawk set", "Landing and strobe lights ON",
                       "Flaps and trim set", "Autopilot modes armed", "Cleared for takeoff"],
    "CLIMB / CRUISE": ["Gear UP", "Flaps UP", "Landing lights OFF above 10,000 ft", "Altimeter to standard at transition",
                       "Fuel and systems monitored"],
    "DESCENT": ["ATIS / weather obtained", "Altimeter set", "Approach briefed", "Landing weight and speeds computed",
                "Seat belt signs ON"],
    "APPROACH": ["Navaids tuned and identified", "Approach mode armed", "Speed and flaps per schedule",
                 "Landing lights ON", "Minimums set"],
    "LANDING": ["Gear DOWN", "Flaps landing", "Speedbrake armed", "Cleared to land", "Stabilised by 1000 ft"],
    "SHUTDOWN": ["Parking brake SET", "Engines OFF", "Beacon OFF", "Lights OFF", "Battery OFF", "Logbook updated"],
}


class Logbook:
    def __init__(self, path):
        self.path = path

    def entries(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def add(self, entry):
        data = self.entries()
        data.append(entry)
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            return False
        return True

    def summary(self, last=8):
        data = self.entries()
        if not data:
            return "No flights logged yet. Flights are logged automatically from takeoff to landing."
        hours = sum(e.get("minutes", 0) for e in data) / 60.0
        nm = sum(e.get("nm", 0) for e in data)
        lines = ["%d flights   %.1f h   %.0f NM" % (len(data), hours, nm), ""]
        for e in reversed(data[-last:]):
            lines.append("%s  %s > %s  %dh%02dm  %.0f NM  max %d ft" % (
                e.get("date", "?"), e.get("origin") or "----", e.get("dest") or "----",
                int(e.get("minutes", 0)) // 60, int(e.get("minutes", 0)) % 60, e.get("nm", 0), e.get("max_alt", 0)))
        return "\n".join(lines)


class FlightMonitor:
    """Turns telemetry snapshots into events: takeoff, top_of_descent, approach, landing."""

    def __init__(self, logbook=None):
        self.logbook = logbook
        self.origin = ""
        self.dest = ""
        self.dest_pos = None
        self.tod_remaining_nm = None
        self.reset_flight()
        self.ref_alt = None

    def reset_flight(self):
        self.airborne = False
        self.t_off = None
        self.nm = 0.0
        self.max_alt = 0.0
        self.last_pos = None
        self.last_t = None
        self.fired = set()

    def set_plan(self, origin, dest, dest_pos, tod_remaining_nm):
        self.origin, self.dest = origin, dest
        self.dest_pos, self.tod_remaining_nm = dest_pos, tod_remaining_nm

    def update(self, snap, now=None):
        now = time.time() if now is None else now
        if not snap.get("connected") or snap.get("lat") is None:
            return []
        lat, lon = snap["lat"], snap["lon"]
        gs, alt = snap.get("speed_kt", 0.0), snap.get("alt_ft", 0.0)
        events = []
        if not self.airborne:
            if gs < 5:
                self.ref_alt = alt
            elif gs >= 60 and self.ref_alt is not None and alt - self.ref_alt > 150:
                self.airborne, self.t_off = True, now
                self.nm, self.max_alt, self.last_pos, self.last_t, self.fired = 0.0, alt, (lat, lon), now, {"takeoff"}
                events.append("takeoff")
            return events
        if self.last_pos and self.last_t is not None:
            step = distance_nm(self.last_pos[0], self.last_pos[1], lat, lon)
            hours = max(now - self.last_t, 1e-3) / 3600.0
            if step / hours < 1500:  # ignore teleports and bad samples (implied speed over 1500 kt)
                self.nm += step
        self.last_pos, self.last_t = (lat, lon), now
        self.max_alt = max(self.max_alt, alt)
        if self.dest_pos:
            remaining = distance_nm(lat, lon, self.dest_pos[0], self.dest_pos[1])
            if ("tod" not in self.fired and self.tod_remaining_nm and alt > 10000
                    and remaining <= self.tod_remaining_nm):
                self.fired.add("tod")
                events.append("top_of_descent")
            if "approach" not in self.fired and remaining <= 25 and "takeoff" in self.fired and now - self.t_off > 120:
                self.fired.add("approach")
                events.append("approach")
        if gs < 40 and now - self.t_off > 60:
            minutes = (now - self.t_off) / 60.0
            if self.logbook:
                self.logbook.add({"date": time.strftime("%Y-%m-%d", time.localtime(now)), "origin": self.origin,
                                  "dest": self.dest, "minutes": round(minutes, 1), "nm": round(self.nm, 1),
                                  "max_alt": int(self.max_alt)})
            self.reset_flight()
            self.ref_alt = alt
            events.append("landing")
        return events
