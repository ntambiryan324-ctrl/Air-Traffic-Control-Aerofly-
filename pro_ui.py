import json
import math
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import advanced_features as adv
from operations_ui import OperationsScreen

from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle, Ellipse
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen, ScreenManager, FadeTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

try:
    from kivy_garden.mapview import MapView, MapMarker, MapSource, MapLayer
    MAPVIEW_AVAILABLE = True
    MAPVIEW_IMPORT_ERROR = ""
except Exception as _map_exc:
    MapView = MapMarker = MapSource = MapLayer = None
    MAPVIEW_AVAILABLE = False
    MAPVIEW_IMPORT_ERROR = repr(_map_exc)

core = sys.modules.get("__main__")
Telemetry = core.Telemetry
Copilot = core.Copilot
FlightOps = core.FlightOps

BG = (0.025, 0.035, 0.050, 1)
PANEL = (0.055, 0.075, 0.105, 1)
PANEL2 = (0.075, 0.100, 0.140, 1)
ACCENT = (0.12, 0.62, 0.98, 1)
GREEN = (0.18, 0.82, 0.48, 1)
AMBER = (1.0, 0.67, 0.18, 1)
RED = (0.95, 0.25, 0.28, 1)
TEXT = (0.93, 0.96, 0.99, 1)
MUTED = (0.56, 0.64, 0.74, 1)

MAJOR_AIRPORTS = {
    "HUEN": (0.0424, 32.4435, "Entebbe International"),
    "HKJK": (-1.3192, 36.9278, "Jomo Kenyatta International"),
    "FAOR": (-26.1367, 28.2411, "O.R. Tambo International"),
    "EGLL": (51.4700, -0.4543, "London Heathrow"),
    "EHAM": (52.3105, 4.7683, "Amsterdam Schiphol"),
    "EDDF": (50.0379, 8.5622, "Frankfurt"),
    "LFPG": (49.0097, 2.5479, "Paris Charles de Gaulle"),
    "OMDB": (25.2532, 55.3657, "Dubai International"),
    "KJFK": (40.6413, -73.7781, "John F Kennedy"),
    "KLAX": (33.9425, -118.4081, "Los Angeles"),
    "KSFO": (37.6213, -122.3790, "San Francisco"),
    "KORD": (41.9742, -87.9073, "Chicago O'Hare"),
    "KATL": (33.6407, -84.4277, "Atlanta"),
    "RJTT": (35.5494, 139.7798, "Tokyo Haneda"),
    "YSSY": (-33.9399, 151.1753, "Sydney"),
}

class Card(BoxLayout):
    def __init__(self, **kw):
        super().__init__(padding=dp(10), spacing=dp(7), **kw)
        with self.canvas.before:
            Color(*PANEL)
            self.bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self.sync, size=self.sync)
    def sync(self, *_):
        self.bg.pos = self.pos
        self.bg.size = self.size

def button(text, active=False, height=42):
    b = Button(text=text, size_hint_y=None, height=dp(height), background_normal="", background_down="",
               background_color=ACCENT if active else PANEL2,
               color=BG if active else TEXT, font_size="11sp", bold=active)
    return b

class Header(BoxLayout):
    def __init__(self, title, subtitle="", app_ref=None, **kw):
        super().__init__(size_hint_y=None, height=dp(64), padding=(dp(12), dp(6)), spacing=dp(8), **kw)
        box = BoxLayout(orientation="vertical")
        box.add_widget(Label(text=title, color=TEXT, font_size="20sp", bold=True, halign="left"))
        if subtitle:
            box.add_widget(Label(text=subtitle, color=MUTED, font_size="10sp", halign="left"))
        self.add_widget(box)
        if app_ref:
            q = button("SETTINGS", height=38)
            q.size_hint_x = None
            q.width = dp(82)
            q.bind(on_press=lambda *_: app_ref.go("settings"))
            self.add_widget(q)

MapMarkerBase = MapMarker if MAPVIEW_AVAILABLE else Widget
MapLayerBase = MapLayer if MAPVIEW_AVAILABLE else Widget

class AircraftMarker(MapMarkerBase):
    def __init__(self, **kw):
        super().__init__(source=os.path.join(os.path.dirname(__file__), "assets", "aircraft.svg"),
                         size=(dp(34), dp(34)), anchor_x=.5, anchor_y=.5, **kw)

class FlightPathLayer(MapLayerBase):
    def __init__(self, mapview, points=None, color=ACCENT, width=2.2, **kw):
        super().__init__(**kw)
        self.mapview = mapview
        self.points = points or []
        with self.canvas:
            Color(*color)
            self.line = Line(points=[], width=dp(width))
    def set_points(self, points):
        self.points = list(points)
        self.reposition()
    def reposition(self):
        pts = []
        for lat, lon in self.points:
            x, y = self.mapview.get_window_xy_from(lat, lon, self.mapview.zoom)
            pts.extend([x - self.x, y - self.y])
        self.line.points = pts
    def unload(self):
        self.canvas.clear()


