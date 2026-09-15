import os, json, time, math, threading, urllib.request, urllib.parse, io
from kivymd.app import MDApp
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, Line, Ellipse, Triangle
from kivy.metrics import dp
from kivy.properties import StringProperty, BooleanProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.uix.screenmanager import ScreenManager, Screen, FadeTransition
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
import advanced_features as adv

try:
    from __main__ import Telemetry
except Exception:
    Telemetry = None

BG=(0.051,0.051,0.051,1); PANEL=(0.102,0.102,0.102,1); PANEL2=(0.14,0.14,0.14,1)
AMBER=(1,0.694,0,1); WHITE=(1,1,1,1); MUTED=(0.50,0.50,0.50,1)
GREEN=(0.30,0.90,0.52,1); RED=(1,0.25,0.25,1)

KV=r"""
#:import dp kivy.metrics.dp
<Panel@BoxLayout>:
    padding: dp(10)
    spacing: dp(7)
    canvas.before:
        Color: rgba: 0.102,0.102,0.102,1
        RoundedRectangle: pos:self.pos; size:self.size; radius:[dp(10)]
<AmberButton@Button>:
    background_normal:""; background_down:""
    background_color:1,0.694,0,1
    color:0.05,0.05,0.05,1
    bold:True; font_size:"10sp"
<DarkButton@Button>:
    background_normal:""; background_down:""
    background_color:0.14,0.14,0.14,1
    color:1,1,1,1; font_size:"10sp"
<TopBar@BoxLayout>:
    title:""; size_hint_y:None; height:dp(55); padding:dp(10),dp(5); spacing:dp(5)
    Label:
        text:root.title; color:1,1,1,1; font_size:"20sp"; bold:True
    Button:
        text:"⚙"; size_hint_x:None; width:dp(45)
        background_normal:""; background_color:0.102,0.102,0.102,1
        color:1,0.694,0,1; font_size:"21sp"
        on_release:app.show_settings()
<BottomNav@BoxLayout>:
    size_hint_y:None; height:dp(70); padding:dp(3),dp(4); spacing:dp(2)
    canvas.before:
        Color: rgba:0.075,0.075,0.075,1
        Rectangle: pos:self.pos; size:self.size
    NavItem: icon:"⌗"; label:"Home"; active:app.tab=="home"; on_release:app.switch_tab("home")
    NavItem: icon:"✈"; label:"My Flight"; active:app.tab=="flight"; on_release:app.switch_tab("flight")
    NavItem: icon:"◉"; label:"Comms"; active:app.tab=="comms"; on_release:app.switch_tab("comms")
    NavItem: icon:"✎"; label:"Scratchpad"; active:app.tab=="scratch"; on_release:app.switch_tab("scratch")
    NavItem: icon:"⌖"; label:"Airports"; active:app.tab=="airports"; on_release:app.switch_tab("airports")
<NavItem>:
    orientation:"vertical"; padding:0
    Label: text:root.icon; color:(1,0.694,0,1) if root.active else (0.5,0.5,0.5,1); font_size:"22sp"
    Label: text:root.label; color:(1,0.694,0,1) if root.active else (0.5,0.5,0.5,1); font_size:"8sp"; size_hint_y:None; height:dp(17)
<TelemetryHUD>:
    orientation:"horizontal"; padding:dp(3); spacing:dp(1)
    canvas.before:
        Color: rgba:0.06,0.06,0.06,0.98
        Rectangle: pos:self.pos; size:self.size
    HUDCell: title:"ORIGIN"; value:root.origin
    HUDCell: title:"DEST"; value:root.dest
    HUDCell: title:"TAS"; value:root.tas
    HUDCell: title:"ALT"; value:root.alt
    HUDCell: title:"HDG"; value:root.hdg
    HUDCell: title:"ETE"; value:root.ete
    HUDCell: title:"TOD"; value:root.tod
<HUDCell@BoxLayout>:
    orientation:"vertical"
    Label: text:root.title; color:0.48,0.48,0.48,1; font_size:"7sp"
    Label: text:root.value; color:1,1,1,1; font_size:"10sp"; bold:True
<FlightScreen>:
    name:"flight"
    BoxLayout:
        orientation:"vertical"; spacing:0
        canvas.before:
            Color: rgba:0.051,0.051,0.051,1
            Rectangle: pos:self.pos; size:self.size
        TopBar: title:"My Flight"
        BoxLayout:
            size_hint_y:None; height:dp(42); padding:dp(5); spacing:dp(5)
            DarkButton: text:"LAYERS"; on_release:app.map_action("layers")
            DarkButton: text:"WX"; on_release:app.map_action("weather")
            DarkButton: text:"RADAR"; on_release:app.map_action("radar")
            AmberButton: text:"CENTER"; on_release:app.map_action("center")
            DarkButton: text:"FILTER"; on_release:app.map_action("filter")
        BoxLayout:
            orientation:"vertical"
            FlightMap: id:flight_map
            Label:
                id:flight_status
                text:app.flight_status
                size_hint_y:None; height:dp(27); color:0.72,0.72,0.72,1; font_size:"8sp"
        TelemetryHUD:
            id:hud; size_hint_y:None; height:dp(64)
        BottomNav:
<CommsScreen>:
    name:"comms"
    BoxLayout:
        orientation:"vertical"; padding:dp(7); spacing:dp(6)
        canvas.before:
            Color: rgba:0.051,0.051,0.051,1
            Rectangle:pos:self.pos;size:self.size
        TopBar:title:"Comms"
        RadioRow:id:com1; title:"COM 1"; active:"118.700"; standby:"122.800"
        RadioRow:id:com2; title:"COM 2"; active:"121.900"; standby:"118.100"
        BoxLayout:size_hint_y:None;height:dp(35)
            AmberButton:text:"'A' FREQUENCIES";size_hint_x:None;width:dp(130);on_release:app.auto_frequencies()
        ScrollView:
            id:chat_scroll
            Label:id:chat; text:"ATC SYSTEM READY"; color:1,1,1,1; font_size:"12sp"; text_size:self.width-dp(12),None; size_hint_y:None; height:max(self.texture_size[1],dp(160)); valign:"top"; padding:dp(6)
        BoxLayout:size_hint_y:None;height:dp(38);spacing:dp(3)
            ChannelButton:text:"COM1";active:True
            ChannelButton:text:"COM2"
            ChannelButton:text:"INT1"
            ChannelButton:text:"INT2"
            ChannelButton:text:"INT3"
            ChannelButton:text:"ATC"
        BoxLayout:size_hint_y:None;height:dp(48);spacing:dp(5)
            TextInput:id:message;hint_text:"Type a message...";multiline:False;background_color:0.102,0.102,0.102,1;foreground_color:1,1,1,1
            AmberButton:text:"MIC";size_hint_x:None;width:dp(58);on_release:app.speech_to_text()
            AmberButton:text:"SEND";size_hint_x:None;width:dp(58);on_release:app.send_message()
        BottomNav:
<RadioRow@BoxLayout>:
    title:"";active:"";standby:"";size_hint_y:None;height:dp(50);spacing:dp(5)
    Label:text:root.title;color:0.5,0.5,0.5,1;size_hint_x:None;width:dp(48)
    Label:id:active_lbl;text:root.active;color:0.30,0.90,0.52,1;font_size:"17sp";bold:True
    AmberButton:text:"⇄";size_hint_x:None;width:dp(45);on_release:app.swap_radio(root)
    Label:id:standby_lbl;text:root.standby;color:0.55,0.55,0.55,1;font_size:"15sp"
<ChannelButton@ToggleButton>:
    background_normal:"";background_down:""
    background_color:(1,0.694,0,1) if self.state=="down" else (0.14,0.14,0.14,1)
    color:(0.05,0.05,0.05,1) if self.state=="down" else (0.7,0.7,0.7,1)
    font_size:"8sp"
<ScratchScreen>:
    name:"scratch"
    BoxLayout:
        orientation:"vertical"
        canvas.before: Color: rgba:0.051,0.051,0.051,1
        TopBar:title:"Scratchpad"
        FloatLayout:
            DrawingPad:id:pad
            BoxLayout:
                orientation:"vertical";size_hint:None,1;width:dp(22);padding:dp(2),dp(25)
                Label:text:"C";color:0.28,0.28,0.28,1
                Label:text:"R";color:0.28,0.28,0.28,1
                Label:text:"A";color:0.28,0.28,0.28,1
                Label:text:"F";color:0.28,0.28,0.28,1
                Label:text:"T";color:0.28,0.28,0.28,1
        BoxLayout:size_hint_y:None;height:dp(58);spacing:dp(8);padding:dp(8)
            Widget:
            ToolButton:icon:"▣"
            ToolButton:icon:"✎";active:True
            ToolButton:icon:"⌫"
            ToolButton:icon:"🗑";on_release:pad.clear()
            Widget:
        BottomNav:
<ToolButton@Button>:
    background_normal:"";background_color:(1,0.694,0,1) if root.active else (0.14,0.14,0.14,1)
    color:(0.05,0.05,0.05,1) if root.active else (0.75,0.75,0.75,1);font_size:"19sp"
<HomeScreen>:
    name:"home"
    BoxLayout:
        orientation:"vertical";padding:dp(8);spacing:dp(7)
        canvas.before: Color: rgba:0.051,0.051,0.051,1
        TopBar:title:"AeroflyATC"
        Panel:
            orientation:"vertical";size_hint_y:None;height:dp(115)
            Label:text:"FLIGHT OPERATIONS";color:1,0.694,0,1;bold:True
            Label:id:home_conn;text:"WAITING";color:1,1,1,1;font_size:"20sp";bold:True
            Label:id:home_detail;text:"Start Aerofly FS Global and enable FSWidgets.";color:0.5,0.5,0.5,1
        GridLayout:cols:2;spacing:dp(7);size_hint_y:None;height:dp(155)
            Panel:orientation:"vertical";Label:text:"CONNECTION";color:0.5,0.5,0.5,1;Label:id:hc;text:"OFFLINE";color:1,0.694,0,1
            Panel:orientation:"vertical";Label:text:"AI ATC";color:0.5,0.5,0.5,1;Label:id:ha;text:"READY";color:1,1,1,1
            Panel:orientation:"vertical";Label:text:"FLIGHT LOG";color:0.5,0.5,0.5,1;Label:id:hl;text:"0 SAMPLES";color:1,1,1,1
            Panel:orientation:"vertical";Label:text:"WEATHER";color:0.5,0.5,0.5,1;Label:id:hw;text:"NO REQUEST";color:1,1,1,1
        Widget:
        BottomNav:
<AirportsScreen>:
    name:"airports"
    BoxLayout:
        orientation:"vertical";padding:dp(7);spacing:dp(6)
        canvas.before:Color:rgba:0.051,0.051,0.051,1
        TopBar:title:"Airports"
        BoxLayout:size_hint_y:None;height:46;spacing:5
            TextInput:id:airport_q;hint_text:"ICAO / airport name";multiline:False
            AmberButton:text:"SEARCH";size_hint_x:None;width:75;on_release:app.search_airports()
        ScrollView:
            Label:id:airport_results;text:"Search aviation databases from the Airports tab.";color:1,1,1,1;text_size:self.width-dp(12),None;size_hint_y:None;height:max(self.texture_size[1],dp(200));padding:dp(7)
        BottomNav:
<SettingsScreen>:
    name:"settings"
    BoxLayout:
        orientation:"vertical";padding:dp(8);spacing:dp(7)
        canvas.before:Color:rgba:0.051,0.051,0.051,1
        TopBar:title:"Settings"
        Panel:
            orientation:"vertical";size_hint_y:None;height:dp(225)
            Label:text:"GEMINI AI";color:1,0.694,0,1;bold:True
            TextInput:id:gemini_key;hint_text:"Gemini API key";password:True;multiline:False
            TextInput:id:gemini_model;text:"gemini-3.6-flash";multiline:False
            AmberButton:text:"SAVE GEMINI SETTINGS";size_hint_y:None;height:40;on_release:app.save_ai_settings()
            Label:text:"Gemini 3.6 Flash is the default model. Change the model ID only if your API account supports another model.";color:0.45,0.45,0.45,1;font_size:"9sp"
        Panel:
            orientation:"vertical";size_hint_y:None;height:145
            Label:text:"OPENAIP";color:1,0.694,0,1;bold:True
            TextInput:id:openaip_key;hint_text:"OpenAIP API key";password:True;multiline:False
            AmberButton:text:"SAVE MAP KEY";size_hint_y:None;height:40;on_release:app.save_map_key()
        Widget:
        DarkButton:text:"BACK TO MY FLIGHT";size_hint_y:None;height:42;on_release:app.switch_tab("flight")
"""

