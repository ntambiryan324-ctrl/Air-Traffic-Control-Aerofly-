import json
import math
import os
import re
import socket
import threading
import time
import traceback
import urllib.request
import urllib.parse

try:
    import advanced_features as adv
except Exception:
    adv = None

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle, Triangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.uix.floatlayout import FloatLayout


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
                "udp_connected": transport.startswith("UDP"),
                "tcp_connected": self.data["tcp_connected"] or transport.startswith("TCP"),
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
                "udp_connected": self.data["udp_connected"] or transport.startswith("UDP"),
                "tcp_connected": self.data["tcp_connected"] or transport.startswith("TCP"),
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
        super().__init__(padding=dp(10), spacing=dp(6), **kwargs)
        with self.canvas.before:
            Color(*CARD)
            self.bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(8)])
        self.bind(pos=self._sync, size=self._sync)
    def _sync(self,*_):
        self.bg.pos=self.pos; self.bg.size=self.size


class TitleBar(BoxLayout):
    def __init__(self, title, app_ref, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(48),
                         padding=(dp(10),dp(3)), spacing=dp(4), **kwargs)
        self.add_widget(Label(text=title, color=TEXT, font_size="19sp", bold=True))
        self.add_widget(Widget())
        gear=Button(text="⚙", background_normal="", background_color=(0,0,0,0),
                    color=MUTED, font_size="19sp", size_hint_x=None, width=dp(38))
        gear.bind(on_press=lambda *_: app_ref.open_settings())
        self.add_widget(gear)


class MetricStrip(BoxLayout):
    FIELDS=("ORIGIN","DEST","TAS","ALT","HDG","ETE","TOD")
    def __init__(self,**kwargs):
        super().__init__(size_hint_y=None,height=dp(62),padding=dp(3),spacing=dp(1),**kwargs)
        self.values={}
        with self.canvas.before:
            Color(0.045,0.045,0.05,0.98);self.bg=Rectangle(pos=self.pos,size=self.size)
        self.bind(pos=lambda *_:setattr(self.bg,"pos",self.pos),size=lambda *_:setattr(self.bg,"size",self.size))
        for k in self.FIELDS:
            b=BoxLayout(orientation="vertical")
            b.add_widget(Label(text=k,color=MUTED,font_size="7sp"))
            v=Label(text="--",color=TEXT,font_size="10sp",bold=True)
            b.add_widget(v);self.values[k]=v;self.add_widget(b)
    def update(self,d):
        self.values["TAS"].text=f'{d.get("speed",0):.0f}'
        self.values["ALT"].text=f'{d.get("altitude",0):.0f}'
        self.values["HDG"].text=f'{d.get("heading",0):03.0f}'
        self.values["ORIGIN"].text=d.get("origin") or "--"
        self.values["DEST"].text=d.get("destination") or "--"