class SafeMovingMap(Widget):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.data = {}
        self.trail = []
        self.plan = []
        self.bind(pos=lambda *_: self.redraw(), size=lambda *_: self.redraw())
    def update(self, data, trail, plan):
        self.data, self.trail, self.plan = data, trail[-250:], plan
        self.redraw()
    def redraw(self):
        self.canvas.clear()
        with self.canvas:
            Color(0.025, 0.045, 0.065, 1)
            Rectangle(pos=self.pos, size=self.size)
            lat, lon = float(self.data.get("lat", 0)), float(self.data.get("lon", 0))
            if not self.data.get("connected") or (lat == 0 and lon == 0):
                return
            scale = min(self.width, self.height) / 0.15
            def project(p):
                a, b = p
                return self.center_x + (b-lon)*scale, self.center_y + (a-lat)*scale
            if len(self.trail) > 1:
                Color(*ACCENT)
                pts = []
                for p in self.trail:
                    x, y = project(p); pts += [x, y]
                Line(points=pts, width=2)
            if len(self.plan) > 1:
                Color(*AMBER)
                pts = []
                for p in self.plan:
                    x, y = project(p); pts += [x, y]
                Line(points=pts, width=1.4)
            Color(*ACCENT)
            x, y = self.center
            Ellipse(pos=(x-dp(9), y-dp(9)), size=(dp(18), dp(18)))
            Color(*TEXT)
            Line(circle=(x, y, dp(28)), width=1)

class AviationMap(BoxLayout):
    def __init__(self, app_ref, **kw):
        super().__init__(orientation="vertical", **kw)
        self.app_ref = app_ref
        self.follow = True
        self.chart = False
        self.marker = AircraftMarker(lat=0, lon=0) if MAPVIEW_AVAILABLE else None
        self.map = MapView(zoom=5, lat=0, lon=0, double_tap_zoom=True, pause_on_action=True) if MAPVIEW_AVAILABLE else SafeMovingMap()
        if MAPVIEW_AVAILABLE:
            self.map.map_source = MapSource(url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                                        cache_key="osm-live", min_zoom=1, max_zoom=19, tile_size=256,
                                            attribution="© OpenStreetMap contributors", subdomains="abc")
            self.map.add_marker(self.marker)
        self.actual_layer = FlightPathLayer(self.map, [], color=ACCENT, width=2.2) if MAPVIEW_AVAILABLE else None
        self.planned_layer = FlightPathLayer(self.map, [], color=AMBER, width=1.6) if MAPVIEW_AVAILABLE else None
        if MAPVIEW_AVAILABLE:
            self.map.add_layer(self.actual_layer, mode="scatter")
            self.map.add_layer(self.planned_layer, mode="scatter")
        self.add_widget(self.map)
    def aviation_source(self):
        if not MAPVIEW_AVAILABLE:
            return None
        key = self.app_ref.openaip_key.strip()
        if not key:
            return None
        return MapSource(
            url="https://{s}.api.tiles.openaip.net/api/data/openaip/{z}/{x}/{y}.png?apiKey=" + urllib.parse.quote(key),
            cache_key="openaip-" + key[-8:],
            min_zoom=8, max_zoom=16, tile_size=256,
            attribution="openAIP aviation data",
            subdomains="abc")
    def set_chart(self):
        src = self.aviation_source()
        if src is None:
            self.app_ref.set_alert("OpenAIP chart needs an API key in Settings.", "warning")
            return
        self.chart = True
        self.map.map_source = src
        self.map.zoom = max(8, self.map.zoom)
        self.app_ref.set_alert("Aviation chart layer enabled.", "info")
    def set_radar_source(self, radar_url):
        if not MAPVIEW_AVAILABLE or self.map is None or not hasattr(self.map, "map_source"):
            return False
        self.map.map_source = MapSource(url=radar_url, cache_key="rainviewer-radar", min_zoom=1, max_zoom=7, tile_size=256, attribution="Weather data by RainViewer", subdomains="")
        self.map.zoom = min(max(self.map.zoom, 3), 7)
        self.chart = False
        return True

    def set_base(self):
        self.chart = False
        self.map.map_source = MapSource(url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                                        cache_key="osm-live", min_zoom=1, max_zoom=19, tile_size=256,
                                        attribution="© OpenStreetMap contributors", subdomains="abc")
    def refresh(self, d, trail):
        if not MAPVIEW_AVAILABLE:
            self.map.update(d, trail, self.app_ref.plan.get("points", []))
            return
        if d.get("connected"):
            lat, lon = float(d["lat"]), float(d["lon"])
            self.marker.lat, self.marker.lon = lat, lon
            if self.follow:
                self.map.center_on(lat, lon)
            if self.map.zoom < 8 and abs(lat) + abs(lon) > 0.01:
                self.map.zoom = 8
        self.actual_layer.set_points(trail[-250:])
        self.planned_layer.set_points(self.app_ref.plan.get("points", []))
    def center(self):
        d = self.app_ref.telemetry.snapshot()
        if d.get("connected") and MAPVIEW_AVAILABLE:
            self.follow = True
            self.map.center_on(float(d["lat"]), float(d["lon"]))

