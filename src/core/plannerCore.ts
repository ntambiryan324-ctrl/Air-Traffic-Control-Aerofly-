import { AIRCRAFT_PROFILES, resolveAircraft } from '../data/aircraft';
import { lookupAirport } from '../data/airports';
import { DecodedMetar, FlightPlan } from '../types/aviation';

export const NM_PER_KM = 0.539957;

/**
 * Great-circle distance between two coordinates in Nautical Miles
 */
export function distance_nm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dp = p2 - p1;
  const dl = ((lon2 - lon1) * Math.PI) / 180;

  const a =
    Math.sin(dp / 2) ** 2 +
    Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;

  return 2 * 3440.065 * Math.asin(Math.min(1.0, Math.sqrt(a)));
}

/**
 * Initial bearing from (lat1, lon1) to (lat2, lon2) in degrees [0, 360)
 */
export function bearing_deg(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dl = ((lon2 - lon1) * Math.PI) / 180;

  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);

  return ((Math.atan2(y, x) * 180) / Math.PI + 360.0) % 360.0;
}

export function route_distance(points: Array<[number, number]>): number {
  let total = 0;
  for (let i = 0; i < points.length - 1; i++) {
    total += distance_nm(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1]);
  }
  return total;
}

export interface PlanOptions {
  aircraft?: string;
  cruise_fl?: number;
  reserve_min?: number;
  contingency?: number;
  speed_override_kt?: number;
}

export interface PlanResult {
  aircraft: string;
  distance_nm: number;
  cruise_fl: number;
  tas_kt: number;
  toc_nm: number;
  tod_nm: number;
  ete_min: number;
  fuel_trip_kg: number;
  fuel_reserve_kg: number;
  fuel_contingency_kg: number;
  fuel_total_kg: number;
}

export function plan_flight(
  points: Array<[number, number]>,
  aircraft = 'A320',
  cruise_fl?: number,
  reserve_min = 45,
  contingency = 0.05,
  speed_override_kt?: number
): PlanResult {
  const code = resolveAircraft(aircraft);
  const profile = AIRCRAFT_PROFILES[code] || AIRCRAFT_PROFILES.A320;
  let tas = profile.tas_kt;
  const climb_fpm = profile.climb_fpm;
  const desc_fpm = profile.desc_fpm;
  const burn = profile.burn_kg_h;
  const max_fl = profile.max_fl;

  if (speed_override_kt !== undefined && Number.isFinite(speed_override_kt)) {
    if (speed_override_kt >= 40.0 && speed_override_kt <= 700.0) {
      tas = speed_override_kt;
    }
  }

  const dist = route_distance(points);
  let fl = cruise_fl ? Math.floor(cruise_fl) : Math.min(max_fl, tas > 400 ? 360 : 100);
  fl = Math.max(20, Math.min(fl, max_fl));

  let d_climb = 0;
  let d_desc = 0;

  // Shrink cruise level on short routes so climb + descent always fit.
  while (true) {
    const alt = fl * 100.0;
    const t_climb = alt / climb_fpm / 60.0; // hours
    const t_desc = alt / desc_fpm / 60.0; // hours
    d_climb = t_climb * tas * 0.8;
    d_desc = t_desc * tas * 0.85;

    if (d_climb + d_desc <= dist || fl <= 20) {
      break;
    }
    fl -= 10;
  }

  const d_cruise = Math.max(0.0, dist - d_climb - d_desc);
  const t_climb = (fl * 100.0) / climb_fpm / 60.0;
  const t_desc = (fl * 100.0) / desc_fpm / 60.0;
  const t_cruise = tas > 0 ? d_cruise / tas : 0;
  const ete = t_climb + t_cruise + t_desc;

  const fuel_trip = burn * (t_climb * 1.6 + t_cruise + t_desc * 0.4);
  const fuel_reserve = (burn * reserve_min) / 60.0;
  const fuel_cont = fuel_trip * contingency;

  return {
    aircraft: code,
    distance_nm: dist,
    cruise_fl: fl,
    tas_kt: tas,
    toc_nm: d_climb,
    tod_nm: Math.max(0, dist - d_desc),
    ete_min: ete * 60.0,
    fuel_trip_kg: fuel_trip,
    fuel_reserve_kg: fuel_reserve,
    fuel_contingency_kg: fuel_cont,
    fuel_total_kg: fuel_trip + fuel_reserve + fuel_cont,
  };
}

export function vertical_profile(plan: PlanResult, step_nm = 10.0): Array<[number, number]> {
  const dist = plan.distance_nm;
  const fl = plan.cruise_fl;
  const toc = plan.toc_nm;
  const tod = plan.tod_nm;
  const pts: Array<[number, number]> = [];
  let d = 0.0;

  while (d < dist) {
    let alt: number;
    if (d < toc) {
      alt = fl * 100.0 * (toc > 0 ? d / toc : 1.0);
    } else if (d > tod) {
      alt = fl * 100.0 * (dist > tod ? (dist - d) / (dist - tod) : 0.0);
    } else {
      alt = fl * 100.0;
    }
    pts.push([d, Math.max(0.0, alt)]);
    d += step_nm;
  }

  pts.push([dist, 0.0]);
  return pts;
}