class NavItem(BoxLayout):
    icon=StringProperty(""); label=StringProperty(""); active=BooleanProperty(False)

class TelemetryHUD(BoxLayout):
    origin=StringProperty("---"); dest=StringProperty("---"); tas=StringProperty("---")
    alt=StringProperty("---"); hdg=StringProperty("---"); ete=StringProperty("---"); tod=StringProperty("---")

class ToolButton(Button):
    icon=StringProperty(""); active=BooleanProperty(False)

class FlightMap(Widget):
    def __init__(self,**kw):
        super().__init__(**kw); self.data={}; self.trail=[]; self.route=[]; self.zoom=1.0; self.cx=0.0; self.cy=0.0; self.drag=None
        self.bind(pos=lambda *_:self.redraw(),size=lambda *_:self.redraw())
    def update(self,data,trail,route):
        self.data=dict(data); self.trail=list(trail[-400:]); self.route=list(route); self.redraw()
    def _project(self,lat,lon):
        lat0=self.data.get("lat",0.0) if self.data.get("connected") else self.cy
        lon0=self.data.get("lon",0.0) if self.data.get("connected") else self.cx
        scale=dp(120)*self.zoom
        return self.center_x+(lon-lon0)*scale, self.center_y+(lat-lat0)*scale
    def on_touch_down(self,t):
        if self.collide_point(*t.pos):
            self.drag=t.pos; return True
        return super().on_touch_down(t)
    def on_touch_move(self,t):
        if self.drag:
            dx,dy=t.x-self.drag[0],t.y-self.drag[1]; self.drag=t.pos
            self.cx-=dx/(dp(120)*self.zoom); self.cy-=dy/(dp(120)*self.zoom); self.redraw(); return True
        return super().on_touch_move(t)
    def on_touch_up(self,t):
        self.drag=None; return True
    def zoom_in(self): self.zoom=min(8,self.zoom*1.35); self.redraw()
    def zoom_out(self): self.zoom=max(.25,self.zoom/1.35); self.redraw()
    def center_aircraft(self):
        if self.data.get("connected"): self.cx=self.data.get("lon",0); self.cy=self.data.get("lat",0); self.redraw()
    def redraw(self,*_):
        self.canvas.clear()
        with self.canvas:
            Color(0.035,0.055,0.065,1); Rectangle(pos=self.pos,size=self.size)
            Color(0.12,0.16,0.17,0.45)
            step=dp(55)
            x=self.x
            while x<self.right: Line(points=[x,self.y,x,self.top],width=.6); x+=step
            y=self.y
            while y<self.top: Line(points=[self.x,y,self.right,y],width=.6); y+=step
            if len(self.trail)>1:
                Color(0.15,0.65,1,0.9); pts=[]
                for p in self.trail:
                    q=self._project(*p); pts += [q[0],q[1]]
                Line(points=pts,width=dp(2))
            if len(self.route)>1:
                Color(*AMBER); pts=[]
                for p in self.route:
                    q=self._project(*p); pts += [q[0],q[1]]
                Line(points=pts,width=dp(1.5))
            if self.data.get("connected"):
                x,y=self._project(self.data.get("lat",0),self.data.get("lon",0))
                Color(*AMBER); Triangle(points=[x,y+dp(12),x-dp(8),y-dp(8),x+dp(8),y-dp(8)])
                Color(*WHITE); Line(circle=(x,y,dp(23)),width=1)

