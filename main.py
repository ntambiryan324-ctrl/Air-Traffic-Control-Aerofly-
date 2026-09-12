import json
import math
import os
import re
import socket
import threading
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput


TELEMETRY_PORT = 58585


class Telemetry:
    def __init__(self, port=TELEMETRY_PORT):
        self.port = port
        self.data = {
            "connected": False, "callsign": "UNKNOWN", "lat": 0.0, "lon": 0.0,
            "altitude": 0.0, "speed": 0.0, "heading": 0.0, "vertical_speed": 0.0,
            "on_ground": True, "phase": "PARKED", "timestamp": 0.0,
        }
        self.lock = threading.Lock()
        self.sock = None
        self.running = False

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", self.port))
            sock.settimeout(1.0)
            self.sock = sock
        except OSError:
            self.running = False
            return
        while self.running:
            try:
                raw, _ = sock.recvfrom(65535)
                payload = json.loads(raw.decode("utf-8"))
                if isinstance(payload, dict):
                    with self.lock:
                        self.data.update(payload)
                        self.data["timestamp"] = time.time()
                        self.data["connected"] = True
                        self.data["phase"] = self._phase(self.data)
            except socket.timeout:
                with self.lock:
                    if time.time() - self.data["timestamp"] > 5:
                        self.data["connected"] = False
            except (ValueError, UnicodeError, OSError):
                continue

    @staticmethod
    def _phase(d):
        if d.get("on_ground", True):
            return "GROUND"
        alt = float(d.get("altitude", 0))
        vs = float(d.get("vertical_speed", 0))
        if alt < 1500 and vs > 200:
            return "DEPARTURE"
        if vs < -300 and alt < 10000:
            return "APPROACH"
        return "CRUISE"

    def snapshot(self):
        with self.lock:
            return dict(self.data)


class Copilot:
    def __init__(self):
        self.afk = False
        self.clearance = {}
        self.events = []
        self.last_phase = None
        self.last_handoff = None

    def observe_atc(self, text, controller, frequency):
        text = str(text)
        self.clearance = {
            "raw": text, "controller": controller, "frequency": frequency,
            "time": time.time(),
        }
        low = text.lower()
        m = re.search(r"\b([0-7]{4})\b", text) if "squawk" in low else None
        if m:
            self.clearance["squawk"] = m.group(1)
        m = re.search(r"heading\s+(?:of\s+)?(\d{1,3})", low)
        if m:
            self.clearance["heading"] = int(m.group(1)) % 360
        m = re.search(r"flight level\s+(\d{2,3})", low)
        if m:
            self.clearance["altitude_ft"] = int(m.group(1)) * 100
        else:
            m = re.search(r"(?:climb|descend)(?: and maintain)?\s+(\d{3,5})", low)
            if m:
                self.clearance["altitude_ft"] = int(m.group(1))

    def monitor(self, d, controller, frequency):
        messages = []
        phase = d.get("phase")
        if phase != self.last_phase:
            self.last_phase = phase
            messages.append("Flight phase: %s" % phase)
        handoff = (controller, frequency)
        if handoff != self.last_handoff:
            self.last_handoff = handoff
            if d.get("connected"):
                messages.append("Now with %s on %s" % (controller, frequency))
        target = self.clearance.get("altitude_ft")
        if target and d.get("connected") and abs(float(d.get("altitude", 0)) - target) > 300:
            messages.append("Altitude deviation from last assigned altitude")
        heading = self.clearance.get("heading")
        if heading is not None and d.get("connected"):
            delta = abs((float(d.get("heading", 0)) - heading + 180) % 360 - 180)
            if delta > 20:
                messages.append("Heading deviation from last assigned heading")
        return messages


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
            issues.append("FAST BELOW 3000")
        return "STABLE" if not issues else "UNSTABLE: " + ", ".join(issues)

    @staticmethod
    def score(deviations, events):
        return max(0, 100 - min(100, deviations * 10 + events * 2))