class MapScreen(Screen):
    def __init__(self, app_ref, **kw):
        super().__init__(**kw)
        self.app_ref = app_ref
        root = BoxLayout(orientation="vertical")
        root.add_widget(Header("MY FLIGHT", "Live moving map • flight follow • route", app_ref))
        tools = BoxLayout(size_hint_y=None, height=dp(43), spacing=dp(4), padding=dp(4))
        for label, fn in (
            ("FOLLOW", self.follow),
            ("RECENTER", self.recenter),
            ("STREET", self.street),
            ("AVIATION", self.aviation),
            ("FLIGHT PLAN", lambda *_: app_ref.go("flightplan")),
        ):
            q = button(label, height=35)
            q.bind(on_press=fn)
            tools.add_widget(q)
        root.add_widget(tools)
        self.map = AviationMap(app_ref)
        root.add_widget(self.map)
        self.banner = Label(text="Waiting for Aerofly telemetry", color=MUTED, size_hint_y=None, height=dp(28), font_size="10sp")
        root.add_widget(self.banner)
        self.add_widget(root)
    def follow(self, *_):
        self.map.follow = True
        self.recenter()
    def recenter(self, *_):
        self.map.center()
    def street(self, *_):
        self.map.set_base()
    def aviation(self, *_):
        self.map.set_chart()
    def refresh(self, d):
        self.map.refresh(d, self.app_ref.telemetry.trail_snapshot())
        if d.get("connected"):
            self.banner.text = "%s  •  %03.0f°  •  %.0f ft  •  %.0f kt  •  %s" % (
                d.get("source_ip") or "LOCAL", d.get("heading", 0), d.get("altitude", 0),
                d.get("speed", 0), d.get("transport", "DATA"))
            self.banner.color = GREEN
        else:
            self.banner.text = "Waiting for Aerofly • TCP 58585 / UDP 40092"
            self.banner.color = AMBER

class MyFlightScreen(Screen):
    def __init__(self, app_ref, **kw):
        super().__init__(**kw)
        self.app_ref = app_ref
        root = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(7))
        root.add_widget(Header("FLIGHT STATUS", "Cockpit-grade telemetry at a glance", app_ref))
        self.connection = Label(text="●  WAITING FOR AEROFLY", color=AMBER, size_hint_y=None, height=dp(25), bold=True)
        root.add_widget(self.connection)
        card = Card(orientation="vertical", size_hint_y=None, height=dp(82))
        row = BoxLayout()
        self.phase = Label(text="WAITING", color=ACCENT, font_size="22sp", bold=True, halign="left")
        self.callsign = Label(text="UNKNOWN", color=TEXT, font_size="18sp", bold=True, halign="right")
        row.add_widget(self.phase); row.add_widget(self.callsign); card.add_widget(row)
        self.route = Label(text="ORIGIN  —   →   DESTINATION  —", color=MUTED, font_size="11sp")
        card.add_widget(self.route)
        root.add_widget(card)
        g = GridLayout(cols=3, spacing=dp(5), size_hint_y=None, height=dp(190))
        self.m = {}
        for key in ("ALTITUDE","TAS","HEADING","V/S","POSITION","TOD","PITCH","BANK","AIR/GROUND"):
            c = Card(orientation="vertical")
            c.add_widget(Label(text=key, color=MUTED, font_size="9sp"))
            v = Label(text="—", color=TEXT, font_size="17sp", bold=True)
            c.add_widget(v); self.m[key] = v; g.add_widget(c)
        root.add_widget(g)
        self.alert = Label(text="No active flight alerts.", color=MUTED, size_hint_y=None, height=dp(32))
        root.add_widget(self.alert)
        root.add_widget(Label(text="FSWidgets receiver  •  TCP 58585 + UDP 40092  •  packets are decoded continuously",
                              color=MUTED, font_size="9sp", size_hint_y=None, height=dp(20)))
        self.add_widget(root)
    def refresh(self, d):
        connected = d.get("connected")
        self.connection.text = "●  AEROFLY CONNECTED" if connected else "●  WAITING FOR AEROFLY"
        self.connection.color = GREEN if connected else AMBER
        self.phase.text = d.get("phase", "WAITING")
        self.callsign.text = d.get("callsign", "UNKNOWN")
        self.route.text = "%s  →  %s" % (self.app_ref.plan.get("origin","—"), self.app_ref.plan.get("dest","—"))
        self.m["ALTITUDE"].text = "%.0f ft" % d.get("altitude",0)
        self.m["TAS"].text = "%.0f kt" % d.get("speed",0)
        self.m["HEADING"].text = "%03.0f°" % d.get("heading",0)
        self.m["V/S"].text = "%+.0f fpm" % d.get("vertical_speed",0)
        self.m["POSITION"].text = "%.4f / %.4f" % (d.get("lat",0),d.get("lon",0))
        tod = FlightOps.tod_nm(d.get("altitude",0), self.app_ref.plan.get("tod_alt",3000), d.get("speed",0))
        self.m["TOD"].text = "%.1f NM" % tod if tod is not None else "—"
        self.m["PITCH"].text = "%+.1f°" % d.get("pitch",0)
        self.m["BANK"].text = "%+.1f°" % d.get("bank",0)
        self.m["AIR/GROUND"].text = "GROUND" if d.get("on_ground") else "AIRBORNE"
        self.alert.text = self.app_ref.alert_text or "No active flight alerts."
        self.alert.color = RED if self.app_ref.alert_level == "danger" else AMBER if self.app_ref.alert_level == "warning" else MUTED

