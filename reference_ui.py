"""FlyCharts-reference visual shell for AeroflyATC.

Keeps live OSM/telemetry rendering from main.py and uses planner_core/advanced_features
for real calculations and optional AIRAC/SimBrief lookups. Missing navigation data is
shown as missing, never synthesized as airway/procedure data.
"""
import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import webbrowser

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import (
    Color, Ellipse, Line, Rectangle, RoundedRectangle,
    StencilPush, StencilUse, StencilUnUse, StencilPop
)
from kivy.metrics import dp
from kivy.utils import platform
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

import advanced_features as adv
import planner_core as pc


BG = (0.075, 0.078, 0.083, 1)
PANEL = (0.085, 0.088, 0.095, 0.96)
PANEL2 = (0.125, 0.128, 0.137, 1)
PANEL3 = (0.165, 0.168, 0.178, 1)
BLUE = (0.06, 0.48, 0.96, 1)
BLUE_SOFT = (0.22, 0.58, 0.96, 1)
TEXT = (0.94, 0.95, 0.97, 1)
MUTED = (0.62, 0.64, 0.69, 1)
DIM = (0.34, 0.36, 0.42, 1)
GREEN = (0.20, 0.86, 0.52, 1)
AMBER = (1.0, 0.69, 0.22, 1)
VIOLET = (0.58, 0.36, 0.72, 0.78)


def label(text, size=12, color=TEXT, bold=False, **kw):
    return Label(text=str(text), color=color, font_size="%ssp" % size,
                 bold=bold, **kw)


class RoundButton(Button):
    def __init__(self, text="", active=False, **kw):
        self.active = active
        kw.setdefault("background_normal", "")
        kw.setdefault("background_down", "")
        kw.setdefault("background_color", (0, 0, 0, 0))
        kw.setdefault("color", BLUE_SOFT if active else TEXT)
        kw.setdefault("font_size", "13sp")
        super().__init__(text=text, **kw)
        with self.canvas.before:
            Color(*(BLUE if active else PANEL2))
            self._shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(28)])
            Color(0.55, 0.60, 0.70, 0.25)
            self._edge = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(28)), width=0.7)
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self._shape.pos, self._shape.size = self.pos, self.size
        self._edge.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(28))


class Card(BoxLayout):
    def __init__(self, **kw):
        kw.setdefault("padding", dp(12))
        kw.setdefault("spacing", dp(8))
        super().__init__(**kw)
        with self.canvas.before:
            Color(*PANEL)
            self._shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(18)])
            Color(0.24, 0.25, 0.28, 0.55)
            self._edge = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(18)), width=0.7)
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self._shape.pos, self._shape.size = self.pos, self.size
        self._edge.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(18))


class GlobeViewport(FloatLayout):
    """Circularly clips the real OSM tile widget and chart overlay to make a globe viewport."""
    def __init__(self, map_widget, overlay, **kw):
        super().__init__(**kw)
        self.map_widget = map_widget
        self.overlay = overlay
        with self.canvas.before:
            StencilPush()
            Color(1, 1, 1, 1)
            self._mask = Ellipse(pos=(0, 0), size=(1, 1))
            StencilUse()
        self.add_widget(map_widget)
        self.add_widget(overlay)
        with self.canvas.after:
            StencilUnUse()
            StencilPop()
            Color(0.12, 0.25, 0.36, 0.52)
            self._glow = Line(circle=(0, 0, 1), width=dp(8))
            Color(0.52, 0.68, 0.82, 0.82)
            self._rim = Line(circle=(0, 0, 1), width=dp(1.2))

    def fit_globe(self, screen_size):
        w, h = screen_size
        diameter = min(w * 1.58, h * 1.08)
        cx, cy = w * 0.50, h * 0.585
        pos = (cx - diameter * 0.5, cy - diameter * 0.5)
        size = (diameter, diameter)
        self._mask.pos, self._mask.size = pos, size
        self.map_widget.pos, self.map_widget.size = pos, size
        self.overlay.pos, self.overlay.size = pos, size
        self._glow.circle = (cx, cy, diameter * 0.5)
        self._rim.circle = (cx, cy, diameter * 0.5)


class ChartOverlay(Widget):
    """Dark chart treatment, graticule, known airport labels and verified generated route."""
    def __init__(self, map_widget, **kw):
        super().__init__(**kw)
        self.map_widget = map_widget
        self.airports = {}
        self.route_points = []
        self.airport_labels = []
        self._load_airports()
        self.bind(pos=self.redraw, size=self.redraw)
        Clock.schedule_interval(self.redraw, 2.0)

    def _load_airports(self):
        self.airports = {}
        for code, value in getattr(pc, "AIRPORT_DB", {}).items():
            try:
                self.airports[code] = (float(value[0]), float(value[1]), str(value[2]))
            except Exception:
                pass
        for code, value in getattr(adv, "KNOWN_AIRPORTS", {}).items():
            try:
                self.airports[code] = (float(value[0]), float(value[1]), str(value[2]))
            except Exception:
                pass

    def set_route(self, points):
        self.route_points = list(points or [])
        self.redraw()

    def project(self, lat, lon):
        m = self.map_widget
        cx, cy = m.world(m.center_lat, m.center_lon)
        px, py = m.world(lat, lon)
        n = 2 ** m.zoom
        dx = (px - cx + n / 2) % n - n / 2
        return m.center_x + dx * dp(256), m.center_y + (cy - py) * dp(256)

    def redraw(self, *_):
        self.canvas.clear()
        self.clear_widgets()
        m = self.map_widget
        if self.width < 10 or self.height < 10:
            return
        with self.canvas:
            # The real basemap remains underneath this dark aviation-chart veil.
            Color(0.015, 0.022, 0.038, 0.66)
            Rectangle(pos=self.pos, size=self.size)
            Color(0.42, 0.49, 0.64, 0.24)
            for lat in range(-60, 81, 30):
                pts = []
                for lon in range(-180, 181, 6):
                    x, y = self.project(lat, lon)
                    pts.extend((x, y))
                if len(pts) > 3:
                    Line(points=pts, width=0.5)
            for lon in range(-180, 181, 30):
                pts = []
                for lat in range(-75, 81, 4):
                    x, y = self.project(lat, lon)
                    pts.extend((x, y))
                if len(pts) > 3:
                    Line(points=pts, width=0.5)

            # FIR boundaries are not fabricated. The violet tone is reserved for
            # real boundary data if/when the licensed/public airspace layer is loaded.
            if len(self.route_points) > 1:
                pts = []
                for p in self.route_points:
                    try:
                        x, y = self.project(float(p[0]), float(p[1]))
                        pts.extend((x, y))
                    except Exception:
                        pass
                if len(pts) >= 4:
                    Color(0.05, 0.49, 1.0, 0.18)
                    Line(points=pts, width=dp(8))
                    Color(0.12, 0.61, 1.0, 0.98)
                    Line(points=pts, width=dp(2.2))
                    for i in range(0, len(pts), 2):
                        Color(0.25, 0.70, 1.0, 1)
                        Ellipse(pos=(pts[i] - dp(3), pts[i + 1] - dp(3)), size=(dp(6), dp(6)))

            # Show real airports from the repo's verified coordinate fallback list.
            for code, (lat, lon, name) in self.airports.items():
                x, y = self.project(lat, lon)
                if not (self.x - dp(12) <= x <= self.right + dp(12) and self.y - dp(10) <= y <= self.top + dp(10)):
                    continue
                Color(0.19, 0.55, 0.92, 0.95)
                Ellipse(pos=(x - dp(1.8), y - dp(1.8)), size=(dp(3.6), dp(3.6)))
                lab = Label(text=code, color=(0.22, 0.56, 0.95, 0.96),
                            font_size="8sp", bold=True, size_hint=(None, None),
                            size=(dp(42), dp(14)), pos=(x - dp(21), y + dp(2)))
                self.add_widget(lab)


class MiniPanel(Card):
    def __init__(self, **kw):
        kw.setdefault("orientation", "vertical")
        super().__init__(**kw)