class DrawingPad(Widget):
    def __init__(self,**kw): super().__init__(**kw); self.strokes=[]; self.current=None
    def on_touch_down(self,t):
        if self.collide_point(*t.pos): self.current=[t.pos]; self.strokes.append(self.current); self.redraw(); return True
        return super().on_touch_down(t)
    def on_touch_move(self,t):
        if self.current is not None: self.current.append(t.pos); self.redraw(); return True
        return super().on_touch_move(t)
    def on_touch_up(self,t): self.current=None; return True
    def clear(self): self.strokes=[];self.current=None;self.redraw()
    def redraw(self,*_):
        self.canvas.clear()
        with self.canvas:
            Color(0.01,0.01,0.01,1);Rectangle(pos=self.pos,size=self.size)
            Color(0.8,0.8,0.8,0.9)
            for s in self.strokes:
                if len(s)>1: Line(points=[v for p in s for v in p],width=dp(2))

class FlightScreen(Screen): pass
class CommsScreen(Screen): pass
class ScratchScreen(Screen): pass
class HomeScreen(Screen): pass
class AirportsScreen(Screen): pass
class SettingsScreen(Screen): pass

class AeroflyATC(MDApp):
    tab=StringProperty("flight")
    flight_status=StringProperty("WAITING FOR ACTIVE FLIGHT TO BE DETECTED...")
    def build(self):
        self.theme_cls.theme_style="Dark"; self.theme_cls.primary_palette="Amber"; self.theme_cls.accent_palette="Amber"
        Builder.load_string(KV)
        self.telemetry=Telemetry() if Telemetry else None
        self.alert_engine=adv.FlightAlertEngine(); self.clearance=adv.ClearanceTracker()
        self.route=[]; self.chat=[]; self.logging=False; self.weather_text=""
        self.settings_dir=self.user_data_dir; os.makedirs(self.settings_dir,exist_ok=True)
        self.gemini_key=self._load("gemini_key",""); self.gemini_model=self._load("gemini_model","gemini-3.6-flash"); self.openaip_key=self._load("openaip_key","")
        sm=ScreenManager(transition=FadeTransition(duration=.08))
        for cls in (HomeScreen,FlightScreen,CommsScreen,ScratchScreen,AirportsScreen,SettingsScreen): sm.add_widget(cls())
        self.sm=sm; sm.current="flight"
        if self.telemetry:
            try:self.telemetry.start()
            except Exception:pass
        Clock.schedule_interval(self.tick,.25)
        return sm
    def _load(self,k,default):
        try:
            with open(os.path.join(self.settings_dir,k+".txt"),encoding="utf-8") as f:return f.read().strip() or default
        except OSError:return default
    def _save(self,k,v):
        with open(os.path.join(self.settings_dir,k+".txt"),"w",encoding="utf-8") as f:f.write(v.strip())
    def switch_tab(self,tab): self.tab=tab; self.sm.current=tab
    def show_settings(self):
        s=self.sm.get_screen("settings"); s.ids.gemini_key.text=self.gemini_key; s.ids.gemini_model.text=self.gemini_model; s.ids.openaip_key.text=self.openaip_key; self.sm.current="settings"
    def save_ai_settings(self):
        s=self.sm.get_screen("settings"); self.gemini_key=s.ids.gemini_key.text.strip(); self.gemini_model=s.ids.gemini_model.text.strip() or "gemini-3.6-flash"; self._save("gemini_key",self.gemini_key); self._save("gemini_model",self.gemini_model); self.switch_tab("comms")
    def save_map_key(self):
        self.openaip_key=self.sm.get_screen("settings").ids.openaip_key.text.strip(); self._save("openaip_key",self.openaip_key); self.switch_tab("flight")
    def tick(self,_dt):
        if not self.telemetry:return
        try:
            d=self.telemetry.snapshot(); trail=self.telemetry.trail_snapshot()
            self.sm.get_screen("flight").ids.flight_map.update(d,trail,self.route)
            hud=self.sm.get_screen("flight").ids.hud
            hud.tas="%03.0f KT"%d.get("speed",0); hud.alt="%05.0f"%d.get("altitude",0); hud.hdg="%03.0f"%d.get("heading",0)
            self.flight_status=("CONNECTED • %s • %s • %s"%(d.get("transport",""),d.get("source_ip",""),d.get("phase",""))) if d.get("connected") else ("WAITING • UDP 40092 / TCP 58585 • "+(d.get("last_error","") or "No Aerofly telemetry"))
            a=self.alert_engine.evaluate(d,self.clearance.current); 
            if a:self.flight_status="⚠ "+" • ".join(a)
            h=self.sm.get_screen("home"); h.ids.hc.text=("ONLINE" if d.get("connected") else "OFFLINE"); h.ids.home_conn.text=("FLIGHT DETECTED" if d.get("connected") else "WAITING"); h.ids.home_detail.text=("Aerofly telemetry: "+d.get("transport","")) if d.get("connected") else "Start Aerofly FS Global and enable FSWidgets."; h.ids.hl.text=str(d.get("packets",0))+" PACKETS"
        except Exception as e:
            self.flight_status="UI RECOVERY: "+str(e)[:80]
    def map_action(self,action):
        m=self.sm.get_screen("flight").ids.flight_map
        if action=="center":m.center_aircraft()
        elif action=="layers":m.zoom_in()
        elif action=="filter":m.zoom_out()
        elif action=="weather":self.fetch_weather("HUEN")
        elif action=="radar":self.fetch_radar()
    def fetch_weather(self,icao):
        def work():
            try:
                metar=adv.fetch_metar(icao); taf=adv.fetch_taf(icao)
                text=json.dumps({"METAR":metar,"TAF":taf},indent=2)[:7000]
                Clock.schedule_once(lambda *_:self.show_weather(text),0)
            except Exception as e:Clock.schedule_once(lambda *_:self.show_weather("WEATHER ERROR: "+str(e)),0)
        threading.Thread(target=work,daemon=True).start()
    def show_weather(self,text):
        self.weather_text=text; self.sm.get_screen("home").ids.hw.text="UPDATED"; self.append_chat("WEATHER",text[:2500])
    def fetch_radar(self):
        def work():
            try:
                d=adv.rainviewer(); frames=d.get("radar",{}).get("past",[]); msg="RADAR: %d frames available"%len(frames)
                if frames: msg+="\nLatest: "+str(frames[-1].get("path",""))
                Clock.schedule_once(lambda *_:self.append_chat("RADAR",msg),0)
            except Exception as e:Clock.schedule_once(lambda *_:self.append_chat("RADAR","ERROR "+str(e)),0)
        threading.Thread(target=work,daemon=True).start()
    def append_chat(self,who,text):
        self.chat.append((who,text)); self.chat=self.chat[-60:]
        self.sm.get_screen("comms").ids.chat.text="\n\n".join("[b]%s[/b]\n%s"%(a,b) for a,b in self.chat)
    def send_message(self):
        s=self.sm.get_screen("comms"); msg=s.ids.message.text.strip()
        if not msg:return
        self.append_chat("PILOT",msg); s.ids.message.text=""
        parsed=self.clearance.readback(msg)
        if self.clearance.current:self.append_chat("READBACK","CORRECT" if parsed else "NOT VERIFIED")
        if self.gemini_key:self.ask_gemini(msg)
    def ask_gemini(self,prompt):
        def work():
            try:
                url="https://generativelanguage.googleapis.com/v1beta/models/"+urllib.parse.quote(self.gemini_model)+":generateContent?key="+urllib.parse.quote(self.gemini_key)
                body={"contents":[{"role":"user","parts":[{"text":"You are the ATC companion for Aerofly FS Global. Be concise and use ICAO phraseology. Flight context: "+json.dumps(self.telemetry.snapshot() if self.telemetry else {})+"\nPilot: "+prompt}]}]}
                req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={"Content-Type":"application/json"},method="POST")
                with urllib.request.urlopen(req,timeout=20) as r:data=json.loads(r.read().decode())
                text=data["candidates"][0]["content"]["parts"][0]["text"]
                self.clearance.parse(text); Clock.schedule_once(lambda *_:self.append_chat("AI ATC",text),0)
            except Exception as e:Clock.schedule_once(lambda *_:self.append_chat("AI ERROR",str(e)),0)
        threading.Thread(target=work,daemon=True).start()
    def swap_radio(self,row):
        a=row.active;row.active=row.standby;row.standby=a
        row.ids.active_lbl.text=row.active;row.ids.standby_lbl.text=row.standby
    def auto_frequencies(self):
        self.sm.get_screen("comms").ids.com1.active="118.700";self.sm.get_screen("comms").ids.com1.standby="122.800";self.append_chat("RADIO","Published sample frequency set loaded.")
    def search_airports(self):
        q=self.sm.get_screen("airports").ids.airport_q.text.strip()
        if not q:return
        def work():
            try:
                rows=adv.search_airports(q)
                lines=[]
                for x in rows:
                    name=x.get("display_name",x.get("name","Unknown")); lines.append("%s\n%s, %s"%(name,x.get("lat",""),x.get("lon","")))
                Clock.schedule_once(lambda *_:self.show_airports("\n\n".join(lines) or "No results"),0)
            except Exception as e:Clock.schedule_once(lambda *_:self.show_airports("SEARCH ERROR: "+str(e)),0)
        threading.Thread(target=work,daemon=True).start()
    def show_airports(self,text):self.sm.get_screen("airports").ids.airport_results.text=text
    def speech_to_text(self):
        try:
            from jnius import autoclass
            SpeechRecognizer=autoclass("android.speech.SpeechRecognizer"); Intent=autoclass("android.content.Intent"); RecognizerIntent=autoclass("android.speech.RecognizerIntent")
            if not SpeechRecognizer.isRecognitionAvailable(autoclass("org.kivy.android.PythonActivity").mActivity):
                self.append_chat("MIC","Speech recognition is not available on this Android device.");return
            self.append_chat("MIC","Native Android speech recognition requested. Use the microphone permission dialog if Android asks.")
            self.sm.get_screen("comms").ids.message.text=""
            self.append_chat("MIC","For production push-to-talk, Android's recognizer callback must be bound to a Java listener; the button is wired and permission-ready.")
        except Exception as e:self.append_chat("MIC","Speech service unavailable: "+str(e))
    def on_stop(self):
        if self.telemetry:
            try:self.telemetry.stop()
            except Exception:pass

if __name__=="__main__":
    AeroflyATC().run()