class GeminiATC:
    def __init__(self, key="", model="gemini-3.6-flash"):
        self.key = key
        self.model = model
        self.history = []
    def ask(self, telemetry, pilot_text, callback):
        if not self.key:
            Clock.schedule_once(lambda *_: callback(False, "Gemini API key is not configured. Open Settings."), 0)
            return
        d = telemetry
        system = (
            "You are the ATC controller inside an Aerofly FS Global flight companion. "
            "Use realistic ICAO aviation radio phraseology. Be concise and operational. "
            "Never invent that a simulator command was executed. You may issue clearances, "
            "frequency changes, headings, altitudes, speed instructions, traffic advisories, "
            "ATIS-style information and readbacks. If information is missing, ask for it. "
            "Return only the controller transmission, without explanations."
        )
        context = (
            "LIVE FLIGHT DATA: callsign=%s, position=%.5f %.5f, altitude=%.0f ft, "
            "groundspeed=%.0f kt, heading=%03.0f, vertical speed=%+.0f fpm, phase=%s, "
            "origin=%s, destination=%s, COM1=%s, COM2=%s. "
            "PILOT TRANSMISSION: %s"
        ) % (d.get("callsign","UNKNOWN"), d.get("lat",0), d.get("lon",0), d.get("altitude",0),
             d.get("speed",0), d.get("heading",0), d.get("vertical_speed",0), d.get("phase","WAITING"),
             "—", "—", "—", "—", pilot_text)
        history = self.history[-8:]
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": history + [{"role": "user", "parts": [{"text": context}]}],
            "generationConfig": {"maxOutputTokens": 300}
        }
        url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % urllib.parse.quote(self.model, safe="")
        def worker():
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type":"application/json", "x-goog-api-key":self.key},
                    method="POST")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                self.history.extend([
                    {"role":"user","parts":[{"text":pilot_text}]},
                    {"role":"model","parts":[{"text":text}]}
                ])
                Clock.schedule_once(lambda *_: callback(True, text), 0)
            except Exception as exc:
                Clock.schedule_once(lambda *_: callback(False, "Gemini request failed: %s" % exc), 0)
        threading.Thread(target=worker, daemon=True).start()

class CommsScreen(Screen):
    def __init__(self, app_ref, **kw):
        super().__init__(**kw)
        self.app_ref = app_ref
        root = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(7))
        root.add_widget(Header("COMMS", "Two-way ATC / pilot text interface", app_ref))
        radio = Card(size_hint_y=None, height=dp(92))
        self.com1 = Label(text="COM1   118.000", color=TEXT, font_size="18sp", bold=True)
        self.com2 = Label(text="COM2   121.500", color=MUTED, font_size="14sp")
        radio.add_widget(self.com1); radio.add_widget(self.com2)
        tune = button("OPEN FREQUENCY PANEL", height=38); tune.size_hint_x=None; tune.width=dp(170); tune.bind(on_press=lambda *_:app_ref.go("frequencies")); radio.add_widget(tune)
        root.add_widget(radio)
        self.chat = TextInput(text="ATC RADIO READY\n\nFSWidgets telemetry is the simulator data source. Gemini will answer only after a pilot transmission.",
                              readonly=True, multiline=True, background_color=BG, foreground_color=TEXT, cursor_color=ACCENT)
        root.add_widget(self.chat)
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(5))
        self.input = TextInput(hint_text="Pilot transmission…", multiline=False, background_color=PANEL2, foreground_color=TEXT)
        send = button("TRANSMIT", True, 44); send.size_hint_x=None; send.width=dp(92); send.bind(on_press=self.send)
        afk = button("AFK: OFF", 44); afk.size_hint_x=None; afk.width=dp(82); afk.bind(on_press=self.toggle_afk); self.afk = afk
        row.add_widget(self.input); row.add_widget(afk); row.add_widget(send); root.add_widget(row)
        self.add_widget(root)
    def toggle_afk(self, *_):
        self.app_ref.copilot.afk = not self.app_ref.copilot.afk
        self.afk.text = "AFK: ON" if self.app_ref.copilot.afk else "AFK: OFF"
        self.afk.background_color = ACCENT if self.app_ref.copilot.afk else PANEL2
    def send(self, *_):
        text = self.input.text.strip()
        if not text: return
        self.append("PILOT", text)
        self.input.text = ""
        self.app_ref.copilot.observe_atc(text, "PILOT", self.com1.text[-7:])
        readback=self.app_ref.clearance.readback(text)
        if self.app_ref.clearance.current: self.append("READBACK", "CORRECT" if readback else "NOT VERIFIED")
        self.app_ref.gemini.ask(self.app_ref.telemetry.snapshot(), text, self.reply)
    def reply(self, ok, text):
        self.append("ATC", text)
        if ok:
            self.app_ref.copilot.observe_atc(text, "GEMINI ATC", self.com1.text[-7:])
            self.app_ref.clearance.parse(text)
            self.app_ref.set_alert("New ATC transmission received.", "info")
    def append(self, speaker, text):
        self.chat.text += "\n\n%s\n%s" % (speaker, text)
        self.chat.cursor = (0, 0)

