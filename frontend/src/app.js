/* ROBIN Dashboard — SPA (vanilla JS). Pages: Home, Chat, Autopilot, Brain, Memory, Agents, Automation, Files,
   Voice, Avatar, Trading, Settings. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Server times are UTC; SQLite returns them without a zone ("2026-11-05T06:37:00") → treat as UTC, not local.
const parseDate = (s) => new Date(typeof s === "string" && /T\d\d:\d\d(:\d\d(\.\d+)?)?$/.test(s) ? s + "Z" : s);
const fmtDate = (s) => s ? parseDate(s).toLocaleString() : "—";
const S = { token: localStorage.getItem("robin_token") || "", user: null, settings: null, conv: null, ws: null, avatar: null, voice: null, unread: 0 };

/* ---------------- markdown (safe, minimal) ---------------- */
function mdInline(s) {
  return s.replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|[^*\w])\*([^*\n]+)\*/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function md(text) {
  // Line-based renderer: code blocks, headings, lists, tables, paragraphs. Input is escaped first (XSS-safe).
  const lines = esc(text || "").split("\n"); const out = []; let i = 0;
  const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => mdInline(c.trim()));
  while (i < lines.length) {
    const l = lines[i];
    if (/^```/.test(l)) { const buf = []; i++; while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]); i++; out.push(`<pre><code>${buf.join("\n")}</code></pre>`); continue; }
    const h = l.match(/^(#{1,3}) (.*)$/); if (h) { out.push(`<h${h[1].length}>${mdInline(h[2])}</h${h[1].length}>`); i++; continue; }
    if (/^\s*\|.*\|\s*$/.test(l)) {
      const rows = []; while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      const hasHead = rows.length > 1 && /^[\s|:\-]+$/.test(rows[1]);
      if (hasHead) rows.splice(1, 1);  // drop the |---|---| separator
      out.push('<div class="table-wrap"><table>' + rows.map((r, k) => `<tr>${cells(r).map((c) => hasHead && k === 0 ? `<th>${c}</th>` : `<td>${c}</td>`).join("")}</tr>`).join("") + "</table></div>");
      continue;
    }
    if (/^\s*([-*•]|\d+[.)]) /.test(l)) {
      const ordered = /^\s*\d+[.)] /.test(l); const items = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)]) /.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*•]|\d+[.)]) /, ""));
      out.push(`<${ordered ? "ol" : "ul"}>${items.map((x) => `<li>${mdInline(x)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`); continue;
    }
    if (!l.trim()) { i++; continue; }
    const para = []; while (i < lines.length && lines[i].trim() && !/^(```|#{1,3} |\s*\||\s*([-*•]|\d+[.)]) )/.test(lines[i])) para.push(mdInline(lines[i++]));
    out.push(`<p>${para.join("<br>")}</p>`);
  }
  return '<div class="md">' + out.join("") + "</div>";
}

/* ---------------- API ---------------- */
async function api(path, opts = {}) {
  const o = { method: opts.method || (opts.body ? "POST" : "GET"), headers: { Authorization: "Bearer " + S.token } };
  if (opts.body instanceof FormData) o.body = opts.body;
  else if (opts.body !== undefined) { o.body = JSON.stringify(opts.body); o.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, o);
  if (r.status === 401) { logout(); throw new Error("Login talab qilinadi"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail ? (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)) : r.statusText);
  return j;
}
function toast(title, body = "", level = "info") {
  const d = document.createElement("div"); d.className = "toast " + level;
  d.innerHTML = `<b>${esc(title)}</b>${body ? `<div class="small muted">${esc(body).slice(0, 400)}</div>` : ""}`;
  $("#toasts").appendChild(d); setTimeout(() => d.remove(), 7000);
}
const guard = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast("Xato", e.message, "error"); } };

/* ---------------- Auth ---------------- */
let authMode = "login";
$$("#login .tabs button").forEach((b) => b.onclick = () => {
  authMode = b.dataset.mode; $$("#login .tabs button").forEach((x) => x.classList.toggle("active", x === b));
  $("#regFields").style.display = authMode === "register" ? "" : "none";
});
$("#authForm").onsubmit = async (e) => {
  e.preventDefault(); const f = new FormData(e.target);
  try {
    const r = await fetch("/api/auth/" + authMode, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.fromEntries(f)) });
    const j = await r.json(); if (!r.ok) throw new Error(j.detail || "Xato");
    S.token = j.token; localStorage.setItem("robin_token", j.token); boot();
  } catch (err) { $("#authErr").textContent = err.message; }
};
fetch("/api/auth/config").then((r) => r.json()).then((c) => { if (!c.registration_open) { const b = $('#login .tabs button[data-mode="register"]'); if (b) b.style.display = "none"; } }).catch(() => {});
function logout() { localStorage.removeItem("robin_token"); S.token = ""; location.hash = ""; location.reload(); }
$("#logout").onclick = (e) => { e.preventDefault(); logout(); };

/* ---------------- Navigation ---------------- */
const PAGES = [
  ["home", "🏠", "Home"], ["chat", "💬", "Chat"], ["autopilot", "🚀", "Autopilot"], ["brain", "🧠", "Brain"],
  ["memory", "🗂️", "Memory"], ["agents", "🤝", "Agents"], ["automation", "⚙️", "Automation"], ["files", "📁", "Files"], ["notes", "📝", "Notes"],
  ["voice", "🎙️", "Voice"], ["avatar", "🤖", "Avatar"], ["trading", "📈", "Trading"], ["settings", "🛠️", "Settings"], ["download", "⬇️", "Download App"],
];
// page → service that must be enabled for this user (admin policy)
const PAGE_SERVICE = { chat: "chat", autopilot: "autopilot", memory: "memory", files: "memory", automation: "commands", notes: "notes", voice: "voice", trading: "trading", download: "devices" };
const svcOn = (sid) => !S.settings || !S.settings.policy || S.settings.policy.services[sid] !== false;
function visiblePages() {
  const list = PAGES.filter(([id]) => !PAGE_SERVICE[id] || svcOn(PAGE_SERVICE[id]));
  if (S.user && S.user.is_admin) list.splice(list.length - 1, 0, ["admin", "👑", "Admin"]);
  return list;
}
function renderNav() { $("#nav").innerHTML = visiblePages().map(([id, ic, t]) => `<a href="#${id}" data-p="${id}"><span class="ic">${ic}</span>${t}</a>`).join(""); }
renderNav();
$("#menuBtn").onclick = () => $("#side").classList.toggle("open");
window.addEventListener("hashchange", route);
function route() {
  const p = (location.hash || "#home").slice(1).split("/")[0];
  const pages = visiblePages(); const page = pages.find((x) => x[0] === p) || pages[0];
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.p === page[0]));
  $("#pageTitle").textContent = page[2]; $("#side").classList.remove("open");
  if (S.avatar && S.avatar.destroy) S.avatar.destroy();
  S.avatar = null;
  if (S.voice && S.voice.listening) S.voice.stop();
  const view = $("#view");
  view.classList.remove("page-in"); void view.offsetWidth; view.classList.add("page-in");
  Promise.resolve().then(() => (VIEWS[page[0]] || VIEWS.home)(view)).catch((e) => {
    console.error(e);
    view.insertAdjacentHTML("afterbegin", `<div class="card" style="border-color:var(--err)"><b>⚠️ Sahifani yuklashda xato</b><div class="small muted">${esc(e.message)}</div><button class="small" onclick="location.reload()">Qayta yuklash</button></div>`);
  });
}

/* ---------------- Boot ---------------- */
async function boot() {
  if (!S.token) { $("#login").style.display = ""; return; }
  try { S.user = await api("/api/auth/me"); } catch { return; }
  $("#login").style.display = "none"; $("#app").classList.add("on");
  if (!S.user.is_admin && !/[?&]full=1/.test(location.search)) {   // mijozlar uchun alohida panel
    const cp = await api("/api/client/panel").catch(() => null);
    if (cp && cp.panel.enabled && cp.panel.default_for_users) { location.replace("/panel"); return; }
  }
  $("#whoami").textContent = `${S.user.full_name || S.user.username}${S.user.is_admin ? " · admin" : ""}`;
  refreshClaudeIcon();
  S.settings = await api("/api/settings");
  S.voice = new RobinVoice({ getToken: () => S.token, onFinal: (t) => voiceInput(t), onInterim: (t) => { const i = $("#interim"); if (i) i.textContent = t; }, onState: (st) => { S.avatar && S.avatar.setState(st); $$(".mic").forEach((m) => m.classList.toggle("on", st === "listening" || (S.voice && S.voice.live))); } });
  S.voice.lang = { uz: "uz-UZ", ru: "ru-RU", en: "en-US" }[S.user.language] || "uz-UZ";
  S.voice.configure(S.settings.voice);
  renderNav();
  connectWS(); refreshBell(); refreshDevices(); setInterval(refreshDevices, 20000);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  route();
}
function connectWS() {
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws?token=" + S.token);
  S.ws = ws;
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === "notification") { toast(m.title, m.body, m.level); S.unread++; updateBell(); if (document.hidden && Notification.permission === "granted") new Notification(m.title, { body: m.body }); }
    if (m.type === "avatar" && S.avatar) S.avatar.setState(m.state);
    if (m.type === "approval_request") showApproval(m);
    if (m.type === "task_update" && location.hash.startsWith("#autopilot")) VIEWS.autopilot($("#view"), true);
    if (m.type === "notes_changed" && location.hash.startsWith("#notes") && S.reloadNotes) S.reloadNotes();
    if (m.type === "policy_changed" || (m.type === "settings_changed" && m.key === "voice")) reloadSettings(m.type === "policy_changed");
    if (m.type === "agent_step") { const el = $("#liveStep"); if (el) el.textContent = `⚙️ ${m.tool} — ${m.status}`; }
  };
  ws.onclose = () => setTimeout(connectWS, 3000);
  setInterval(() => ws.readyState === 1 && ws.send(JSON.stringify({ type: "ping" })), 25000);
}
async function reloadSettings(policy = false) {
  try {
    S.settings = await api("/api/settings"); S.voice && S.voice.configure(S.settings.voice); renderNav();
    if (policy) { toast("Ruxsatlaringiz yangilandi", "Administrator xizmatlar ro'yxatini o'zgartirdi"); route(); }
  } catch {}
}
async function refreshDevices() {
  if (!svcOn("devices")) { $("#devStatus").style.display = "none"; return; }
  try { const d = await api("/api/devices"); const on = d.filter((x) => x.online);
    $("#devStatus").textContent = on.length ? `💻 ${on.map((x) => x.name).join(", ")}` : "💻 lokal"; $("#devStatus").className = "badge " + (on.length ? "ok" : "info"); } catch {}
}
async function refreshBell() { try { const n = await api("/api/notifications"); S.unread = n.unread; updateBell(); } catch {} }
function updateBell() { $("#bellN").style.display = S.unread ? "" : "none"; $("#bellN").textContent = S.unread; }
$("#bellBtn").onclick = guard(async () => {
  const n = await api("/api/notifications"); await api("/api/notifications/read", { body: {} }); S.unread = 0; updateBell();
  modal(`<h2>Bildirishnomalar</h2>${n.items.map((i) => `<div class="list-item"><span class="badge ${i.level === "error" ? "err" : i.level === "success" ? "ok" : i.level === "warning" ? "warn" : "info"}">${i.level}</span> <b>${esc(i.title)}</b><div class="small muted">${esc(i.body).slice(0, 500)}</div><div class="small muted">${fmtDate(i.created_at)}</div></div>`).join("") || "<p class='muted'>Bo'sh</p>"}`);
  if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
});
let stopped = false;
$("#stopBtn").onclick = guard(async () => {
  if (!stopped) { const r = await api("/api/emergency/stop", { body: {} }); stopped = true; toast("⛔ STOP", `${r.cancelled_tasks} vazifa to'xtatildi. Qayta bosing — davom ettirish.`, "error"); }
  else { await api("/api/emergency/resume", { body: {} }); stopped = false; toast("▶️ ROBIN davom etmoqda"); }
  $("#stopBtn").classList.toggle("active", stopped); $("#stopBtn").textContent = stopped ? "▶️ RESUME" : "⛔ STOP";
});
function modal(html, onMount) {
  const bg = document.createElement("div"); bg.className = "modal-bg";
  bg.innerHTML = `<div class="card modal" style="max-height:88vh;overflow:auto">${html}<div class="row" style="justify-content:flex-end;margin-top:14px"><button class="ghost" data-close>Yopish</button></div></div>`;
  bg.onclick = (e) => { if (e.target === bg || e.target.dataset.close !== undefined) bg.remove(); };
  document.body.appendChild(bg); onMount && onMount(bg); return bg;
}
function showApproval(a) {
  const bg = modal(`<h2>⚠️ Tasdiq kerak</h2><p>ROBIN quyidagi amalni bajarmoqchi:</p><p><b>${esc(a.tool)}</b> <span class="badge ${a.risk === "critical" ? "err" : "warn"}">${esc(a.risk)}</span></p><pre>${esc(JSON.stringify(a.args, null, 2))}</pre><p class="small muted">${esc(a.reason || "")}</p>
    <div class="row"><button class="ok" id="apYes">✅ Tasdiqlash</button><button class="danger" id="apNo">❌ Rad etish</button></div>`);
  $("#apYes", bg).onclick = guard(async () => { await api("/api/approvals/" + a.id, { body: { approved: true } }); bg.remove(); });
  $("#apNo", bg).onclick = guard(async () => { await api("/api/approvals/" + a.id, { body: { approved: false } }); bg.remove(); });
}
function mountAvatar(el, compact = false) {
  const av = S.settings?.avatar || {};
  S.avatar = new RobinAvatar(el, { color: av.color, accent: av.accent, eyeTracking: av.eye_tracking !== false, compact });
  return S.avatar;
}

/* ---------------- Voice input (global) ---------------- */
async function voiceInput(text) {
  if (!text) return;
  if (location.hash.startsWith("#chat")) { sendChat(text, true); return; }
  S.avatar && S.avatar.setState("thinking");
  const r = await api("/api/chat", { body: { text, conversation_id: S.conv, voice: true } });
  S.conv = r.conversation_id; const o = $("#homeReply"); if (o) o.innerHTML = `<b>Siz:</b> ${esc(text)}<br><b>ROBIN:</b> ${md(r.reply)}`;
  S.voice.speak(r.reply, S.avatar, S.settings.voice.tts_engine);
}

/* =================================================================== VIEWS */
const VIEWS = {};

VIEWS.home = async (v) => {
  v.innerHTML = `<div class="grid2">
    <div class="card"><div class="avatar-box" id="av"></div>
      <div class="row" style="justify-content:center"><button class="mic primary" id="homeMic" title="Gapiring">🎙️</button>
      <input id="homeInput" class="grow" placeholder="ROBIN'ga buyruq bering… masalan: Ertaga soat 10:00 ga uchrashuv belgilab qo'y"><button class="primary" id="homeSend">Yuborish</button></div>
      <div id="interim" class="small muted" style="margin-top:6px;text-align:center"></div>
      <div id="homeReply" style="margin-top:10px"></div></div>
    <div class="grid" id="homeStats" style="align-content:start"></div></div>
    <div class="card" style="margin-top:14px"><h2>Tezkor buyruqlar</h2><div class="row" id="quick"></div></div>`;
  mountAvatar($("#av"));
  const send = guard(async () => { const t = $("#homeInput").value.trim(); if (!t) return; $("#homeInput").value = ""; await voiceInput(t); });
  $("#homeSend").onclick = send; $("#homeInput").onkeydown = (e) => e.key === "Enter" && send();
  $("#homeMic").onclick = () => { if (S.voice.listening) { S.voice.stop(); $("#homeMic").classList.remove("on"); } else { S.voice.start(false); $("#homeMic").classList.add("on"); } };
  const quick = ["Kompyuter holatini ko'rsat", "Bugungi rejamni ayt", "Desktop papkamdagi fayllarni saralab ber", "BTCUSDT ni tahlil qil", "Ekranda nima ochiq?"];
  $("#quick").innerHTML = quick.map((q) => `<button class="ghost small">${esc(q)}</button>`).join("");
  $$("#quick button").forEach((b) => b.onclick = () => { $("#homeInput").value = b.textContent; send(); });
  const [ap, rem, br, res] = await Promise.all([svcOn("autopilot") ? api("/api/autopilot") : Promise.resolve(null), svcOn("reminders") ? api("/api/reminders") : Promise.resolve(null), api("/api/brain/status"), api("/api/system/resources")].map((p) => p.catch(() => null)));
  if (!$("#homeStats")) return;   // user left the page while data was loading
  const conn = br ? Object.values(br.providers).filter((x) => x.connected) : [];
  const prov = conn.length ? conn.map((x) => `<span class="badge ok">${esc(x.title)}</span>`).join(" ") : '<span class="badge err">AI ulanmagan</span>';
  $("#homeStats").innerHTML = `
    <div class="card"><div class="muted small">Faol vazifalar</div><div class="stat">${ap ? ap.active.length : 0}</div><div class="small muted">Navbatda: ${ap ? ap.queue.length : 0}</div></div>
    <div class="card"><div class="muted small">Tasdiq kutmoqda</div><div class="stat">${ap ? ap.approvals.length : 0}</div><a href="#autopilot" class="small">Approval Center →</a></div>
    <div class="card"><div class="muted small">Eslatma va uchrashuvlar</div><div class="stat">${rem ? rem.length : 0}</div>${(rem || []).slice(0, 3).map((r) => `<div class="small">${r.kind === "meeting" ? "📅" : "⏰"} ${esc(r.title)} — ${fmtDate(r.due_at)}</div>`).join("")}</div>
    <div class="card"><div class="muted small">AI miya</div><div style="margin:8px 0">${prov}</div><a href="#brain" class="small">Sozlash →</a></div>
    <div class="card"><div class="muted small">Resurslar</div>${res ? `<div class="small">CPU ${res.cpu}%</div><div class="bar"><i style="width:${res.cpu}%"></i></div><div class="small" style="margin-top:6px">RAM ${res.ram}%</div><div class="bar"><i style="width:${res.ram}%"></i></div>` : ""}</div>`;
};

/* ---------------- CHAT ---------------- */
VIEWS.chat = async (v) => {
  v.innerHTML = `<div class="chat-layout">
    <div class="card chat-side" style="overflow:auto"><div class="row"><b class="grow">Suhbatlar</b><button class="small primary" id="newConv">+ Yangi</button></div>
      <input id="convSearch" placeholder="Qidirish…" style="margin:8px 0"><div id="convList"></div></div>
    <div class="card chat-main"><div class="msgs" id="msgs"></div>
      <div class="small muted" id="liveStep" style="padding:0 16px"></div><div class="small muted" id="interim" style="padding:0 16px"></div>
      <div class="composer">
        <button class="mic" id="micBtn" title="Ovozli buyruq">🎙️</button>
        <label class="mic ghost" style="display:grid;place-items:center;margin:0;cursor:pointer" title="Rasm (Live Vision)">🖼️<input type="file" id="imgIn" accept="image/*" capture="environment" hidden></label>
        <textarea id="chatIn" placeholder="Yozing… (Enter — yuborish, Shift+Enter — yangi qator)"></textarea>
        <button class="primary" id="sendBtn">➤</button></div></div>
    <div class="card chat-avatar"><div class="avatar-box sm" id="av"></div>
      <label class="row small"><input type="checkbox" id="liveMode" style="width:auto"> Live suhbat (to'xtovsiz tinglash)</label>
      <label class="row small"><input type="checkbox" id="speakMode" style="width:auto" ${S.settings.voice.auto_speak ? "checked" : ""}> Yozma javoblarni ham ovozda o'qish</label>
      <label class="row small"><input type="checkbox" id="screenShare" style="width:auto"> Ekranni ulashish (Live Vision)</label></div></div>`;
  mountAvatar($("#av"), true);
  const loadConvs = S.loadConvs = async (q = "") => {
    const cs = await api("/api/chat/conversations?q=" + encodeURIComponent(q));
    $("#convList").innerHTML = cs.map((c) => `<div class="conv-item ${c.id === S.conv ? "active" : ""}" data-id="${c.id}">${esc(c.title)}<div class="small muted">${c.project ? "📁 " + esc(c.project) + " · " : ""}${fmtDate(c.updated_at)}</div></div>`).join("") || "<p class='small muted'>Hali suhbat yo'q</p>";
    $$(".conv-item").forEach((el) => el.onclick = () => { S.conv = el.dataset.id; loadMsgs(); loadConvs(); });
  };
  const loadMsgs = async () => {
    $("#msgs").innerHTML = "";
    if (!S.conv) { addMsg("assistant", `Salom${S.user.full_name ? ", " + S.user.full_name : ""}! Men ROBIN 🤖 — nima qilamiz? Kompyuteringizni boshqaraman, fayllar, Excel, internet, eslatmalar, trading… shunchaki ayting.`); return; }
    const c = await api("/api/chat/conversations/" + S.conv); c.messages.forEach((m) => addMsg(m.role, m.content, m));
  };
  $("#newConv").onclick = () => { S.conv = null; loadMsgs(); loadConvs(); };
  $("#convSearch").oninput = (e) => loadConvs(e.target.value);
  $("#sendBtn").onclick = () => sendChat();
  $("#chatIn").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } };
  $("#micBtn").onclick = () => { if (S.voice.listening) { S.voice.stop(); $("#micBtn").classList.remove("on"); } else { S.voice.start($("#liveMode").checked); $("#micBtn").classList.add("on"); } };
  $("#imgIn").onchange = (e) => { const f = e.target.files[0]; if (!f) return; const r = new FileReader(); r.onload = () => { S.pendingImage = { data: r.result, type: f.type }; toast("Rasm biriktirildi", "Savolingizni yozing va yuboring"); }; r.readAsDataURL(f); };
  $("#screenShare").onchange = guard(async (e) => {
    if (!e.target.checked) { S.screenStream && S.screenStream.getTracks().forEach((t) => t.stop()); S.screenStream = null; return; }
    S.screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true }); toast("Ekran ulashildi", "Har bir xabar bilan ekran kadri yuboriladi");
  });
  loadConvs(); loadMsgs();
};
function addMsg(role, content, m = {}) {
  const box = $("#msgs"); if (!box) return;
  const d = document.createElement("div"); d.className = "msg " + (role === "user" ? "user" : "assistant");
  const meta = m.meta || {};
  const steps = (meta.steps || []).length ? `<details class="steps"><summary>⚙️ ${meta.steps.length} ta amal${meta.agent ? " · " + esc(meta.agent) : ""}${meta.provider ? " · " + esc(meta.provider) : ""}</summary>${meta.steps.map((s) => `<div>• <b>${esc(s.tool)}</b> <code>${esc(JSON.stringify(s.args)).slice(0, 160)}</code></div>`).join("")}</details>` : "";
  d.innerHTML = (role === "user" ? esc(content) : md(content)) + steps +
    (role !== "user" && m.id ? `<div class="meta"><button data-r="1" title="Yaxshi">👍</button><button data-r="-1" title="Yomon">👎</button><button data-fix title="Tuzatish (Self-Learning)">✏️ Tuzatish</button><button data-say title="O'qib berish">🔊</button></div>` : "");
  $$("[data-r]", d).forEach((b) => b.onclick = guard(async () => { await api("/api/chat/feedback", { body: { message_id: m.id, rating: +b.dataset.r } }); toast("Rahmat! Fikringiz saqlandi"); }));
  const fix = $("[data-fix]", d); fix && (fix.onclick = () => {
    const bg = modal(`<h2>ROBIN'ni o'rgatish</h2><p class="small muted">Qanday javob kerak edi? ROBIN bundan qoida chiqarib, keyingi safar shunday ishlaydi.</p><textarea id="fbText" placeholder="Masalan: hisobotlarni doim jadval ko'rinishida ber"></textarea>${S.user.is_admin ? `<label class="row small"><input type="checkbox" id="fbApply" style="width:auto"> Sozlamalarni ham avtomatik moslashtirsin (admin)</label>` : ""}<button class="primary" id="fbSend">Saqlash</button>`);
    $("#fbSend", bg).onclick = guard(async () => { const r = await api("/api/chat/feedback", { body: { message_id: m.id, rating: -1, text: $("#fbText", bg).value, apply_settings: !!($("#fbApply", bg) || {}).checked } }); bg.remove(); toast("O'rgandim ✅", r.lesson); });
  });
  const say = $("[data-say]", d); say && (say.onclick = () => S.voice.speak(content, S.avatar, S.settings.voice.tts_engine));
  box.appendChild(d); box.scrollTop = box.scrollHeight;
}
async function grabScreenFrame() {
  if (!S.screenStream) return null;
  const video = document.createElement("video"); video.srcObject = S.screenStream; await video.play();
  const c = document.createElement("canvas"); const sc = Math.min(1, 1366 / video.videoWidth);
  c.width = video.videoWidth * sc; c.height = video.videoHeight * sc; c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
  video.pause(); return { data: c.toDataURL("image/jpeg", 0.8), type: "image/jpeg" };
}
const sendChat = guard(async (preset, viaVoice = false) => {
  const ta = $("#chatIn"); const text = (preset ?? ta.value).trim(); if (!text && !S.pendingImage) return;
  if (ta) ta.value = ""; $("#interim") && ($("#interim").textContent = "");
  addMsg("user", text + (S.pendingImage ? " 🖼️" : ""));
  const img = S.pendingImage || await grabScreenFrame(); S.pendingImage = null;
  S.avatar && S.avatar.setState("thinking");
  const wait = document.createElement("div"); wait.className = "msg assistant pending"; wait.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>'; $("#msgs").appendChild(wait);
  try {
    const r = await api("/api/chat", { body: { text, conversation_id: S.conv, voice: viaVoice, image_b64: img ? img.data : null, image_type: img ? img.type : "image/png" } });
    wait.remove(); S.conv = r.conversation_id; addMsg("assistant", r.reply, { id: r.message_id, meta: r.meta });
    if (S.loadConvs && $("#convList")) S.loadConvs().catch(() => {});
    // Voice questions get spoken answers; typed ones only when "read answers aloud" is ticked.
    if (viaVoice || ($("#speakMode") && $("#speakMode").checked)) svcOn("voice") && S.voice.speak(r.reply, S.avatar, S.settings.voice.tts_engine);
    else S.avatar && S.avatar.setState("idle");
    $("#liveStep") && ($("#liveStep").textContent = "");
  } catch (e) { wait.remove(); throw e; }
});