class AviationMap(Widget):
    """Interactive OSM-backed moving map with aviation overlays.

    Only visible tiles are requested and cached locally. The aircraft remains
    visible even before telemetry arrives so the UI never looks empty.
    """
    def __init__(self,app_ref,**kwargs):
        super().__init__(**kwargs)
        self.app_ref=app_ref;self.data={};self.zoom=9;self.center_lat=0.0;self.center_lon=0.0
        self.drag_start=None;self.tiles={};self.airports=[];self.navaids=[];self.airspaces=[];self.follow=True
        self.aircraft_heading=0
        self.base_layer='osm'
        self.theme_mode='dark'
        self.weather_mode=None
        self.weather={'clouds':None,'precipitation':None,'wind_speed':None,'wind_dir':None}
        self.ifr_visible=True
        self.bind(pos=lambda *_:self.redraw(),size=lambda *_:self.redraw())
        Clock.schedule_once(lambda *_:self.refresh_data(),.2)

    def refresh_data(self):
        d=self.data
        if d.get("connected"):
            self.center_lat=d.get("lat",0);self.center_lon=d.get("lon",0)
        elif not self.center_lat:
            self.center_lat=.0424;self.center_lon=32.4435
        self.airports=adv.nearby_airports(self.center_lat,self.center_lon,8) if adv else []
        self.navaids=adv.nearby_navaids(self.center_lat,self.center_lon,8) if adv else []
        self.airspaces=adv.fetch_airspaces(self.center_lat,self.center_lon,3,self.app_ref.openaip_key) if adv else []
        self.load_visible_tiles();self.redraw()

    def set_data(self,d):
        self.data=d
        if d.get("connected"):
            self.aircraft_heading=float(d.get("heading",0))
            if self.follow:
                self.center_lat=float(d.get("lat",0));self.center_lon=float(d.get("lon",0))
        self.redraw()

    def world(self,lat,lon):
        z=self.zoom;n=2**z
        x=(lon+180)/360*n
        latr=math.radians(max(-85.0511,min(85.0511,lat)))
        y=(1-math.asinh(math.tan(latr))/math.pi)/2*n
        return x,y

    def screen(self,lat,lon):
        x,y=self.world(lat,lon);cx,cy=self.world(self.center_lat,self.center_lon)
        scale=256
        return self.center_x+(x-cx)*scale,self.center_y+(cy-y)*scale

    def tile_xy(self,x,y):
        return int(math.floor(x)),int(math.floor(y))

    def load_visible_tiles(self, force=False):
        cx,cy=self.world(self.center_lat,self.center_lon);tx,ty=self.tile_xy(cx,cy)
        for xx in range(tx-2,tx+3):
            for yy in range(ty-2,ty+3):
                key=(self.zoom,xx,yy)
                if key in self.tiles and not force: continue
                if xx<0 or yy<0 or xx>=2**self.zoom or yy>=2**self.zoom: continue
                self.tiles[key]=None
                threading.Thread(target=self._download_tile,args=(key,),daemon=True).start()

    def _download_tile(self,key):
        try:
            import hashlib
            z,x,y=key
            cache=os.path.join(self.app_ref.user_data_dir,"tiles",str(z))
            os.makedirs(cache,exist_ok=True)
            path=os.path.join(cache,f"{x}_{y}.png")
            if os.path.exists(path) and time.time()-os.path.getmtime(path)<7*86400:
                data=open(path,"rb").read()
            else:
                if self.base_layer == 'satellite':
                    url=f'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
                elif self.base_layer == 'dark':
                    url=f'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'
                else:
                    url=f'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
                req=urllib.request.Request(url, headers={'User-Agent':'AeroflyATC/2.2 (+AeroflyATC mobile companion)'})
                with urllib.request.urlopen(req,timeout=8) as r:data=r.read()
                open(path,"wb").write(data)
            from kivy.core.image import Image as CoreImage
            from io import BytesIO
            tex=CoreImage(BytesIO(data),ext="png").texture
            Clock.schedule_once(lambda *_: self._set_tile(key,tex),0)
        except Exception:
            Clock.schedule_once(lambda *_: self._set_tile(key,None),0)

    def _set_tile(self,key,tex):
        self.tiles[key]=tex;self.redraw()

    def redraw(self,*_):
        self.canvas.clear()
        with self.canvas:
            Color(0.03,0.04,0.05,1);Rectangle(pos=self.pos,size=self.size)
            cx,cy=self.world(self.center_lat,self.center_lon);tx,ty=self.tile_xy(cx,cy)
            fracx=cx-tx;fracy=cy-ty
            for key,tex in list(self.tiles.items()):
                z,x,y=key
                if z!=self.zoom or tex is None:continue
                px=self.center_x+(x-cx)*256
                py=self.center_y+(cy-y)*256
                Color(1,1,1,1)
                Rectangle(texture=tex,pos=(px,py),size=(256,256))
            # aviation overlays
            for a in self.airports:
                sx,sy=self.screen(a["lat"],a["lon"])
                if self.x-20<sx<self.right+20 and self.y-20<sy<self.top+20:
                    Color(*ACCENT);Ellipse(pos=(sx-3,sy-3),size=(6,6))
                    # labels are rendered as a separate Label layer below
            if self.ifr_visible:
                for n in self.navaids:
                    sx,sy=self.screen(n["lat"],n["lon"])
                    if self.x-20<sx<self.right+20 and self.y-20<sy<self.top+20:
                        Color(0.25,0.85,1.0,0.9)
                        Line(circle=(sx,sy,dp(5)),width=1)
                for a in self.airspaces:
                    pass
            wx=self.weather
            sx,sy=self.screen(self.center_lat,self.center_lon)
            if self.weather_mode=="precipitation" and wx.get("precipitation") is not None:
                intensity=min(1.0,float(wx["precipitation"])/10.0)
                Color(0.15,0.35,1.0,0.12+0.30*intensity)
                Ellipse(pos=(sx-dp(55),sy-dp(55)),size=(dp(110),dp(110)))
            elif self.weather_mode=="clouds" and wx.get("clouds") is not None:
                coverage=float(wx["clouds"])/100.0
                Color(0.7,0.75,0.8,0.08+0.20*coverage)
                Ellipse(pos=(sx-dp(65),sy-dp(65)),size=(dp(130),dp(130)))
            elif self.weather_mode=="winds" and wx.get("wind_speed") is not None:
                ang=math.radians(float(wx.get("wind_dir") or 0))
                length=dp(45); ex=sx+math.sin(ang)*length; ey=sy+math.cos(ang)*length
                Color(0.25,0.9,0.8,0.9)
                Line(points=[sx,sy,ex,ey],width=dp(2))
            if self.data.get("connected"):
                px,py=self.screen(self.data.get("lat",0),self.data.get("lon",0))
            else: px,py=self.center
            h=math.radians(self.aircraft_heading)
            size=dp(22)
            nose=(px+math.sin(h)*size,py+math.cos(h)*size)
            left=(px+math.sin(h+2.45)*size*.75,py+math.cos(h+2.45)*size*.75)
            right=(px+math.sin(h-2.45)*size*.75,py+math.cos(h-2.45)*size*.75)
            Color(*AMBER);Triangle(points=[nose[0],nose[1],left[0],left[1],right[0],right[1]])
            Color(1,0.70,0.1,.25);Line(circle=(px,py,dp(34)),width=1.3)
            Color(1,1,1,.65);Line(circle=(px,py,dp(5)),width=1)

    def set_base_layer(self, layer):
        self.base_layer=layer
        self.load_visible_tiles(force=True)
        self.redraw()

    def toggle_theme(self):
        self.theme_mode='light' if self.theme_mode=='dark' else 'dark'
        self.redraw()

    def set_weather_mode(self, mode):
        self.weather_mode=None if self.weather_mode==mode else mode
        self.app_ref.request_weather_layer(self.weather_mode)
        self.redraw()

    def toggle_ifr(self):
        self.ifr_visible=not self.ifr_visible
        self.refresh_data()
        self.redraw()

    def on_touch_down(self,t):
        if not self.collide_point(*t.pos): return False
        self.drag_start=t.pos;self.follow=False;return True
    def on_touch_move(self,t):
        if self.drag_start:
            dx=t.x-self.drag_start[0];dy=t.y-self.drag_start[1];self.drag_start=t.pos
            scale=256
            x,y=self.world(self.center_lat,self.center_lon)
            # invert screen movement into world coordinates
            x-=dx/scale;y+=dy/scale
            n=2**self.zoom
            lon=x/n*360-180
            lat=math.degrees(math.atan(math.sinh(math.pi*(1-2*y/n))))
            self.center_lat=lat;self.center_lon=lon;self.load_visible_tiles();self.redraw();return True
        return False
    def on_touch_up(self,t):
        self.drag_start=None;return True
    def zoom_by(self,f):
        self.zoom=max(4,min(13,self.zoom+int(f)));self.load_visible_tiles();self.redraw()
    def center_on_aircraft(self):
        if self.data.get("connected"):
            self.center_lat=self.data["lat"];self.center_lon=self.data["lon"]
        self.follow=True;self.load_visible_tiles();self.refresh_data()


