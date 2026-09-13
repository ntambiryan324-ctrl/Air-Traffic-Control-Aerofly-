import json
import math
import os
import re
import socket
import threading
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget


TELEMETRY_PORT = 58585
APP_BG = (0.035, 0.055, 0.085, 1)
CARD = (0.065, 0.095, 0.135, 1)
CARD2 = (0.085, 0.12, 0.165, 1)
ACCENT = (0.10, 0.62, 0.95, 1)
GOOD = (0.15, 0.80, 0.48, 1)
TEXT = (0.90, 0.94, 0.98, 1)
MUTED = (0.56, 0.64, 0.73, 1)
WARN = (1.0, 0.67, 0.20, 1)


class Telemetry:
    """Dual Aerofly mobile receiver.

    1) FSWidgets stream: TCP 58585. The client connects to the simulator and
       sends the small HTTP-style wake-up request used by Aerofly mobile.
    2) ForeFlight-style broadcast: UDP 40092. Aerofly sends XGPS/XATT lines
       containing position and attitude data.

    Both feeds use the same XGPS/XATT sentence formats. The receivers are
    independent so either feed can update the flight state.
    """

    TCP_PORT = 58585
    UDP_PORT = 40092

    def __init__(self, tcp_host="127.0.0.1"):
        self.tcp_host = tcp_host.strip() or "127.0.0.1"
        self.data = {
            "connected": False,
            "tcp_connected": False,
            "udp_connected": False,
            "callsign": "UNKNOWN",
            "sim_name": "",
            "lat": 0.0,
            "lon": 0.0,
            "altitude": 0.0,
            "speed": 0.0,
            "heading": 0.0,
            "vertical_speed": 0.0,
            "pitch": 0.0,
            "bank": 0.0,
            "on_ground": True,
            "phase": "WAITING",
            "timestamp": 0.0,
            "source_ip": "",
            "transport": "NONE",
            "packets": 0,
            "last_error": "",
        }
        self.lock = threading.RLock()
        self.udp_sock = None
        self.tcp_sock = None
        self.running = False
        self.last_altitude = None
        self.last_altitude_time = None
        self.trail = []

    def start(self):
        if self.running:
            return True
        self.running = True
        threading.Thread(target=self._udp_loop, daemon=True).start()
        threading.Thread(target=self._tcp_loop, daemon=True).start()
        return True

    def set_tcp_host(self, host):
        host = str(host).strip() or "127.0.0.1"
        if host == self.tcp_host:
            return
        self.tcp_host = host
        self._close_tcp()

    def _udp_loop(self):
        while self.running:
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                except OSError:
                    pass
                sock.bind(("0.0.0.0", self.UDP_PORT))
                sock.settimeout(1.0)
                self.udp_sock = sock
                while self.running:
                    try:
                        raw, address = sock.recvfrom(65535)
                        self._consume(raw.decode("utf-8", errors="replace"), address[0], "UDP 40092")
                    except socket.timeout:
                        self._refresh_connection_flags()
                    except OSError:
                        break
                    except Exception as exc:
                        with self.lock:
                            self.data["last_error"] = str(exc)
            except OSError as exc:
                with self.lock:
                    self.data["last_error"] = "UDP 40092: " + str(exc)
                time.sleep(2)
            finally:
                try:
                    if sock:
                        sock.close()
                except OSError:
                    pass
                self.udp_sock = None

    def _tcp_loop(self):
        while self.running:
            sock = None
            try:
                sock = socket.create_connection((self.tcp_host, self.TCP_PORT), timeout=3.0)
                sock.settimeout(2.0)
                self.tcp_sock = sock
                with self.lock:
                    self.data["tcp_connected"] = True
                    self.data["last_error"] = ""
                # Aerofly mobile's FSWidgets endpoint expects the client to
                # initiate the connection before it starts streaming.
                sock.sendall(b"GET / HTTP/1.1\r\nHost: aerofly\r\nConnection: keep-alive\r\n\r\n")
                buffer = b""
                while self.running:
                    try:
                        chunk = sock.recv(8192)
                        if not chunk:
                            break
                        buffer += chunk
                        while b"\n" in buffer:
                            raw_line, buffer = buffer.split(b"\n", 1)
                            self._consume(raw_line.decode("utf-8", errors="replace"), self.tcp_host, "TCP 58585")
                    except socket.timeout:
                        self._refresh_connection_flags()
            except (OSError, socket.timeout) as exc:
                with self.lock:
                    self.data["tcp_connected"] = False
                    self.data["last_error"] = "TCP 58585: " + str(exc)
                time.sleep(2)
            finally:
                try:
                    if sock:
                        sock.close()
                except OSError:
                    pass
                self.tcp_sock = None
                with self.lock:
                    self.data["tcp_connected"] = False
                time.sleep(0.5)

    def _consume(self, text, source_ip, transport):
        # TCP may contain HTTP headers before the Aerofly stream.
        for line in text.replace("\r", "").split("\n"):
            line = line.strip()
            if not line or line.startswith("HTTP/") or ":" in line and not line.startswith(("XGPS", "XATT")):
                continue
            try:
                if line.startswith("XGPS"):
                    self._parse_xgps(line, source_ip, transport)
                elif line.startswith("XATT"):
                    self._parse_xatt(line, source_ip, transport)
            except (ValueError, IndexError):
                continue

    def _parse_xgps(self, line, source_ip, transport):
        # XGPS<sim>,lon,lat,alt_msl_m,track_true_deg,groundspeed_mps
        parts = line[4:].strip().split(",")
        if len(parts) < 6:
            return
        sim_name = parts[0].strip()
        lon = float(parts[1])
        lat = float(parts[2])
        altitude_ft = float(parts[3]) * 3.280839895
        speed_kt = float(parts[5]) * 1.943844492
        track = float(parts[4]) % 360.0
        now = time.time()
        with self.lock:
            if self.last_altitude is not None and self.last_altitude_time:
                dt = now - self.last_altitude_time
                if 0.05 < dt < 5.0:
                    self.data["vertical_speed"] = (altitude_ft - self.last_altitude) / dt * 60.0
            self.last_altitude = altitude_ft
            self.last_altitude_time = now
            self.data.update({
                "lat": lat, "lon": lon, "altitude": altitude_ft,
                "speed": speed_kt, "heading": track,
                "sim_name": sim_name, "source_ip": source_ip,
                "transport": transport, "connected": True,
                "timestamp": now, "packets": self.data["packets"] + 1,
            })
            self.data["on_ground"] = altitude_ft < 50 and abs(self.data["vertical_speed"]) < 600
            self.data["phase"] = self._phase(self.data)
            self.trail.append((lat, lon))
            if len(self.trail) > 600:
                del self.trail[:-600]

    def _parse_xatt(self, line, source_ip, transport):
        # XATT<sim>,true_heading,pitch_deg,roll_deg
        parts = line[4:].strip().split(",")
        if len(parts) < 4:
            return
        sim_name = parts[0].strip()
        heading, pitch, bank = float(parts[1]), float(parts[2]), float(parts[3])
        with self.lock:
            self.data.update({
                "heading": heading % 360.0,
                "pitch": pitch,
                "bank": bank,
                "sim_name": sim_name,
                "source_ip": source_ip,
                "transport": transport,
                "connected": True,
                "timestamp": time.time(),
                "packets": self.data["packets"] + 1,
            })
            self.data["phase"] = self._phase(self.data)

    def _refresh_connection_flags(self):
        with self.lock:
            stale = time.time() - self.data["timestamp"] > 5
            self.data["connected"] = not stale and (self.data["tcp_connected"] or self.data["udp_connected"])

    @staticmethod
    def _phase(d):
        if not d.get("connected"):
            return "WAITING"
        alt = float(d.get("altitude", 0))
        vs = float(d.get("vertical_speed", 0))
        if d.get("on_ground", False):
            return "GROUND"
        if alt < 1500 and vs > 200:
            return "DEPARTURE"
        if vs < -300 and alt < 10000:
            return "APPROACH"
        return "CRUISE"

    def snapshot(self):
        with self.lock:
            result = dict(self.data)
            result["tcp_host"] = self.tcp_host
            return result

    def trail_snapshot(self):
        with self.lock:
            return list(self.trail)

    def _close_tcp(self):
        sock = self.tcp_sock
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def stop(self):
        self.running = False
        self._close_tcp()
        if self.udp_sock:
            try:
                self.udp_sock.close()
            except OSError:
                pass