/* ---------------- AUTOPILOT ---------------- */
VIEWS.autopilot = async (v, refresh = false) => {
  if (!refresh) v.innerHTML = `<div class="card"><h2>🚀 Yangi vazifa (ROBIN Autopilot)</h2><div class="row"><textarea id="goal" class="grow" placeholder="Masalan: Desktop'dagi savdo.xlsx faylini tahlil qil, xatolarni top va hisobot tayyorla"></textarea></div>
    <div class="row" style="margin-top:8px"><select id="goalAgent" style="width:auto"></select><select id="goalPrio" style="width:auto"><option value="3">Yuqori</option><option value="5" selected>O'rta</option><option value="8">Past</option></select><button class="primary" id="goalBtn">Navbatga qo'shish</button></div></div><div id="apBody"></div>`;
  if (!refresh) {
    const ags = await api("/api/agents"); $("#goalAgent").innerHTML = ags.map((a) => `<option value="${a.id}">${esc(a.title)}</option>`).join("");
    $("#goalBtn").onclick = guard(async () => { const g = $("#goal").value.trim(); if (!g) return; await api("/api/tasks", { body: { goal: g, agent: $("#goalAgent").value, priority: +$("#goalPrio").value } }); $("#goal").value = ""; toast("Vazifa navbatga qo'shildi"); VIEWS.autopilot(v, true); });
  }
  const [d, res, act] = await Promise.all([api("/api/autopilot"), api("/api/system/resources"), api("/api/system/activity?limit=40")]);
  const taskCard = (t) => `<div class="list-item"><div class="row"><b class="grow">${esc(t.title)}</b><span class="badge ${t.status === "done" ? "ok" : t.status === "failed" ? "err" : t.status === "running" ? "info" : ""}">${t.status}</span>
      ${["queued", "running", "waiting"].includes(t.status) ? `<button class="small danger" data-cancel="${t.id}">Bekor</button>` : ""}<button class="small ghost" data-open="${t.id}">Batafsil</button></div>
      <div>${(t.plan || []).map((s) => `<span class="step-chip">${s.status === "done" ? "✅" : s.status === "running" ? "⏳" : s.status === "failed" ? "❌" : "•"} ${esc(s.agent)}: ${esc(s.action).slice(0, 60)}</span>`).join("")}</div>
      <div class="small muted">${fmtDate(t.created_at)}</div></div>`;
  $("#apBody").innerHTML = `<div class="grid" style="margin-top:14px">
    <div class="card"><h3>⏳ Active Tasks (${d.active.length})</h3>${d.active.map(taskCard).join("") || "<p class='muted small'>Yo'q</p>"}</div>
    <div class="card"><h3>📋 Task Queue (${d.queue.length})</h3>${d.queue.map(taskCard).join("") || "<p class='muted small'>Bo'sh</p>"}</div>
    <div class="card"><h3>🛡️ Approval Center (${d.approvals.length})</h3>${d.approvals.map((a) => `<div class="list-item"><b>${esc(a.tool)}</b> <span class="badge warn">${a.risk}</span><pre>${esc(JSON.stringify(a.args, null, 1)).slice(0, 400)}</pre><div class="row"><button class="small ok" data-yes="${a.id}">✅</button><button class="small danger" data-no="${a.id}">❌</button></div></div>`).join("") || "<p class='muted small'>Tasdiq kutayotgan amal yo'q</p>"}</div>
    <div class="card"><h3>🤖 Agent Monitor</h3>${Object.entries(d.agents).map(([a, xs]) => `<div class="list-item"><b>${esc(a)}</b>${xs.map((x) => `<div class="small">${esc(x.task)}: ${esc(x.step)}</div>`).join("")}</div>`).join("") || "<p class='muted small'>Hozir agentlar dam olmoqda</p>"}</div>
    <div class="card"><h3>📊 Resource Monitor</h3><div class="small">CPU ${res.cpu}%</div><div class="bar"><i style="width:${res.cpu}%"></i></div><div class="small" style="margin-top:8px">RAM ${res.ram}% (${res.ram_used_gb}/${res.ram_total_gb} GB)</div><div class="bar"><i style="width:${res.ram}%"></i></div><div class="small muted" style="margin-top:8px">Internet: ↑${res.net_sent_mb} MB ↓${res.net_recv_mb} MB · ROBIN: ${res.robin_ram_mb} MB</div></div>
    <div class="card"><h3>✅ Completed (${d.completed.length})</h3>${d.completed.slice(0, 10).map(taskCard).join("") || "<p class='muted small'>—</p>"}</div>
    <div class="card"><h3>❌ Failed (${d.failed.length})</h3>${d.failed.slice(0, 10).map(taskCard).join("") || "<p class='muted small'>—</p>"}</div>
    <div class="card" style="grid-column:1/-1"><h3>📜 Activity Log</h3><div class="table-wrap"><table><tr><th>Vaqt</th><th>Kim</th><th>Amal</th><th>Tafsilot</th></tr>${act.map((a) => `<tr><td class="small">${fmtDate(a.at)}</td><td>${esc(a.actor)}</td><td>${a.ok ? "" : "❌ "}${esc(a.action)}</td><td class="small muted">${esc(JSON.stringify(a.detail)).slice(0, 160)}</td></tr>`).join("")}</table></div></div></div>`;
  $$("[data-cancel]").forEach((b) => b.onclick = guard(async () => { await api(`/api/tasks/${b.dataset.cancel}/cancel`, { body: {} }); VIEWS.autopilot(v, true); }));
  $$("[data-yes],[data-no]").forEach((b) => b.onclick = guard(async () => { await api("/api/approvals/" + (b.dataset.yes || b.dataset.no), { body: { approved: !!b.dataset.yes } }); VIEWS.autopilot(v, true); }));
  const all = [...d.active, ...d.queue, ...d.completed, ...d.failed];
  $$("[data-open]").forEach((b) => b.onclick = () => { const t = all.find((x) => x.id === b.dataset.open);
    modal(`<h2>${esc(t.title)}</h2><p class="small muted">${esc(t.goal)}</p><h3>Natija</h3>${md(t.result || t.error || "—")}${t.review ? `<h3>Self-Review</h3><pre>${esc(t.review)}</pre>` : ""}<h3>Amallar</h3><pre>${esc(t.steps_log.map((s) => `${s.step}. ${s.tool} ${JSON.stringify(s.args)}\n   → ${s.result}`).join("\n"))}</pre>`); });
};

/* ---------------- BRAIN ---------------- */
VIEWS.brain = async (v) => {
  const st = await api("/api/settings"); S.settings = st; const b = st.brain, p = st.personality; const status = await api("/api/brain/status");
  const provs = Object.entries(status.providers);
  const connected = provs.filter(([, x]) => x.connected).length;
  const hp = (h) => h && h.success_pct != null ? `<span class="badge ${h.success_pct >= 80 ? "ok" : h.success_pct >= 40 ? "warn" : "err"}">${h.success_pct}% · ${h.calls} so'rov</span>` : "";
  v.innerHTML = `<div class="hero card"><div><h1>🔌 AI ulanishlar</h1><p class="muted">Bir nechta AI ulansangiz, ROBIN ulardan birini avtomatik tanlaydi: bittasi band bo'lsa yoki limiti tugasa, keyingisiga o'tadi. Kalitlar shifrlangan holda saqlanadi.</p></div>
      <div class="hero-stat"><div class="stat">${connected}<span class="muted" style="font-size:16px">/${provs.length}</span></div><div class="small muted">ulangan</div></div></div>
    <div class="grid prov-grid">${provs.map(([k, x]) => `<div class="card prov ${x.connected ? "on" : ""}">
      <div class="row"><b class="grow">${esc(x.title)}</b>${x.free ? '<span class="badge info">bepul tarif</span>' : ""}</div>
      <div class="row small" style="margin:6px 0 2px">${x.connected ? `<span class="badge ok">● ulangan</span> <span class="muted">${esc(x.model || "")}</span>` : '<span class="badge">ulanmagan</span>'} ${hp(x.health)}</div>
      ${x.health && x.health.last_error && !x.health.last_ok ? `<div class="small" style="color:var(--err)">${esc(x.health.last_error).slice(0, 140)}</div>` : ""}
      <input data-key="${k}" type="password" autocomplete="off" placeholder="${esc(st.api_keys[k] || (x.key_format ? x.key_format : "API kalit…"))}">
      <input data-model="${k}" placeholder="model (bo'sh = avtomatik)" value="${esc(b[k + "_model"] || "")}" style="margin-top:6px">
      <div class="row small" style="margin-top:8px"><a href="${x.key_url}" target="_blank" rel="noopener">🔑 Kalit olish ↗</a><span class="grow"></span>${x.connected ? `<button class="small ghost" data-rmkey="${k}">O'chirish</button>` : ""}</div></div>`).join("")}</div>
    <div class="row" style="margin:14px 0"><button class="primary" id="saveKeys">💾 Kalitlarni saqlash</button><button class="ghost" id="testKeys">⚡ Ulanishni sinash</button></div><div id="testOut"></div>
    <div class="grid2" style="margin-top:14px">
    <div class="card"><h2>🧠 Miya sozlamalari</h2>
      <label>Provayderlar tartibi (vergul bilan, birinchisi asosiy)</label><input id="order" value="${esc(b.providers.join(","))}">
      <label class="row"><input type="checkbox" id="multi" style="width:auto" ${b.multi_brain ? "checked" : ""}> Multi-Brain (mutaxassis agentlarga yo'naltirish)</label>
      <label class="row"><input type="checkbox" id="review" style="width:auto" ${b.self_review ? "checked" : ""}> Self-Review (natijani ikkinchi AI tekshiradi)</label>
      <label class="row"><input type="checkbox" id="ensemble" style="width:auto" ${b.ensemble ? "checked" : ""}> Ensemble (barcha AI javoblarini birlashtirish)</label>
      <label>Ijodkorlik (temperature): <span id="tv">${b.temperature}</span></label><input type="range" id="temp" min="0" max="1" step="0.05" value="${b.temperature}">
      <button class="primary" id="saveBrain" style="margin-top:12px">Saqlash</button></div>
    <div class="card"><h2>🎭 Shaxsiyat (Personality)</h2>
      <label>Ism</label><input id="pName" value="${esc(p.name)}"><label>Xarakter uslubi</label><input id="pStyle" value="${esc(p.style)}">
      <label>Hazil darajasi: <span id="hv">${p.humor}</span></label><input type="range" id="pHumor" min="0" max="1" step="0.1" value="${p.humor}">
      <label>Murojaat</label><select id="pForm"><option value="sen" ${p.formality === "sen" ? "selected" : ""}>Sen (samimiy)</option><option value="siz" ${p.formality === "siz" ? "selected" : ""}>Siz (rasmiy)</option></select>
      <label>Til</label><select id="pLang">${["auto", "uz", "ru", "en"].map((l) => `<option ${p.language === l ? "selected" : ""}>${l}</option>`).join("")}</select>
      <button class="primary" id="savePers" style="margin-top:12px">Saqlash</button></div></div>`;
  $("#temp").oninput = (e) => $("#tv").textContent = e.target.value; $("#pHumor").oninput = (e) => $("#hv").textContent = e.target.value;
  $("#saveKeys").onclick = guard(async () => {
    const keys = {}, models = {};
    $$("[data-key]").forEach((i) => { if (i.value.trim()) keys[i.dataset.key] = i.value.trim(); });
    $$("[data-model]").forEach((i) => { models[i.dataset.model + "_model"] = i.value.trim(); });
    if (Object.keys(keys).length) await api("/api/settings/api_keys", { method: "PUT", body: keys });
    await api("/api/settings/brain", { method: "PUT", body: models });
    toast("Saqlandi ✅", Object.keys(keys).length ? `${Object.keys(keys).length} ta kalit yangilandi` : "Modellar yangilandi", "success"); VIEWS.brain(v);
  });
  $$("[data-rmkey]").forEach((bt) => bt.onclick = guard(async () => { if (!confirm("Bu kalit o'chirilsinmi?")) return; await api("/api/settings/api_keys", { method: "PUT", body: { [bt.dataset.rmkey]: "" } }); VIEWS.brain(v); }));
  $("#testKeys").onclick = guard(async () => {
    const out = $("#testOut"); out.innerHTML = `<div class="card"><span class="muted small">⏳ Har bir ulangan AI'ga sinov xabari yuborilmoqda…</span></div>`;
    const r = await api("/api/brain/test", { body: {} });
    const rows = Object.entries(r);
    out.innerHTML = '<div class="card">' + (rows.length ? rows.map(([k, x]) => `<div class="list-item">${x.ok ? "✅" : "❌"} <b>${esc(status.providers[k]?.title || k)}</b>
        ${x.ok ? `<span class="badge ok">${esc(x.model)}</span> <span class="small muted">${x.seconds}s · javob: “${esc(x.reply)}”</span>${x.fallback ? `<div class="small" style="color:var(--warn)">Asosiy model (${esc(x.configured)}) band edi — zaxira model javob berdi.</div>` : ""}`
        : `<div class="small" style="color:var(--err)">${esc(x.hint)}</div><div class="small muted">${esc(x.error).slice(0, 300)}</div>`}</div>`).join("")
      : '<p class="small muted">Hech qanday kalit kiritilmagan.</p>') + "</div>";
  });
  $("#saveBrain").onclick = guard(async () => { await api("/api/settings/brain", { method: "PUT", body: { providers: $("#order").value.split(",").map((s) => s.trim()).filter(Boolean), multi_brain: $("#multi").checked, self_review: $("#review").checked, ensemble: $("#ensemble").checked, temperature: +$("#temp").value } }); toast("Saqlandi", "", "success"); });
  $("#savePers").onclick = guard(async () => { await api("/api/settings/personality", { method: "PUT", body: { name: $("#pName").value, style: $("#pStyle").value, humor: +$("#pHumor").value, formality: $("#pForm").value, language: $("#pLang").value } }); toast("Saqlandi"); });
};

