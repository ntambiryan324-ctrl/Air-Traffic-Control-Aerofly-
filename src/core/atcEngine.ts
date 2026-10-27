import { lookupAirport } from '../data/airports';
import { DecodedMetar } from '../types/aviation';
import { bearing_deg, decode_metar, distance_nm } from './plannerCore';

const WORDS: Record<string, string> = {
  zero: '0',
  one: '1',
  two: '2',
  three: '3',
  tree: '3',
  four: '4',
  five: '5',
  fife: '5',
  six: '6',
  seven: '7',
  eight: '8',
  nine: '9',
  niner: '9',
  ten: '10',
  left: 'l',
  right: 'r',
  center: 'c',
  centre: 'c',
};

export function normalize(text: string): string {
  let s = (text || '').toLowerCase().replace(/,/g, '');
  s = s.replace(/flight\s*level/g, 'fl');
  s = s.replace(/[^a-z0-9 ]/g, ' ');
  s = s
    .split(/\s+/)
    .map((w) => WORDS[w] || w)
    .join(' ');
  // Combine digits: "4 5 2 1" -> "4521"
  s = s.replace(/(?<=\d) (?=\d)/g, '');
  // Combine runway letter: "28 l" -> "28l"
  s = s.replace(/(?<=\d) (?=[lrc]\b)/g, '');
  // "5 thousand" -> "5000"
  s = s.replace(/(\d+) thousand/g, (_, g1) => `${g1}000`);
  s = s.replace(/fl (\d+)/g, 'fl$1');
  return s.trim();
}

