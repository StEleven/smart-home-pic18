export interface HostEvent { stamp: string; kind: string; message: string; source: string; }
export interface HostSnapshot {
  schemaVersion: number; revision: number; sessionId: string;
  mode: 'offline' | 'simulation' | 'real'; boot: string | null; seq: number | null;
  firmware: string; fresh: boolean; stateAgeMs: number | null;
  capabilities: string[]; pending: {id: string; action: string; value: string} | null;
  requestStatus: string; status: string; state: Record<string, string> & {ktv_brightness?: string; demand_mode?: 'auto' | 'on' | 'off'};
  ports: {name: string; description: string}[]; events: HostEvent[];
  simulation: {windowFeedback: 'auto' | '0' | '1' | '?'; doorFeedback: 'auto' | '0' | '1' | '?'} | null;
}
export const emptySnapshot: HostSnapshot = {
  schemaVersion: 1, revision: -1, sessionId: '', mode: 'offline', boot: null, seq: null,
  firmware: '', fresh: false, stateAgeMs: null, capabilities: [], pending: null,
  requestStatus: '连接桌面数据源后即可操作', status: '等待桌面连接', state: {}, ports: [], events: [], simulation: null,
};