/* ---------------- MEMORY ---------------- */
VIEWS.memory = async (v) => {
  v.innerHTML = `<div class="grid2"><div class="card"><h2>🔎 Xotiradan qidirish</h2><div class="row"><input id="mq" class="grow" placeholder="Masalan: marketplace loyihasi"><button class="primary" id="mqBtn">Qidirish</button></div><div id="mqOut"></div>
    <h3 style="margin-top:16px">📁 Loyiha konteksti (Memory 360)</h3><div class="row"><input id="pq" class="grow" placeholder="Loyiha nomi"><button id="pqBtn">Ko'rish</button></div><pre id="pqOut" style="display:none"></pre></div>
    <div class="card"><h2>➕ Eslab qolish</h2><select id="mk">${["fact", "preference", "project", "decision", "workflow"].map((k) => `<option>${k}</option>`).join("")}</select><label>Mavzu</label><input id="ms"><label>Ma'lumot</label><textarea id="mc"></textarea><button class="primary" id="mAdd" style="margin-top:8px">Saqlash</button></div></div>
    <div class="card" style="margin-top:14px"><div class="row"><h2 class="grow">🗂️ Uzoq muddatli xotira</h2><select id="mf" style="width:auto"><option value="">Hammasi</option>${["fact", "preference", "project", "decision", "workflow", "correction"].map((k) => `<option>${k}</option>`).join("")}</select></div><div id="mList"></div></div>`;
  const load = async () => { const ms = await api("/api/memory?kind=" + $("#mf").value);
    $("#mList").innerHTML = `<div class="table-wrap"><table><tr><th>Tur</th><th>Mavzu</th><th>Ma'lumot</th><th>Muhimlik</th><th></th></tr>${ms.map((m) => `<tr><td><span class="badge info">${m.kind}</span></td><td>${esc(m.subject)}</td><td>${esc(m.content)}</td><td>${m.importance}</td><td><button class="small ghost" data-del="${m.id}">🗑</button></td></tr>`).join("")}</table></div>${ms.length ? "" : "<p class='muted'>ROBIN suhbatlardan muhim narsalarni avtomatik eslab qoladi.</p>"}`;
    $$("[data-del]").forEach((b) => b.onclick = guard(async () => { await api("/api/memory/" + b.dataset.del, { method: "DELETE" }); load(); })); };
  $("#mf").onchange = load; load();
  $("#mAdd").onclick = guard(async () => { await api("/api/memory", { body: { kind: $("#mk").value, subject: $("#ms").value, content: $("#mc").value } }); $("#mc").value = ""; toast("Eslab qoldim"); load(); });
  $("#mqBtn").onclick = guard(async () => { const r = await api("/api/memory/search?q=" + encodeURIComponent($("#mq").value));
    $("#mqOut").innerHTML = r.memories.map((m) => `<div class="list-item"><span class="badge info">${m.kind}</span> <b>${esc(m.subject)}</b> ${esc(m.content)}</div>`).join("") + r.knowledge.map((k) => `<div class="list-item"><span class="badge">📄 ${esc(k.doc)}</span> <span class="small muted">${k.score}</span><div class="small">${esc(k.text).slice(0, 300)}</div></div>`).join(""); });
  $("#pqBtn").onclick = guard(async () => { const r = await api("/api/memory/project/" + encodeURIComponent($("#pq").value)); $("#pqOut").style.display = ""; $("#pqOut").textContent = r.context; });
};

/* ---------------- AGENTS ---------------- */
VIEWS.agents = async (v) => {
  const ags = await api("/api/agents");
  v.innerHTML = `<p class="muted">ROBIN Multi-Brain: har bir so'rov eng mos mutaxassisga yo'naltiriladi, murakkab vazifalar esa bir nechta agentga taqsimlanadi.</p><div class="grid">${ags.map((a) => `<div class="card"><h3>${esc(a.title)}</h3><p class="small muted">${esc(a.prompt).slice(0, 260)}…</p><textarea data-agent="${a.id}" placeholder="Bu agentga topshiriq…" style="min-height:60px"></textarea><button class="small primary" data-run="${a.id}" style="margin-top:6px">Topshiriq berish</button></div>`).join("")}</div>`;
  $$("[data-run]").forEach((b) => b.onclick = guard(async () => { const ta = $(`[data-agent="${b.dataset.run}"]`); if (!ta.value.trim()) return;
    await api("/api/tasks", { body: { goal: ta.value, agent: b.dataset.run } }); ta.value = ""; toast("Topshiriq Autopilot'ga yuborildi"); }));
};

/* ---------------- AUTOMATION (Commands + Reminders) ---------------- */
VIEWS.automation = async (v) => {
  const [cmds, rems, tools] = await Promise.all([api("/api/commands"), api("/api/reminders"), api("/api/tools")]);
  S.tools = tools;
  v.innerHTML = `<div class="card"><div class="row"><h2 class="grow">⚡ Commands — saqlangan buyruqlar</h2><button class="primary" id="addCmd">＋ Buyruq qo'shish</button></div>
    <p class="small muted">Buyruq nomini yoki ovozli iborasini aytsangiz ("ROBIN, ertalabki ish"), ROBIN uni bajaradi. Jadval: <code>daily 09:00</code>, <code>weekdays 18:30</code>, <code>every 30m</code>.</p>
    <div class="table-wrap"><table><tr><th>Nomi</th><th>Iboralar</th><th>Bosqichlar</th><th>Jadval</th><th>Manba</th><th>Ishlatilgan</th><th></th></tr>
    ${cmds.map((c) => `<tr><td><b>${esc(c.name)}</b><div class="small muted">${esc(c.description)}</div></td><td class="small">${c.triggers.map(esc).join(", ")}</td><td>${c.steps.length}</td><td>${esc(c.schedule || "—")}</td><td><span class="badge">${c.source}</span></td><td>${c.run_count}</td>
      <td class="row"><button class="small ok" data-run="${c.id}">▶</button><button class="small ghost" data-edit="${c.id}">✏️</button><button class="small ghost" data-del="${c.id}">🗑</button></td></tr>`).join("")}</table></div>${cmds.length ? "" : "<p class='muted'>Hali buyruq yo'q. ＋ ni bosing.</p>"}</div>
    <div class="card" style="margin-top:14px"><div class="row"><h2 class="grow">⏰ Eslatmalar va uchrashuvlar</h2></div>
      <div class="row"><input id="rTitle" class="grow" placeholder="Nomi"><input id="rWhen" type="datetime-local" style="width:auto"><select id="rKind" style="width:auto"><option value="reminder">Eslatma</option><option value="meeting">Uchrashuv</option><option value="task">Vazifa</option></select><select id="rRep" style="width:auto"><option value="">Bir marta</option><option value="daily">Har kuni</option><option value="weekly">Har hafta</option></select><button class="primary" id="rAdd">Qo'shish</button></div>
      ${rems.map((r) => `<div class="list-item row"><span class="grow">${r.kind === "meeting" ? "📅" : "⏰"} <b>${esc(r.title)}</b> — ${fmtDate(r.due_at)} ${r.repeat ? `<span class="badge">${r.repeat}</span>` : ""}<div class="small muted">${esc(r.note)}</div></span><button class="small ghost" data-rdel="${r.id}">🗑</button></div>`).join("")}</div>`;
  $("#addCmd").onclick = () => commandModal();
  $$("[data-run]").forEach((b) => b.onclick = guard(async () => { toast("Bajarilmoqda…"); const r = await api(`/api/commands/${b.dataset.run}/run`, { body: {} }); modal(`<h2>${esc(r.command)} ${r.ok ? "✅" : "⚠️"}</h2><pre>${esc(r.steps.map((s) => `${s.step}. ${s.tool}: ${s.result}`).join("\n"))}</pre>`); }));
  $$("[data-edit]").forEach((b) => b.onclick = () => commandModal(cmds.find((c) => c.id === b.dataset.edit)));
  $$("[data-del]").forEach((b) => b.onclick = guard(async () => { if (!confirm("O'chirilsinmi?")) return; await api("/api/commands/" + b.dataset.del, { method: "DELETE" }); VIEWS.automation(v); }));
  $("#rAdd").onclick = guard(async () => { await api("/api/reminders", { body: { title: $("#rTitle").value, due_at: $("#rWhen").value, kind: $("#rKind").value, repeat: $("#rRep").value } }); VIEWS.automation(v); });
  $$("[data-rdel]").forEach((b) => b.onclick = guard(async () => { await api("/api/reminders/" + b.dataset.rdel, { method: "DELETE" }); VIEWS.automation(v); }));
};
function commandModal(existing) {
  let draft = existing ? JSON.parse(JSON.stringify(existing)) : { name: "", description: "", triggers: [], steps: [], schedule: "", enabled: true, source: "manual" };
  const bg = modal(`<h2>${existing ? "Buyruqni tahrirlash" : "＋ Yangi buyruq"}</h2>
    ${existing ? "" : `<div class="tabs"><button class="active" data-m="manual">✍️ Qo'lda</button><button data-m="smart">🎥 Aqlli (kuzatish orqali)</button><button data-m="ai">🧠 Ta'riflab berish</button></div>`}
    <div id="mSmart" style="display:none"><p class="small">ROBIN kompyuterdagi harakatlaringizni ketma-ket kuzatadi (sichqoncha, klaviatura, oynalar) va ularni qayta bajariladigan buyruqqa aylantiradi.</p>
      <label>Nima ko'rsatmoqchisiz (izoh)</label><input id="recHint" placeholder="Masalan: har kuni ertalab pochtani ochib, hisobot papkasini ochaman">
      <div class="row" style="margin-top:8px"><button class="danger" id="recStart">⏺ Yozishni boshlash</button><button id="recStop" disabled>⏹ To'xtatish va o'rganish</button></div><p id="recInfo" class="small muted"></p></div>
    <div id="mAi" style="display:none"><label>Kunlik ishingizni so'z bilan ta'riflang</label><textarea id="aiDesc" placeholder="Masalan: Chrome'da gmail.com ni och, Excel'da Desktop/hisobot.xlsx ni och va Telegram'ga 'Ish boshlandi' deb yoz"></textarea><button id="aiGen" class="primary">Bosqichlarni yaratish</button></div>
    <label>Nomi</label><input id="cName" value="${esc(draft.name)}"><label>Tavsif</label><input id="cDesc" value="${esc(draft.description)}">
    <label>Ovozli iboralar (vergul bilan)</label><input id="cTrig" value="${esc(draft.triggers.join(", "))}" placeholder="ertalabki ish, ishni boshla">
    <label>Jadval (ixtiyoriy)</label><input id="cSched" value="${esc(draft.schedule)}" placeholder="daily 09:00 | weekdays 18:30 | every 30m">
    <label>Bosqichlar</label><div id="cSteps"></div>
    <div class="row" style="margin-top:6px"><select id="newTool" style="width:auto">${'<option value="ai">ai — ROBIN\'ga topshiriq</option>' + S.tools.map((t) => `<option value="${t.name}">${t.name}</option>`).join("")}</select><button class="small" id="addStep">＋ Bosqich</button></div>
    <div class="row" style="margin-top:14px"><button class="primary" id="cSave">💾 Saqlash</button></div>`);
  const renderSteps = () => {
    $("#cSteps", bg).innerHTML = draft.steps.map((s, i) => `<div class="card" style="padding:8px;margin:6px 0"><div class="row"><b class="grow">${i + 1}. ${esc(s.tool)}</b><button class="small ghost" data-up="${i}">↑</button><button class="small ghost" data-rm="${i}">✕</button></div>
      <textarea data-args="${i}" style="min-height:44px" placeholder='{"name":"chrome"}'>${esc(JSON.stringify(s.tool === "ai" ? (s.args || { prompt: "" }) : (s.args || {})))}</textarea>${s.note ? `<div class="small muted">${esc(s.note)}</div>` : ""}</div>`).join("") || "<p class='small muted'>Bosqich qo'shing</p>";
    $$("[data-rm]", bg).forEach((b) => b.onclick = () => { draft.steps.splice(+b.dataset.rm, 1); renderSteps(); });
    $$("[data-up]", bg).forEach((b) => b.onclick = () => { const i = +b.dataset.up; if (i > 0) { [draft.steps[i - 1], draft.steps[i]] = [draft.steps[i], draft.steps[i - 1]]; renderSteps(); } });
    $$("[data-args]", bg).forEach((t) => t.onchange = () => { try { draft.steps[+t.dataset.args].args = JSON.parse(t.value || "{}"); t.style.borderColor = ""; } catch { t.style.borderColor = "var(--err)"; } });
  };
  const fill = (d) => { draft = Object.assign(draft, d); $("#cName", bg).value = draft.name || ""; $("#cDesc", bg).value = draft.description || ""; $("#cTrig", bg).value = (draft.triggers || []).join(", "); renderSteps(); };
  renderSteps();
  $$(".tabs button", bg).forEach((b) => b.onclick = () => { $$(".tabs button", bg).forEach((x) => x.classList.toggle("active", x === b)); $("#mSmart", bg).style.display = b.dataset.m === "smart" ? "" : "none"; $("#mAi", bg).style.display = b.dataset.m === "ai" ? "" : "none"; });
  $("#addStep", bg).onclick = () => { const t = $("#newTool", bg).value; draft.steps.push({ tool: t, args: t === "ai" ? { prompt: "" } : {} }); renderSteps(); };
  const rs = $("#recStart", bg); rs && (rs.onclick = guard(async () => { await api("/api/commands/record/start", { body: {} }); rs.disabled = true; $("#recStop", bg).disabled = false; $("#recInfo", bg).textContent = "⏺ Yozilmoqda… Ishingizni odatdagidek bajaring, so'ng To'xtatish ni bosing."; }));
  const rt = $("#recStop", bg); rt && (rt.onclick = guard(async () => { $("#recInfo", bg).textContent = "🧠 ROBIN o'rganmoqda…"; const r = await api("/api/commands/record/stop", { body: { name: $("#cName", bg).value, hint: $("#recHint", bg).value } }); rs.disabled = false; rt.disabled = true; $("#recInfo", bg).textContent = `${r.events} ta harakat, ${r.duration}s. Qoralamani tekshirib saqlang.`; fill(r.draft); }));
  const ag = $("#aiGen", bg); ag && (ag.onclick = guard(async () => { ag.textContent = "…"; const r = await api("/api/commands/ai-create", { body: { name: $("#cName", bg).value, description: $("#aiDesc", bg).value } }); ag.textContent = "Bosqichlarni yaratish"; fill(r.draft); }));
  $("#cSave", bg).onclick = guard(async () => {
    const body = { name: $("#cName", bg).value.trim(), description: $("#cDesc", bg).value, triggers: $("#cTrig", bg).value.split(",").map((s) => s.trim()).filter(Boolean), steps: draft.steps, schedule: $("#cSched", bg).value.trim(), enabled: true, source: draft.source || "manual" };
    if (existing) await api("/api/commands/" + existing.id, { method: "PUT", body }); else await api("/api/commands", { body });
    bg.remove(); toast("Buyruq saqlandi ✅", body.name); VIEWS.automation($("#view"));
  });
}

/* ---------------- FILES (Knowledge Center) ---------------- */
VIEWS.files = async (v) => {
  const docs = await api("/api/knowledge");
  v.innerHTML = `<div class="grid2"><div class="card"><h2>📚 Knowledge Center</h2><p class="small muted">PDF, Word, Excel, CSV, TXT hujjatlarni yuklang — ROBIN ulardan bilimlar bazasini yaratadi va savollaringizga shu asosda javob beradi.</p>
      <input type="file" id="kFile" multiple accept=".pdf,.docx,.xlsx,.xls,.csv,.txt,.md"><button class="primary" id="kUp" style="margin-top:8px">Yuklash</button></div>
    <div class="card"><h2>📊 Excel Expert</h2><p class="small muted">Kompyuterdagi fayl yo'lini kiriting — ROBIN tahlil qilib, xatolarni topadi va hisobot yaratadi.</p>
      <input id="xPath" placeholder="C:\\Users\\...\\Desktop\\savdo.xlsx"><div class="row" style="margin-top:8px"><button class="primary" id="xGo">Tahlil + hisobot</button><button id="xFind">Excel fayllarni topish</button></div></div></div>
    <div class="card" style="margin-top:14px"><h2>Hujjatlar (${docs.length})</h2><div class="table-wrap"><table><tr><th>Nomi</th><th>Hajmi</th><th>Bo'laklar</th><th>Sana</th><th></th></tr>${docs.map((d) => `<tr><td>📄 ${esc(d.name)}</td><td>${(d.size / 1024).toFixed(1)} KB</td><td>${d.chunks}</td><td>${fmtDate(d.created_at)}</td><td><button class="small ghost" data-del="${d.id}">🗑</button></td></tr>`).join("")}</table></div></div>`;
  $("#kUp").onclick = guard(async () => { for (const f of $("#kFile").files) { const fd = new FormData(); fd.append("file", f); const r = await api("/api/knowledge/upload", { body: fd }); toast("Yuklandi", `${r.name}: ${r.chunks} bo'lak`, "success"); } VIEWS.files(v); });
  $$("[data-del]").forEach((b) => b.onclick = guard(async () => { await api("/api/knowledge/" + b.dataset.del, { method: "DELETE" }); VIEWS.files(v); }));
  $("#xGo").onclick = guard(async () => { const p = $("#xPath").value.trim(); if (!p) return;
    await api("/api/tasks", { body: { goal: `Excel faylni oching va savdo natijalarini tahlil qiling: ${p}. excel_analyze bilan statistikani va barcha xatolarni toping, excel_report bilan shu papkaga '_ROBIN_hisobot.xlsx' qo'shimchali hisobot yarating, natija va xatolar ro'yxatini notify_owner orqali egaga yuboring.`, agent: "analyst", priority: 3 } });
    toast("Analyst ishga tushdi", "Natija Autopilot va bildirishnomalarda chiqadi"); });
  $("#xFind").onclick = () => { location.hash = "#chat"; setTimeout(() => sendChat("Kompyuterimdagi oxirgi o'zgartirilgan Excel fayllarni topib ber"), 400); };
};