function escapeRegex(string: string): string {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function contains_token(norm_text: string, token: string): boolean {
  const t = normalize(token);
  if (!t) return false;
  const regex = new RegExp(`(?<![a-z0-9])${escapeRegex(t)}(?![a-z0-9])`, 'i');
  return regex.test(norm_text);
}

export interface ATCSnapshot {
  lat?: number | null;
  lon?: number | null;
  alt_ft?: number;
  speed_kt?: number;
  heading?: number;
}

export class ATCEngine {
  callsign = 'N123AB';
  phase:
    | 'PARKED'
    | 'CLEARED'
    | 'TAXI'
    | 'DEPARTING'
    | 'AIRBORNE'
    | 'CRUISE'
    | 'DESCENT'
    | 'APPROACH'
    | 'LANDING' = 'PARKED';
  origin = '';
  dest = '';
  cruise_fl = 360;
  metar: DecodedMetar = { raw: '' };
  metar_icao = '';
  squawk: string | null = null;
  dep_runway = '';
  arr_runway = '';
  runways: Record<string, string[]> = {};
  pending: Record<string, string> = {};
  last_reply = '';
  llm: { respond: (prompt: string, context?: any) => Promise<string> | string } | null = null;

  constructor(llm: any = null) {
    this.llm = llm;
  }

  set_plan(origin: string, dest: string, cruise_fl?: number): void {
    this.origin = (origin || '').toUpperCase().trim();
    this.dest = (dest || '').toUpperCase().trim();
    if (cruise_fl) {
      this.cruise_fl = Math.floor(cruise_fl);
    }
    this.squawk = null;
  }

  set_callsign(callsign: string): void {
    if (callsign && callsign.trim()) {
      this.callsign = callsign.trim().toUpperCase();
    }
  }

  set_metar(icao: string, raw: string): void {
    this.metar_icao = (icao || '').toUpperCase().trim();
    this.metar = decode_metar(raw || '');
  }

  set_runways(icao: string, idents: string[]): void {
    this.runways[icao.toUpperCase()] = [...idents];
  }

  private _make_squawk(): string {
    // Generate deterministic yet pseudo-random 4-digit octal code based on callsign and route
    let seed = 0;
    const str = `${this.callsign}${this.origin}${this.dest}${Date.now()}`;
    for (let i = 0; i < str.length; i++) {
      seed = (seed * 31 + str.charCodeAt(i)) & 0xffffffff;
    }
    const banned = new Set(['7500', '7600', '7700', '1200', '0000']);
    for (let attempt = 0; attempt < 50; attempt++) {
      let code = '';
      for (let digit = 0; digit < 4; digit++) {
        seed = (seed * 1664525 + 1013904223) & 0xffffffff;
        const octalDigit = Math.abs(seed) % 8;
        code += octalDigit.toString();
      }
      if (!banned.has(code)) {
        return code;
      }
    }
    return '4521';
  }

  private _wind_phrase(): string {
    const m = this.metar;
    if (!m || m.wind_kt === undefined || m.wind_kt === null) {
      return 'wind not available';
    }
    if (m.wind_kt === 0) {
      return 'wind calm';
    }
    const d = m.wind_dir === null ? 'variable' : m.wind_dir.toString().padStart(3, '0');
    const g = m.gust_kt ? `, gusting ${m.gust_kt}` : '';
    return `wind ${d} at ${m.wind_kt}${g}`;
  }

  private _altimeter(): [string | null, string | null] {
    const m = this.metar;
    if (!m || (m.qnh_hpa === undefined && m.altim_inhg === undefined)) {
      return [null, null];
    }
    if (m.raw && /\bQ\d{4}\b/.test(m.raw)) {
      return [`QNH ${m.qnh_hpa}`, `${m.qnh_hpa}`];
    }
    if (m.altim_inhg !== undefined) {
      const code = Math.round(m.altim_inhg * 100)
        .toString()
        .padStart(4, '0');
      return [`altimeter ${code}`, code];
    }
    return [null, null];
  }

  private _pick_runway(icao: string, manual?: string): string {
    if (manual) return manual;
    const idents = this.runways[icao.toUpperCase()];
    if (!idents || idents.length === 0) return '';
    const wd = this.metar?.wind_dir;
    const ws = this.metar?.wind_kt || 0;
    if (wd === null || wd === undefined || ws === 0) {
      return idents[0];
    }

    const headwind = (r: string) => {
      const match = r.match(/\d+/);
      if (!match) return 0;
      const hdg = parseInt(match[0], 10) * 10;
      const rad = ((wd - hdg) * Math.PI) / 180;
      return ws * Math.cos(rad);
    };

    let bestRwy = idents[0];
    let maxHw = -Infinity;
    for (const r of idents) {
      const hw = headwind(r);
      if (hw > maxHw) {
        maxHw = hw;
        bestRwy = r;
      }
    }
    return bestRwy;
  }

  event(name: string): string {
    const cs = this.callsign;
    if (name === 'takeoff') {
      this.phase = 'AIRBORNE';
      this.pending = {};
      return `DEPARTURE: ${cs}, radar contact. Continue climb, expect FL${this.cruise_fl}.`;
    }
    if (name === 'top_of_descent') {
      this.phase = 'DESCENT';
      return `CENTER: ${cs}, descend at pilot's discretion. Expect approach into ${this.dest || 'destination'}. Fetch destination weather in PLAN.`;
    }
    if (name === 'approach') {
      return `APPROACH: ${cs}, radar contact. Say 'inbound' for approach instructions.`;
    }
    if (name === 'landing') {
      this.phase = 'PARKED';
      this.pending = {};
      return `GROUND: ${cs}, welcome to ${this.dest || 'the field'}. Taxi to the gate via taxiways as published.`;
    }
    return '';
  }

  atis(icao?: string): string {
    const code = (icao || this.metar_icao || this.origin).toUpperCase();
    if (!this.metar || !this.metar.raw) {
      return 'No weather loaded. Fetch weather in PLAN first.';
    }
    const m = this.metar;
    const hour = parseInt((m.time_z || '0000Z').substring(0, 2), 10) || 0;
    const letter = String.fromCharCode('A'.charCodeAt(0) + (hour % 24));
    const parts = [
      `${code} information ${letter}`,
      `time ${m.time_z || 'unknown'}`,
      this._wind_phrase(),
    ];
    if (m.vis) parts.push(`visibility ${m.vis}`);
    if (m.temp_c !== undefined && m.dew_c !== undefined) {
      parts.push(`temperature ${m.temp_c}, dew point ${m.dew_c}`);
    }
    const [alt] = this._altimeter();
    if (alt) parts.push(alt);
    parts.push(`advise on initial contact you have information ${letter}`);
    return `ATIS: ${parts.join('. ')}.`;
  }

  handle(text: string, snapshot: ATCSnapshot = {}): string {
    const raw = (text || '').trim();
    if (!raw) return '';
    const norm = normalize(raw);
    const reply = this._dispatch(raw, norm, snapshot);
    this.last_reply = reply;
    return reply;
  }

  private static _is_request(n: string): boolean {
    const keys = [
      'request',
      'ready',
      'inbound',
      'taxi',
      'atis',
      'weather',
      'altimeter',
      'qnh',
      'direct',
      'mayday',
      'pan pan',
      'say again',
      'repeat',
      'radio check',
      'clearance',
      'squawk',
      'approach',
      'land',
      'push',
      'takeoff',
    ];
    return keys.some((k) => n.includes(k));
  }

  private _check_readback(n: string): string {
    const cs = this.callsign;
    const missing: string[] = [];
    for (const [k, v] of Object.entries(this.pending)) {
      if (!contains_token(n, v)) {
        missing.push(`${k} ${v}`);
      }
    }
    if (missing.length > 0) {
      return `CONTROL: ${cs}, negative. I need a readback of: ${missing.join(', ')}.`;
    }
    this.pending = {};
    return `CONTROL: ${cs}, readback correct.`;
  }

  private _clearance(): string {
    const cs = this.callsign;
    if (!this.dest) {
      return `CLEARANCE: ${cs}, say destination. Set it in PLAN first.`;
    }
    this.squawk = this._make_squawk();
    this.phase = 'CLEARED';
    this.pending = { squawk: this.squawk, altitude: '5000' };
    return (
      `CLEARANCE: ${cs}, cleared to ${this.dest} airport as filed. Climb and maintain 5000, ` +
      `expect FL${this.cruise_fl} ten minutes after departure. Squawk ${this.squawk}.`
    );
  }

  private _taxi(): string {
    const cs = this.callsign;
    const rwy = this._pick_runway(this.origin, this.dep_runway);
    if (!rwy) {
      return `GROUND: ${cs}, runway in use is not known. Say 'runway 28L' (your runway) and request taxi again.`;
    }
    this.dep_runway = rwy;
    this.phase = 'TAXI';
    const [alt] = this._altimeter();
    this.pending = { runway: rwy };
    const extra = alt ? ` ${alt}.` : '';
    return `GROUND: ${cs}, taxi to runway ${rwy} via taxiways as published, hold short.${extra}`;
  }

  private _takeoff(): string {
    const cs = this.callsign;
    const rwy = this._pick_runway(this.origin, this.dep_runway);
    if (!rwy) {
      return `TOWER: ${cs}, say runway.`;
    }
    this.phase = 'DEPARTING';
    this.pending = { runway: rwy };
    return `TOWER: ${cs}, ${this._wind_phrase()}, runway ${rwy}, cleared for takeoff.`;
  }

  private _approach(): string {
    const cs = this.callsign;
    this.phase = 'APPROACH';
    const rwy = this._pick_runway(this.dest, this.arr_runway);
    if (!rwy) {
      return `APPROACH: ${cs}, runway in use is not known. Say 'runway 28L' for your arrival runway.`;
    }
    this.arr_runway = rwy;
    const [alt, token] = this._altimeter();
    this.pending = { runway: rwy };
    if (token) {
      this.pending['altimeter'] = token;
    }
    const extra = alt ? ` ${alt}.` : '';
    return `APPROACH: ${cs}, expect runway ${rwy}, report established.${extra}`;
  }

  private _landing(snap: ATCSnapshot): string {
    const cs = this.callsign;
    const rwy = this._pick_runway(this.dest, this.arr_runway);
    if (!rwy) {
      return `TOWER: ${cs}, say runway.`;
    }
    const destAp = lookupAirport(this.dest);
    if (destAp && snap.lat !== undefined && snap.lat !== null && snap.lon !== undefined && snap.lon !== null) {
      const d = distance_nm(snap.lat, snap.lon, destAp.lat, destAp.lon);
      if (d > 15) {
        return `TOWER: ${cs}, continue approach, ${d.toFixed(0)} miles out. Report 10 mile final.`;
      }
    }
    this.phase = 'LANDING';
    this.pending = { runway: rwy };
    return `TOWER: ${cs}, ${this._wind_phrase()}, runway ${rwy}, cleared to land.`;
  }

  private _direct(ident: string, snap: ATCSnapshot): string {
    const cs = this.callsign;
    const ap = lookupAirport(ident);
    if (!ap) {
      return `CENTER: ${cs}, unable direct ${ident}. It is not in the loaded database.`;
    }
    if (snap.lat !== undefined && snap.lat !== null && snap.lon !== undefined && snap.lon !== null) {
      const brg = bearing_deg(snap.lat, snap.lon, ap.lat, ap.lon);
      const dist = distance_nm(snap.lat, snap.lon, ap.lat, ap.lon);
      return `CENTER: ${cs}, proceed direct ${ident}. Bearing ${brg.toFixed(0).padStart(3, '0')}, ${dist.toFixed(0)} miles.`;
    }
    return `CENTER: ${cs}, proceed direct ${ident}.`;
  }

  private _altitude(token: string): string {
    const cs = this.callsign;
    const t = normalize(token);
    let value = '';
    if (t.startsWith('fl')) {
      const level = parseInt(t.substring(2), 10);
      if (level > 450 || level < 10) {
        return `CENTER: ${cs}, unable FL${level.toString().padStart(3, '0')}.`;
      }
      value = `FL${level}`;
    } else {
      const feet = parseInt(t.replace(/\D/g, ''), 10);
      if (feet > 45000) {
        return `CENTER: ${cs}, unable ${feet}.`;
      }
      value = feet.toString();
    }
    this.pending = { altitude: value };
    return `CENTER: ${cs}, climb or descend and maintain ${value}.`;
  }

  private _dispatch(raw: string, n: string, snap: ATCSnapshot): string {
    const cs = this.callsign;

    // Distress / urgency
    if (n.includes('mayday') || n.includes('pan pan') || n.includes('emergency')) {
      const kind = n.includes('mayday') ? 'mayday' : 'pan-pan';
      const rwy = this._pick_runway(this.dest || this.origin, this.arr_runway);
      const tail = rwy ? ` Runway ${rwy} is available.` : '';
      return (
        `CONTROL: ${cs}, roger ${kind}. Say nature of emergency, souls on board and fuel remaining. ` +
        `All other traffic is being kept clear.${tail}`
      );
    }

    // Runway specification
    const rwyMatch = n.match(/runway (\d{1,2}[lrc]?)\b/);
    let ident: string | null = null;
    if (rwyMatch) {
      ident = rwyMatch[1].toUpperCase();
      if (['PARKED', 'CLEARED', 'TAXI'].includes(this.phase)) {
        this.dep_runway = ident;
      } else {
        this.arr_runway = ident;
      }
    }

    if (Object.keys(this.pending).length > 0) {
      const echoes = Object.values(this.pending).some((v) => contains_token(n, v));
      const explicit = n.includes('request') || n.includes('ready');
      if ((echoes && !explicit) || !ATCEngine._is_request(n)) {
        return this._check_readback(n);
      }
    }

    if (ident && !ATCEngine._is_request(n)) {
      return `CONTROL: ${cs}, runway ${ident} noted.`;
    }

    if (n.includes('say again') || n.includes('repeat')) {
      return this.last_reply || `CONTROL: ${cs}, nothing to repeat.`;
    }

    if (n.includes('radio check')) {
      return `CONTROL: ${cs}, loud and clear.`;
    }

    if (n.includes('atis') || n.includes('weather') || ['wx', 'metar'].includes(n.trim())) {
      return this.atis();
    }

    if (n.includes('altimeter') || n.includes('qnh')) {
      const [alt] = this._altimeter();
      return alt ? `CONTROL: ${cs}, ${alt}.` : `CONTROL: ${cs}, altimeter not available.`;
    }

    if (n.includes('squawk')) {
      if (!this.squawk) {
        this.squawk = this._make_squawk();
      }
      this.pending = { squawk: this.squawk };
      return `CONTROL: ${cs}, squawk ${this.squawk}.`;
    }

    if (n.includes('clearance') || n.includes('ifr')) {
      return this._clearance();
    }

    if (n.includes('taxi') || n.includes('push')) {
      return this._taxi();
    }

    if (['ready', 'takeoff', 'take off', 'departure'].some((k) => n.includes(k))) {
      return this._takeoff();
    }

    if (['inbound', 'approach', 'ils', 'visual'].some((k) => n.includes(k))) {
      return this._approach();
    }

    if (/\bland(ing)?\b/.test(n)) {
      return this._landing(snap);
    }

    const dMatch = n.match(/direct (?:to )?([a-z0-9]{2,7})/);
    if (dMatch) {
      return this._direct(dMatch[1].toUpperCase(), snap);
    }

    const altMatch = n.match(/\bfl(\d{2,3})\b/) || n.match(/\b(\d{4,5}) ?(?:ft|feet)\b/);
    if (
      altMatch &&
      ['climb', 'descend', 'descent', 'request', 'level'].some((k) => n.includes(k))
    ) {
      return this._altitude(altMatch[0]);
    }

    if (this.llm) {
      try {
        const res = this.llm.respond(raw, {
          phase: this.phase,
          origin: this.origin,
          dest: this.dest,
          metar: this.metar.raw,
          squawk: this.squawk,
          aircraft: snap,
        });
        if (typeof res === 'string' && res.trim()) {
          return res;
        }
      } catch {
        // Fallback
      }
    }

    return `CONTROL: ${cs}, say again, request not understood.`;
  }
}