class MapOverlay(BoxLayout):
    def __init__(self,app_ref,**kwargs):
        super().__init__(orientation="vertical",padding=dp(7),spacing=dp(5),**kwargs)
        self.app_ref=app_ref
        top=BoxLayout(size_hint_y=None,height=dp(34),spacing=dp(4))
        for txt,fn in (("−",lambda:self.app_ref.map.zoom_by(-1)),("+",lambda:self.app_ref.map.zoom_by(1)),
                       ("CENTER",lambda:self.app_ref.map.center_on_aircraft()),
                       ("MAP",lambda:self.app_ref.cycle_map_layer()),
                       ("WX",lambda:self.app_ref.cycle_weather_layer()),
                       ("IFR",lambda:self.app_ref.map.toggle_ifr())):
            b=Button(text=txt,size_hint_x=None,width=dp(52),background_normal="",background_color=(.05,.05,.06,.90),color=TEXT,font_size="8sp")
            b.bind(on_press=lambda _,f=fn:f());top.add_widget(b)
        self.add_widget(top)
        self.labels=GridLayout(cols=1,size_hint_y=1)
        self.add_widget(self.labels)
    def refresh_labels(self,airports,airspaces):
        self.labels.clear_widgets()
        shown=0
        for a in airports:
            if shown>=8:break
            self.labels.add_widget(Label(text=f'{a["ident"]}  {a["name"]}',color=TEXT,font_size="9sp",halign="left",size_hint_y=None,height=dp(18)))
            shown+=1
        for a in airspaces[:5]:
            self.labels.add_widget(Label(text=f'▧ {a.get("name","AIRSPACE")} {a.get("lower","")}–{a.get("upper","")}',
                                         color=WARN,font_size="8sp",halign="left",size_hint_y=None,height=dp(16)))