class FlightPlanOverlay(FloatLayout):
    def __init__(self, ui, **kw):
        super().__init__(**kw)
        self.ui = ui
        self.generated = False
        self.active_tab = "Info"
        self.plan = {}
        self.route_points = []
        self.route_text = ""
        self.cruise_fl = 400
        self.mach_mode = True
        self.speed_value = 0.84
        self.payload_pct = 85
        self.selected_sid = "Auto"
        self.selected_star = "Auto"
        self.selected_approach = "Auto"
        self.alternate = ""
        self.simbrief_username = ""
        with self.canvas.before:
            Color(0.075, 0.078, 0.083, 1)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_bg, size=self._sync_bg)
        self.airport_map = dict(pc.AIRPORT_DB)
        for code, value in getattr(adv, "KNOWN_AIRPORTS", {}).items():
            self.airport_map[code] = value
        self.airport_values = ["%s · %s" % (k, v[2]) for k, v in sorted(self.airport_map.items())]
        self._build()

    def _sync_bg(self, *_):
        self._bg.pos, self._bg.size = self.pos, self.size

    def _btn(self, text, active=False, height=40, **kw):
        return RoundButton(text=text, active=active, size_hint_y=None, height=dp(height), **kw)

    def _build(self):
        root = BoxLayout(orientation="vertical", padding=(dp(15), dp(8)), spacing=dp(8))
        head = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        title_box = BoxLayout(orientation="vertical", spacing=dp(0))
        title_box.add_widget(label("⌘  Flight plan", 19, TEXT, True, halign="left", valign="middle"))
        title_box.add_widget(label("ROUTE  /  PERFORMANCE  /  DISPATCH", 8, MUTED, halign="left"))
        head.add_widget(title_box)
        close = self._btn("×", False, 42, size_hint_x=None, width=dp(46))
        close.bind(on_release=lambda *_: self.ui.close_planner())
        head.add_widget(close)
        root.add_widget(head)

        self.body_scroll = ScrollView(do_scroll_x=False, bar_width=dp(3))
        self.body = BoxLayout(orientation="vertical", spacing=dp(12), padding=(0, dp(6)),
                              size_hint_y=None)
        self.body.bind(minimum_height=self.body.setter("height"))
        self.body_scroll.add_widget(self.body)
        root.add_widget(self.body_scroll)

        self.bottom = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8), padding=(0, dp(2)))
        self.status = label("Choose departure and arrival airports to start.", 9, MUTED,
                            halign="left", valign="middle")
        self.bottom.add_widget(self.status)
        self.reset_button = self._btn("Reset", False, 42, size_hint_x=None, width=dp(82))
        self.generate_button = self._btn("⌁  Generate", True, 42, size_hint_x=None, width=dp(130))
        self.reset_button.bind(on_release=self.reset)
        self.generate_button.bind(on_release=self.generate)
        self.bottom.add_widget(self.reset_button)
        self.bottom.add_widget(self.generate_button)
        root.add_widget(self.bottom)
        self.add_widget(root)
        self._build_form()

    def _section(self, title, content, expanded=True):
        shell = Card(orientation="vertical", padding=dp(10), spacing=dp(8),
                     size_hint_y=None)
        heading = self._btn("⌄  " + title, False, 34)
        shell.add_widget(heading)
        content.size_hint_y = None
        shell.add_widget(content)
        content.opacity = 1 if expanded else 0
        original = content.height
        if not expanded:
            content.height = 0
        shell.height = dp(54) + (original if expanded else 0)
        def toggle(*_):
            if content.height:
                content.height = 0
                content.opacity = 0
                heading.text = "›  " + title
                shell.height = dp(54)
            else:
                content.height = original
                content.opacity = 1
                heading.text = "⌄  " + title
                shell.height = dp(54) + original
        heading.bind(on_release=toggle)
        return shell

    def _row(self, name, control, height=42):
        row = BoxLayout(size_hint_y=None, height=dp(height), spacing=dp(8))
        row.add_widget(label(name, 10, MUTED, size_hint_x=None, width=dp(86),
                             halign="left", valign="middle"))
        control.size_hint_x = 1
        row.add_widget(control)
        return row

    def _spinner(self, values, hint="Select", width=None):
        s = Spinner(text=hint, values=tuple(values), size_hint_y=None, height=dp(40),
                    background_normal="", background_down="", background_color=PANEL2,
                    color=TEXT, font_size="12sp", option_cls="SpinnerOption")
        if width:
            s.size_hint_x = None
            s.width = dp(width)
        return s

    def _build_form(self):
        self.body.clear_widgets()
        self.generated = False
        self.bottom.clear_widgets()
        self.status = label("Choose departure and arrival airports to start.", 9, MUTED,
                            halign="left", valign="middle")
        self.bottom.add_widget(self.status)

        airports = BoxLayout(orientation="vertical", spacing=dp(7), size_hint_y=None, height=dp(164))
        self.origin = self._spinner(self.airport_values, "Select an airport")
        self.destination = self._spinner(self.airport_values, "Select an airport")
        self.aircraft = self._spinner(
            ["Airbus A350-1000 XWB (A35K)", "Airbus A350-900 (A359)", "Airbus A320neo (A320)",
             "Boeing 737-800 (B738)", "Boeing 777-300ER (B77W)", "Boeing 787-9 (B789)",
             "Airbus A380-800 (A388)", "Cessna 172 (C172)", "Bombardier Dash 8 Q400 (DH8D)"],
            "Airbus A350-1000 XWB (A35K)")
        self.aircraft.text = "Airbus A350-1000 XWB (A35K)"
        self.aircraft.bind(text=self._configure_speed_for_aircraft)
        airports.add_widget(self._row("Departure", self.origin))
        airports.add_widget(self._row("Arrival", self.destination))
        airports.add_widget(self._row("Aircraft", self.aircraft))
        self.body.add_widget(airports)

        dep = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None, height=dp(114))
        self.sid_enabled = CheckBox(active=True, size_hint_x=None, width=dp(28))
        self.sid_auto = self._spinner(["Auto", "Select procedure"], "Auto")
        self.sid_auto.size_hint_x = 0.60
        load_sid = self._btn("Load SID", False, 36, size_hint_x=None, width=dp(86))
        load_sid.bind(on_release=lambda *_: self.load_procedures("SID"))
        r1 = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        r1.add_widget(self.sid_enabled)
        r1.add_widget(label("SID", 10, TEXT, size_hint_x=None, width=dp(34)))
        r1.add_widget(self.sid_auto)
        r1.add_widget(load_sid)
        self.dep_runway = self._spinner(["AUTO / unresolved locally"], "Select runway")
        dep.add_widget(r1)
        dep.add_widget(self._row("From runway", self.dep_runway))
        self.body.add_widget(self._section("Departure options", dep))

        arr = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None, height=dp(162))
        self.star_enabled = CheckBox(active=True, size_hint_x=None, width=dp(28))
        self.star_auto = self._spinner(["Auto", "Select procedure"], "Auto")
        self.star_auto.size_hint_x = 0.60
        load_star = self._btn("Load STAR", False, 36, size_hint_x=None, width=dp(86))
        load_star.bind(on_release=lambda *_: self.load_procedures("STAR"))
        r2 = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        r2.add_widget(self.star_enabled)
        r2.add_widget(label("STAR", 10, TEXT, size_hint_x=None, width=dp(42)))
        r2.add_widget(self.star_auto)
        r2.add_widget(load_star)
        self.arr_runway = self._spinner(["AUTO / unresolved locally"], "Select runway")
        self.approach_auto = self._spinner(["Auto", "Select procedure"], "Auto")
        load_app = self._btn("Load", False, 36, size_hint_x=None, width=dp(68))
        load_app.bind(on_release=lambda *_: self.load_procedures("APP"))
        r3 = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        r3.add_widget(label("Approach", 10, MUTED, size_hint_x=None, width=dp(72)))
        r3.add_widget(self.approach_auto)
        r3.add_widget(load_app)
        arr.add_widget(r2)
        arr.add_widget(self._row("To runway", self.arr_runway))
        arr.add_widget(r3)
        self.body.add_widget(self._section("Arrival options", arr))

        perf = BoxLayout(orientation="vertical", spacing=dp(7), size_hint_y=None, height=dp(174))
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(12))
        cl = BoxLayout(orientation="vertical", spacing=dp(2))
        cl.add_widget(label("Cruise level", 10, TEXT, True, halign="left"))
        cr = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(3))
        bminus = self._btn("−", False, 32, size_hint_x=None, width=dp(38))
        self.fl_label = label("FL 400", 14, TEXT, True)
        bplus = self._btn("+", False, 32, size_hint_x=None, width=dp(38))
        bminus.bind(on_release=lambda *_: self.set_fl(-10))
        bplus.bind(on_release=lambda *_: self.set_fl(10))
        cr.add_widget(bminus); cr.add_widget(self.fl_label); cr.add_widget(bplus)
        cl.add_widget(cr); row.add_widget(cl)
        sp = BoxLayout(orientation="vertical", spacing=dp(2))
        unitrow = BoxLayout(size_hint_y=None, height=dp(18))
        unitrow.add_widget(label("Airspeed", 10, TEXT, True, halign="left"))
        self.speed_unit = self._btn("Mach", False, 22, size_hint_x=None, width=dp(60))
        self.speed_unit.bind(on_release=self.toggle_speed_unit)
        unitrow.add_widget(self.speed_unit)
        sp.add_widget(unitrow)
        sr = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(3))
        sbminus = self._btn("−", False, 32, size_hint_x=None, width=dp(38))
        self.speed_label = label("M 0.84", 13, TEXT, True)
        sbplus = self._btn("+", False, 32, size_hint_x=None, width=dp(38))
        sbminus.bind(on_release=lambda *_: self.adjust_speed(-1))
        sbplus.bind(on_release=lambda *_: self.adjust_speed(1))
        sr.add_widget(sbminus); sr.add_widget(self.speed_label); sr.add_widget(sbplus)
        sp.add_widget(sr); row.add_widget(sp); perf.add_widget(row)
        self.perf_caption = label("Altitude 12,192 m     True airspeed varies with conditions", 9, MUTED,
                                  halign="left")
        perf.add_widget(self.perf_caption)
        pr = BoxLayout(size_hint_y=None, height=dp(26))
        pr.add_widget(label("Payload", 10, TEXT, True, halign="left"))
        self.payload_label = label("85%", 10, MUTED, halign="right")
        pr.add_widget(self.payload_label); perf.add_widget(pr)
        self.payload = Slider(min=0, max=100, value=85, step=1, cursor_size=(dp(18), dp(18)))
        self.payload.bind(value=self.set_payload)
        perf.add_widget(self.payload)
        self.weight_hint = label("Performance values are simulator estimates, not dispatch certification.", 8, MUTED,
                                 halign="left", valign="top")
        perf.add_widget(self.weight_hint)
        self.body.add_widget(self._section("Aircraft performance", perf))

        route = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None, height=dp(130))
        self.route_mode = self._spinner(["Direct", "Auto route (AIRAC service)", "Custom route"], "Auto route (AIRAC service)")
        route.add_widget(self._row("Mode", self.route_mode))
        self.route_input = TextInput(text="", hint_text="Optional fixes / airway route",
                                     multiline=False, size_hint_y=None, height=dp(42),
                                     background_normal="", background_active="",
                                     background_color=PANEL2, foreground_color=TEXT,
                                     hint_text_color=MUTED, cursor_color=BLUE,
                                     padding=(dp(10), dp(10)))
        route.add_widget(self._row("Route", self.route_input))
        self.body.add_widget(self._section("Routing options", route))

        self.fl_label.text = "FL %03d" % self.cruise_fl
        self._update_speed_label()
        self._sync_payload()
        self._install_bottom_actions(self.reset, self.generate)

    def _install_bottom_actions(self, reset_fn, generate_fn):
        self.bottom.clear_widgets()
        self.status = label("Route generation uses known airport coordinates; airway data is queried when available.", 8, MUTED,
                            halign="left", valign="middle")
        self.bottom.add_widget(self.status)
        self.reset_button = self._btn("Reset", False, 42, size_hint_x=None, width=dp(82))
        self.generate_button = self._btn("⌁  Generate", True, 42, size_hint_x=None, width=dp(130))
        self.reset_button.bind(on_release=lambda *_: reset_fn())
        self.generate_button.bind(on_release=lambda *_: generate_fn())
        self.bottom.add_widget(self.reset_button)
        self.bottom.add_widget(self.generate_button)

    def set_fl(self, delta):
        self.cruise_fl = max(60, min(500, self.cruise_fl + delta))
        self.fl_label.text = "FL %03d" % self.cruise_fl

    def toggle_speed_unit(self, *_):
        self.mach_mode = not self.mach_mode
        self.speed_unit.text = "Mach" if self.mach_mode else "TAS"
        self.speed_value = 0.84 if self.mach_mode else 480
        self._update_speed_label()

    def adjust_speed(self, delta):
        if self.mach_mode:
            self.speed_value = round(max(0.50, min(0.95, self.speed_value + 0.01 * delta)), 2)
        else:
            self.speed_value = max(100, min(650, self.speed_value + 5 * delta))
        self._update_speed_label()
        if self.generated:
            self.recalculate()

    def _configure_speed_for_aircraft(self, value):
        code = pc.resolve_aircraft(value)
        if code in ("C172", "BE58", "DH8D"):
            self.mach_mode = False
            self.speed_value = float(pc.AIRCRAFT[code][0])
        else:
            self.mach_mode = True
            self.speed_value = 0.84
        if hasattr(self, "speed_unit"):
            self.speed_unit.text = "Mach" if self.mach_mode else "TAS"
        if hasattr(self, "speed_label"):
            self._update_speed_label()

    def _effective_tas(self):
        if not self.mach_mode:
            return float(self.speed_value)
        # Standard-atmosphere speed of sound, capped at the tropopause.
        altitude_m = min(11000.0, max(0.0, float(self.cruise_fl) * 100.0 * 0.3048))
        temperature_k = 288.15 - 0.0065 * altitude_m
        speed_of_sound_kt = math.sqrt(1.4 * 287.05287 * temperature_k) * 1.943844492
        return max(40.0, min(700.0, float(self.speed_value) * speed_of_sound_kt))

    def _update_speed_label(self):
        self.speed_label.text = ("M %.2f" % self.speed_value) if self.mach_mode else ("%d kt" % self.speed_value)

    def set_payload(self, *_):
        self.payload_pct = int(self.payload.value)
        self._sync_payload()

    def _sync_payload(self):
        if hasattr(self, "payload_label"):
            self.payload_label.text = "%d%%" % int(self.payload.value)

    def _airport_code(self, value):
        if not value or value == "Select an airport":
            return ""
        return value.split(" · ", 1)[0].strip().upper()

    def _airport(self, code):
        row = pc.lookup_airport(code)
        if row:
            return row
        value = self.airport_map.get(code)
        if value:
            return {"icao": code, "lat": float(value[0]), "lon": float(value[1]), "name": str(value[2])}
        return None

    def load_procedures(self, typ):
        code = self._airport_code(self.origin.text if typ == "SID" else self.destination.text)
        if not code:
            self.status.text = "Select the relevant airport first."
            return
        self.status.text = "Querying published procedure data..."
        def work():
            try:
                data, cycle = adv.airport_procedures(code, typ)
                vals = []
                if isinstance(data, dict):
                    for key in ("procedures", "items", "data", typ.lower(), typ.lower() + "s"):
                        v = data.get(key)
                        if isinstance(v, list):
                            vals.extend(v)
                    if not vals:
                        vals = [data]
                elif isinstance(data, list):
                    vals = data
                names = []
                for x in vals:
                    if isinstance(x, str):
                        names.append(x)
                    elif isinstance(x, dict):
                        n = x.get("identifier") or x.get("name") or x.get("procedure") or x.get("id")
                        if n:
                            names.append(str(n))
                names = sorted(set(names))
                Clock.schedule_once(lambda *_: self._apply_procedures(typ, names, cycle), 0)
            except Exception as exc:
                Clock.schedule_once(lambda *_: self._procedure_error(typ, str(exc)), 0)
        threading.Thread(target=work, daemon=True).start()

    def _apply_procedures(self, typ, names, cycle):
        sp = {"SID": self.sid_auto, "STAR": self.star_auto, "APP": self.approach_auto}[typ]
        sp.values = tuple(["Auto"] + names) if names else ("Auto", "No procedure data returned")
        sp.text = "Auto"
        self.status.text = ("AIRAC %s • %d procedures loaded" % (cycle or "unknown", len(names))
                            if names else "No published %s list returned for %s." %
                            (typ, self._airport_code(self.origin.text if typ == "SID" else self.destination.text)))

    def _procedure_error(self, typ, message):
        self.status.text = "%s data lookup failed: %s" % (typ, message[:90])

    def reset(self, *_):
        self.origin.text = "Select an airport"
        self.destination.text = "Select an airport"
        self.aircraft.text = "Airbus A350-1000 XWB (A35K)"
        self.route_input.text = ""
        self.route_mode.text = "Auto route (AIRAC service)"
        self.cruise_fl = 400
        self.fl_label.text = "FL 400"
        self.payload.value = 85
        self._build_form()

    def generate(self, *_):
        orig = self._airport_code(self.origin.text)
        dest = self._airport_code(self.destination.text)
        o, d = self._airport(orig), self._airport(dest)
        if not o or not d:
            self.status.text = "Select two airports with known coordinates first."
            self.status.color = AMBER
            return
        route = self.route_input.text.strip().upper()
        codes = [orig]
        points = [(o["lat"], o["lon"])]
        for token in route.replace(",", " ").split():
            code = token.strip().upper()
            if code in ("DCT", "DIRECT", "AIRWAY", "AUTO"):
                continue
            a = self._airport(code)
            if a and code not in codes:
                codes.append(code)
                points.append((a["lat"], a["lon"]))
        if dest not in codes:
            codes.append(dest)
            points.append((d["lat"], d["lon"]))
        aircraft_text = self.aircraft.text
        aircraft_code = pc.resolve_aircraft(aircraft_text)
        self.plan = pc.plan_flight(points, aircraft_code, self.cruise_fl,
                                   speed_override_kt=self._effective_tas())
        self.route_points = list(points)
        self.plan.update({
            "origin": orig, "destination": dest, "origin_name": o["name"], "destination_name": d["name"],
            "route": route or "%s DCT %s" % (orig, dest), "codes": codes,
            "points": points, "aircraft_name": aircraft_text, "payload_pct": self.payload_pct,
            "sid": self.sid_auto.text if self.sid_enabled.active else "None",
            "star": self.star_auto.text if self.star_enabled.active else "None",
            "approach": self.approach_auto.text, "alternate": self.alternate,
            "departure_runway": self.dep_runway.text, "arrival_runway": self.arr_runway.text,
            "nav_cycle": None, "routing_source": "direct/entered route"
        })
        self.route_text = self.plan["route"]
        self.generated = True
        self.active_tab = "Info"
        self.ui.overlay.set_route(points)
        self._build_results()
        self.status.text = "ROUTE GENERATED • %.1f NM" % self.plan.get("distance_nm", 0)
        self.status.color = GREEN
        # Try the actual cycle-aware service in the background only when auto routing is selected.
        if self.route_mode.text.startswith("Auto route") and not route:
            threading.Thread(target=self._request_auto_route, args=(orig, dest), daemon=True).start()

    def _request_auto_route(self, orig, dest):
        try:
            data, cycle = adv.parse_route(orig, dest, "")
            route = ""
            if isinstance(data, dict):
                route = data.get("route") or data.get("route_string") or data.get("route_text") or ""
                if not route and isinstance(data.get("fixes"), list):
                    route = " ".join(str(x.get("identifier") or x.get("id") or x)
                                     if isinstance(x, dict) else str(x) for x in data["fixes"])
            if route:
                Clock.schedule_once(lambda *_: self._apply_auto_route(route, cycle), 0)
            else:
                Clock.schedule_once(lambda *_: self._route_source_note(cycle), 0)
        except Exception as exc:
            Clock.schedule_once(lambda *_: self._route_source_note(None, str(exc)), 0)

    def _apply_auto_route(self, route, cycle):
        if not self.generated:
            return
        self.plan["route"] = str(route).strip()
        self.route_text = self.plan["route"]
        self.plan["nav_cycle"] = cycle
        self.plan["routing_source"] = "AIRAC service"
        self._build_results()
        self.status.text = "AIRAC %s • ROUTE UPDATED" % (cycle or "cycle not reported")
        self.status.color = GREEN

    def _route_source_note(self, cycle, error=""):
        if not self.generated:
            return
        if error:
            self.status.text = "AIRAC auto-route unavailable; direct route retained."
        else:
            self.status.text = "Direct route retained; no airway route returned%s." % (
                (" (AIRAC %s)" % cycle) if cycle else ""
            )
        self.status.color = MUTED

    def _build_results(self):
        self.body.clear_widgets()
        tabs = GridLayout(cols=5, size_hint_y=None, height=dp(42), spacing=dp(4))
        for t in ("Info", "Table", "Load", "Profile", "Export"):
            b = self._btn(t, t == self.active_tab, 38)
            b.bind(on_release=lambda _, tab=t: self.show_tab(tab))
            tabs.add_widget(b)
        self.body.add_widget(tabs)
        if self.active_tab == "Info":
            self._info_tab()
        elif self.active_tab == "Table":
            self._table_tab()
        elif self.active_tab == "Load":
            self._load_tab()
        elif self.active_tab == "Profile":
            self._profile_tab()
        else:
            self._export_tab()
        self._install_bottom_actions(self.back_to_form, self.recalculate)

    def show_tab(self, tab):
        self.active_tab = tab
        self._build_results()

    def _info_tab(self):
        p = self.plan
        summary = Card(orientation="vertical", size_hint_y=None, height=dp(252), spacing=dp(8))
        top = BoxLayout(size_hint_y=None, height=dp(50))
        left = BoxLayout(orientation="vertical")
        left.add_widget(label("%s  →  %s" % (p["origin"], p["destination"]), 18, TEXT, True, halign="left"))
        left.add_widget(label("From %s\nTo %s" % (p["origin_name"], p["destination_name"]), 10, MUTED, halign="left"))
        top.add_widget(left)
        right = BoxLayout(orientation="vertical", size_hint_x=None, width=dp(104))
        right.add_widget(label("✈ %.0f nm" % p.get("distance_nm", 0), 11, TEXT, True, halign="right"))
        right.add_widget(label("◷ %s" % self._duration(p.get("ete_min", 0)), 10, MUTED, halign="right"))
        top.add_widget(right); summary.add_widget(top)
        summary.add_widget(label("Aircraft", 10, TEXT, True, halign="left"))
        ac = self._spinner(self.aircraft.values, self.aircraft.text)
        ac.text = self.aircraft.text
        ac.bind(text=lambda _, v: self._change_aircraft(v))
        summary.add_widget(ac)
        steps = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(10))
        steps.add_widget(self._stepper("Cruise level", "FL %03d" % p.get("cruise_fl", self.cruise_fl),
                                       lambda delta: self._change_cruise(delta)))
        steps.add_widget(self._stepper("Airspeed", "%d kt" % p.get("tas_kt", 0),
                                       lambda delta: self._change_speed(delta)))
        summary.add_widget(steps)
        self.alt_input = TextInput(text=self.alternate, hint_text="Alternate airport (optional)",
                                   multiline=False, size_hint_y=None, height=dp(40),
                                   background_normal="", background_color=PANEL2,
                                   foreground_color=TEXT, hint_text_color=MUTED, padding=(dp(10), dp(9)))
        summary.add_widget(self.alt_input)
        self.body.add_widget(summary)
        timecard = Card(orientation="vertical", size_hint_y=None, height=dp(150))
        timecard.add_widget(label("Timeline", 13, TEXT, True, halign="left"))
        now = time.strftime("%d/%m/%Y, %H:%M UTC", time.gmtime())
        eta_seconds = int(float(p.get("ete_min", 0)) * 60)
        eta = time.strftime("%d/%m/%Y, %H:%M UTC", time.gmtime(time.time() + eta_seconds))
        timecard.add_widget(label("Actual time of departure     " + now, 10, MUTED, halign="left"))
        timecard.add_widget(label("Estimated time of arrival   " + eta, 10, MUTED, halign="left"))
        self.body.add_widget(timecard)
        routecard = Card(orientation="vertical", size_hint_y=None, height=dp(132))
        routecard.add_widget(label("Route", 12, TEXT, True, halign="left"))
        self.route_result = TextInput(text=p.get("route", ""), multiline=True, size_hint_y=None,
                                      height=dp(76), background_normal="", background_color=PANEL2,
                                      foreground_color=TEXT, cursor_color=BLUE, padding=dp(8))
        routecard.add_widget(self.route_result)
        routecard.add_widget(label("Route source: %s%s" % (
            p.get("routing_source", "direct/entered route"),
            (" • AIRAC " + str(p["nav_cycle"])) if p.get("nav_cycle") else
            " • airway/procedure validity not asserted"), 8, MUTED, halign="left"))
        self.body.add_widget(routecard)

    def _stepper(self, title, value, callback):
        box = BoxLayout(orientation="vertical", spacing=dp(2))
        box.add_widget(label(title, 10, TEXT, True, halign="left"))
        row = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(3))
        b1 = self._btn("−", False, 30, size_hint_x=None, width=dp(34))
        b2 = self._btn("+", False, 30, size_hint_x=None, width=dp(34))
        v = label(value, 12, TEXT, True)
        b1.bind(on_release=lambda *_: callback(-1))
        b2.bind(on_release=lambda *_: callback(1))
        row.add_widget(b1); row.add_widget(v); row.add_widget(b2)
        box.add_widget(row)
        return box

    def _change_aircraft(self, value):
        self.aircraft.text = value
        self.recalculate()

    def _change_cruise(self, delta):
        self.cruise_fl = max(60, min(500, self.cruise_fl + delta * 10))
        self.recalculate()

    def _change_speed(self, delta):
        self.adjust_speed(delta)

    def recalculate(self, *_):
        if not self.generated:
            self.generate()
            return
        codes = self.plan.get("codes", [])
        points = self.plan.get("points", [])
        previous = dict(self.plan)
        self.plan = pc.plan_flight(points, pc.resolve_aircraft(self.aircraft.text), self.cruise_fl,
                                   speed_override_kt=self._effective_tas())
        self.route_points = list(points)
        self.plan.update({
            "origin": codes[0], "destination": codes[-1],
            "origin_name": self._airport(codes[0])["name"],
            "destination_name": self._airport(codes[-1])["name"],
            "route": getattr(self, "route_result", None).text if hasattr(self, "route_result") else self.route_text,
            "codes": codes, "points": points, "aircraft_name": self.aircraft.text,
            "payload_pct": self.payload_pct,
            "sid": previous.get("sid", "Auto"),
            "star": previous.get("star", "Auto"),
            "approach": previous.get("approach", "Auto"),
            "alternate": previous.get("alternate", self.alternate),
            "departure_runway": previous.get("departure_runway", "AUTO / unresolved locally"),
            "arrival_runway": previous.get("arrival_runway", "AUTO / unresolved locally"),
            "nav_cycle": previous.get("nav_cycle"),
            "routing_source": previous.get("routing_source", "direct/entered route")
        })
        if hasattr(self, "alt_input"):
            self.alternate = self.alt_input.text.strip().upper()
            self.plan["alternate"] = self.alternate
        self.route_text = self.plan["route"]
        self._build_results()
        self.status.text = "Recalculated • %.0f nm" % self.plan.get("distance_nm", 0)

    def _table_tab(self):
        p = self.plan
        self.body.add_widget(label("Route table", 15, TEXT, True, halign="left"))
        self.body.add_widget(label("Only coordinates resolved from the local airport database are plotted. Other fix names remain text until navdata resolves them.", 9, MUTED, halign="left"))
        for i, code in enumerate(p.get("codes", [])):
            row = Card(orientation="horizontal", size_hint_y=None, height=dp(58), padding=dp(9))
            name = self._airport(code)
            row.add_widget(label("%02d   %s" % (i + 1, code), 12, BLUE_SOFT, True,
                                 size_hint_x=None, width=dp(92), halign="left"))
            if name:
                detail = "%s\n%0.4f, %0.4f" % (name["name"], name["lat"], name["lon"])
            else:
                detail = "Navigation coordinates not resolved"
            row.add_widget(label(detail, 9, MUTED, halign="left"))
            self.body.add_widget(row)
        pplan = p
        totals = Card(orientation="vertical", size_hint_y=None, height=dp(90))
        totals.add_widget(label("Distance   %.1f NM" % pplan.get("distance_nm", 0), 11, TEXT, True, halign="left"))
        totals.add_widget(label("Initial track   %03.0f°" % self._bearing(), 10, MUTED, halign="left"))
        totals.add_widget(label("Estimated en-route time   %s" % self._duration(pplan.get("ete_min", 0)), 10, MUTED, halign="left"))
        self.body.add_widget(totals)

    def _load_tab(self):
        p = self.plan
        self.body.add_widget(label("Payload & loading", 15, TEXT, True, halign="left"))
        card = Card(orientation="vertical", size_hint_y=None, height=dp(265))
        row = BoxLayout(size_hint_y=None, height=dp(30))
        row.add_widget(label("Payload", 11, TEXT, True, halign="left"))
        row.add_widget(label("%d%%" % self.payload_pct, 11, BLUE_SOFT, True, halign="right"))
        card.add_widget(row)
        sl = Slider(min=0, max=100, value=self.payload_pct, step=1)
        sl.bind(value=lambda _, v: self._update_result_payload(int(v)))
        card.add_widget(sl)
        aircraft_code = pc.resolve_aircraft(p.get("aircraft_name", self.aircraft.text))
        payload_capacity = {"A35K": 56000, "A359": 51000, "A320": 19000, "B738": 20000,
                            "B77W": 55000, "B789": 48000, "A388": 80000, "C172": 400, "DH8D": 8000}.get(aircraft_code, 20000)
        amount = payload_capacity * self.payload_pct / 100.0
        rows = [
            ("Estimated payload", "%,.0f kg" % amount),
            ("Passengers (planning estimate)", str(max(0, int(amount / 95)))),
            ("Baggage / cargo allowance", "%,.0f kg" % (amount * 0.18)),
            ("Estimated trip fuel", "%,.0f kg" % p.get("fuel_trip_kg", 0)),
            ("Reserve fuel", "%,.0f kg" % p.get("fuel_reserve_kg", 0)),
            ("Trip + reserve fuel", "%,.0f kg" % p.get("fuel_total_kg", 0)),
        ]
        for name, val in rows:
            r = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(4))
            r.add_widget(label(name, 10, MUTED, halign="left"))
            r.add_widget(label(val, 10, TEXT, True, halign="right"))
            card.add_widget(r)
        self.body.add_widget(card)
        self.body.add_widget(label("Weights are simplified simulation estimates. Use the aircraft's actual performance data and SimBrief for dispatch decisions.", 8, MUTED, halign="left"))

    def _update_result_payload(self, value):
        self.payload_pct = value
        self.plan["payload_pct"] = value
        self.active_tab = "Load"
        self._build_results()

    def _profile_tab(self):
        p = self.plan
        self.body.add_widget(label("Route profile", 15, TEXT, True, halign="left"))
        chart = ProfileChart(size_hint_y=None, height=dp(220))
        try:
            profile = pc.vertical_profile(p)
        except Exception:
            profile = []
        chart.set_profile(profile, float(p.get("distance_nm", 0)), int(p.get("cruise_fl", self.cruise_fl)))
        self.body.add_widget(chart)
        card = Card(orientation="vertical", size_hint_y=None, height=dp(112))
        card.add_widget(label("Terrain clearance", 12, TEXT, True, halign="left"))
        card.add_widget(label("Cruise FL   %03d" % p.get("cruise_fl", self.cruise_fl), 10, MUTED, halign="left"))
        card.add_widget(label("TOC / TOD estimate   %.0f NM / %.0f NM" %
                              (p.get("toc_nm", 0), p.get("tod_nm", 0)), 10, MUTED, halign="left"))
        card.add_widget(label("Terrain clearance requires terrain samples along the route; no clearance guarantee is made here.", 8, MUTED, halign="left"))
        self.body.add_widget(card)

    def _export_tab(self):
        p = self.plan
        self.body.add_widget(label("Export flight plan", 15, TEXT, True, halign="left"))
        card = Card(orientation="vertical", size_hint_y=None, height=dp(140))
        card.add_widget(label("General route formats", 11, TEXT, True, halign="left"))
        card.add_widget(label("Export GPX route points for compatible tools. Importing into a simulator still depends on its supported format and current navdata.", 9, MUTED, halign="left", valign="top"))
        save = self._btn("↓  Download GPX", True, 42)
        save.bind(on_release=self.export_gpx)
        card.add_widget(save)
        share = self._btn("Share route text", False, 38)
        share.bind(on_release=self.share_route)
        card.add_widget(share)
        self.body.add_widget(card)

        integrations = Card(orientation="vertical", size_hint_y=None, height=dp(192))
        integrations.add_widget(label("SimBrief / Navigraph", 12, TEXT, True, halign="left"))
        self.simbrief_input = TextInput(text=self.simbrief_username, hint_text="SimBrief username (for importing an existing OFP)",
                                        multiline=False, size_hint_y=None, height=dp(40),
                                        background_normal="", background_color=PANEL2,
                                        foreground_color=TEXT, hint_text_color=MUTED, padding=(dp(10), dp(9)))
        integrations.add_widget(self.simbrief_input)
        btnrow = GridLayout(cols=2, size_hint_y=None, height=dp(40), spacing=dp(6))
        imp = self._btn("Import SimBrief OFP", True, 38)
        imp.bind(on_release=self.import_simbrief)
        sim = self._btn("Open SimBrief", False, 38)
        sim.bind(on_release=self.open_simbrief)
        btnrow.add_widget(imp); btnrow.add_widget(sim); integrations.add_widget(btnrow)
        nav = self._btn("Open Navigraph Charts", False, 38)
        nav.bind(on_release=lambda *_: self.ui.open_url("https://charts.navigraph.com/"))
        integrations.add_widget(nav)
        self.body.add_widget(integrations)
        self.export_status = label("Export creates a local file and shows its path below.", 8, MUTED, halign="left")
        self.body.add_widget(self.export_status)

    def export_gpx(self, *_):
        try:
            os.makedirs(App.get_running_app().user_data_dir, exist_ok=True)
            p = self.plan
            marks = []
            for code, point in zip(p.get("codes", []), self.route_points):
                marks.append((code, point[0], point[1]))
            if not marks:
                marks = [(p["origin"], p["points"][0][0], p["points"][0][1]),
                         (p["destination"], p["points"][-1][0], p["points"][-1][1])]
            xml = pc.export_gpx("Aerofly ATC route", marks)
            dest = os.path.join(App.get_running_app().user_data_dir, "AeroflyATC_route.gpx")
            with open(dest, "w", encoding="utf-8") as f:
                f.write(xml)
            self.export_status.text = "GPX saved: " + dest
            self.status.text = "GPX exported."
            self.status.color = GREEN
        except Exception as exc:
            self.export_status.text = "Export failed: " + str(exc)[:140]

    def share_route(self, *_):
        route = self.plan.get("route", self.route_text)
        url = "https://dispatch.simbrief.com/options/new?" + urllib.parse.urlencode({
            "orig": self.plan.get("origin", ""), "dest": self.plan.get("destination", ""),
            "type": pc.resolve_aircraft(self.plan.get("aircraft_name", "")), "route": route
        })
        self.ui.open_url(url)
        self.status.text = "Opened route link. Review and confirm the route in the external service."

    def open_simbrief(self, *_):
        p = self.plan
        url = "https://dispatch.simbrief.com/options/new?" + urllib.parse.urlencode({
            "orig": p.get("origin", ""), "dest": p.get("destination", ""),
            "type": pc.resolve_aircraft(p.get("aircraft_name", "")), "route": p.get("route", "")
        })
        self.ui.open_url(url)

    def import_simbrief(self, *_):
        username = getattr(self, "simbrief_input", None)
        user = username.text.strip() if username else ""
        if not user:
            self.export_status.text = "Enter your SimBrief username."
            return
        self.simbrief_username = user
        self.export_status.text = "Fetching the latest SimBrief OFP..."
        def work():
            try:
                url = "https://www.simbrief.com/api/xml.fetcher.php?" + urllib.parse.urlencode({"username": user})
                req = urllib.request.Request(url, headers={"User-Agent": "AeroflyATC Android"})
                with urllib.request.urlopen(req, timeout=20) as response:
                    xml_data = response.read()
                root = ET.fromstring(xml_data)
                orig = (root.findtext("./origin/icao") or "").strip().upper()
                dest = (root.findtext("./destination/icao") or "").strip().upper()
                route = (root.findtext("./general/route") or "").strip()
                Clock.schedule_once(lambda *_: self._apply_simbrief(orig, dest, route), 0)
            except Exception as exc:
                Clock.schedule_once(lambda *_: setattr(self.export_status, "text",
                                 "SimBrief import failed: " + str(exc)[:140]), 0)
        threading.Thread(target=work, daemon=True).start()

    def _apply_simbrief(self, orig, dest, route):
        if not orig or not dest:
            self.export_status.text = "SimBrief OFP did not provide both airport codes."
            return
        self._build_form()
        self.origin.text = self._airport_value(orig)
        self.destination.text = self._airport_value(dest)
        self.route_input.text = route
        self.route_mode.text = "Custom route"
        self.generate()
        self.status.text = "SimBrief OFP imported. Verify the route and navdata."
        self.status.color = GREEN

    def _airport_value(self, code):
        for v in self.airport_values:
            if v.startswith(code + " ·"):
                return v
        return "Select an airport"

    def back_to_form(self, *_):
        self._build_form()

    def _bearing(self):
        points = self.plan.get("points", [])
        if len(points) < 2:
            return 0.0
        return pc.bearing_deg(points[0][0], points[0][1], points[-1][0], points[-1][1])

    @staticmethod
    def _duration(minutes):
        try:
            m = max(0, int(float(minutes)))
            return "%02d:%02d" % (m // 60, m % 60)
        except Exception:
            return "--:--"


class ProfileChart(Widget):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.profile = []
        self.distance_nm = 0
        self.cruise_fl = 0
        self.bind(pos=self.redraw, size=self.redraw)

    def set_profile(self, profile, distance_nm, cruise_fl):
        self.profile, self.distance_nm, self.cruise_fl = list(profile or []), distance_nm, cruise_fl
        self.redraw()

    def redraw(self, *_):
        self.canvas.clear()
        with self.canvas:
            Color(*PANEL)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
            Color(0.32, 0.38, 0.48, 0.46)
            for i in range(1, 5):
                y = self.y + self.height * i / 5.0
                Line(points=[self.x + dp(16), y, self.right - dp(12), y], width=0.6)
            Color(0.20, 0.58, 0.98, 0.95)
            if len(self.profile) > 1:
                max_x = max(float(x[0]) for x in self.profile) or 1.0
                max_y = max(float(x[1]) for x in self.profile) or self.cruise_fl * 100.0 or 1.0
                pts = []
                for dist, alt in self.profile:
                    px = self.x + dp(16) + (float(dist) / max_x) * max(dp(1), self.width - dp(28))
                    py = self.y + dp(18) + (float(alt) / max_y) * max(dp(1), self.height - dp(34))
                    pts.extend((px, py))
                Line(points=pts, width=dp(2.2))
            else:
                # No invented profile if calculation returned no samples.
                Color(*MUTED)
                Line(points=[self.x + dp(18), self.y + self.height * .25,
                             self.right - dp(18), self.y + self.height * .25], width=1)


class ReferenceUI:
    def __init__(self, app):
        self.app = app
        self.root = FloatLayout()
        with self.root.canvas.before:
            Color(*BG)
            self.bg = Rectangle(pos=self.root.pos, size=self.root.size)
        self.root.bind(pos=self._sync_bg, size=self._sync_bg)
        self.follow = True
        self.night_mode = True
        self.current_layer = "chart"
        self.layer_menu = None
        self.selection = None
        self._build()
        self.root.bind(size=self._geometry)
        Clock.schedule_once(lambda *_: self._geometry(self.root, self.root.size), 0.25)

    def _sync_bg(self, *_):
        self.bg.pos, self.bg.size = self.root.pos, self.root.size

    def _build(self):
        # Subtle star field around the clipped globe, as in the supplied screenshots.
        import random
        random.seed(41023)
        with self.root.canvas.before:
            Color(0.62, 0.67, 0.74, 0.30)
            for _ in range(105):
                sx = random.random() * 1000
                sy = random.random() * 1600
                radius = random.choice([0.5, 0.7, 1.0, 1.3])
                Ellipse(pos=(sx, sy), size=(radius, radius))

        self.app.map = self.app.map if getattr(self.app, "map", None) else None
        if self.app.map is None:
            raise RuntimeError("Telemetry map widget was not initialized")
        self.app.map.center_lat = 24.0
        self.app.map.center_lon = 8.0
        self.app.map.zoom = 3
        self.overlay = ChartOverlay(self.app.map)
        self.globe = GlobeViewport(self.app.map, self.overlay, size_hint=(1, 1))
        self.root.add_widget(self.globe)
        self.app.map.tap_callback = self.on_map_tap
        self.app.map.pan_callback = self.on_map_pan

        # Left search / aircraft / route stack.
        stack = BoxLayout(orientation="vertical", size_hint=(None, None),
                          size=(dp(48), dp(144)), spacing=dp(1),
                          pos_hint={"x": 0.026, "top": 0.88})
        with stack.canvas.before:
            Color(0.065, 0.071, 0.084, 0.95)
            self._stack_bg = RoundedRectangle(pos=stack.pos, size=stack.size, radius=[dp(26)])
            Color(0.32, 0.36, 0.43, 0.4)
            self._stack_edge = Line(rounded_rectangle=(stack.x, stack.y, stack.width, stack.height, dp(26)), width=0.9)
        stack.bind(pos=lambda w, *_: self._sync_stack(w), size=lambda w, *_: self._sync_stack(w))
        for glyph, fn in (("⌕", self.toggle_search), ("✈", self.toggle_telemetry),
                          ("⌁", self.open_planner)):
            b = Button(text=glyph, background_normal="", background_down="",
                       background_color=(0, 0, 0, 0), color=BLUE_SOFT,
                       font_size="23sp")
            b.bind(on_release=lambda _, callback=fn: callback())
            stack.add_widget(b)
        self.root.add_widget(stack)

        self.fullscreen = RoundButton("⛶", False, size_hint=(None, None),
                                      size=(dp(52), dp(52)),
                                      pos_hint={"right": 0.96, "top": 0.89},
                                      font_size="20sp")
        self.fullscreen.bind(on_release=self.toggle_fullscreen)
        self.root.add_widget(self.fullscreen)

        # Bottom map controls are separate from the persistent vertical tools.
        controls = BoxLayout(size_hint=(None, None), size=(dp(226), dp(44)),
                             spacing=dp(2), pos_hint={"x": 0.54, "y": 0.035})
        for glyph, action in (("△", self.show_terrain), ("◉", self.toggle_layers),
                              ("▱", self.toggle_layers), ("☁", self.show_weather)):
            b = RoundButton(glyph, False, font_size="17sp")
            b.bind(on_release=lambda _, cb=action: cb())
            controls.add_widget(b)
        self.root.add_widget(controls)
        self.recenter = RoundButton("➤", True, size_hint=(None, None),
                                    size=(dp(48), dp(48)), pos_hint={"right": 0.96, "y": 0.033},
                                    font_size="19sp")
        self.recenter.bind(on_release=self.recenter_map)
        self.root.add_widget(self.recenter)

        self.scale_label = label("500 nm", 9, MUTED, size_hint=(None, None),
                                 size=(dp(80), dp(24)), pos_hint={"x": 0.04, "y": 0.04},
                                 halign="center", valign="middle")
        self.root.add_widget(self.scale_label)
        self.attribution = label("OpenStreetMap © contributors", 8, MUTED,
                                 size_hint=(None, None), size=(dp(160), dp(18)),
                                 pos_hint={"x": 0.04, "y": 0.005}, halign="left")
        self.root.add_widget(self.attribution)

        self.link_chip = RoundButton("● WAITING  ·  0 packets", False,
                                     size_hint=(None, None), size=(dp(190), dp(32)),
                                     pos_hint={"center_x": 0.50, "top": 0.965}, font_size="9sp")
        self.link_chip.bind(on_release=self.toggle_telemetry)
        self.root.add_widget(self.link_chip)
        self._make_layers_menu()
        self._make_search_panel()
        self._make_telemetry_panel()
        self._make_info_panel()

    def _sync_stack(self, w):
        self._stack_bg.pos, self._stack_bg.size = w.pos, w.size
        self._stack_edge.rounded_rectangle = (w.x, w.y, w.width, w.height, dp(26))

    def _geometry(self, *_):
        if hasattr(self, "globe"):
            self.globe.fit_globe(self.root.size)
            self.overlay.redraw()
            self.app.map.load_tiles()

    def _panel(self, size, pos_hint):
        panel = Card(orientation="vertical", size_hint=(None, None),
                     size=size, pos_hint=pos_hint, padding=dp(12), spacing=dp(7))
        return panel

    def _make_layers_menu(self):
        self.layer_menu = self._panel((dp(178), dp(184)), {"right": 0.78, "y": 0.095})
        self.layer_menu.opacity = 0
        self.layer_menu.disabled = True
        row = BoxLayout(size_hint_y=None, height=dp(30))
        row.add_widget(label("Night mode", 12, TEXT, True, halign="left"))
        self.night_switch = CheckBox(active=True, size_hint_x=None, width=dp(34))
        self.night_switch.bind(active=self.set_night_mode)
        row.add_widget(self.night_switch)
        self.layer_menu.add_widget(row)
        self.layer_menu.add_widget(label("Map style", 9, MUTED, halign="left"))
        for title, key in (("Chart", "chart"), ("Terrain", "terrain"), ("Satellite", "satellite")):
            b = self._btn(title, key == self.current_layer, 34)
            b.bind(on_release=lambda _, k=key: self.select_layer(k))
            self.layer_menu.add_widget(b)
        self.root.add_widget(self.layer_menu)

    def _btn(self, text, active=False, height=38):
        return RoundButton(text=text, active=active, size_hint_y=None, height=dp(height), font_size="11sp")

    def _make_search_panel(self):
        self.search_panel = self._panel((dp(275), dp(135)), {"x": 0.16, "top": 0.84})
        self.search_input = TextInput(hint_text="Airport ICAO / name", multiline=False,
                                      size_hint_y=None, height=dp(40), background_normal="",
                                      background_color=PANEL2, foreground_color=TEXT,
                                      hint_text_color=MUTED, cursor_color=BLUE, padding=(dp(10), dp(8)))
        self.search_panel.add_widget(label("Search airport / map", 12, TEXT, True, halign="left"))
        self.search_panel.add_widget(self.search_input)
        b = self._btn("Search", True, 34)
        b.bind(on_release=self.search_airport)
        self.search_panel.add_widget(b)
        self.search_panel.opacity = 0
        self.search_panel.disabled = True
        self.root.add_widget(self.search_panel)

    def _make_telemetry_panel(self):
        self.telemetry_panel = self._panel((dp(330), dp(208)), {"x": 0.035, "y": 0.085})
        self.telemetry_panel.add_widget(label("AEROFLY TELEMETRY", 12, TEXT, True, halign="left"))
        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        self.ip = TextInput(hint_text="Simulator IPv4 address", text=self.app.telemetry.host,
                            multiline=False, size_hint_x=1,
                            background_normal="", background_color=PANEL2,
                            foreground_color=TEXT, hint_text_color=MUTED, cursor_color=BLUE,
                            padding=(dp(10), dp(8)))
        row.add_widget(self.ip)
        connect = self._btn("Connect", True, 38)
        connect.size_hint_x = None
        connect.width = dp(88)
        connect.bind(on_release=self.connect)
        row.add_widget(connect)
        self.telemetry_panel.add_widget(row)
        self.telemetry_status = label("TCP 58585  ·  UDP 49002 / 40092", 9, MUTED,
                                      halign="left", valign="top")
        self.telemetry_panel.add_widget(self.telemetry_status)
        self.telemetry_metrics = label("LAT --   LON --   ALT -- ft\\nGS -- kt   HDG ---", 10, BLUE_SOFT,
                                       halign="left", valign="top")
        self.telemetry_panel.add_widget(self.telemetry_metrics)
        self.telemetry_panel.opacity = 0
        self.telemetry_panel.disabled = True
        self.root.add_widget(self.telemetry_panel)

    def _make_info_panel(self):
        self.info_panel = self._panel((dp(332), dp(166)), {"x": 0.035, "y": 0.085})
        self.info_title = label("Position", 13, TEXT, True, halign="left")
        self.info_panel.add_widget(self.info_title)
        self.info_pos = label("Tap a point on the map to inspect coordinates.", 10, MUTED,
                              halign="left", valign="top")
        self.info_panel.add_widget(self.info_pos)
        self.info_nav = label("Navigation data: not queried", 9, MUTED, halign="left")
        self.info_panel.add_widget(self.info_nav)
        self.info_panel.opacity = 0
        self.info_panel.disabled = True
        self.root.add_widget(self.info_panel)

    def _show_only_panel(self, selected):
        for p in (self.search_panel, self.telemetry_panel, self.info_panel):
            show = p is selected
            p.opacity = 1 if show else 0
            p.disabled = not show

    def toggle_search(self, *_):
        visible = self.search_panel.opacity > 0
        self._show_only_panel(None if visible else self.search_panel)
        if not visible:
            self.search_input.focus = True

    def toggle_telemetry(self, *_):
        visible = self.telemetry_panel.opacity > 0
        self._show_only_panel(None if visible else self.telemetry_panel)

    def toggle_layers(self, *_):
        visible = self.layer_menu.opacity > 0
        self.layer_menu.opacity = 0 if visible else 1
        self.layer_menu.disabled = visible

    def select_layer(self, key):
        self.current_layer = key
        self.app.map.set_layer(key)
        self.layer_menu.opacity = 0
        self.layer_menu.disabled = True
        self.attribution.text = ("OpenStreetMap © contributors" if key == "chart" else
                                 "Terrain tiles © OpenTopoMap" if key == "terrain" else
                                 "Imagery © Esri")
        self.overlay.redraw()

    def set_night_mode(self, _, active):
        self.night_mode = bool(active)
        self.overlay.night_mode = self.night_mode
        self.overlay.redraw()

    def show_terrain(self, *_):
        self.select_layer("terrain")

    def show_weather(self, *_):
        self._show_only_panel(self.info_panel)
        self.info_title.text = "Weather overlay"
        self.info_pos.text = "Current cloud, precipitation and wind values are available from the Open-Meteo service. Select a point on the map for a position-specific refresh."
        self.info_nav.text = "Weather raster radar is not enabled in this build."

    def toggle_fullscreen(self, *_):
        try:
            from kivy.core.window import Window
            Window.fullscreen = False if Window.fullscreen else "auto"
        except Exception:
            pass

    def recenter_map(self, *_):
        d = self.app.telemetry.snapshot()
        if d.get("lat") is not None and d.get("lon") is not None:
            self.app.map.center_lat, self.app.map.center_lon = d["lat"], d["lon"]
            self.app.map.zoom = max(self.app.map.zoom, 4)
        else:
            self.app.map.center_lat, self.app.map.center_lon = 24.0, 8.0
        self.follow = True
        self.app.follow_map = True
        self.app.map.load_tiles()
        self.app.map.redraw()
        self.overlay.redraw()

    def search_airport(self, *_):
        query = self.search_input.text.strip().upper()
        row = pc.lookup_airport(query)
        if not row:
            matches = [(code, val) for code, val in self.overlay.airports.items()
                       if query and (query in code or query.lower() in val[2].lower())]
            if matches:
                code, val = matches[0]
                row = {"icao": code, "lat": val[0], "lon": val[1], "name": val[2]}
        if not row:
            self.info_title.text = "No local airport match"
            self.info_pos.text = "Use a known ICAO airport code, or load a current navigation-data source."
            self.info_nav.text = "No coordinates returned."
            self._show_only_panel(self.info_panel)
            return
        self.app.map.center_lat, self.app.map.center_lon = row["lat"], row["lon"]
        self.app.map.zoom = 5
        self.app.map.load_tiles()
        self.app.map.redraw()
        self.info_title.text = "%s  ·  %s" % (row["icao"], row["name"])
        self.info_pos.text = "N %.5f°   E/W %.5f°" % (row["lat"], row["lon"])
        self.info_nav.text = "Airport coordinates from the local reference table."
        self._show_only_panel(self.info_panel)
        self.overlay.redraw()

    def open_planner(self, *_):
        self.planner = FlightPlanOverlay(self, size_hint=(1, 1))
        self.root.add_widget(self.planner)

    def close_planner(self):
        if hasattr(self, "planner") and self.planner.parent:
            self.root.remove_widget(self.planner)

    def connect(self, *_):
        host = self.ip.text.strip()
        self.app.telemetry.reconnect(host)
        self.telemetry_status.text = "Connecting to %s:58585  ·  TCP stream request + UDP 49002/40092" % (host or "simulator IP")

    def on_map_pan(self):
        self.follow = False
        self.app.follow_map = False
        self.link_chip.text = "● FREE MAP  ·  tap ➤ to follow"

    def on_map_tap(self, lat, lon):
        # Ignore touches outside the visible spherical viewport.
        gx, gy = self.globe._mask.pos
        d = self.globe._mask.size[0]
        cx, cy = gx + d / 2, gy + d / 2
        if (lat is None) or (lon is None):
            return
        # The mapping widget can receive touch events in the square corners; only display
        # a point card for points inside the circle.
        self.info_title.text = "Position"
        self.info_pos.text = "LAT %0.5f°\\nLON %0.5f°" % (lat, lon)
        self.info_nav.text = "Checking current navigation data..."
        self._show_only_panel(self.info_panel)
        def work():
            try:
                nearby = adv.nearby_navdata(lat, lon, 20)
                airports = nearby.get("airports", []) if isinstance(nearby, dict) else []
                waypoints = nearby.get("waypoints", []) if isinstance(nearby, dict) else []
                navaids = nearby.get("navaids", []) if isinstance(nearby, dict) else []
                cycle = nearby.get("cycle") if isinstance(nearby, dict) else None
                entries = airports[:1] + waypoints[:1] + navaids[:1]
                summary = ", ".join(str(x.get("identifier") or x.get("icao") or x.get("name") or "fix")
                                    for x in entries if isinstance(x, dict))
                txt = ("AIRAC %s  ·  %s" % (cycle or "unknown", summary)) if summary else "No nearby records returned by the navdata service."
                Clock.schedule_once(lambda *_: setattr(self.info_nav, "text", txt), 0)
            except Exception:
                Clock.schedule_once(lambda *_: setattr(self.info_nav, "text", "Navigation data unavailable."), 0)
        threading.Thread(target=work, daemon=True).start()

    def refresh_telemetry(self, d):
        if hasattr(self, "link_chip"):
            connected = d.get("connected", False)
            self.link_chip.text = ("● CONNECTED" if connected else "● WAITING") + "  ·  %s packets" % d.get("packets", 0)
            self.link_chip.color = GREEN if connected else BLUE_SOFT
            self.telemetry_status.text = d.get("message", "Waiting for telemetry") + "\\n" + d.get("transport", "WAITING")
            if d.get("lat") is not None and d.get("lon") is not None:
                self.telemetry_metrics.text = "LAT %.5f   LON %.5f\\nALT %.0f ft   GS %.0f kt   HDG %03.0f" % (
                    d["lat"], d["lon"], d.get("alt", 0), d.get("speed", 0), d.get("heading", 0))
            self.overlay.redraw()

    def open_url(self, url):
        try:
            if platform == "android":
                from jnius import autoclass
                Intent = autoclass("android.content.Intent")
                Uri = autoclass("android.net.Uri")
                Activity = autoclass("org.kivy.android.PythonActivity")
                intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                Activity.mActivity.startActivity(intent)
            else:
                webbrowser.open(url)
        except Exception:
            try:
                webbrowser.open(url)
            except Exception:
                pass