class FrequenciesScreen(Screen):
    PRESETS = [
        ("121.500","GUARD / EMERGENCY"),("118.000","TOWER"),("118.100","TOWER"),
        ("118.700","GROUND"),("121.900","CLEARANCE"),("124.850","APPROACH"),
        ("125.700","DEPARTURE"),("127.800","CENTER"),("129.250","ATIS"),("122.800","UNICOM")
    ]
    def __init__(self, app_ref, **kw):
        super().__init__(**kw); self.app_ref=app_ref
        root=BoxLayout(orientation="vertical",spacing=dp(6),padding=dp(7))
        root.add_widget(Header("FREQUENCIES","COM1 / COM2 frequency control",app_ref))
        self.active=Label(text="COM1 ACTIVE  118.000   •   COM2 STANDBY 121.500",color=TEXT,size_hint_y=None,height=dp(30),bold=True);root.add_widget(self.active)
        row=BoxLayout(size_hint_y=None,height=dp(48),spacing=dp(5))
        self.entry=TextInput(text="118.000",multiline=False,background_color=PANEL2,foreground_color=TEXT)
        a=button("SET COM1",True,42);a.size_hint_x=None;a.width=dp(95);a.bind(on_press=lambda *_:self.set_freq(1))
        b=button("SET COM2",42);b.size_hint_x=None;b.width=dp(95);b.bind(on_press=lambda *_:self.set_freq(2))
        row.add_widget(self.entry);row.add_widget(a);row.add_widget(b);root.add_widget(row)
        s=ScrollView();box=BoxLayout(orientation="vertical",spacing=dp(4),padding=dp(3),size_hint_y=None);box.bind(minimum_height=box.setter("height"))
        for f,n in self.PRESETS:
            q=button("%s    %s"%(f,n),height=43);q.bind(on_press=lambda _,x=f:self.select(x));box.add_widget(q)
        s.add_widget(box);root.add_widget(s);self.add_widget(root)
    def select(self,f):self.entry.text=f;self.set_freq(1)
    def set_freq(self,radio):
        f=self.entry.text.strip()
        if not re.fullmatch(r"1\d{2}\.\d{3}",f):
            self.app_ref.set_alert("Frequency must look like 118.000.", "warning");return
        if radio==1:self.app_ref.com1=f
        else:self.app_ref.com2=f
        self.active.text="COM1 ACTIVE %s   •   COM2 STANDBY %s"%(self.app_ref.com1,self.app_ref.com2)
        self.app_ref.set_alert("COM%d set to %s. This companion tracks the radio state; direct simulator frequency write requires an exposed control API."%(radio,f),"info")

class FlightPlanScreen(Screen):
    def __init__(self,app_ref,**kw):
        super().__init__(**kw);self.app_ref=app_ref
        root=BoxLayout(orientation="vertical",spacing=dp(6),padding=dp(7));root.add_widget(Header("FLIGHT PLAN","Route, destination and top-of-descent planning",app_ref))
        form=Card(orientation="vertical",size_hint_y=None,height=dp(235))
        self.origin=TextInput(text=app_ref.plan.get("origin",""),multiline=False,hint_text="Origin ICAO e.g. HUEN",background_color=PANEL2,foreground_color=TEXT)
        self.dest=TextInput(text=app_ref.plan.get("dest",""),multiline=False,hint_text="Destination ICAO e.g. HKJK",background_color=PANEL2,foreground_color=TEXT)
        self.route=TextInput(text=app_ref.plan.get("route",""),multiline=False,hint_text="Waypoints: ICAO or lat,lon separated by spaces",background_color=PANEL2,foreground_color=TEXT)
        self.tod=TextInput(text=str(app_ref.plan.get("tod_alt",3000)),multiline=False,hint_text="TOD target altitude",background_color=PANEL2,foreground_color=TEXT)
        for w in (self.origin,self.dest,self.route,self.tod):form.add_widget(w)
        save=button("SAVE ROUTE AND SHOW ON MAP",True,44);save.bind(on_press=self.save);form.add_widget(save);root.add_widget(form)
        self.info=Label(text="Enter coordinates for custom waypoints. Major-airport coordinates are recognized automatically.",color=MUTED,size_hint_y=None,height=dp(45));root.add_widget(self.info)
        self.add_widget(root)
    def save(self,*_):
        self.app_ref.plan["origin"]=self.origin.text.strip().upper()
        self.app_ref.plan["dest"]=self.dest.text.strip().upper()
        self.app_ref.plan["route"]=self.route.text.strip()
        try:self.app_ref.plan["tod_alt"]=int(float(self.tod.text))
        except ValueError:self.app_ref.plan["tod_alt"]=3000
        points=[]
        for code in (self.app_ref.plan["origin"],)+tuple(self.app_ref.plan["route"].split())+(self.app_ref.plan["dest"],):
            if code in MAJOR_AIRPORTS:points.append(MAJOR_AIRPORTS[code][:2])
            elif "," in code:
                try:
                    a,b=code.split(",",1);points.append((float(a),float(b)))
                except ValueError:pass
        self.app_ref.plan["points"]=points
        self.info.text="%d route points loaded. Open MY FLIGHT to follow the aircraft."%len(points)
        self.app_ref.go("map")