class MainScreen(Screen):
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        root = BoxLayout(orientation="vertical", padding=8, spacing=6)
        self.status = Label(text="Aerofly Flight Companion", halign="left", valign="top")
        root.add_widget(self.status)

        controls = BoxLayout(size_hint_y=None, height=44, spacing=5)
        self.afk = Button(text="AFK COMMS: OFF")
        self.afk.bind(on_press=self.toggle_afk)
        controls.add_widget(self.afk)
        self.listen = Button(text="Telemetry: START")
        self.listen.bind(on_press=self.start_telemetry)
        controls.add_widget(self.listen)
        root.add_widget(controls)

        self.log = TextInput(readonly=True, multiline=True)
        root.add_widget(self.log)
        self.add_widget(root)

    def toggle_afk(self, _):
        self.app_ref.copilot.afk = not self.app_ref.copilot.afk
        self.afk.text = "AFK COMMS: %s" % ("ON" if self.app_ref.copilot.afk else "OFF")

    def start_telemetry(self, _):
        self.app_ref.telemetry.start()
        self.listen.text = "Telemetry: LISTENING"

    def add_log(self, text):
        self.log.text += "[%s] %s\n" % (time.strftime("%H:%M:%S"), text)


class EFBScreen(Screen):
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        root = BoxLayout(orientation="vertical", padding=8, spacing=6)
        self.info = Label(text="EFB / MOVING MAP\nWaiting for telemetry...")
        root.add_widget(self.info)
        self.add_widget(root)

    def refresh(self, d):
        self.info.text = (
            "EFB / FLIGHT FOLLOW\n"
            "Callsign: %s\nPosition: %.5f, %.5f\n"
            "Altitude: %.0f ft\nSpeed: %.0f kt\n"
            "Heading: %03.0f°\nPhase: %s\nTelemetry: %s"
        ) % (
            d.get("callsign", "UNKNOWN"), d.get("lat", 0), d.get("lon", 0),
            d.get("altitude", 0), d.get("speed", 0), d.get("heading", 0),
            d.get("phase", "UNKNOWN"), "CONNECTED" if d.get("connected") else "WAITING",
        )


class ChecklistScreen(Screen):
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
        root = BoxLayout(orientation="vertical", padding=8, spacing=6)
        self.selector = Spinner(text="Select aircraft", values=tuple(self.AIRCRAFT))
        self.selector.bind(text=self.select)
        root.add_widget(self.selector)
        self.info = Label(text="Select an aircraft. Licensed/public-domain checklist assets may be placed in assets/checklists/.")
        root.add_widget(self.info)
        self.add_widget(root)

    def select(self, _, aircraft):
        if aircraft == "Select aircraft":
            return
        filename = os.path.join("assets", "checklists", aircraft.lower() + ".txt")
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as handle:
                self.info.text = handle.read()
        else:
            self.info.text = (
                "%s\n\nNo checklist asset installed.\n"
                "Add a licensed/public-domain checklist as %s."
            ) % (self.AIRCRAFT[aircraft], filename)


class ExperienceScreen(Screen):
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        root = BoxLayout(orientation="vertical", padding=8, spacing=6)
        self.info = Label(text="Flight Experience")
        root.add_widget(self.info)
        buttons = BoxLayout(size_hint_y=None, height=44, spacing=5)
        tod = Button(text="TOD")
        tod.bind(on_press=self.tod)
        approach = Button(text="APPROACH")
        approach.bind(on_press=self.approach)
        buttons.add_widget(tod)
        buttons.add_widget(approach)
        root.add_widget(buttons)
        self.add_widget(root)

    def tod(self, _):
        d = self.app_ref.telemetry.snapshot()
        value = FlightOps.tod_nm(d["altitude"], 3000, d["speed"])
        self.info.text = "TOD: %.1f NM to 3,000 ft" % value if value is not None else "TOD unavailable"

    def approach(self, _):
        self.info.text = "APPROACH: " + FlightOps.approach_status(self.app_ref.telemetry.snapshot())


class AeroflyCompanion(App):
    def build(self):
        self.telemetry = Telemetry()
        self.copilot = Copilot()
        manager = ScreenManager()
        main = MainScreen(self, name="main")
        self.efb = EFBScreen(self, name="efb")
        checklist = ChecklistScreen(name="checklists")
        experience = ExperienceScreen(self, name="experience")
        manager.add_widget(main)
        manager.add_widget(self.efb)
        manager.add_widget(checklist)
        manager.add_widget(experience)
        Clock.schedule_interval(self.tick, 0.5)
        return manager

    def tick(self, _dt):
        d = self.telemetry.snapshot()
        messages = self.copilot.monitor(d, "GROUND", "118.000")
        if messages:
            self.root.get_screen("main").add_log("COPILOT: " + " | ".join(messages))
        self.efb.refresh(d)

    def on_stop(self):
        self.telemetry.running = False
        if self.telemetry.sock:
            try:
                self.telemetry.sock.close()
            except OSError:
                pass


if __name__ == "__main__":
    AeroflyCompanion().run()
