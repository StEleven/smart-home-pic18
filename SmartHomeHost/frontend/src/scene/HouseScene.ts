import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader, type GLTF } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import type { HostSnapshot } from '../types';
import { BINDINGS, binary, percentage, ktvPixel, studyBrightness, type AnimatedDevice } from './bindings';
import { HOUSE, MODEL_ASSETS } from './house.config';

interface Motion { current: number; target: number; known: boolean; initialized: boolean }
interface WallSide { group: THREE.Group; normal: THREE.Vector3 }
type ModelName = keyof typeof MODEL_ASSETS;

/** Local, self-contained Three.js presentation; all device authority stays in Python. */
export class HouseScene {
  readonly ready: Promise<void>;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(37, 1, 0.1, 90);
  private readonly renderer: THREE.WebGLRenderer;
  private readonly controls: OrbitControls;
  private readonly observer: ResizeObserver;
  private readonly house = new THREE.Group();
  private readonly roof = new THREE.Group();
  private readonly walls: WallSide[] = [];
  private readonly partitions: THREE.Group[] = [];
  private readonly loadingManager = new THREE.LoadingManager();
  private readonly loader = new GLTFLoader(this.loadingManager);
  private readonly assetErrors: string[] = [];
  private readonly modelCache = new Map<ModelName, Promise<GLTF>>();
  private readonly devices = new Map<string, THREE.Object3D[]>();
  private readonly pickables: THREE.Object3D[] = [];
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointer = new THREE.Vector2();
  private readonly motions = Object.fromEntries(Object.keys(BINDINGS).map(key => [key, {
    current: 0, target: 0, known: false, initialized: false,
  }])) as Record<AnimatedDevice, Motion>;
  private readonly doorAssembly = new THREE.Group();
  private doorNode: THREE.Object3D | null = null;
  private readonly windowPivot = new THREE.Group();
  private readonly curtains = [new THREE.Group(), new THREE.Group()];
  private readonly vent = new THREE.Group();
  private readonly louvers: THREE.Group[] = [];
  private readonly airflow = new THREE.Group();
  private readonly roomLights = new Map<string, { light: THREE.PointLight; bulb: THREE.MeshStandardMaterial; glow: THREE.Mesh }>();
  private lightEffect = 'warm';
  private lightEffectStarted = 0;
  private lightEffectElapsed = 0;
  private lightingScene = 'unknown';
  private ktvBrightness = 0.5;
  private loadSwitch: boolean | null = null;
  private loadKeep: boolean | null = null;
  private readonly televisionScreens: THREE.MeshBasicMaterial[] = [];
  private televisionTexture: THREE.CanvasTexture | null = null;
  private televisionLight: THREE.PointLight | null = null;
  private readonly stoveRings: THREE.MeshBasicMaterial[] = [];
  private fridgeIndicator: THREE.MeshStandardMaterial | null = null;
  private studyLamp: { light: THREE.PointLight; bulb: THREE.MeshStandardMaterial; glow: THREE.MeshBasicMaterial } | null = null;
  private timerCanvas: HTMLCanvasElement | null = null;
  private timerTexture: THREE.CanvasTexture | null = null;
  private timerStatus = 'unknown';
  private timerRemaining = '';
  private timerKnown = false;
  private timerDisplay = '';
  private studyStarted = 0;
  private studyElapsed = 0;
  private studyLevel = 0;
  private readonly rain = new THREE.Group();
  private readonly water = new THREE.Group();
  private readonly environment: THREE.WebGLRenderTarget;
  private readonly selectOutline = new THREE.BoxHelper(new THREE.Object3D(), 0x70e5cc);
  private readonly hoverOutline = new THREE.BoxHelper(new THREE.Object3D(), 0x9bcacb);
  private readonly clock = new THREE.Clock();
  private readonly errors = document.createElement('div');
  private frame = 0;
  private disposed = false;
  private loading = true;
  private selected = '';
  private hovered = '';
  private wallsVisible = false;
  private snapshot: HostSnapshot | null = null;
  private stateReceivedAt = 0;
  private latestSession = '';
  private firstValid = true;
  private down: { x: number; y: number; dragged: boolean } | null = null;
  private rainActive = false;
  private waterActive = false;
  private coolingActive = false;
  private glLost = false;
  private renderedFrames = 0;
  private lastRenderedAt = 0;
  private previousPose = '';
  private startTime = performance.now();
  private readonly materials = {
    wall: new THREE.MeshStandardMaterial({ color: 0xdcd5c8, roughness: 0.92 }),
    trim: new THREE.MeshStandardMaterial({ color: 0xeae5da, roughness: 0.65 }),
    oak: new THREE.MeshStandardMaterial({ color: 0xb18b64, roughness: 0.74 }),
    metal: new THREE.MeshStandardMaterial({ color: 0x414d4b, roughness: 0.4, metalness: 0.6 }),
    brass: new THREE.MeshStandardMaterial({ color: 0xbc9c63, roughness: 0.35, metalness: 0.65 }),
    teal: new THREE.MeshStandardMaterial({ color: 0x416d70, roughness: 0.95 }),
    glass: new THREE.MeshPhysicalMaterial({ color: 0xb4d5df, transparent: true, opacity: 0.25, roughness: 0.12, metalness: 0.05, side: THREE.DoubleSide, depthWrite: false }),
  };

