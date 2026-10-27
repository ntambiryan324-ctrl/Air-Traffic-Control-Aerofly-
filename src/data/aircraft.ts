import { AircraftProfile } from '../types/aviation';

export const AIRCRAFT_PROFILES: Record<string, AircraftProfile> = {
  A320: {
    code: 'A320',
    name: 'Airbus A320-200',
    tas_kt: 450,
    climb_fpm: 2200,
    desc_fpm: 2000,
    burn_kg_h: 2500,
    max_fl: 390,
  },
  B738: {
    code: 'B738',
    name: 'Boeing 737-800',
    tas_kt: 450,
    climb_fpm: 2200,
    desc_fpm: 2000,
    burn_kg_h: 2500,
    max_fl: 410,
  },
  B77W: {
    code: 'B77W',
    name: 'Boeing 777-300ER',
    tas_kt: 490,
    climb_fpm: 1800,
    desc_fpm: 2000,
    burn_kg_h: 7500,
    max_fl: 430,
  },
  B789: {
    code: 'B789',
    name: 'Boeing 787-9 Dreamliner',
    tas_kt: 490,
    climb_fpm: 2000,
    desc_fpm: 2000,
    burn_kg_h: 5400,
    max_fl: 430,
  },
  A359: {
    code: 'A359',
    name: 'Airbus A350-900',
    tas_kt: 490,
    climb_fpm: 2000,
    desc_fpm: 2000,
    burn_kg_h: 5800,
    max_fl: 410,
  },
  A35K: {
    code: 'A35K',
    name: 'Airbus A350-1000',
    tas_kt: 490,
    climb_fpm: 2000,
    desc_fpm: 2000,
    burn_kg_h: 6000,
    max_fl: 410,
  },
  A388: {
    code: 'A388',
    name: 'Airbus A380-800',
    tas_kt: 490,
    climb_fpm: 1500,
    desc_fpm: 2000,
    burn_kg_h: 11500,
    max_fl: 430,
  },
  DH8D: {
    code: 'DH8D',
    name: 'Bombardier Dash 8 Q400',
    tas_kt: 285,
    climb_fpm: 1500,
    desc_fpm: 1500,
    burn_kg_h: 1000,
    max_fl: 250,
  },
  CRJ9: {
    code: 'CRJ9',
    name: 'Bombardier CRJ-900',
    tas_kt: 430,
    climb_fpm: 2500,
    desc_fpm: 2000,
    burn_kg_h: 2100,
    max_fl: 410,
  },
  LJ45: {
    code: 'LJ45',
    name: 'Bombardier Learjet 45',
    tas_kt: 450,
    climb_fpm: 3000,
    desc_fpm: 2500,
    burn_kg_h: 900,
    max_fl: 510,
  },
  C172: {
    code: 'C172',
    name: 'Cessna 172 Skyhawk',
    tas_kt: 110,
    climb_fpm: 700,
    desc_fpm: 500,
    burn_kg_h: 23,
    max_fl: 130,
  },
  BE58: {
    code: 'BE58',
    name: 'Beechcraft Baron 58',
    tas_kt: 180,
    climb_fpm: 1500,
    desc_fpm: 800,
    burn_kg_h: 65,
    max_fl: 200,
  },
};

export const AIRCRAFT_ALIASES: Record<string, string> = {
  A350: 'A35K',
  'A350-1000': 'A35K',
  'A350-900': 'A359',
  A380: 'A388',
  B777: 'B77W',
  '777': 'B77W',
  B787: 'B789',
  '787': 'B789',
  Q400: 'DH8D',
  'DASH 8': 'DH8D',
  'LEARJET 45': 'LJ45',
  'CESSNA 172': 'C172',
  'BARON 58': 'BE58',
  'CRJ-900': 'CRJ9',
  CRJ900: 'CRJ9',
  B737: 'B738',
  '737': 'B738',
};

export function resolveAircraft(text: string): string {
  const key = (text || '').trim().toUpperCase();
  if (AIRCRAFT_PROFILES[key]) return key;
  if (AIRCRAFT_ALIASES[key]) return AIRCRAFT_ALIASES[key];
  for (const [name, code] of Object.entries(AIRCRAFT_ALIASES)) {
    if (key.includes(name)) return code;
  }
  return 'A320';
}
