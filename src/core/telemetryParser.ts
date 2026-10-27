import { TelemetryData } from '../types/aviation';

export class TelemetryParser {
  private data: TelemetryData = {
    connected: false,
    transport: 'WAITING',
    lat: null,
    lon: null,
    alt: 0.0,
    speed: 0.0,
    heading: 0.0,
    pitch: 0.0,
    roll: 0.0,
    vs: 0.0,
    packets: 0,
    message: 'Enter simulator IP and tap CONNECT',
    last: 0,
    sim: '',
  };

  private prevAlt = 0;
  private prevAltTime = 0;

  getSnapshot(): TelemetryData {
    const isStale = Date.now() - this.data.last > 5000;
    return {
      ...this.data,
      connected: isStale ? false : this.data.connected,
    };
  }

  reset(): void {
    this.data = {
      connected: false,
      transport: 'WAITING',
      lat: null,
      lon: null,
      alt: 0.0,
      speed: 0.0,
      heading: 0.0,
      pitch: 0.0,
      roll: 0.0,
      vs: 0.0,
      packets: 0,
      message: 'Enter simulator IP and tap CONNECT',
      last: 0,
      sim: '',
    };
    this.prevAlt = 0;
    this.prevAltTime = 0;
  }

  parseSegment(record: string, transport: string, source: string): boolean {
    const line = record.trim();
    if (!line) return false;

    try {
      if (line.startsWith('XGPS')) {
        const payload = line.substring(4).trim();
        const parts = payload.split(',');
        if (parts.length < 6) return false;

        const sim = parts[0].trim();
        const lon = parseFloat(parts[1]);
        const lat = parseFloat(parts[2]);
        const altMeters = parseFloat(parts[3]);
        const heading = (parseFloat(parts[4]) + 360) % 360;
        const speedMps = parseFloat(parts[5]);

        if (isNaN(lon) || isNaN(lat)) return false;

        const altFt = altMeters * 3.280839895;
        const speedKt = speedMps * 1.943844492;

        const now = Date.now();
        let vs = this.data.vs || 0;
        if (this.prevAltTime > 0 && now > this.prevAltTime) {
          const dtMin = (now - this.prevAltTime) / 60000;
          if (dtMin > 0 && dtMin < 0.1) {
            vs = (altFt - this.prevAlt) / dtMin;
          }
        }
        this.prevAlt = altFt;
        this.prevAltTime = now;

        this.data.sim = sim || 'Aerofly FS Global';
        this.data.lon = lon;
        this.data.lat = lat;
        this.data.alt = Math.round(altFt);
        this.data.heading = Math.round(heading);
        this.data.speed = Math.round(speedKt);
        this.data.vs = Math.round(vs);
        this.data.connected = true;
        this.data.transport = transport;
        this.data.message = `Telemetry received via ${transport} from ${source}`;
        this.data.packets += 1;
        this.data.last = now;
        return true;
      } else if (line.startsWith('XATT')) {
        const payload = line.substring(4).trim();
        const parts = payload.split(',');
        if (parts.length < 2) return false;

        const sim = parts[0].trim();
        const heading = (parseFloat(parts[1]) + 360) % 360;
        const pitch = parts.length >= 3 ? parseFloat(parts[2]) : 0;
        const roll = parts.length >= 4 ? parseFloat(parts[3]) : 0;

        this.data.sim = sim || this.data.sim || 'Aerofly FS Global';
        this.data.heading = Math.round(heading);
        if (!isNaN(pitch)) this.data.pitch = Math.round(pitch * 10) / 10;
        if (!isNaN(roll)) this.data.roll = Math.round(roll * 10) / 10;
        this.data.connected = true;
        this.data.transport = transport;
        this.data.message = `Attitude received via ${transport} from ${source}`;
        this.data.packets += 1;
        this.data.last = Date.now();
        return true;
      }
    } catch {
      return false;
    }
    return false;
  }

  consumeBuffer(buffer: string, chunk: string, source: string, transport = 'TCP 58585'): string {
    let data = (buffer || '') + chunk;

    // Process line-delimited records
    const lines = data.split(/[\r\n]+/);
    if (lines.length > 1) {
      for (let i = 0; i < lines.length - 1; i++) {
        this.parseSegment(lines[i], transport, source);
      }
      data = lines[lines.length - 1];
    }

    // Process concatenated XGPS and XATT records
    const starts: number[] = [];
    for (let i = 0; i < data.length; i++) {
      if (data.startsWith('XGPS', i) || data.startsWith('XATT', i)) {
        starts.push(i);
      }
    }

    if (starts.length > 1) {
      for (let i = 0; i < starts.length - 1; i++) {
        const seg = data.substring(starts[i], starts[i + 1]).trim();
        if (seg) {
          this.parseSegment(seg, transport, source);
        }
      }
      data = data.substring(starts[starts.length - 1]);
    }

    // Whitespace terminated trailing record check
    if (
      (data.startsWith('XGPS') || data.startsWith('XATT')) &&
      (/\s$/.test(data) || data.endsWith('\n') || data.endsWith('\r'))
    ) {
      const needed = data.startsWith('XGPS') ? 5 : 3;
      if ((data.match(/,/g) || []).length >= needed) {
        this.parseSegment(data, transport, source);
        data = '';
      }
    }

    if (data.length > 8192) {
      data = '';
    }

    return data;
  }
}