class MyFlightScreen(Screen):
    def __init__(self,app_ref,**kwargs):
        super().__init__(**kwargs);self.app_ref=app_ref
        root=BoxLayout(orientation="vertical")
        root.add_widget(TitleBar("MY FLIGHT",app_ref))
        mapbox=FloatLayout()
        self.app_ref.map=AviationMap(app_ref,size_hint=(1,1));mapbox.add_widget(self.app_ref.map)
        self.overlay=MapOverlay(app_ref,size_hint=(1,None),height=dp(88),pos_hint={"top":1})
        mapbox.add_widget(self.overlay)
        self.status=Label(text="WAITING FOR ACTIVE FLIGHT • MAP CENTERED ON ENTEBBE",color=TEXT,
                          size_hint=(1,None),height=dp(24),pos_hint={"x":0,"y":0},
                          halign="left",text_size=(None,None))
        mapbox.add_widget(self.status)
        root.add_widget(mapbox)
        self.hud=MetricStrip();root.add_widget(self.hud)
        self.add_widget(root)
    def refresh(self,d,trail):
        self.app_ref.map.set_data(d)
        if d.get("connected"):
            self.status.text=f'● AEROFLY CONNECTED  {d.get("transport","")}  {d.get("source_ip","")}'
        else:self.status.text="○ WAITING FOR AEROFLY • TAP CENTER AFTER CONNECT"
        self.hud.update(d)
        self.overlay.refresh_labels(self.app_ref.map.airports,self.app_ref.map.airspaces)


class CommsScreen(Screen):
    def __init__(self,app_ref,**kwargs):
        super().__init__(**kwargs);self.app_ref=app_ref
        root=BoxLayout(orientation="vertical",padding=dp(7),spacing=dp(6));root.add_widget(TitleBar("COMMS",app_ref))
        for name,a,s in (("COM 1","118.700","122.800"),("COM 2","121.900","118.100")):
            row=BoxLayout(size_hint_y=None,height=dp(48),spacing=dp(5))
            row.add_widget(Label(text=name,color=MUTED,font_size="10sp"))
            av=Label(text=a,color=GOOD,font_size="18sp",bold=True);sv=Label(text=s,color=MUTED,font_size="16sp")
            row.add_widget(av);sw=Button(text="⇄",size_hint_x=None,width=dp(48),background_normal="",background_color=ACCENT,color=(.05,.05,.05,1))
            sw.bind(on_press=lambda _,x=av,y=sv:(setattr(x,"text",y.text),setattr(y,"text",x.text)))
            row.add_widget(sw);row.add_widget(sv);root.add_widget(row)
        root.add_widget(Button(text="'A' FREQUENCIES",size_hint_y=None,height=dp(32)))
        self.chat=TextInput(readonly=True,multiline=True,text="ATC SYSTEM READY\n\nAwaiting radio traffic.",background_color=CARD,foreground_color=TEXT)
        root.add_widget(self.chat)
        channels=BoxLayout(size_hint_y=None,height=dp(34),spacing=dp(3))
        for x in ("COM1","COM2","INT1","INT2","INT3","ATC"):channels.add_widget(Button(text=x,background_normal="",background_color=CARD2,color=TEXT))
        root.add_widget(channels)
        sendrow=BoxLayout(size_hint_y=None,height=dp(48),spacing=dp(4));self.input=TextInput(hint_text="Type a message…",multiline=False);sendrow.add_widget(self.input)
        mic=Button(text="MIC",size_hint_x=None,width=dp(54));mic.bind(on_press=lambda *_:self.app_ref.start_voice())
        send=Button(text="SEND",size_hint_x=None,width=dp(60));send.bind(on_press=self.send)
        sendrow.add_widget(mic);sendrow.add_widget(send);root.add_widget(sendrow);self.add_widget(root)
    def send(self,*_):
        t=self.input.text.strip()
        if t:
            self.chat.text+=f"\n\nPILOT\n{t}";self.input.text="";self.app_ref.copilot.observe_atc(t)