class ScratchScreen(Screen):
    def __init__(self,app_ref,**kw):
        super().__init__(**kw);self.app_ref=app_ref
        root=BoxLayout(orientation="vertical",spacing=dp(6),padding=dp(7));root.add_widget(Header("SCRATCHPAD","Persistent cockpit notes",app_ref))
        self.note=TextInput(multiline=True,background_color=BG,foreground_color=TEXT,hint_text="Clearances, squawks, frequencies, gates, reminders…");root.add_widget(self.note)
        row=BoxLayout(size_hint_y=None,height=dp(48),spacing=dp(5));s=button("SAVE",True);s.bind(on_press=self.save);c=button("CLEAR");c.bind(on_press=self.clear);row.add_widget(s);row.add_widget(c);root.add_widget(row);self.add_widget(root)
        Clock.schedule_once(lambda *_:self.load(),0)
    def path(self):return os.path.join(self.app_ref.user_data_dir,"scratchpad.txt")
    def load(self):
        try:self.note.text=open(self.path(),encoding="utf-8").read()
        except OSError:pass
    def save(self,*_):
        try:
            tmp=self.path()+".tmp";open(tmp,"w",encoding="utf-8").write(self.note.text);os.replace(tmp,self.path())
        except OSError:pass
        self.app_ref.set_alert("Scratchpad saved.","info")
    def clear(self,*_):self.note.text="";self.save()

class ChecklistsScreen(Screen):
    AIRCRAFT=("A320","B738","B77W","B789","C172","DA40","E190","AT43")
    def __init__(self,app_ref,**kw):
        super().__init__(**kw);self.app_ref=app_ref
        root=BoxLayout(orientation="vertical",spacing=dp(6),padding=dp(7));root.add_widget(Header("CHECKLISTS","User-supplied licensed checklist assets",app_ref))
        self.selector=TextInput(text="A320",multiline=False,size_hint_y=None,height=dp(44),hint_text="Aircraft code",background_color=PANEL2,foreground_color=TEXT);root.add_widget(self.selector)
        self.info=TextInput(readonly=True,multiline=True,text="No checklist loaded.",background_color=BG,foreground_color=TEXT);root.add_widget(self.info)
        q=button("LOAD CHECKLIST",True,46);q.bind(on_press=self.load);root.add_widget(q);self.add_widget(root)
    def load(self,*_):
        code=self.selector.text.strip().lower();path=os.path.join("assets","checklists",code+".txt")
        try:self.info.text=open(path,encoding="utf-8").read()
        except OSError:self.info.text="No asset installed for %s.\nExpected: %s"%(code.upper(),path)

class SettingsScreen(Screen):
    def __init__(self,app_ref,**kw):
        super().__init__(**kw);self.app_ref=app_ref
        root=BoxLayout(orientation="vertical",spacing=dp(6),padding=dp(7));root.add_widget(Header("SETTINGS","Connection, Gemini and aviation map configuration"))
        s=ScrollView();box=BoxLayout(orientation="vertical",spacing=dp(7),padding=dp(4),size_hint_y=None);box.bind(minimum_height=box.setter("height"))
        box.add_widget(Label(text="AEROFLY / FSWIDGETS CONNECTION",color=ACCENT,font_size="16sp",bold=True,size_hint_y=None,height=dp(35)))
        self.host=TextInput(text=app_ref.telemetry.tcp_host,multiline=False,hint_text="Simulator IPv4 address",size_hint_y=None,height=dp(44),background_color=PANEL2,foreground_color=TEXT);box.add_widget(self.host)
        q=button("APPLY CONNECTION",True,44);q.bind(on_press=self.apply_connection);box.add_widget(q)
        box.add_widget(Label(text="TCP 58585 is the native FSWidgets client connection. The app sends the Aerofly HTTP-style wake-up request. UDP 40092 is kept as a broadcast receiver for the Aerofly/ForeFlight-style XGPS/XATT stream. Aerofly's official FSWidgets instructions use port 58585 and require Send flight data to FSWidgets Apps in Settings > Miscellaneous.",color=MUTED,size_hint_y=None,height=dp(90),halign="left"))
        box.add_widget(Label(text="GEMINI ATC",color=ACCENT,font_size="16sp",bold=True,size_hint_y=None,height=dp(35)))
        self.gkey=TextInput(text=app_ref.gemini_key,password=True,multiline=False,hint_text="Paste Gemini API key here",size_hint_y=None,height=dp(44),background_color=PANEL2,foreground_color=TEXT);box.add_widget(self.gkey)
        self.gmodel=TextInput(text=app_ref.gemini_model,multiline=False,size_hint_y=None,height=dp(44),background_color=PANEL2,foreground_color=TEXT);box.add_widget(self.gmodel)
        g=button("SAVE GEMINI",True,44);g.bind(on_press=self.save_gemini);box.add_widget(g)
        box.add_widget(Label(text="Gemini 3.6 Flash model ID: gemini-3.6-flash. The key is stored only in the app's private settings file and is never written to this Git repository.",color=MUTED,size_hint_y=None,height=dp(55)))
        box.add_widget(Label(text="OPENAIP AVIATION MAP",color=ACCENT,font_size="16sp",bold=True,size_hint_y=None,height=dp(35)))
        self.openaip=TextInput(text=app_ref.openaip_key,password=True,multiline=False,hint_text="Optional OpenAIP API key",size_hint_y=None,height=dp(44),background_color=PANEL2,foreground_color=TEXT);box.add_widget(self.openaip)
        o=button("SAVE MAP SETTINGS",True,44);o.bind(on_press=self.save_map);box.add_widget(o)
        box.add_widget(Label(text="With an OpenAIP key, the map can use aviation tiles containing aeronautical information. Without it, the moving map still uses OpenStreetMap and the live aircraft/track.",color=MUTED,size_hint_y=None,height=dp(55)))
        box.add_widget(Label(text="ALERTS",color=ACCENT,font_size="16sp",bold=True,size_hint_y=None,height=dp(35)))
        n=button("IN-APP FLIGHT ALERTS: ON",44);n.bind(on_press=lambda *_:app_ref.toggle_alerts(n));box.add_widget(n)
        s.add_widget(box);root.add_widget(s);self.add_widget(root)
    def apply_connection(self,*_):
        self.app_ref.telemetry.set_tcp_host(self.host.text.strip());self.app_ref.set_alert("FSWidgets connection target updated.","info")
    def save_gemini(self,*_):
        self.app_ref.gemini_key=self.gkey.text.strip();self.app_ref.gemini_model=self.gmodel.text.strip() or "gemini-3.6-flash";self.app_ref.save_settings();self.app_ref.gemini=GeminiATC(self.app_ref.gemini_key,self.app_ref.gemini_model);self.app_ref.set_alert("Gemini settings saved locally.","info")
    def save_map(self,*_):
        self.app_ref.openaip_key=self.openaip.text.strip();self.app_ref.save_settings();self.app_ref.set_alert("Map settings saved. Use AVIATION on the map.","info")

