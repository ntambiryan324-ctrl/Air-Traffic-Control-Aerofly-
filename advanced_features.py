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

KNOWN_AIRPORTS = {
 "HUEN":(0.0424,32.4435,"Entebbe International"),"HKJK":(-1.3192,36.9278,"Jomo Kenyatta"),
 "FAOR":(-26.1367,28.2411,"O.R. Tambo"),"EGLL":(51.4700,-0.4543,"London Heathrow"),
 "EHAM":(52.3105,4.7683,"Amsterdam Schiphol"),"EDDF":(50.0379,8.5622,"Frankfurt"),
 "LFPG":(49.0097,2.5479,"Paris Charles de Gaulle"),"OMDB":(25.2532,55.3657,"Dubai International"),
 "KJFK":(40.6413,-73.7781,"John F Kennedy"),"KLAX":(33.9425,-118.4081,"Los Angeles"),
 "KSFO":(37.6213,-122.3790,"San Francisco"),"KORD":(41.9742,-87.9073,"Chicago O'Hare"),
 "KATL":(33.6407,-84.4277,"Atlanta"),"RJTT":(35.5494,139.7798,"Tokyo Haneda"),
 "YSSY":(-33.9399,151.1753,"Sydney")
}
def nearest_airport(lat,lon):
    if not KNOWN_AIRPORTS:return None
    return min(((haversine_nm(lat,lon,a,b),icao,name,a,b) for icao,(a,b,name) in KNOWN_AIRPORTS.items()),key=lambda x:x[0])


def _csv_rows(url):
    import csv, io
    req=urllib.request.Request(url,headers={"User-Agent":"AeroflyATC/2.2"})
    with urllib.request.urlopen(req,timeout=12) as r:
        return list(csv.DictReader(io.TextIOWrapper(r,"utf-8")))

def nearby_airports(lat,lon,radius_nm=8):
    try:
        rows=_csv_rows("https://davidmegginson.github.io/ourairports-data/airports.csv")
        out=[]
        for x in rows:
            try:
                a=float(x.get("latitude_deg") or 0);b=float(x.get("longitude_deg") or 0)
                dist=haversine_nm(lat,lon,a,b)
                if dist<=radius_nm:
                    out.append({"ident":x.get("ident") or x.get("gps_code") or x.get("local_code") or "----",
                                "name":x.get("name") or "Airport","lat":a,"lon":b,
                                "elevation_ft":x.get("elevation_ft") or ""})
            except (ValueError,TypeError): continue
        return sorted(out,key=lambda x:haversine_nm(lat,lon,x["lat"],x["lon"]))[:40]
    except Exception:
        return [{"ident":k,"name":v[2],"lat":v[0],"lon":v[1]} for k,v in KNOWN_AIRPORTS.items()
                if haversine_nm(lat,lon,v[0],v[1])<=radius_nm]

def nearby_navaids(lat,lon,radius_nm=30):
    try:
        rows=_csv_rows("https://davidmegginson.github.io/ourairports-data/navaids.csv")
        out=[]
        for x in rows:
            try:
                a=float(x.get("latitude_deg") or 0);b=float(x.get("longitude_deg") or 0)
                if haversine_nm(lat,lon,a,b)<=radius_nm:
                    out.append({"ident":x.get("ident") or "NAVAID","name":x.get("name") or "",
                                "lat":a,"lon":b,"type":x.get("type") or ""})
            except (ValueError,TypeError): continue
        return out[:60]
    except Exception:return []

def fetch_airspaces(lat,lon,radius_nm=50,api_key=""):
    if not api_key:return []
    try:
        # OpenAIP is optional because its API requires the user's own key.
        url="https://api.core.openaip.net/api/airspaces?bbox=%f,%f,%f,%f&limit=100" % (
            lon-radius_nm/60,lat-radius_nm/60,lon+radius_nm/60,lat+radius_nm/60)
        req=urllib.request.Request(url,headers={"User-Agent":"AeroflyATC/2.2","x-openaip-api-key":api_key})
        with urllib.request.urlopen(req,timeout=12) as r:
            data=json.loads(r.read().decode())
        out=[]
        for x in data.get("items",data if isinstance(data,list) else []):
            out.append({"name":x.get("name","AIRSPACE"),"lower":str(x.get("lowerCeiling","")),
                        "upper":str(x.get("upperCeiling",""))})
        return out
    except Exception:return []


def terrain_elevation(lat, lon):
    """Free worldwide 90m Copernicus DEM via Open-Meteo; no API key."""
    try:
        q=urllib.parse.urlencode({"latitude":lat,"longitude":lon})
        req=urllib.request.Request("https://api.open-meteo.com/v1/elevation?"+q,
            headers={"User-Agent":"AeroflyATC/2.2"})
        with urllib.request.urlopen(req,timeout=8) as r:
            d=json.loads(r.read().decode())
        vals=d.get("elevation") or []
        return float(vals[0]) if vals else None
    except Exception:
        return None

