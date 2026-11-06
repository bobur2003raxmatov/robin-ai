/* Bot Adminka — brauzer tomoni. Build yo'q, tashqi kutubxona yo'q. */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const API = "/bot-admin/api";
  const st = { after: 0, catalog: [], msgs: new Map(), timer: null, fast: 0, file: null, online: null, loaded: false };

  // ---------------------------------------------------------------- yordamchilar
  async function api(path, opts = {}) {
    const r = await fetch(API + path, { credentials: "same-origin", ...opts,
      headers: opts.body instanceof FormData ? {} : { "Content-Type": "application/json", ...(opts.headers || {}) } });
    let data = null;
    try { data = await r.json(); } catch { /* bo'sh javob */ }
    if (r.status === 401 && path !== "/login") { showLogin(); throw new Error("Kirish talab qilinadi"); }
    if (!r.ok) throw new Error((data && data.detail) || `Xato ${r.status}`);
    return data;
  }
  function toast(text, bad = false) {
    const t = document.createElement("div");
    t.className = "toast" + (bad ? " bad" : "");
    t.textContent = text;
    $("#toasts").append(t);
    setTimeout(() => t.remove(), bad ? 6000 : 3500);
  }
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const size = n => n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : n > 1024 ? Math.round(n / 1024) + " KB" : (n || 0) + " B";
  const hhmm = t => new Date((t || Date.now() / 1000) * 1000).toLocaleTimeString("uz-UZ", { hour: "2-digit", minute: "2-digit" });

  // Telegram HTML -> xavfsiz DOM (faqat ruxsat etilgan teglar)
  const ALLOWED = new Set(["B", "STRONG", "I", "EM", "U", "INS", "S", "STRIKE", "DEL", "CODE", "PRE", "A", "BLOCKQUOTE", "TG-SPOILER", "SPAN", "BR"]);
  function safeHtml(html) {
    const doc = new DOMParser().parseFromString(`<div>${html || ""}</div>`, "text/html");
    const walk = (node, out) => {
      for (const ch of node.childNodes) {
        if (ch.nodeType === 3) { out.append(ch.textContent); continue; }
        if (ch.nodeType !== 1) continue;
        if (!ALLOWED.has(ch.tagName)) { walk(ch, out); continue; }
        let el;
        if (ch.tagName === "TG-SPOILER" || (ch.tagName === "SPAN" && ch.classList.contains("tg-spoiler"))) {
          el = document.createElement("span"); el.className = "spoiler"; el.onclick = () => el.classList.toggle("show");
        } else if (ch.tagName === "SPAN") { walk(ch, out); continue; }
        else if (ch.tagName === "A") {
          el = document.createElement("a");
          const href = ch.getAttribute("href") || "";
          if (/^(https?:|tg:|mailto:)/i.test(href)) { el.href = href; el.target = "_blank"; el.rel = "noopener noreferrer"; }
        } else el = document.createElement(ch.tagName.toLowerCase());
        walk(ch, el);
        out.append(el);
      }
    };
    const frag = document.createDocumentFragment();
    walk(doc.body.firstChild, frag);
    return frag;
  }

  // ---------------------------------------------------------------- kirish / chiqish
  function showLogin(msg) {
    clearTimeout(st.timer);
    $("#app").hidden = true; $("#login").hidden = false;
    if (msg) $("#loginErr").textContent = msg;
    setTimeout(() => $("#loginForm [name=login]").focus(), 50);
  }
  function showApp() { $("#login").hidden = true; $("#app").hidden = false; $("#text").focus(); }

  $("#loginForm").addEventListener("submit", async e => {
    e.preventDefault();
    const f = new FormData(e.target), btn = $("button", e.target);
    btn.disabled = true; $("#loginErr").textContent = "";
    try {
      await api("/login", { method: "POST", body: JSON.stringify({ login: f.get("login"), password: f.get("password") }) });
      e.target.reset(); start();
    } catch (err) { $("#loginErr").textContent = err.message; }
    finally { btn.disabled = false; }
  });
  $("#logoutBtn").onclick = async () => { await api("/logout", { method: "POST" }).catch(() => {}); location.reload(); };

  // ---------------------------------------------------------------- mavzu
  const root = document.documentElement;
  try { const t = localStorage.getItem("ba_theme"); if (t) root.dataset.theme = t; } catch { /* yo'q */ }
  $("#themeBtn").onclick = () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : !matchMedia("(prefers-color-scheme: light)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("ba_theme", root.dataset.theme); } catch { /* yo'q */ }
  };

  // ---------------------------------------------------------------- buyruqlar katalogi
  function renderCatalog(filter = "") {
    const nav = $("#catalog"); nav.textContent = "";
    const q = filter.trim().toLowerCase().replace(/^\//, "");
    let total = 0, shown = 0;
    for (const sec of st.catalog) {
      const cmds = sec.cmds.filter(c => !q || c.c.includes(q) || (c.d + " " + c.h).toLowerCase().includes(q));
      total += sec.cmds.length;
      if (!cmds.length) continue;
      shown += cmds.length;
      const d = document.createElement("details");
      d.className = "sec"; d.open = !!q || st.catalog.length <= 3 || sec.open;
      d.innerHTML = `<summary>${esc(sec.title)} <span class="n">${cmds.length}</span></summary>`;
      d.addEventListener("toggle", () => { sec.open = d.open; });
      for (const c of cmds) {
        const b = document.createElement("button");
        b.type = "button"; b.className = "cmd";
        const ex = exampleOf(c);
        b.innerHTML = `<code>/${esc(c.c)}</code>${ex ? '<span class="arg" title="Parametr bilan ham ishlaydi">✎ parametr</span>' : ""}<span class="d">${esc(c.d)}</span>`;
        if (c.h) { const h = document.createElement("span"); h.className = "h"; h.append(safeHtml(c.h)); b.append(h); }
        b.onclick = ev => {
          closeSide();
          if (ex && (ev.altKey || ev.target.classList.contains("arg"))) { setText(ex + " "); return; }
          sendText("/" + c.c);
        };
        d.append(b);
      }
      nav.append(d);
    }
    $("#cmdCount").textContent = q ? `${shown} ta topildi` : `${total} ta buyruq · ✎ — parametr bilan`;
    if (!nav.childElementCount) nav.innerHTML = `<p class="muted" style="padding:12px">Hech narsa topilmadi</p>`;
  }
  function exampleOf(c) {
    const m = (c.h || "").match(new RegExp(`<code>(/${c.c}\\s[^<]*)</code>`));
    return m ? m[1].replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&").trim() : "";
  }
  function renderQuick() {
    const want = ["help", "holat", "hisobot", "elektriklar", "sovga_tanlaganlar", "statistika", "xodimlar"];
    const all = st.catalog.flatMap(s => s.cmds);
    const box = $("#quick"); box.textContent = "";
    for (const w of want) {
      const c = all.find(x => x.c === w); if (!c) continue;
      const b = document.createElement("button"); b.className = "chip"; b.type = "button";
      b.textContent = "/" + c.c; b.title = c.d; b.onclick = () => sendText("/" + c.c);
      box.append(b);
    }
  }
  $("#search").addEventListener("input", e => renderCatalog(e.target.value));
  document.addEventListener("keydown", e => {
    if (e.key === "/" && document.activeElement.tagName !== "TEXTAREA" && document.activeElement.tagName !== "INPUT") {
      e.preventDefault(); openSide(); $("#search").focus();
    }
    if (e.key === "Escape") closeSide();
  });

  // ---------------------------------------------------------------- yon panel (mobil)
  const openSide = () => $("#app").classList.add("side-open");
  const closeSide = () => $("#app").classList.remove("side-open");
  $("#sideOpen").onclick = openSide; $("#sideClose").onclick = closeSide; $("#scrim").onclick = closeSide;

  // ---------------------------------------------------------------- xabarlar
  const feed = $("#feed");
  const nearBottom = () => feed.scrollHeight - feed.scrollTop - feed.clientHeight < 160;
  const toBottom = () => requestAnimationFrame(() => { feed.scrollTop = feed.scrollHeight; });

  function fileCard(f) {
    const ext = (f.name.split(".").pop() || "").toLowerCase();
    const a = document.createElement("a");
    a.className = "file"; a.href = `${API}/file/${f.id}`; a.download = f.name;
    const cls = ext === "pdf" ? "pdf" : ["png", "jpg", "jpeg", "gif", "webp"].includes(ext) ? "img" : "";
    a.innerHTML = `<span class="ic ${cls}">${esc(ext.slice(0, 4).toUpperCase() || "FILE")}</span><span><span class="nm">${esc(f.name)}</span><br><span class="sz">${size(f.size)}</span></span><span class="dl">⤓</span>`;
    return a;
  }
  function keyboard(markup, mid) {
    const rows = markup && markup.inline_keyboard;
    if (!rows || !rows.length) return null;
    const kb = document.createElement("div"); kb.className = "kb";
    for (const row of rows) {
      const r = document.createElement("div"); r.className = "kb-row";
      for (const btn of row) {
        let el;
        const url = btn.url || (btn.web_app && btn.web_app.url) || (btn.login_url && btn.login_url.url);
        if (url) { el = document.createElement("a"); el.href = url; el.target = "_blank"; el.rel = "noopener noreferrer"; }
        else {
          el = document.createElement("button"); el.type = "button";
          if (btn.callback_data) el.onclick = () => pressButton(el, btn.callback_data, mid);
          else if (btn.copy_text) el.onclick = () => navigator.clipboard.writeText(btn.copy_text.text).then(() => toast("Nusxa olindi"));
          else el.disabled = true;
        }
        el.textContent = btn.text;
        r.append(el);
      }
      kb.append(r);
    }
    return kb;
  }
  function replyKeyboard(markup) {
    if (!markup) return;
    const box = $("#replyKb");
    if (markup.remove_keyboard) { box.hidden = true; box.textContent = ""; return; }
    if (!markup.keyboard) return;
    box.textContent = "";
    for (const row of markup.keyboard) for (const btn of row) {
      const t = typeof btn === "string" ? btn : btn.text;
      if (btn.request_contact || btn.request_location) continue;      // brauzerda ma'nosiz
      const b = document.createElement("button"); b.className = "chip"; b.type = "button"; b.textContent = t;
      b.onclick = () => { sendText(t); if (markup.one_time_keyboard) box.hidden = true; };
      box.append(b);
    }
    box.hidden = !box.childElementCount;
  }
  function fillBubble(bubble, ev) {
    bubble.textContent = "";
    if (ev.html) bubble.append(safeHtml(ev.html));
    if (ev.file) {
      const ext = (ev.file.name.split(".").pop() || "").toLowerCase();
      if (["png", "jpg", "jpeg", "gif", "webp"].includes(ext)) {
        const img = document.createElement("img"); img.className = "photo"; img.loading = "lazy";
        img.src = `${API}/file/${ev.file.id}`; img.alt = ev.file.name; bubble.append(img);
      }
      bubble.append(fileCard(ev.file));
    }
    if (ev.url) { const img = document.createElement("img"); img.className = "photo"; img.src = ev.url; img.alt = ""; bubble.append(img); }
    if (!ev.html && !ev.file && !ev.url) bubble.append(safeHtml("<i>(bo'sh xabar)</i>"));
  }
  function addMsg(ev) {
    $("#empty").hidden = true;
    const stick = nearBottom() || ev.type === "out";
    const m = document.createElement("div");
    const bubble = document.createElement("div"); bubble.className = "bubble";
    const meta = document.createElement("div"); meta.className = "meta";
    if (ev.type === "out") {
      m.className = "msg out";
      if (ev.text) bubble.textContent = ev.text;
      if (ev.file) bubble.append(fileCard(ev.file));
      meta.textContent = "Siz · " + hhmm(ev.t);
      m.append(bubble, meta);
    } else {
      m.className = "msg in";
      fillBubble(bubble, ev);
      meta.textContent = "Bot · " + hhmm(ev.t);
      m.append(bubble);
      const kb = keyboard(ev.markup, ev.mid); if (kb) m.append(kb);
      m.append(meta);
      if (ev.mid) st.msgs.set(ev.mid, m);
      replyKeyboard(ev.markup);
    }
    feed.append(m);
    if (stick) toBottom();
  }
  function editMsg(ev) {
    const m = st.msgs.get(ev.mid);
    if (!m) return;
    const bubble = $(".bubble", m);
    if (ev.html !== undefined && ev.html !== null) { fillBubble(bubble, ev); bubble.classList.add("edited"); }
    if (ev.markup !== undefined) {
      const old = $(".kb", m); if (old) old.remove();
      const kb = keyboard(ev.markup, ev.mid); if (kb) m.insertBefore(kb, $(".meta", m));
    }
  }
  function handle(ev) {
    switch (ev.type) {
      case "out": case "message": addMsg(ev); break;
      case "edit": editMsg(ev); break;
      case "delete": { const m = st.msgs.get(ev.mid); if (m) { m.remove(); st.msgs.delete(ev.mid); } break; }
      case "toast": if (st.loaded && ev.text) toast(ev.text, !!ev.alert); break;
      case "status": { const s = document.createElement("div"); s.className = "sysline"; s.textContent = ev.text; feed.append(s); break; }
    }
  }

  // ---------------------------------------------------------------- yuborish
  function setText(t) { const ta = $("#text"); ta.value = t; ta.focus(); autosize(); }
  async function sendText(text) {
    text = (text || "").trim();
    if (!text) return;
    try { await api("/send", { method: "POST", body: JSON.stringify({ text }) }); fastPoll(); }
    catch (e) { toast(e.message, true); }
  }
  async function pressButton(el, data, mid) {
    el.classList.add("busy");
    try { await api("/send", { method: "POST", body: JSON.stringify({ callback: data, mid }) }); fastPoll(); }
    catch (e) { toast(e.message, true); }
    finally { setTimeout(() => el.classList.remove("busy"), 1200); }
  }
  async function sendFile(file, caption) {
    if (file.size > 20 * 1024 * 1024) { toast("Fayl 20 MB dan katta", true); return; }
    const fd = new FormData(); fd.append("file", file); fd.append("caption", caption || "");
    try { await api("/upload", { method: "POST", body: fd }); fastPoll(); }
    catch (e) { toast(e.message, true); }
  }
  function setFile(f) {
    st.file = f || null;
    $("#attach").hidden = !f;
    if (f) { $("#attachName").textContent = `📄 ${f.name} · ${size(f.size)} — izohga buyruq yozing (masalan /dusel)`; $("#text").focus(); }
  }
  $("#fileIn").onchange = e => { setFile(e.target.files[0]); e.target.value = ""; };
  $("#attachDel").onclick = () => setFile(null);
  $("#composer").addEventListener("submit", e => {
    e.preventDefault();
    const ta = $("#text"), text = ta.value;
    if (st.file) { sendFile(st.file, text.trim()); setFile(null); }
    else sendText(text);
    ta.value = ""; autosize();
  });
  const autosize = () => { const ta = $("#text"); ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 180) + "px"; };
  $("#text").addEventListener("input", autosize);
  $("#text").addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); }
  });
  // sudrab tashlash
  let dragN = 0;
  addEventListener("dragenter", e => { if (e.dataTransfer.types.includes("Files") && !$("#app").hidden) { dragN++; $("#drop").hidden = false; } });
  addEventListener("dragleave", () => { if (--dragN <= 0) { dragN = 0; $("#drop").hidden = true; } });
  addEventListener("dragover", e => e.preventDefault());
  addEventListener("drop", e => { e.preventDefault(); dragN = 0; $("#drop").hidden = true; if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); });

  $("#clearBtn").onclick = async () => {
    if (!confirm("Oynadagi barcha xabarlar o'chirilsinmi? (Botdagi ma'lumotlarga ta'sir qilmaydi)")) return;
    await api("/clear", { method: "POST" }).catch(e => toast(e.message, true));
    [...feed.querySelectorAll(".msg, .sysline")].forEach(x => x.remove());
    st.msgs.clear(); $("#empty").hidden = false;
  };

  // ---------------------------------------------------------------- holat (polling)
  function setStatus(s) {
    const el = $("#status");
    const on = s.online;
    el.className = "pill " + (on ? "pill-on" : "pill-off");
    $("span", el).textContent = on ? "Noutbuk ulangan" : "Noutbuk oflayn" + (s.last_seen ? " · " + new Date(s.last_seen * 1000).toLocaleString("uz-UZ", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "");
    el.title = on ? "Buyruqlar darhol bajariladi" : "Noutbuk yoqilganda navbatdagi buyruqlar bajariladi";
    const p = $("#pending");
    p.hidden = !s.pending; p.textContent = `⏳ navbatda: ${s.pending}`;
    if (st.online !== null && st.online !== on) toast(on ? "✅ Noutbuk ulandi" : "⚠️ Noutbuk bilan aloqa uzildi", !on);
    st.online = on;
    if (s.bot && s.bot.username) { $("#botUser").textContent = "@" + s.bot.username; $("#loginBot").textContent = "@" + s.bot.username; }
    if (s.bot && s.bot.name) $("#botName").textContent = s.bot.name;
  }
  async function poll(withCatalog = false) {
    clearTimeout(st.timer);
    try {
      const s = await api(`/state?after=${st.after}${withCatalog ? "&catalog=1" : ""}`);
      if (s.catalog) { st.catalog = s.catalog; renderCatalog($("#search").value); renderQuick(); }
      if (s.last_id < st.after) {            // tozalangan (boshqa oynada)
        st.after = 0; [...feed.querySelectorAll(".msg, .sysline")].forEach(x => x.remove()); st.msgs.clear(); $("#empty").hidden = false;
      }
      for (const ev of s.events) { handle(ev); st.after = Math.max(st.after, ev.id); }
      if (!st.loaded) { st.loaded = true; toBottom(); }
      setStatus(s);
    } catch (e) {
      if ($("#app").hidden) return;
    }
    const delay = st.fast > Date.now() ? 900 : document.hidden ? 8000 : 2500;
    st.timer = setTimeout(() => poll(Math.random() < 0.05), delay);
  }
  function fastPoll() { st.fast = Date.now() + 90_000; poll(); }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !$("#app").hidden) poll(); });

  async function start() {
    try { await api(`/state?after=999999999`); }
    catch (e) { if (!$("#login").hidden || /Kirish/.test(e.message)) return; showLogin(e.message); return; }
    showApp(); st.after = 0; st.loaded = false; poll(true);
  }
  start();
})();
