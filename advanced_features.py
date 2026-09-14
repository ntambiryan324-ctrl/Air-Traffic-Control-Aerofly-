import json, math, os, threading, time, urllib.parse, urllib.request

def haversine_nm(lat1, lon1, lat2, lon2):
    r=3440.065
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(min(1,math.sqrt(a)))

def initial_bearing(lat1,lon1,lat2,lon2):
    p1=math.radians(lat1); p2=math.radians(lat2); dl=math.radians(lon2-lon1)
    return (math.degrees(math.atan2(math.sin(dl)*math.cos(p2),math.cos(p1)*math.sin(p2)-math.sin(p1)*math.cos(p2)*math.cos(dl)))+360)%360

def route_distance(points):
    return sum(haversine_nm(a,b,c,d) for (a,b),(c,d) in zip(points,points[1:]))

def _json(url, timeout=10):
    req=urllib.request.Request(url,headers={"User-Agent":"AeroflyATC/2.1 mobile companion"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_airport(icao):
    code=icao.strip().upper()
    return _json("https://aviationweather.gov/api/data/airport?ids="+urllib.parse.quote(code)+"&format=json")

def fetch_metar(icao):
    code=icao.strip().upper()
    return _json("https://aviationweather.gov/api/data/metar?ids="+urllib.parse.quote(code)+"&format=json")

def fetch_taf(icao):
    code=icao.strip().upper()
    return _json("https://aviationweather.gov/api/data/taf?ids="+urllib.parse.quote(code)+"&format=json")

def search_airports(query):
    q=urllib.parse.quote(query.strip())
    return _json("https://nominatim.openstreetmap.org/search?q="+q+"&format=json&limit=8&addressdetails=1")

def rainviewer():
    return _json("https://api.rainviewer.com/public/weather-maps.json")

class FlightLogger:
    def __init__(self,path):
        self.path=path
        self.enabled=False
        self.lock=threading.Lock()
    def start(self):
        os.makedirs(os.path.dirname(self.path),exist_ok=True)
        self.enabled=True
    def stop(self):
        self.enabled=False
    def record(self,data):
        if not self.enabled:return
        row={"t":time.time(),"data":dict(data)}
        try:
            with self.lock,open(self.path,"a",encoding="utf-8") as f:
                f.write(json.dumps(row,separators=(",",":"))+"\n")
        except OSError:pass
    def load(self):
        rows=[]
        try:
            with open(self.path,encoding="utf-8") as f:
                for line in f:
                    try: rows.append(json.loads(line))
                    except ValueError: pass
        except OSError: pass
        return rows

class ClearanceTracker:
    def __init__(self):
        self.current={}
        self.readback_ok=False
    def parse(self,text):
        low=text.lower()
        out={"raw":text,"time":time.time()}
        import re
        m=re.search(r"heading(?: of)? (\d{1,3})",low)
        if m:out["heading"]=int(m.group(1))%360
        m=re.search(r"(?:climb|descend)(?: and maintain)? (?:flight level )?(\d{3,5})",low)
        if m:
            n=int(m.group(1));out["altitude_ft"]=n*100 if "flight level" in low else n
        m=re.search(r"(?:squawk|code) (\d{4})",low)
        if m:out["squawk"]=m.group(1)
        m=re.search(r"(\d{3}\.\d{3})",low)
        if m:out["frequency"]=m.group(1)
        self.current=out
        self.readback_ok=False
        return out
    def readback(self,text):
        low=text.lower()
        c=self.current
        checks=[]
        if "heading" in c: checks.append(str(c["heading"]) in low)
        if "altitude_ft" in c: checks.append(str(c["altitude_ft"]) in low or str(c["altitude_ft"]//100) in low)
        if "squawk" in c: checks.append(c["squawk"] in low)
        if "frequency" in c: checks.append(c["frequency"] in low)
        self.readback_ok=bool(checks) and all(checks)
        return self.readback_ok

class FlightAlertEngine:
    def __init__(self):
        self.last={}
    def evaluate(self,d,clearance):
        alerts=[]
        if not d.get("connected"): return alerts
        alt=float(d.get("altitude",0)); spd=float(d.get("speed",0)); vs=float(d.get("vertical_speed",0))
        if clearance.get("altitude_ft") is not None and abs(alt-clearance["altitude_ft"])>300:
            alerts.append("ALTITUDE DEVIATION")
        if clearance.get("heading") is not None:
            delta=abs((float(d.get("heading",0))-clearance["heading"]+180)%360-180)
            if delta>20: alerts.append("HEADING DEVIATION")
        if alt<10000 and spd>250: alerts.append("SPEED > 250 KT BELOW 10,000 FT")
        if alt<3000 and spd>190: alerts.append("HIGH APPROACH SPEED")
        if vs < -1500: alerts.append("HIGH DESCENT RATE")
        return alerts

def nearest_point(lat,lon,points):
    if not points:return None
    return min(points,key=lambda p:haversine_nm(lat,lon,p[0],p[1]))
