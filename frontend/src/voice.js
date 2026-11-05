/* ROBIN Voice: live conversation (Web Speech API, uz-UZ / ru-RU / en-US), wake word, server STT fallback with
   voice-activity detection, neural TTS with streamed (chunked) playback + avatar lip sync, echo filter, barge-in. */
(function () {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const WAKE_VARIANTS = ["robin", "робин", "rabin", "robbin", "ro bin", "робен", "rubin"];

  class RobinVoice {
    constructor({ onFinal, onInterim, onState, getToken }) {
      this.onFinal = onFinal; this.onInterim = onInterim || (() => {}); this.onState = onState || (() => {});
      this.getToken = getToken; this.lang = "uz-UZ"; this.listening = false; this.live = false;
      this.wakeWord = "robin"; this.requireWake = false; this.audio = new Audio(); this.audio.crossOrigin = "anonymous";
      this.speaking = false; this._gen = 0; this.cfg = {};
    }
    get supported() { return !!SR; }

    /** Apply the user's voice settings (from /api/settings → voice). */
    configure(cfg = {}) {
      this.cfg = cfg || {};
      if (cfg.stt_lang) this.lang = cfg.stt_lang;
      this.wakeWord = (cfg.wake_word || "robin").toLowerCase();
      this.requireWake = !!cfg.require_wake;
    }

    /* ---------------- listening ---------------- */
    start(live = false) {
      this.live = live;
      if (!SR || this.cfg.stt_engine === "openai" || this.cfg.stt_engine === "gemini") return this.recordFallback();
      try { this.rec && this.rec.abort(); } catch (_) {}
      this.rec = new SR(); this.rec.lang = this.lang; this.rec.interimResults = true; this.rec.continuous = live;
      this.rec.maxAlternatives = 3;
      this.rec.onresult = (e) => {
        let interim = "", final = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const r = e.results[i];
          (r.isFinal ? (final += this._best(r)) : (interim += r[0].transcript));
        }
        const heard = final || interim;
        // The mic also hears ROBIN's own voice from the speakers — ignore that echo; otherwise barge-in.
        if (heard && this.speaking) {
          if (this._isEcho(heard)) return;
          if (this.cfg.barge_in === false) return;
          this.stopSpeaking();
        }
        if (interim) this.onInterim(interim);
        if (final.trim()) {
          let text = final.trim();
          if (this.requireWake) {
            const low = text.toLowerCase();
            const words = [this.wakeWord, ...WAKE_VARIANTS];
            let at = -1, len = 0;
            for (const w of words) { const i = low.indexOf(w); if (i >= 0 && (at < 0 || i < at)) { at = i; len = w.length; } }
            if (at < 0) return;
            text = text.slice(at + len).replace(/^[\s,.!?]+/, "");
            if (!text) { this.chime(880); return; }   // just the wake word → ready signal
          }
          this.onFinal(text);
        }
      };
      this.rec.onstart = () => { this.listening = true; this.onState("listening"); this.chime(660); };
      this.rec.onerror = (e) => {
        if (e.error === "not-allowed" || e.error === "service-not-allowed") { this.live = false; alert("Mikrofonga ruxsat bering (brauzer manzil satridagi 🔒 belgisi)"); }
        else if (e.error === "language-not-supported") { this.live = false; alert("Brauzer bu tilni tanimaydi. Ovoz sozlamalarida STT ni 'openai' yoki 'gemini' qiling."); }
        else if (e.error === "network") { this.live = false; this.recordFallback(); }
      };
      this.rec.onend = () => {
        this.listening = false;
        if (this.live) { setTimeout(() => { try { this.live && this.rec.start(); } catch (_) {} }, 150); }
        else { this.onState("idle"); this.chime(440); }
      };
      try { this.rec.start(); } catch (_) {}
    }

    // Pick the alternative that looks most like Uzbek/expected text (contains oʻ/gʻ, not empty).
    _best(r) {
      let best = r[0].transcript, score = -1;
      for (let i = 0; i < r.length; i++) {
        const t = r[i].transcript; const s = (r[i].confidence || 0) + (/[og]['ʻ’‘]/i.test(t) && this.lang.startsWith("uz") ? 0.15 : 0);
        if (s > score) { score = s; best = t; }
      }
      return best.replace(/[ʻ’‘`]/g, "'");
    }

    _words(t) { return (t || "").toLowerCase().replace(/[ʻʼ'’`]/g, "").split(/[^\p{L}\p{N}]+/u).filter((w) => w.length > 2); }

    _isEcho(heard) {
      const ws = this._words(heard);
      if (!ws.length) return true;               // too short to be a real interruption
      const hits = ws.filter((w) => this._spoken && this._spoken.has(w)).length;
      const thr = this.cfg.echo_filter != null ? Number(this.cfg.echo_filter) : 0.5;
      return hits / ws.length >= Math.max(0.15, Math.min(0.95, thr));
    }

    stop() {
      this.live = false;
      try { this.rec && this.rec.stop(); } catch (_) {}
      if (this.mr && this.mr.state === "recording") this.mr.stop();
      this.onState("idle");
    }

    async recordFallback() {
      // MediaRecorder → server Whisper/Gemini STT. Voice-activity detection stops recording after a pause.
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: this.cfg.noise_suppression !== false, autoGainControl: true } });
      } catch (_) { alert("Mikrofonga ruxsat bering"); return; }
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
      this.mr = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined); const chunks = [];
      this.mr.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      const ac = new (window.AudioContext || window.webkitAudioContext)(); const src = ac.createMediaStreamSource(stream);
      const an = ac.createAnalyser(); an.fftSize = 512; src.connect(an); const buf = new Uint8Array(an.fftSize);
      let spoke = false, quietSince = performance.now(); const t0 = performance.now(); const silence = Number(this.cfg.silence_ms) || 1500;
      const vad = () => {
        if (!this.mr || this.mr.state !== "recording") return;
        an.getByteTimeDomainData(buf); let sum = 0; for (const v of buf) sum += (v - 128) ** 2;
        const rms = Math.sqrt(sum / buf.length);
        if (rms > 6) { spoke = true; quietSince = performance.now(); }
        const now = performance.now();
        if ((spoke && now - quietSince > silence) || now - t0 > 30000 || (!spoke && now - t0 > 8000)) { this.mr.stop(); return; }
        requestAnimationFrame(vad);
      };
      this.mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop()); ac.close().catch(() => {}); this.mr = null; this.listening = false;
        this.chime(440);
        if (!spoke) { this.onState("idle"); if (this.live) setTimeout(() => this.live && this.recordFallback(), 300); return; }
        this.onState("thinking");
        const fd = new FormData(); fd.append("file", new Blob(chunks, { type: "audio/webm" }), "voice.webm");
        fd.append("language", this.lang.slice(0, 2));
        try {
          const r = await fetch("/api/voice/stt", { method: "POST", body: fd, headers: { Authorization: "Bearer " + this.getToken() } });
          const j = await r.json(); if (j.text) this.onFinal(j.text); else alert(j.detail || "Ovoz tanilmadi");
        } catch (e) { alert("Ovoz serverga yuborilmadi: " + e.message); }
        this.onState("idle");
      };
      this.mr.start(250); this.listening = true; this.onState("listening"); this.chime(660); requestAnimationFrame(vad);
    }

    /* ---------------- speaking ---------------- */
    // Split into chunks: a short first one (fast start), then ~450 chars, on sentence boundaries.
    _chunks(text) {
      let t = String(text || "");
      if (!this.cfg.read_code) t = t.replace(/```[\s\S]*?```/g, " (kod ekranda). ");
      const max = Number(this.cfg.max_chars) || 3000; if (t.length > max) t = t.slice(0, max);
      const sents = t.split(/(?<=[.!?…])\s+|\n{2,}/).map((s) => s.trim()).filter(Boolean);
      const out = []; let cur = "";
      for (const s of sents) {
        const lim = out.length === 0 ? 180 : 450;
        if (cur && (cur + " " + s).length > lim) { out.push(cur); cur = s; } else cur = cur ? cur + " " + s : s;
      }
      if (cur) out.push(cur);
      return out.length ? out : [t];
    }

    async _fetchTTS(text, overrides) {
      const r = await fetch("/api/voice/tts", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + this.getToken() }, body: JSON.stringify({ text, overrides }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
      return r.json();
    }

    _play(src, avatar) {
      return new Promise((resolve) => {
        this.audio.src = src; avatar && avatar.attachAudio(this.audio);
        this.audio.onended = () => resolve(true); this.audio.onerror = () => resolve(false);
        this.audio.play().catch(() => resolve(false));
      });
    }

    async speak(text, avatar, engine, overrides) {
      if (!text) return;
      engine = engine || this.cfg.tts_engine || "edge";
      this.stopSpeaking(); const gen = ++this._gen;
      this._spoken = new Set(this._words(text));
      if (engine === "browser" || !this.getToken()) return this.speakBrowser(text, avatar);
      const parts = this._chunks(text);
      this.speaking = true; this.onState("speaking");
      let next = this._fetchTTS(parts[0], overrides).catch((e) => ({ error: e.message }));
      for (let i = 0; i < parts.length; i++) {
        const j = await next; if (gen !== this._gen) return;
        next = i + 1 < parts.length ? this._fetchTTS(parts[i + 1], overrides).catch((e) => ({ error: e.message })) : null;  // prefetch
        if (j.error && !j.text) { console.warn("TTS:", j.error); await this.speakBrowser(parts[i], avatar, null, true); continue; }
        if (!j.file) { await this.speakBrowser(j.text || parts[i], avatar, j.lang, true); continue; }
        const ok = await this._play("/api/voice/audio/" + j.file, avatar);
        if (gen !== this._gen) return;
        if (!ok) await this.speakBrowser(parts[i], avatar, j.lang, true);
      }
      if (gen === this._gen) { this.speaking = false; this.onState(this.live ? "listening" : "idle"); avatar && avatar.setState && avatar.setState("idle"); }
    }

    speakBrowser(text, avatar, lang, chained = false) {
      return new Promise((resolve) => {
        if (!("speechSynthesis" in window)) return resolve();
        const u = new SpeechSynthesisUtterance(String(text).replace(/[*#`_>|]/g, ""));
        const l = lang || (/[а-яё]/i.test(text) ? "ru" : /[oʻ'g]['ʻ]|\b(va|bu|uchun|bilan)\b/i.test(text) ? "uz" : "en");
        u.lang = { uz: "uz-UZ", ru: "ru-RU", en: "en-US" }[l] || "uz-UZ";
        const vs = speechSynthesis.getVoices();
        const pick = (this.cfg.browser_voice && vs.find((v) => v.name === this.cfg.browser_voice && v.lang.startsWith(u.lang.slice(0, 2))))
          || vs.find((v) => v.lang === u.lang) || vs.find((v) => v.lang.startsWith(u.lang.slice(0, 2)));
        if (pick) u.voice = pick;
        const num = (s) => parseInt(String(s || "0").replace(/[^\d-]/g, ""), 10) || 0;
        u.rate = Math.max(0.5, Math.min(2, 1 + num(this.cfg.rate) / 100));
        u.pitch = Math.max(0.1, Math.min(2, 1 + num(this.cfg.pitch) / 100));
        u.volume = Math.max(0, Math.min(1, 1 + num(this.cfg.volume) / 100));
        u.onboundary = () => avatar && avatar.pulseSyllable && avatar.pulseSyllable();
        u.onstart = () => { this.speaking = true; avatar && (avatar._externalMouth = true, avatar.setState("speaking")); };
        u.onend = u.onerror = () => {
          if (!chained) this.speaking = false;
          avatar && (avatar._externalMouth = false, !chained && avatar.setState("idle")); resolve();
        };
        if (!chained) { this._spoken = new Set(this._words(text)); speechSynthesis.cancel(); }
        speechSynthesis.speak(u);
      });
    }

    stopSpeaking() {
      this._gen++; this.speaking = false;
      try { this.audio.pause(); this.audio.removeAttribute("src"); } catch (_) {}
      if ("speechSynthesis" in window) speechSynthesis.cancel();
    }

    chime(freq = 660) {
      if (this.cfg.chime === false) return;
      try {
        const ac = window.__robinAC || (window.__robinAC = new (window.AudioContext || window.webkitAudioContext)());
        const o = ac.createOscillator(), g = ac.createGain(); o.frequency.value = freq; o.type = "sine";
        g.gain.setValueAtTime(0.0001, ac.currentTime); g.gain.exponentialRampToValueAtTime(0.08, ac.currentTime + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 0.18); o.connect(g); g.connect(ac.destination);
        o.start(); o.stop(ac.currentTime + 0.2);
      } catch (_) {}
    }
  }
  window.RobinVoice = RobinVoice;
})();
