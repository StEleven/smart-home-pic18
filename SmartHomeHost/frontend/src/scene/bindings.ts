/** Servo animation follows software targets, never a measured position. */
export const BINDINGS = {
  door: 'door_target',
  window: 'window_target',
  curtain: 'curtain',
  vent: 'vent',
  living: 'living',
  bedroom: 'bedroom',
  hall: 'hall',
} as const;

export type AnimatedDevice = keyof typeof BINDINGS;

export function percentage(value: string | undefined): number | null {
  if (value === undefined || !/^(?:\d+(?:\.\d+)?)$/.test(value)) return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 && n <= 100 ? n / 100 : null;
}

export function binary(value: string | undefined): boolean | null {
  return value === '1' ? true : value === '0' ? false : null;
}

/** Same three-segment wheel and 24 ms step as the eight board LEDs. */
export function rainbowColor(elapsedMs: number, pixel: number): [number, number, number] {
  const phase = (Math.floor(Math.max(0, elapsedMs) / 24) + pixel * 32) % 256;
  return wheelColor(phase);
}

function wheelColor(phase: number): [number, number, number] {
  if (phase < 85) return [255 - phase * 3, phase * 3, 0];
  if (phase < 170) return [0, 255 - (phase - 85) * 3, (phase - 85) * 3];
  return [(phase - 170) * 3, 0, 255 - (phase - 170) * 3];
}

/** Board-equivalent eight-pixel KTV effect; brightness is a percentage. */
export function ktvPixel(elapsedMs: number, pixel: number, effect: string, brightness: number): [number, number, number] {
  const elapsed = Math.max(0, elapsedMs);
  let level = Math.max(0, Math.min(100, Math.round(brightness)));
  let color: [number, number, number];
  if (effect === 'party') {
    const beat = Math.floor(elapsed / 180) % 256, lead = (beat * 5) & 7;
    if (![lead, (lead + 3) & 7, (lead + 5) & 7].includes(pixel)) return [0, 0, 0];
    color = wheelColor((beat * 53 + pixel * 71) % 256);
  } else if (effect === 'rainbow' || effect === 'pulse') {
    color = rainbowColor(elapsed, pixel);
    if (effect === 'pulse') {
      const time = elapsed % 2400, triangle = time < 1200 ? time : 2400 - time;
      const gain = 10 + Math.floor(triangle * 90 / 1200);
      level = Math.floor(level * gain / 100);
    }
  } else color = [255, 210, 150];
  return color.map(channel => Math.floor(channel * level / 100)) as [number, number, number];
}

export function studyBrightness(elapsedMs: number): number {
  const time = Math.max(0, elapsedMs) % 4000, triangle = time < 2000 ? time : 4000 - time;
  return (10 + Math.floor(triangle / 40)) / 100;
}