class ScratchCanvas(Widget):
    def __init__(self,**kwargs):
        super().__init__(**kwargs);self.strokes=[];self.current=None;self.bind(pos=lambda *_:self.redraw(),size=lambda *_:self.redraw())
    def on_touch_down(self,t):
        if self.collide_point(*t.pos):self.current=[t.pos];self.strokes.append(self.current);return True
        return False
    def on_touch_move(self,t):
        if self.current is not None:self.current.append(t.pos);self.redraw();return True
        return False
    def on_touch_up(self,t):
        self.current=None;return True
    def clear(self):self.strokes=[];self.redraw()
    def redraw(self,*_):
        self.canvas.clear()
        with self.canvas:
            Color(.008,.008,.009,1);Rectangle(pos=self.pos,size=self.size)
            Color(.9,.9,.9,.95)
            for s in self.strokes:
                if len(s)>1:Line(points=[v for p in s for v in p],width=dp(2))


class ScratchpadScreen(Screen):
    def __init__(self,app_ref,**kwargs):
        super().__init__(**kwargs);self.app_ref=app_ref
        root=BoxLayout(orientation="vertical");root.add_widget(TitleBar("SCRATCHPAD",app_ref))
        body=FloatLayout()
        self.canvas_pad=ScratchCanvas();body.add_widget(self.canvas_pad)
        for i,ch in enumerate("CRAFT"):
            body.add_widget(Label(text=ch,color=(.35,.35,.35,.35),font_size="24sp",
                                  size_hint=(None,None),size=(dp(28),dp(34)),
                                  pos_hint={"x":.015,"top":1-(i*.18)}))
        root.add_widget(body)
        tools=BoxLayout(size_hint_y=None,height=dp(52),padding=dp(6),spacing=dp(6))
        for txt,fn in (("NOTE",lambda:None),("PEN",lambda:None),("ERASER",lambda:None),("CLEAR",self.canvas_pad.clear)):
            b=Button(text=txt,background_normal="",background_color=ACCENT if txt=="PEN" else CARD2,color=TEXT);b.bind(on_press=lambda _,f=fn:f());tools.add_widget(b)
        root.add_widget(tools);self.add_widget(root)


class SettingsScreen(Screen):
    def __init__(self,app_ref,**kwargs):
        super().__init__(**kwargs);self.app_ref=app_ref
        root=BoxLayout(orientation="vertical",padding=dp(8),spacing=dp(7))
        root.add_widget(TitleBar("SETTINGS",app_ref))
        conn=Card(orientation="vertical",size_hint_y=None,height=dp(150))
        conn.add_widget(Label(text="AEROFLY CONNECTION",color=ACCENT,font_size="11sp",bold=True))
        row=BoxLayout(size_hint_y=None,height=dp(42),spacing=dp(5));row.add_widget(Label(text="SIM HOST",color=MUTED,size_hint_x=None,width=dp(80)))
        self.host=TextInput(text=app_ref.telemetry.tcp_host,multiline=False);row.add_widget(self.host)
        applyb=Button(text="APPLY",size_hint_x=None,width=dp(70));applyb.bind(on_press=lambda *_:app_ref.telemetry.set_tcp_host(self.host.text));row.add_widget(applyb);conn.add_widget(row)
        conn.add_widget(Label(text="TCP 58585  •  UDP 40092\\nEnable Aerofly flight-data sharing / FSWidgets in Aerofly.",color=MUTED,font_size="9sp"))
        root.add_widget(conn)
        ai=Card(orientation="vertical",size_hint_y=None,height=dp(175));ai.add_widget(Label(text="AI ATC",color=ACCENT,font_size="11sp",bold=True))
        self.key=TextInput(text=app_ref.gemini_key,password=True,multiline=False,hint_text="Gemini API key");ai.add_widget(self.key)
        self.model=TextInput(text=app_ref.gemini_model,multiline=False);ai.add_widget(self.model)
        save=Button(text="SAVE AI SETTINGS",size_hint_y=None,height=dp(40));save.bind(on_press=self.save_ai);ai.add_widget(save);root.add_widget(ai)
        maps=Card(orientation="vertical",size_hint_y=None,height=dp(150));maps.add_widget(Label(text="AVIATION MAP DATA",color=ACCENT,font_size="11sp",bold=True))
        maps.add_widget(Label(text="OpenStreetMap base map • OurAirports airport/runway/navaid data • aviation weather\\nOptional OpenAIP key enables richer airspace geometry.",color=MUTED,font_size="9sp"))
        self.oai=TextInput(text=app_ref.openaip_key,password=True,multiline=False,hint_text="Optional OpenAIP API key");maps.add_widget(self.oai)
        sv=Button(text="SAVE MAP SETTINGS",size_hint_y=None,height=dp(38));sv.bind(on_press=self.save_map);maps.add_widget(sv);root.add_widget(maps)
        root.add_widget(Widget());self.add_widget(root)
    def save_ai(self,*_):
        self.app_ref.gemini_key=self.key.text.strip();self.app_ref.gemini_model=self.model.text.strip() or "gemini-3.6-flash"
        self.app_ref.persist_settings();self.app_ref.go("flight")
    def save_map(self,*_):
        self.app_ref.openaip_key=self.oai.text.strip();self.app_ref.persist_settings();self.app_ref.map.refresh_data();self.app_ref.go("flight")