/* ---------------- VOICE ---------------- */
VIEWS.voice = async (v) => {
  const st = await api("/api/settings"); S.settings = st; const vc = st.voice; const cat = await api("/api/voice/voices");
  const num = (s, d = 0) => { const m = String(s ?? "").match(/-?\d+/); return m ? +m[0] : d; };
  const opt = (val, cur, label) => `<option value="${esc(val)}" ${String(cur) === String(val) ? "selected" : ""}>${esc(label || val)}</option>`;
  const voiceName = (id) => id.replace(/^[a-z]{2}-[A-Z]{2}-/, "").replace("Neural", "").replace("Multilingual", " (ko'p tilli)");
  const voiceSel = (l) => `<div class="row" style="flex-wrap:nowrap"><select id="v_${l}" class="grow">${(cat[l] || []).map((x) => opt(x.id, vc["voice_" + l], `${voiceName(x.id)} · ${x.id.slice(0, 5)} · ${x.gender === "Female" ? "ayol" : "erkak"}`)).join("")}</select><button class="small ghost" data-prev="${l}" title="Eshitib ko'rish">▶</button></div>`;
  const slider = (id, label, val, min, max, unit) => `<label>${label}: <b id="${id}V">${val > 0 ? "+" : ""}${val}${unit}</b></label><input type="range" id="${id}" min="${min}" max="${max}" value="${val}" step="1">`;
  const lexRow = (k = "", val = "") => `<div class="row lexrow" style="flex-wrap:nowrap;margin:4px 0"><input class="grow lk" value="${esc(k)}" placeholder="Yozilishi"><span>→</span><input class="grow lv" value="${esc(val)}" placeholder="Aytilishi"><button class="small ghost lx">✕</button></div>`;
  const chk = (id, on, label) => `<label class="row"><input type="checkbox" id="${id}" style="width:auto" ${on ? "checked" : ""}> ${label}</label>`;
  v.innerHTML = `<div class="grid2">
    <div class="card"><div class="avatar-box sm" id="av"></div>
      <div class="row" style="justify-content:center"><button class="mic primary" id="vMic">🎙️</button>
        <label class="row small"><input type="checkbox" id="vLive" style="width:auto" ${vc.live_conversation ? "checked" : ""}> Live suhbat</label>
        <label class="row small"><input type="checkbox" id="vWake" style="width:auto" ${vc.require_wake ? "checked" : ""}> Faqat "<span id="wwShow">${esc(vc.wake_word)}</span>" deganda</label></div>
      <div id="interim" class="small muted" style="text-align:center;margin-top:6px"></div><div id="homeReply"></div>
      ${S.voice.supported ? "" : "<p class='small' style='color:var(--warn)'>Brauzeringiz Web Speech API'ni qo'llamaydi, shuning uchun ovoz serverga (Whisper/Gemini) yuboriladi.</p>"}
      <h2 style="margin-top:16px">🧪 Sinov</h2>
      <textarea id="vText" style="min-height:90px">Salom! Men ROBIN. Bugun 5-noyabr, soat 15:30 da uchrashuvingiz bor. Excel hisobotdagi 1 250 000 so'mlik xarajat 12,5% ga oshdi. Oʻzbek tilida toʻgʻri gapiraman.</textarea>
      <div class="row" style="margin-top:8px"><button class="primary" id="vTest">🔊 Eshitish</button><button class="ghost" id="vShow">👁 Qanday o'qiladi?</button><button class="ghost" id="vStop">⏹ To'xtatish</button></div>
      <pre id="vSpoken" style="display:none;white-space:pre-wrap"></pre>
      <h2 style="margin-top:16px">📖 Talaffuz lug'ati</h2>
      <p class="small muted">ROBIN biror so'zni noto'g'ri aytsa, uni shu yerga qanday aytilishi bilan yozing. Masalan: <code>CRM → si-ar-em</code>, <code>Jasurbek → Jasurbek</code>. Ism, brend va qisqartmalar uchun ishlaydi. ROBIN 150+ texnik so'zni (Excel, PDF, AI, Telegram…) o'zi to'g'ri aytadi.</p>
      <div id="lexRows">${Object.entries(vc.lexicon || {}).map(([k, val]) => lexRow(k, val)).join("")}</div>
      <button class="small" id="lexAdd">＋ So'z qo'shish</button></div>
    <div class="card"><h2>🔊 Gapirish (TTS)</h2>
      <div class="chips" id="presets">${[["natural", "🌿 Tabiiy"], ["clear", "🎯 Sekin va aniq"], ["fast", "⚡ Tez"], ["deep", "🎩 Chuqur ovoz"], ["bright", "☀️ Yorqin"]].map(([k, n]) => `<button class="chip" data-pre="${k}">${n}</button>`).join("")}</div>
      <label>Dvigatel</label><select id="tEng">${opt("edge", vc.tts_engine, "Edge Neural (bepul, o'zbekchada eng yaxshi)")}${opt("openai", vc.tts_engine, "OpenAI TTS (kalit kerak)")}${opt("browser", vc.tts_engine, "Brauzer ovozi (oflayn)")}</select>
      <div id="edgeBox"><label>🇺🇿 O'zbek ovozi</label>${voiceSel("uz")}<label>🇷🇺 Rus ovozi</label>${voiceSel("ru")}<label>🇬🇧 Ingliz ovozi</label>${voiceSel("en")}</div>
      <div id="oaBox"><label>OpenAI ovozi</label><select id="oaVoice">${(cat.openai || []).map((x) => opt(x, vc.openai_voice)).join("")}</select>
        <label>OpenAI modeli</label><select id="oaModel">${(cat.openai_models || []).map((x) => opt(x, vc.openai_model, x === "gpt-4o-mini-tts" ? "gpt-4o-mini-tts (ohangni boshqarish)" : x === "tts-1-hd" ? "tts-1-hd (yuqori sifat)" : "tts-1 (tez)")).join("")}</select>
        <label>Ohang ko'rsatmasi (gpt-4o-mini-tts)</label><input id="oaInstr" value="${esc(vc.openai_instructions || "")}" placeholder="Masalan: iliq, xotirjam, Toshkent talaffuzida gapir"></div>
      <div id="brBox"><label>Brauzer ovozi</label><select id="brVoice"><option value="">Avtomatik</option></select></div>
      ${slider("vRate", "Tezlik", num(vc.rate), -50, 100, "%")}${slider("vPitch", "Ohang balandligi", num(vc.pitch), -50, 50, "Hz")}${slider("vVol", "Ovoz balandligi", num(vc.volume), -50, 50, "%")}
      <label>Gapirish tili</label><select id="sLang">${opt("auto", vc.speak_language, "Avtomatik (matnga qarab)")}${opt("uz", vc.speak_language, "Doim o'zbekcha")}${opt("ru", vc.speak_language, "Doim ruscha")}${opt("en", vc.speak_language, "Doim inglizcha")}</select>
      ${chk("vMulti", vc.multilingual, "Aralash matn: ruscha/inglizcha gaplarni o'z tilidagi ovozda o'qish")}
      ${chk("vNums", vc.speak_numbers, "Raqam, sana, vaqt va foizlarni o'zbekcha so'z bilan o'qish")}
      ${chk("vCode", vc.read_code, "Kod bloklarini ham o'qish")}
      ${chk("vAuto", vc.auto_speak, "Chatdagi barcha javoblarni ovozda o'qish")}
      <label>Eng uzun o'qiladigan javob (belgi)</label><input type="number" id="vMax" value="${num(vc.max_chars, 3000)}" min="200" max="20000" step="100">
      <h2 style="margin-top:18px">🎧 Tinglash (STT)</h2>
      <label>Tanib olish</label><select id="sEng">${opt("browser", vc.stt_engine, "Brauzer (bepul, tez, Live)")}${opt("openai", vc.stt_engine, "OpenAI Whisper (shevalarni eng yaxshi taniydi)")}${opt("gemini", vc.stt_engine, "Gemini (kalit kerak)")}</select>
      <label>Tanish tili</label><select id="vLang">${opt("uz-UZ", vc.stt_lang, "O'zbek")}${opt("ru-RU", vc.stt_lang, "Русский")}${opt("en-US", vc.stt_lang, "English")}</select>
      <div id="sttModelBox"><label>Whisper modeli</label><select id="sModel">${["whisper-1", "gpt-4o-mini-transcribe", "gpt-4o-transcribe"].map((x) => opt(x, vc.stt_model)).join("")}</select></div>
      <label>Uyg'otish so'zi</label><input id="vWw" value="${esc(vc.wake_word)}">
      ${chk("vBarge", vc.barge_in !== false, "Gapini bo'lish mumkin (ROBIN gapirayotganda gapirsangiz, u to'xtaydi)")}
      <label>Aks-sado filtri: <b id="vEchoV">${Math.round((vc.echo_filter ?? 0.5) * 100)}%</b> <span class="small muted">(qancha yuqori bo'lsa, ROBIN o'z ovozini shuncha kam buyruq deb oladi)</span></label><input type="range" id="vEcho" min="15" max="95" value="${Math.round((vc.echo_filter ?? 0.5) * 100)}">
      <label>Gap tugadi deb hisoblanadigan sukut (server STT): <b id="vSilV">${num(vc.silence_ms, 1500)} ms</b></label><input type="range" id="vSil" min="600" max="4000" step="100" value="${num(vc.silence_ms, 1500)}">
      ${chk("vNoise", vc.noise_suppression !== false, "Shovqinni pasaytirish")}
      ${chk("vChime", vc.chime !== false, "Tinglash boshlanganda va tugaganda signal")}
      <div class="row" style="margin-top:14px"><button class="primary" id="vSave">💾 Saqlash</button><button class="ghost" id="vReset">↺ Standart</button></div></div></div>`;
  mountAvatar($("#av"), true);
  const showEng = () => { const e = $("#tEng").value; $("#edgeBox").style.display = e === "edge" ? "" : "none"; $("#oaBox").style.display = e === "openai" ? "" : "none"; $("#brBox").style.display = e === "browser" ? "" : "none"; $("#sttModelBox").style.display = $("#sEng").value === "openai" ? "" : "none"; };
  $("#tEng").onchange = showEng; $("#sEng").onchange = showEng; showEng();
  const fillBrowser = () => { if (!$("#brVoice")) return; const vs = speechSynthesis.getVoices(); $("#brVoice").innerHTML = `<option value="">Avtomatik</option>` + vs.filter((x) => /^(uz|ru|en)/.test(x.lang)).map((x) => opt(x.name, vc.browser_voice, `${x.name} (${x.lang})`)).join(""); };
  if ("speechSynthesis" in window) { fillBrowser(); speechSynthesis.onvoiceschanged = fillBrowser; }
  const sign = (x) => (x > 0 ? "+" : "") + x;
  [["vRate", "%"], ["vPitch", "Hz"], ["vVol", "%"]].forEach(([id, u]) => $("#" + id).oninput = (e) => $("#" + id + "V").textContent = sign(+e.target.value) + u);
  $("#vEcho").oninput = (e) => $("#vEchoV").textContent = e.target.value + "%"; $("#vSil").oninput = (e) => $("#vSilV").textContent = e.target.value + " ms";
  const PRE = { natural: [0, 0, 0], clear: [-15, 0, 5], fast: [25, 0, 0], deep: [-5, -20, 5], bright: [8, 15, 0] };
  $$("[data-pre]").forEach((b) => b.onclick = () => { const [r, p, vo] = PRE[b.dataset.pre]; for (const [id, val, u] of [["vRate", r, "%"], ["vPitch", p, "Hz"], ["vVol", vo, "%"]]) { $("#" + id).value = val; $("#" + id + "V").textContent = sign(val) + u; } $$("[data-pre]").forEach((x) => x.classList.toggle("active", x === b)); });
  const lexObj = () => { const o = {}; $$(".lexrow").forEach((r) => { const k = $(".lk", r).value.trim(), val = $(".lv", r).value.trim(); if (k && val) o[k] = val; }); return o; };
  const bindLex = () => $$(".lx").forEach((b) => b.onclick = () => b.closest(".lexrow").remove());
  $("#lexAdd").onclick = () => { $("#lexRows").insertAdjacentHTML("beforeend", lexRow()); bindLex(); $$(".lk").at(-1).focus(); };
  bindLex();
  const collect = () => ({
    tts_engine: $("#tEng").value, voice_uz: $("#v_uz").value, voice_ru: $("#v_ru").value, voice_en: $("#v_en").value,
    openai_voice: $("#oaVoice").value, openai_model: $("#oaModel").value, openai_instructions: $("#oaInstr").value, browser_voice: $("#brVoice").value,
    rate: sign(+$("#vRate").value).replace(/^0$/, "+0") + "%", pitch: sign(+$("#vPitch").value).replace(/^0$/, "+0") + "Hz", volume: sign(+$("#vVol").value).replace(/^0$/, "+0") + "%",
    speak_language: $("#sLang").value, multilingual: $("#vMulti").checked, speak_numbers: $("#vNums").checked, read_code: $("#vCode").checked,
    auto_speak: $("#vAuto").checked, max_chars: +$("#vMax").value || 3000, lexicon: lexObj(),
    stt_engine: $("#sEng").value, stt_lang: $("#vLang").value, stt_model: $("#sModel").value, wake_word: $("#vWw").value.trim() || "robin",
    require_wake: $("#vWake").checked, live_conversation: $("#vLive").checked, barge_in: $("#vBarge").checked,
    echo_filter: +$("#vEcho").value / 100, silence_ms: +$("#vSil").value, noise_suppression: $("#vNoise").checked, chime: $("#vChime").checked,
  });
  const tryCfg = () => { const c = collect(); S.voice.configure({ ...S.settings.voice, ...c }); return c; };
  $("#vMic").onclick = () => { tryCfg(); if (S.voice.listening) { S.voice.stop(); $("#vMic").classList.remove("on"); } else { S.voice.start($("#vLive").checked); $("#vMic").classList.add("on"); } };
  $("#vWake").onchange = (e) => S.voice.requireWake = e.target.checked;
  $("#vLang").onchange = (e) => S.voice.lang = e.target.value;
  $("#vTest").onclick = () => { const c = tryCfg(); S.voice.speak($("#vText").value, S.avatar, c.tts_engine, c); };
  $("#vStop").onclick = () => S.voice.stopSpeaking();
  $("#vShow").onclick = guard(async () => { const r = await api("/api/voice/preview-text", { body: { text: $("#vText").value, overrides: collect() } }); $("#vSpoken").style.display = ""; $("#vSpoken").textContent = `[${r.lang}] ${r.spoken}`; });
  const SAMPLE = { uz: "Salom! Men ROBIN, sizning yordamchingizman. Bugun soat 9:30 da ishni boshlaymiz.", ru: "Привет! Я Робин, ваш помощник. Начнём работу в девять тридцать.", en: "Hi! I'm ROBIN, your assistant. Let's get started." };
  $$("[data-prev]").forEach((b) => b.onclick = () => { const c = { ...tryCfg(), tts_engine: "edge", speak_language: b.dataset.prev }; S.voice.speak(SAMPLE[b.dataset.prev], S.avatar, "edge", c); });
  $("#vSave").onclick = guard(async () => { S.settings.voice = await api("/api/settings/voice", { method: "PUT", body: collect() }); S.voice.configure(S.settings.voice); $("#wwShow").textContent = S.settings.voice.wake_word; toast("Ovoz sozlamalari saqlandi", "", "success"); });
  $("#vReset").onclick = guard(async () => {
    if (!confirm("Ovoz sozlamalari standart holatga qaytarilsinmi? Talaffuz lug'ati saqlanib qoladi.")) return;
    await api("/api/settings/voice", { method: "PUT", body: { tts_engine: "edge", voice_uz: "uz-UZ-SardorNeural", voice_ru: "ru-RU-DmitryNeural", voice_en: "en-US-AndrewNeural", rate: "+0%", pitch: "+0Hz", volume: "+0%", speak_language: "auto", multilingual: true, speak_numbers: true, read_code: false, max_chars: 3000, stt_engine: "browser", barge_in: true, echo_filter: 0.5, silence_ms: 1500, noise_suppression: true, chime: true } });
    await reloadSettings(); VIEWS.voice(v);
  });
};

/* ---------------- AVATAR ---------------- */
VIEWS.avatar = async (v) => {
  const st = await api("/api/settings"); const a = st.avatar;
  v.innerHTML = `<div class="grid2"><div class="card"><div class="avatar-box" id="av"></div><div class="row" style="justify-content:center">${["idle", "listening", "thinking", "speaking", "working", "happy", "warning"].map((s) => `<button class="small ghost" data-st="${s}">${s}</button>`).join("")}</div></div>
    <div class="card"><h2>🤖 Avatar sozlamalari</h2><label>Asosiy rang</label><input type="color" id="aCol" value="${a.color}"><label>Urg'u rangi</label><input type="color" id="aAcc" value="${a.accent}">
      <label class="row"><input type="checkbox" id="aEye" style="width:auto" ${a.eye_tracking ? "checked" : ""}> Eye Tracking (foydalanuvchiga qarab turadi)</label>
      <label>Desktop vidjet burchagi</label><select id="aCorner">${["bottom-right", "bottom-left", "top-right", "top-left"].map((c) => `<option ${a.widget_corner === c ? "selected" : ""}>${c}</option>`).join("")}</select>
      <label>Vidjet o'lchami (px)</label><input type="number" id="aSize" value="${a.size}">
      <button class="primary" id="aSave" style="margin-top:12px">Saqlash</button>
      <p class="small muted" style="margin-top:14px">💻 Laptop chetida kichik 3D ikonka: <code>python desktop/robin_widget.py</code> — doim ustida turadigan shaffof oyna; bosilsa tinglaydi, gapirganda lablari harakatlanadi.</p></div></div>`;
  const av = mountAvatar($("#av"));
  $$("[data-st]").forEach((b) => b.onclick = () => av.setState(b.dataset.st));
  $("#aCol").oninput = () => av.setColor($("#aCol").value, $("#aAcc").value); $("#aAcc").oninput = $("#aCol").oninput;
  $("#aSave").onclick = guard(async () => { S.settings.avatar = await api("/api/settings/avatar", { method: "PUT", body: { color: $("#aCol").value, accent: $("#aAcc").value, eye_tracking: $("#aEye").checked, widget_corner: $("#aCorner").value, size: +$("#aSize").value } }); toast("Saqlandi"); });
};

