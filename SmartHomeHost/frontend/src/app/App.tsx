import {useCallback, useEffect, useRef, useState} from 'react';
import {ArrowClockwise, ArrowsOut, CaretRight, CloudRain, Cube, Door, Drop, Eye, FileArrowDown, Flask, HouseLine, Lightbulb, Moon, PlugsConnected, Power, SlidersHorizontal, Stack, Sun, TerminalWindow, Thermometer, Timer, WarningCircle, Wind, X} from '@phosphor-icons/react';
import {HouseScene} from '../scene/HouseScene';
import {emptySnapshot} from '../types';
import type {HostSnapshot} from '../types';
import {connectHost} from './host';
import type {HostCall} from './host';

const names: Record<string, string> = {door:'入户门', window:'客厅窗户', curtain:'遮阳窗帘', vent:'空调风口', living:'客厅照明', bedroom:'卧室照明', hall:'走道照明', water:'厨房水浸', rain:'屋外雨滴', cooling:'模拟空调', loads:'模拟家电', timer:'学习计时'};
const places: Record<string, string> = {door:'走道 · 入口',window:'客厅 · 靠窗区',curtain:'客厅 · 靠窗区',vent:'客厅 · 空调',living:'客厅',bedroom:'卧室',hall:'走道',water:'厨房 · 水槽旁',rain:'屋外',cooling:'客厅',loads:'全屋',timer:'卧室 · 学习区'};
const sceneNames: Record<string, string> = {home:'回家',away:'普通离家',long_away:'长期离家',sleep:'睡眠',movie:'观影',ktv:'KTV',unknown:'未知'};
const capFor: Record<string, string> = {scene:'scene',door:'door',window:'window',curtain:'curtain',demand:'demand',night:'night',living:'lights',bedroom:'lights',hall:'lights',light_effect:'light_effect',ktv_brightness:'ktv',load_switch:'loads',mute:'mute',timer_start:'timer',timer_pause:'timer',timer_resume:'timer',timer_stop:'timer'};
const demandModes: Record<string,string> = {auto:'auto','1':'on','0':'off'};
const demandLabels: Record<string,string> = {auto:'自动',on:'手动开启',off:'手动关闭'};
const lightEffects: Record<string, string> = {rainbow:'流动彩虹',pulse:'彩色呼吸',party:'节拍跳色'};
const contact = (v?: string) => v === '1' ? '关闭状态' : v === '0' ? '开启 / 运动中' : '未知';
const comfortNames: Record<string,string> = {'0':'湿度未知','1':'偏干燥','2':'湿度舒适','3':'偏潮湿'};
const percent = (v?: string) => v && v !== '?' ? `${v}%` : '—';
const num = (v?: string, scale = 1) => v && v !== '?' && Number.isFinite(Number(v)) ? (Number(v)/scale).toLocaleString('zh-CN',{maximumFractionDigits:1}) : '—';
const countdown = (v?: string) => v && v !== '?' ? `${Math.floor(Number(v)/60).toString().padStart(2,'0')}:${(Number(v)%60).toString().padStart(2,'0')}` : '—';
const timerNames: Record<string,string> = {idle:'未开始',running:'进行中',paused:'已暂停',done:'已结束',unknown:'未知'};

function SelectInput({label,value,items,onChange}:{label:string;value:string;items:[string,string][];onChange:(value:string)=>void}) {
  return <label className="form-field"><span>{label}</span><select aria-label={label} value={value} onChange={e=>onChange(e.target.value)}>{items.map(([v,text])=><option key={v} value={v}>{text}</option>)}</select></label>;
}
function NumericInput({label,value,min,max,step,onChange}:{label:string;value:number;min:number;max:number;step:number;onChange:(value:number)=>void}) {
  return <label className="form-field"><span>{label}</span><input aria-label={label} type="number" defaultValue={value} min={min} max={max} step={step} key={label} onBlur={e=>{const v=Number(e.target.value); if(e.target.value && Number.isFinite(v) && v>=min && v<=max)onChange(v); else e.target.value=String(value);}} onKeyDown={e=>{if(e.key==='Enter')e.currentTarget.blur();}}/></label>;
}

