/* ROBIN — Mijoz paneli (customer dashboard). Chat + ready-made commands defined in Admin → Mijoz paneli. */
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const S = { token: localStorage.getItem("robin_token") || "", conv: sessionStorage.getItem("robin_panel_conv") || null, data: null };

function mdLite(t) {   // escaped → code blocks, inline code, bold, line breaks
  return esc(t || "").replace(/```[\w-]*\n?([\s\S]*?)```/g, "<pre><code>$1</code></pre>").replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>");
}
function toast(title, body = "", level = "info") {
  const d = document.createElement("div"); d.className = "toast " + level;
  d.innerHTML = `<b>${esc(title)}</b>${body ? `<div class="small muted">${esc(body)}</div>` : ""}`;
  $("#toasts").appendChild(d); setTimeout(() => d.remove(), 6000);
}
async function api(path, body) {
  const o = { method: body ? "POST" : "GET", headers: { Authorization: "Bearer " + S.token } };
  if (body) { o.body = JSON.stringify(body); o.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, o);
  if (r.status === 401) { logout(); throw new Error("Login talab qilinadi"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : r.statusText);
  return j;
}
function logout() { localStorage.removeItem("robin_token"); sessionStorage.removeItem("robin_panel_conv"); location.reload(); }
$("#logout").onclick = (e) => { e.preventDefault(); logout(); };

$("#authForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.fromEntries(new FormData(e.target))) });
    const j = await r.json(); if (!r.ok) throw new Error(j.detail || "Xato");
    S.token = j.token; localStorage.setItem("robin_token", j.token); boot();
  } catch (err) { $("#authErr").textContent = err.message; }
};

function addMsg(text, me, wait) {
  const d = document.createElement("div"); d.className = "cp-msg" + (me ? " me" : "") + (wait ? " wait" : "");
  if (me) d.textContent = text; else d.innerHTML = mdLite(text);
  $("#msgs").appendChild(d); $("#msgs").scrollTop = $("#msgs").scrollHeight; return d;
}
function renderUsage() {
  const u = S.data.usage.daily_messages, l = S.data.limits.daily_messages;
  $("#usage").textContent = l ? `Bugun: ${u}/${l} xabar` : `Bugun: ${u} xabar`;
  $("#usage").className = "badge " + (l && u >= l ? "err" : "info");
}
async function send(text, commandId, extra) {
  const wait = addMsg("ROBIN o'ylayapti…", false, true);
  $("#sendBtn").disabled = true;
  try {
    const r = commandId ? await api("/api/client/run", { command_id: commandId, extra: extra || "", conversation_id: S.conv })
      : await api("/api/chat", { text, conversation_id: S.conv });
    if (r.conversation_id) { S.conv = r.conversation_id; sessionStorage.setItem("robin_panel_conv", S.conv); }
    wait.remove(); addMsg(r.reply || "(javob yo'q)", false);
    S.data.usage.daily_messages++; renderUsage();
  } catch (e) { wait.remove(); addMsg("⚠️ " + e.message, false); }
  finally { $("#sendBtn").disabled = false; }
}
function runCommand(c) {
  const needsText = /[:\s]$/.test(c.prompt);
  if (needsText) {
    const extra = prompt(`${c.icon} ${c.title}\n\nMatnni kiriting:`, "");
    if (extra === null || !extra.trim()) return;
    addMsg(`${c.icon} ${c.title}: ${extra}`, true); send("", c.id, extra);
  } else { addMsg(`${c.icon} ${c.title}`, true); send("", c.id, ""); }
}
async function loadHistory() {
  if (!S.conv) return;
  try {
    const c = await fetch(`/api/chat/conversations/${S.conv}`, { headers: { Authorization: "Bearer " + S.token } }).then((r) => r.ok ? r.json() : null);
    (c ? c.messages : []).filter((m) => m.role === "user" || m.role === "assistant").slice(-30).forEach((m) => addMsg(m.content, m.role === "user"));
  } catch { /* history is optional */ }
}

async function boot() {
  if (!S.token) { $("#login").style.display = ""; return; }
  try { S.data = await api("/api/client/panel"); } catch { $("#login").style.display = ""; return; }
  const P = S.data.panel, U = S.data.user;
  if (!P.enabled && !U.is_admin) { document.body.innerHTML = `<div class="card" style="margin:40px auto;max-width:480px"><h2>Mijoz paneli vaqtincha o'chiq</h2><p class="muted">Administrator bilan bog'laning.</p><a href="/?full=1">Dashboard</a></div>`; return; }
  $("#login").style.display = "none"; $("#panel").style.display = "";
  document.querySelectorAll(".pTitle").forEach((e) => e.textContent = P.title || "ROBIN");
  document.title = (P.title || "ROBIN") + " — Mijoz paneli";
  $("#who").textContent = U.full_name || U.username;
  $("#hello").textContent = `Salom, ${U.full_name || U.username}! 👋`;
  $("#welcome").textContent = P.welcome;
  renderUsage();
  $("#cmds").innerHTML = S.data.commands.map((c, i) => `<button class="cp-cmd" data-i="${i}" title="${esc(c.prompt)}"><span class="ic">${esc(c.icon)}</span><b>${esc(c.title)}</b></button>`).join("")
    || `<p class="muted small">Hozircha tayyor buyruqlar yo'q.</p>`;
  document.querySelectorAll(".cp-cmd").forEach((b) => b.onclick = () => runCommand(S.data.commands[+b.dataset.i]));
  if (!S.data.services.chat?.on) { $("#sendForm").innerHTML = `<p class="muted small">💬 Chat xizmati siz uchun o'chirilgan.</p>`; }
  loadHistory();
}
$("#sendForm").onsubmit = (e) => { e.preventDefault(); const t = $("#txt").value.trim(); if (!t) return; $("#txt").value = ""; addMsg(t, true); send(t); };
$("#txt").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#sendForm").requestSubmit(); } };
$("#newChat").onclick = () => { S.conv = null; sessionStorage.removeItem("robin_panel_conv"); $("#msgs").innerHTML = ""; toast("Yangi suhbat"); };
boot();
