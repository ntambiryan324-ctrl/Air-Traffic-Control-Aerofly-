import os
import sys
import socket
import json
import threading
import time
import urllib.request
import urllib.error

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle


def load_env_file(filepath=".env"):
    """Loads environment variables from a local .env file if present."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        os.environ[key.strip()] = val.strip().strip('"').strip("'")
        except Exception as e:
            print(f"Error loading .env file: {e}")


load_env_file()


def call_groq_atc(prompt, system_prompt="You are an Air Traffic Controller providing concise, accurate aviation communications based on pilot requests and telemetry."):
    """Queries the Groq API using standard Python libraries to ensure mobile compatibility."""
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return "ERROR: GROQ_API_KEY is not configured."

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        return f"ATC Communications Error (HTTP {e.code}): {e.reason}"
    except Exception as e:
        return f"ATC Communications Error: {str(e)}"


class TelemetryReceiver:
    """Listens for UDP telemetry broadcast from flight simulators on port 49002."""
    def __init__(self, port=49002):
        self.port = port
        self.running = False
        self.latest_data = {
            "connected": False,
            "altitude": 0,
            "speed": 0,
            "heading": 0,
            "lat": 0.0,
            "lon": 0.0
        }
        self.socket = None

    def start(self):
        self.running = True
        thread = threading.Thread(target=self._listen, daemon=True)
        thread.start()

    def _listen(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(("", self.port))
            self.socket.settimeout(2.0)
            
            while self.running:
                try:
                    data, _ = self.socket.recvfrom(2048)
                    if data:
                        self.latest_data["connected"] = True
                        # Telemetry payload parsing can be extended per specific sim data format
                except socket.timeout:
                    self.latest_data["connected"] = False
        except Exception as e:
            print(f"Socket error: {e}")
        finally:
            if self.socket:
                self.socket.close()

    def stop(self):
        self.running = False


class MyFlightScreen(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=15, spacing=10, **kwargs)
        
        self.status_label = Label(text="Telemetry Status: Disconnected", size_hint_y=0.1, font_size="16sp", color=(1, 0.3, 0.3, 1))
        self.add_widget(self.status_label)

        grid = GridLayout(cols=2, spacing=10, size_hint_y=0.7)
        
        grid.add_widget(Label(text="Altitude (ft):", font_size="16sp"))
        self.alt_val = Label(text="0", font_size="16sp")
        grid.add_widget(self.alt_val)

        grid.add_widget(Label(text="Airspeed (kts):", font_size="16sp"))
        self.spd_val = Label(text="0", font_size="16sp")
        grid.add_widget(self.spd_val)

        grid.add_widget(Label(text="Heading (°):", font_size="16sp"))
        self.hdg_val = Label(text="000", font_size="16sp")
        grid.add_widget(self.hdg_val)

        grid.add_widget(Label(text="Latitude / Longitude:", font_size="16sp"))
        self.pos_val = Label(text="0.0000 / 0.0000", font_size="16sp")
        grid.add_widget(self.pos_val)

        self.add_widget(grid)

    def update_telemetry(self, data):
        if data["connected"]:
            self.status_label.text = "Telemetry Status: Connected (UDP 49002)"
            self.status_label.color = (0.3, 1, 0.3, 1)
        else:
            self.status_label.text = "Telemetry Status: Searching for Sim Telemetry..."
            self.status_label.color = (1, 0.7, 0.2, 1)

        self.alt_val.text = f"{data['altitude']:,}"
        self.spd_val.text = f"{data['speed']}"
        self.hdg_val.text = f"{data['heading']:03d}"
        self.pos_val.text = f"{data['lat']:.4f} / {data['lon']:.4f}"


class CommsScreen(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=15, spacing=10, **kwargs)

        self.add_widget(Label(text="ATC Transmission Log", size_hint_y=0.08, font_size="16sp"))
        
        self.atc_log = TextInput(readonly=True, multiline=True, size_hint_y=0.6, font_size="14sp")
        self.add_widget(self.atc_log)

        input_box = BoxLayout(orientation="horizontal", size_hint_y=0.15, spacing=10)
        self.pilot_input = TextInput(hint_text="Type transmission (e.g., 'Request taxi clearance to RWY 18')...", multiline=False)
        send_btn = Button(text="Transmit", size_hint_x=0.3)
        send_btn.bind(on_press=self.send_transmission)

        input_box.add_widget(self.pilot_input)
        input_box.add_widget(send_btn)
        self.add_widget(input_box)

    def send_transmission(self, instance):
        text = self.pilot_input.text.strip()
        if not text:
            return

        self.atc_log.text += f"\nPILOT: {text}\n"
        self.pilot_input.text = ""
        self.atc_log.text += "ATC: [Processing transmission...]\n"

        threading.Thread(target=self._process_atc, args=(text,), daemon=True).start()

    def _process_atc(self, prompt):
        response = call_groq_atc(prompt)
        Clock.schedule_once(lambda dt: self._append_atc_response(response))

    def _append_atc_response(self, response):
        lines = self.atc_log.text.split("\n")
        if lines and "Processing transmission" in lines[-2]:
            lines.pop(-2)
        self.atc_log.text = "\n".join(lines) + f"ATC: {response}\n"


class ScratchpadScreen(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=15, spacing=10, **kwargs)
        
        self.add_widget(Label(text="C.R.A.F.T. IFR Clearance Scratchpad", size_hint_y=0.08, font_size="16sp"))

        craft_grid = GridLayout(cols=2, spacing=10, size_hint_y=0.6)

        craft_grid.add_widget(Label(text="C - Clearance Limit:", font_size="14sp"))
        self.clearance_in = TextInput(multiline=False)
        craft_grid.add_widget(self.clearance_in)

        craft_grid.add_widget(Label(text="R - Route:", font_size="14sp"))
        self.route_in = TextInput(multiline=False)
        craft_grid.add_widget(self.route_in)

        craft_grid.add_widget(Label(text="A - Altitude:", font_size="14sp"))
        self.altitude_in = TextInput(multiline=False)
        craft_grid.add_widget(self.altitude_in)

        craft_grid.add_widget(Label(text="F - Frequency:", font_size="14sp"))
        self.freq_in = TextInput(multiline=False)
        craft_grid.add_widget(self.freq_in)

        craft_grid.add_widget(Label(text="T - Transponder (Squawk):", font_size="14sp"))
        self.squawk_in = TextInput(multiline=False)
        craft_grid.add_widget(self.squawk_in)

        self.add_widget(craft_grid)

        clear_btn = Button(text="Clear Scratchpad", size_hint_y=0.1)
        clear_btn.bind(on_press=self.clear_fields)
        self.add_widget(clear_btn)

    def clear_fields(self, instance):
        self.clearance_in.text = ""
        self.route_in.text = ""
        self.altitude_in.text = ""
        self.freq_in.text = ""
        self.squawk_in.text = ""


class AeroflyATCApp(App):
    def build(self):
        self.title = "AeroflyATC Companion"
        
        self.receiver = TelemetryReceiver()
        self.receiver.start()

        tab_panel = TabbedPanel(do_default_tab=False)

        # Tab 1: My Flight
        self.flight_screen = MyFlightScreen()
        tab_flight = TabbedPanelItem(text="My Flight")
        tab_flight.add_widget(self.flight_screen)
        tab_panel.add_widget(tab_flight)

        # Tab 2: Comms
        self.comms_screen = CommsScreen()
        tab_comms = TabbedPanelItem(text="Comms")
        tab_comms.add_widget(self.comms_screen)
        tab_panel.add_widget(tab_comms)

        # Tab 3: Scratchpad
        self.scratchpad_screen = ScratchpadScreen()
        tab_scratchpad = TabbedPanelItem(text="Scratchpad")
        tab_scratchpad.add_widget(self.scratchpad_screen)
        tab_panel.add_widget(tab_scratchpad)

        Clock.schedule_interval(self.update_ui, 1.0)
        return tab_panel

    def update_ui(self, dt):
        self.flight_screen.update_telemetry(self.receiver.latest_data)

    def on_stop(self):
        self.receiver.stop()


if __name__ == "__main__":
    AeroflyATCApp().run()

