export interface ChecklistGroup {
  id: string;
  title: string;
  items: string[];
}

export const CHECKLISTS: Record<string, string[]> = {
  'BEFORE START': [
    'Flight plan and weather reviewed',
    'Fuel and weights set',
    'Parking brake SET',
    'Battery / external power ON',
    'Beacon ON',
    'Altimeters set',
    'Avionics and FMS programmed',
  ],
  'AFTER START': [
    'Engines running, parameters normal',
    'Flaps set for takeoff',
    'Flight controls free and correct',
    'Anti-ice as required',
    'Taxi clearance received',
  ],
  TAXI: [
    'Brakes checked',
    'Taxi lights ON',
    'Flight instruments cross-checked',
    'Takeoff briefing done',
  ],
  'BEFORE TAKEOFF': [
    'Runway confirmed',
    'Transponder ON / squawk set',
    'Landing and strobe lights ON',
    'Flaps and trim set',
    'Autopilot modes armed',
    'Cleared for takeoff',
  ],
  'CLIMB / CRUISE': [
    'Gear UP',
    'Flaps UP',
    'Landing lights OFF above 10,000 ft',
    'Altimeter to standard (29.92 / 1013) at transition',
    'Fuel and systems monitored',
  ],
  DESCENT: [
    'ATIS / weather obtained',
    'Altimeter set to local QNH',
    'Approach briefed',
    'Landing weight and speeds computed',
    'Seat belt signs ON',
  ],
  APPROACH: [
    'Navaids tuned and identified',
    'Approach mode armed',
    'Speed and flaps per schedule',
    'Landing lights ON',
    'Minimums set',
  ],
  LANDING: [
    'Gear DOWN (3 green)',
    'Flaps landing',
    'Speedbrake armed',
    'Cleared to land',
    'Stabilised by 1000 ft',
  ],
  SHUTDOWN: [
    'Parking brake SET',
    'Engines OFF',
    'Beacon OFF',
    'Lights OFF',
    'Battery OFF',
    'Logbook updated',
  ],
};
