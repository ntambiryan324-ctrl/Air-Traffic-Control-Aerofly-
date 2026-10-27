import math, json, threading, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.graphics import Color, RoundedRectangle, Line, Ellipse
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.widget import Widget
import advanced_features as adv

BG=(0.035,0.055,0.085,1); CARD=(0.065,0.095,0.135,1); CARD2=(0.085,0.12,0.165,1)
ACCENT=(0.10,0.62,0.95,1); GOOD=(0.15,0.80,0.48,1); TEXT=(0.90,0.94,0.98,1); MUTED=(0.56,0.64,0.73,1); WARN=(1,.67,.20,1)

def _label(text,size=10,color=TEXT,bold=False,**kw):
    return Label(text=text,color=color,font_size=f"{size}sp",bold=bold,**kw)

def _button(text,active=False,height=42):
    b=Button(text=text,background_normal="",background_color=ACCENT if active else CARD2,color=(.04,.05,.07,1) if active else TEXT,font_size="9sp",bold=active,size_hint_y=None,height=dp(height))
    return b

class RouteCanvas(Widget):
    def __init__(self,**kw):
        super().__init__(**kw); self.points=[]; self.bind(pos=lambda *_:self.redraw(),size=lambda *_:self.redraw())
    def set_points(self,p): self.points=p or []; self.redraw()
    def redraw(self,*_):
        self.canvas.clear()
        with self.canvas:
            Color(.025,.045,.065,1); RoundedRectangle(pos=self.pos,size=self.size,radius=[dp(14)])
            Color(.12,.20,.24,.45)
            for x in range(0,int(self.width),int(dp(35))): Line(points=[self.x+x,self.y,self.x+x,self.top],width=.5)
            for y in range(0,int(self.height),int(dp(35))): Line(points=[self.x,self.y+y,self.right,self.y+y],width=.5)
            if len(self.points)>1:
                lats=[p[0] for p in self.points]; lons=[p[1] for p in self.points]
                la0,la1=min(lats),max(lats); lo0,lo1=min(lons),max(lons)
                sx=max(1e-5,lo1-lo0); sy=max(1e-5,la1-la0)
                def pxy(p):
                    return self.x+dp(18)+(p[1]-lo0)/sx*max(1,self.width-dp(36)), self.y+dp(18)+(p[0]-la0)/max(1e-5,sy)*max(1,self.height-dp(36))
                pts=[]
                for p in self.points: pts.extend(pxy(p))
                Color(*ACCENT); Line(points=pts,width=dp(2))
                Color(*GOOD)
                for p in self.points:
                    x,y=pxy(p); Ellipse(pos=(x-dp(4),y-dp(4)),size=(dp(8),dp(8)))

