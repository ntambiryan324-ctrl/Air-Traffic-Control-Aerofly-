import os
import math
import re
import socket
import threading
import time
import urllib.request
from io import BytesIO

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Line, Ellipse, Triangle, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

BG = (0.035, 0.055, 0.075, 1)
PANEL = (0.075, 0.10, 0.13, 1)
TEXT = (0.92, 0.95, 0.98, 1)
MUTED = (0.62, 0.70, 0.77, 1)
GREEN = (0.16, 0.85, 0.48, 1)
BLUE = (0.18, 0.58, 0.95, 1)


def tile_xy(lat, lon, zoom):
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat = max(-85.0511, min(85.0511, lat))
    rad = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(rad)) / math.pi) / 2.0 * n
    return x, y


class MovingMap(Widget):
    """Offline-rendered aviation globe. No tile server or network map dependency."""
    AIRPORTS = [
        ("HKJK", -1.32, 36.93), ("HUEN", 0.04, 32.44), ("HTDA", -6.88, 39.20),
        ("HAAB", 8.98, 38.80), ("HECA", 30.12, 31.41), ("OERK", 24.96, 46.70),
        ("OMDB", 25.25, 55.36), ("VABB", 19.09, 72.87), ("VIDP", 28.56, 77.10),
        ("WSSS", 1.36, 103.99), ("RJTT", 35.55, 139.78), ("ZBAA", 40.08, 116.58),
        ("EGLL", 51.47, -0.45), ("LFPG", 49.01, 2.55), ("EDDF", 50.03, 8.57),
        ("EHAM", 52.31, 4.76), ("LEMD", 40.47, -3.56), ("LIRF", 41.80, 12.25),
        ("KJFK", 40.64, -73.78), ("KLAX", 33.94, -118.41), ("KSFO", 37.62, -122.38),
        ("CYYZ", 43.68, -79.63), ("SBGR", -23.43, -46.47), ("FAOR", -26.13, 28.24),
        ("FACT", -33.97, 18.60), ("DNMM", 6.58, 3.32), ("GOBD", 14.74, -17.49),
        ("LPPT", 38.77, -9.13), ("LOWW", 48.11, 16.57), ("LTFM", 41.28, 28.75),
        ("UUDD", 55.41, 37.91), ("YSSY", -33.95, 151.18), ("NZAA", -37.01, 174.79),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.lat, self.lon, self.heading = 0.0, 20.0, 0.0
        self.has_aircraft_position = False
        self.follow = True
        self.zoom = 1.0
        self.drag_origin = None
        self.bind(pos=lambda *_: self.redraw(), size=lambda *_: self.redraw())

    def set_position(self, lat, lon, heading):
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return
        first = not self.has_aircraft_position
        self.has_aircraft_position = True
        self.lat, self.lon, self.heading = lat, lon, heading
        if first:
            self.follow = True
        self.redraw()

    def pan(self, dx, dy):
        self.follow = False
        self.lon = ((self.lon - dx * 0.55) + 180) % 360 - 180
        self.lat = max(-75, min(75, self.lat + dy * 0.35))
        self.redraw()

    def zoom_by(self, amount):
        self.zoom = max(0.75, min(1.5, self.zoom + amount * 0.12))
        self.redraw()

    def center_plane(self):
        self.follow = True
        self.redraw()

    def _project(self, lat, lon, cx, cy, radius):
        if self.follow and self.has_aircraft_position:
            center_lat, center_lon = self.lat, self.lon
        else:
            center_lat, center_lon = 12.0, 20.0
        p1, p2 = math.radians(lat), math.radians(center_lat)
        dl = math.radians((lon - center_lon + 180) % 360 - 180)
        cosc = math.sin(p2)*math.sin(p1) + math.cos(p2)*math.cos(p1)*math.cos(dl)
        if cosc < -0.03:
            return None
        x = radius * math.cos(p1) * math.sin(dl)
        y = radius * (math.cos(p2)*math.sin(p1) - math.sin(p2)*math.cos(p1)*math.cos(dl))
        return cx+x, cy+y

    def redraw(self):
        self.canvas.clear()
        if self.width < 2 or self.height < 2:
            return
        with self.canvas:
            Color(0.018, 0.025, 0.040, 1)
            Rectangle(pos=self.pos, size=self.size)
            radius = min(self.width * 0.46, self.height * 0.47) * self.zoom
            cx, cy = self.center
            # Sphere body and subtle atmospheric rim.
            Color(0.16, 0.26, 0.34, 0.32)
            Ellipse(pos=(cx-radius-dp(4), cy-radius-dp(4)), size=(2*radius+dp(8),2*radius+dp(8)))
            Color(0.025, 0.055, 0.085, 1)
            Ellipse(pos=(cx-radius, cy-radius), size=(2*radius,2*radius))
            # Latitude and longitude graticule.
            Color(0.30, 0.43, 0.52, 0.42)
            for factor in (-0.8, -0.55, -0.28, 0.0, 0.28, 0.55, 0.8):
                yy = cy + radius*factor
                half = radius*math.sqrt(max(0,1-factor*factor))
                Line(points=[cx-half,yy,cx+half,yy],width=0.65)
                xx = cx + radius*factor
                halfy = radius*math.sqrt(max(0,1-factor*factor))
                Line(points=[xx,cy-halfy,xx,cy+halfy],width=0.65)
            projected = {}
            for code, lat, lon in self.AIRPORTS:
                point = self._project(lat, lon, cx, cy, radius)
                if point:
                    projected[code] = point
            # Schematic airway network connecting visible airports.
            routes = [
                ("HKJK","HUEN"),("HKJK","HAAB"),("HAAB","HECA"),("HECA","OERK"),
                ("OERK","OMDB"),("OMDB","VABB"),("VABB","VIDP"),("VIDP","WSSS"),
                ("WSSS","RJTT"),("WSSS","ZBAA"),("EGLL","LFPG"),("EGLL","EDDF"),
                ("EDDF","EHAM"),("LFPG","LIRF"),("LEMD","LPPT"),("LOWW","LTFM"),
                ("LTFM","OMDB"),("KJFK","CYYZ"),("KJFK","EGLL"),("KLAX","KSFO"),
                ("KJFK","KLAX"),("SBGR","DNMM"),("DNMM","GOBD"),("GOBD","LPPT"),
                ("FAOR","FACT"),("FAOR","HKJK"),("YSSY","NZAA"),("RJTT","YSSY"),
                ("HUEN","DNMM"),("HAAB","FAOR"),("EDDF","UUDD"),("OMDB","WSSS"),
            ]
            Color(0.22, 0.43, 0.70, 0.72)
            for a,b in routes:
                if a in projected and b in projected:
                    Line(points=[*projected[a],*projected[b]],width=0.75)
            for code, point in projected.items():
                x,y = point
                Color(0.15,0.58,0.96,0.95)
                Ellipse(pos=(x-dp(2),y-dp(2)),size=(dp(4),dp(4)))
            # Labels are kept sparse and readable at tablet scale.
            for code in ("HKJK","HUEN","HAAB","HECA","OERK","OMDB","VABB","VIDP",
                         "EGLL","LFPG","EDDF","EHAM","KJFK","KLAX","RJTT","WSSS",
                         "FAOR","DNMM","LTFM","YSSY","SBGR","LOWW"):
                if code in projected:
                    x,y=projected[code]
                    Color(0.33,0.66,0.98,1)
                    # Small ticks are used instead of text inside the canvas; labels below
                    # are rendered by the app overlay for crisp scalable type.
                    Line(points=[x-dp(3),y,x+dp(3),y],width=1.2)
            # Aircraft marker at its geographic location on the globe.
            if self.has_aircraft_position:
                plane = self._project(self.lat,self.lon,cx,cy,radius)
                if plane:
                    x,y=plane
                    Color(0.05,0.95,0.66,0.18)
                    Ellipse(pos=(x-dp(12),y-dp(12)),size=(dp(24),dp(24)))
                    Color(0.18,1.0,0.70,1)
                    Ellipse(pos=(x-dp(4),y-dp(4)),size=(dp(8),dp(8)))
                    Color(0.88,1.0,0.96,1)
                    Line(points=[x,y,x+math.sin(math.radians(self.heading))*dp(22),
                                 y+math.cos(math.radians(self.heading))*dp(22)],width=2)
            # Top and bottom HUD markers.
            Color(0.15,0.68,1,0.85)
            Line(points=[cx-dp(8),cy,cx+dp(8),cy],width=0.7)
            Line(points=[cx,cy-dp(8),cx,cy+dp(8)],width=0.7)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._drag_last = touch.pos
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if getattr(self, "_drag_last", None) and self.collide_point(*touch.pos):
            oldx, oldy = self._drag_last
            self.pan(touch.x-oldx, touch.y-oldy)
            self._drag_last = touch.pos
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        self._drag_last = None
        return super().on_touch_up(touch)


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
        self.data = {"connected": False, "transport": "WAITING", "lat": None, "lon": None,
                     "alt_ft": 0.0, "speed_kt": 0.0, "heading": 0.0, "pitch": 0.0,
                     "bank": 0.0, "sim": "", "packets": 0, "last_packet": 0.0,
                     "message": "Enter simulator IP, then tap CONNECT"}

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
            try: s.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            try: s.close()
            except OSError: pass

    def _parse(self, raw, transport, source):
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        # Aerofly/FSWidgets streams may delimit records with CR, LF, or CRLF.
        for line in re.split(r"[\r\n]+", text):
            line=line.strip()
            try:
                if line.startswith("XGPS"):
                    p=line[4:].strip().split(",")
                    if len(p)<6: continue
                    with self.lock:
                        self.data.update({"sim":p[0].strip(),"lon":float(p[1]),"lat":float(p[2]),
                            "alt_ft":float(p[3])*3.280839895,"heading":float(p[4])%360,
                            "speed_kt":float(p[5])*1.943844492,"connected":True,
                            "transport":transport,"message":"Telemetry received from "+source,
                            "last_packet":time.time(),"packets":self.data["packets"]+1})
                elif line.startswith("XATT"):
                    p=line[4:].strip().split(",")
                    if len(p)<4: continue
                    with self.lock:
                        self.data.update({"sim":p[0].strip(),"heading":float(p[1])%360,
                            "pitch":float(p[2]),"bank":float(p[3]),"connected":True,
                            "transport":transport,"message":"Telemetry received from "+source,
                            "last_packet":time.time(),"packets":self.data["packets"]+1})
            except (ValueError, IndexError):
                continue

    def _udp_loop(self):
        while self.running:
            opened=[]
            try:
                # Bind each UDP port independently so a port conflict does not disable the other.
                for port in self.UDP_PORTS:
                    try:
                        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                        s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                        s.bind(("0.0.0.0",port));s.settimeout(1)
                        opened.append((port,s))
                    except OSError:
                        try:s.close()
                        except Exception:pass
                if not opened:
                    with self.lock: self.data["message"]="UDP 49002/40092 unavailable (port already in use?)"
                    time.sleep(2);continue
                while self.running:
                    for port,s in opened:
                        try:
                            raw,addr=s.recvfrom(65535)
                            self._parse(raw,"UDP "+str(port),addr[0])
                        except socket.timeout: pass
                        except OSError: break
            finally:
                for _,s in opened:
                    try:s.close()
                    except OSError:pass
            time.sleep(.5)

    def _tcp_loop(self):
        while self.running:
            s=None
            requested_host=self.host
            connected_host=requested_host
            try:
                # On the same Android device, Aerofly may expose the service on loopback
                # or only on the device's active IPv4 interface. Try both automatically.
                # The official FSWidgets setup specifies the simulator device's local IP,
                # not 127.0.0.1. Try the active interface first, loopback second.
                candidates=[]
                detected=self.detect_local_ip()
                for candidate in (requested_host, detected, "127.0.0.1"):
                    if candidate and candidate not in candidates:
                        candidates.append(candidate)
                last_error=None
                for candidate in candidates:
                    with self.lock:
                        self.data["message"]=f"Connecting to {candidate}:{self.TCP_PORT}..."
                    try:
                        s=socket.create_connection((candidate,self.TCP_PORT),timeout=4)
                        connected_host=candidate
                        break
                    except OSError as e:
                        last_error=e
                if s is None:
                    raise last_error or OSError("No simulator address could be reached")
                s.settimeout(2)
                self.tcp=s
                s.sendall(b"GET / HTTP/1.1\r\n\r\n")
                with self.lock:
                    self.data["message"]=f"TCP connected at {connected_host}:{self.TCP_PORT}; waiting for telemetry"
                buf=b""
                while self.running and requested_host==self.host:
                    try:
                        chunk=s.recv(8192)
                        if not chunk:
                            break
                        buf+=chunk
                        # Accept CR, LF, or CRLF record separators. A CR-only stream
                        # must not sit forever in the buffer waiting for a newline.
                        buf=buf.replace(b"\r", b"\n")
                        while b"\n" in buf:
                            line,buf=buf.split(b"\n",1)
                            self._parse(line,"TCP 58585",connected_host)
                        # Some implementations send one complete XGPS/XATT record without
                        # a trailing newline. Parse it once enough fields are present.
                        if buf.startswith((b"XGPS", b"XATT")):
                            fields=buf.count(b",")
                            if (buf.startswith(b"XGPS") and fields >= 5) or (buf.startswith(b"XATT") and fields >= 3):
                                self._parse(buf,"TCP 58585",connected_host)
                                buf=b""
                    except socket.timeout:
                        if time.time()-self.data["last_packet"]>5:
                            with self.lock:
                                self.data["connected"]=False
                                self.data["message"]=f"TCP reachable at {connected_host}:{self.TCP_PORT}, but no telemetry received. Enable Send flight data to FSWidgets Apps in Aerofly."
            except OSError as e:
                with self.lock:
                    self.data["connected"]=False
                    self.data["message"]=f"TCP {self.TCP_PORT} failed: {e}. Check Aerofly FSWidgets setting and target IP."
                time.sleep(2)
            finally:
                if s:
                    try:s.close()
                    except OSError:pass
                self.tcp=None
            time.sleep(1)

    def snapshot(self):
        with self.lock:
            d=dict(self.data)
        if time.time()-d["last_packet"]>5:
            d["connected"]=False
        return d

    def stop(self):
        self.running=False
        if self.tcp:
            try:self.tcp.close()
            except OSError:pass


class AeroflyATCApp(App):
    title = "Aerofly Telemetry Map"

    def build(self):
        self.telemetry=Telemetry()
        root=BoxLayout(orientation="vertical", spacing=dp(5), padding=dp(6))
        with root.canvas.before:
            Color(*BG)
            self.background = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=lambda w, *_: setattr(self.background, "pos", w.pos),
                  size=lambda w, *_: setattr(self.background, "size", w.size))
        head=BoxLayout(size_hint_y=None,height=dp(42),spacing=dp(5))
        head.add_widget(Label(text="AEROFLY TELEMETRY",bold=True,color=TEXT,font_size="17sp",halign="left"))
        self.state=Label(text="WAITING",color=MUTED,size_hint_x=None,width=dp(110),font_size="12sp")
        head.add_widget(self.state);root.add_widget(head)
        conn=BoxLayout(size_hint_y=None,height=dp(46),spacing=dp(4))
        self.ip=TextInput(text="127.0.0.1",hint_text="Aerofly device IPv4",multiline=False,
                          size_hint_x=0.62,background_color=PANEL,foreground_color=TEXT,
                          cursor_color=TEXT)
        conn.add_widget(self.ip)
        b=Button(text="CONNECT / RETRY",size_hint_x=0.38,background_normal="",background_color=BLUE,color=TEXT)
        b.bind(on_press=self.connect);conn.add_widget(b);root.add_widget(conn)
        map_box=BoxLayout(orientation="vertical", spacing=0, size_hint_y=0.72)
        self.map=MovingMap()
        map_box.add_widget(self.map)
        self.map_note=Label(text="Loading global OpenStreetMap… • © OpenStreetMap contributors",
                            size_hint_y=None, height=dp(20), font_size="10sp", color=MUTED,
                            halign="right", valign="middle")
        self.map_note.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        map_box.add_widget(self.map_note)
        root.add_widget(map_box)
        controls=BoxLayout(size_hint_y=None,height=dp(42),spacing=dp(4))
        for label,fn in (("−",lambda *_:self.map.zoom_by(-1)),("+",lambda *_:self.map.zoom_by(1)),
                         ("FOLLOW",lambda *_:self.map.center_plane())):
            b=Button(text=label,background_normal="",background_color=PANEL,color=TEXT)
            b.bind(on_press=fn);controls.add_widget(b)
        root.add_widget(controls)
        self.status=Label(text="Map starting • enable Aerofly Settings > Miscellaneous > Send flight data to FSWidgets Apps",
                          color=MUTED,size_hint_y=None,height=dp(38),font_size="10sp")
        root.add_widget(self.status)
        self.metrics=Label(text="LAT --  LON --  ALT -- ft  GS -- kt  HDG ---°",
                           color=TEXT,size_hint_y=None,height=dp(28),font_size="11sp")
        root.add_widget(self.metrics)
        Clock.schedule_once(lambda *_:self.telemetry.start(),.3)
        Clock.schedule_interval(self.refresh,.5)
        return root

    def connect(self,*_):
        self.telemetry.set_host(self.ip.text)
        with self.telemetry.lock:
            self.telemetry.data["message"]=f"Trying TCP {self.ip.text.strip()}:{self.telemetry.TCP_PORT}; UDP listeners active"
        if not self.telemetry.running:self.telemetry.start()

    def refresh(self,*_):
        d=self.telemetry.snapshot()
        self.state.text="CONNECTED" if d["connected"] else "WAITING"
        self.state.color=GREEN if d["connected"] else MUTED
        tile_info = f"tiles {len(self.map.tiles)}  errors {self.map.tile_errors}"
        self.status.text=d["message"]+" | "+d["transport"]+" | packets "+str(d["packets"])+" | "+tile_info
        if self.map.tile_errors and not self.map.tiles:
            detail = (self.map.last_tile_error or "unknown error").replace("\n", " ")[:95]
            self.map_note.text = f"OSM tile error: {detail} • © OpenStreetMap contributors"
        elif not self.map.tiles:
            self.map_note.text = "Loading global OpenStreetMap… • © OpenStreetMap contributors"
        elif d["lat"] is None:
            self.map_note.text = "WORLD VIEW — waiting for aircraft telemetry • © OpenStreetMap contributors"
        else:
            self.map_note.text = "LIVE AIRCRAFT POSITION • © OpenStreetMap contributors"
        if d["lat"] is not None and d["lon"] is not None:
            self.map.set_position(d["lat"],d["lon"],d["heading"])
            self.metrics.text=f'LAT {d["lat"]:.5f}  LON {d["lon"]:.5f}  ALT {d["alt_ft"]:.0f} ft  GS {d["speed_kt"]:.0f} kt  HDG {d["heading"]:03.0f}°'
        else:
            self.metrics.text="LAT --  LON --  ALT -- ft  GS -- kt  HDG ---°"

    def on_stop(self):
        if hasattr(self,"telemetry"):self.telemetry.stop()


if __name__ == "__main__":
    AeroflyATCApp().run()