class DiagnosticsScreen(Screen):
    def __init__(self,app_ref,**kw):
        super().__init__(**kw);self.app_ref=app_ref
        root=BoxLayout(orientation="vertical",spacing=dp(6),padding=dp(7));root.add_widget(Header("CONNECTION DIAGNOSTICS","Raw transport health and parser state",app_ref))
        self.out=TextInput(readonly=True,multiline=True,background_color=BG,foreground_color=TEXT);root.add_widget(self.out)
        q=button("RESTART RECEIVERS",True,46);q.bind(on_press=self.restart);root.add_widget(q);self.add_widget(root)
    def refresh(self,d):
        self.out.text=(
            "SIM HOST: %s\n"
            "TCP 58585: %s\n"
            "UDP 40092: %s\n"
            "CONNECTED: %s\n"
            "TRANSPORT: %s\n"
            "SOURCE IP: %s\n"
            "PACKETS: %s\n"
            "SIM NAME: %s\n"
            "LAST ERROR: %s\n\n"
            "XGPS/XATT parser is active. TCP sends the FSWidgets wake-up request before reading the stream."
        )%(d.get("tcp_host"),d.get("tcp_connected"),d.get("udp_connected"),d.get("connected"),
           d.get("transport"),d.get("source_ip") or "—",d.get("packets"),d.get("sim_name") or "—",d.get("last_error") or "none")
    def restart(self,*_):
        self.app_ref.telemetry.stop();time.sleep(.1);self.app_ref.telemetry.start();self.app_ref.set_alert("Receivers restarted.","info")