/* ---------------- TRADING ---------------- */
VIEWS.trading = async (v) => {
  const tab = (location.hash.split("/")[1]) || "analysis";
  const TABS = [["analysis", "📈 Tahlil"], ["ai", "🧠 AI tahlilchi"], ["risk", "🛡️ Risk Manager"], ["backtest", "🧪 Backtest"], ["sim", "🎮 Simulator"], ["journal", "📓 Jurnal"], ["academy", "🎓 Akademiya"]];
  v.innerHTML = `<div class="tabs">${TABS.map(([k, n]) => `<button class="${k === tab ? "active" : ""}" onclick="location.hash='#trading/${k}'">${n}</button>`).join("")}</div><div id="tBody"></div>
    <p class="small muted">⚠️ ROBIN Trading Expert — ta'lim va tahlil vositasi; moliyaviy maslahat emas. Real hisobdagi har bir savdo faqat sizning tasdig'ingiz bilan bajariladi.</p>`;
  const b = $("#tBody");
  const symForm = (extra = "") => `<div class="row"><input id="sym" value="${esc(localStorage.getItem("robin_sym") || "BTCUSDT")}" style="width:160px" placeholder="BTCUSDT, EURUSD, AAPL, GOLD"><select id="tf" style="width:auto">${["5m", "15m", "1h", "4h", "1d", "1w"].map((x) => `<option ${x === "1h" ? "selected" : ""}>${x}</option>`).join("")}</select>${extra}</div>`;
  if (tab === "analysis") {
    b.innerHTML = `<div class="card">${symForm('<button class="primary" id="go">Tahlil</button>')}<canvas class="chart" id="chart" width="1000" height="260"></canvas><div id="out"></div></div>`;
    $("#go").onclick = guard(async () => { localStorage.setItem("robin_sym", $("#sym").value); const a = await api(`/api/trading/analyze?symbol=${encodeURIComponent($("#sym").value)}&interval=${$("#tf").value}`);
      drawCandles($("#chart"), a.candles, a.levels); const i = a.indicators, sm = a.smart_money;
      $("#out").innerHTML = `<div class="grid" style="margin-top:12px">
        <div class="card"><div class="muted small">${esc(a.symbol)} narx</div><div class="stat">${a.price}</div><div class="small">Trend: <b>${esc(a.trend.bias)}</b> (${a.trend.confidence_pct}% ishonch)</div><div class="small muted">${a.trend.reasons.map(esc).join(" · ")}</div></div>
        <div class="card"><h3>Indikatorlar</h3><div class="small">RSI14: <b>${i.rsi14}</b> · ATR: ${i.atr14}<br>EMA20 ${i.ema20} · EMA50 ${i.ema50} · EMA200 ${i.ema200 ?? "—"}<br>MACD ${i.macd} / signal ${i.macd_signal} / hist ${i.macd_hist}<br>Bollinger: ${i.bollinger.lower} – ${i.bollinger.upper}</div></div>
        <div class="card"><h3>Support / Resistance</h3><div class="small">🟢 ${a.levels.support.map((x) => `${x.level} (${x.touches})`).join(", ") || "—"}<br>🔴 ${a.levels.resistance.map((x) => `${x.level} (${x.touches})`).join(", ") || "—"}</div><h3 style="margin-top:8px">Fibonacci (${a.fibonacci.direction})</h3><div class="small">${Object.entries(a.fibonacci.levels).map(([k, x]) => `${k}: ${x}`).join(" · ")}</div></div>
        <div class="card"><h3>Smart Money</h3><div class="small">Tuzilma: <b>${sm.structure}</b><br>${sm.last_events.map((e) => `${e.type} ${e.dir} @${e.level}`).join("<br>")}<br>OB: ${sm.order_blocks.map((o) => `${o.type} ${o.low}–${o.high}`).join("; ") || "—"}<br>FVG: ${sm.fair_value_gaps.map((f) => `${f.type} ${f.bottom}–${f.top}`).join("; ") || "—"}<br>Likvidlik: EQH ${sm.liquidity.equal_highs.join(", ") || "—"} / EQL ${sm.liquidity.equal_lows.join(", ") || "—"}</div></div>
        <div class="card"><h3>Price Action</h3><div class="small">${a.candle_patterns.map(esc).join("<br>") || "Aniq pattern yo'q"}<br>Volatillik: ${a.volatility_pct}%</div></div></div>`; });
  }
  if (tab === "ai") {
    b.innerHTML = `<div class="card">${symForm('<button class="primary" id="go">AI tahlil</button>')}<div id="out" style="margin-top:12px"></div></div>`;
    $("#go").onclick = guard(async () => { $("#out").innerHTML = "🧠 Trading Expert bozorni o'rganmoqda (bir necha taymfreym + yangiliklar)…"; const r = await api(`/api/trading/ai-analysis?symbol=${encodeURIComponent($("#sym").value)}&interval=${$("#tf").value}`); $("#out").innerHTML = md(r.analysis); });
  }
  if (tab === "risk") {
    const acc = await api("/api/trading/account");
    b.innerHTML = `<div class="grid2"><div class="card"><h2>Pozitsiya hajmi kalkulyatori</h2><label>Balans</label><input id="rb" type="number" value="${acc.balance}"><label>Risk %</label><input id="rp" type="number" step="0.1" value="${acc.limits.max_risk_per_trade_pct}"><label>Kirish</label><input id="re" type="number" step="any"><label>Stop Loss</label><input id="rs" type="number" step="any"><label>Take Profit</label><input id="rt" type="number" step="any"><button class="primary" id="rc" style="margin-top:10px">Hisoblash</button><pre id="ro"></pre></div>
      <div class="card"><h2>Limitlar</h2><label>Maks. kunlik zarar %</label><input id="l1" type="number" step="0.5" value="${acc.limits.max_daily_loss_pct}"><label>Maks. pozitsiya %</label><input id="l2" type="number" step="0.5" value="${acc.limits.max_position_pct}"><label>Maks. risk / savdo %</label><input id="l3" type="number" step="0.1" value="${acc.limits.max_risk_per_trade_pct}"><button class="primary" id="ls" style="margin-top:10px">Saqlash</button>
      <h3 style="margin-top:16px">Broker API (shifrlangan)</h3><input id="bk" type="password" placeholder="${esc(S.settings.api_keys.binance_key || "Binance API key")}"><input id="bs" type="password" placeholder="Binance secret" style="margin-top:6px"><button id="bsave" style="margin-top:6px">Kalitlarni saqlash</button></div></div>`;
    $("#rc").onclick = guard(async () => { $("#ro").textContent = JSON.stringify(await api("/api/trading/risk", { body: { balance: +$("#rb").value, risk_pct: +$("#rp").value, entry: +$("#re").value, stop_loss: +$("#rs").value, take_profit: $("#rt").value ? +$("#rt").value : null } }), null, 2); });
    $("#ls").onclick = guard(async () => { await api("/api/settings/trading", { method: "PUT", body: { max_daily_loss_pct: +$("#l1").value, max_position_pct: +$("#l2").value, max_risk_per_trade_pct: +$("#l3").value } }); toast("Limitlar saqlandi"); });
    $("#bsave").onclick = guard(async () => { await api("/api/settings/api_keys", { method: "PUT", body: { binance_key: $("#bk").value, binance_secret: $("#bs").value } }); toast("Saqlandi"); });
  }
  if (tab === "backtest") {
    const strats = await api("/api/trading/strategies");
    b.innerHTML = `<div class="card">${symForm(`<select id="st" style="width:auto"><option value="competition">🏆 Strategy Competition (hammasi)</option>${strats.map((s) => `<option value="${s.id}">${s.id}</option>`).join("")}</select><input id="bars" type="number" value="1000" style="width:100px"><button class="primary" id="go">Sinash</button>`)}<div id="out" style="margin-top:12px"></div></div>`;
    $("#go").onclick = guard(async () => { const r = await api(`/api/trading/backtest?symbol=${encodeURIComponent($("#sym").value)}&interval=${$("#tf").value}&strategy=${$("#st").value}&bars=${$("#bars").value}`);
      const rows = r.leaderboard || [r];
      $("#out").innerHTML = `<div class="table-wrap"><table><tr><th>Strategiya</th><th>Daromad %</th><th>Buy&Hold %</th><th>Max DD %</th><th>Sharpe</th><th>Savdolar</th><th>Win %</th><th>PF</th></tr>${rows.map((x, i) => `<tr><td>${i === 0 && r.leaderboard ? "🏆 " : ""}<b>${x.strategy}</b><div class="small muted">${esc(x.description)}</div></td><td>${x.total_return_pct}</td><td>${x.buy_hold_pct}</td><td>${x.max_drawdown_pct}</td><td>${x.sharpe}</td><td>${x.trades}</td><td>${x.win_rate_pct}</td><td>${x.profit_factor ?? "—"}</td></tr>`).join("")}</table></div>${r.equity_curve ? '<canvas class="chart" id="eq" width="1000" height="220"></canvas>' : ""}<p class="small muted">${esc(rows[0].note)}</p>`;
      if (r.equity_curve) drawLine($("#eq"), r.equity_curve); });
  }
  if (tab === "sim") {
    const acc = await api("/api/trading/account"); const j = await api("/api/trading/journal"); const open = j.trades.filter((t) => t.status === "open");
    b.innerHTML = `<div class="grid2"><div class="card"><h2>🎮 Demo hisob</h2><div class="stat">$${acc.balance.toFixed(2)}</div><div class="small muted">Boshlang'ich: $${acc.start_balance} · Bugun boshida: $${acc.day_start_balance}</div><button class="small ghost" id="reset" style="margin-top:8px">Hisobni qayta boshlash</button>
      <h3 style="margin-top:14px">Yangi savdo (Approval Workflow)</h3>${symForm("")}<div class="row" style="margin-top:6px"><select id="side" style="width:auto"><option value="buy">BUY</option><option value="sell">SELL</option></select><input id="qty" type="number" step="any" placeholder="Miqdor"><input id="sl" type="number" step="any" placeholder="SL"><input id="tp" type="number" step="any" placeholder="TP"></div>
      <input id="why" placeholder="Nega bu savdo? (jurnal uchun)" style="margin-top:6px"><select id="emo" style="margin-top:6px"><option value="">Kayfiyat…</option><option>xotirjam</option><option>ishonchli</option><option>shoshilish (FOMO)</option><option>zarardan keyin</option></select>
      <div class="row" style="margin-top:8px"><button id="calc">🛡️ Risk bo'yicha hajm</button><button class="primary" id="openP">Demo ochish</button><button class="danger" id="openL">REAL (tasdiq bilan)</button></div><pre id="po"></pre></div>
      <div class="card"><h2>Ochiq pozitsiyalar (${open.length})</h2>${open.map((t) => `<div class="list-item row"><span class="grow"><b>${t.symbol}</b> ${t.side.toUpperCase()} ${t.qty} @${t.entry} <span class="small muted">SL ${t.sl ?? "—"} TP ${t.tp ?? "—"} · ${t.mode}</span></span><button class="small" data-close="${t.id}">Yopish</button></div>`).join("") || "<p class='muted small'>Yo'q</p>"}</div></div>`;
    const plan = (mode) => ({ symbol: $("#sym").value, side: $("#side").value, qty: +$("#qty").value, stop_loss: $("#sl").value ? +$("#sl").value : null, take_profit: $("#tp").value ? +$("#tp").value : null, mode, reason: $("#why").value, emotion: $("#emo").value });
    $("#calc").onclick = guard(async () => { const r = await api("/api/chat", { body: { text: `risk_calculate asbobi bilan ${$("#sym").value} ${$("#side").value} uchun pozitsiya hajmi, SL va TP ni hisobla. Faqat raqamlar va qisqa izoh.` } }); $("#po").textContent = r.reply; });
    $("#openP").onclick = guard(async () => { const r = await api("/api/trading/plan", { body: plan("paper") }); $("#po").textContent = JSON.stringify(r, null, 2); if (r.ok) setTimeout(() => VIEWS.trading(v), 800); });
    $("#openL").onclick = guard(async () => { if (!confirm("REAL savdo rejasi Approval Center'ga yuboriladi. Davom etasizmi?")) return; $("#po").textContent = "Tasdiq kutilmoqda…"; const r = await api("/api/trading/plan", { body: plan("live") }); $("#po").textContent = JSON.stringify(r, null, 2); });
    $("#reset").onclick = guard(async () => { if (confirm("Demo hisob 10000$ ga qaytarilsinmi?")) { await api("/api/trading/account/reset?balance=10000", { body: {} }); VIEWS.trading(v); } });
    $$("[data-close]").forEach((x) => x.onclick = guard(async () => { const r = await api("/api/trading/close/" + x.dataset.close, { body: {} }); toast("Yopildi", `PnL: ${r.pnl}`); VIEWS.trading(v); }));
  }
  if (tab === "journal") {
    const j = await api("/api/trading/journal"); const s = j.stats;
    b.innerHTML = `<div class="grid"><div class="card"><div class="muted small">Savdolar</div><div class="stat">${s.closed}/${s.total}</div></div><div class="card"><div class="muted small">Win rate</div><div class="stat">${s.win_rate}%</div></div><div class="card"><div class="muted small">Jami PnL</div><div class="stat" style="color:${s.pnl >= 0 ? "var(--ok)" : "var(--err)"}">${s.pnl}</div></div><div class="card"><div class="muted small">O'rtacha yutuq / zarar</div><div class="stat">${s.avg_win} / ${s.avg_loss}</div></div></div>
      <div class="card" style="margin-top:14px"><div class="table-wrap"><table><tr><th>Sana</th><th>Simvol</th><th>Tomon</th><th>Kirish→Chiqish</th><th>PnL</th><th>Holat</th><th>Sabab</th><th></th></tr>${j.trades.map((t) => `<tr><td class="small">${fmtDate(t.opened_at)}</td><td>${t.symbol} <span class="badge">${t.mode}</span></td><td>${t.side}</td><td>${t.entry} → ${t.exit ?? "…"}</td><td style="color:${t.pnl >= 0 ? "var(--ok)" : "var(--err)"}">${t.pnl}</td><td>${t.status}</td><td class="small">${esc(t.reason)}</td><td><button class="small ghost" data-m="${t.id}">🧑‍🏫 Mentor</button></td></tr>`).join("")}</table></div></div>`;
    $$("[data-m]").forEach((x) => x.onclick = guard(async () => { x.textContent = "…"; const r = await api("/api/trading/mentor/" + x.dataset.m, { body: {} }); x.textContent = "🧑‍🏫 Mentor"; modal(`<h2>AI Mentor</h2>${md(r.review)}`); }));
  }
  if (tab === "academy") {
    const a = await api("/api/trading/academy");
    b.innerHTML = a.curriculum.map((lvl) => `<div class="card" style="margin-bottom:14px"><h2>${esc(lvl.level)}</h2>${lvl.lessons.map((l) => { const p = a.progress[l.id]; return `<div class="list-item row"><span class="grow">${p && p.completed ? "✅" : "📘"} <b>${esc(l.title)}</b><div class="small muted">${l.points.map(esc).join(" · ")}</div></span>${p ? `<span class="badge ok">${p.score}</span>` : ""}<button class="small primary" data-l="${l.id}">O'qish</button></div>`; }).join("")}</div>`).join("");
    $$("[data-l]").forEach((x) => x.onclick = guard(async () => { x.textContent = "…"; const r = await api("/api/trading/academy/" + x.dataset.l); x.textContent = "O'qish";
      const bg = modal(`<h2>${esc(r.lesson.title)}</h2>${md(r.content)}<h3>Test</h3>${r.lesson.quiz.map((q, i) => `<label>${esc(q.q)}</label><input data-q="${i}">`).join("")}<button class="primary" id="qz" style="margin-top:8px">Tekshirish</button><div id="qr"></div>`);
      $("#qz", bg).onclick = guard(async () => { const res = await api(`/api/trading/academy/${r.lesson.id}/quiz`, { body: { answers: $$("[data-q]", bg).map((i) => i.value) } }); $("#qr", bg).innerHTML = `<p><b>${res.score}/100</b> ${res.completed ? "✅" : ""}</p>${md(res.feedback)}`; }); }));
  }
};
function drawCandles(cv, candles, levels) {
  const ctx = cv.getContext("2d"); const W = cv.width, H = cv.height; ctx.clearRect(0, 0, W, H);
  if (!candles || !candles.length) return;
  const hi = Math.max(...candles.map((c) => c[2])), lo = Math.min(...candles.map((c) => c[3])); const y = (p) => H - 10 - ((p - lo) / (hi - lo || 1)) * (H - 20);
  const w = W / candles.length; const css = getComputedStyle(document.documentElement);
  (levels?.support || []).forEach((l) => { ctx.strokeStyle = "rgba(31,174,107,.5)"; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(0, y(l.level)); ctx.lineTo(W, y(l.level)); ctx.stroke(); });
  (levels?.resistance || []).forEach((l) => { ctx.strokeStyle = "rgba(229,72,77,.5)"; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(0, y(l.level)); ctx.lineTo(W, y(l.level)); ctx.stroke(); });
  ctx.setLineDash([]);
  candles.forEach((c, i) => { const [_, o, h, l, cl] = c; const up = cl >= o; ctx.strokeStyle = ctx.fillStyle = up ? css.getPropertyValue("--ok") : css.getPropertyValue("--err");
    const x = i * w + w / 2; ctx.beginPath(); ctx.moveTo(x, y(h)); ctx.lineTo(x, y(l)); ctx.stroke(); ctx.fillRect(x - w * 0.35, Math.min(y(o), y(cl)), w * 0.7, Math.max(1, Math.abs(y(o) - y(cl)))); });
}
function drawLine(cv, vals) {
  const ctx = cv.getContext("2d"); const W = cv.width, H = cv.height; ctx.clearRect(0, 0, W, H);
  const hi = Math.max(...vals), lo = Math.min(...vals); ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--brand"); ctx.lineWidth = 2; ctx.beginPath();
  vals.forEach((v, i) => { const x = (i / (vals.length - 1)) * W, y = H - 10 - ((v - lo) / (hi - lo || 1)) * (H - 20); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke();
}

/* ---------------- LIVE HEALTH PANEL (Settings → Ishlash holati) ---------------- */
const HEALTH_PANEL = `<div class="card health" id="healthCard">
  <div class="health-top">
    <div class="ring" id="hRing" style="--p:0"><div><div class="ring-val" id="hOverall">—</div><div class="small muted">umumiy holat</div></div></div>
    <div class="grow" style="min-width:0">
      <div class="row"><h2 class="grow" style="margin:0">📊 Ishlash holati <span class="live-dot"></span><span class="small muted">live</span></h2><span class="small muted" id="hUptime"></span></div>
      <div class="hbars" id="hComp"></div>
    </div>
  </div>
  <div class="grid2" style="margin-top:14px">
    <div class="card inset"><div class="row"><b class="grow">Live diagramma</b><span class="legend"><i style="background:var(--brand)"></i>CPU <i style="background:var(--brand2)"></i>RAM <i style="background:var(--ok)"></i>AI %</span></div><canvas id="hChart" class="chart" width="900" height="240"></canvas></div>
    <div class="card inset"><b>24 soatlik ko'rsatkichlar</b><div class="hbars" id="hMetrics"></div><b style="display:block;margin-top:12px">AI provayderlar</b><div id="hProv" class="small"></div></div>
  </div></div>`;
const HEALTH_SERIES = { cpu: [], ram: [], ai: [] };
function healthBar(name, pct, detail) {
  const cls = pct == null ? "" : pct >= 80 ? "ok" : pct >= 40 ? "warn" : "err";
  return `<div class="hbar"><div class="row small"><span class="grow">${esc(name)}</span><span class="muted">${esc(detail || "")}</span><b class="pct ${cls}">${pct == null ? "—" : pct + "%"}</b></div><div class="bar ${cls}"><i style="width:${pct == null ? 0 : pct}%"></i></div></div>`;
}
function drawHealthChart(cv) {
  const ctx = cv.getContext("2d"), W = cv.width, H = cv.height, css = getComputedStyle(document.documentElement);
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = css.getPropertyValue("--line"); ctx.lineWidth = 1; ctx.font = "11px Inter, sans-serif"; ctx.fillStyle = css.getPropertyValue("--muted");
  for (const g of [0, 25, 50, 75, 100]) { const y = H - 16 - (g / 100) * (H - 28); ctx.beginPath(); ctx.moveTo(30, y); ctx.lineTo(W, y); ctx.stroke(); ctx.fillText(g + "%", 0, y + 4); }
  const n = 60, step = (W - 34) / (n - 1);
  for (const [key, color] of [["cpu", "--brand"], ["ram", "--brand2"], ["ai", "--ok"]]) {
    const s = HEALTH_SERIES[key]; if (s.length < 2) continue;
    const col = css.getPropertyValue(color).trim(); const pts = s.map((v, i) => [34 + (n - s.length + i) * step, H - 16 - (v / 100) * (H - 28)]);
    const grad = ctx.createLinearGradient(0, 0, 0, H); grad.addColorStop(0, col + "55"); grad.addColorStop(1, col + "00");
    ctx.beginPath(); pts.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.lineTo(pts.at(-1)[0], H - 16); ctx.lineTo(pts[0][0], H - 16); ctx.closePath(); ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath(); pts.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.strokeStyle = col; ctx.lineWidth = 2.2; ctx.lineJoin = "round"; ctx.stroke();
    const [lx, ly] = pts.at(-1); ctx.beginPath(); ctx.arc(lx, ly, 3.5, 0, 7); ctx.fillStyle = col; ctx.fill();
  }
}
function startHealthPanel() {
  clearInterval(S.healthTimer);
  const tick = async () => {
    const card = $("#healthCard"); if (!card) { clearInterval(S.healthTimer); return; }
    let s; try { s = await api("/api/system/status"); } catch { return; }
    if (!$("#healthCard")) { clearInterval(S.healthTimer); return; }   // page changed while waiting
    const ring = $("#hRing"); ring.style.setProperty("--p", s.overall); ring.className = "ring " + (s.overall >= 80 ? "ok" : s.overall >= 50 ? "warn" : "err");
    $("#hOverall").textContent = s.overall + "%";
    const up = s.uptime_s; $("#hUptime").textContent = `ishlash vaqti: ${Math.floor(up / 3600)}s ${Math.floor(up % 3600 / 60)}d`;
    $("#hComp").innerHTML = s.components.map((c) => healthBar(c.name, c.pct, c.detail)).join("");
    $("#hMetrics").innerHTML = s.metrics.map((m) => healthBar(m.name, m.pct, m.n ? `${m.n} ta` : "ma'lumot yo'q")).join("");
    const pv = Object.values(s.providers);
    $("#hProv").innerHTML = pv.length ? pv.map((p) => `<div class="row" style="margin:4px 0"><span class="grow">${p.last_ok === false ? "🔴" : "🟢"} ${esc(p.title)} <span class="muted">${esc(p.model || "")}</span></span><span class="muted">${p.avg_seconds != null ? p.avg_seconds + "s" : ""}</span><b>${p.success_pct != null ? p.success_pct + "%" : "—"}</b></div>`).join("") : '<span class="muted">Ulangan AI yo\'q</span>';
    const rated = pv.map((p) => p.success_pct).filter((x) => x != null);
    for (const [k, val] of [["cpu", s.resources.cpu], ["ram", s.resources.ram], ["ai", rated.length ? Math.max(...rated) : (pv.length ? 100 : 0)]]) { HEALTH_SERIES[k].push(val); if (HEALTH_SERIES[k].length > 60) HEALTH_SERIES[k].shift(); }
    drawHealthChart($("#hChart"));
  };
  tick(); S.healthTimer = setInterval(tick, 2000);
}

/* ---------------- SETTINGS ---------------- */
VIEWS.settings = async (v) => {
  const st = await api("/api/settings"); const p = st.permissions; S.settings = st; const devs = svcOn("devices") ? await api("/api/devices") : [];
  const permLabels = { files_read: "Fayllarni o'qish", files_write: "Fayllarga yozish", files_delete: "Fayllarni o'chirish", apps: "Dasturlarni boshqarish", shell: "Terminal buyruqlari", python: "Python sandbox", mouse_keyboard: "Sichqoncha va klaviatura", screen_vision: "Ekranni ko'rish", web: "Internet", email_messages: "Xabar yuborish", trading_paper: "Demo trading", trading_live: "Real trading", smart_home: "Aqlli uy", self_config: "O'z sozlamalarini o'zgartirish" };
  v.innerHTML = HEALTH_PANEL + `<div class="grid2">
    <div class="card"><h2>🔐 Xavfsizlik — Permission Manager</h2><p class="small muted">Xavfli amallar Approval Center orqali tasdiqlanadi. Tizim papkalari va xavfli buyruqlar har doim bloklanadi.</p>
      ${Object.entries(permLabels).map(([k, n]) => { const lk = (st.policy?.locked_modules || []).includes(k); return `<label class="row"${lk ? ' title="Administrator tomonidan yopilgan"' : ""}><input type="checkbox" data-perm="${k}" style="width:auto" ${p[k] ? "checked" : ""} ${lk ? "disabled" : ""}> ${n}${lk ? ' <span class="badge">🔒 admin</span>' : ""}</label>`; }).join("")}
      <label>Mustaqillik darajasi</label><select id="autonomy"><option value="ask" ${p.autonomy === "ask" ? "selected" : ""}>Ehtiyotkor — o'rta xavfdan boshlab so'raydi</option><option value="balanced" ${p.autonomy === "balanced" ? "selected" : ""}>Muvozanat — yuqori xavfli amallarni so'raydi</option><option value="autonomous" ${p.autonomy === "autonomous" ? "selected" : ""}>Mustaqil — faqat kritik amallarni so'raydi</option></select>
      <button class="primary" id="savePerm" style="margin-top:10px">Saqlash</button></div>
    <div class="card">${svcOn("devices") ? "" : "<!--"}<h2>💻 Qurilmalar (barcha laptoplar)</h2><p class="small muted">Windows / macOS / Linux noutbukda <code>python desktop/robin_agent.py --server ${location.origin} --token TOKEN</code> ishga tushiring.</p>
      ${devs.map((d) => `<div class="list-item row"><span class="grow">${d.online ? "🟢" : "⚪"} <b>${esc(d.name)}</b> <span class="small muted">${esc(d.platform)} · ${fmtDate(d.last_seen)}</span></span><button class="small ghost" data-ddel="${d.id}">🗑</button></div>`).join("")}
      <div class="row" style="margin-top:8px"><input id="devName" class="grow" placeholder="Qurilma nomi (masalan: Ish noutbuki)"><button class="primary" id="devAdd">Token olish</button></div><pre id="devTok" style="display:none"></pre>${svcOn("devices") ? "" : "-->"}
      ${svcOn("telegram") ? "" : "<!--"}<h2 style="margin-top:18px">✈️ Telegram</h2><p class="small muted">ROBIN'ni Telegram orqali boshqaring: matn, ovozli xabar, tasdiqlash tugmalari, /stop.</p><button id="tgCode">Ulash kodini olish</button><pre id="tgOut" style="display:none"></pre>${svcOn("telegram") ? "" : "-->"}
      <h2 style="margin-top:18px">🔔 Bildirishnomalar</h2>${["web", "desktop", "telegram"].map((k) => `<label class="row"><input type="checkbox" data-notif="${k}" style="width:auto" ${st.notifications[k] ? "checked" : ""}> ${k}</label>`).join("")}<button class="small" id="saveNotif">Saqlash</button></div>
    <div class="card"><h2>🏠 Smart Home (Home Assistant)</h2><label>URL</label><input id="haUrl" value="${esc(st.smart_home.home_assistant_url)}" placeholder="http://homeassistant.local:8123"><label>Long-lived token</label><input id="haTok" type="password" placeholder="${esc(st.api_keys.home_assistant || "token")}"><button class="primary" id="saveHa" style="margin-top:10px">Saqlash</button>
      <h2 style="margin-top:18px">👤 Profil</h2><label>Eski parol</label><input id="op" type="password"><label>Yangi parol</label><input id="np" type="password"><button id="savePw" style="margin-top:8px">Parolni o'zgartirish</button>
      <label class="row" style="margin-top:12px">Mavzu: <select id="theme" style="width:auto"><option value="">Avto</option><option value="light">Yorug'</option><option value="dark">Qorong'i</option></select></label></div>
    ${S.user.is_admin ? `<div class="card"><h2>👑 Admin</h2><p class="small muted">Foydalanuvchilar, har bir foydalanuvchiga ochiq xizmatlar, limitlar, statistika, zaxira nusxa, Self-Repair va Global STOP endi alohida <b>Admin paneli</b>da.</p><a href="#admin"><button class="primary">👑 Admin paneliga o'tish</button></a></div>` : ""}</div>`;
  startHealthPanel();
  $("#theme").value = localStorage.getItem("robin_theme") || ""; $("#theme").onchange = (e) => { localStorage.setItem("robin_theme", e.target.value); applyTheme(); };
  $("#savePerm").onclick = guard(async () => { const body = { autonomy: $("#autonomy").value }; $$("[data-perm]").forEach((c) => { if (!c.disabled) body[c.dataset.perm] = c.checked; }); await api("/api/settings/permissions", { method: "PUT", body }); toast("Ruxsatlar saqlandi"); });
  $("#devAdd") && ($("#devAdd").onclick = guard(async () => { const r = await api("/api/devices", { body: { name: $("#devName").value || "Laptop" } }); $("#devTok").style.display = ""; $("#devTok").textContent = `Token (faqat bir marta ko'rsatiladi):\n${r.device_token}\n\nIshga tushirish:\npython desktop/robin_agent.py --server ${location.origin} --token ${r.device_token}`; }));
  $$("[data-ddel]").forEach((b) => b.onclick = guard(async () => { await api("/api/devices/" + b.dataset.ddel, { method: "DELETE" }); VIEWS.settings(v); }));
  $("#tgCode") && ($("#tgCode").onclick = guard(async () => { const r = await api("/api/telegram/link-code", { body: {} }); $("#tgOut").style.display = ""; $("#tgOut").textContent = r.bot_running ? r.instruction : `Bot ishlamayapti: .env faylida TELEGRAM_BOT_TOKEN ni kiriting va serverni qayta ishga tushiring.\nKod: ${r.code}`; }));
  $("#saveNotif").onclick = guard(async () => { const body = {}; $$("[data-notif]").forEach((c) => body[c.dataset.notif] = c.checked); await api("/api/settings/notifications", { method: "PUT", body }); toast("Saqlandi"); });
  $("#saveHa").onclick = guard(async () => { await api("/api/settings/smart_home", { method: "PUT", body: { home_assistant_url: $("#haUrl").value.trim() } }); if ($("#haTok").value) await api("/api/settings/api_keys", { method: "PUT", body: { home_assistant: $("#haTok").value } }); toast("Saqlandi"); });
  $("#savePw").onclick = guard(async () => { await api("/api/auth/password", { body: { old_password: $("#op").value, new_password: $("#np").value } }); toast("Parol o'zgartirildi"); });
};

/* ---------------- ADMIN PANEL (users, per-user services, limits, usage, security) ---------------- */
VIEWS.admin = async (v) => {
  if (!S.user.is_admin) { v.innerHTML = `<div class="card"><p>Faqat admin uchun.</p></div>`; return; }
  const tab = S.adminTab || "users";
  v.innerHTML = `<div class="hero card"><div><h1>👑 Admin paneli</h1><p class="muted">Foydalanuvchilarni boshqarish, har bir foydalanuvchiga qaysi xizmatlar ishlashini belgilash, kunlik limitlar, statistika va xavfsizlik.</p></div><div class="hero-stat" id="admStat"></div></div>
    <div class="tabs" style="margin:14px 0">${[["users", "👥 Foydalanuvchilar"], ["matrix", "🧩 Xizmatlar nazorati"], ["stats", "📊 Statistika"], ["security", "🛡️ Xavfsizlik va sozlamalar"], ["audit", "📜 Audit"], ["claude", "🤖 Claude"], ["client", "🧑‍💼 Mijoz paneli"], ["deploy", "🚀 Hosting"]].map(([k, n]) => `<button class="${tab === k ? "active" : ""}" data-at="${k}">${n}</button>`).join("")}</div>
    <div id="admBody"></div>`;
  $$("[data-at]").forEach((b) => b.onclick = () => { S.adminTab = b.dataset.at; VIEWS.admin(v); });
  const [ov, cat] = await Promise.all([api("/api/admin/overview"), api("/api/admin/catalog")]);
  if (!$("#admBody")) return;
  $("#admStat").innerHTML = `<div class="stat">${ov.active_today}<span class="muted" style="font-size:16px">/${ov.users}</span></div><div class="small muted">bugun faol</div>`;
  const body = $("#admBody");
  const SV = cat.services; const svcIds = Object.keys(SV);
  const ago = (s) => { if (!s) return "hech qachon"; const m = (Date.now() - parseDate(s)) / 60000; return m < 2 ? "hozirgina" : m < 60 ? `${m | 0} daqiqa oldin` : m < 1440 ? `${(m / 60) | 0} soat oldin` : `${(m / 1440) | 0} kun oldin`; };
  const showPw = (title, pw) => modal(`<h2>${esc(title)}</h2><p class="small muted">Parolni foydalanuvchiga xavfsiz yo'l bilan yetkazing. U faqat hozir ko'rsatiladi.</p><pre id="pwBox" style="font-size:18px">${esc(pw)}</pre><button class="primary" id="pwCopy">📋 Nusxalash</button>`)
    .querySelector("#pwCopy").onclick = () => { navigator.clipboard.writeText(pw); toast("Nusxalandi", "", "success"); };

  /* ---- service editor modal (one user) ---- */
  const editServices = (u, users) => {
    const bg = modal(`<h2>🧩 ${esc(u.full_name || u.username)} uchun xizmatlar</h2>
      ${u.is_admin ? `<p class="small" style="color:var(--warn)">Bu foydalanuvchi admin, shuning uchun unga barcha xizmatlar doim ochiq turadi.</p>` : ""}
      <div class="row" style="margin:6px 0"><button class="small ghost" id="sAll">Hammasini yoqish</button><button class="small ghost" id="sNone">Hammasini o'chirish</button><button class="small ghost" id="sBasic">Faqat suhbat (asosiy)</button></div>
      <div class="svc-grid">${svcIds.map((k) => `<label class="svc-item"><input type="checkbox" data-s="${k}" ${u.services[k] ? "checked" : ""} ${u.is_admin ? "disabled" : ""}><span><b>${esc(SV[k].title)}</b><span class="small muted">${esc(SV[k].desc)}</span></span></label>`).join("")}</div>
      <div class="grid2" style="margin-top:10px"><div><label>Kunlik xabarlar limiti (0 = cheksiz)</label><input type="number" min="0" id="lM" value="${u.limits.daily_messages}"></div><div><label>Kunlik ovozli so'rovlar (0 = cheksiz)</label><input type="number" min="0" id="lV" value="${u.limits.daily_voice}"></div></div>
      <label>Admin izohi (faqat siz ko'rasiz)</label><input id="uNote" value="${esc(u.note || "")}" placeholder="Masalan: sinov muddati, 1-dekabrgacha">
      <button class="primary" id="sSave" style="margin-top:12px">💾 Saqlash</button>`);
    const set = (fn) => $$("[data-s]", bg).forEach((c) => c.checked = fn(c.dataset.s));
    $("#sAll", bg).onclick = () => set(() => true); $("#sNone", bg).onclick = () => set(() => false);
    $("#sBasic", bg).onclick = () => set((k) => ["chat", "voice", "notes", "reminders", "memory", "web"].includes(k));
    $("#sSave", bg).onclick = guard(async () => {
      const services = {}; $$("[data-s]", bg).forEach((c) => services[c.dataset.s] = c.checked);
      await api(`/api/admin/users/${u.id}/policy`, { method: "PUT", body: { services, limits: { daily_messages: +$("#lM", bg).value || 0, daily_voice: +$("#lV", bg).value || 0 }, note: $("#uNote", bg).value } });
      bg.remove(); toast("Xizmatlar saqlandi", u.username, "success"); VIEWS.admin(v);
    });
  };

  /* ================= USERS ================= */
  if (tab === "users") {
    const users = await api("/api/admin/users");
    body.innerHTML = `<div class="card"><div class="row"><input id="uQ" class="grow" placeholder="🔎 Login yoki ism bo'yicha qidirish…"><button class="primary" id="uNew">＋ Yangi foydalanuvchi</button></div>
      <div class="table-wrap" style="margin-top:10px"><table class="adm-table"><tr><th>Foydalanuvchi</th><th>Holat</th><th>Bugun</th><th>7 kun</th><th>Xizmatlar</th><th>Oxirgi faollik</th><th></th></tr>
      ${users.map((u) => { const on = svcIds.filter((k) => u.services[k]).length; const lim = u.limits.daily_messages;
        return `<tr data-row="${esc(u.username + " " + (u.full_name || ""))}"><td><b>${esc(u.full_name || u.username)}</b> ${u.is_admin ? '<span class="badge info">admin</span>' : ""}${u.is_self ? ' <span class="badge">siz</span>' : ""}<div class="small muted">@${esc(u.username)}${u.telegram ? " · ✈️" : ""}${u.devices ? ` · 💻${u.devices}` : ""}</div>${u.note ? `<div class="small muted">📝 ${esc(u.note)}</div>` : ""}</td>
          <td>${u.is_active ? '<span class="badge ok">faol</span>' : '<span class="badge err">bloklangan</span>'}${u.stopped ? ' <span class="badge warn">STOP</span>' : ""}</td>
          <td>${u.today.daily_messages}${lim ? `<span class="muted">/${lim}</span>` : ""}</td><td>${u.messages_week}</td>
          <td><button class="small ghost" data-svc="${u.id}">${on}/${svcIds.length} ✏️</button></td><td class="small">${ago(u.last_active)}</td>
          <td><button class="small ghost" data-menu="${u.id}">⋯</button></td></tr>`; }).join("")}</table></div></div>`;
    $("#uQ").oninput = (e) => { const q = e.target.value.toLowerCase(); $$("[data-row]").forEach((r) => r.style.display = r.dataset.row.toLowerCase().includes(q) ? "" : "none"); };
    $$("[data-svc]").forEach((b) => b.onclick = () => editServices(users.find((x) => x.id === b.dataset.svc), users));
    $$("[data-menu]").forEach((b) => b.onclick = () => {
      const u = users.find((x) => x.id === b.dataset.menu);
      const bg = modal(`<h2>${esc(u.full_name || u.username)} <span class="small muted">@${esc(u.username)}</span></h2>
        <div class="small muted">ID: ${u.id} · ro'yxatdan o'tgan: ${fmtDate(u.created_at)} · jami ${u.messages_total} xabar</div>
        <label>Ism</label><div class="row" style="flex-wrap:nowrap"><input id="mName" class="grow" value="${esc(u.full_name || "")}"><button class="small" id="mNameS">Saqlash</button></div>
        <div class="adm-actions">
          <button data-a="services">🧩 Xizmatlar va limitlar</button>
          <button data-a="password">🔑 Parolni tiklash</button>
          ${u.is_self ? "" : `<button data-a="logout">🚪 Barcha sessiyalardan chiqarish</button>`}
          <button data-a="stop">${u.stopped ? "▶️ Agentlarni qayta yoqish" : "⛔ Agentlarini to'xtatish"}</button>
          ${u.is_self ? "" : `<button data-a="admin">${u.is_admin ? "⬇️ Admin huquqini olish" : "👑 Admin qilish"}</button>`}
          ${u.is_self ? "" : `<button data-a="block" class="${u.is_active ? "danger" : "primary"}">${u.is_active ? "🔒 Bloklash" : "🔓 Blokdan chiqarish"}</button>`}
          <button data-a="activity">📜 Faollik tarixi</button></div><div id="mOut"></div>`);
      $("#mNameS", bg).onclick = guard(async () => { await api(`/api/admin/users/${u.id}`, { method: "PUT", body: { full_name: $("#mName", bg).value } }); toast("Saqlandi"); });
      $$("[data-a]", bg).forEach((x) => x.onclick = guard(async () => {
        const a = x.dataset.a;
        if (a === "services") { bg.remove(); return editServices(u, users); }
        if (a === "password") { const pw = prompt("Yangi parol (bo'sh qoldirsangiz, kuchli parol avtomatik yaratiladi):", ""); if (pw === null) return; const r = await api(`/api/admin/users/${u.id}/password`, { body: { password: pw } }); bg.remove(); showPw("🔑 Yangi parol: " + u.username, r.password); return; }
        if (a === "logout") { if (!confirm("Foydalanuvchi barcha qurilmalardan chiqarilsinmi?")) return; await api(`/api/admin/users/${u.id}/logout`, { body: {} }); toast("Sessiyalar yakunlandi", u.username, "success"); }
        if (a === "stop") { const r = await api(`/api/admin/users/${u.id}/stop`, { body: {} }); toast(r.stopped ? `To'xtatildi (${r.cancelled} vazifa)` : "Qayta yoqildi", u.username); }
        if (a === "admin") { if (!confirm(u.is_admin ? "Admin huquqi olinsinmi?" : "Bu foydalanuvchi admin qilinsinmi? U barcha foydalanuvchilarni boshqara oladi.")) return; await api(`/api/admin/users/${u.id}`, { method: "PUT", body: { is_admin: !u.is_admin } }); }
        if (a === "block") { if (u.is_active && !confirm("Foydalanuvchi bloklansinmi? U darhol tizimdan chiqariladi va agentlari to'xtatiladi.")) return; await api(`/api/admin/users/${u.id}`, { method: "PUT", body: { is_active: !u.is_active } }); }
        if (a === "activity") { const rows = await api(`/api/admin/users/${u.id}/activity?limit=80`); $("#mOut", bg).innerHTML = `<div class="adm-log">${rows.map((r) => `<div class="small"><span class="muted">${fmtDate(r.at)}</span> ${r.ok ? "" : "❌"} <b>${esc(r.action)}</b> <span class="muted">${esc(JSON.stringify(r.detail)).slice(0, 160)}</span></div>`).join("") || "<p class='muted small'>Bo'sh</p>"}</div>`; return; }
        bg.remove(); VIEWS.admin(v);
      }));
    });
    $("#uNew").onclick = () => {
      const bg = modal(`<h2>＋ Yangi foydalanuvchi</h2><label>Login</label><input id="nU" autocomplete="off"><label>Ism</label><input id="nN"><label>Parol (bo'sh qoldirilsa, avtomatik yaratiladi)</label><input id="nP" type="text" autocomplete="off">
        <label>Til</label><select id="nL"><option value="uz">O'zbek</option><option value="ru">Русский</option><option value="en">English</option></select>
        <label>Ruxsatlar shabloni</label><select id="nT"><option value="default">Standart (yangi foydalanuvchilar sozlamasi)</option><option value="basic">Faqat suhbat va ovoz</option><option value="full">To'liq (barcha xizmatlar)</option><option value="noPC">Kompyuter boshqaruvisiz</option></select>
        <label class="row"><input type="checkbox" id="nA" style="width:auto"> Admin qilish</label><button class="primary" id="nS" style="margin-top:10px">Yaratish</button>`);
      $("#nS", bg).onclick = guard(async () => {
        const t = $("#nT", bg).value; let services = null;
        if (t === "basic") services = Object.fromEntries(svcIds.map((k) => [k, ["chat", "voice", "notes", "reminders"].includes(k)]));
        if (t === "full") services = Object.fromEntries(svcIds.map((k) => [k, true]));
        if (t === "noPC") services = Object.fromEntries(svcIds.map((k) => [k, !["files", "computer", "terminal", "devices", "trading_live"].includes(k)]));
        const r = await api("/api/admin/users", { body: { username: $("#nU", bg).value, full_name: $("#nN", bg).value, password: $("#nP", bg).value, language: $("#nL", bg).value, is_admin: $("#nA", bg).checked, services } });
        bg.remove(); if (r.password) showPw("✅ Foydalanuvchi yaratildi: " + r.username, r.password); else toast("Foydalanuvchi yaratildi", r.username, "success"); VIEWS.admin(v);
      });
    };
  }

  /* ================= SERVICE MATRIX ================= */
  if (tab === "matrix") {
    const users = (await api("/api/admin/users")).filter((u) => !u.is_admin);
    body.innerHTML = `<div class="card"><p class="small muted">Har bir foydalanuvchi uchun qaysi xizmatlar ishlashini belgilang. O'chirilgan xizmat foydalanuvchi menyusidan yo'qoladi, ROBIN ham u uchun bu asboblarni ishlatmaydi (chat, Telegram va ovoz orqali ham). Adminlar bu ro'yxatda ko'rinmaydi, chunki ularga hamma xizmat doim ochiq.</p>
      ${users.length ? `<div class="table-wrap"><table class="adm-table matrix"><tr><th>Xizmat</th>${users.map((u) => `<th title="${esc(u.full_name || "")}"><label class="row small" style="justify-content:center;flex-wrap:nowrap"><input type="checkbox" class="colSel" data-u="${u.id}" style="width:auto">@${esc(u.username)}</label></th>`).join("")}</tr>
        ${svcIds.map((k) => `<tr><td><b>${esc(SV[k].title)}</b><div class="small muted">${esc(SV[k].desc)}</div></td>${users.map((u) => `<td class="center"><input type="checkbox" class="mx" data-u="${u.id}" data-s="${k}" ${u.services[k] ? "checked" : ""}></td>`).join("")}</tr>`).join("")}
        <tr><td><b>⏳ Kunlik xabar limiti</b><div class="small muted">0 = cheksiz</div></td>${users.map((u) => `<td><input type="number" min="0" class="mxl" data-u="${u.id}" value="${u.limits.daily_messages}" style="width:80px"></td>`).join("")}</tr>
        <tr><td><b>🎙️ Kunlik ovozli limit</b></td>${users.map((u) => `<td><input type="number" min="0" class="mxv" data-u="${u.id}" value="${u.limits.daily_voice}" style="width:80px"></td>`).join("")}</tr></table></div>
        <div class="row" style="margin-top:12px"><button class="primary" id="mxSave">💾 Barchasini saqlash</button><span class="grow"></span><span class="small muted">Tanlangan ustunlarga:</span><select id="bulkSvc" style="width:auto">${svcIds.map((k) => `<option value="${k}">${esc(SV[k].title)}</option>`).join("")}</select><button class="small" data-bulk="1">Yoqish</button><button class="small" data-bulk="0">O'chirish</button></div>`
      : `<p class="muted">Hozircha oddiy foydalanuvchi yo'q. "Foydalanuvchilar" bo'limida yangisini yarating.</p>`}</div>`;
    if (!users.length) return;
    $$("[data-bulk]").forEach((b) => b.onclick = () => { const s = $("#bulkSvc").value; const sel = $$(".colSel").filter((c) => c.checked).map((c) => c.dataset.u); if (!sel.length) return toast("Avval ustunlarni (foydalanuvchilarni) belgilang"); $$(`.mx[data-s="${s}"]`).forEach((c) => { if (sel.includes(c.dataset.u)) c.checked = b.dataset.bulk === "1"; }); });
    $("#mxSave").onclick = guard(async () => {
      for (const u of users) {
        const services = {}; $$(`.mx[data-u="${u.id}"]`).forEach((c) => services[c.dataset.s] = c.checked);
        const limits = { daily_messages: +$(`.mxl[data-u="${u.id}"]`).value || 0, daily_voice: +$(`.mxv[data-u="${u.id}"]`).value || 0 };
        const changed = svcIds.some((k) => services[k] !== u.services[k]) || limits.daily_messages !== u.limits.daily_messages || limits.daily_voice !== u.limits.daily_voice;
        if (changed) await api(`/api/admin/users/${u.id}/policy`, { method: "PUT", body: { services, limits } });
      }
      toast("Xizmatlar nazorati saqlandi", "", "success"); VIEWS.admin(v);
    });
  }

  /* ================= STATS ================= */
  if (tab === "stats") {
    const users = await api("/api/admin/users");
    const tile = (n, l, cls = "") => `<div class="card inset center"><div class="stat ${cls}">${n}</div><div class="small muted">${l}</div></div>`;
    const max = Math.max(1, ...ov.chart.map((d) => d.n));
    body.innerHTML = `<div class="adm-tiles">${tile(ov.users, "foydalanuvchi")}${tile(ov.active_today, "bugun faol")}${tile(ov.messages_today, "bugungi xabarlar")}${tile(ov.messages_week, "7 kunlik xabarlar")}${tile(ov.tools_today, "bugungi amallar")}${tile(ov.blocked_today, "bloklangan amallar", ov.blocked_today ? "warn" : "")}${tile(ov.failed_logins_today, "noto'g'ri login urinishi", ov.failed_logins_today ? "err" : "")}${tile(ov.open_errors, "ochiq xatolar", ov.open_errors ? "err" : "")}</div>
      <div class="grid2" style="margin-top:14px"><div class="card"><h2>📈 14 kunlik faollik (xabarlar)</h2><div class="adm-bars">${ov.chart.map((d) => `<div class="adm-bar" title="${d.day}: ${d.n}"><i style="height:${Math.round(d.n / max * 100)}%"></i><span>${d.day.slice(3)}</span></div>`).join("")}</div></div>
      <div class="card"><h2>🏆 Eng faol foydalanuvchilar (7 kun)</h2>${users.slice().sort((a, b) => b.messages_week - a.messages_week).slice(0, 10).map((u) => `<div class="hbar"><div class="row small"><span class="grow">${esc(u.full_name || u.username)} <span class="muted">@${esc(u.username)}</span></span><b>${u.messages_week}</b></div><div class="bar ok"><i style="width:${Math.round(u.messages_week / Math.max(1, ...users.map((x) => x.messages_week)) * 100)}%"></i></div></div>`).join("")}</div></div>`;
  }

  /* ================= SECURITY & CONFIG ================= */
  if (tab === "security") {
    const cfg = ov.config;
    body.innerHTML = `<div class="grid2"><div class="card"><h2>🚪 Ro'yxatdan o'tish</h2>
        <label class="row"><input type="checkbox" id="cReg" style="width:auto" ${cfg.registration_open ? "checked" : ""}> Har kim o'zi ro'yxatdan o'ta oladi</label>
        <p class="small muted">Server tarmoqqa ochiq bo'lsa (<code>HOST=0.0.0.0</code>), ro'yxatdan o'tishni yopib qo'ying. Shunda yangi hisoblarni faqat siz "Foydalanuvchilar" bo'limida yaratasiz.</p>
        <h2 style="margin-top:16px">🆕 Yangi foydalanuvchilar uchun standart</h2><p class="small muted">Yangi ro'yxatdan o'tganlarga avtomatik beriladigan xizmatlar va limitlar.</p>
        <div class="svc-grid">${svcIds.map((k) => `<label class="svc-item"><input type="checkbox" data-ds="${k}" ${cfg.default_services[k] ? "checked" : ""}><span><b>${esc(SV[k].title)}</b></span></label>`).join("")}</div>
        <div class="grid2"><div><label>Kunlik xabarlar (0 = cheksiz)</label><input type="number" min="0" id="dM" value="${cfg.default_limits.daily_messages}"></div><div><label>Kunlik ovozli (0 = cheksiz)</label><input type="number" min="0" id="dV" value="${cfg.default_limits.daily_voice}"></div></div>
        <button class="primary" id="cSave" style="margin-top:12px">💾 Saqlash</button></div>
      <div class="card"><h2>🛠️ Tizim</h2><div class="row"><button class="primary" id="repair">🔧 Xatolarni tahlil qilish (Self-Repair)</button><button id="backup">💾 Zaxira nusxa</button>
        <button class="danger" id="gstop">${ov.global_stop ? "▶️ Global STOP'ni o'chirish" : "⛔ Global STOP"}</button></div>
        <h3 style="margin-top:14px">Zaxira nusxalar</h3><div id="bkList" class="small"></div>
        <h3 style="margin-top:14px">Xatolar</h3><div id="errList"></div></div></div>`;
    $("#cSave").onclick = guard(async () => { const ds = {}; $$("[data-ds]").forEach((c) => ds[c.dataset.ds] = c.checked);
      await api("/api/admin/config", { method: "PUT", body: { registration_open: $("#cReg").checked, default_services: ds, default_limits: { daily_messages: +$("#dM").value || 0, daily_voice: +$("#dV").value || 0 } } }); toast("Sozlamalar saqlandi", "", "success"); });
    const loadBk = async () => { const bs = await api("/api/system/backups"); $("#bkList").innerHTML = bs.slice(0, 8).map((b) => `<div class="row"><span class="grow">💾 ${esc(b.file)}</span><span class="muted">${(b.size / 1e6).toFixed(1)} MB</span><a href="#" data-bk="${esc(b.file)}">⬇</a></div>`).join("") || "<span class='muted'>Hozircha yo'q</span>";
      $$("[data-bk]").forEach((a) => a.onclick = async (e) => { e.preventDefault(); const r = await fetch("/api/system/backups/" + a.dataset.bk, { headers: { Authorization: "Bearer " + S.token } }); const l = document.createElement("a"); l.href = URL.createObjectURL(await r.blob()); l.download = a.dataset.bk; l.click(); }); };
    const loadErr = async () => { const es = await api("/api/system/errors"); $("#errList").innerHTML = es.slice(0, 12).map((e) => `<div class="list-item"><span class="badge ${e.resolved ? "ok" : "err"}">${e.resolved ? "hal qilindi" : "ochiq"}</span> <b>${esc(e.where)}</b> <span class="small muted">${fmtDate(e.at)}</span><div class="small">${esc(e.error).slice(0, 300)}</div>${e.diagnosis ? `<div class="small"><b>Tashxis:</b> ${esc(e.diagnosis)}</div>` : ""}${e.fix_proposal ? `<pre>${esc(e.fix_proposal)}</pre>` : ""}${e.resolved ? "" : `<button class="small" data-res="${e.id}">✔ Hal qilindi</button>`}</div>`).join("") || "<p class='small muted'>Xatolar yo'q 🎉</p>";
      $$("[data-res]").forEach((b) => b.onclick = guard(async () => { await api(`/api/system/errors/${b.dataset.res}/resolve`, { body: {} }); loadErr(); })); };
    loadBk(); loadErr();
    $("#repair").onclick = guard(async () => { toast("ROBIN o'z xatolarini tahlil qilmoqda…"); await api("/api/system/self-repair", { body: {} }); loadErr(); });
    $("#backup").onclick = guard(async () => { const r = await api("/api/system/backup", { body: {} }); toast("Zaxira yaratildi", r.file, "success"); loadBk(); });
    $("#gstop").onclick = guard(async () => {
      if (ov.global_stop) { await api("/api/system/global-resume", { body: {} }); toast("Global STOP o'chirildi", "", "success"); }
      else { if (!confirm("Barcha foydalanuvchilarning agentlari to'xtatilsinmi?")) return; await api("/api/system/global-stop", { body: {} }); toast("Global STOP", "", "error"); }
      VIEWS.admin(v);
    });
  }

  /* ================= 🤖 CLAUDE (Claude Code CLI on the ROBIN code) ================= */
  if (tab === "claude") return claudeTab(body);
  /* ================= 🧑‍💼 CLIENT PANEL ================= */
  if (tab === "client") return clientTab(body, cat);
  /* ================= 🚀 HOSTING / DEPLOY ================= */
  if (tab === "deploy") return deployTab(body);

  /* ================= AUDIT ================= */
  if (tab === "audit") {
    body.innerHTML = `<div class="card"><div class="row"><select id="auF" style="width:auto"><option value="">Hammasi</option><option value="admin:">Admin amallari</option><option value="login">Kirishlar</option><option value="login_failed">Noto'g'ri parollar</option><option value="blocked:">Bloklangan amallar</option><option value="tool:">ROBIN amallari</option><option value="settings">Sozlama o'zgarishlari</option></select><button class="small ghost" id="auR">↻</button></div><div id="auList" class="adm-log" style="margin-top:10px"></div></div>`;
    const load = async () => { const rows = await api("/api/admin/audit?limit=300&action=" + encodeURIComponent($("#auF").value)); $("#auList").innerHTML = rows.map((r) => `<div class="small"><span class="muted">${fmtDate(r.at)}</span> ${r.ok ? "" : "❌"} <b>@${esc(r.user)}</b> <span class="badge">${esc(r.actor)}</span> ${esc(r.action)} <span class="muted">${esc(JSON.stringify(r.detail)).slice(0, 180)}</span></div>`).join("") || "<p class='muted small'>Bo'sh</p>"; };
    $("#auF").onchange = guard(load); $("#auR").onclick = guard(load); load();
  }
};

/* ---------------- 🤖 Claude console (Admin → Claude) ---------------- */
async function refreshClaudeIcon(st) {
  const b = $("#claudeBtn"); if (!b) return;
  if (!S.user || !S.user.is_admin) { b.style.display = "none"; return; }
  try { st = st || await api("/api/claude/status"); } catch { return; }
  b.style.display = ""; b.classList.toggle("on", !!st.enabled); b.classList.toggle("busy", !!st.running);
  b.title = st.enabled ? (st.running ? "Claude ishlayapti…" : "Claude yoqilgan — bosing: Claude menyusi") : "Claude o'chiq — bosing: Claude menyusi";
}
function claudeEvent(ev) {
  if (ev.t === "text") return `<div class="cl-text">${md(ev.text)}</div>`;
  if (ev.t === "tool") return `<div class="cl-tool">⚙️ <b>${esc(ev.name)}</b> <code>${esc(ev.input)}</code></div>`;
  if (ev.t === "tool_result") return `<details class="cl-res ${ev.is_error ? "err" : ""}"><summary>${ev.is_error ? "❌ xato" : "↳ natija"}</summary><pre>${esc(ev.text)}</pre></details>`;
  if (ev.t === "init") return `<div class="cl-meta">▶ sessiya ${esc((ev.session_id || "").slice(0, 8))} · ${esc(ev.model)}</div>`;
  if (ev.t === "result") return `<div class="cl-meta">${ev.is_error ? "❌" : "✅"} ${ev.turns} qadam · ${(ev.duration_ms / 1000).toFixed(1)} s · $${(+ev.cost || 0).toFixed(4)}</div>`;
  if (ev.t === "error") return `<div class="cl-err">⚠️ ${esc(ev.text)}</div>`;
  if (ev.t === "info" || ev.t === "stderr") return `<div class="cl-meta">${esc(ev.text)}</div>`;
  return "";
}
const CL_MODES = { default: "default (so'raydi → rad etadi)", acceptEdits: "acceptEdits (fayl tahriri)", plan: "plan (faqat o'qish / reja)", bypassPermissions: "bypass (terminal kabi, hammasi)" };
const CL_QUICK = ["Mijoz paneli (/panel) ga yangi bo'lim qo'sh: ", "Testlarni ishga tushir va xatolarni tuzat", "Oxirgi qilingan ishlarni eslat va keyingi qadamni taklif qil", "Mobil ilova uchun reja tuz (hali kod yozma)"];
async function claudeTab(body) {
  let st = await api("/api/claude/status");
  const hist = () => st.history.map((h) => `<div class="cl-turn"><div class="cl-q">🧑 ${esc(h.prompt)} <span class="muted small">· @${esc(h.admin)} · ${new Date(h.at * 1000).toLocaleString()}</span></div><div class="cl-a">${md(h.result)}<div class="cl-meta">${h.ok ? "✅" : "❌"} ${h.seconds}s · $${(+h.cost || 0).toFixed(4)}</div></div></div>`).join("");
  body.innerHTML = `<div class="card cl-head">
      <button class="claude-orb ${st.enabled ? "on" : ""} ${st.running ? "busy" : ""}" id="clOrb" title="Claude'ni yoqish / o'chirish">🤖</button>
      <div class="grow"><h2 style="margin:0">Claude Code <span class="badge ${st.enabled ? "ok" : ""}">${st.enabled ? "🟢 yoqilgan" : "⚫ o'chiq"}</span></h2>
        <div class="small muted">Terminaldagi Claude Code bilan bir xil: ROBIN kodini o'qiydi, tuzatadi, test qiladi. Faqat ikonka yonib turganda ishlaydi.
        Avto-xotira: sessiya davom ettiriladi + <code>CLAUDE.md</code> + <code>notes/05_Claude_jurnali.md</code>.</div>
        <div class="small muted">CLI: <b>${esc(st.version || "topilmadi")}</b> · loyiha: <code>${esc(st.project)}</code> · sessiya: <code>${esc((st.session_id || "yangi").slice(0, 8))}</code> · ${st.runs} vazifa · $${st.total_cost}</div></div>
      <div class="cl-ctl"><label class="small">Ruxsat rejimi</label><select id="clMode">${st.modes.map((m) => `<option value="${m}" ${m === st.permission_mode ? "selected" : ""}>${CL_MODES[m] || m}</option>`).join("")}</select>
        <label class="small">Model (bo'sh = standart)</label><input id="clModel" value="${esc(st.model)}" placeholder="opus / sonnet / claude-opus-5-5">
        <div class="row" style="margin-top:6px"><button class="small" id="clNew">🆕 Yangi sessiya</button><button class="small danger" id="clStop">⛔ STOP</button></div></div></div>
    <div class="card"><div id="clLog" class="cl-log">${hist() || `<p class="muted small">Hali vazifa yo'q. Masalan: <i>"Mijoz paneliga 'Buyurtma holati' tugmasini qo'sh"</i>.</p>`}</div>
      <div class="chips" style="margin:10px 0">${CL_QUICK.map((q) => `<button class="chip" data-q="${esc(q)}">${esc(q.length > 44 ? q.slice(0, 44) + "…" : q)}</button>`).join("")}</div>
      <textarea id="clIn" rows="3" placeholder="${st.enabled ? "Claude'ga vazifa yozing… (Ctrl+Enter — yuborish)" : "Avval yuqoridagi 🤖 ikonkani yoqing"}" ${st.enabled ? "" : "disabled"}></textarea>
      <div class="row" style="margin-top:8px"><span class="small muted grow" id="clHint">${st.running ? "⏳ Claude ishlayapti: " + esc(st.current) : ""}</span><button class="primary" id="clSend" ${st.enabled && !st.running ? "" : "disabled"}>▶ Yuborish</button></div></div>`;
  const log = $("#clLog"); log.scrollTop = log.scrollHeight;
  const rerender = () => { if ($("#clLog")) { refreshClaudeIcon(); claudeTab(body); } };
  $("#clOrb").onclick = guard(async () => { st = await api("/api/claude/toggle", { body: { enabled: !st.enabled } }); toast(st.enabled ? "🤖 Claude yoqildi" : "Claude o'chirildi", "", st.enabled ? "success" : "info"); rerender(); });
  $("#clMode").onchange = guard(async (e) => {
    if (e.target.value === "bypassPermissions" && !confirm("Bypass rejimida Claude istalgan buyruqni (o'chirish, o'rnatish, internet) so'ramasdan bajaradi. Davom etilsinmi?")) { e.target.value = st.permission_mode; return; }
    st = await api("/api/claude/config", { method: "PUT", body: { permission_mode: e.target.value } }); toast("Rejim saqlandi", e.target.value, "success"); });
  $("#clModel").onchange = guard(async (e) => { st = await api("/api/claude/config", { method: "PUT", body: { model: e.target.value } }); toast("Model saqlandi", e.target.value || "standart"); });
  $("#clNew").onclick = guard(async () => { if (!confirm("Yangi sessiya boshlansinmi? (Jurnal xotirasi saqlanib qoladi)")) return; await api("/api/claude/new", { body: {} }); rerender(); });
  $("#clStop").onclick = guard(async () => { const r = await api("/api/claude/stop", { body: {} }); toast(r.stopped ? "Claude to'xtatildi" : "Ishlayotgan vazifa yo'q"); });
  $$("[data-q]").forEach((c) => c.onclick = () => { const i = $("#clIn"); if (i.disabled) return toast("Avval 🤖 ikonkani yoqing"); i.value = c.dataset.q; i.focus(); });
  $("#clIn").onkeydown = (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("#clSend").click(); };
  if (st.running) { const t = setInterval(async () => { if (!$("#clLog")) return clearInterval(t); const s = await api("/api/claude/status").catch(() => null); if (s && !s.running) { clearInterval(t); rerender(); } }, 3000); }
  $("#clSend").onclick = guard(async () => {
    const text = $("#clIn").value.trim(); if (!text) return;
    $("#clIn").value = ""; $("#clSend").disabled = true; $("#clHint").textContent = "⏳ Claude ishlayapti…"; refreshClaudeIcon({ enabled: true, running: true });
    if (log.querySelector("p.muted")) log.innerHTML = "";
    log.insertAdjacentHTML("beforeend", `<div class="cl-turn"><div class="cl-q">🧑 ${esc(text)}</div><div class="cl-a"></div></div>`);
    const live = log.lastElementChild.querySelector(".cl-a"); log.scrollTop = log.scrollHeight;
    const r = await fetch("/api/claude/chat", { method: "POST", headers: { Authorization: "Bearer " + S.token, "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    if (!r.ok) { const j = await r.json().catch(() => ({})); live.innerHTML = claudeEvent({ t: "error", text: j.detail || r.statusText }); $("#clSend").disabled = false; $("#clHint").textContent = ""; refreshClaudeIcon(); return; }
    const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); const lines = buf.split("\n"); buf = lines.pop();
      for (const l of lines) {
        if (!l.trim()) continue; let ev; try { ev = JSON.parse(l); } catch { continue; }
        if (ev.t === "done") continue;
        if (ev.t === "tool" && $("#clHint")) $("#clHint").textContent = `⚙️ ${ev.name}: ${ev.input}`.slice(0, 140);
        live.insertAdjacentHTML("beforeend", claudeEvent(ev));
        if (log.scrollHeight - log.scrollTop - log.clientHeight < 300) log.scrollTop = log.scrollHeight;
      }
    }
    if ($("#clSend")) { $("#clSend").disabled = false; $("#clHint").textContent = "✅ Tayyor"; }
    refreshClaudeIcon();
  });
}

/* ---------------- 🧑‍💼 Client panel editor (Admin → Mijoz paneli) ---------------- */
async function clientTab(body, cat) {
  const cfg = await api("/api/admin/config"); const P = cfg.client_panel; const cmds = cfg.client_commands.slice();
  const svcOpts = (sel) => Object.entries(cat.services).map(([k, s]) => `<option value="${k}" ${k === (sel || "chat") ? "selected" : ""}>${esc(s.title)}</option>`).join("");
  const rows = () => cmds.map((c, i) => `<div class="cc-row" data-i="${i}"><input class="cc-ic" value="${esc(c.icon)}" data-f="icon"><input value="${esc(c.title)}" data-f="title" placeholder="Tugma nomi"><select data-f="service" title="Qaysi xizmat ochiq bo'lsa ko'rinadi">${svcOpts(c.service)}</select><button class="small ghost" data-del="${i}">🗑</button><textarea data-f="prompt" rows="2" placeholder="ROBIN'ga yuboriladigan buyruq matni">${esc(c.prompt)}</textarea></div>`).join("");
  body.innerHTML = `<div class="grid2"><div class="card"><h2>🧑‍💼 Mijoz paneli</h2><p class="small muted">Oddiy foydalanuvchilar (mijozlar) uchun alohida, sodda dashboard: <a href="/panel" target="_blank">/panel</a>. Unda chat va siz belgilagan tayyor buyruqlar bo'ladi. Panelni Claude orqali kengaytirish: <a href="#admin" id="toClaude">🤖 Claude</a>.</p>
      <label class="row"><input type="checkbox" id="cpOn" style="width:auto" ${P.enabled ? "checked" : ""}> Mijoz paneli yoqilgan</label>
      <label class="row"><input type="checkbox" id="cpDef" style="width:auto" ${P.default_for_users ? "checked" : ""}> Oddiy foydalanuvchilar kirganda avtomatik shu panel ochilsin</label>
      <label>Sarlavha</label><input id="cpTitle" value="${esc(P.title)}"><label>Salomlashuv matni</label><textarea id="cpWel" rows="3">${esc(P.welcome)}</textarea>
      <div class="row" style="margin-top:10px"><a href="/panel" target="_blank"><button class="ghost">👁 Panelni ochish</button></a></div></div>
    <div class="card"><h2>⚡ Mijoz buyruqlari</h2><p class="small muted">Tugma bosilganda matn ROBIN'ga yuboriladi (oxiriga mijoz yozgan matn qo'shiladi). Tanlangan xizmat o'chiq foydalanuvchilarga tugma ko'rinmaydi.</p>
      <div id="ccList">${rows()}</div><div class="row" style="margin-top:8px"><button id="ccAdd">＋ Buyruq qo'shish</button><button class="primary" id="ccSave">💾 Saqlash</button></div></div></div>`;
  const sync = () => $$(".cc-row").forEach((r) => { const c = cmds[+r.dataset.i]; $$("[data-f]", r).forEach((el) => { c[el.dataset.f] = el.value; }); });
  const bind = () => $$("[data-del]").forEach((b) => b.onclick = () => { sync(); cmds.splice(+b.dataset.del, 1); $("#ccList").innerHTML = rows(); bind(); });
  bind();
  $("#toClaude").onclick = (e) => { e.preventDefault(); S.adminTab = "claude"; VIEWS.admin($("#view")); };
  $("#ccAdd").onclick = () => { sync(); cmds.push({ id: "c" + Date.now().toString(36), icon: "⚡", title: "", prompt: "", service: "chat" }); $("#ccList").innerHTML = rows(); bind(); };
  $("#ccSave").onclick = guard(async () => {
    sync();
    await api("/api/admin/config", { method: "PUT", body: { client_panel: { enabled: $("#cpOn").checked, default_for_users: $("#cpDef").checked, title: $("#cpTitle").value, welcome: $("#cpWel").value }, client_commands: cmds } });
    toast("Mijoz paneli saqlandi", "", "success");
  });
}

/* ---------------- 🚀 Hosting / auto-deploy ---------------- */
async function deployTab(body) {
  const d = await api("/api/deploy/status");
  const hook = location.origin + "/api/deploy/webhook";
  const last = d.last ? `${d.last.ok ? "✅" : "❌"} ${new Date(d.last.at * 1000).toLocaleString()} (${esc(d.last.trigger)}) ${d.last.changed ? "· yangilandi " + esc(d.last.commit || "") : "· o'zgarish yo'q"}` : "—";
  body.innerHTML = `<div class="grid2"><div class="card"><h2>🚀 Doimiy hosting (git push → avto-yangilanish)</h2>
      <div class="list-item">Git: <b>${esc(d.head || "repo yo'q")}</b></div>
      <div class="list-item">Remote: <code>${esc(d.remote || "ulanmagan")}</code> · branch <b>${esc(d.branch)}</b></div>
      <div class="list-item">Webhook kaliti: ${d.configured ? `<span class="badge ok">sozlangan</span>` : `<span class="badge warn">DEPLOY_WEBHOOK_SECRET yo'q</span>`} · avto-restart: <b>${d.restart ? "ha" : "yo'q"}</b></div>
      <div class="list-item">Oxirgi deploy: ${last}</div>
      ${d.last ? `<pre class="small">${esc((d.last.log || []).join("\n\n")).slice(-3000)}</pre>` : ""}
      <button class="primary" id="dpRun" ${d.remote ? "" : "disabled"}>⬇ Hozir yangilash (git pull)</button></div>
    <div class="card"><h2>📘 Qanday ulanadi</h2><ol class="small">
      <li>Hosting serverda: <code>git clone &lt;repo&gt;</code> → <code>bash deploy/install.sh</code> (yoki Docker: <code>docker compose up -d</code>).</li>
      <li>Server <code>.env</code>: <code>DEPLOY_WEBHOOK_SECRET=&lt;uzun kalit&gt;</code>, <code>DEPLOY_RESTART=true</code>, <code>HOST=0.0.0.0</code>.</li>
      <li>GitHub → Settings → Webhooks → Payload URL: <code>https://&lt;domen&gt;/api/deploy/webhook</code>, JSON, Secret = o'sha kalit, faqat <i>push</i>.</li>
      <li>Endi kompyuterda <code>git push</code> qilsangiz, server o'zi <code>git pull</code> → kerak bo'lsa <code>pip install</code> → qayta ishga tushadi.</li></ol>
      <p class="small muted">Bu server uchun webhook manzili: <code>${esc(hook)}</code>. Batafsil: <code>deploy/README.md</code>.</p></div></div>`;
  $("#dpRun").onclick = guard(async () => { const r = await api("/api/deploy/run", { body: {} }); toast(r.ok ? "Deploy tugadi" : "Deploy xatosi", (r.log || [r.error || ""]).join(" ").slice(0, 300), r.ok ? "success" : "error"); deployTab(body); });
}

/* ---------------- NOTES (auto-written by ROBIN + guides) ---------------- */
VIEWS.notes = async (v) => {
  v.innerHTML = `<div class="hero card"><div><h1>📝 Notes</h1><p class="muted">Bu yerda barcha yo'riqnomalar va qilingan ishlar turadi. ROBIN bu yerga o'zi yozib boradi: bajarilgan vazifalar, yangi buyruqlar, o'rgangan qoidalari va kunlik jurnal. Chatda <b>"buni notesga yozib qo'y"</b> deb aytsangiz, u yozib qo'yadi.</p></div>
      <div class="row"><button class="primary" id="nNew">＋ Yangi qayd</button><button class="ghost" id="nExport">⬇ .md eksport</button></div></div>
    <div class="notes-layout"><div class="card notes-list"><input id="nQ" placeholder="🔎 Qidirish…"><div class="chips" id="nCats"></div><div id="nItems"></div></div>
      <div class="card notes-view" id="nView"><p class="muted">Chapdan qaydni tanlang.</p></div></div>`;
  let cat = S.notesCat || "", q = "", items = [], cats = {};
  const icon = (n) => (cats[n.category] || "📄").split(" ")[0];
  const load = async () => {
    const r = await api(`/api/notes?q=${encodeURIComponent(q)}&category=${cat}`); items = r.items; cats = r.categories;
    if (!$("#nItems")) return;
    $("#nCats").innerHTML = `<button class="chip ${!cat ? "active" : ""}" data-c="">Hammasi</button>` + Object.entries(cats).map(([k, t]) => `<button class="chip ${cat === k ? "active" : ""}" data-c="${k}">${esc(t)}</button>`).join("");
    $$("#nCats .chip").forEach((b) => b.onclick = () => { cat = S.notesCat = b.dataset.c; load(); });
    $("#nItems").innerHTML = items.map((n) => `<div class="note-item" data-id="${esc(n.id)}"><div class="row" style="flex-wrap:nowrap"><span>${icon(n)}</span><b class="grow ell">${esc(n.title)}</b>${n.pinned && !n.system ? "📌" : ""}</div>
      <div class="small muted ell">${n.system ? "yo'riqnoma" : (n.auto ? "🤖 ROBIN yozdi · " : "") + fmtDate(n.created_at)}</div></div>`).join("") || `<p class="muted small">Hozircha qayd yo'q</p>`;
    $$(".note-item").forEach((el) => el.onclick = () => show(el.dataset.id));
    if (S.noteOpen && items.find((x) => x.id === S.noteOpen)) show(S.noteOpen); else if (items[0]) show(items[0].id);
  };
  const show = (id) => {
    const n = items.find((x) => x.id === id); if (!n) return; S.noteOpen = id;
    $$(".note-item").forEach((el) => el.classList.toggle("active", el.dataset.id === id));
    const tools = n.system ? `<span class="small muted">faqat o'qish uchun</span>`
      : `<button class="small ghost" id="nPin">${n.pinned ? "📌 Olib tashlash" : "📌 Mahkamlash"}</button><button class="small ghost" id="nEdit">✏️ Tahrirlash</button><button class="small ghost" id="nDel">🗑</button>`;
    $("#nView").innerHTML = `<div class="row"><span class="badge info">${esc(cats[n.category] || n.category)}</span>${n.auto ? `<span class="badge">🤖 avtomatik</span>` : ""}<span class="grow"></span>${tools}</div>
      <h2 style="margin-top:12px">${esc(n.title)}</h2><div class="small muted">${fmtDate(n.updated_at || n.created_at)}</div><div class="note-body">${md(n.body)}</div>`;
    if (n.system) return;
    $("#nDel").onclick = guard(async () => { if (!confirm("Qayd o'chirilsinmi?")) return; await api("/api/notes/" + n.id, { method: "DELETE" }); S.noteOpen = null; load(); });
    $("#nPin").onclick = guard(async () => { await api("/api/notes/" + n.id, { method: "PUT", body: { title: n.title, body: n.body, pinned: !n.pinned } }); load(); });
    $("#nEdit").onclick = () => editor(n);
  };
  const editor = (n) => {
    const bg = modal(`<h2>${n ? "✏️ Tahrirlash" : "＋ Yangi qayd"}</h2><label>Sarlavha</label><input id="eT" value="${esc(n ? n.title : "")}"><label>Matn (Markdown)</label><textarea id="eB" style="min-height:260px">${esc(n ? n.body : "")}</textarea><button class="primary" id="eS" style="margin-top:10px">💾 Saqlash</button>`);
    $("#eS", bg).onclick = guard(async () => {
      const body = { title: $("#eT", bg).value, body: $("#eB", bg).value, pinned: n ? n.pinned : false };
      const r = n ? await api("/api/notes/" + n.id, { method: "PUT", body }) : await api("/api/notes", { body });
      bg.remove(); S.noteOpen = r.id; load();
    });
  };
  $("#nNew").onclick = () => editor(null);
  $("#nExport").onclick = guard(async () => {
    const r = await fetch("/api/notes/export.md", { headers: { Authorization: "Bearer " + S.token } });
    const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = "ROBIN_notes.md"; a.click();
  });
  let t; $("#nQ").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { q = e.target.value; load(); }, 250); };
  S.reloadNotes = load;
  load();
};