def terrain_profile(lat,lon,heading_deg,distance_nm=20,samples=21):
    """Sample terrain ahead along the aircraft track."""
    out=[]
    R=3440.065
    h=math.radians(heading_deg)
    for i in range(samples):
        d=distance_nm*i/(samples-1)
        dr=d/R
        la=math.asin(math.sin(math.radians(lat))*math.cos(dr)+
                     math.cos(math.radians(lat))*math.sin(dr)*math.cos(h))
        lo=math.radians(lon)+math.atan2(math.sin(h)*math.sin(dr)*math.cos(math.radians(lat)),
                                        math.cos(dr)-math.sin(math.radians(lat))*math.sin(la))
        e=terrain_elevation(math.degrees(la),math.degrees(lo))
        out.append({"distance_nm":d,"lat":math.degrees(la),"lon":math.degrees(lo),"elevation_ft":e})
    return out

def terrain_conflict(aircraft_alt_ft,lat,lon,heading_deg,agl_margin_ft=1000):
    profile=terrain_profile(lat,lon,heading_deg)
    valid=[p for p in profile if p["elevation_ft"] is not None]
    if not valid:return {"status":"UNKNOWN","reason":"terrain data unavailable"}
    clearance=[aircraft_alt_ft-p["elevation_ft"] for p in valid]
    min_clear=min(clearance)
    worst=valid[clearance.index(min_clear)]
    if min_clear < 0:return {"status":"CRITICAL","clearance_ft":min_clear,"distance_nm":worst["distance_nm"]}
    if min_clear < agl_margin_ft:return {"status":"WARNING","clearance_ft":min_clear,"distance_nm":worst["distance_nm"]}
    return {"status":"CLEAR","clearance_ft":min_clear,"distance_nm":worst["distance_nm"]}


# AIRAC navigation-data service. The public AIRAC API is cycle-aware and returns
# current worldwide waypoints, navaids, airways, airports and procedures.
AIRAC_BASE = "https://airac.net/api/v1"

def _airac_get(path, params=None):
    try:
        q=urllib.parse.urlencode(params or {}, doseq=True)
        url=AIRAC_BASE+path+("?" + q if q else "")
        req=urllib.request.Request(url, headers={
            "Accept":"application/json",
            "User-Agent":"AeroflyATC/2.2 (Aerofly mobile ATC companion)"
        })
        with urllib.request.urlopen(req,timeout=12) as r:
            payload=json.loads(r.read().decode())
            cycle=r.headers.get("X-AIRAC-Cycle")
        return payload,cycle
    except Exception:
        return None,None

def current_airac():
    data,cycle=_airac_get("/airac/current")
    return (data or {}).get("data",data),cycle

def nearby_navdata(lat,lon,radius_nm=30):
    result={"waypoints":[],"navaids":[],"airports":[],"airways":[],"cycle":None}
    for kind in ("waypoints","navaids","airports"):
        data,cycle=_airac_get("/"+kind+"/nearby",{
            "latitude":lat,"longitude":lon,"radius":radius_nm
        })
        if data:
            result[kind]=data.get("data",[]) if isinstance(data,dict) else data
        result["cycle"]=cycle or result["cycle"]
    return result

def search_navdata(query):
    data,cycle=_airac_get("/search",{"q":query,"limit":20})
    return (data or {}).get("data",data),cycle

def airway_for_fix(fix):
    data,cycle=_airac_get("/airways",{"fix":fix})
    return (data or {}).get("data",data),cycle

def parse_route(origin,destination,route,departure_runway="",arrival_runway=""):
    params={"origin":origin,"destination":destination,"route":route}
    if departure_runway: params["departure_runway"]=departure_runway
    if arrival_runway: params["arrival_runway"]=arrival_runway
    data,cycle=_airac_get("/routes/parse",params)
    return (data or {}).get("data",data),cycle

def airport_procedures(airport,procedure_type=None):
    p={"airport":airport}
    if procedure_type:p["type"]=procedure_type
    data,cycle=_airac_get("/procedures",p)
    return (data or {}).get("data",data),cycle

def route_direct_instruction(fix, lat, lon):
    data,cycle=search_navdata(fix)
    matches=[]
    if isinstance(data,dict):
        for k in ("waypoints","navaids","airports"):
            matches.extend(data.get(k,[]) or [])
    elif isinstance(data,list):
        matches=data
    if not matches:
        return {"ok":False,"reason":"fix_not_found","cycle":cycle}
    best=None;best_dist=1e9
    for x in matches:
        co=x.get("coordinates",{})
        la=co.get("lat",x.get("latitude"))
        lo=co.get("lon",x.get("longitude"))
        if la is None or lo is None:continue
        d=haversine_nm(lat,lon,float(la),float(lo))
        if d<best_dist:
            best_dist=d;best=x
    if not best:return {"ok":False,"reason":"coordinates_unavailable","cycle":cycle}
    return {"ok":True,"instruction":"DIRECT "+str(best.get("identifier") or best.get("icao") or fix),
            "fix":best,"distance_nm":round(best_dist,1),"cycle":cycle}
