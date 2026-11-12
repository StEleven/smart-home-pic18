import type {HostSnapshot} from '../types';
type NativeHost = Record<string, any>;
declare global {
  interface Window { qt?: {webChannelTransport: unknown}; QWebChannel?: new (transport: unknown, callback: (channel: {objects: {host: NativeHost}}) => void) => unknown; }
}
export type HostCall = (method: string, ...args: unknown[]) => Promise<{ok?: boolean; message?: string}>;
export function connectHost(accept: (snapshot: HostSnapshot) => void, report: (message: string) => void): Promise<HostCall> {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const init = () => {
      if (!window.QWebChannel || !window.qt?.webChannelTransport) {
        if (++attempts > 120) { reject(new Error('桌面桥接尚未连接，请使用“启动上位机.cmd”打开程序。')); return; }
        window.setTimeout(init, 50); return;
      }
      new window.QWebChannel(window.qt.webChannelTransport, ({objects: {host}}) => {
        let revision = -1;
        const receive = (raw: string) => {
          try {
            const snapshot = JSON.parse(raw) as HostSnapshot;
            if (snapshot.schemaVersion !== 1 || !Number.isSafeInteger(snapshot.revision) || snapshot.revision <= revision) return;
            revision = snapshot.revision; accept(snapshot);
          } catch { report('收到无效桌面数据，等待下一次更新'); }
        };
        host.snapshotChanged.connect(receive);
        host.exportReport.connect((raw: string) => {
          try { const value = JSON.parse(raw); report(value.message || (value.ok ? '记录已导出' : '导出未完成')); }
          catch { report(raw); }
        });
        // Subscribe first: a delayed ready callback cannot roll back a signal.
        host.ready(receive);
        resolve((method, ...args) => new Promise(result => {
          if (typeof host[method] !== 'function') { result({ok: false, message: '桌面未提供此操作'}); return; }
          host[method](...args, (raw: string) => {
            try { result(raw ? JSON.parse(raw) : {ok: true}); }
            catch { result({ok: false, message: '桌面响应格式异常'}); }
          });
        }));
      });
    };
    init();
  });
}