  constructor(private readonly container: HTMLElement, private readonly onSelect: (id: string) => void) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    this.renderer.setClearColor(0x101b2a, 0);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 0.95;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.shadowMap.autoUpdate = false;
    this.renderer.shadowMap.needsUpdate = true;
    this.renderer.domElement.style.cssText = 'display:block;width:100%;height:100%;outline:none;touch-action:none';
    this.renderer.domElement.setAttribute('aria-label', '可旋转的三维智慧小屋，拖动旋转，滚轮缩放，点击设备查看状态');
    this.renderer.domElement.tabIndex = 0;
    container.appendChild(this.renderer.domElement);
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    const roomEnvironment = new RoomEnvironment();
    this.environment = pmrem.fromScene(roomEnvironment, 0.04);
    this.scene.environment = this.environment.texture;
    this.scene.environmentIntensity = 0.28;
    roomEnvironment.dispose();
    pmrem.dispose();
    this.scene.add(this.house, this.roof);
    this.house.name = 'house.shell'; this.roof.name = 'house.roof'; this.roof.visible = false;
    this.camera.position.fromArray(HOUSE.homeCamera);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.fromArray(HOUSE.cameraTarget);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.075;
    this.controls.minDistance = 7;
    this.controls.maxDistance = 24;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.08;
    this.controls.minPolarAngle = 0.08;
    this.controls.maxTargetRadius = 4;
    this.controls.screenSpacePanning = true;
    this.controls.addEventListener('change', this.onCameraChange);
    this.scene.add(this.selectOutline, this.hoverOutline);
    this.selectOutline.visible = false; this.hoverOutline.visible = false;
    for (const outline of [this.selectOutline, this.hoverOutline]) {
      (outline.material as THREE.LineBasicMaterial).transparent = true;
      (outline.material as THREE.LineBasicMaterial).opacity = 0.85;
      (outline.material as THREE.LineBasicMaterial).depthTest = false;
      outline.renderOrder = 20;
    }
    this.buildLighting();
    this.buildHouse();
    this.buildWindowAndCurtains();
    this.buildVent();
    this.buildIndicators();
    this.errors.style.cssText = 'position:absolute;inset:30% 8% auto;padding:20px;background:#19283a;color:#f3f6fa;border:1px solid #e0a095;border-radius:12px;z-index:10;display:none;font:14px/1.6 sans-serif';
    container.appendChild(this.errors);
    this.observer = new ResizeObserver(this.resize);
    this.observer.observe(container);
    this.resize();
    const canvas = this.renderer.domElement;
    canvas.addEventListener('pointerdown', this.pointerDown);
    canvas.addEventListener('pointermove', this.pointerMove);
    canvas.addEventListener('pointerup', this.pointerUp);
    canvas.addEventListener('pointerleave', this.pointerLeave);
    canvas.addEventListener('pointercancel', this.pointerCancel);
    canvas.addEventListener('webglcontextlost', this.contextLost);
    canvas.addEventListener('webglcontextrestored', this.contextRestored);
    this.loadingManager.onError = (url: string): void => { this.assetErrors.push(url); };
    this.ready = this.loadAssets().then(() => {
      if (this.disposed) return;
      // GLTFLoader can otherwise accept a GLB after a dependent image fails.
      if (this.assetErrors.length) throw new Error(`依赖资源不可用：${this.assetErrors.join('、')}`);
      this.loading = false;
      this.renderer.shadowMap.needsUpdate = true;
      this.applyPose();
      this.onCameraChange();
      this.setSelected(this.selected);
    }).catch((reason: unknown) => {
      const error = reason instanceof Error ? reason : new Error(String(reason));
      this.showError(`三维资产加载失败：${error.message}。请检查本地 assets 目录并重新加载。`);
      throw error;
    });
    this.frame = requestAnimationFrame(this.animate);
  }

  private box(parent: THREE.Object3D, size: [number, number, number], at: [number, number, number], material: THREE.Material, radius = 0): THREE.Mesh {
    const geometry = radius > 0 ? new RoundedBoxGeometry(...size, 2, radius) : new THREE.BoxGeometry(...size);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(...at); mesh.castShadow = true; mesh.receiveShadow = true;
    parent.add(mesh); return mesh;
  }

  private buildLighting(): void {
    this.scene.add(new THREE.HemisphereLight(0xd8e7f4, 0x807466, 0.95));
    const sun = new THREE.DirectionalLight(0xfff0d6, 2.7);
    sun.position.set(-3, 12, 8); sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -8, right: 8, top: 7, bottom: -7, near: 1, far: 30 });
    sun.shadow.normalBias = 0.025; sun.shadow.bias = -0.0003; sun.shadow.radius = 4;
    this.scene.add(sun);
    const rim = new THREE.DirectionalLight(0xbbd7f5, 0.65); rim.position.set(6, 6, -7); this.scene.add(rim);
    const platform = this.box(this.scene, [11.8, 0.22, 9.6], [0, -0.52, 0], new THREE.MeshStandardMaterial({ color: 0x263c47, roughness: 0.9 }), 0.22);
    platform.name = 'display.plinth';
    this.box(this.scene, [9.3, 0.13, 7.3], [0, -0.32, 0], new THREE.MeshStandardMaterial({ color: 0xa9b5ad, roughness: 0.9 }), 0.1);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), new THREE.ShadowMaterial({ opacity: 0.17 }));
    ground.rotation.x = -Math.PI / 2; ground.position.y = -0.64; ground.receiveShadow = true; this.scene.add(ground);
  }

  private buildHouse(): void {
    this.box(this.house, [8.28, 0.22, 6.28], [0, -0.1, 0], this.materials.trim, 0.04);
    const floorMap = this.woodTexture();
    const floorMaterial = new THREE.MeshStandardMaterial({ map: floorMap, roughness: 0.84, color: 0xe8c69d });
    this.box(this.house, [7.85, 0.05, 5.85], [0, 0.012, 0], floorMaterial);
    const tileMat = new THREE.MeshStandardMaterial({ color: 0xadb4aa, roughness: 0.85 });
    for (let x = -3.7; x < 0.3; x += 0.45) for (let z = -2.7; z < -0.4; z += 0.45) {
      this.box(this.house, [0.44, 0.014, 0.44], [x, 0.047, z], tileMat);
    }
    const makeSide = (normal: THREE.Vector3): THREE.Group => {
      const group = new THREE.Group(); this.house.add(group); this.walls.push({ group, normal }); return group;
    };
    const back = makeSide(new THREE.Vector3(0, 0, -1));
    this.box(back, [8.16, 2.65, 0.16], [0, 1.36, -3], this.materials.wall);
    this.box(back, [8.16, 0.10, 0.06], [0, 0.11, -2.89], this.materials.trim);
    const left = makeSide(new THREE.Vector3(-1, 0, 0));
    this.box(left, [0.16, 2.65, 6], [-4, 1.36, 0], this.materials.wall);
    this.box(left, [0.06, 0.10, 5.85], [-3.89, 0.11, 0], this.materials.trim);
    const right = makeSide(new THREE.Vector3(1, 0, 0));
    this.box(right, [0.16, 2.65, 6], [4, 1.36, 0], this.materials.wall);
    const front = makeSide(new THREE.Vector3(0, 0, 1));
    // These segments leave real holes for the living window and the imported doorway.
    for (const [min, max] of [[-4, -3.2], [-0.8, 0.55], [2.55, 4]]) {
      this.box(front, [max - min, 2.65, 0.16], [(min + max) / 2, 1.36, 3], this.materials.wall);
    }
    this.box(front, [2.4, 0.84, 0.16], [-2, 0.46, 3], this.materials.wall);
    this.box(front, [2.4, 0.29, 0.16], [-2, 2.545, 3], this.materials.wall);
    this.box(front, [2, 0.25, 0.16], [1.55, 2.565, 3], this.materials.wall);
    // A low perimeter keeps the dollhouse grounded when the camera-facing walls are cut away.
    for (const [min, max] of [[-4, -3.2], [-0.8, 1.04], [2.1, 4]]) {
      this.box(this.house, [max - min, 0.35, 0.16], [(min + max) / 2, 0.19, 3], this.materials.wall);
    }
    this.box(this.house, [0.16, 0.35, 6], [4, 0.19, 0], this.materials.wall);
    this.box(this.house, [0.14, 0.68, 3], [0.46, 0.37, -1.5], this.materials.wall);
    this.box(this.house, [0.7, 0.68, 0.14], [0.81, 0.37, -0.02], this.materials.wall);
    this.box(this.house, [1.8, 0.68, 0.14], [3.1, 0.37, -0.02], this.materials.wall);
    const partition = new THREE.Group(); this.house.add(partition); this.partitions.push(partition);
    this.box(partition, [0.14, 1.97, 3], [0.46, 1.695, -1.5], this.materials.wall);
    this.box(partition, [0.7, 1.97, 0.14], [0.81, 1.695, -0.02], this.materials.wall);
    this.box(partition, [1.8, 1.97, 0.14], [3.1, 1.695, -0.02], this.materials.wall);
    partition.visible = false;
    // Open kitchen/living zone, with a rug and separate entry runner.
    this.box(this.house, [3.1, 0.025, 2.35], [-1.9, 0.064, 1.13], this.fabricMaterial(0x698685), 0.07);
    this.box(this.house, [1.05, 0.02, 1.72], [1.57, 0.055, 1.75], this.fabricMaterial(0xd5c1a3), 0.025);
    this.box(this.house, [2.3, 0.025, 2.45], [2.3, 0.06, -1.49], this.fabricMaterial(0xb1bab0), 0.05);
    this.buildRoomLamp('living', -1.8, 1.1);
    this.buildRoomLamp('bedroom', 2.3, -1.5);
    this.buildRoomLamp('hall', 1.65, 1.6);
    // Decorative prints are physical frames, not state panels.
    this.artwork(-3.88, 1.75, -0.38, Math.PI / 2, 0x6f8981);
    this.artwork(2.27, 1.8, -2.89, 0, 0xbaa181);
    const roofMat = new THREE.MeshStandardMaterial({ color: 0x3c595d, roughness: 0.85 });
    for (const sign of [-1, 1]) {
      const panel = this.box(this.roof, [8.8, 0.13, 3.65], [0, 3.20, sign * 1.60], roofMat);
      panel.rotation.x = sign * 0.31;
      for (let i = 0; i < 20; i++) {
        const rib = this.box(this.roof, [0.025, 0.035, 3.67], [-4.2 + i * 0.44, 3.27, sign * 1.60], roofMat);
        rib.rotation.x = sign * 0.31;
      }
    }
    this.box(this.roof, [8.9, 0.12, 0.2], [0, 3.77, 0], roofMat, 0.05);
    // Garden strips and stepping stones make the miniature read as a home.
    const grass = new THREE.MeshStandardMaterial({ color: 0x718b69, roughness: 1 });
    this.box(this.house, [0.48, 0.06, 5.7], [-4.47, -0.2, 0], grass, 0.05);
    this.box(this.house, [0.48, 0.06, 5.7], [4.47, -0.2, 0], grass, 0.05);
    for (let i = 0; i < 3; i++) this.box(this.house, [0.7, 0.06, 0.34], [1.55, -0.20, 3.35 + i * 0.46], this.materials.trim, 0.025);
  }

  private artwork(x: number, y: number, z: number, angle: number, color: number): void {
    const group = new THREE.Group(); group.position.set(x, y, z); group.rotation.y = angle; this.house.add(group);
    this.box(group, [0.76, 0.84, 0.035], [0, 0, 0], this.materials.oak);
    this.box(group, [0.67, 0.75, 0.012], [0, 0, 0.025], this.materials.trim);
    const arc = new THREE.Mesh(new THREE.CircleGeometry(0.22, 30), new THREE.MeshBasicMaterial({ color }));
    arc.position.set(-0.05, 0.05, 0.035); group.add(arc);
    this.box(group, [0.4, 0.15, 0.01], [0.05, -0.15, 0.035], this.materials.teal);
  }

  private buildWindowAndCurtains(): void {
    const frame = new THREE.Group(); frame.name = 'window.living.frame'; frame.position.set(-2, 0.94, 3); this.house.add(frame);
    for (const sign of [-1, 1]) {
      this.box(frame, [0.07, 1.43, 0.17], [sign * 1.14, 0.69, 0], this.materials.trim);
      this.box(frame, [2.35, 0.07, 0.17], [0, sign === 1 ? 1.4 : 0, 0], this.materials.trim);
    }
    this.box(frame, [2.53, 0.08, 0.34], [0, -0.055, 0], this.materials.oak, 0.025);
    this.windowPivot.name = 'window.living.pivot'; this.windowPivot.position.fromArray(HOUSE.windowHinge); this.house.add(this.windowPivot);
    const sash = new THREE.Group(); sash.name = 'window.living.panel'; this.windowPivot.add(sash);
    this.box(sash, [2.19, 1.29, 0.036], [1.1, 0.69, 0], this.materials.glass);
    for (const x of [0.03, 1.1, 2.17]) this.box(sash, [0.045, 1.34, 0.07], [x, 0.69, 0], this.materials.oak);
    for (const y of [0.04, 1.34]) this.box(sash, [2.2, 0.05, 0.07], [1.1, y, 0], this.materials.oak);
    this.box(sash, [0.04, 0.17, 0.07], [2.08, 0.69, -0.04], this.materials.brass, 0.01);
    this.register('window', frame); this.register('window', this.windowPivot);
    const rail = this.box(this.house, [2.78, 0.045, 0.045], [-2, 2.51, 2.76], this.materials.brass, 0.015);
    this.register('curtain', rail);
    const curtainMaterial = this.fabricMaterial(0xc1ad8a); curtainMaterial.side = THREE.DoubleSide;
    for (const [index, side] of [-1, 1].entries()) {
      const group = this.curtains[index]; group.name = index === 0 ? 'curtain.left' : 'curtain.right';
      group.position.set(-2 + side * 1.3, 1.54, 2.74); this.house.add(group);
      const geometry = new THREE.PlaneGeometry(1.3, 1.82, 48, 3);
      const positions = geometry.attributes.position;
      for (let i = 0; i < positions.count; i++) {
        const px = positions.getX(i) + 0.65;
        positions.setX(i, side === -1 ? px : -px);
        positions.setZ(i, Math.cos(px / 1.3 * Math.PI * 14) * 0.055);
      }
      geometry.computeVertexNormals(); const fabric = new THREE.Mesh(geometry, curtainMaterial); fabric.castShadow = true; fabric.receiveShadow = true; group.add(fabric);
      this.register('curtain', group);
    }
  }

  private buildVent(): void {
    this.vent.name = 'vent.pivot'; this.vent.position.set(-3.84, 2.14, 1.25); this.vent.rotation.y = Math.PI / 2; this.house.add(this.vent);
    this.box(this.vent, [1.28, 0.37, 0.22], [0, 0, 0], this.materials.trim, 0.055);
    this.box(this.vent, [1.1, 0.21, 0.018], [0, -0.04, 0.13], this.materials.metal, 0.015);
    for (let i = 0; i < 4; i++) {
      const pivot = new THREE.Group(); pivot.name = `vent.louver.${i}`; pivot.position.set(0, -0.105 + i * 0.045, 0.15);
      this.box(pivot, [1.04, 0.022, 0.1], [0, 0, 0], this.materials.trim, 0.008); this.louvers.push(pivot); this.vent.add(pivot);
    }
    this.airflow.name = 'cooling.airflow'; this.vent.add(this.airflow);
    for (let i = 0; i < 5; i++) {
      const points = Array.from({ length: 17 }, (_, k) => new THREE.Vector3((i - 2) * 0.18 + Math.sin(k / 5) * 0.035, -k * 0.025, 0.25 + k * 0.10));
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineBasicMaterial({ color: 0x8bdfdf, transparent: true, opacity: 0.43 }));
      this.airflow.add(line);
    }
    this.airflow.visible = false; this.register('vent', this.vent); this.register('cooling', this.airflow);
  }

  private buildRoomLamp(id: string, x: number, z: number): void {
    const group = new THREE.Group(); group.name = `light.${id}`; group.position.set(x, 2.24, z); this.house.add(group);
    const shade = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.30, 0.23, 32, 1, true), this.materials.trim);
    shade.material = this.materials.trim.clone(); (shade.material as THREE.MeshStandardMaterial).side = THREE.DoubleSide;
    group.add(shade);
    this.box(group, [0.022, 0.3, 0.022], [0, 0.25, 0], this.materials.brass);
    const bulb = new THREE.MeshStandardMaterial({ color: 0xffecc6, emissive: 0xffcc7c, emissiveIntensity: 0.05, roughness: 0.45 });
    const disc = new THREE.Mesh(new THREE.CircleGeometry(0.24, 28), bulb); disc.rotation.x = Math.PI / 2; disc.position.y = -0.1; disc.material.side = THREE.DoubleSide; group.add(disc);
    const light = new THREE.PointLight(0xffcb88, 0, 4.5, 2); light.position.set(x, 1.98, z); this.house.add(light);
    const glow = new THREE.Mesh(new THREE.CircleGeometry(1.15, 48), new THREE.MeshBasicMaterial({ color: 0xffd99c, transparent: true, opacity: 0, depthWrite: false }));
    glow.rotation.x = -Math.PI / 2; glow.position.set(x, 0.09, z); this.house.add(glow);
    this.roomLights.set(id, { light, bulb, glow }); this.register(id, group);
    // Broad floor targets make rooms easy to select without a floating label wall.
    const hit = this.box(this.house, id === 'living' ? [3.5, 0.02, 2.6] : id === 'bedroom' ? [3.2, 0.02, 2.65] : [2.7, 0.02, 2.3], [x, 0.08, z], new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
    hit.name = `room.${id}.hit`; this.register(id, hit); hit.userData.floorHit = true;
  }

  private buildIndicators(): void {
    this.water.name = 'sensor.water'; this.water.position.set(-2.8, 0.075, -1.88); this.house.add(this.water);
    const puddle = new THREE.Mesh(new THREE.CircleGeometry(0.34, 40), new THREE.MeshBasicMaterial({ color: 0x61bad2, transparent: true, opacity: 0.20, depthWrite: false }));
    puddle.rotation.x = -Math.PI / 2; puddle.scale.set(1.25, 0.67, 1); this.water.add(puddle);
    this.sensor(this.water, 0xe4ece7); this.register('water', this.water);
    this.rain.name = 'sensor.rain'; this.rain.position.set(4.48, -0.12, -1.65); this.house.add(this.rain);
    this.sensor(this.rain, 0x789c9e); this.register('rain', this.rain);
    const drops = new THREE.Group(); drops.name = 'rain.drops'; this.rain.add(drops);
    const dropMaterial = new THREE.MeshBasicMaterial({ color: 0x9fdae9, transparent: true, opacity: 0.65 });
    for (let i = 0; i < 26; i++) {
      const drop = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.12, 4), dropMaterial);
      drop.position.set(Math.sin(i * 6.8) * 0.45, (i * 0.131) % 2.8 + 0.1, Math.cos(i * 3.1) * 0.8); drops.add(drop);
    }
    drops.visible = false;
    this.buildStudyArea();
    const load = this.box(this.house, [0.11, 0.18, 0.04], [0.35, 0.45, 2.8], this.materials.trim, 0.015); load.name = 'loads'; this.register('loads', load);
  }

  private buildStudyArea(): void {
    const desk = new THREE.Group(); desk.name = 'study.desk'; desk.position.set(3.42, 0, -0.58); this.house.add(desk);
    this.box(desk, [0.74, 0.065, 0.68], [0, 0.61, 0], this.materials.oak, 0.02);
    for (const x of [-0.30, 0.30]) for (const z of [-0.26, 0.26]) this.box(desk, [0.035, 0.58, 0.035], [x, 0.30, z], this.materials.metal);
    const lamp = new THREE.Group(); lamp.name = 'study.lamp'; lamp.position.set(-0.20, 0.66, -0.14); desk.add(lamp);
    this.box(lamp, [0.20, 0.025, 0.17], [0, 0, 0], this.materials.metal, 0.04);
    this.box(lamp, [0.025, 0.31, 0.025], [0, 0.16, 0], this.materials.brass);
    const shade = new THREE.Mesh(new THREE.ConeGeometry(0.15, 0.18, 32, 1, true), this.materials.teal.clone());
    (shade.material as THREE.MeshStandardMaterial).side = THREE.DoubleSide; shade.position.set(0, 0.32, 0); lamp.add(shade);
    const bulb = new THREE.MeshStandardMaterial({ color: 0xe9edef, emissive: 0xffffff, emissiveIntensity: 0, side: THREE.DoubleSide });
    const disc = new THREE.Mesh(new THREE.CircleGeometry(0.135, 32), bulb); disc.rotation.x = Math.PI / 2; disc.position.y = 0.235; lamp.add(disc);
    const light = new THREE.PointLight(0xffffff, 0, 1.65, 2); light.position.set(0, 0.23, 0); lamp.add(light);
    const glow = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthWrite: false });
    const pool = new THREE.Mesh(new THREE.CircleGeometry(0.24, 40), glow); pool.rotation.x = -Math.PI / 2; pool.position.set(-0.15, 0.648, 0.02); desk.add(pool);
    this.studyLamp = { light, bulb, glow }; this.register('timer', lamp);
    const timer = new THREE.Group(); timer.name = 'timer'; timer.position.set(0.16, 0.72, 0.18); desk.add(timer);
    this.box(timer, [0.34, 0.19, 0.07], [0, 0, 0], this.materials.teal, 0.025);
    this.timerCanvas = document.createElement('canvas'); this.timerCanvas.width = 512; this.timerCanvas.height = 280;
    this.timerTexture = new THREE.CanvasTexture(this.timerCanvas); this.timerTexture.colorSpace = THREE.SRGBColorSpace;
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.30, 0.155), new THREE.MeshBasicMaterial({ map: this.timerTexture }));
    screen.name = 'timer.display'; screen.position.z = 0.036; timer.add(screen); this.register('timer', timer);
    this.updateTimerDisplay();
  }

  private updateTimerDisplay(): void {
    if (!this.timerCanvas || !this.timerTexture) return;
    const display = `${this.timerStatus}:${this.timerRemaining}`;
    if (display === this.timerDisplay) return;
    this.timerDisplay = display;
    const ctx = this.timerCanvas.getContext('2d')!;
    ctx.fillStyle = '#122c31'; ctx.fillRect(0, 0, 512, 280);
    const labels: Record<string, string> = { running: '学习中', paused: '已暂停', done: '已完成', idle: '待开始', unknown: '未连接' };
    const colors: Record<string, string> = { running: '#dfffea', paused: '#f3d59b', done: '#b4e9ea', idle: '#9aafb2', unknown: '#7c8d94' };
    ctx.fillStyle = colors[this.timerStatus] || colors.unknown; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.font = '600 44px sans-serif'; ctx.fillText(labels[this.timerStatus] || labels.unknown, 256, 57);
    const seconds = /^\d+$/.test(this.timerRemaining) ? Number(this.timerRemaining) : null;
    const time = seconds === null ? '--:--' : `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
    ctx.font = '600 104px monospace'; ctx.fillText(time, 256, 162);
    ctx.fillRect(78, 240, 356, this.timerStatus === 'running' ? 9 : this.timerStatus === 'paused' ? 5 : 2);
    this.timerTexture.needsUpdate = true;
  }

  private configureTelevision(wrapper: THREE.Group): void {
    const canvas = document.createElement('canvas'); canvas.width = 512; canvas.height = 288;
    const ctx = canvas.getContext('2d')!;
    const sky = ctx.createLinearGradient(0, 0, 0, 288); sky.addColorStop(0, '#143d6e'); sky.addColorStop(1, '#83c8da');
    ctx.fillStyle = sky; ctx.fillRect(0, 0, 512, 288);
    ctx.fillStyle = '#e8eee0'; ctx.beginPath(); ctx.arc(394, 68, 29, 0, Math.PI * 2); ctx.fill();
    for (const [color, top, bottom] of [['#447d8a', 143, 288], ['#285b71', 195, 288]] as const) {
      ctx.fillStyle = color; ctx.beginPath(); ctx.moveTo(0, bottom); ctx.lineTo(0, top + 45); ctx.lineTo(113, top); ctx.lineTo(231, top + 68); ctx.lineTo(351, top + 8); ctx.lineTo(512, top + 58); ctx.lineTo(512, bottom); ctx.fill();
    }
    this.televisionTexture = new THREE.CanvasTexture(canvas); this.televisionTexture.colorSpace = THREE.SRGBColorSpace;
    // Kenney's metal primitive is the actual independent flat screen surface.
    wrapper.traverse(node => {
      if (!(node instanceof THREE.Mesh)) return;
      let isScreen = false;
      const replace = (material: THREE.Material): THREE.Material => {
        if (material.name !== 'metal') return material;
        isScreen = true;
        const screen = new THREE.MeshBasicMaterial({ color: 0x10171d }); screen.name = 'television.screen'; this.televisionScreens.push(screen); material.dispose(); return screen;
      };
      node.material = Array.isArray(node.material) ? node.material.map(replace) : replace(node.material);
      if (isScreen) {
        // The source UVs tile a plain material far outside 0..1. Give the
        // screen its own UVs so the image fills the real screen exactly once.
        node.geometry = node.geometry.clone();
        const positions = node.geometry.attributes.position, indices = node.geometry.index;
        const bounds = new THREE.Box3(), vertex = new THREE.Vector3();
        for (let i = 0; i < (indices?.count ?? positions.count); i++) bounds.expandByPoint(vertex.fromBufferAttribute(positions, indices ? indices.getX(i) : i));
        const size = bounds.getSize(new THREE.Vector3()), uv = new THREE.Float32BufferAttribute(new Float32Array(positions.count * 2), 2);
        for (let i = 0; i < positions.count; i++) uv.setXY(i, (positions.getX(i) - bounds.min.x) / size.x, (positions.getY(i) - bounds.min.y) / size.y);
        node.geometry.setAttribute('uv', uv);
      }
    });
    this.televisionLight = new THREE.PointLight(0x8bcce4, 0, 1.7, 2); this.televisionLight.position.set(0, 0.42, 0.18); wrapper.add(this.televisionLight);
    this.applyAppliances();
  }

  private configureStove(wrapper: THREE.Group): void {
    const height = 0.45 * 0.76 / 0.43;
    for (const x of [-0.17, 0.17]) for (const z of [-0.17, 0.17]) {
      const material = new THREE.MeshBasicMaterial({ color: 0xff652e, transparent: true, opacity: 0 }); this.stoveRings.push(material);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.09, 0.012, 8, 36), material); ring.name = 'stove.heat'; ring.rotation.x = -Math.PI / 2; ring.position.set(x, height + 0.005, z); wrapper.add(ring);
    }
    this.applyAppliances();
  }

  private configureFridge(wrapper: THREE.Group): void {
    this.fridgeIndicator = new THREE.MeshStandardMaterial({ color: 0x283c34, emissive: 0x8fe5b2, emissiveIntensity: 0 });
    const indicator = this.box(wrapper, [0.11, 0.024, 0.008], [0.12, 1.22, 0.25], this.fridgeIndicator, 0.005); indicator.name = 'fridge.power';
    this.applyAppliances();
  }

  private applyAppliances(): void {
    for (const screen of this.televisionScreens) {
      const texture = this.loadSwitch === true ? this.televisionTexture : null;
      if (screen.map !== texture) { screen.map = texture; screen.needsUpdate = true; }
      screen.color.setHex(this.loadSwitch === true ? 0xffffff : 0x10171d);
    }
    if (this.televisionLight) this.televisionLight.intensity = this.loadSwitch === true ? 0.75 : 0;
    for (const ring of this.stoveRings) ring.opacity = this.loadSwitch === true ? 0.85 : 0;
    if (this.fridgeIndicator) {
      this.fridgeIndicator.color.setHex(this.loadKeep === true ? 0xa9f5c4 : 0x283c34);
      this.fridgeIndicator.emissiveIntensity = this.loadKeep === true ? 1.25 : 0;
    }
  }

  private sensor(group: THREE.Group, color: number): void {
    this.box(group, [0.19, 0.08, 0.15], [0, 0.04, 0], new THREE.MeshStandardMaterial({ color, roughness: 0.8 }), 0.025);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.014, 6, 32), new THREE.MeshBasicMaterial({ color: 0x6aa69e, transparent: true, opacity: 0.5 }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.012; ring.name = 'sensor.ring'; group.add(ring);
  }

  private async loadModel(name: ModelName): Promise<GLTF> {
    let pending = this.modelCache.get(name);
    if (!pending) { pending = this.loader.loadAsync(MODEL_ASSETS[name]); this.modelCache.set(name, pending); }
    return pending;
  }

  private recolor(root: THREE.Object3D): void {
    root.traverse(node => {
      if (!(node instanceof THREE.Mesh)) return;
      node.castShadow = true; node.receiveShadow = true;
      const palette: Record<string, number> = {
        carpetBlue: 0x426b70, carpet: 0x7f9d8c, carpetWhite: 0xe5ded0,
        wood: 0xb08b62, woodDark: 0x765b40, plant: 0x52775b,
        metal: 0xb3b6af, metalDark: 0x465451, metalLight: 0xe3e6df,
      };
      const convert = (source: THREE.Material): THREE.Material => {
        const material = source.clone();
        if (material instanceof THREE.MeshStandardMaterial) {
          if (palette[material.name] !== undefined) material.color.setHex(palette[material.name]);
          material.roughness = material.name.startsWith('carpet') ? 0.96 : 0.72;
          material.metalness = material.name.startsWith('metal') ? 0.25 : 0;
        }
        return material;
      };
      node.material = Array.isArray(node.material) ? node.material.map(convert) : convert(node.material);
    });
  }

  private async place(name: ModelName, x: number, z: number, width: number, rotation = 0, id?: string, y = HOUSE.floorY): Promise<THREE.Group> {
    const gltf = await this.loadModel(name);
    const asset = gltf.scene.clone(true); this.recolor(asset);
    const bound = new THREE.Box3().setFromObject(asset); const size = bound.getSize(new THREE.Vector3());
    const scale = width / size.x;
    asset.scale.multiplyScalar(scale);
    const fit = new THREE.Box3().setFromObject(asset); const center = fit.getCenter(new THREE.Vector3());
    asset.position.set(-center.x, -fit.min.y, -center.z);
    const wrapper = new THREE.Group(); wrapper.name = `kenney.${name}`; wrapper.add(asset);
    wrapper.position.set(x, y, z); wrapper.rotation.y = rotation;
    if (this.disposed) { this.disposeObject(wrapper); return wrapper; }
    this.house.add(wrapper); if (id) this.register(id, wrapper);
    return wrapper;
  }

  private async loadAssets(): Promise<void> {
    const tasks: Promise<unknown>[] = [
      this.place('sofa', -2.0, 0.1, 2.55, 0, 'living'),
      this.place('armchair', -3.16, 1.67, 0.84, Math.PI / 2.5, 'living'),
      this.place('coffee', -1.8, 1.40, 1.15, 0, 'living', 0.09),
      this.place('plant', -3.4, 2.35, 0.46),
      this.place('floorLamp', -3.48, 0.04, 0.5, 0, 'living'),
      this.place('tvCabinet', -0.5, 1.32, 1.35, -Math.PI / 12, 'loads'),
      this.place('television', -0.5, 1.32, 1.08, -Math.PI / 12, 'loads', 0.58).then(model => { if (!this.disposed) this.configureTelevision(model); }),
      this.place('bed', 2.14, -1.49, 1.72, 0, 'bedroom'),
      this.place('bedside', 3.4, -2.08, 0.51, 0, 'bedroom'),
      this.place('smallPlant', 3.48, -2.13, 0.20, 0, undefined, 0.487),
      this.place('sink', -2.98, -2.52, 0.77, 0, 'water'),
      this.place('cabinet', -3.75, -2.52, 0.70),
      this.place('stove', -2.19, -2.52, 0.76, 0, 'loads').then(model => { if (!this.disposed) this.configureStove(model); }),
      this.place('cabinet', -1.42, -2.52, 0.76),
      this.place('fridge', -0.40, -2.48, 0.72, 0, 'loads').then(model => { if (!this.disposed) this.configureFridge(model); }),
      this.place('upper', -3.00, -2.73, 0.79, 0, undefined, 1.62),
      this.place('upper', -1.40, -2.73, 0.79, 0, undefined, 1.62),
      this.place('hood', -2.20, -2.69, 0.70, 0, undefined, 1.55),
      this.place('dining', -1.57, -1.17, 1.35),
      this.place('chair', -2.35, -1.15, 0.5, -Math.PI / 2),
      this.place('chair', -0.85, -1.15, 0.5, Math.PI / 2),
      this.place('smallPlant', -1.57, -1.17, 0.22, 0, undefined, 0.755),
      this.place('coatRack', 3.2, 2.28, 0.53, 0, 'hall'),
      this.place('sideTable', 3.36, 0.88, 0.6, 0, 'hall'),
      this.place('books', 3.36, 0.88, 0.29, 0, undefined, 0.473),
      this.place('plant', 4.45, 1.9, 0.4),
      this.place('plant', -4.46, -2.0, 0.42),
    ];
    tasks.push(this.loadModel('door').then(gltf => {
      const asset = gltf.scene.clone(true); this.recolor(asset);
      this.doorNode = asset.getObjectByName('door') ?? null;
      if (!this.doorNode) throw new Error('Kenney 门模型缺少独立 door 节点');
      this.doorAssembly.name = 'door.main.pivot'; this.doorAssembly.position.fromArray(HOUSE.doorHinge); this.doorAssembly.rotation.y = Math.PI / 2;
      this.doorAssembly.scale.set(1, 1.04, 1.09); this.doorAssembly.add(asset);
      if (this.disposed) { this.disposeObject(this.doorAssembly); return; }
      this.house.add(this.doorAssembly); this.register('door', this.doorAssembly);
    }));
    tasks.push(this.loadModel('doorway').then(gltf => {
      const portal = gltf.scene.clone(true); this.recolor(portal);
      portal.position.set(1.55, HOUSE.floorY, 3); portal.rotation.y = Math.PI / 2;
      // The original CC0 opening and its wall thickness remain intact.
      if (this.disposed) { this.disposeObject(portal); return; }
      this.house.add(portal); this.register('door', portal);
    }));
    await Promise.all(tasks);
  }

  private woodTexture(): THREE.CanvasTexture {
    const canvas = document.createElement('canvas'); canvas.width = 512; canvas.height = 512;
    const ctx = canvas.getContext('2d')!;
    for (let row = 0; row < 16; row++) {
      const tint = 170 + ((row * 17) % 25); ctx.fillStyle = `rgb(${tint + 23},${tint},${tint - 29})`;
      ctx.fillRect(0, row * 32, 512, 32);
      ctx.fillStyle = '#8a725821'; ctx.fillRect(0, row * 32, 512, 1);
      for (let j = 0; j < 18; j++) {
        ctx.strokeStyle = j % 2 ? '#634a3410' : '#f7e2c20f'; ctx.beginPath(); ctx.moveTo(0, row * 32 + j * 1.7); ctx.bezierCurveTo(180, row * 32 + j * 1.7 + 2, 340, row * 32 + j * 1.7 - 2, 512, row * 32 + j * 1.7); ctx.stroke();
      }
      const joint = ((row * 137) % 360) + 80; ctx.fillStyle = '#6e584333'; ctx.fillRect(joint, row * 32, 1, 32);
    }
    const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace; texture.wrapS = texture.wrapT = THREE.RepeatWrapping; texture.repeat.set(2, 2); texture.anisotropy = Math.min(8, this.renderer.capabilities.getMaxAnisotropy()); return texture;
  }

  private fabricMaterial(color: number): THREE.MeshStandardMaterial {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 64;
    const ctx = canvas.getContext('2d')!; ctx.fillStyle = '#cccccc'; ctx.fillRect(0, 0, 64, 64);
    for (let i = 0; i < 64; i += 2) { ctx.fillStyle = i % 4 ? '#b5b5b5' : '#dedede'; ctx.fillRect(i, 0, 1, 64); ctx.fillRect(0, i, 64, 1); }
    const texture = new THREE.CanvasTexture(canvas); texture.wrapS = texture.wrapT = THREE.RepeatWrapping; texture.repeat.set(8, 8); texture.colorSpace = THREE.SRGBColorSpace;
    return new THREE.MeshStandardMaterial({ color, roughness: 1, map: texture });
  }

  private register(id: string, object: THREE.Object3D): void {
    object.userData.deviceId = id; const list = this.devices.get(id) ?? []; list.push(object); this.devices.set(id, list); this.pickables.push(object);
  }

  setState(snapshot: HostSnapshot): void {
    const changedSession = snapshot.sessionId !== this.latestSession;
    this.snapshot = snapshot; this.stateReceivedAt = performance.now();
    if (changedSession) {
      this.latestSession = snapshot.sessionId; this.firstValid = true;
      // Offline keeps a frozen last pose. A new live source has no pose history:
      // an absent optional door_target must not inherit the previous demo's door.
      for (const motion of Object.values(this.motions)) {
        motion.known = false;
        if (snapshot.mode !== 'offline') { motion.initialized = false; motion.current = motion.target = 0; }
      }
      if (snapshot.mode !== 'offline') {
        this.lightingScene = 'unknown'; this.lightEffect = 'warm'; this.lightEffectElapsed = 0; this.ktvBrightness = 0.5;
        this.loadSwitch = this.loadKeep = null;
        this.timerStatus = 'unknown'; this.timerRemaining = ''; this.timerKnown = false; this.studyElapsed = this.studyLevel = 0;
      }
    }
    const usable = snapshot.fresh && snapshot.mode !== 'offline';
    if (usable) {
      const previousScene = this.lightingScene;
      this.lightingScene = snapshot.state.scene || this.lightingScene;
      const effect = this.lightingScene === 'ktv' ? snapshot.state.light_effect || 'rainbow' : 'warm';
      if (changedSession || effect !== this.lightEffect || previousScene !== this.lightingScene) {
        this.lightEffect = effect; this.lightEffectStarted = performance.now(); this.lightEffectElapsed = 0;
      }
      this.ktvBrightness = snapshot.state.ktv_brightness === undefined ? 0.5 : percentage(snapshot.state.ktv_brightness) ?? 0;
      this.loadSwitch = binary(snapshot.state.load_switch); this.loadKeep = binary(snapshot.state.load_keep);
      const timerStatus = snapshot.state.timer;
      this.timerKnown = ['running', 'paused', 'idle', 'done'].includes(timerStatus);
      if (this.timerKnown) {
        if (timerStatus === 'running' && (this.timerStatus !== 'running' || Number(snapshot.state.timer_s) > Number(this.timerRemaining))) {
          this.studyStarted = performance.now(); this.studyElapsed = 0;
        }
        this.timerStatus = timerStatus; this.timerRemaining = snapshot.state.timer_s ?? '';
      }
    }
    for (const [device, field] of Object.entries(BINDINGS) as [AnimatedDevice, string][]) {
      const motion = this.motions[device]; const value = percentage(snapshot.state[field]);
      motion.known = usable && value !== null;
      if (!motion.known) { motion.target = motion.current; continue; }
      motion.target = value!;
      if (this.firstValid || !motion.initialized) { motion.current = value!; motion.initialized = true; }
    }
    if (usable) this.firstValid = false;
    this.applyAppliances(); this.updateTimerDisplay();
    this.rainActive = usable && binary(snapshot.state.rain) === true;
    this.waterActive = usable && binary(snapshot.state.alarm ?? snapshot.state.water) === true;
    this.coolingActive = usable && binary(snapshot.state.cooling) === true;
    this.applyPose();
  }

  setSelected(id: string): void {
    this.selected = id; this.updateOutline(this.selectOutline, id);
  }

  setView(view: 'home' | 'top' | 'exterior'): void {
    if (view === 'top') this.camera.position.set(0.02, 16.8, 0.1);
    else if (view === 'exterior') { this.camera.position.set(11.7, 7.8, 13.6); this.setRoof(true); this.setWalls(true); }
    else this.camera.position.fromArray(HOUSE.homeCamera);
    this.controls.target.fromArray(HOUSE.cameraTarget); this.controls.update();
  }

  setRoof(visible: boolean): void {
    if (this.roof.visible !== visible) this.renderer.shadowMap.needsUpdate = true;
    this.roof.visible = visible;
  }
  setWalls(visible: boolean): void { this.wallsVisible = visible; this.onCameraChange(); }

  private isFresh(): boolean {
    return !!this.snapshot?.fresh && this.snapshot.mode !== 'offline' &&
      (this.snapshot.stateAgeMs ?? 0) + performance.now() - this.stateReceivedAt < 2000;
  }

  private applyPose(): void {
    const pose = [this.motions.door.current, this.motions.window.current, this.motions.curtain.current, this.motions.vent.current].join(',');
    if (pose !== this.previousPose) { this.previousPose = pose; this.renderer.shadowMap.needsUpdate = true; }
    if (this.doorNode) this.doorNode.rotation.y = this.motions.door.current * HOUSE.maxDoorAngle;
    this.windowPivot.rotation.y = this.motions.window.current * HOUSE.maxWindowAngle;
    const curtainWidth = 1 - this.motions.curtain.current * 0.79;
    for (const curtain of this.curtains) curtain.scale.x = curtainWidth;
    for (const louver of this.louvers) louver.rotation.x = -this.motions.vent.current * 0.9;
    this.applyLighting();
    this.applyStudyLighting();
    const fresh = this.isFresh();
    this.airflow.visible = fresh && this.coolingActive && this.motions.vent.known;
    const drops = this.rain.getObjectByName('rain.drops'); if (drops) drops.visible = fresh && this.rainActive;
    const puddle = this.water.children[0] as THREE.Mesh;
    (puddle.material as THREE.MeshBasicMaterial).opacity = this.waterActive ? 0.65 : 0.10;
    for (const [id, group] of [['water', this.water], ['rain', this.rain]] as const) {
      const ring = group.getObjectByName('sensor.ring') as THREE.Mesh;
      const material = ring.material as THREE.MeshBasicMaterial;
      const known = fresh && binary(this.snapshot?.state[id]) !== null;
      material.color.setHex(!known ? 0x87949a : (id === 'water' ? this.waterActive : this.rainActive) ? 0xf3b080 : 0x6aa69e);
      material.opacity = known ? 0.9 : 0.35;
    }
    // Unknown means the last pose is held; an unobtrusive material fade conveys uncertainty.
    for (const id of ['door', 'window', 'curtain', 'vent'] as AnimatedDevice[]) {
      const known = fresh && this.motions[id].known;
      for (const object of this.devices.get(id) ?? []) {
        object.traverse(node => {
          if (!(node instanceof THREE.Mesh)) return;
          for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
            if (!(material instanceof THREE.MeshStandardMaterial)) continue;
            if (!material.userData.baseColor) material.userData.baseColor = material.color.clone();
            material.color.copy(material.userData.baseColor as THREE.Color);
            if (!known) material.color.lerp(new THREE.Color(0x8b969a), 0.42);
          }
        });
      }
    }
  }

  private applyLighting(): void {
    const fresh = this.isFresh();
    if (fresh) this.lightEffectElapsed = performance.now() - this.lightEffectStarted;
    // The three room fixtures represent board pixels 0, 3 and 6 respectively.
    const pixels: Record<string, number> = {living: 0, bedroom: 3, hall: 6};
    for (const [id, room] of this.roomLights) {
      const motion = this.motions[id as AnimatedDevice];
      let brightness = motion.current;
      const glow = room.glow.material as THREE.MeshBasicMaterial;
      if (this.lightingScene === 'ktv') {
        const [r, g, b] = ktvPixel(this.lightEffectElapsed, pixels[id], this.lightEffect, this.ktvBrightness * 100);
        const total = r + g + b;
        brightness = total / 255;
        room.light.color.setRGB(total ? r / total : 0, total ? g / total : 0, total ? b / total : 0, THREE.SRGBColorSpace);
        room.bulb.emissive.copy(room.light.color); room.bulb.color.copy(room.light.color); glow.color.copy(room.light.color);
      } else {
        room.light.color.setHex(0xffcb88); room.bulb.emissive.setHex(0xffcc7c); room.bulb.color.setHex(0xffecc6); glow.color.setHex(0xffd99c);
      }
      room.bulb.emissiveIntensity = brightness * 2.3;
      room.light.intensity = brightness * 9; glow.opacity = brightness * 0.10;
    }
  }

  private applyStudyLighting(): void {
    if (this.isFresh() && this.timerKnown) {
      if (['away', 'long_away', 'ktv'].includes(this.lightingScene)) this.studyLevel = 0;
      else if (this.timerStatus === 'running') {
        this.studyElapsed = performance.now() - this.studyStarted;
        this.studyLevel = studyBrightness(this.studyElapsed);
      } else this.studyLevel = this.timerStatus === 'paused' ? 0.2 : 0;
    }
    if (!this.studyLamp) return;
    this.studyLamp.light.intensity = this.studyLevel * 4;
    this.studyLamp.bulb.emissiveIntensity = this.studyLevel * 3;
    this.studyLamp.glow.opacity = this.studyLevel * 0.32;
  }

  private readonly onCameraChange = (): void => {
    // Adapted from ch-bas applyWallDisplay's outward-normal cutaway principle;
    // this bounded fixed plan does not import its editor-dependent room builder.
    const direction = this.camera.position.clone().sub(this.controls.target);
    let changed = false;
    for (const wall of this.walls) {
      const visible = this.wallsVisible || wall.normal.dot(direction) < 0.4;
      if (wall.group.visible !== visible) changed = true;
      wall.group.visible = visible;
    }
    for (const partition of this.partitions) {
      if (partition.visible !== this.wallsVisible) changed = true;
      partition.visible = this.wallsVisible;
    }
    if (changed) this.renderer.shadowMap.needsUpdate = true;
    this.updateOutline(this.selectOutline, this.selected);
  };

  private visible(object: THREE.Object3D): boolean {
    let node: THREE.Object3D | null = object;
    while (node) { if (!node.visible) return false; node = node.parent; } return true;
  }

  private pick(event: PointerEvent): string {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const intersections = this.raycaster.intersectObjects(this.pickables.filter(object => this.visible(object)), true);
    const eligible = intersections.filter(hit => this.visible(hit.object));
    // Small fixtures win over the broad transparent floor selection areas.
    const first = eligible.find(hit => !hit.object.userData.floorHit) ?? eligible[0];
    if (!first) return '';
    let object: THREE.Object3D | null = first.object;
    while (object) { if (object.userData.deviceId) return object.userData.deviceId as string; object = object.parent; }
    return '';
  }

  private updateOutline(outline: THREE.BoxHelper, id: string): void {
    const objects = (this.devices.get(id) ?? []).filter(object => this.visible(object) && !object.userData.floorHit);
    if (!objects.length) { outline.visible = false; return; }
    const bounds = new THREE.Box3(); for (const object of objects) bounds.expandByObject(object);
    if (bounds.isEmpty()) { outline.visible = false; return; }
    // BoxHelper's public API accepts one object; set the geometry from the union ourselves.
    const min = bounds.min, max = bounds.max;
    const array = outline.geometry.attributes.position as THREE.BufferAttribute;
    const corners = [[max.x,max.y,max.z],[min.x,max.y,max.z],[min.x,min.y,max.z],[max.x,min.y,max.z],[max.x,max.y,min.z],[min.x,max.y,min.z],[min.x,min.y,min.z],[max.x,min.y,min.z]];
    corners.forEach((p, i) => array.setXYZ(i, p[0], p[1], p[2])); array.needsUpdate = true; outline.geometry.computeBoundingSphere(); outline.visible = true;
  }

  private readonly pointerDown = (event: PointerEvent): void => { if (event.button === 0) this.down = { x: event.clientX, y: event.clientY, dragged: false }; };
  private readonly pointerMove = (event: PointerEvent): void => {
    if (this.down && Math.hypot(event.clientX - this.down.x, event.clientY - this.down.y) > 5) this.down.dragged = true;
    if (this.down?.dragged) { this.hoverOutline.visible = false; this.renderer.domElement.style.cursor = 'grabbing'; return; }
    this.hovered = this.pick(event); this.renderer.domElement.style.cursor = this.hovered ? 'pointer' : 'grab';
    this.updateOutline(this.hoverOutline, this.hovered === this.selected ? '' : this.hovered);
  };
  private readonly pointerUp = (event: PointerEvent): void => {
    const down = this.down; this.down = null;
    if (event.button !== 0 || !down || down.dragged || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5) return;
    const id = this.pick(event); if (id) { this.setSelected(id); this.onSelect(id); }
  };
  private readonly pointerLeave = (): void => { this.hoverOutline.visible = false; this.hovered = ''; };
  private readonly pointerCancel = (): void => { this.down = null; this.pointerLeave(); };
  private readonly resize = (): void => {
    const width = Math.max(this.container.clientWidth, 1), height = Math.max(this.container.clientHeight, 1);
    this.renderer.setSize(width, height, false); this.camera.aspect = width / height; this.camera.updateProjectionMatrix();
  };
  private readonly contextLost = (event: Event): void => { event.preventDefault(); this.glLost = true; this.showError('三维图形上下文已丢失。正在等待显卡恢复；仍可在设备面板查看状态。'); };
  private readonly contextRestored = (): void => { this.glLost = false; this.errors.style.display = 'none'; };
  private showError(message: string): void { if (this.disposed) return; this.errors.textContent = message; this.errors.style.display = 'block'; }

  private readonly animate = (time: number): void => {
    if (this.disposed) return; this.frame = requestAnimationFrame(this.animate);
    // Windows presentation uses back-to-back begin frames to avoid a slow
    // software-compositor cadence. Bound real WebGL work to 60 Hz.
    const interval = 1000 / 60, elapsed = time - this.lastRenderedAt;
    if (elapsed < interval) return;
    this.lastRenderedAt = time - elapsed % interval;
    const dt = Math.min(this.clock.getDelta(), 0.05);
    if (document.hidden || this.glLost) return;
    this.controls.update();
    const fresh = this.isFresh();
    if (fresh) for (const motion of Object.values(this.motions)) {
      if (!motion.known) continue;
      const delta = motion.target - motion.current;
      motion.current += Math.sign(delta) * Math.min(Math.abs(delta), dt / 0.85);
    }
    this.applyPose();
    if (fresh && this.coolingActive) {
      const phase = performance.now() * 0.002;
      this.airflow.children.forEach((line, i) => { line.position.z = ((phase + i * 0.1) % 0.4); });
    }
    if (fresh && this.rainActive) this.rain.getObjectByName('rain.drops')?.children.forEach((drop, i) => { drop.position.y -= dt * 2.1; if (drop.position.y < 0.05) drop.position.y = 2.6 + (i % 3) * 0.1; });
    if (this.selectOutline.visible) this.updateOutline(this.selectOutline, this.selected);
    if (this.hoverOutline.visible) this.updateOutline(this.hoverOutline, this.hovered);
    this.renderer.render(this.scene, this.camera); this.renderedFrames++;
  };

  getDebugState(): object {
    return {
      loading: this.loading, fresh: this.isFresh(), sessionId: this.latestSession,
      selected: this.selected, roofVisible: this.roof.visible, wallsVisible: this.wallsVisible,
      motions: structuredClone(this.motions),
      lightEffect: this.lightEffect,
      lightingScene: this.lightingScene, ktvBrightness: this.ktvBrightness,
      appliances: { switched: this.loadSwitch, kept: this.loadKeep, televisionLit: this.televisionLight?.intensity ?? 0, stoveRings: this.stoveRings.map(ring => ring.opacity), fridgeLit: this.fridgeIndicator?.emissiveIntensity ?? 0 },
      study: { status: this.timerStatus, remaining: this.timerRemaining, brightness: this.studyLevel },
      lights: Object.fromEntries([...this.roomLights].map(([id, room]) => [id, {color: room.light.color.getHexString(), intensity: room.light.intensity}])),
      doorHierarchy: this.doorNode ? { name: this.doorNode.name, children: this.doorNode.children.map(child => child.name), rotation: this.doorNode.rotation.y } : null,
      windowRotation: this.windowPivot.rotation.y,
      curtainScales: this.curtains.map(curtain => curtain.scale.x),
      ventRotations: this.louvers.map(louver => louver.rotation.x),
      coolingVisible: this.airflow.visible, rainVisible: this.rain.getObjectByName('rain.drops')?.visible,
      camera: this.camera.position.toArray(), target: this.controls.target.toArray(),
      models: [...this.modelCache.keys()], deviceIds: [...this.devices.keys()],
      render: { calls: this.renderer.info.render.calls, triangles: this.renderer.info.render.triangles, frames: this.renderedFrames, elapsedMs: performance.now() - this.startTime, renderer: this.renderer.getContext().getParameter(this.renderer.getContext().RENDERER) },
    };
  }

  private disposeObject(object: THREE.Object3D): void {
    const textures = new Set<THREE.Texture>(), materials = new Set<THREE.Material>(), geometries = new Set<THREE.BufferGeometry>();
    object.traverse(node => {
      if (node instanceof THREE.Mesh || node instanceof THREE.Line || node instanceof THREE.Points) {
        geometries.add(node.geometry);
        for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
          materials.add(material);
          for (const value of Object.values(material)) if (value instanceof THREE.Texture) textures.add(value);
        }
      }
    });
    geometries.forEach(geometry => geometry.dispose()); materials.forEach(material => material.dispose()); textures.forEach(texture => texture.dispose());
  }

  dispose(): void {
    if (this.disposed) return; this.disposed = true; cancelAnimationFrame(this.frame); this.observer.disconnect();
    this.controls.removeEventListener('change', this.onCameraChange); this.controls.dispose();
    const canvas = this.renderer.domElement;
    canvas.removeEventListener('pointerdown', this.pointerDown); canvas.removeEventListener('pointermove', this.pointerMove);
    canvas.removeEventListener('pointerup', this.pointerUp); canvas.removeEventListener('pointerleave', this.pointerLeave); canvas.removeEventListener('pointercancel', this.pointerCancel);
    canvas.removeEventListener('webglcontextlost', this.contextLost); canvas.removeEventListener('webglcontextrestored', this.contextRestored);
    this.disposeObject(this.scene); this.televisionTexture?.dispose(); this.environment.dispose(); this.renderer.dispose();
    this.modelCache.forEach(promise => { void promise.then(gltf => this.disposeObject(gltf.scene), () => {}); });
    canvas.remove(); this.errors.remove();
  }
}