class Copilot:
    def __init__(self):
        self.afk = False
        self.clearance = {}
        self.last_phase = None
        self.messages = []

    def observe_atc(self, text, controller="ATC", frequency=""):
        text = str(text).strip()
        if not text:
            return
        self.clearance = {"raw": text, "controller": controller, "frequency": frequency}
        low = text.lower()
        match = re.search(r"\b([0-7]{4})\b", text) if "squawk" in low else None
        if match:
            self.clearance["squawk"] = match.group(1)
        match = re.search(r"heading\s+(?:of\s+)?(\d{1,3})", low)
        if match:
            self.clearance["heading"] = int(match.group(1)) % 360
        match = re.search(r"flight level\s+(\d{2,3})", low)
        if match:
            self.clearance["altitude_ft"] = int(match.group(1)) * 100
        else:
            match = re.search(r"(?:climb|descend)(?: and maintain)?\s+(\d{3,5})", low)
            if match:
                self.clearance["altitude_ft"] = int(match.group(1))

    def monitor(self, data):
        phase = data.get("phase")
        if phase != self.last_phase:
            self.last_phase = phase
            return "Flight phase: " + str(phase)
        target = self.clearance.get("altitude_ft")
        if target and data.get("connected") and abs(float(data.get("altitude", 0)) - target) > 300:
            return "Altitude deviation from last assigned altitude"
        heading = self.clearance.get("heading")
        if heading is not None and data.get("connected"):
            delta = abs((float(data.get("heading", 0)) - heading + 180) % 360 - 180)
            if delta > 20:
                return "Heading deviation from last assigned heading"
        return None


