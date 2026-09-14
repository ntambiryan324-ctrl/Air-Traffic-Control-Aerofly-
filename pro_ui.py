import json
import math
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request

from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle
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

class AircraftMarker(MapMarker):
    def __init__(self, **kw):
        super().__init__(source=os.path.join(os.path.dirname(__file__), "assets", "aircraft.svg"),
                         size=(dp(34), dp(34)), anchor_x=.5, anchor_y=.5, **kw)

class FlightPathLayer(MapLayer):
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
                Color(*MUTED)
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
        self.map = None
        self.marker = None
        self.actual_layer = None
        self.planned_layer = None
        if MAPVIEW_AVAILABLE:
            try:
                self._build_mapview()
            except Exception as exc:
                self.app_ref.map_error = repr(exc)
                self._build_safe_map()
        else:
            self._build_safe_map()
    def _build_safe_map(self):
        self.map = SafeMovingMap()
        self.add_widget(self.map)
    def _build_mapview(self):
        self.marker = AircraftMarker(lat=0, lon=0)
        self.map = MapView(zoom=5, lat=0, lon=0, double_tap_zoom=True, pause_on_action=True)
        self.map.map_source = MapSource(url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                                        cache_key="osm-live", min_zoom=1, max_zoom=19, tile_size=256,
                                        attribution="© OpenStreetMap contributors", subdomains="abc")
        self.map.add_marker(self.marker)
        self.actual_layer = FlightPathLayer(self.map, [], color=ACCENT, width=2.2)
        self.planned_layer = FlightPathLayer(self.map, [], color=AMBER, width=1.6)
        self.map.add_layer(self.actual_layer, mode="scatter")
        self.map.add_layer(self.planned_layer, mode="scatter")
        self.add_widget(self.map)
    def aviation_source(self):
        if not MAPVIEW_AVAILABLE or self.map is None or not hasattr(self.map, "map_source"):
            return None
        key = self.app_ref.openaip_key.strip()
        if not key:
            return None
        return MapSource(url="https://{s}.api.tiles.openaip.net/api/data/openaip/{z}/{x}/{y}.png?apiKey=" + urllib.parse.quote(key),
                         cache_key="openaip-" + key[-8:], min_zoom=8, max_zoom=16, tile_size=256,
                         attribution="openAIP aviation data", subdomains="abc")
    def set_chart(self):
        src = self.aviation_source()
        if src is None:
            self.app_ref.set_alert("Aviation chart unavailable. Configure MapView/OpenAIP in Settings.", "warning")
            return
        self.chart = True
        self.map.map_source = src
        self.map.zoom = max(8, self.map.zoom)
    def set_base(self):
        if not MAPVIEW_AVAILABLE or not hasattr(self.map, "map_source"):
            return
        self.chart = False
        self.map.map_source = MapSource(url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                                        cache_key="osm-live", min_zoom=1, max_zoom=19, tile_size=256,
                                        attribution="© OpenStreetMap contributors", subdomains="abc")
    def refresh(self, d, trail):
        if MAPVIEW_AVAILABLE and self.marker is not None:
            if d.get("connected"):
                lat, lon = float(d["lat"]), float(d["lon"])
                self.marker.lat, self.marker.lon = lat, lon
                if self.follow:
                    self.map.center_on(lat, lon)
                if self.map.zoom < 8 and abs(lat) + abs(lon) > 0.01:
                    self.map.zoom = 8
            self.actual_layer.set_points(trail[-250:])
            self.planned_layer.set_points(self.app_ref.plan.get("points", []))
        else:
            self.map.update(d, trail, self.app_ref.plan.get("points", []))
    def center(self):
        d = self.app_ref.telemetry.snapshot()
        if d.get("connected"):
            self.follow = True
            if MAPVIEW_AVAILABLE and self.marker is not None:
                self.map.center_on(float(d["lat"]), float(d["lon"]))


