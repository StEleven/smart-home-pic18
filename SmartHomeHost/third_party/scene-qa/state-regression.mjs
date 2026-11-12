// Deterministic checks of actual HouseScene state and visual materials, with no
// renderer, browser process, visible window or independently advancing timer.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { pathToFileURL, fileURLToPath } from 'node:url';
import * as THREE from '../../frontend/node_modules/three/build/three.module.js';
import { GLTFLoader } from '../../frontend/node_modules/three/examples/jsm/loaders/GLTFLoader.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const dependencies = path.resolve(here, '../../frontend/node_modules');
let source = await fs.readFile(path.join(here, 'HouseScene.js'), 'utf8');
source = source.replace(/from ['"]three['"]/g, `from '${pathToFileURL(path.join(dependencies, 'three/build/three.module.js')).href}'`);
source = source.replace(/from ['"]three\/addons\/([^'"]+)['"]/g, (_, subpath) => `from '${pathToFileURL(path.join(dependencies, 'three/examples/jsm', subpath)).href}'`);
const { HouseScene } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
let now = 0;
Object.defineProperty(performance, 'now', {value: () => now, configurable: true});
globalThis.document = {createElement: () => {
  const context = {texts: [], fillRect() {}, beginPath() {}, arc() {}, fill() {}, moveTo() {}, lineTo() {},
    createLinearGradient: () => ({addColorStop() {}}), fillText(text) {this.texts.push(text);}};
  return {getContext: () => context};
}};
const scene = Object.create(HouseScene.prototype);
Object.assign(scene, {
  motions: Object.fromEntries(['door','window','curtain','vent','living','bedroom','hall'].map(id => [id, {current:0,target:0,known:false,initialized:false}])),
  latestSession:'', firstValid:true, lightingScene:'unknown', lightEffect:'warm', lightEffectStarted:0, lightEffectElapsed:0, ktvBrightness:.5,
  house:new THREE.Group(), materials:Object.fromEntries(['oak','metal','brass','teal'].map(id => [id,new THREE.MeshStandardMaterial()])), devices:new Map(), pickables:[],
  loadSwitch:null, loadKeep:null, televisionScreens:[], televisionTexture:null, televisionLight:null, stoveRings:[], fridgeIndicator:null,
  timerStatus:'unknown', timerRemaining:'', timerKnown:false, timerDisplay:'', timerCanvas:null, timerTexture:null, studyElapsed:0, studyStarted:0, studyLevel:0,
  roomLights:new Map(['living','bedroom','hall'].map(id => [id, {light:new THREE.PointLight(),bulb:new THREE.MeshStandardMaterial(),glow:new THREE.Mesh(new THREE.CircleGeometry(),new THREE.MeshBasicMaterial())}])),
});
scene.applyPose = () => {scene.applyLighting(); scene.applyStudyLighting();};
scene.buildStudyArea();
const televisionBytes = await fs.readFile(path.resolve(here, '../../frontend/public/assets/furniture/televisionModern.glb'));
const television = (await new GLTFLoader().parseAsync(televisionBytes.buffer.slice(televisionBytes.byteOffset, televisionBytes.byteOffset + televisionBytes.byteLength), '')).scene;
scene.recolor(television);
scene.configureTelevision(television); scene.configureStove(new THREE.Group()); scene.configureFridge(new THREE.Group());
let screenSurface;
television.traverse(node => {if (node.material?.name==='television.screen') screenSurface=node;});
assert(screenSurface,'the imported GLB screen material is bound');
for (let i=0; i<screenSurface.geometry.index.count; i++) {
  const vertex=screenSurface.geometry.index.getX(i), uv=screenSurface.geometry.attributes.uv;
  assert(uv.getX(vertex)>=0 && uv.getX(vertex)<=1 && uv.getY(vertex)>=0 && uv.getY(vertex)<=1,'actual screen UVs show the whole image without source tiling');
}
const state = (sessionId, values, options = {}) => ({sessionId,mode:'simulation',fresh:true,stateAgeMs:0,state:values,...options});
const lights = () => [...scene.roomLights].map(([id, room]) => ({id,color:room.light.color.getHexString(),intensity:room.light.intensity,emissive:room.bulb.emissiveIntensity}));
const level = (index = 0) => lights()[index].intensity;
const near = (actual,expected) => assert(Math.abs(actual-expected)<1e-9, `${actual} != ${expected}`);

scene.setState(state('demo-a', {door_target:'75',window_target:'100'}));
assert.equal(scene.motions.door.current,.75,'first target initializes directly');
scene.setState(state('demo-a', {door_target:'25'}));
assert.equal(scene.motions.door.current,.75,'new target does not pre-emptively snap');
assert.equal(scene.motions.door.target,.25);
scene.setState(state('demo-a', {door_target:'?'}));
assert.equal(scene.motions.door.current,.75,'unknown in same session holds pose');
assert.equal(scene.motions.door.known,false);
assert.equal(scene.motions.door.target,.75,'unknown freezes outstanding movement');
scene.setState(state('off-a', {}, {mode:'offline',fresh:false}));
assert.equal(scene.motions.door.current,.75,'disconnect holds last pose');
scene.setState(state('real-a', {door:'0',window_target:'50'}, {mode:'real'}));
assert.equal(scene.motions.door.current,0,'new source cannot inherit the demo pose');
assert.equal(scene.motions.door.known,false,'reed feedback is not an actuator target');
assert.equal(scene.motions.window.current,.5);
scene.setState(state('real-a', {door_target:'60'}, {mode:'real'}));
assert.equal(scene.motions.door.current,.6,'late first field initializes directly');
scene.setState(state('real-a', {door_target:'100'}, {mode:'real',fresh:false}));
assert.equal(scene.motions.door.current,.6);
assert.equal(scene.motions.door.target,.6,'stale snapshot cannot set a target');
scene.setState(state('real-a', {door_target:'101'}, {mode:'real'}));
assert.equal(scene.motions.door.known,false);
scene.setState(state('real-a', {water:'?',alarm:'1'}, {mode:'real'}));
assert.equal(scene.waterActive,true,'unknown measurement cannot clear a water alarm');
scene.setState(state('real-a', {water:'0',alarm:'0'}, {mode:'real'}));
assert.equal(scene.waterActive,false);
scene.setState(state('old-fw', {water:'1'}, {mode:'real'}));
assert.equal(scene.waterActive,true,'legacy state falls back to water');

for (const currentScene of ['home','movie','away','long_away','sleep']) {
  scene.setState(state('lights', {scene:currentScene,light_effect:'rainbow',living:'0',bedroom:'0',hall:'0'}));
  assert.equal(scene.lightEffect,'warm',`${currentScene} ignores KTV selection`);
  assert(lights().every(light => light.intensity===0 && light.emissive===0),'no forced minimum light');
}
scene.motions.hall.current=.8; scene.applyLighting();
near(level(2),7.2);
assert(lights().every(light => light.color==='ffcb88'),'ordinary scenes always use warm fixtures');
scene.setState(state('ktv', {scene:'ktv',light_effect:'rainbow',living:'99',bedroom:'0',hall:'37'}));
const firstLights=lights();
assert.equal(scene.ktvBrightness,.5,'older KTV state defaults to 50%');
assert(lights().every(light => light.intensity===127/255*9),'KTV uses one master across the room channels');
assert.equal(firstLights[0].color,'ff0000');
assert.equal(new Set(firstLights.map(light => light.color)).size,3,'fixtures represent pixels 0/3/6');
now=48; scene.applyLighting(); assert.notDeepEqual(lights(),firstLights,'rainbow moves');
now=6144; scene.setState(state('ktv', {scene:'ktv',light_effect:'rainbow'}));
assert.deepEqual(lights(),firstLights,'rainbow repeats after 6.144 seconds');
const heldLights=lights();
scene.setState(state('ktv', {scene:'home',light_effect:'warm',ktv_brightness:'0'}, {fresh:false}));
now+=1200; scene.applyLighting(); assert.deepEqual(lights(),heldLights,'stale state freezes phase, scene and master');
scene.setState(state('disconnected', {}, {mode:'offline',fresh:false}));
now+=1200; scene.applyLighting(); assert.deepEqual(lights(),heldLights,'disconnect holds light color and level');
scene.setState(state('new-preview', {}, {mode:'simulation'}));
assert(lights().every(light => light.intensity===0),'new source cannot invent lit rooms');
scene.setState(state('ktv-effects', {scene:'ktv',light_effect:'pulse',ktv_brightness:'50'}));
near(level(),12/255*9);
now+=1200; scene.setState(state('ktv-effects', {scene:'ktv',light_effect:'pulse',ktv_brightness:'50'}));
near(level(),127/255*9);
scene.setState(state('ktv-effects', {scene:'ktv',light_effect:'party',ktv_brightness:'100'}));
assert(level(0)>0 && level(1)>0 && level(2)===0,'party starts on board pixels 0/3/5');
now+=180; scene.applyLighting();
assert(level(0)>0 && level(1)===0 && level(2)===0,'party advances the active pixels every 180ms');
for (const effect of ['rainbow','pulse','party']) {
  scene.setState(state('ktv-effects', {scene:'ktv',light_effect:effect,ktv_brightness:'0',living:'100',bedroom:'100',hall:'100'}));
  assert(lights().every(light => light.intensity===0 && light.emissive===0),'zero master is fully off for every effect');
}
scene.setState(state('legacy', {scene:'home',living:'20',bedroom:'20',hall:'20'}, {mode:'real'}));
assert.equal(scene.lightEffect,'warm');
assert(lights().every(light => light.color==='ffcb88' && light.intensity===1.8),'legacy room brightness remains warm');

scene.setState(state('appliances', {load_switch:'1',load_keep:'1'}));
assert.equal(screenSurface.material.map,scene.televisionTexture,'actual screen primitive displays the powered image');
assert(scene.televisionLight.intensity>0);
assert(scene.stoveRings.every(ring => ring.opacity>0));
assert(scene.fridgeIndicator.emissiveIntensity>0);
scene.setState(state('appliances', {load_switch:'0',load_keep:'1'}));
assert.equal(screenSurface.material.map,null,'switchable TV is dark');
assert.equal(scene.televisionLight.intensity,0);
assert(scene.stoveRings.every(ring => ring.opacity===0));
assert(scene.fridgeIndicator.emissiveIntensity>0,'switchable loads never turn off the always-powered fridge');
scene.setState(state('appliances-offline', {load_switch:'1',load_keep:'0'}, {mode:'offline',fresh:false}));
assert.equal(scene.televisionLight.intensity,0,'disconnect cannot turn a load on');
assert(scene.fridgeIndicator.emissiveIntensity>0,'disconnect holds fridge power indication');
scene.setState(state('appliances-new', {load_switch:'?',load_keep:'?'}));
assert.equal(scene.loadSwitch,null); assert.equal(scene.loadKeep,null);
assert.equal(scene.televisionLight.intensity,0); assert.equal(scene.fridgeIndicator.emissiveIntensity,0,'unknown is never inferred powered');
scene.setState(state('appliances-new', {load_switch:'1',load_keep:'1'}));
scene.setState(state('appliances-new', {load_switch:'0',load_keep:'0'}, {fresh:false}));
assert(scene.televisionLight.intensity>0 && scene.fridgeIndicator.emissiveIntensity>0,'stale load state freezes the display');
scene.setState(state('appliances-reset', {}));
assert.equal(scene.televisionLight.intensity,0); assert.equal(scene.fridgeIndicator.emissiveIntensity,0,'new session clears old power states');

now=0;
const studyState = (timer, seconds, currentScene='home', options={}) => scene.setState(state('study', {scene:currentScene,timer,timer_s:String(seconds),curtain:'37',living:'0',bedroom:'0',hall:'0'}, options));
studyState('running',1500); near(scene.studyLevel,.1);
assert(scene.timerCanvas.getContext('2d').texts.includes('25:00'),'timer shows authoritative remaining seconds');
now=2000; studyState('running',1498); near(scene.studyLevel,.6);
assert.equal(scene.studyLamp.light.color.getHexString(),'ffffff','study lamp stays white');
now=4000; studyState('running',1496); near(scene.studyLevel,.1);
studyState('paused',1496); near(scene.studyLevel,.2);
assert(scene.timerCanvas.getContext('2d').texts.includes('已暂停'));
const pausedDisplay=scene.timerDisplay;
studyState('done',0,'home',{fresh:false}); now=5000; scene.applyStudyLighting();
near(scene.studyLevel,.2); assert.equal(scene.timerDisplay,pausedDisplay,'stale timer cannot finish or advance its display');
scene.setState(state('study-offline', {}, {mode:'offline',fresh:false})); now=6000; scene.applyStudyLighting();
near(scene.studyLevel,.2); assert.equal(scene.timerDisplay,pausedDisplay,'disconnect freezes timer display and lamp');
studyState('running',1496); near(scene.studyLevel,.1);
now=7000; studyState('running',1495); near(scene.studyLevel,.35);
studyState('running',1500); near(scene.studyLevel,.1,'restart resets local breathing');
studyState('idle',0); assert.equal(scene.studyLevel,0); assert(scene.timerCanvas.getContext('2d').texts.includes('待开始'));
studyState('done',0); assert.equal(scene.studyLevel,0); assert(scene.timerCanvas.getContext('2d').texts.includes('已完成'));
for (const currentScene of ['away','long_away','ktv']) {studyState('running',100,currentScene); assert.equal(scene.studyLevel,0,`${currentScene} suppresses study overlay`);}
assert.equal(scene.motions.curtain.current,.37,'study never links or replaces curtain targets');
scene.setState(state('study-reset', {}));
assert.equal(scene.studyLevel,0); assert.equal(scene.timerStatus,'unknown'); assert.equal(scene.timerRemaining,'','new source clears old timer');
console.log('PASS: actuator/session/unknown/stale holds; KTV 3 effects, master 0/default/100, 6.144s wheel; ordinary warm/no floors; real TV material, stove and independent fridge; timer screen, white breathing/pause/stop/done/away/KTV, offline freeze, no curtain link');