class FlightOps:
    @staticmethod
    def tod_nm(altitude, target, groundspeed, descent_fpm=1500):
        delta = max(0.0, float(altitude) - float(target))
        if delta <= 0 or groundspeed <= 20:
            return None
        return float(groundspeed) * (delta / descent_fpm) / 60.0

    @staticmethod
    def approach_status(d):
        if not d.get("connected") or d.get("on_ground"):
            return "NO APPROACH DATA"
        issues = []
        if float(d.get("vertical_speed", 0)) < -1200:
            issues.append("HIGH SINK")
        if float(d.get("speed", 0)) > 190 and float(d.get("altitude", 0)) < 3000:
            issues.append("FAST BELOW 3000"
)
        return "STABLE" if not issues else "UNSTABLE: " + ", ".join(issues)


class Card(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(padding=dp(12), spacing=dp(8), **kwargs)
        with self.canvas.before:
            Color(*CARD)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_bg, size=self._sync_bg)

    def _sync_bg(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size


class TitleBar(BoxLayout):
    def __init__(self, title, subtitle="", **kwargs):
        super().__init__(orientation="vertical", size_hint_y=None, height=dp(68), padding=(dp(14), dp(8)), **kwargs)
        self.add_widget(Label(text=title, color=TEXT, font_size="22sp", bold=True, halign="left"))
        if subtitle:
            self.add_widget(Label(text=subtitle, color=MUTED, font_size="12sp", halign="left"))


class Metric(BoxLayout):
    def __init__(self, label, value="—", **kwargs):
        super().__init__(orientation="vertical", padding=(dp(10), dp(7)), **kwargs)
        self.add_widget(Label(text=label.upper(), color=MUTED, font_size="10sp"))
        self.value = Label(text=value, color=TEXT, font_size="18sp", bold=True)
        self.add_widget(self.value)


class MovingMap(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.data = {}
        self.trail = []
        self.bind(pos=lambda *_: self.redraw(), size=lambda *_: self.redraw())

    def update(self, data, trail):
        self.data = data
        self.trail = trail
        self.redraw()

    def redraw(self):
        self.canvas.clear()
        with self.canvas:
            Color(0.025, 0.06, 0.08, 1)
            Rectangle(pos=self.pos, size=self.size)
            Color(0.10, 0.20, 0.23, 0.7)
            for x in range(int(self.x), int(self.right), int(dp(50))):
                Line(points=[x, self.y, x, self.top], width=0.7)
            for y in range(int(self.y), int(self.top), int(dp(50))):
                Line(points=[self.x, y, self.right, y], width=0.7)

            lat = float(self.data.get("lat", 0))
            lon = float(self.data.get("lon", 0))
            if lat == 0 and lon == 0:
                Color(*MUTED)
                return

            def project(p):
                plat, plon = p
                scale = min(self.width, self.height) / 0.16
                return (
                    self.center_x + (plon - lon) * scale,
                    self.center_y + (plat - lat) * scale,
                )

            if len(self.trail) > 1:
                Color(0.15, 0.65, 0.95, 0.9)
                points = []
                for p in self.trail:
                    x, y = project(p)
                    if self.x - 100 < x < self.right + 100 and self.y - 100 < y < self.top + 100:
                        points.extend([x, y])
                if len(points) >= 4:
                    Line(points=points, width=2.0)

            px, py = self.center
            heading = math.radians(float(self.data.get("heading", 0)))
            size = dp(18)
            nose = (px + math.sin(heading) * size, py + math.cos(heading) * size)
            left = (px + math.sin(heading + 2.45) * size * 0.75, py + math.cos(heading + 2.45) * size * 0.75)
            right = (px + math.sin(heading - 2.45) * size * 0.75, py + math.cos(heading - 2.45) * size * 0.75)
            Color(*ACCENT)
            Line(points=[nose[0], nose[1], left[0], left[1], right[0], right[1], nose[0], nose[1]], width=2.4)
            Color(0.2, 0.7, 1, 0.22)
            Line(circle=(px, py, dp(55)), width=1.0)


class MyFlightScreen(Screen):
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        root = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        root.add_widget(TitleBar("MY FLIGHT", "Aerofly Flight Companion"))
        self.connection = Label(text="●  WAITING FOR AEROFLY", color=WARN, size_hint_y=None, height=dp(28))
        root.add_widget(self.connection)

        card = Card(orientation="vertical", size_hint_y=None, height=dp(118))
        row = BoxLayout()
        self.phase = Label(text="PARKED", color=ACCENT, font_size="22sp", bold=True)
        row.add_widget(self.phase)
        self.callsign = Label(text="UNKNOWN", color=TEXT, font_size="20sp", bold=True, halign="right")
        row.add_widget(self.callsign)
        card.add_widget(row)
        self.summary = Label(text="Enable Aerofly flight-data sharing to begin.", color=MUTED, halign="left")
        card.add_widget(self.summary)
        root.add_widget(card)

        metrics = GridLayout(cols=3, size_hint_y=None, height=dp(150), spacing=dp(7))
        self.alt = Metric("Altitude")
        self.spd = Metric("Speed")
        self.hdg = Metric("Heading")
        self.vs = Metric("V/S")
        self.pos = Metric("Position")
        self.tod = Metric("TOD")
        for item in (self.alt, self.spd, self.hdg, self.vs, self.pos, self.tod):
            metric_card = Card(orientation="vertical")
            metric_card.add_widget(item)
            metrics.add_widget(metric_card)
        root.add_widget(metrics)
        root.add_widget(Label(text="LIVE TELEMETRY  •  UDP 58585", color=MUTED, font_size="10sp", size_hint_y=None, height=dp(22)))
        self.add_widget(root)

    def refresh(self, d):
        connected = d.get("connected", False)
        self.connection.text = "●  AEROFLY CONNECTED" if connected else "●  WAITING FOR AEROFLY"
        self.connection.color = GOOD if connected else WARN
        self.phase.text = d.get("phase", "WAITING")
        self.callsign.text = d.get("callsign", "UNKNOWN")
        self.alt.value.text = "%.0f ft" % d.get("altitude", 0)
        self.spd.value.text = "%.0f kt" % d.get("speed", 0)
        self.hdg.value.text = "%03.0f°" % d.get("heading", 0)
        self.vs.value.text = "%+.0f fpm" % d.get("vertical_speed", 0)
        self.pos.value.text = "%.3f / %.3f" % (d.get("lat", 0), d.get("lon", 0))
        tod = FlightOps.tod_nm(d.get("altitude", 0), 3000, d.get("speed", 0))
        self.tod.value.text = "%.1f NM" % tod if tod is not None else "—"
        self.summary.text = "Source %s  •  %s packets" % (d.get("source_ip") or "unknown", d.get("packets", 0))


class MapScreen(Screen):
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        root = BoxLayout(orientation="vertical")
        root.add_widget(TitleBar("MAP", "Moving map • flight path • heading vector"))
        self.map = MovingMap()
        root.add_widget(self.map)
        self.map_label = Label(text="Waiting for position", color=TEXT, size_hint_y=None, height=dp(34))
        root.add_widget(self.map_label)
        self.add_widget(root)

    def refresh(self, d, trail):
        self.map.update(d, trail)
        if d.get("connected"):
            self.map_label.text = "%.5f  %.5f   •   %03.0f°   •   %.0f ft" % (
                d.get("lat", 0), d.get("lon", 0), d.get("heading", 0), d.get("altitude", 0))
        else:
            self.map_label.text = "Waiting for Aerofly telemetry on UDP 58585"


class CommsScreen(Screen):
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        root = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(8))
        root.add_widget(TitleBar("COMMS", "ATC • COPILOT • CABIN"))

        top = Card(size_hint_y=None, height=dp(54))
        top.add_widget(Label(text="COM1  118.000", color=TEXT, font_size="18sp", bold=True))
        afk = Button(text="COPILOT AFK: OFF", size_hint_x=None, width=dp(145))
        afk.bind(on_press=self.toggle_afk)
        self.afk_button = afk
        top.add_widget(afk)
        root.add_widget(top)

        self.chat = TextInput(readonly=True, multiline=True, text="ATC COMMS READY\n\nNo radio traffic received yet.", background_color=CARD, foreground_color=TEXT)
        root.add_widget(self.chat)

        compose = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(6))
        self.input = TextInput(hint_text="Type pilot transmission…", multiline=False)
        compose.add_widget(self.input)
        mic = Button(text="MIC", size_hint_x=None, width=dp(58))
        mic.bind(on_press=lambda *_: self.append("COPILOT", "Speech-to-text interface ready; Android microphone integration will be enabled in the next audio build."))
        compose.add_widget(mic)
        send = Button(text="SEND", size_hint_x=None, width=dp(68))
        send.bind(on_press=self.send)
        compose.add_widget(send)
        root.add_widget(compose)
        self.add_widget(root)

    def toggle_afk(self, *_):
        self.app_ref.copilot.afk = not self.app_ref.copilot.afk
        self.afk_button.text = "COPILOT AFK: %s" % ("ON" if self.app_ref.copilot.afk else "OFF")

    def send(self, *_):
        text = self.input.text.strip()
        if text:
            self.append("PILOT", text)
            self.input.text = ""
            self.app_ref.copilot.observe_atc(text, "SIMULATED ATC", "118.000")

    def append(self, speaker, text):
        self.chat.text += "\n\n%s\n%s" % (speaker, text)