class AeroflyCompanion(App):
    def _write_crash_log(self,exc):
        try:
            with open(os.path.join(self.user_data_dir,"startup_error.log"),"a",encoding="utf8") as f:
                f.write("\\n--- error ---\\n");traceback.print_exc(file=f)
        except Exception:pass
    def build(self):
        self.gemini_key=self.load_setting("gemini_key","")
        self.gemini_model=self.load_setting("gemini_model","gemini-3.6-flash")
        self.openaip_key=self.load_setting("openaip_key","")
        self.telemetry=Telemetry();self.copilot=Copilot()
        sm=ScreenManager(transition=SlideTransition(duration=.10));self.screens={}
        for name,fn in (("flight",lambda:MyFlightScreen(self,name="flight")),
                        ("comms",lambda:CommsScreen(self,name="comms")),
                        ("scratch",lambda:ScratchpadScreen(self,name="scratch")),
                        ("settings",lambda:SettingsScreen(self,name="settings"))):
            try:s=fn()
            except Exception as e:self._write_crash_log(e);s=Screen(name=name)
            self.screens[name]=s;sm.add_widget(s)
        self.manager=sm
        root=BoxLayout(orientation="vertical");root.add_widget(sm)
        nav=BoxLayout(size_hint_y=None,height=dp(56),spacing=dp(3),padding=dp(3))
        for n,t in (("flight","MY FLIGHT"),("comms","COMMS"),("scratch","SCRATCHPAD")):
            b=Button(text=t,background_normal="",background_color=CARD2,color=TEXT,font_size="9sp");b.bind(on_press=lambda _,x=n:self.go(x));nav.add_widget(b)
        root.add_widget(nav)
        Clock.schedule_once(self._start_services,.6);Clock.schedule_interval(self.tick,.35)
        return root
    def load_setting(self,k,d):
        try:
            with open(os.path.join(self.user_data_dir,k+".txt"),encoding="utf8") as f:return f.read().strip() or d
        except OSError:return d
    def persist_settings(self):
        for k,v in (("gemini_key",self.gemini_key),("gemini_model",self.gemini_model),("openaip_key",self.openaip_key)):
            try:
                with open(os.path.join(self.user_data_dir,k+".txt"),"w",encoding="utf8") as f:f.write(v)
            except OSError:pass
    def _start_services(self,_dt):
        try:self.telemetry.start()
        except Exception as e:self._write_crash_log(e)
    def go(self,n):self.manager.current=n
    def open_settings(self):self.go("settings")
    def tick(self,_dt):
        try:
            d=self.telemetry.snapshot();self.screens["flight"].refresh(d,self.telemetry.trail_snapshot())
        except Exception as e:self._write_crash_log(e)
    def cycle_map_layer(self):
        layers=["osm","satellite","dark"]
        i=layers.index(self.map.base_layer)
        self.map.set_base_layer(layers[(i+1)%len(layers)])

    def cycle_weather_layer(self):
        modes=[None,"clouds","precipitation","winds"]
        i=modes.index(self.map.weather_mode)
        self.map.set_weather_mode(modes[(i+1)%len(modes)])

    def request_weather_layer(self,mode):
        if not mode:
            self.map.weather={"clouds":None,"precipitation":None,"wind_speed":None,"wind_dir":None}
            self.map.redraw()
            return
        lat,lon=self.map.center_lat,self.map.center_lon
        def work():
            try:
                q=urllib.parse.urlencode({"latitude":lat,"longitude":lon,"current":"cloud_cover,precipitation,wind_speed_10m,wind_direction_10m","timezone":"UTC"})
                req=urllib.request.Request("https://api.open-meteo.com/v1/forecast?"+q,headers={"User-Agent":"AeroflyATC/2.2"})
                with urllib.request.urlopen(req,timeout=10) as r:d=json.loads(r.read().decode())
                x=d.get("current",{})
                self.map.weather={"clouds":x.get("cloud_cover"),"precipitation":x.get("precipitation"),"wind_speed":x.get("wind_speed_10m"),"wind_dir":x.get("wind_direction_10m")}
                Clock.schedule_once(lambda *_:self.map.redraw(),0)
            except Exception:
                pass
        threading.Thread(target=work,daemon=True).start()

    def request_weather(self):
        d=self.telemetry.snapshot();icao=d.get("destination") or "HUEN"
        self.screens["comms"].chat.text+="\\n\\nWEATHER\\nFetching METAR/TAF for "+icao
        def work():
            try:
                m=adv.fetch_metar(icao);t=adv.fetch_taf(icao)
                Clock.schedule_once(lambda *_:setattr(self.screens["comms"].chat,"text",
                    self.screens["comms"].chat.text+"\\n"+json.dumps(m)[:1200]+"\\n"+json.dumps(t)[:1200]),0)
            except Exception as e:Clock.schedule_once(lambda *_:setattr(self.screens["comms"].chat,"text",
                self.screens["comms"].chat.text+"\\nWEATHER ERROR "+str(e)),0)
        threading.Thread(target=work,daemon=True).start()
    def start_voice(self):
        try:
            from jnius import autoclass,PythonJavaClass,java_method
            from android.permissions import request_permissions,Permission
            request_permissions([Permission.RECORD_AUDIO])
            SR=autoclass("android.speech.SpeechRecognizer");Act=autoclass("org.kivy.android.PythonActivity").mActivity
            if not SR.isRecognitionAvailable(Act):
                self.screens["comms"].chat.text+="\\n\\nMIC: speech recognition unavailable";return
            app=self
            class L(PythonJavaClass):
                __javainterfaces__=["android/speech/RecognitionListener"]
                @java_method("(Landroid/os/Bundle;)V")
                def onResults(self,b):
                    arr=b.getStringArrayList(SR.RESULTS_RECOGNITION)
                    if arr and arr.size():Clock.schedule_once(lambda *_:app._voice_result(str(arr.get(0))),0)
                @java_method("(I)V")
                def onError(self,e):Clock.schedule_once(lambda *_:app._voice_result(""),0)
                @java_method("()V")
                def onReadyForSpeech(self,b):pass
                @java_method("()V")
                def onBeginningOfSpeech(self):pass
                @java_method("(F)V")
                def onRmsChanged(self,v):pass
                @java_method("([B)V")
                def onBufferReceived(self,b):pass
                @java_method("()V")
                def onEndOfSpeech(self):pass
                @java_method("(Landroid/os/Bundle;)V")
                def onPartialResults(self,b):pass
                @java_method("(ILandroid/os/Bundle;)V")
                def onEvent(self,e,b):pass
            self._voice_listener=L();self._voice=SR.createSpeechRecognizer(Act);self._voice.setRecognitionListener(self._voice_listener)
            I=autoclass("android.content.Intent");RI=autoclass("android.speech.RecognizerIntent");i=I(RI.ACTION_RECOGNIZE_SPEECH)
            i.putExtra(RI.EXTRA_LANGUAGE_MODEL,RI.LANGUAGE_MODEL_FREE_FORM);self._voice.startListening(i)
        except Exception as e:self.screens["comms"].chat.text+="\\n\\nMIC ERROR "+str(e)
    def _voice_result(self,text):
        if text:self.screens["comms"].input.text=text
    def on_stop(self):
        try:self.telemetry.stop()
        except Exception:pass


if __name__ == "__main__":
    AeroflyCompanion().run()