/* ---------------- DOWNLOAD APP ---------------- */
VIEWS.download = async (v) => {
  const info = await api("/api/apps/info");
  if (!v.isConnected) return;
  const os = /Win/.test(navigator.platform) ? "Windows" : /Mac/.test(navigator.platform) ? "macOS" : /Linux/.test(navigator.platform) ? "Linux" : "kompyuter";
  const reach = info.lan;   // other laptops reach this server only via the LAN address
  const warn = info.exposed ? "" : `<div class="card warn-card"><b>⚠️ Server hozir faqat shu kompyuterdan ochiladi</b> (<code>HOST=${esc(info.host)}</code>). Telefon yoki boshqa noutbuk QR kod orqali ulanishi uchun <code>.env</code> faylida <code>HOST=0.0.0.0</code> qilib, ROBIN'ni qayta ishga tushiring. Windows "Firewall" so'rasa, <b>Private network</b> uchun ruxsat bering. Shundan keyin manzil <code>${esc(info.lan)}</code> bo'ladi.</div>`;
  v.innerHTML = `<div class="hero card"><div><h1>⬇️ Download App</h1><p class="muted">ROBIN'ni boshqa qurilmalarga o'rnating. Kompyuterda ROBIN o'sha kompyuterni boshqaradi, telefonda esa ROBIN bilan gaplashasiz va uni kuzatib turasiz.</p></div><div class="hero-stat"><div class="small muted">versiya</div><div class="stat" style="font-size:22px">${esc(info.version)}</div></div></div>
  ${warn}
  <div class="grid2" style="margin-top:16px">
    <div class="card dl-card"><div class="dl-icon">💻</div><h2>Desktop ilova</h2><p class="muted small">Windows · macOS · Linux. Tarkibi: ROBIN agenti va ekran chetidagi 3D robot vidjeti. Server manzili va qurilma tokeni paket ichida tayyor turadi, hech narsa kiritish shart emas.</p>
      <label>Qurilma nomi</label><input id="dName" value="${esc(os)} noutbuk">
      <div class="row" style="margin-top:10px"><button class="primary" id="dHere">⬇ Shu kompyuterga yuklab olish</button><button class="ghost" id="dQr">📱 Boshqa noutbuk uchun QR</button></div>
      <div id="dOut"></div>
      <details style="margin-top:12px"><summary><b>O'rnatish yo'riqnomasi</b></summary><ol class="small steps-list">
        <li>Yuklangan <code>ROBIN-Desktop.zip</code> ni oching (Extract all).</li>
        <li><b>Windows:</b> <code>ROBIN_Ornatish_Windows.bat</code> faylini ikki marta bosing.<br><b>macOS/Linux:</b> <code>bash install_mac_linux.sh</code>.</li>
        <li>Birinchi marta Python kutubxonalari o'rnatiladi (1–3 daqiqa). Kompyuterda Python 3.10+ bo'lishi kerak.</li>
        <li>Ekran chetida 3D robot paydo bo'ladi, Settings → Qurilmalar ro'yxatida esa 🟢 belgisi yonadi.</li>
        <li>macOS'da Accessibility va Screen Recording ruxsatini bering.</li>
        <li>Favqulodda to'xtatish uchun sichqonchani ekran burchagiga olib boring yoki ⛔ STOP tugmasini bosing.</li></ol></details></div>
    <div class="card dl-card"><div class="dl-icon">📱</div><h2>Mobil ilova</h2><p class="muted small">Android va iPhone. Telefon kamerasi bilan QR kodni skanerlang, ochilgan sahifada <b>"Bosh ekranga qo'shish"</b> (Add to Home Screen) ni tanlang. ROBIN ilova kabi ochiladi.</p>
      <div class="qr-box">${info.mobile_qr}</div><div class="center small"><a href="${esc(info.mobile_url)}" target="_blank" rel="noopener">${esc(info.mobile_url)}</a></div>
      <div class="row center" style="margin-top:10px"><button class="ghost small" id="pwaBtn" ${S.pwaPrompt ? "" : "hidden"}>📲 Shu qurilmaga o'rnatish</button><button class="ghost small" id="copyUrl">📋 Havolani nusxalash</button></div>
      <details style="margin-top:12px"><summary><b>Yo'riqnoma</b></summary><ol class="small steps-list">
        <li>Telefon va kompyuter <b>bitta Wi-Fi</b> tarmog'ida bo'lishi kerak.</li>
        <li><b>Android (Chrome):</b> ⋮ menyu → "Bosh ekranga qo'shish" yoki "Ilovani o'rnatish".</li>
        <li><b>iPhone (Safari):</b> "Ulashish" ⬆ → "Add to Home Screen".</li>
        <li>Login va parolingiz bilan kiring. Chat, ovoz, Autopilot, tasdiqlash va bildirishnomalar ishlaydi.</li>
        <li>iOS cheklovlari sabab telefon kompyuterdagidek tizim amallarini bajara olmaydi: u boshqaruv va monitoring uchun.</li>
        <li>Uydan tashqarida ishlatish uchun Telegram bot (Settings → Telegram) yoki HTTPS bilan internetga chiqarilgan server kerak.</li></ol></details></div>
  </div>
  <div class="card dl-card" style="margin-top:16px"><div class="dl-icon">🤖</div><h2>ROBIN Android ilovasi</h2>
    <p class="muted small">Native ilova: chat, ovozli savol va javob, kamera orqali Live Vision, tasdiqlash (Approval), bildirishnomalar, tayyor buyruqlar, adminlar uchun 🤖 Claude. Parolsiz ulanadi: ilovada <b>"QR orqali ulanish"</b> ni bosib, quyidagi QR kodni skanerlang.</p>
    <div class="grid2"><div id="apkBox" class="center small muted">APK tekshirilmoqda…</div>
      <div class="center"><button class="primary" id="pairBtn">📱 Telefonni ulash (QR)</button><div id="pairOut"></div></div></div></div>`;
  api("/api/mobile/info").then((m) => { const el = $("#apkBox"); if (!el) return;
    const url = (info.exposed ? info.lan : location.origin) + m.url;
    el.innerHTML = m.apk ? `<a href="${m.url}"><button class="primary">⬇ ROBIN.apk (${(m.size / 1e6).toFixed(1)} MB)</button></a><div class="qr-box" style="margin-top:8px"><img alt="APK QR" style="width:180px" src="/api/apps/qr?text=${encodeURIComponent(url)}&token=${encodeURIComponent(S.token)}"></div><div class="small muted">Telefonda QR'ni skanerlab APK'ni yuklang → o'rnating ("Noma'lum manbalar"ga ruxsat bering).</div>`
      : `<p class="small muted">APK hali yig'ilmagan. Admin: <code>mobile\robin_app\build_apk.bat</code></p>`; }).catch(() => {});
  $("#pairBtn").onclick = guard(async () => {
    const r = await api("/api/mobile/pair-code", { body: {} });
    $("#pairOut").innerHTML = `<div class="qr-box">${r.qr}</div><div class="small">Server: <code>${esc(r.server)}</code> · kod: <code>${esc(r.code)}</code></div><div class="small muted">5 daqiqa amal qiladi, bir marta ishlatiladi.${r.lan_ok ? "" : " ⚠️ Telefon ulanishi uchun .env da HOST=0.0.0.0 kerak."}</div>`;
  });
  const showLink = (r, forQr) => {
    $("#dOut").innerHTML = forQr
      ? `<div class="qr-box">${r.qr}</div><div class="small muted center">Boshqa noutbukda telefon kamerasi yoki brauzer orqali oching. Havola 30 daqiqa amal qiladi. Qurilma: <b>${esc(r.device_name)}</b></div><div class="center small"><a href="${esc(r.url)}">${esc(r.url)}</a></div>`
      : `<p class="small" style="color:var(--ok)">✅ Yuklab olish boshlandi. Qurilma: <b>${esc(r.device_name)}</b>. ZIP'ni oching va o'rnatuvchini ishga tushiring.</p>`;
  };
  $("#dHere").onclick = guard(async () => { const r = await api("/api/apps/desktop-link", { body: { name: $("#dName").value, base: location.origin } }); location.href = r.url; showLink(r, false); });
  $("#dQr").onclick = guard(async () => { const r = await api("/api/apps/desktop-link", { body: { name: $("#dName").value, base: reach } }); showLink(r, true); });
  $("#copyUrl").onclick = () => { navigator.clipboard.writeText(info.mobile_url); toast("Havola nusxalandi", "", "success"); };
  $("#pwaBtn").onclick = async () => { if (!S.pwaPrompt) return; S.pwaPrompt.prompt(); await S.pwaPrompt.userChoice; S.pwaPrompt = null; $("#pwaBtn").hidden = true; };
};
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); S.pwaPrompt = e; const b = $("#pwaBtn"); if (b) b.hidden = false; });

function applyTheme() { const t = localStorage.getItem("robin_theme"); if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; }
applyTheme();
boot();

/* header 🤖 icon → Admin → Claude menu (lit = Claude enabled, pulsing = working) */
$("#claudeBtn").onclick = () => { S.adminTab = "claude"; if (location.hash === "#admin") VIEWS.admin($("#view")); else location.hash = "#admin"; };
setInterval(() => { if (S.user && S.user.is_admin && !document.hidden) refreshClaudeIcon(); }, 15000);