export function format_plan(plan: PlanResult, origin: string, dest: string): string {
  const totalMin = Math.round(plan.ete_min);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  const mPad = m.toString().padStart(2, '0');

  return (
    `${origin} > ${dest}   ${plan.aircraft}\n` +
    `DIST ${plan.distance_nm.toFixed(0)} NM   CRUISE FL${plan.cruise_fl}   TAS ${plan.tas_kt} KT\n` +
    `ETE ${h}:${mPad}   TOC ${plan.toc_nm.toFixed(0)} NM   TOD ${plan.tod_nm.toFixed(0)} NM\n` +
    `FUEL trip ${plan.fuel_trip_kg.toFixed(0)}  res ${plan.fuel_reserve_kg.toFixed(0)}  ` +
    `cont ${plan.fuel_contingency_kg.toFixed(0)}  total ${plan.fuel_total_kg.toFixed(0)} KG\n` +
    `Approximate, simulator use only.`
  );
}

/**
 * Decode METAR string with exact AviationWeather fields
 */
export function decode_metar(raw: string): DecodedMetar {
  const clean = (raw || '').trim();
  const out: DecodedMetar = {
    raw: clean,
    wind_dir: null,
    wind_kt: undefined,
    gust_kt: null,
    vis: undefined,
    temp_c: undefined,
    dew_c: undefined,
    qnh_hpa: undefined,
    altim_inhg: undefined,
    time_z: undefined,
  };

  const timeMatch = clean.match(/\b(\d{2})(\d{2})(\d{2})Z\b/);
  if (timeMatch) {
    out.time_z = `${timeMatch[2]}${timeMatch[3]}Z`;
  }

  const windMatch = clean.match(/\b(VRB|\d{3})(\d{2,3})(?:G(\d{2,3}))?KT\b/);
  if (windMatch) {
    out.wind_dir = windMatch[1] === 'VRB' ? null : parseInt(windMatch[1], 10);
    out.wind_kt = parseInt(windMatch[2], 10);
    out.gust_kt = windMatch[3] ? parseInt(windMatch[3], 10) : null;
  }

  const smMatch = clean.match(/\b(\d{1,2}(?: \d\/\d)?)SM\b/);
  if (smMatch) {
    out.vis = `${smMatch[1]} SM`;
  } else {
    const afterKt = clean.includes('KT') ? clean.split('KT')[1] : clean;
    const mMatch = afterKt.match(/\b(\d{4})\b(?!\/)/);
    if (mMatch) {
      out.vis = mMatch[1] === '9999' ? '10 KM' : `${parseInt(mMatch[1], 10)} M`;
    }
  }

  const tempMatch = clean.match(/\b(M?\d{2})\/(M?\d{2})\b/);
  if (tempMatch) {
    const conv = (s: string) => (s.startsWith('M') ? -parseInt(s.substring(1), 10) : parseInt(s, 10));
    out.temp_c = conv(tempMatch[1]);
    out.dew_c = conv(tempMatch[2]);
  }

  const qnhMatch = clean.match(/\bQ(\d{4})\b/);
  if (qnhMatch) {
    out.qnh_hpa = parseInt(qnhMatch[1], 10);
    out.altim_inhg = Number((out.qnh_hpa * 0.02953).toFixed(2));
  } else {
    const altMatch = clean.match(/\bA(\d{4})\b/);
    if (altMatch) {
      out.altim_inhg = parseInt(altMatch[1], 10) / 100.0;
      out.qnh_hpa = Math.round(out.altim_inhg / 0.02953);
    }
  }

  // Determine flight category
  if (out.vis) {
    let visMiles = 10;
    if (out.vis.includes('SM')) {
      visMiles = parseFloat(out.vis);
    } else if (out.vis.includes('KM')) {
      visMiles = 6.2;
    }
    if (visMiles < 1) out.flight_category = 'LIFR';
    else if (visMiles < 3) out.flight_category = 'IFR';
    else if (visMiles <= 5) out.flight_category = 'MVFR';
    else out.flight_category = 'VFR';
  } else {
    out.flight_category = 'VFR';
  }

  return out;
}

export function export_gpx(
  name: string,
  waypoints: Array<[string, number, number]>
): string {
  const pts = waypoints
    .map(
      ([ident, lat, lon]) =>
        `    <rtept lat="${lat.toFixed(6)}" lon="${lon.toFixed(6)}"><name>${ident}</name></rtept>\n`
    )
    .join('');

  return (
    '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<gpx version="1.1" creator="AeroflyATC" xmlns="http://www.topografix.com/GPX/1/1">\n' +
    `  <rte>\n    <name>${name}</name>\n${pts}  </rte>\n</gpx>\n`
  );
}

export function great_circle_points(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
  step_nm = 100.0
): Array<[number, number]> {
  const d = distance_nm(lat1, lon1, lat2, lon2);
  const n = Math.max(1, Math.ceil(d / step_nm));
  const p1 = (lat1 * Math.PI) / 180;
  const l1 = (lon1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const l2 = (lon2 * Math.PI) / 180;
  const delta = d / 3440.065;

  if (delta === 0) return [[lat1, lon1]];

  const pts: Array<[number, number]> = [];
  for (let i = 0; i <= n; i++) {
    const f = i / n;
    const a = Math.sin((1 - f) * delta) / Math.sin(delta);
    const b = Math.sin(f * delta) / Math.sin(delta);
    const x = a * Math.cos(p1) * Math.cos(l1) + b * Math.cos(p2) * Math.cos(l2);
    const y = a * Math.cos(p1) * Math.sin(l1) + b * Math.cos(p2) * Math.sin(l2);
    const z = a * Math.sin(p1) + b * Math.sin(p2);
    const lat = (Math.atan2(z, Math.sqrt(x * x + y * y)) * 180) / Math.PI;
    const lon = (Math.atan2(y, x) * 180) / Math.PI;
    pts.push([lat, lon]);
  }
  return pts;
}