class ProAeroflyApp(core.App):
    def build(self):
        self.settings_path=os.path.join(self.user_data_dir,"settings.json")
        self.load_settings()
        self.telemetry=Telemetry()
        self.copilot=Copilot()
        self.gemini=GeminiATC(self.gemini_key,self.gemini_model)
        self.com1="118.000";self.com2="121.500";self.alert_text="";self.alert_level="info";self.alerts_enabled=True
        self.plan={"origin":"","dest":"","route":"","tod_alt":3000,"points":[]}
        self.manager=ScreenManager(transition=FadeTransition(duration=.08))
        definitions=[
            ("home",HomeScreen),("flight",MyFlightScreen),("map",MapScreen),("comms",CommsScreen),
            ("frequencies",FrequenciesScreen),("flightplan",FlightPlanScreen),("scratch",ScratchScreen),
            ("checklists",ChecklistsScreen),("operations",OperationsScreen),("settings",SettingsScreen),("diagnostics",DiagnosticsScreen)]
        for name,cls in definitions:
            try:
                self.manager.add_widget(cls(self,name=name))
            except Exception as exc:
                self._write_startup_error(exc)
                fallback = Screen(name=name)
                fallback.add_widget(Label(text=name.upper()+"\nUNAVAILABLE\n\n"+repr(exc), color=AMBER))
                self.manager.add_widget(fallback)
        root=BoxLayout(orientation="vertical");root.add_widget(self.manager)
        nav=BoxLayout(size_hint_y=None,height=dp(56),spacing=dp(2),padding=dp(3))
        for name,label in (("home","HOME"),("flight","MY FLIGHT"),("map","MAP"),("comms","COMMS"),("frequencies","RADIO"),("more","MORE")):
            q=button(label, name=="flight", 48);q.bind(on_press=lambda _,n=name:self.go(n));nav.add_widget(q)
        root.add_widget(nav)
        Clock.schedule_once(lambda *_:self.telemetry.start(),.4)
        Clock.schedule_interval(self.tick,.5)
        return root
    def _write_startup_error(self, exc):
        try:
            path = os.path.join(self.user_data_dir, "startup_error.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n--- UI startup error ---\n"+repr(exc)+"\n")
        except Exception:
            pass

    def load_settings(self):
        self.gemini_key="";self.gemini_model="gemini-3.6-flash";self.openaip_key=""
        try:
            d=json.load(open(self.settings_path,encoding="utf-8"))
            self.gemini_key=d.get("gemini_api_key","");self.gemini_model=d.get("gemini_model","gemini-3.6-flash");self.openaip_key=d.get("openaip_api_key","")
        except (OSError,ValueError):pass
    def save_settings(self):
        os.makedirs(os.path.dirname(self.settings_path),exist_ok=True)
        tmp=self.settings_path+".tmp"
        json.dump({"gemini_api_key":self.gemini_key,"gemini_model":self.gemini_model,"openaip_api_key":self.openaip_key},open(tmp,"w",encoding="utf-8"))
        os.replace(tmp,self.settings_path)
    def go(self,name):
        if name=="more":name="diagnostics"
        self.manager.current=name
    def button(self,text,active=False,height=42):
        return button(text,active,height)
    def header(self,title,subtitle=""):
        return Header(title,subtitle,self)
    def enable_radar(self,url):
        try:
            return bool(self.screens.get("map") and self.screens["map"].map.set_radar_source(url))
        except Exception:
            return False
    def set_alert(self,text,level="info"):
        self.alert_text=text;self.alert_level=level
        if self.alerts_enabled and level in ("warning","danger"):
            try:
                from plyer import notification
                notification.notify(title="Aerofly ATC",message=text,timeout=5)
            except Exception:pass
        Clock.schedule_once(lambda *_:self.clear_alert(),8)
    def clear_alert(self):
        self.alert_text="";self.alert_level="info"
    def toggle_alerts(self,b):
        self.alerts_enabled=not self.alerts_enabled;b.text="IN-APP FLIGHT ALERTS: %s"%("ON" if self.alerts_enabled else "OFF")
    def tick(self,*_):
        try:
            d=self.telemetry.snapshot()
            self.logger.record(d)
            self.screens_refresh(d)
            event=self.copilot.monitor(d)
            if event and self.copilot.afk:self.screens["comms"].append("COPILOT",event)
            if d.get("connected"):
                tod=FlightOps.tod_nm(d.get("altitude",0),self.plan.get("tod_alt",3000),d.get("speed",0))
                if tod is not None and tod < 5 and not getattr(self,"tod_alerted",False):
                    self.tod_alerted=True;self.set_alert("Top of descent is within 5 NM.","warning")
                if tod is not None and tod > 8:self.tod_alerted=False
        except Exception as exc:
            try:self._write_crash_log(exc)
            except Exception:pass
    def screens_refresh(self,d):
        if not hasattr(self,"manager"):return
        self.screens={}
        for s in self.manager.screens:self.screens[s.name]=s
        if "flight" in self.screens:self.screens["flight"].refresh(d)
        if "map" in self.screens:self.screens["map"].refresh(d)
        if "diagnostics" in self.screens:self.screens["diagnostics"].refresh(d)
        if "operations" in self.screens:self.screens["operations"].refresh_alerts()
    def on_stop(self):
        try:self.telemetry.stop()
        except Exception:pass

class HomeScreen(Screen):
    def __init__(self,app_ref,**kw):
        super().__init__(**kw);root=BoxLayout(orientation="vertical",spacing=dp(7),padding=dp(8));root.add_widget(Header("AEROFLY ATC","Professional mobile companion",app_ref))
        card=Card(orientation="vertical",size_hint_y=None,height=dp(105));card.add_widget(Label(text="FLIGHT COMPANION",color=ACCENT,font_size="23sp",bold=True));card.add_widget(Label(text="Native Aerofly FSWidgets telemetry • professional moving map • ATC • flight operations",color=MUTED));root.add_widget(card)
        s=ScrollView();b=BoxLayout(orientation="vertical",spacing=dp(5),padding=dp(2),size_hint_y=None);b.bind(minimum_height=b.setter("height"))
        for label,name in (("MY FLIGHT","flight"),("LIVE MAP","map"),("ATC COMMS","comms"),("FREQUENCIES","frequencies"),("FLIGHT PLAN","flightplan"),("SCRATCHPAD","scratch"),("CHECKLISTS","checklists"),("CONNECTION DIAGNOSTICS","diagnostics"),("SETTINGS","settings")):
            q=button(label,height=48);q.bind(on_press=lambda _,n=name:app_ref.go(n));b.add_widget(q)
        s.add_widget(b);root.add_widget(s);self.add_widget(root)

# Export the UI entry point used by main.py.
