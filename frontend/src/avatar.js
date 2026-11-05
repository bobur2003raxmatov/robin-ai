/* ROBIN 3D Avatar — cute glossy robot: rounded helmet head, black glass face-screen with glowing LED eyes,
   ear pods, egg-shaped body with chest light, floating hands. Lip sync, eye tracking, emotional states.
   Uses global THREE (three.js r128 from cdnjs). Public API: setState, setColor, setMouth, attachAudio,
   pulseSyllable, resize, destroy. */
(function () {
  /* ---------- geometry helpers ---------- */
  // Rounded cube / squircle body: push sphere vertices onto a p-norm surface (p≈4 → soft box).
  function superEllipsoid(sx, sy, sz, p = 4, seg = 64) {
    const g = new THREE.SphereGeometry(1, seg, seg / 2 | 0);
    const pos = g.attributes.position, v = new THREE.Vector3();
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i);
      const r = Math.pow(Math.pow(Math.abs(v.x), p) + Math.pow(Math.abs(v.y), p) + Math.pow(Math.abs(v.z), p), 1 / p);
      v.divideScalar(r || 1);
      pos.setXYZ(i, v.x * sx, v.y * sy, v.z * sz);
    }
    g.computeVertexNormals();
    return g;
  }
  // Egg: sphere that narrows towards the bottom.
  function egg(rx, ry, rz) {
    const g = new THREE.SphereGeometry(1, 64, 48);
    const pos = g.attributes.position, v = new THREE.Vector3();
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i);
      const k = 1 - 0.16 * (-v.y);             // bottom narrower
      pos.setXYZ(i, v.x * rx * k, v.y * ry, v.z * rz * k);
    }
    g.computeVertexNormals();
    return g;
  }
  function roundedRectShape(w, h, r) {
    const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
    s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
    s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
    s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
    return s;
  }
  // Curved face plate: extruded rounded rect bent around the head's front.
  function facePlate(w, h, r, bend) {
    const g = new THREE.ExtrudeGeometry(roundedRectShape(w, h, r), { depth: 0.04, bevelEnabled: true, bevelThickness: 0.03,
      bevelSize: 0.03, bevelSegments: 6, curveSegments: 24 });
    const pos = g.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), y = pos.getY(i);
      pos.setZ(i, pos.getZ(i) - bend * (x * x * 0.9 + y * y * 0.5));
    }
    g.computeVertexNormals();
    return g;
  }
  function glowTexture(inner = "rgba(255,255,255,1)", outer = "rgba(255,255,255,0)") {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const ctx = c.getContext("2d"), gr = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    gr.addColorStop(0, inner); gr.addColorStop(1, outer);
    ctx.fillStyle = gr; ctx.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }

  class RobinAvatar {
    constructor(container, opts = {}) {
      this.el = container;
      this.opts = Object.assign({ color: "#3fd0ff", accent: "#7c6cff", eyeTracking: true, compact: false }, opts);
      this.state = "idle";
      this.mouth = 0; this.targetMouth = 0;
      this.look = { x: 0, y: 0 }; this.lookTarget = { x: 0, y: 0 };
      this.blink = 0; this.nextBlink = performance.now() + 2500;
      this.t0 = performance.now();
      if (!window.THREE) { container.innerHTML = '<div class="avatar-fallback">🤖</div>'; return; }
      try { this._init(); } catch (e) {
        // A 3D problem must never break the page that hosts the avatar.
        console.warn("ROBIN avatar:", e); this.destroyed = true;
        container.innerHTML = '<div class="avatar-fallback">🤖</div>';
      }
    }

    _init() {
      const w = this.el.clientWidth || 300, h = this.el.clientHeight || 300;
      this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      this.renderer.setSize(w, h);
      this.renderer.outputEncoding = THREE.sRGBEncoding;
      this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
      this.renderer.toneMappingExposure = 1.05;
      this.el.appendChild(this.renderer.domElement);
      this.scene = new THREE.Scene();
      this.camera = new THREE.PerspectiveCamera(30, w / h, 0.1, 100);
      const compact = this.opts.compact;
      this.camera.position.set(0, compact ? 0.95 : 0.75, compact ? 5.4 : 7.0);
      this.camera.lookAt(0, compact ? 0.85 : 0.6, 0);

      // Studio lighting for a glossy plastic look
      this.scene.add(new THREE.HemisphereLight(0xf2f6ff, 0x3a4060, 0.75));
      const key = new THREE.DirectionalLight(0xffffff, 1.15); key.position.set(2.5, 4, 4); this.scene.add(key);
      const fill = new THREE.DirectionalLight(0xdfe8ff, 0.45); fill.position.set(-4, 1.5, 2); this.scene.add(fill);
      const top = new THREE.PointLight(0xffffff, 0.6, 12); top.position.set(0, 4, 1.5); this.scene.add(top);
      this.rim = new THREE.PointLight(new THREE.Color(this.opts.color), 1.4, 9); this.rim.position.set(-2, 1.6, -2.2); this.scene.add(this.rim);

      const white = new THREE.MeshPhysicalMaterial({ color: 0xf4f6fb, roughness: 0.28, metalness: 0.05, clearcoat: 1, clearcoatRoughness: 0.12 });
      const grey = new THREE.MeshPhysicalMaterial({ color: 0xc9cfdc, roughness: 0.35, metalness: 0.1, clearcoat: 0.6 });
      const glass = new THREE.MeshPhysicalMaterial({ color: 0x05070d, roughness: 0.08, metalness: 0.2, clearcoat: 1, clearcoatRoughness: 0.03, reflectivity: 1 });
      this.ledMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(this.opts.color), toneMapped: false });  // vivid LEDs
      this.coreMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(this.opts.color), toneMapped: false });
      this.accentMat = new THREE.MeshPhysicalMaterial({ color: new THREE.Color(this.opts.color), emissive: new THREE.Color(this.opts.color),
        emissiveIntensity: 0.55, roughness: 0.25, clearcoat: 1 });
      this.glowTex = glowTexture();

      this.robot = new THREE.Group(); this.scene.add(this.robot);

      /* ---------- head ---------- */
      this.head = new THREE.Group(); this.head.position.y = 1.32; this.robot.add(this.head);
      const skull = new THREE.Mesh(superEllipsoid(0.86, 0.66, 0.66, 3.4), white); this.head.add(skull);
      const face = new THREE.Mesh(facePlate(1.3, 0.86, 0.36, 0.1), glass); face.position.set(0, -0.02, 0.66); this.head.add(face);
      // ear pods with glowing rings
      this.ears = [];
      for (const sx of [-1, 1]) {
        const pod = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.22, 0.16, 40), grey);
        pod.rotation.z = Math.PI / 2; pod.position.set(0.88 * sx, 0, 0); this.head.add(pod);
        const ring = new THREE.Mesh(new THREE.TorusGeometry(0.15, 0.028, 16, 48), this.accentMat);
        ring.rotation.y = Math.PI / 2; ring.position.set(0.97 * sx, 0, 0); this.head.add(ring);
        const cap = new THREE.Mesh(new THREE.SphereGeometry(0.12, 32, 16), white);
        cap.scale.set(0.45, 1, 1); cap.position.set(0.97 * sx, 0, 0); this.head.add(cap);
        this.ears.push(ring);
      }
      // small antenna nub
      const nub = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.05, 0.14, 16), grey); nub.position.y = 0.7; this.head.add(nub);
      this.antTip = new THREE.Mesh(new THREE.SphereGeometry(0.065, 24, 16), this.accentMat); this.antTip.position.y = 0.8; this.head.add(this.antTip);

      /* ---------- face LEDs ---------- */
      this.faceGroup = new THREE.Group(); this.faceGroup.position.set(0, -0.02, 0.765); this.head.add(this.faceGroup);
      this.eyes = [];
      for (const sx of [-1, 1]) {
        const g = new THREE.Group(); g.position.set(0.27 * sx, 0.06, 0);
        const open = new THREE.Mesh(new THREE.ShapeGeometry(roundedRectShape(0.2, 0.26, 0.1), 24), this.ledMat);
        const happy = new THREE.Mesh(new THREE.TorusGeometry(0.1, 0.03, 12, 32, Math.PI), this.ledMat);
        happy.position.y = -0.03; happy.visible = false;
        const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.glowTex, color: new THREE.Color(this.opts.color),
          transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false }));
        glow.scale.set(0.5, 0.5, 1); glow.position.z = -0.005;
        g.add(glow); g.add(open); g.add(happy); this.faceGroup.add(g);
        this.eyes.push({ g, open, happy, glow });
      }
      // mouth: rounded LED bar (lip sync stretches it), little smile when idle
      this.mouthMesh = new THREE.Mesh(new THREE.ShapeGeometry(roundedRectShape(0.16, 0.05, 0.025), 16), this.ledMat);
      this.mouthMesh.position.set(0, -0.2, 0); this.faceGroup.add(this.mouthMesh);
      this.smile = new THREE.Mesh(new THREE.TorusGeometry(0.075, 0.018, 10, 28, Math.PI), this.ledMat);
      this.smile.rotation.z = Math.PI; this.smile.position.set(0, -0.15, 0); this.faceGroup.add(this.smile);

      /* ---------- body ---------- */
      const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.2, 0.12, 32), grey); neck.position.y = 0.66; this.robot.add(neck);
      this.torso = new THREE.Mesh(egg(0.6, 0.62, 0.52), white); this.torso.position.y = 0.12; this.robot.add(this.torso);
      const seam = new THREE.Mesh(new THREE.TorusGeometry(0.585, 0.012, 8, 80), grey);
      seam.rotation.x = Math.PI / 2; seam.scale.set(1, 0.88, 1); seam.position.y = 0.1; this.robot.add(seam);
      // chest light panel
      const chest = new THREE.Mesh(facePlate(0.42, 0.26, 0.12, 0.35), glass); chest.position.set(0, 0.3, 0.47); chest.rotation.x = -0.12; this.robot.add(chest);
      this.core = new THREE.Mesh(new THREE.ShapeGeometry(roundedRectShape(0.28, 0.12, 0.06), 16), this.coreMat);
      this.core.position.set(0, 0.3, 0.6); this.core.rotation.x = -0.12; this.robot.add(this.core);
      this.coreGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.glowTex, color: new THREE.Color(this.opts.color),
        transparent: true, opacity: 0.45, blending: THREE.AdditiveBlending, depthWrite: false }));
      this.coreGlow.scale.set(0.8, 0.5, 1); this.coreGlow.position.set(0, 0.3, 0.56); this.robot.add(this.coreGlow);

      /* ---------- floating hands ---------- */
      this.arms = [];
      for (const sx of [-1, 1]) {
        const pivot = new THREE.Group(); pivot.position.set(0.66 * sx, 0.42, 0.02); this.robot.add(pivot);
        const hand = new THREE.Mesh(new THREE.SphereGeometry(0.2, 40, 24), white);
        hand.scale.set(0.72, 1.25, 0.78); hand.position.set(0.12 * sx, -0.32, 0); hand.rotation.z = 0.25 * sx;
        pivot.add(hand); pivot.rotation.z = 0.08 * sx;
        this.arms.push(pivot);
      }

      /* ---------- thinking halo, hover glow, shadow ---------- */
      this.halo = new THREE.Mesh(new THREE.TorusGeometry(0.62, 0.014, 8, 96),
        new THREE.MeshBasicMaterial({ color: new THREE.Color(this.opts.accent), transparent: true, opacity: 0 }));
      this.halo.rotation.x = Math.PI / 2.2; this.halo.position.y = 2.15; this.robot.add(this.halo);
      this.jet = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.glowTex, color: new THREE.Color(this.opts.color),
        transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false }));
      this.jet.scale.set(0.7, 0.45, 1); this.jet.position.y = -0.55; this.robot.add(this.jet);
      this.shadow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture("rgba(10,15,40,.45)", "rgba(10,15,40,0)"),
        transparent: true, depthWrite: false }));
      this.shadow.scale.set(1.5, 0.32, 1); this.shadow.position.y = -0.92; this.scene.add(this.shadow);

      this._onMove = (e) => {
        this.lookTarget.x = (e.clientX / window.innerWidth) * 2 - 1;
        this.lookTarget.y = -((e.clientY / window.innerHeight) * 2 - 1);
      };
      this._onResize = () => this.resize();
      if (this.opts.eyeTracking) window.addEventListener("mousemove", this._onMove);
      window.addEventListener("resize", this._onResize);
      this._ro = new ResizeObserver(this._onResize); this._ro.observe(this.el);
      this.setColor(this.opts.color, this.opts.accent);
      this._loop();
    }

    /** Stop rendering and free the WebGL context (called when the page changes). */
    destroy() {
      if (this.destroyed) return;
      this.destroyed = true;
      cancelAnimationFrame(this._raf);
      window.removeEventListener("mousemove", this._onMove);
      window.removeEventListener("resize", this._onResize);
      this._ro && this._ro.disconnect();
      clearTimeout(this._stateTimer);
      if (this.scene) this.scene.traverse((o) => { o.geometry && o.geometry.dispose(); o.material && o.material.dispose(); });
      if (this.renderer) { this.renderer.dispose(); this.renderer.forceContextLoss && this.renderer.forceContextLoss(); this.renderer.domElement.remove(); }
    }

    resize() {
      if (!this.renderer) return;
      const w = this.el.clientWidth, h = this.el.clientHeight;
      if (!w || !h) return;
      this.renderer.setSize(w, h); this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
    }

    _applyLed(colorHex) {
      const c = new THREE.Color(colorHex);
      this.ledMat.color.copy(c);
      this.eyes.forEach((e) => e.glow.material.color.copy(c));
    }

    setColor(color, accent) {
      this.opts.color = color || this.opts.color; this.opts.accent = accent || this.opts.accent;
      if (!this.ledMat) return;
      const c = new THREE.Color(this.opts.color);
      this._applyLed(this.opts.color);
      this.accentMat.color.copy(c); this.accentMat.emissive.copy(c); this.rim.color.copy(c); this.coreMat.color.copy(c);
      this.coreGlow.material.color.copy(c); this.jet.material.color.copy(c);
      this.halo.material.color = new THREE.Color(this.opts.accent);
    }

    setState(s) {
      this.state = s || "idle";
      if (!this.ledMat) return;
      const map = { warning: "#ff9a3d", happy: "#4dffa6", listening: "#8cf5ff" };
      this._applyLed(map[this.state] || this.opts.color);
      const happy = this.state === "happy";
      this.eyes.forEach((e) => { e.open.visible = !happy; e.happy.visible = happy; });
      clearTimeout(this._stateTimer);
      if (["happy", "warning"].includes(this.state)) this._stateTimer = setTimeout(() => this.setState("idle"), 4000);
    }

    setMouth(level) { this.targetMouth = Math.max(0, Math.min(1, level)); }

    /** Lip sync from an <audio> element via WebAudio analyser. */
    attachAudio(audioEl) {
      try {
        // One shared AudioContext/analyser per <audio> element: a media element can be wired only once.
        const ac = window.__robinAC || (window.__robinAC = new (window.AudioContext || window.webkitAudioContext)());
        if (ac.state === "suspended") ac.resume();
        if (!audioEl._robinAnalyser) {
          const src = ac.createMediaElementSource(audioEl);
          const an = ac.createAnalyser(); an.fftSize = 256;
          src.connect(an); an.connect(ac.destination);
          audioEl._robinAnalyser = an;
        }
        this.analyser = audioEl._robinAnalyser;
        this.freq = new Uint8Array(this.analyser.frequencyBinCount);
        this.setState("speaking");
        audioEl.addEventListener("ended", () => { this.speakingFromAudio = false; this.setState("idle"); this.setMouth(0); }, { once: true });
        this.speakingFromAudio = true;
      } catch (e) { console.warn("lip sync", e); }
    }

    /** Fallback lip sync for browser speechSynthesis (word boundary pulses). */
    pulseSyllable() { this.setMouth(0.6 + Math.random() * 0.4); setTimeout(() => this.setMouth(0.1), 120); }

    _loop() {
      if (this.destroyed) return;
      if (!this.el.isConnected) return this.destroy();  // element removed from the page
      this._raf = requestAnimationFrame(() => this._loop());
      const t = (performance.now() - this.t0) / 1000;
      const s = this.state;
      // hover + breathing
      const bob = Math.sin(t * 1.7) * 0.07;
      this.robot.position.y = bob;
      this.robot.rotation.y = Math.sin(t * 0.6) * 0.06;
      this.torso.scale.y = 1 + Math.sin(t * 1.7) * 0.012;
      this.shadow.scale.set(1.5 - bob, 0.32 - bob * 0.2, 1);
      this.shadow.material.opacity = 0.9 - bob * 2;
      this.jet.material.opacity = 0.35 + Math.sin(t * 18) * 0.08 + (s === "working" ? 0.3 : 0);
      // eye tracking
      this.look.x += (this.lookTarget.x - this.look.x) * 0.08;
      this.look.y += (this.lookTarget.y - this.look.y) * 0.08;
      let lx = this.look.x, ly = this.look.y;
      if (s === "thinking") { lx = Math.sin(t * 1.3) * 0.6; ly = 0.55; }
      this.head.rotation.y = lx * 0.42; this.head.rotation.x = -ly * 0.2;
      this.head.rotation.z = s === "listening" ? Math.sin(t * 2.2) * 0.09 : Math.sin(t * 0.8) * 0.02;
      this.faceGroup.position.x = lx * 0.05; this.faceGroup.position.y = -0.02 + ly * 0.035; this.faceGroup.position.z = 0.765;
      // blink
      const now = performance.now();
      if (now > this.nextBlink) { this.blink = 1; this.nextBlink = now + 2200 + Math.random() * 3500; }
      this.blink = Math.max(0, this.blink - 0.12);
      const lid = Math.max(0.08, 1 - Math.sin(this.blink * Math.PI));
      const wide = s === "listening" ? 1.12 : s === "warning" ? 0.8 : 1;
      this.eyes.forEach((e) => { e.open.scale.set(1, lid * wide, 1); e.glow.material.opacity = 0.18 + 0.2 * lid; });
      // mouth / lip sync
      if (this.speakingFromAudio && this.analyser) {
        this.analyser.getByteFrequencyData(this.freq);
        let sum = 0; for (let i = 2; i < 40; i++) sum += this.freq[i];
        this.targetMouth = Math.min(1, sum / (38 * 150));
      } else if (s === "speaking" && !this._externalMouth) {
        this.targetMouth = 0.3 + Math.abs(Math.sin(t * 13)) * 0.5;
      } else if (s !== "speaking") this.targetMouth *= 0.8;
      this.mouth += (this.targetMouth - this.mouth) * 0.35;
      const talking = this.mouth > 0.04;
      this.mouthMesh.visible = talking; this.smile.visible = !talking && s !== "warning";
      this.mouthMesh.scale.set(1 + this.mouth * 0.6, 1 + this.mouth * 4.5, 1);
      // ear rings, antenna, chest pulse
      const pulse = s === "listening" ? 0.6 + Math.sin(t * 8) * 0.4 : s === "thinking" ? 0.5 + Math.sin(t * 4) * 0.4 : 0.55 + Math.sin(t * 2) * 0.1;
      this.accentMat.emissiveIntensity = pulse;
      this.coreGlow.material.opacity = 0.25 + pulse * 0.35;
      this.antTip.scale.setScalar(1 + (s === "listening" ? Math.sin(t * 8) * 0.3 : 0));
      // halo
      const haloOn = s === "thinking" || s === "working";
      this.halo.material.opacity += ((haloOn ? 0.9 : 0) - this.halo.material.opacity) * 0.1;
      this.halo.rotation.z = t * 2;
      // hands: wave when happy, type-like motion when working, gentle float otherwise
      const [L, R] = this.arms;
      L.rotation.z = -0.08 + Math.sin(t * 1.7 + 1) * 0.05;
      R.rotation.z = 0.08 + Math.sin(t * 1.7) * 0.05;
      L.rotation.x = R.rotation.x = 0;
      if (s === "happy") { R.rotation.z = 2.4 + Math.sin(t * 11) * 0.35; }
      else if (s === "working") { L.rotation.x = Math.sin(t * 9) * 0.35; R.rotation.x = Math.sin(t * 9 + 1.5) * 0.35; }
      else if (s === "speaking") { R.rotation.z = 0.25 + Math.sin(t * 3) * 0.15; }
      else if (s === "warning") { L.rotation.z = -0.5; R.rotation.z = 0.5; }
      this.renderer.render(this.scene, this.camera);
    }
  }
  window.RobinAvatar = RobinAvatar;
})();