class ScratchpadScreen(Screen):
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        root = BoxLayout(orientation="vertical", spacing=dp(7), padding=dp(8))
        root.add_widget(TitleBar("SCRATCHPAD", "Quick cockpit notes"))
        bar = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        save = Button(text="SAVE")
        save.bind(on_press=self.save)
        clear = Button(text="CLEAR")
        clear.bind(on_press=self.clear)
        bar.add_widget(save)
        bar.add_widget(clear)
        root.add_widget(bar)
        self.note = TextInput(multiline=True, hint_text="ATC clearance, squawk, frequencies, gates, reminders…", background_color=CARD, foreground_color=TEXT, cursor_color=ACCENT)
        root.add_widget(self.note)
        self.add_widget(root)
        Clock.schedule_once(lambda *_: self.load(), 0)

    def path(self):
        return os.path.join(self.app_ref.user_data_dir, "scratchpad.txt")

    def load(self):
        try:
            with open(self.path(), "r", encoding="utf-8") as f:
                self.note.text = f.read()
        except OSError:
            pass

    def save(self, *_):
        try:
            with open(self.path(), "w", encoding="utf-8") as f:
                f.write(self.note.text)
        except OSError:
            pass

    def clear(self, *_):
        self.note.text = ""
        self.save()


class ChecklistsScreen(Screen):
    AIRCRAFT = {
        "A320": "Airbus A320",
        "B738": "Boeing 737-800",
        "B77W": "Boeing 777-300ER",
        "B789": "Boeing 787-9",
        "C172": "Cessna 172",
        "DA40": "Diamond DA40",
        "E190": "Embraer E190",
        "AT43": "ATR 42",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation="vertical", spacing=dp(7), padding=dp(8))
        root.add_widget(TitleBar("CHECKLISTS", "Select an aircraft"))
        self.selector = TextInput(text="A320", multiline=False, size_hint_y=None, height=dp(45), hint_text="Aircraft code")
        root.add_widget(self.selector)
        self.info = TextInput(readonly=True, multiline=True, text="Checklist assets are loaded from assets/checklists/. Only licensed, public-domain or user-provided checklists should be added.", background_color=CARD, foreground_color=TEXT)
        root.add_widget(self.info)
        load = Button(text="LOAD CHECKLIST", size_hint_y=None, height=dp(48))
        load.bind(on_press=self.load_checklist)
        root.add_widget(load)
        self.add_widget(root)

    def load_checklist(self, *_):
        code = self.selector.text.strip().lower()
        filename = os.path.join("assets", "checklists", code + ".txt")
        try:
            with open(filename, "r", encoding="utf-8") as f:
                self.info.text = f.read()
        except OSError:
            name = self.AIRCRAFT.get(code.upper(), code.upper())
            self.info.text = "%s\n\nNo checklist asset installed.\nExpected: %s" % (name, filename)


