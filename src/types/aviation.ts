export interface Airport {
  icao: string;
  name: string;
  lat: number;
  lon: number;
  elevation_ft?: number;
  runways?: string[];
}

export interface AircraftProfile {
  code: string;
  name: string;
  tas_kt: number;
  climb_fpm: number;
  desc_fpm: number;
  burn_kg_h: number;
  max_fl: number;
}

export interface FlightPlan {
  aircraft: string;
  origin: string;
  dest: string;
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
  waypoints: Array<{ ident: string; lat: number; lon: number }>;
}

export interface DecodedMetar {
  raw: string;
  time_z?: string;
  wind_dir?: number | null;
  wind_kt?: number;
  gust_kt?: number | null;
  vis?: string;
  temp_c?: number;
  dew_c?: number;
  qnh_hpa?: number;
  altim_inhg?: number;
  flight_category?: 'VFR' | 'MVFR' | 'IFR' | 'LIFR';
}

export interface TelemetryData {
  connected: boolean;
  transport: string;
  lat: number | null;
  lon: number | null;
  alt: number; // ft MSL
  speed: number; // knots GS
  heading: number; // deg
  pitch?: number; // deg
  roll?: number; // deg
  vs?: number; // ft/min
  packets: number;
  message: string;
  last: number;
  sim?: string;
}

export type ATCPhase =
  | 'PARKED'
  | 'CLEARED'
  | 'TAXI'
  | 'DEPARTING'
  | 'AIRBORNE'
  | 'CRUISE'
  | 'DESCENT'
  | 'APPROACH'
  | 'LANDING';

export interface ATCMessage {
  id: string;
  timestamp: string;
  sender: 'PILOT' | 'ATC' | 'SYSTEM' | 'ATIS';
  callsign: string;
  text: string;
  isReadbackRequired?: boolean;
  isReadbackError?: boolean;
}

export interface LogbookEntry {
  id: string;
  date: string;
  origin: string;
  dest: string;
  aircraft: string;
  minutes: number;
  nm: number;
  max_alt: number;
  notes?: string;
}

export interface RadioState {
  com1Active: number;
  com1Standby: number;
  com2Active: number;
  com2Standby: number;
  activeRadio: 'COM1' | 'COM2';
  squawk: string;
  transponderMode: 'STBY' | 'ON' | 'ALT';
}