export function App() {
  const [snapshot,setSnapshot] = useState<HostSnapshot>(emptySnapshot);
  const [received,setReceived] = useState(performance.now());
  const [now,setNow] = useState(performance.now());
  const [host,setHost] = useState<HostCall|null>(null);
  const [bridgeError,setBridgeError] = useState('');
  const [selected,setSelected] = useState('window');
  const [tab,setTab] = useState<'device'|'simulate'>('device');
  const [roof,setRoof] = useState(false);
  const [walls,setWalls] = useState(false);
  const [sceneReady,setSceneReady] = useState(false);
  const [sceneError,setSceneError] = useState('');
  const [toast,setToast] = useState('');
  const [drawer,setDrawer] = useState<'connection'|'logs'|null>(null);
  const [port,setPort] = useState('');
  const [brightness,setBrightness] = useState(70);
  const [minutes,setMinutes] = useState(25);
  const canvasRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<HouseScene|null>(null);
  const latest = useRef(snapshot);
  const select = useCallback((id:string)=>{if(names[id]){setSelected(id);setTab('device');}},[]);
  const age = snapshot.stateAgeMs === null ? null : snapshot.stateAgeMs + Math.max(0,now-received);
  const fresh = snapshot.fresh && age !== null && age < 2000 && now-received < 2500;
  const viewSnapshot = {...snapshot,fresh};
  latest.current=viewSnapshot;
  const s=snapshot.state;
  const isKtv=s.scene==='ktv';
  const demandHold=snapshot.capabilities.includes('demand_hold');
  const enabled=(action:string)=>Boolean(host && fresh && !snapshot.pending && snapshot.capabilities.includes(capFor[action]));
  const call = useCallback(async(method:string,...args:unknown[])=>{
    if(!host)return;
    const result=await host(method,...args);
    if(result.ok===false && result.message)setToast(result.message);
  },[host]);
  const action=(key:string,value:string)=>void call('requestAction',snapshot.sessionId,key,value);
  const input=(key:string,value:string)=>void call('setSimInput',snapshot.sessionId,key,value);
  const actuator=(value:string)=>void call('setSimActuator',snapshot.sessionId,'door',value);

  useEffect(()=>{
    let alive=true;
    connectHost(value=>{if(alive){setSnapshot(value);setReceived(performance.now());}},message=>{if(alive)setToast(message);})
      .then(value=>{if(alive)setHost(()=>value);}).catch(error=>{if(alive)setBridgeError(String(error.message));});
    const interval=window.setInterval(()=>setNow(performance.now()),250);
    return()=>{alive=false;window.clearInterval(interval);};
  },[]);
  useEffect(()=>{
    if(!canvasRef.current)return;
    let alive=true;
    let scene:HouseScene;
    try {
      scene=new HouseScene(canvasRef.current,select);
      sceneRef.current=scene;
      scene.setState(latest.current);
      scene.ready.then(()=>{if(alive){setSceneReady(true);scene.setState(latest.current);}}).catch(error=>{if(alive)setSceneError(String(error.message||error));});
    } catch(error) {setSceneError(String(error));return;}
    return()=>{alive=false;scene.dispose();sceneRef.current=null;};
  },[select]);
  useEffect(()=>{sceneRef.current?.setState(viewSnapshot);},[snapshot,fresh]);
  useEffect(()=>{sceneRef.current?.setSelected(selected);},[selected,sceneReady]);
  useEffect(()=>{sceneRef.current?.setRoof(roof);},[roof,sceneReady]);
  useEffect(()=>{sceneRef.current?.setWalls(walls);},[walls,sceneReady]);
  useEffect(()=>{if(toast){const t=window.setTimeout(()=>setToast(''),6500);return()=>clearTimeout(t);}},[toast]);
  useEffect(()=>{
    if(!drawer)return;
    const previous=document.activeElement as HTMLElement|null;
    const dialog=document.querySelector<HTMLElement>('[role="dialog"]');
    const controls=()=>[...dialog?.querySelectorAll<HTMLElement>('button:not(:disabled),select:not(:disabled),input:not(:disabled),[tabindex="0"]')||[]];
    controls()[0]?.focus();
    const listener=(event:KeyboardEvent)=>{
      if(event.key==='Escape')setDrawer(null);
      if(event.key==='Tab'){
        const items=controls(),first=items[0],last=items.at(-1);
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
      }
    };
    window.addEventListener('keydown',listener);
    return()=>{window.removeEventListener('keydown',listener);previous?.focus();};
  },[drawer]);
  useEffect(()=>{
    (window as any).__smartHomeDebug={snapshot:()=>latest.current,scene:()=>sceneRef.current?.getDebugState(),select};
    return()=>{delete (window as any).__smartHomeDebug;};
  },[select]);

  useEffect(()=>{
    const value=isKtv?(s.ktv_brightness||'50'):s[selected];
    if(value!==undefined&&value!=='?'&&Number.isFinite(Number(value)))setBrightness(Number(value));
  },[selected,s.scene,s.ktv_brightness,snapshot.sessionId]);

  const liveSource = snapshot.mode==='simulation' ? '离线演示 · 模拟数据' : snapshot.mode==='real' ? (fresh?'硬件已连接 · 已同步':'硬件已连接 · 等待同步') : '未连接 · 场景预览';
  const activeScene=sceneNames[s.scene]||'尚未同步';
  const target=selected==='door'?s.door_target:selected==='window'?s.window_target:s[selected];
  const hasTarget=target!==undefined && target!=='?';
  const feedback=selected==='door'||selected==='window'?contact(s[selected]):null;
  const simulatedFeedback=snapshot.mode==='simulation' && (selected==='door'?(snapshot.simulation?.doorFeedback||'auto'):selected==='window'?(snapshot.simulation?.windowFeedback||'auto'):'auto')!=='auto';
  const stateLabel=simulatedFeedback?'模拟反馈':s.state_source==='commanded'?'当前状态':'状态';
  const alarm=s.alarm!==undefined?s.alarm==='1':s.water==='1';
  const selectedIcon = selected==='water'?<Drop/>:selected==='timer'?<Timer/>:selected==='rain'?<CloudRain/>:['vent','cooling'].includes(selected)?<Wind/>:['living','bedroom','hall'].includes(selected)?<Lightbulb/>:<Door/>;

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><span className="brand-mark"><HouseLine weight="duotone"/></span><div><h1>栖居<span>SMART HOME</span></h1><p>智慧小屋 · 交互展示</p></div></div>
      <div className="header-center"><span className={'source-pill '+(snapshot.mode==='simulation'?'demo':fresh?'live':'idle')}><i/>{liveSource}</span><span className="version-label">3D LIVE VIEW</span></div>
      <div className="header-actions"><button className="subtle" onClick={()=>{setDrawer('connection');void call('refreshPorts');}}><PlugsConnected/>连接设备</button>{snapshot.mode==='offline'?<button className="primary" disabled={!host} onClick={()=>void call('startDemo')}><Flask/>进入演示</button>:<button className="icon-button" title="断开并保存会话" aria-label="断开并保存会话" onClick={()=>void call('disconnect')}><Power/></button>}</div>
    </header>

    <div className="scene-bar"><div className="scene-label"><span className="eyebrow">HOME SCENES</span><strong>让空间回应生活</strong></div><nav aria-label="场景切换">{Object.entries(sceneNames).filter(([key])=>key!=='unknown').map(([key,text])=><button key={key} data-testid={'scene-'+key} className={s.scene===key?'scene-button active':'scene-button'} disabled={!enabled('scene')||(key==='ktv'&&!snapshot.capabilities.includes('ktv'))} onClick={()=>action('scene',key)}>{key==='home'?<HouseLine/>:key==='sleep'?<Moon/>:key==='movie'?<Cube/>:<Door/>}{text}</button>)}</nav><span className="scene-current">当前场景 <b>{activeScene}</b></span></div>

    <main className="main-layout">
      <section className="stage" aria-label="可旋转的三维智慧小屋">
        <div className="stage-title"><span className="eyebrow">YOUR CONNECTED SPACE</span><h2>一屋之间，尽在眼前<span>.</span></h2><p>拖动旋转 · 滚轮缩放 · 点选设备</p></div>
        <div ref={canvasRef} className="scene-canvas" data-testid="three-canvas"/>
        <div className="stage-top-right"><span className={'live-dot '+(fresh?'':'paused')}/>{fresh?'状态同步中':'等待有效状态'}</div>
        {!sceneReady&&!sceneError&&<div className="loading"><span className="loading-ring"/><b>正在布置你的小屋</b><small>载入本地模型与材质</small></div>}
        {sceneError&&<div className="scene-error"><WarningCircle size={32}/><h3>三维场景未能载入</h3><p>{sceneError}</p><button onClick={()=>location.reload()}>重新载入</button></div>}
        <div className="view-tools"><button title="回到展示视角" aria-label="回到展示视角" onClick={()=>sceneRef.current?.setView('home')}><ArrowClockwise/></button><button title="俯视布局" aria-label="俯视布局" onClick={()=>sceneRef.current?.setView('top')}><Eye/></button><span/><button className={roof?'active':''} aria-pressed={roof} onClick={()=>setRoof(!roof)}><HouseLine/>{roof?'隐藏屋顶':'显示屋顶'}</button><button className={walls?'active':''} aria-pressed={walls} onClick={()=>setWalls(!walls)}><Stack/>{walls?'剖视模式':'完整外墙'}</button><span/><button title="全屏展示" aria-label="全屏展示" onClick={()=>{if(document.fullscreenElement)void document.exitFullscreen();else void document.documentElement.requestFullscreen().catch(()=>setToast('当前窗口未开启全屏权限'));}}><ArrowsOut/></button></div>
        <div className="stage-footnote"><span>01 / 单层功能展示屋</span><span>门窗、灯光与场景同步</span></div>
      </section>

      <aside className="side-panel">
        <div className="panel-tabs"><button className={tab==='device'?'active':''} onClick={()=>setTab('device')}>设备详情</button><button className={tab==='simulate'?'active':''} onClick={()=>setTab('simulate')}><Flask/>模拟实验</button></div>
        <div className="panel-scroll">
          {tab==='device'?<>
            <div className="device-heading"><span className="device-symbol">{selectedIcon}</span><span className="eyebrow">DEVICE CONTROL</span><h2>{names[selected]}</h2><p>{places[selected]} <span className="muted">/ {fresh?'实时状态':'等待同步'}</span></p></div>
            <label className="device-select"><select aria-label="选择设备" value={selected} onChange={e=>select(e.target.value)}>{Object.entries(names).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>
            <div className="quick-devices">{['door','window','curtain','vent'].map(id=><button key={id} onClick={()=>select(id)} className={selected===id?'active':''}>{names[id].replace('客厅','').replace('遮阳','').replace('空调','')}</button>)}</div>
            {['door','window','curtain','vent'].includes(selected)?<>
              <div className="primary-reading"><span>{selected==='window'||selected==='door'?'目标开度':'输出目标'}</span><strong>{percent(target)}</strong><small>{!hasTarget?'控制器尚未提供此目标':'三维机构随此目标运动'}</small></div>
              <div className="position-track"><i style={{width:hasTarget?`${Math.max(0,Math.min(100,Number(target)))}%`:'0%'}}/></div>
              {feedback&&<div className="feedback-row"><span>{stateLabel}</span><b className={s[selected]==='0'?'amber':''}>{feedback}</b></div>}
              {selected==='window'&&<div className="feedback-row"><span>控制模式</span><b>{s.control==='manual'?`手动 · ${Math.ceil(Number(s.manual_ms)/1000)}s`:s.control==='auto'?'自动':'未知'}</b></div>}
              {selected!=='vent'?<><div className="button-pair"><button data-testid="open-device" disabled={!enabled(selected)} onClick={()=>action(selected,'open')}>打开</button><button data-testid="close-device" disabled={!enabled(selected)} onClick={()=>action(selected,'close')}>关闭</button></div><button className="wide subtle" disabled={!enabled(selected)} onClick={()=>action(selected,'auto')}><ArrowClockwise/>恢复自动控制</button></>:<p className="hint">风口随制冷自动开启。</p>}
            </>:['living','bedroom','hall'].includes(selected)?<>
              <div className="primary-reading"><span>{isKtv?'KTV 总亮度':'输出亮度'}</span><strong>{percent(isKtv?(s.ktv_brightness||'50'):s[selected])}</strong></div>
              {isKtv?<>
                <div className="feedback-row"><span>KTV 灯效</span><b>{lightEffects[s.light_effect||'rainbow']||'日常暖光'}</b></div>
                <div className="effect-options" role="group" aria-label="KTV 灯效">{Object.entries(lightEffects).map(([effect,label])=><button key={effect} data-testid={'light-effect-'+effect} aria-pressed={s.light_effect===effect} className={s.light_effect===effect?'primary':''} disabled={!enabled('light_effect')} onClick={()=>action('light_effect',effect)}>{label}</button>)}</div>
                <p className="hint">八灯统一调光，0% 全灭。</p>
                <label className="slider-field"><span>KTV 总亮度 <b>{brightness}%</b></span><input aria-label="KTV 总亮度" type="range" min="0" max="100" value={brightness} onChange={e=>setBrightness(Number(e.target.value))}/></label>
                <button className="primary wide" disabled={!enabled('ktv_brightness')} onClick={()=>action('ktv_brightness',String(brightness))}>设置总亮度</button>
                <button className="wide subtle" disabled={!enabled('ktv_brightness')} onClick={()=>action('ktv_brightness','0')}>全灭</button>
              </>:<>
                <div className="feedback-row"><span>灯光</span><b>日常暖光</b></div>
                <label className="slider-field"><span>请求亮度 <b>{brightness}%</b></span><input aria-label="灯光亮度" type="range" min="0" max="100" value={brightness} onChange={e=>setBrightness(Number(e.target.value))}/></label>
                <button className="primary wide" disabled={!enabled(selected)} onClick={()=>action(selected,String(brightness))}>设置亮度</button>
                <div className="button-pair"><button disabled={!enabled(selected)} onClick={()=>action(selected,'0')}>关灯</button><button disabled={!enabled(selected)} onClick={()=>action(selected,'auto')}>恢复自动</button></div>
                {selected==='hall'&&<button className="wide subtle" disabled={s.scene!=='sleep'||!enabled('night')} onClick={()=>action('night','1')}><Moon/>起夜照明 · 10% · 30秒</button>}
              </>}
            </>:selected==='water'?<>
              <div className={'condition-card '+(alarm?'danger':'')}><Drop size={30}/><h3>{s.water==='?'||s.water===undefined?(alarm?'检测未知 · 保留水浸报警':'检测状态未知'):s.water==='1'?'检测到水浸':'当前无水浸'}</h3><p>{s.muted==='1'?'已消音，异常仍保留':alarm?'水浸报警保留至检测确认解除':'水浸状态与消音状态分别记录'}</p></div><button className="wide" disabled={!enabled('mute')||!alarm} onClick={()=>action('mute','1')}>消音并保留异常</button>
            </>:selected==='timer'?<>
              <div className="primary-reading"><span>{timerNames[s.timer]||'未知'}</span><strong className="time-value">{countdown(s.timer_s)}</strong></div>
              <p className="hint">开始后台灯慢呼吸，暂停时常亮；窗帘保持原状态。</p>
              {isKtv&&<p className="hint tight">KTV 灯效优先，计时继续。</p>}
              <label className="form-field"><span>学习时长 / 分钟</span><input aria-label="学习时长" type="number" min="1" max="1440" value={minutes} onChange={e=>setMinutes(Number(e.target.value))}/></label>
              <button className="primary wide" disabled={!enabled('timer_start')||!Number.isInteger(minutes)||minutes<1||minutes>1440} onClick={()=>action('timer_start',String(minutes*60))}>设置并开始</button>
              <div className="button-pair"><button disabled={!enabled('timer_pause')||s.timer!=='running'} onClick={()=>action('timer_pause','1')}>暂停</button><button disabled={!enabled('timer_resume')||s.timer!=='paused'} onClick={()=>action('timer_resume','1')}>继续</button></div><button className="wide subtle" disabled={!enabled('timer_stop')} onClick={()=>action('timer_stop','1')}>结束计时</button>
            </>:selected==='loads'?<>
              <div className="feedback-row"><span>可关闭负载</span><b>{s.load_switch==='1'?'开启':s.load_switch==='0'?'关闭':'未知'}</b></div><div className="feedback-row"><span>保留负载</span><b>{s.load_keep==='1'?'开启':s.load_keep==='0'?'关闭':'未知'}</b></div><div className="button-pair"><button disabled={!enabled('load_switch')} onClick={()=>action('load_switch','1')}>开启负载</button><button disabled={!enabled('load_switch')} onClick={()=>action('load_switch','0')}>关闭负载</button></div><p className="hint">展示模拟家电输出；常供电负载不提供关闭入口。</p>
            </>:selected==='rain'?<div className="condition-card"><CloudRain size={34}/><h3>{s.rain==='1'?'检测到雨湿':s.rain==='0'?'当前干燥':'检测状态未知'}</h3><p>雨湿优先关闭窗户。雨停后重新判断场景与需求。</p></div>:<>
              <div className="condition-card"><Wind size={34}/><h3>{s.cooling==='1'?'模拟制冷开启':s.cooling==='0'?'模拟制冷关闭':'输出未知'}</h3><div className="feedback-row"><span>旋钮设温</span><b>{num(s.setpoint10,10)} °C</b></div><div className="feedback-row"><span>控制方式</span><b>{demandHold?(demandLabels[s.demand_mode||'']||'未提供'):'临时需求控制'}</b></div></div>
              <div className="demand-options" role="group" aria-label="空调控制">{[['auto','自动'],['1',demandHold?'手动开启':'临时开启'],['0',demandHold?'手动关闭':'临时关闭']].map(([value,label])=><button key={value} data-testid={'demand-'+value} className={demandHold&&s.demand_mode===demandModes[value]?'primary':''} aria-pressed={demandHold&&s.demand_mode===demandModes[value]} disabled={!enabled('demand')||(value==='1'&&['away','long_away'].includes(s.scene))} onClick={()=>action('demand',value)}>{label}</button>)}</div>
              <p className="hint">{demandHold?'手动保持，离家恢复自动。':'旧固件使用临时需求控制。'}</p>
            </>}
            {['door','window','curtain'].includes(selected)&&<div className="rule-note"><span className="note-dot"/><p>{selected==='window'?'雨湿时自动关窗；长期离家保持关闭。':selected==='curtain'?'窗帘按光照与场景遮阳，手动控制60秒后恢复自动。':'回家自动开门，KTV 默认关闭，可手动打开。'}</p></div>}
          </>:<>
            <div className="simulation-heading"><Flask size={28}/><h2>让小屋动起来</h2><p>改变模拟环境，观察机构与灯光的联动。</p></div>
            {snapshot.mode!=='simulation'?<div className="condition-card"><p>此面板仅用于离线演示</p><button className="primary wide" disabled={!host} onClick={()=>void call('startDemo')}>启动离线演示</button></div>:<fieldset className="sim-fields" disabled={!fresh} key={snapshot.sessionId}>
              <div className="form-section"><span className="eyebrow">WEATHER & SAFETY</span><div className="field-grid">
                <SelectInput label="屋外雨滴" value={s.rain||'?'} items={[["0","干燥"],["1","雨湿"],["?","未知"]]} onChange={v=>input('rain',v)}/>
                <SelectInput label="厨房水浸" value={s.water||'?'} items={[["0","无水"],["1","有水"],["?","未知"]]} onChange={v=>input('water',v)}/>
                <SelectInput label="门状态" value={snapshot.simulation?.doorFeedback||'auto'} items={[["auto","跟随动作"],["1","关闭"],["0","未关闭"],["?","未知"]]} onChange={v=>input('door',v)}/>
                <SelectInput label="窗状态" value={snapshot.simulation?.windowFeedback||'auto'} items={[["auto","跟随动作"],["1","关闭"],["0","未关闭"],["?","未知"]]} onChange={v=>input('window',v)}/>
              </div></div>
              <div className="form-section"><span className="eyebrow">ACTUATOR & COMFORT</span><label className="slider-field"><span>门舵机目标 <b>{percent(s.door_target)}</b></span><input aria-label="模拟门舵机目标" type="range" min="0" max="100" value={Number(s.door_target)||0} onChange={e=>actuator(e.target.value)}/></label><SelectInput label="模拟制冷需求" value={s.demand||'?'} items={[["0","无需求"],["1","有需求"],["?","未知"]]} onChange={v=>input('demand',v)}/><div className="field-grid">
                <NumericInput label="温度 / °C" value={Number(s.temp)/10} min={-40} max={125} step={0.1} onChange={v=>input('temp',String(Math.round(v*10)))}/>
                <NumericInput label="湿度 / %RH" value={Number(s.humid)/10} min={0} max={100} step={0.1} onChange={v=>input('humid',String(Math.round(v*10)))}/>
              </div><NumericInput label="环境光 / lx" value={Number(s.lux)} min={0} max={200000} step={1} onChange={v=>input('lux',String(Math.round(v)))}/></div>
              <p className="hint">通风阈值30°C，制冷设温31.5°C。遮阳按500/300 lx切换，连续确认3秒。</p>
            </fieldset>}
          </>}
        </div>
        <div className={'request-status '+(!fresh?'stale':'')}><span className="eyebrow">CONTROLLER</span><p>{bridgeError || (!fresh&&snapshot.mode!=='offline'?'数据已过期，控制已禁用':snapshot.requestStatus)}</p>{fresh&&<small>最近状态 {((age||0)/1000).toFixed(1)} 秒前</small>}</div>
      </aside>
    </main>

    <footer className="bottom-bar">
      <div className="metric"><Thermometer/><div><span>环境温度</span><strong>{num(s.temp,10)}<small>°C</small></strong></div></div><div className="metric"><Drop/><div><span>相对湿度 · {comfortNames[s.comfort]||'舒适提示未提供'}</span><strong>{num(s.humid,10)}<small>%RH</small></strong></div></div><div className="metric"><Sun/><div><span>环境光</span><strong>{num(s.lux)}<small>lx</small></strong></div></div><button className={'metric metric-button '+(alarm?'alert':'')} onClick={()=>select('water')}><Drop/><div><span>水浸检测</span><strong>{s.water==='?'||s.water===undefined?(alarm?'检测未知 · 报警保留':'未知'):alarm?(s.muted==='1'?'异常 · 已消音':'发现水浸'):'正常'}</strong></div></button><button className="metric metric-button" onClick={()=>select('timer')}><Timer/><div><span>学习计时</span><strong>{s.timer==='idle'?'未开始':countdown(s.timer_s)}</strong></div></button><button className="log-toggle" onClick={()=>setDrawer('logs')}><TerminalWindow/><span>运行记录</span><CaretRight/></button>
    </footer>
    {toast&&<div role="status" className="toast"><WarningCircle/>{toast}<button aria-label="关闭提示" onClick={()=>setToast('')}><X/></button></div>}
    {drawer&&<div className="drawer-scrim" onPointerDown={e=>{if(e.target===e.currentTarget)setDrawer(null);}}><section className={'drawer '+(drawer==='logs'?'log-drawer':'')} role="dialog" aria-modal="true" aria-label={drawer==='logs'?'运行记录':'连接设备'}><div className="drawer-title"><div><span className="eyebrow">{drawer==='logs'?'SESSION LOG':'CONNECTION'}</span><h2>{drawer==='logs'?'运行记录':'连接你的小屋'}</h2></div><button className="icon-button" aria-label="关闭面板" onClick={()=>setDrawer(null)}><X/></button></div>
      {drawer==='connection'?<><p className="drawer-intro">连接已烧录智慧小屋固件的 Nano 板卡，即可控制小屋。</p><label className="form-field"><span>串口设备 · 115200 / 8N1</span><select aria-label="串口设备" value={port||snapshot.ports[0]?.name||''} onChange={e=>setPort(e.target.value)}>{!snapshot.ports.length&&<option value="">未发现串口</option>}{snapshot.ports.map(p=><option key={p.name} value={p.name}>{p.name} · {p.description}</option>)}</select></label><div className="button-pair"><button disabled={!host} onClick={()=>void call('refreshPorts')}><ArrowClockwise/>刷新</button><button className="primary" disabled={!host||!snapshot.ports.length} onClick={()=>{void call('connectPort',port||snapshot.ports[0]?.name);setDrawer(null);}}>连接硬件</button></div><div className="connection-divider"/><h3>先体验完整联动</h3><p className="hint">离线演示提供模拟环境和舵机输入，无需连接开发板。</p><button className="wide primary" disabled={!host} onClick={()=>{void call('startDemo');setDrawer(null);setTab('simulate');}}><Flask/>开始离线演示</button><div className="session-info"><span>当前来源</span><b>{liveSource}</b><span>固件版本</span><b>{snapshot.firmware||'—'}</b><span>启动标识</span><b>{snapshot.boot||'—'}</b></div></>:<><div className="log-toolbar"><span>{snapshot.events.length} 条最近事件 · {snapshot.mode==='simulation'?'模拟会话':snapshot.mode==='real'?'真实会话':'已断开'}</span><button disabled={!host} onClick={()=>void call('exportLogs')}><FileArrowDown/>导出会话 CSV</button></div><div className="event-list">{!snapshot.events.length&&<p className="hint">操作和通信事件将显示在这里。</p>}{[...snapshot.events].reverse().map((e,i)=><article key={`${e.stamp}-${i}`}><time>{e.stamp.slice(11,19)||e.stamp}</time><span>{e.kind}</span><p>{e.message}</p></article>)}</div></>}
    </section></div>}
  </div>;
}
