"""Flight plan tabs: Info, Table, Load, Profile, Export.

The data model is plain Python so it can be tested without Kivy. The view
(FlightPlanTabs) is a Kivy widget that renders each tab from the model. Nothing
here fetches data; callers pass in the waypoints, fuel rates and weights.
Simulation planning only, not for real-world navigation.
"""
import json
from dataclasses import dataclass, field

TABS = ("Info", "Table", "Load", "Profile", "Export")

# Fuel reserve defaults in minutes at burn rate, matching the reference app layout.
TAXI_MIN = 20
FINAL_RESERVE_MIN = 30
CONTINGENCY_PCT = 5


@dataclass
class Waypoint:
    ident: str
    altitude_ft: int
    distance_nm: float
    course_deg: int
    airway: str = ""


@dataclass
class FlightPlan:
    departure: str
    arrival: str
    aircraft: str
    cruise_fl: int
    mach: float
    burn_kg_per_hr: float
    trip_minutes: int
    alternate: str = ""
    alternate_minutes: int = 26
    payload_pct: int = 85
    max_payload_kg: int = 56950
    waypoints: list = field(default_factory=list)
    callsign: str = ""

    def info(self):
        return {
            "title": f"{self.departure} -> {self.arrival}",
            "aircraft": self.aircraft,
            "cruise": f"FL{self.cruise_fl}",
            "mach": f"M{self.mach:.2f}",
            "alternate": self.alternate or "none",
            "callsign": self.callsign or "not set",
        }

    def table(self):
        return [
            {"ident": w.ident, "alt_ft": w.altitude_ft, "dist_nm": w.distance_nm,
             "course": w.course_deg, "airway": w.airway or "DCT"}
            for w in self.waypoints
        ]

    def fuel(self):
        """Block fuel breakdown in kg. Taxi, contingency, alternate and reserve are added to trip fuel."""
        per_min = self.burn_kg_per_hr / 60.0
        trip = self.trip_minutes * per_min
        taxi = TAXI_MIN * per_min * 0.5
        contingency = trip * CONTINGENCY_PCT / 100.0
        alternate = self.alternate_minutes * per_min
        reserve = FINAL_RESERVE_MIN * per_min
        block = trip + taxi + contingency + alternate + reserve
        return {
            "trip_kg": round(trip), "taxi_kg": round(taxi), "contingency_kg": round(contingency),
            "alternate_kg": round(alternate), "final_reserve_kg": round(reserve),
            "block_kg": round(block),
        }

    def load(self):
        payload = round(self.max_payload_kg * self.payload_pct / 100)
        return {"payload_pct": self.payload_pct, "payload_kg": payload, "fuel": self.fuel()}

    def profile(self):
        """Simple climb / cruise / descent altitude profile as (nm, ft) points."""
        cruise_ft = self.cruise_fl * 100
        total = sum(w.distance_nm for w in self.waypoints) or 1.0
        climb = min(total * 0.1, 120.0)
        descent = min(total * 0.1, 120.0)
        return [(0.0, 0), (climb, cruise_ft), (total - descent, cruise_ft), (total, 0)]

    def export_geofs(self):
        """GeoFS-style flight plan JSON built from the waypoint list."""
        return json.dumps({
            "name": f"{self.departure}{self.arrival}01",
            "aircraft": self.aircraft,
            "waypoints": [
                {"name": w.ident, "altitude": w.altitude_ft, "distance": w.distance_nm,
                 "course": w.course_deg, "airway": w.airway}
                for w in self.waypoints
            ],
        }, indent=2)


def tab_content(plan, tab):
    """Return the text lines for a tab, so the view and tests use the same data."""
    if tab == "Info":
        return [f"{k}: {v}" for k, v in plan.info().items()]
    if tab == "Table":
        return [f"{r['ident']}  {r['alt_ft']} ft  {r['dist_nm']} nm  {r['course']:03d}  {r['airway']}"
                for r in plan.table()]
    if tab == "Load":
        ld = plan.load()
        return [f"payload {ld['payload_kg']} kg ({ld['payload_pct']}%)"] + \
               [f"{k}: {v} kg" for k, v in ld["fuel"].items()]
    if tab == "Profile":
        return [f"{nm:.0f} nm: {ft} ft" for nm, ft in plan.profile()]
    if tab == "Export":
        return plan.export_geofs().splitlines()
    raise ValueError(f"unknown tab: {tab}")


try:
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.scrollview import ScrollView

    class FlightPlanTabs(BoxLayout):
        """Tab bar plus a scrolling text area that shows the selected tab."""

        def __init__(self, plan, **kwargs):
            super().__init__(orientation="vertical", **kwargs)
            self.plan = plan
            self.bar = BoxLayout(size_hint_y=None, height=48)
            for name in TABS:
                btn = Button(text=name)
                btn.bind(on_release=lambda _b, n=name: self.show(n))
                self.bar.add_widget(btn)
            self.add_widget(self.bar)
            self.body = Label(text="", halign="left", valign="top", size_hint_y=None)
            self.body.bind(texture_size=lambda w, size: setattr(w, "height", size[1]))
            self.body.bind(width=lambda w, width: setattr(w, "text_size", (width, None)))
            self.scroll = ScrollView()
            self.scroll.add_widget(self.body)
            self.add_widget(self.scroll)
            self.show("Info")

        def show(self, tab):
            self.body.text = "\n".join(tab_content(self.plan, tab))
except ImportError:
    # Kivy is not installed in test environments; the data model above still works.
    FlightPlanTabs = None
