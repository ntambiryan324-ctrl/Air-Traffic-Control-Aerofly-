import math
import os
import re
import socket
import threading
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Line, Ellipse, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.spinner import Spinner
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.stencilview import StencilView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import escape_markup

import planner_core as pc
from atc_engine import ATCEngine
from extras import CHECKLISTS, FlightMonitor, Logbook
from voice import Voice

BG = (0.035, 0.055, 0.075, 1)
PANEL = (0.075, 0.10, 0.13, 1)
TEXT = (0.92, 0.95, 0.98, 1)
MUTED = (0.62, 0.70, 0.77, 1)
GREEN = (0.16, 0.85, 0.48, 1)
BLUE = (0.18, 0.58, 0.95, 1)
AMBER = (0.98, 0.74, 0.15, 1)


class MovingMap(StencilView):
    """Offline orthographic globe. No tile server needed. StencilView keeps drawing inside its box."""
    AIRPORTS = [(c, v[0], v[1]) for c, v in pc.AIRPORT_DB.items()]
    AIRWAYS = [
        ("HKJK", "HUEN"), ("HKJK", "HAAB"), ("HAAB", "HECA"), ("HECA", "OERK"),
        ("OERK", "OMDB"), ("OMDB", "VABB"), ("VABB", "VIDP"), ("VIDP", "WSSS"),
        ("WSSS", "RJTT"), ("WSSS", "ZBAA"), ("EGLL", "LFPG"), ("EGLL", "EDDF"),
        ("EDDF", "EHAM"), ("LFPG", "LIRF"), ("LEMD", "LPPT"), ("LOWW", "LTFM"),
        ("LTFM", "OMDB"), ("KJFK", "CYYZ"), ("KJFK", "EGLL"), ("KLAX", "KSFO"),
        ("KJFK", "KLAX"), ("SBGR", "DNMM"), ("DNMM", "GOBD"), ("GOBD", "LPPT"),
        ("FAOR", "FACT"), ("FAOR", "HKJK"), ("YSSY", "NZAA"), ("RJTT", "YSSY"),
        ("HUEN", "DNMM"), ("HAAB", "FAOR"), ("EDDF", "UUDD"), ("OMDB", "WSSS"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ac_lat, self.ac_lon, self.heading = 0.0, 20.0, 0.0
        self.view_lat, self.view_lon = 12.0, 20.0
        self.has_aircraft_position = False
        self.follow = True
        self.zoom = 1.0
        self.route = []
        self._tex = {}
        self._drag_last = None
        self.bind(pos=lambda *_: self.redraw(), size=lambda *_: self.redraw())

    def set_position(self, lat, lon, heading):
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return
        self.has_aircraft_position = True
        self.ac_lat, self.ac_lon, self.heading = lat, lon, heading
        if self.follow:
            self.view_lat, self.view_lon = lat, lon
        self.redraw()

    def set_route(self, points):
        self.route = list(points or [])
        self.redraw()

    def pan(self, dx, dy):
        self.follow = False
        scale = 0.35 / max(self.zoom, 0.75)
        self.view_lon = ((self.view_lon - dx * scale) + 180) % 360 - 180
        self.view_lat = max(-85, min(85, self.view_lat + dy * scale))
        self.redraw()

    def zoom_by(self, factor):
        self.zoom = max(0.75, min(8.0, self.zoom * factor))
        self.redraw()

    def center_plane(self):
        self.follow = True
        if self.has_aircraft_position:
            self.view_lat, self.view_lon = self.ac_lat, self.ac_lon
        self.redraw()

    def _project(self, lat, lon, cx, cy, radius):
        p1, p2 = math.radians(lat), math.radians(self.view_lat)
        dl = math.radians((lon - self.view_lon + 180) % 360 - 180)
        cosc = math.sin(p2) * math.sin(p1) + math.cos(p2) * math.cos(p1) * math.cos(dl)
        if cosc < 0.0:
            return None
        x = radius * math.cos(p1) * math.sin(dl)
        y = radius * (math.cos(p2) * math.sin(p1) - math.sin(p2) * math.cos(p1) * math.cos(dl))
        return cx + x, cy + y

    def _geo_line(self, pts, cx, cy, radius, width):
        run = []
        for lat, lon in pts:
            p = self._project(lat, lon, cx, cy, radius)
            if p:
                run.extend(p)
            else:
                if len(run) >= 4:
                    Line(points=run, width=width)
                run = []
        if len(run) >= 4:
            Line(points=run, width=width)

    def _texture(self, text):
        tex = self._tex.get(text)
        if tex is None:
            glyph = CoreLabel(text=text, font_size=dp(9), color=(0.35, 0.68, 1, 1))
            glyph.refresh()
            tex = self._tex[text] = glyph.texture
        return tex

    def redraw(self):
        self.canvas.clear()
        if self.width < 2 or self.height < 2:
            return
        with self.canvas:
            Color(0.018, 0.025, 0.040, 1)
            Rectangle(pos=self.pos, size=self.size)
            radius = min(self.width * 0.46, self.height * 0.47) * self.zoom
            cx, cy = self.center
            Color(0.025, 0.055, 0.085, 1)
            Ellipse(pos=(cx - radius, cy - radius), size=(2 * radius, 2 * radius))
            # True graticule: parallels every 30 deg, meridians every 30 deg.
            Color(0.30, 0.43, 0.52, 0.35)
            for lat in range(-60, 61, 30):
                self._geo_line([(lat, lon) for lon in range(-180, 181, 6)], cx, cy, radius, 0.65)
            for lon in range(-180, 180, 30):
                self._geo_line([(lat, lon) for lat in range(-85, 86, 5)], cx, cy, radius, 0.65)
            ap = {c: (la, lo) for c, la, lo in self.AIRPORTS}
            Color(0.22, 0.43, 0.70, 0.60)
            for a, b in self.AIRWAYS:
                if a in ap and b in ap:
                    self._geo_line(pc.great_circle_points(*ap[a], *ap[b], step_nm=200.0),
                                   cx, cy, radius, 0.75)
            for code, (la, lo) in ap.items():
                p = self._project(la, lo, cx, cy, radius)
                if not p:
                    continue
                x, y = p
                Color(0.15, 0.58, 0.96, 0.95)
                Ellipse(pos=(x - dp(2), y - dp(2)), size=(dp(4), dp(4)))
                if self.zoom >= 1.0:
                    tex = self._texture(code)
                    Color(1, 1, 1, 1)
                    Rectangle(texture=tex, pos=(x + dp(4), y + dp(2)), size=tex.size)
            if len(self.route) > 1:
                Color(*AMBER)
                self._geo_line(self.route, cx, cy, radius, 1.8)
            if self.has_aircraft_position:
                p = self._project(self.ac_lat, self.ac_lon, cx, cy, radius)
                if p:
                    x, y = p
                    Color(0.05, 0.95, 0.66, 0.18)
                    Ellipse(pos=(x - dp(12), y - dp(12)), size=(dp(24), dp(24)))
                    Color(0.18, 1.0, 0.70, 1)
                    Ellipse(pos=(x - dp(4), y - dp(4)), size=(dp(8), dp(8)))
                    Color(0.88, 1.0, 0.96, 1)
                    h = math.radians(self.heading)
                    Line(points=[x, y, x + math.sin(h) * dp(22), y + math.cos(h) * dp(22)], width=2)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._drag_last = touch.pos
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._drag_last and self.collide_point(*touch.pos):
            ox, oy = self._drag_last
            self.pan(touch.x - ox, touch.y - oy)
            self._drag_last = touch.pos
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        self._drag_last = None
        return super().on_touch_up(touch)


class ProfileView(Widget):
    """Vertical profile (distance vs altitude)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pts = []
        self.bind(pos=lambda *_: self.redraw(), size=lambda *_: self.redraw())

    def set_profile(self, pts):
        self.pts = list(pts or [])
        self.redraw()

    def redraw(self):
        self.canvas.clear()
        with self.canvas:
            Color(0.025, 0.045, 0.065, 1)
            Rectangle(pos=self.pos, size=self.size)
            if len(self.pts) < 2:
                return
            dmax = max(p[0] for p in self.pts) or 1.0
            amax = max(p[1] for p in self.pts) or 1.0
            pad = dp(10)
            flat = []
            for d, a in self.pts:
                flat.extend([self.x + pad + d / dmax * (self.width - 2 * pad),
                             self.y + pad + a / amax * (self.height - 2 * pad)])
            Color(*BLUE)
            Line(points=flat, width=1.6)


class Telemetry:
    TCP_PORT = 58585
    UDP_PORTS = (49002, 40092)

    @staticmethod
    def detect_local_ip():
        probe = None
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
        except OSError:
            return ""
        finally:
            if probe:
                probe.close()

    def __init__(self):
        self.host = self.detect_local_ip() or "127.0.0.1"
        self.running = False
        self.lock = threading.RLock()
        self.tcp = None
        self.capture_path = None
        self.capture_left = 0
        self.data = {"connected": False, "transport": "WAITING", "lat": None, "lon": None,
                     "alt_ft": 0.0, "speed_kt": 0.0, "heading": 0.0, "pitch": 0.0,
                     "bank": 0.0, "sim": "", "packets": 0, "last_packet": 0.0,
                     "message": "Enter simulator IP, then tap CONNECT"}

    # ---- raw capture, used to study what the simulator actually sends ----
    def start_capture(self, path, limit=65536):
        with self.lock:
            self.capture_path, self.capture_left = path, limit
        try:
            open(path, "wb").close()
        except OSError:
            self.capture_path = None

    def stop_capture(self):
        with self.lock:
            self.capture_path, self.capture_left = None, 0

    def _capture(self, tag, chunk):
        with self.lock:
            path, left = self.capture_path, self.capture_left
            if not path or left <= 0:
                return
            chunk = chunk[:left]
            self.capture_left = left - len(chunk)
        try:
            with open(path, "ab") as f:
                f.write(("[%s %s] " % (tag, time.strftime("%H:%M:%S"))).encode() + chunk + b"\n")
                f.write(b"HEX " + chunk.hex().encode() + b"\n---\n")
        except OSError:
            pass

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._udp_loop, daemon=True).start()
        threading.Thread(target=self._tcp_loop, daemon=True).start()

    def set_host(self, host):
        host = host.strip() or "127.0.0.1"
        if host == self.host:
            return
        self.host = host
        s = self.tcp
        if s:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass

    def _parse(self, raw, transport, source):
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        for line in re.split(r"[\r\n]+", text):
            line = line.strip()
            try:
                if line.startswith("XGPS"):
                    p = line[4:].strip().split(",")
                    if len(p) < 6:
                        continue
                    with self.lock:
                        self.data.update({"sim": p[0].strip(), "lon": float(p[1]), "lat": float(p[2]),
                                          "alt_ft": float(p[3]) * 3.280839895, "heading": float(p[4]) % 360,
                                          "speed_kt": float(p[5]) * 1.943844492, "connected": True,
                                          "transport": transport, "message": "Telemetry received from " + source,
                                          "last_packet": time.time(), "packets": self.data["packets"] + 1})
                elif line.startswith("XATT"):
                    p = line[4:].strip().split(",")
                    if len(p) < 4:
                        continue
                    with self.lock:
                        self.data.update({"sim": p[0].strip(), "heading": float(p[1]) % 360,
                                          "pitch": float(p[2]), "bank": float(p[3]), "connected": True,
                                          "transport": transport, "message": "Telemetry received from " + source,
                                          "last_packet": time.time(), "packets": self.data["packets"] + 1})
            except (ValueError, IndexError):
                continue

    def _udp_loop(self):
        while self.running:
            opened = []
            try:
                for port in self.UDP_PORTS:
                    s = None
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        s.bind(("0.0.0.0", port))
                        s.settimeout(1)
                        opened.append((port, s))
                    except OSError:
                        if s:
                            try:
                                s.close()
                            except OSError:
                                pass
                if not opened:
                    with self.lock:
                        self.data["message"] = "UDP 49002/40092 unavailable (port already in use?)"
                    time.sleep(2)
                    continue
                while self.running:
                    for port, s in opened:
                        try:
                            raw, addr = s.recvfrom(65535)
                            self._capture("UDP %d" % port, raw)
                            self._parse(raw, "UDP " + str(port), addr[0])
                        except socket.timeout:
                            pass
                        except OSError:
                            break
            finally:
                for _, s in opened:
                    try:
                        s.close()
                    except OSError:
                        pass
            time.sleep(.5)

    def _tcp_loop(self):
        while self.running:
            s = None
            requested_host = self.host
            connected_host = requested_host
            try:
                candidates = []
                for candidate in (requested_host, self.detect_local_ip(), "127.0.0.1"):
                    if candidate and candidate not in candidates:
                        candidates.append(candidate)
                last_error = None
                for candidate in candidates:
                    with self.lock:
                        self.data["message"] = "Connecting to %s:%d..." % (candidate, self.TCP_PORT)
                    try:
                        s = socket.create_connection((candidate, self.TCP_PORT), timeout=4)
                        connected_host = candidate
                        break
                    except OSError as e:
                        last_error = e
                if s is None:
                    raise last_error or OSError("No simulator address could be reached")
                s.settimeout(2)
                self.tcp = s
                with self.lock:
                    self.data["message"] = "TCP connected at %s:%d; waiting for telemetry" % (connected_host, self.TCP_PORT)
                buf = b""
                got_data = False
                probe_sent = False
                while self.running and requested_host == self.host:
                    try:
                        chunk = s.recv(8192)
                        if not chunk:
                            break
                        got_data = True
                        self._capture("TCP 58585", chunk)
                        buf += chunk
                        buf = buf.replace(b"\r", b"\n")
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            self._parse(line, "TCP 58585", connected_host)
                        if buf.startswith((b"XGPS", b"XATT")):
                            fields = buf.count(b",")
                            if (buf.startswith(b"XGPS") and fields >= 5) or (buf.startswith(b"XATT") and fields >= 3):
                                self._parse(buf, "TCP 58585", connected_host)
                                buf = b""
                    except socket.timeout:
                        if not got_data and not probe_sent:
                            # Silent after 2 s: some setups need a request first, so probe once.
                            probe_sent = True
                            s.sendall(b"GET / HTTP/1.1\r\n\r\n")
                            self._capture("TCP SENT", b"GET / HTTP/1.1")
                        if time.time() - self.data["last_packet"] > 5:
                            with self.lock:
                                self.data["connected"] = False
                                self.data["message"] = ("TCP reachable at %s:%d, but no telemetry received. Enable "
                                                        "Send flight data to FSWidgets Apps in Aerofly." % (connected_host, self.TCP_PORT))
            except OSError as e:
                with self.lock:
                    self.data["connected"] = False
                    self.data["message"] = "TCP %d failed: %s. Check Aerofly FSWidgets setting and target IP." % (self.TCP_PORT, e)
                time.sleep(2)
            finally:
                if s:
                    try:
                        s.close()
                    except OSError:
                        pass
                self.tcp = None
            time.sleep(1)

    def snapshot(self):
        with self.lock:
            d = dict(self.data)
        if time.time() - d["last_packet"] > 5:
            d["connected"] = False
        return d

    def stop(self):
        self.running = False
        if self.tcp:
            try:
                self.tcp.close()
            except OSError:
                pass


class AeroflyATCApp(App):
    title = "Aerofly ATC"
    icon = "icon.png"

    # ---------- small widget helpers ----------
    def _label(self, text, size="12sp", color=TEXT, bold=False, halign="left"):
        w = Label(text=text, font_size=size, color=color, bold=bold, halign=halign,
                  valign="middle", shorten=True, shorten_from="right")
        w.bind(size=lambda obj, *_: setattr(obj, "text_size", obj.size))
        return w

    def _input(self, hint, text=""):
        return TextInput(text=text, hint_text=hint, multiline=False, size_hint_y=None, height=dp(44),
                         background_normal="", background_active="", background_color=PANEL,
                         foreground_color=TEXT, hint_text_color=MUTED, cursor_color=TEXT,
                         padding=(dp(12), dp(11)))

    def _button(self, text, cb, color=BLUE, height=44):
        b = Button(text=text, size_hint_y=None, height=dp(height), background_normal="",
                   background_color=color, color=TEXT, bold=True, font_size="11sp")
        b.bind(on_press=cb)
        return b

    def _scroll_label(self, markup=False, size="12sp"):
        sv = ScrollView(do_scroll_x=False)
        lbl = Label(text="", font_size=size, color=TEXT, markup=markup, size_hint_y=None,
                    halign="left", valign="top")
        lbl.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
        lbl.bind(texture_size=lambda w, ts: setattr(w, "height", ts[1]))
        sv.add_widget(lbl)
        return sv, lbl

    def _row(self, *widgets, height=44, spacing=6):
        r = BoxLayout(size_hint_y=None, height=dp(height), spacing=dp(spacing))
        for w in widgets:
            r.add_widget(w)
        return r

    # ---------- build ----------
    def build(self):
        try:
            Window.softinput_mode = "below_target"
        except Exception:
            pass
        self.telemetry = Telemetry()
        self.atc = ATCEngine()
        self.logbook = Logbook(os.path.join(self.user_data_dir, "logbook.json"))
        self.monitor = FlightMonitor(self.logbook)
        self.voice = Voice()
        self.voice_on = True
        self.alert_until = 0.0
        self.plan = {}
        self.metars = {}
        self._llm = None
        self._llm_tried = False
        self.screen_mode = "map"

        self.root_box = BoxLayout(orientation="vertical")
        with self.root_box.canvas.before:
            Color(*BG)
            self.background = Rectangle(pos=self.root_box.pos, size=self.root_box.size)
        self.root_box.bind(pos=lambda w, *_: setattr(self.background, "pos", w.pos),
                           size=lambda w, *_: setattr(self.background, "size", w.size))

        head = BoxLayout(size_hint_y=None, height=dp(48), padding=(dp(12), 0, dp(10), 0), spacing=dp(8))
        head.add_widget(self._label("AEROFLY ATC  /  FLIGHT DECK", "15sp", TEXT, True))
        self.state = self._label("OFFLINE", "11sp", MUTED, True, "right")
        self.state.size_hint_x = None
        self.state.width = dp(112)
        head.add_widget(self.state)
        self.root_box.add_widget(head)

        self.content = BoxLayout(orientation="vertical")
        self.root_box.add_widget(self.content)

        self.screens = {"map": self._build_map(), "plan": self._build_plan(),
                        "atc": self._build_atc(), "tools": self._build_tools(),
                        "link": self._build_link()}

        nav = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(2), padding=(dp(6), dp(4)))
        for label, mode in (("GLOBE", "map"), ("PLAN", "plan"), ("ATC", "atc"), ("TOOLS", "tools"), ("LINK", "link")):
            b = Button(text=label, background_normal="", background_color=PANEL, color=TEXT,
                       font_size="11sp", bold=True)
            b.bind(on_press=lambda _btn, m=mode: self.show_screen(m))
            nav.add_widget(b)
        self.root_box.add_widget(nav)
        self.show_screen("map")
        Clock.schedule_once(lambda *_: self.telemetry.start(), .4)
        Clock.schedule_interval(self.refresh, .5)
        return self.root_box

    def show_screen(self, mode):
        self.screen_mode = mode
        self.content.clear_widgets()
        self.content.add_widget(self.screens[mode])

    # ---------- GLOBE ----------
    def _build_map(self):
        stage = BoxLayout(orientation="vertical")
        self.map = MovingMap()
        stage.add_widget(self.map)
        controls = self._row(self._button("CENTER", lambda *_: self.map.center_plane(), PANEL, 38),
                             self._button("+", lambda *_: self.map.zoom_by(1.35), PANEL, 38),
                             self._button("-", lambda *_: self.map.zoom_by(1 / 1.35), PANEL, 38),
                             height=38)
        controls.padding = (dp(8), 0)
        stage.add_widget(controls)
        self.alert = self._label("", "12sp", AMBER, True)
        self.alert.size_hint_y = None
        self.alert.height = dp(26)
        self.alert.padding = (dp(12), 0)
        stage.add_widget(self.alert)
        self.metrics = self._label("LAT --  LON --  ALT -- ft  GS -- kt  HDG ---", "11sp", TEXT, True)
        self.metrics.size_hint_y = None
        self.metrics.height = dp(32)
        stage.add_widget(self.metrics)
        self.status = self._label("Aerofly FS Global: enable Send flight data to FSWidgets Apps", "10sp", MUTED)
        self.status.size_hint_y = None
        self.status.height = dp(28)
        stage.add_widget(self.status)
        return stage

    # ---------- PLAN (FlyCharts-style) ----------
    def _build_plan(self):
        box = BoxLayout(orientation="vertical", padding=(dp(12), dp(8)), spacing=dp(6))
        self.in_orig = self._input("Departure ICAO (e.g. HUEN)")
        self.in_dest = self._input("Arrival ICAO (e.g. HKJK)")
        self.in_ac = self._input("Aircraft (A320, A350, B777, C172...)", "A350")
        self.in_fl = self._input("Cruise FL (optional)", "")
        self.in_sb = self._input("SimBrief username (optional)")
        box.add_widget(self._row(self.in_orig, self.in_dest))
        box.add_widget(self._row(self.in_ac, self.in_fl))
        box.add_widget(self.in_sb)
        box.add_widget(self._row(self._button("GENERATE", self.generate_plan),
                                 self._button("WEATHER", self.fetch_weather, PANEL),
                                 self._button("SIMBRIEF", self.import_simbrief, PANEL),
                                 self._button("GPX", self.copy_gpx, PANEL)))
        self.profile = ProfileView(size_hint_y=None, height=dp(110))
        box.add_widget(self.profile)
        sv, self.plan_out = self._scroll_label(size="11sp")
        self.plan_out.text = "Enter two ICAO codes and tap GENERATE."
        box.add_widget(sv)
        return box

    def _set_plan_text(self, text):
        Clock.schedule_once(lambda *_: setattr(self.plan_out, "text", text), 0)

    def generate_plan(self, *_):
        o = pc.lookup_airport(self.in_orig.text)
        d = pc.lookup_airport(self.in_dest.text)
        if not o or not d:
            self.plan_out.text = ("Airport not in the built-in database. Use one of the listed ICAO codes "
                                  "or import a SimBrief plan.")
            return
        digits = re.sub(r"\D", "", self.in_fl.text)
        points = [(o["lat"], o["lon"]), (d["lat"], d["lon"])]
        plan = pc.plan_flight(points, self.in_ac.text, int(digits) if digits else None)
        self.plan = {"origin": o["icao"], "dest": d["icao"], "plan": plan}
        self.plan_out.text = pc.format_plan(plan, o["icao"], d["icao"])
        self.profile.set_profile(pc.vertical_profile(plan))
        self.map.set_route(pc.great_circle_points(o["lat"], o["lon"], d["lat"], d["lon"], 50.0))
        self.atc.set_plan(o["icao"], d["icao"], plan["cruise_fl"])
        self.monitor.set_plan(o["icao"], d["icao"], (d["lat"], d["lon"]), plan["distance_nm"] - plan["tod_nm"])

    def fetch_weather(self, *_):
        codes = [c.strip().upper() for c in (self.in_orig.text, self.in_dest.text) if c.strip()]
        if not codes:
            self.plan_out.text = "Enter departure and/or arrival first."
            return
        self.plan_out.text = "Fetching METAR..."

        def work():
            lines = []
            for code in codes:
                try:
                    raw = pc.fetch_metar(code)
                    if raw:
                        self.metars[code] = raw
                        lines.append(raw)
                    else:
                        lines.append(code + ": no METAR returned")
                except Exception as e:
                    lines.append("%s: weather fetch failed (%s)" % (code, str(e)[:60]))
            self._set_plan_text("\n\n".join(lines))
        threading.Thread(target=work, daemon=True).start()

    def import_simbrief(self, *_):
        user = self.in_sb.text.strip()
        if not user:
            self.plan_out.text = "Enter your SimBrief username first."
            return
        self.plan_out.text = "Fetching latest SimBrief plan..."

        def work():
            try:
                o, d, route, dist = pc.fetch_simbrief(user)
            except Exception as e:
                self._set_plan_text("SimBrief import failed: " + str(e)[:100])
                return

            def apply(_dt):
                self.in_orig.text, self.in_dest.text = o, d
                self.generate_plan()
                self.plan_out.text += "\nSimBrief route: " + (route or "n/a") + "  (" + str(dist) + " NM)"
            Clock.schedule_once(apply, 0)
        threading.Thread(target=work, daemon=True).start()

    def copy_gpx(self, *_):
        if not self.plan:
            self.plan_out.text = "Generate a plan first."
            return
        o = pc.lookup_airport(self.plan["origin"])
        d = pc.lookup_airport(self.plan["dest"])
        gpx = pc.export_gpx("%s-%s" % (o["icao"], d["icao"]),
                            [(o["icao"], o["lat"], o["lon"]), (d["icao"], d["lat"], d["lon"])])
        try:
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(gpx)
            self.plan_out.text += "\nGPX route copied to clipboard."
        except Exception as e:
            self.plan_out.text += "\nClipboard unavailable: " + str(e)[:60]

    # ---------- ATC ----------
    def _build_atc(self):
        box = BoxLayout(orientation="vertical", padding=(dp(12), dp(8)), spacing=dp(6))
        self.in_call = self._input("Callsign", "N123AB")
        self.voice_btn = self._button("VOICE ON", self.toggle_voice, PANEL)
        box.add_widget(self._row(self.in_call, self._button("ATIS", lambda *_: self.send_atc("atis"), PANEL), self.voice_btn))
        self.com_active = self._label("COM1  ---.---", "12sp", GREEN, True)
        self.com_standby = self._input("Standby MHz")
        box.add_widget(self._row(self.com_active, self.com_standby, self._button("SWAP", self.swap_com, PANEL)))
        self.atc_scroll, self.atc_log = self._scroll_label(markup=True)
        self.atc_log.text = ("[color=#9fb3c8]Simulation ATC. Type a request or use the buttons. "
                             "Fetch weather in PLAN first for wind and altimeter.[/color]")
        box.add_widget(self.atc_scroll)
        quick = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(4))
        for label, msg in (("CLEARANCE", "request IFR clearance"), ("TAXI", "request taxi"),
                           ("READY", "ready for departure"), ("INBOUND", "inbound for approach"),
                           ("LAND", "request landing")):
            b = Button(text=label, background_normal="", background_color=PANEL, color=TEXT, font_size="10sp")
            b.bind(on_press=lambda _b, m=msg: self.send_atc(m))
            quick.add_widget(b)
        box.add_widget(quick)
        self.atc_in = self._input("Type to ATC, e.g. 'runway 28L' or 'direct HKJK'")
        self.atc_in.bind(on_text_validate=lambda *_: self.send_atc(self.atc_in.text))
        box.add_widget(self._row(self.atc_in, self._button("MIC", self.mic, PANEL),
                                 self._button("SEND", lambda *_: self.send_atc(self.atc_in.text))))
        return box

    def _atc_append(self, who, text, color):
        line = "[color=%s][b]%s[/b][/color] %s" % (color, who, escape_markup(text))
        self.atc_log.text += "\n\n" + line
        Clock.schedule_once(lambda *_: setattr(self.atc_scroll, "scroll_y", 0), .05)

    def _get_llm(self):
        if self._llm_tried:
            return self._llm
        self._llm_tried = True
        try:
            from local_ai_agent import OfflineATCAgent
            self._llm = OfflineATCAgent(self.user_data_dir)
        except Exception:
            self._llm = None
        return self._llm

    def send_atc(self, text):
        text = (text or "").strip()
        if not text:
            return
        self.atc_in.text = ""
        self._atc_append("YOU", text, "#58a6ff")
        self.atc.set_callsign(self.in_call.text)
        icao = self.atc.dest if self.atc.phase in ("APPROACH", "LANDING") else self.atc.origin
        if icao in self.metars:
            self.atc.set_metar(icao, self.metars[icao])
        snap = self.telemetry.snapshot()

        def work():
            self.atc.llm = self._get_llm()
            try:
                reply = self.atc.handle(text, snap)
            except Exception as e:
                reply = "ATC error: " + str(e)[:80]
            if self.voice_on:
                self.voice.speak(reply)
            Clock.schedule_once(lambda *_: self._atc_append("ATC", reply, "#3fb950"), 0)
        threading.Thread(target=work, daemon=True).start()

    # ---------- ATC extras: voice, COM, flight events ----------
    def toggle_voice(self, *_):
        self.voice_on = not self.voice_on
        self.voice_btn.text = "VOICE ON" if self.voice_on else "VOICE OFF"

    def mic(self, *_):
        started = self.voice.listen(lambda text: Clock.schedule_once(lambda *_: self.send_atc(text), 0))
        if not started:
            self._atc_append("SYSTEM", "Speech input is not available on this device. Type your request instead.", "#d29922")

    def swap_com(self, *_):
        try:
            mhz = float(self.com_standby.text.strip())
        except ValueError:
            self.com_active.text = "COM1  invalid"
            return
        if not (118.0 <= mhz <= 136.975):
            self.com_active.text = "COM1  out of range"
            return
        self.com_active.text = "COM1  %.3f" % mhz
        self.com_standby.text = ""

    def _on_event(self, name):
        msg = self.atc.event(name)
        if not msg:
            return
        titles = {"takeoff": "AIRBORNE", "top_of_descent": "TOP OF DESCENT",
                  "approach": "APPROACHING DESTINATION", "landing": "LANDED - FLIGHT LOGGED"}
        self.alert.text = titles.get(name, name.upper())
        self.alert_until = time.time() + 20
        self._atc_append("ATC", msg, "#3fb950")
        if self.voice_on:
            self.voice.speak(msg)
        if name == "landing":
            self.logbook_label.text = self.logbook.summary()

    # ---------- TOOLS: checklists, logbook, notes ----------
    def _build_tools(self):
        box = BoxLayout(orientation="vertical", padding=(dp(12), dp(8)), spacing=dp(6))
        tabs = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(4))
        for name in ("CHECKLISTS", "LOGBOOK", "NOTES"):
            b = Button(text=name, background_normal="", background_color=PANEL, color=TEXT, font_size="11sp", bold=True)
            b.bind(on_press=lambda _b, n=name: self.show_tool(n))
            tabs.add_widget(b)
        box.add_widget(tabs)
        self.tool_body = BoxLayout()
        box.add_widget(self.tool_body)

        chk = BoxLayout(orientation="vertical", spacing=dp(6))
        self.chk_spinner = Spinner(text="BEFORE START", values=list(CHECKLISTS.keys()), size_hint_y=None,
                                   height=dp(44), background_normal="", background_color=BLUE, color=TEXT)
        self.chk_spinner.bind(text=lambda *_: self._fill_checklist())
        chk.add_widget(self.chk_spinner)
        sv = ScrollView(do_scroll_x=False)
        self.chk_grid = GridLayout(cols=1, spacing=dp(4), size_hint_y=None)
        self.chk_grid.bind(minimum_height=self.chk_grid.setter("height"))
        sv.add_widget(self.chk_grid)
        chk.add_widget(sv)
        chk.add_widget(self._label("Generic airliner-style items. Use your aircraft's own checklist for real procedures.",
                                   "9sp", MUTED))
        self._fill_checklist()

        lg, self.logbook_label = self._scroll_label(size="11sp")
        self.logbook_label.text = self.logbook.summary()

        self.notes = TextInput(hint_text="Scratchpad: clearances, frequencies, notes...", background_normal="",
                               background_active="", background_color=PANEL, foreground_color=TEXT,
                               hint_text_color=MUTED, cursor_color=TEXT, padding=(dp(12), dp(12)))
        self._notes_path = os.path.join(self.user_data_dir, "scratch.txt")
        try:
            with open(self._notes_path, "r", encoding="utf-8") as f:
                self.notes.text = f.read()
        except OSError:
            pass
        self.notes.bind(text=lambda _w, v: self._save_notes(v))
        self.tool_panels = {"CHECKLISTS": chk, "LOGBOOK": lg, "NOTES": self.notes}
        self.show_tool("CHECKLISTS")
        return box

    def _save_notes(self, value):
        try:
            with open(self._notes_path, "w", encoding="utf-8") as f:
                f.write(value)
        except OSError:
            pass

    def _fill_checklist(self):
        self.chk_grid.clear_widgets()
        for item in CHECKLISTS.get(self.chk_spinner.text, []):
            self.chk_grid.add_widget(ToggleButton(text=item, size_hint_y=None, height=dp(44), background_normal="",
                                                  background_down="", background_color=PANEL, color=TEXT,
                                                  font_size="12sp"))

    def show_tool(self, name):
        self.tool_body.clear_widgets()
        if name == "LOGBOOK":
            self.logbook_label.text = self.logbook.summary()
        self.tool_body.add_widget(self.tool_panels[name])

    # ---------- LINK ----------
    def _build_link(self):
        panel = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
        panel.add_widget(self._label("SIMULATOR CONNECTION", "16sp", TEXT, True))
        self.ip = self._input("Simulator device IPv4 address", self.telemetry.host)
        panel.add_widget(self._label("SIMULATOR IPv4", "10sp", MUTED, True))
        panel.add_widget(self.ip)
        panel.add_widget(self._button("CONNECT / RETRY", self.connect))
        self.cap_btn = self._button("START RAW CAPTURE", self.toggle_capture, PANEL)
        panel.add_widget(self.cap_btn)
        self.link_detail = self._label("TCP 58585  /  UDP 49002, 40092", "10sp", MUTED)
        panel.add_widget(self.link_detail)
        sv, help_label = self._scroll_label(size="11sp")
        help_label.color = MUTED
        help_label.text = (
            "METHOD A - same as FSWidgets (TCP 58585)\n"
            "1. Aerofly: Settings > Miscellaneous > turn ON 'Send flight data to FSWidgets Apps'. No Broadcast options needed.\n"
            "2. Enter the IPv4 address of the device running Aerofly above (this device's own address if Aerofly runs here), then CONNECT.\n\n"
            "METHOD B - UDP broadcast (port 49002)\n"
            "1. Aerofly: Miscellaneous > turn ON 'Broadcast flight info to IP address'.\n"
            "2. Set 'Broadcast IP address' to the IPv4 address of the device running THIS app, and 'Broadcast IP port' to 49002.\n\n"
            "Same device? Use split-screen or a floating window so Android keeps this app's network alive while Aerofly runs. "
            "Nothing arriving? Tap START RAW CAPTURE, fly for a minute, then share fsw_capture.txt.")
        panel.add_widget(sv)
        return panel

    def connect(self, *_):
        self.telemetry.set_host(self.ip.text)
        with self.telemetry.lock:
            self.telemetry.data["message"] = "Trying TCP %s:%d; UDP listeners active" % (
                self.ip.text.strip(), self.telemetry.TCP_PORT)
        if not self.telemetry.running:
            self.telemetry.start()

    def toggle_capture(self, *_):
        if self.telemetry.capture_path:
            self.telemetry.stop_capture()
            self.cap_btn.text = "START RAW CAPTURE"
            self.link_detail.text = "Capture stopped. File: " + os.path.join(self.user_data_dir, "fsw_capture.txt")
        else:
            path = os.path.join(self.user_data_dir, "fsw_capture.txt")
            self.telemetry.start_capture(path)
            self.cap_btn.text = "STOP RAW CAPTURE"
            self.link_detail.text = "Recording raw simulator bytes (max 64 KB) to " + path

    # ---------- refresh ----------
    def refresh(self, *_):
        d = self.telemetry.snapshot()
        self.state.text = "CONNECTED" if d["connected"] else "WAITING"
        self.state.color = GREEN if d["connected"] else MUTED
        self.status.text = d["message"] + " | " + d["transport"] + " | packets " + str(d["packets"])
        if d["lat"] is not None and d["lon"] is not None:
            self.map.set_position(d["lat"], d["lon"], d["heading"])
            self.metrics.text = "LAT %.5f  LON %.5f  ALT %.0f ft  GS %.0f kt  HDG %03.0f" % (
                d["lat"], d["lon"], d["alt_ft"], d["speed_kt"], d["heading"])
        else:
            self.metrics.text = "LAT --  LON --  ALT -- ft  GS -- kt  HDG ---"
        for name in self.monitor.update(d):
            self._on_event(name)
        if self.alert.text and time.time() > self.alert_until:
            self.alert.text = ""

    def on_stop(self):
        if hasattr(self, "telemetry"):
            self.telemetry.stop()
        if hasattr(self, "voice"):
            self.voice.shutdown()


if __name__ == "__main__":
    AeroflyATCApp().run()
