import { LogbookEntry, TelemetryData } from '../types/aviation';
import { distance_nm } from './plannerCore';

export interface FlightMonitorSnapshot {
  connected: boolean;
  lat: number | null;
  lon: number | null;
  speed_kt: number;
  alt_ft: number;
}

export class FlightMonitor {
  origin = '';
  dest = '';
  dest_pos: [number, number] | null = null;
  tod_remaining_nm: number | null = null;
  ref_alt: number | null = null;

  airborne = false;
  t_off: number | null = null;
  nm = 0.0;
  max_alt = 0.0;
  last_pos: [number, number] | null = null;

  private eventsFired = new Set<string>();
  private logbookEntries: LogbookEntry[] = [];

  constructor(initialEntries: LogbookEntry[] = []) {
    this.logbookEntries = [...initialEntries];
  }

  set_plan(
    origin: string,
    dest: string,
    dest_pos?: [number, number],
    tod_remaining_nm?: number
  ): void {
    this.origin = (origin || '').toUpperCase().trim();
    this.dest = (dest || '').toUpperCase().trim();
    this.dest_pos = dest_pos || null;
    this.tod_remaining_nm = tod_remaining_nm !== undefined ? tod_remaining_nm : null;
    this.reset_flight();
  }

  reset_flight(): void {
    this.airborne = false;
    this.t_off = null;
    this.nm = 0.0;
    this.max_alt = 0.0;
    this.last_pos = null;
    this.eventsFired.clear();
  }

  getLogbook(): LogbookEntry[] {
    return [...this.logbookEntries];
  }

  addManualEntry(entry: Omit<LogbookEntry, 'id'>): LogbookEntry {
    const newEntry: LogbookEntry = {
      ...entry,
      id: `log-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
    };
    this.logbookEntries.unshift(newEntry);
    return newEntry;
  }

  update(snap: FlightMonitorSnapshot, now: number = Date.now()): string[] {
    if (!snap.connected || snap.lat === null || snap.lon === null) {
      return [];
    }

    const events: string[] = [];
    const lat = snap.lat;
    const lon = snap.lon;
    const speed = snap.speed_kt;
    const alt = snap.alt_ft;

    // Track distance and max altitude while airborne
    if (this.airborne) {
      if (alt > this.max_alt) {
        this.max_alt = alt;
      }
      if (this.last_pos) {
        const d = distance_nm(this.last_pos[0], this.last_pos[1], lat, lon);
        if (d < 100) {
          // ignore teleport / reset jumps
          this.nm += d;
        }
      }
    }
    this.last_pos = [lat, lon];

    // Establish reference ground elevation
    if (this.ref_alt === null) {
      this.ref_alt = alt;
    } else if (!this.airborne && speed < 30) {
      this.ref_alt = alt;
    }

    // TAKEOFF check
    if (!this.airborne && speed > 100 && alt > (this.ref_alt || 0) + 200) {
      this.airborne = true;
      this.t_off = now;
      this.max_alt = alt;
      if (!this.eventsFired.has('takeoff')) {
        this.eventsFired.add('takeoff');
        events.push('takeoff');
      }
    }

    // In-flight events
    if (this.airborne && this.dest_pos) {
      const distToDest = distance_nm(lat, lon, this.dest_pos[0], this.dest_pos[1]);

      // TOP OF DESCENT check
      if (
        this.tod_remaining_nm !== null &&
        distToDest <= this.tod_remaining_nm &&
        !this.eventsFired.has('top_of_descent')
      ) {
        this.eventsFired.add('top_of_descent');
        events.push('top_of_descent');
      }

      // APPROACH check
      if (distToDest <= 25 && alt < 8000 && !this.eventsFired.has('approach')) {
        this.eventsFired.add('approach');
        events.push('approach');
      }
    }

    // LANDING check
    if (this.airborne && speed < 40 && this.t_off !== null && now - this.t_off > 60) {
      this.airborne = false;
      if (!this.eventsFired.has('landing')) {
        this.eventsFired.add('landing');
        events.push('landing');

        // Automatically log flight
        const minutes = Math.max(1, Math.round((now - this.t_off) / 60));
        const entry: LogbookEntry = {
          id: `log-${now}`,
          date: new Date(now > 1000000000 ? now : Date.now()).toISOString().split('T')[0],
          origin: this.origin || '----',
          dest: this.dest || '----',
          aircraft: 'A320',
          minutes,
          nm: Math.round(this.nm),
          max_alt: Math.round(this.max_alt),
        };
        this.logbookEntries.unshift(entry);
      }
    }

    return events;
  }
}
