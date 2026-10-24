"""Dependency-light Aerofly FS telemetry networking and protocol parsing."""
import re
import socket
import threading
import time


class Telemetry:
    TCP_PORT=58585
    UDP_PORTS=(49002,40092)
    def __init__(self):
        self.host=""
        self.running=False
        self.lock=threading.RLock()
        self.sock=None
        self.data={"connected":False,"transport":"WAITING","lat":None,"lon":None,"alt":0.0,
                   "speed":0.0,"heading":0.0,"packets":0,"message":"Enter simulator IP and tap CONNECT","last":0}
    def start(self):
        if self.running: return
        self.running=True
        threading.Thread(target=self.udp_loop,daemon=True).start()
        threading.Thread(target=self.tcp_loop,daemon=True).start()
    def stop(self):
        self.running=False
        try:
            if self.sock: self.sock.close()
        except OSError: pass

    def reconnect(self, host):
        host = (host or "").strip()
        with self.lock:
            self.host = host
            self.data["connected"] = False
            self.data["message"] = (
                "Connecting to %s:58585 and requesting telemetry" % host
                if host else "Enter simulator IP and tap CONNECT"
            )
        sock = self.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    @staticmethod
    def _request_stream(sock):
        # Aerofly FS Global's mobile FSWidgets endpoint expects a client request.
        sock.sendall(b"GET / HTTP/1.1\r\n\r\n")

    def _parse_tcp_segment(self, segment, source):
        if not segment:
            return
        text = segment.decode("utf-8", "replace") if isinstance(segment, bytes) else str(segment)
        starts = [match.start() for match in re.finditer(r"(?=XGPS|XATT)", text)]
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(text)
            record = text[start:end].strip()
            if record:
                self.parse(record, "TCP 58585", source)

    def _consume_tcp_buffer(self, buffer, chunk, source):
        data = (buffer or b"") + chunk
        # First consume line-framed records and discard unrelated HTTP headers.
        while True:
            match = re.search(rb"[\r\n]", data)
            if match is None:
                break
            self._parse_tcp_segment(data[:match.start()], source)
            data = data[match.end():]
        # Some simulator builds concatenate XGPS and XATT records without newlines.
        starts = [match.start() for match in re.finditer(rb"(?=XGPS|XATT)", data)]
        if len(starts) > 1:
            for index in range(len(starts) - 1):
                self._parse_tcp_segment(data[starts[index]:starts[index + 1]], source)
            data = data[starts[-1]:]
        # A whitespace-terminated trailing record is complete even without CR/LF.
        if data.startswith((b"XGPS", b"XATT")) and data[-1:] in (b" ", b"\t"):
            needed = 5 if data.startswith(b"XGPS") else 3
            if data.count(b",") >= needed:
                self._parse_tcp_segment(data, source)
                data = b""
        # Protect against a corrupt/non-framed stream growing forever.
        if len(data) > 8192:
            starts = [match.start() for match in re.finditer(rb"(?=XGPS|XATT)", data)]
            data = data[starts[-1]:] if starts else b""
        return data

    def parse(self, raw, transport, source):
        txt=raw.decode("utf-8","replace") if isinstance(raw,bytes) else str(raw)
        for line in re.split(r"[\r\n]+",txt):
            line=line.strip()
            try:
                if line.startswith("XGPS"):
                    p=line[4:].strip().split(",")
                    if len(p)<6: continue
                    update={"sim":p[0].strip(),"lon":float(p[1]),"lat":float(p[2]),
                            "alt":float(p[3])*3.280839895,"heading":float(p[4])%360,
                            "speed":float(p[5])*1.943844492}
                elif line.startswith("XATT"):
                    p=line[4:].strip().split(",")
                    if len(p)<4: continue
                    update={"sim":p[0].strip(),"heading":float(p[1])%360}
                else: continue
                with self.lock:
                    self.data.update(update,connected=True,transport=transport,
                        message="Telemetry received via %s from %s"%(transport,source),
                        packets=self.data["packets"]+1,last=time.time())
            except (ValueError,IndexError): pass
    def udp_loop(self):
        while self.running:
            sockets=[]
            for port in self.UDP_PORTS:
                try:
                    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                    s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                    s.bind(("0.0.0.0",port)); s.settimeout(.5); sockets.append((port,s))
                except OSError:
                    try: s.close()
                    except Exception: pass
            if not sockets:
                with self.lock: self.data["message"]="Could not bind UDP 49002/40092; retrying"
                time.sleep(2); continue
            while self.running:
                for port,s in sockets:
                    try:
                        raw,addr=s.recvfrom(65535); self.parse(raw,"UDP "+str(port),addr[0])
                    except socket.timeout: pass
                    except OSError: break
            for _,s in sockets:
                try:s.close()
                except OSError:pass
    def tcp_loop(self):
        while self.running:
            host=self.host.strip()
            if not host:
                time.sleep(1); continue
            s=None
            try:
                s=socket.create_connection((host,self.TCP_PORT),timeout=4); s.settimeout(2); self.sock=s
                self._request_stream(s)
                with self.lock:
                    self.data["connected"] = False
                    self.data["message"] = "TCP connected to %s:%d; stream request sent, waiting for XGPS/XATT"%(host,self.TCP_PORT)
                buf=b""
                while self.running and host==self.host:
                    try:
                        chunk=s.recv(8192)
                        if not chunk:break
                        buf=self._consume_tcp_buffer(buf,chunk,host)
                    except socket.timeout: pass
            except OSError as e:
                with self.lock:
                    if not self.data["connected"]: self.data["message"]="TCP 58585: %s; UDP listeners remain active"%e
            finally:
                try:
                    if s:s.close()
                except OSError:pass
                self.sock=None
            time.sleep(1)
    def snapshot(self):
        with self.lock:d=dict(self.data)
        if time.time()-d["last"]>5:d["connected"]=False
        return d