class FlightPlanningScreen(Screen):
    def __init__(self,app_ref,**kw):
        super().__init__(**kw); self.app_ref=app_ref; self.points=[]; self.route_tokens=[]
        root=BoxLayout(orientation="vertical",padding=dp(7),spacing=dp(6))
        head=BoxLayout(size_hint_y=None,height=dp(58),spacing=dp(5))
        title=BoxLayout(orientation="vertical"); title.add_widget(_label("FLIGHT PLANNER",19,TEXT,True)); title.add_widget(_label("FLYCHARTS-STYLE • IFR / VFR • ROUTE / PROCEDURES / DISPATCH",8,MUTED)); head.add_widget(title)
        b=_button("CLOSE",False,40); b.size_hint_x=None;b.width=dp(65);b.bind(on_press=lambda *_:app_ref.go("flight"));head.add_widget(b);root.add_widget(head)
        tabs=GridLayout(cols=4,size_hint_y=None,height=dp(40),spacing=dp(4))
        for name in ("ROUTE","PROCEDURES","DISPATCH","INTEGRATIONS"):
            b=_button(name,name=="ROUTE",38);b.bind(on_press=lambda _,n=name:self.set_tab(n));tabs.add_widget(b)
        root.add_widget(tabs)
        self.body=BoxLayout();root.add_widget(self.body);self.add_widget(root);self.set_tab("ROUTE")
    def set_tab(self,tab):
        self.body.clear_widgets()
        if tab=="ROUTE": self.body.add_widget(self.route_tab())
        elif tab=="PROCEDURES": self.body.add_widget(self.proc_tab())
        elif tab=="DISPATCH": self.body.add_widget(self.dispatch_tab())
        else: self.body.add_widget(self.integrations_tab())
    def route_tab(self):
        box=BoxLayout(orientation="vertical",spacing=dp(5))
        form=GridLayout(cols=2,size_hint_y=None,height=dp(118),spacing=dp(5))
        self.orig=TextInput(text=getattr(self.app_ref,"plan",{}).get("origin",""),hint_text="ORIGIN ICAO",multiline=False); self.dest=TextInput(text=getattr(self.app_ref,"plan",{}).get("dest",""),hint_text="DESTINATION ICAO",multiline=False)
        self.route=TextInput(text=getattr(self.app_ref,"plan",{}).get("route",""),hint_text="OPTIONAL ROUTE / FIXES",multiline=False)
        self.aircraft=TextInput(text="B738",hint_text="AIRCRAFT TYPE",multiline=False)
        for x in (self.orig,self.dest,self.route,self.aircraft): form.add_widget(x)
        box.add_widget(form)
        actions=GridLayout(cols=4,size_hint_y=None,height=dp(42),spacing=dp(4))
        for t,fn in (("GENERATE",self.generate),("DIRECT",self.direct),("SIMBRIEF",self.import_simbrief),("CLEAR",self.clear)):
            b=_button(t,t=="GENERATE",40);b.bind(on_press=lambda _,f=fn:f());actions.add_widget(b)
        box.add_widget(actions)
        self.map=RouteCanvas(size_hint_y=None,height=dp(190));box.add_widget(self.map)
        self.status=_label("Enter two ICAO airports, then GENERATE.",9,MUTED);self.status.size_hint_y=None;self.status.height=dp(35);box.add_widget(self.status)
        self.route_view=ScrollView();self.route_label=_label("No route generated.",10,TEXT);self.route_label.text_size=(None,None);self.route_view.add_widget(self.route_label);box.add_widget(self.route_view)
        return box
    def _airport(self,code):
        code=code.strip().upper()
        if code in adv.KNOWN_AIRPORTS:
            a,b,n=adv.KNOWN_AIRPORTS[code]; return {"icao":code,"lat":a,"lon":b,"name":n}
        return None
    def generate(self,*_):
        o=self._airport(self.orig.text); d=self._airport(self.dest.text)
        if not o or not d:
            self.status.text="Use an airport in the local database or import a SimBrief plan."; self.status.color=WARN; return
        route=self.route.text.strip().upper()
        pts=[(o["lat"],o["lon"])]
        if route:
            for token in route.replace(","," ").split():
                n=self._airport(token)
                if n: pts.append((n["lat"],n["lon"]))
        pts.append((d["lat"],d["lon"]))
        self.points=pts; self.map.set_points(pts)
        dist=adv.route_distance(pts)
        brg=adv.initial_bearing(o["lat"],o["lon"],d["lat"],d["lon"])
        self.route_tokens=[o["icao"]]+[x for x in route.split() if x]+[d["icao"]]
        self.route_label.text=("  ".join(self.route_tokens)+"\n\nDIST %.1f NM   INITIAL TRACK %03.0f°\n"
                               "ROUTE POINTS %d   AIRCRAFT %s\n\n"
                               "Generated route is deterministic from the verified airport coordinates. "
                               "AIRAC route/procedure data is requested when available.")%(dist,brg,len(pts),self.aircraft.text.upper())
        self.route_label.texture_update();self.status.text="ROUTE GENERATED • %.1f NM"%dist;self.status.color=GOOD
        self.app_ref.plan["origin"]=o["icao"];self.app_ref.plan["dest"]=d["icao"];self.app_ref.plan["route"]=" ".join(self.route_tokens[1:-1]);self.app_ref.plan["points"]=pts
    def direct(self,*_):
        self.route.text="";self.generate()
    def clear(self,*_):
        self.orig.text="";self.dest.text="";self.route.text="";self.map.set_points([]);self.route_label.text="No route generated.";self.status.text="Planner cleared."
    def import_simbrief(self,*_):
        user=self.route.text.strip()
        if not user:
            self.status.text="Enter your SimBrief username in the ROUTE field, then press SIMBRIEF.";self.status.color=WARN;return
        self.status.text="Fetching latest SimBrief OFP…"
        def work():
            try:
                u="https://www.simbrief.com/api/xml.fetcher.php?username="+urllib.parse.quote(user)
                req=urllib.request.Request(u,headers={"User-Agent":"AeroflyATC/1.0"})
                with urllib.request.urlopen(req,timeout=20) as r: xml=r.read()
                root=ET.fromstring(xml)
                orig=(root.findtext("./origin/icao") or "").strip().upper()
                dest=(root.findtext("./destination/icao") or "").strip().upper()
                route=(root.findtext("./general/route") or "").strip()
                dist=root.findtext("./general/route_distance") or "—"
                self._ui_import(orig,dest,route,dist,None)
            except Exception as e:self._ui_import("","","","",str(e))
        threading.Thread(target=work,daemon=True).start()
    def _ui_import(self,o,d,r,dist,err):
        def apply(_):
            if err:self.status.text="SIMBRIEF IMPORT FAILED: "+err[:100];self.status.color=WARN;return
            self.orig.text=o;self.dest.text=d;self.route.text=r;self.generate();self.status.text="SIMBRIEF OFP IMPORTED • %s NM"%dist
        Clock.schedule_once(apply,0)
    def proc_tab(self):
        box=BoxLayout(orientation="vertical",spacing=dp(6))
        box.add_widget(_label("PROCEDURES",15,TEXT,True))
        box.add_widget(_label("SID • STAR • APPROACH • RUNWAY • ILS • AIRWAY",9,MUTED))
        self.proc_out=_label("Select airports in ROUTE. Procedure data uses the cycle-aware navigation-data layer when available.",10,TEXT)
        box.add_widget(self.proc_out)
        row=GridLayout(cols=3,size_hint_y=None,height=dp(44),spacing=dp(4))
        for t,typ in (("SIDS","SID"),("STARS","STAR"),("APPROACHES","APP")):
            b=_button(t,False,40);b.bind(on_press=lambda _,x=typ:self.load_procedure(x));row.add_widget(b)
        box.add_widget(row);box.add_widget(Widget());return box
    def load_procedure(self,typ):
        code=(self.orig.text if typ=="SID" else self.dest.text).strip().upper()
        if not code:self.proc_out.text="Enter the airport first.";return
        self.proc_out.text="Querying navigation data…"
        def work():
            data,cycle=adv.airport_procedures(code,typ)
            text="AIRAC "+str(cycle or "unknown")+"\n"+json.dumps(data,indent=2)[:7000] if data else "No procedure data returned. Check the configured navdata source."
            Clock.schedule_once(lambda *_:setattr(self.proc_out,"text",text),0)
        threading.Thread(target=work,daemon=True).start()
    def dispatch_tab(self):
        box=BoxLayout(orientation="vertical",spacing=dp(6));box.add_widget(_label("DISPATCH / PERFORMANCE",15,TEXT,True))
        grid=GridLayout(cols=2,spacing=dp(5),size_hint_y=None,height=dp(170))
        self.cruise=TextInput(text="360",hint_text="CRUISE FL",multiline=False);self.reserve=TextInput(text="45",hint_text="RESERVE MIN",multiline=False)
        self.pax=TextInput(text="160",hint_text="PASSENGERS",multiline=False);self.fuel=TextInput(text="0",hint_text="FUEL / KG (optional)",multiline=False)
        for x in (self.cruise,self.reserve,self.pax,self.fuel):grid.add_widget(x)
        box.add_widget(grid);b=_button("CALCULATE",True,42);b.bind(on_press=self.calculate);box.add_widget(b)
        self.dispatch_out=_label("Enter route and performance inputs.",10,TEXT);box.add_widget(self.dispatch_out);box.add_widget(Widget());return box
    def calculate(self,*_):
        try:
            pts=self.points; dist=adv.route_distance(pts) if len(pts)>1 else 0
            gs=450.0; ete=dist/gs*60
            self.dispatch_out.text=("ROUTE %.1f NM\nEST ETE %.0f MIN @ %.0f KT\nCRUISE FL%s • RESERVE %s MIN • PAX %s\n"
                                    "Fuel burn remains aircraft-profile dependent; use SimBrief for dispatch-grade calculations.")%(dist,ete,gs,self.cruise.text,self.reserve.text,self.pax.text)
        except Exception as e:self.dispatch_out.text="CALCULATION ERROR: "+str(e)
    def integrations_tab(self):
        box=BoxLayout(orientation="vertical",spacing=dp(6));box.add_widget(_label("INTEGRATIONS",15,TEXT,True))
        items=[
            ("SIMBRIEF","Import latest OFP by username; generate dispatch in SimBrief and bring the route here."),
            ("NAVIGRAPH","Open your licensed Navigraph Charts workflow. Native Charts/Navigation Data API requires approved developer credentials."),
            ("VATSIM / IVAO","Export the route text for network flight planning; traffic visualization is intentionally excluded."),
            ("MSFS / X-PLANE","Generate standard PLN-style route data from the verified route points."),
            ("AEROFLY","Push the planned route into the companion state for live map/ATC monitoring.")
        ]
        s=ScrollView();g=GridLayout(cols=1,spacing=dp(7),size_hint_y=None);g.bind(minimum_height=g.setter("height"))
        for a,b in items:
            c=BoxLayout(orientation="vertical",padding=dp(10),size_hint_y=None,height=dp(72)); 
            with c.canvas.before: Color(*CARD); c.r=RoundedRectangle(pos=c.pos,size=c.size,radius=[dp(12)])
            c.bind(pos=lambda w,*_:setattr(w.r,"pos",w.pos),size=lambda w,*_:setattr(w.r,"size",w.size));c.add_widget(_label(a,10,ACCENT,True));c.add_widget(_label(b,8,MUTED));g.add_widget(c)
        s.add_widget(g);box.add_widget(s);return box