class MoreScreen(Screen):
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        root = BoxLayout(orientation="vertical", spacing=dp(7), padding=dp(8))
        root.add_widget(TitleBar("MORE", "Connection and app settings"))
        card = Card(orientation="vertical", size_hint_y=None, height=dp(230))
        card.add_widget(Label(text="AEROFLY CONNECTION", color=TEXT, font_size="17sp", bold=True))
        card.add_widget(Label(text="UDP PORT  58585\n\nAerofly FS: Settings → Miscellaneous → Send flight data to FSWidgets apps\n\nPoint Aerofly at this tablet's IPv4 address and port 58585. Both apps can run side-by-side on the same Android tablet.\n\nThe receiver accepts Aerofly's XGPS/XATT plain-text stream.", color=MUTED, halign="left"))
        root.add_widget(card)
        self.status = Label(text="", color=MUTED)
        root.add_widget(self.status)
        self.add_widget(root)

    def refresh(self, d):
        self.status.text = "Receiver: %s   •   Source: %s   •   Packets: %s" % (
            "CONNECTED" if d.get("connected") else "WAITING",
            d.get("source_ip") or "—",
            d.get("packets", 0))


class AeroflyCompanion(App):
    def build(self):
        self.telemetry = Telemetry()
        self.copilot = Copilot()
        self.telemetry.start()

        manager = ScreenManager(transition=SlideTransition(duration=0.12))
        self.screens = {}
        for name, screen in (
            ("flight", MyFlightScreen(self, name="flight")),
            ("map", MapScreen(self, name="map")),
            ("comms", CommsScreen(self, name="comms")),
            ("scratch", ScratchpadScreen(self, name="scratch")),
            ("checklists", ChecklistsScreen(name="checklists")),
            ("more", MoreScreen(self, name="more")),
        ):
            self.screens[name] = screen
            manager.add_widget(screen)

        nav = BoxLayout(orientation="vertical")
        nav.add_widget(manager)
        bottom = BoxLayout(size_hint_y=None, height=dp(62), spacing=dp(3), padding=(dp(4), dp(4)))
        for name, label in (
            ("flight", "MY FLIGHT"),
            ("map", "MAP"),
            ("comms", "COMMS"),
            ("scratch", "SCRATCH"),
            ("checklists", "CHECKLISTS"),
            ("more", "MORE"),
        ):
            button = Button(text=label, background_normal="", background_color=CARD2, color=TEXT, font_size="10sp")
            button.bind(on_press=lambda _, n=name: self.go(n))
            bottom.add_widget(button)
        nav.add_widget(bottom)
        self.manager = manager
        Clock.schedule_interval(self.tick, 0.25)
        return nav

    def go(self, name):
        self.manager.current = name

    def tick(self, _dt):
        d = self.telemetry.snapshot()
        self.screens["flight"].refresh(d)
        self.screens["map"].refresh(d, self.telemetry.trail_snapshot())
        self.screens["more"].refresh(d)
        event = self.copilot.monitor(d)
        if event and self.copilot.afk:
            self.screens["comms"].append("COPILOT", event)

    def on_stop(self):
        self.telemetry.stop()


if __name__ == "__main__":
    AeroflyCompanion().run()
