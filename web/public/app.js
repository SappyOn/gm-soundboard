/* GM Soundboard — UI. Talks to Python through window.pywebview.api */
"use strict";

const SLOTS = 12;
const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;

const S = {
  presets: [],
  settings: null,
  activeId: null,
  globalHotkeys: false,
  hotkeyErrors: {},
  defaults: null,
  editing: false,
  drawer: null,          // {mode:'slot', index, draft} | {mode:'board'}
  triggers: new Array(SLOTS).fill(0),
  filesVersion: 0,
  dlRunning: false,
  hasKey: false,
  key: "",
  playingCount: 0,
};

/* ------------------------------------------------------------------ utils */
const MOD_ORDER = ["ctrl", "alt", "shift", "win"];
const KEY_LABELS = {
  Space: "Space", Backspace: "Bksp", Minus: "-", Equal: "=", BracketLeft: "[", BracketRight: "]",
  Semicolon: ";", Quote: "'", Backquote: "`", Backslash: "\\", Comma: ",", Period: ".", Slash: "/",
  PageUp: "PgUp", PageDown: "PgDn", ArrowLeft: "←", ArrowUp: "↑", ArrowRight: "→", ArrowDown: "↓",
  NumpadMultiply: "Num*", NumpadAdd: "Num+", NumpadSubtract: "Num-", NumpadDecimal: "Num.",
  NumpadDivide: "Num/", ScrollLock: "ScrLk", Delete: "Del", Insert: "Ins",
};
function keyLabel(code) {
  if (!code) return "—";
  if (KEY_LABELS[code]) return KEY_LABELS[code];
  if (code.startsWith("Digit")) return code.slice(5);
  if (code.startsWith("Key")) return code.slice(3);
  if (code.startsWith("Numpad")) return "Num" + code.slice(6);
  return code;
}
const modLabel = (m) => ({ ctrl: "Ctrl", alt: "Alt", shift: "Shift", win: "Win" }[m] || m);
function comboKbd(mods, code) {
  if (!code) return "";
  const ms = MOD_ORDER.filter((m) => mods.includes(m)).map(modLabel);
  return [...ms, keyLabel(code)].map((k) => `<kbd>${esc(k)}</kbd>`).join("");
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
let toastTimer;
function toast(msg, err = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (err ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast" + (err ? " err" : "")), 2600);
}
const active = () => S.presets.find((p) => p.id === S.activeId) || S.presets[0];
const hk = () => S.settings.hotkeys;
const REPEAT_ICON = { overlap: "⧉", restart: "↻", toggle: "⏻" };
const REPEAT_TEXT = { overlap: "Overlap", restart: "Restart", toggle: "Start / stop" };
const THEME_NAMES = { cyber: "Neon / Cyber", gothic: "Gothic / Blood", neutral: "Neutral" };

/* ------------------------------------------------------------------- boot */
async function boot() {
  const init = await api().get_init();
  S.presets = init.presets;
  S.settings = init.settings;
  S.activeId = init.settings.active_preset;
  S.globalHotkeys = init.global_hotkeys;
  S.hotkeyErrors = init.hotkey_errors || {};
  S.defaults = init.default_hotkeys;
  S.hasKey = init.has_freesound_key;
  S.key = init.freesound_key || "";
  S.web = !!init.web;
  renderAll();
  renderFaders();
  bindStatic();
  poll();
  const missing = S.presets.some((p) => p.is_starter && p.slots.some((s) => s && !s.exists));
  if (missing && !S.hasKey && !S.web) {
    setTimeout(() => toast("Starter sounds are not downloaded yet — open Settings → Starter sounds."), 600);
  }
}
if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener("pywebviewready", boot, { once: true });

/* ----------------------------------------------------------------- render */
function renderAll() {
  const p = active();
  document.body.dataset.theme = p.theme;
  document.body.classList.toggle("editing", S.editing);
  $("btnEdit").classList.toggle("on", S.editing);
  $("btnEdit").textContent = S.editing ? "Done" : "Edit";
  renderTabs();
  $("boardName").textContent = p.name;
  $("boardSub").textContent = p.subtitle || "";
  renderGrid();
  renderStatus();
  $("panicKey").textContent = hk().panic ? MOD_ORDER.filter((m) => hk().mods.includes(m)).map(modLabel).concat(keyLabel(hk().panic)).join(" + ") : "";
}

function renderTabs() {
  const html = S.presets.map((p) =>
    `<button class="tab ${p.id === S.activeId ? "active" : ""}" data-id="${esc(p.id)}" data-theme="${p.theme}"><span class="dot"></span>${esc(p.name)}</button>`
  ).join("") + (S.editing ? `<button class="tab add" id="tabAdd" title="New board">+ New board</button>` : "");
  $("tabs").innerHTML = html;
}

function renderGrid() {
  const p = active();
  const grid = $("grid");
  grid.innerHTML = "";
  p.slots.forEach((s, i) => {
    const el = document.createElement("button");
    el.className = "pad";
    el.dataset.i = i;
    el.draggable = S.editing;
    const keys = comboKbd(hk().mods, hk().slots[i]);
    if (!s) {
      el.classList.add("empty");
      el.innerHTML = `<div class="pad-name">${S.editing ? "+ Assign sound" : "—"}</div>
        <div class="keys" style="opacity:.5">${keys}</div>`;
    } else {
      if (!s.exists) el.classList.add("missing");
      el.innerHTML = `
        <div class="pad-top">
          <span class="pad-num">${String(i + 1).padStart(2, "0")}</span>
          <span class="badge ${s.type}">${s.type === "loop" ? "Loop" : "SFX"}</span>
          <span class="pad-count">×<b>1</b></span>
          <span class="pad-mode" title="${REPEAT_TEXT[s.repeat]}">${REPEAT_ICON[s.repeat]}</span>
        </div>
        <div class="pad-name">${esc(s.name)}</div>
        <div class="pad-foot"><div class="keys">${keys}</div><span class="pad-warn">no file</span></div>
        <div class="pad-progress"><i></i></div>`;
    }
    grid.appendChild(el);
  });
}

function renderStatus() {
  const pill = $("hkStatus");
  const errs = Object.keys(S.hotkeyErrors || {});
  if (!S.globalHotkeys) {
    pill.className = "pill";
    pill.textContent = S.web ? "Hotkeys: this tab" : "Hotkeys: window only";
    pill.title = S.web ? "In the browser, shortcuts work while this tab is open and focused."
                       : "Global hotkeys need Windows. Shortcuts work while this window is focused.";
  } else if (errs.length) {
    pill.className = "pill warn";
    pill.textContent = `${errs.length} hotkey conflict${errs.length > 1 ? "s" : ""}`;
    pill.title = "Some combos are taken by another program — open Settings to change them.";
  } else {
    pill.className = "pill ok";
    pill.textContent = "Global hotkeys on";
    pill.title = "Hotkeys work even when another program is focused.";
  }
}

function renderFaders() {
  const s = S.settings;
  const rows = [["master", "Master", s.master], ["sfx", "SFX", s.groups.sfx], ["ambient", "Ambient", s.groups.ambient]];
  $("faders").innerHTML = rows.map(([k, label, v]) => `
    <div class="fader"><label for="f_${k}">${label}</label>
      <input type="range" id="f_${k}" min="0" max="100" value="${Math.round(v * 100)}" data-k="${k}">
      <output id="o_${k}">${Math.round(v * 100)}</output></div>`).join("");
  $("faders").querySelectorAll("input").forEach((inp) => {
    paintRange(inp);
    inp.addEventListener("input", () => {
      paintRange(inp);
      $("o_" + inp.dataset.k).textContent = inp.value;
      const v = inp.value / 100;
      if (inp.dataset.k === "master") S.settings.master = v; else S.settings.groups[inp.dataset.k] = v;
      api().set_volume(inp.dataset.k, v);
    });
  });
}
function paintRange(inp) {
  const min = +inp.min || 0, max = +inp.max || 100;
  inp.style.setProperty("--p", ((inp.value - min) / (max - min)) * 100 + "%");
}

/* ------------------------------------------------------------- live state */
async function poll() {
  try {
    const st = await api().get_state();
    applyState(st);
  } catch (e) { /* window closing */ }
  setTimeout(poll, 120);
}

async function applyState(st) {
  if (st.files_version !== S.filesVersion) {
    const first = S.filesVersion === 0;
    S.filesVersion = st.files_version;
    if (!first) { S.presets = await api().get_presets(); renderAll(); }
  }
  if (st.active !== S.activeId) { S.activeId = st.active; renderAll(); }
  if (JSON.stringify(st.hotkey_errors) !== JSON.stringify(S.hotkeyErrors)) { S.hotkeyErrors = st.hotkey_errors; renderStatus(); }

  const pads = $("grid").children;
  let live = 0;
  for (let i = 0; i < pads.length; i++) {
    const pad = pads[i];
    const pl = st.playing[String(i)];
    pad.classList.toggle("playing", !!pl);
    pad.classList.toggle("multi", !!pl && pl.count > 1);
    const bar = pad.querySelector(".pad-progress i");
    if (bar) bar.style.width = pl ? (pl.progress * 100).toFixed(1) + "%" : "0";
    const cnt = pad.querySelector(".pad-count b");
    if (cnt && pl) cnt.textContent = pl.count;
    if (pl) live += pl.count;
    if (st.triggers[i] > S.triggers[i]) {
      pad.classList.remove("flash"); void pad.offsetWidth; pad.classList.add("flash");
    }
  }
  S.triggers = st.triggers.slice();
  const now = $("nowPlaying");
  now.textContent = live ? `▶ ${live} playing` : "silence";
  now.classList.toggle("live", live > 0);

  const pv = $("btnPreview");
  if (pv) pv.textContent = st.preview ? "■ Stop" : "▶ Preview";

  updateDownload(st.download);
}

/* ----------------------------------------------------------------- events */
function bindStatic() {
  $("tabs").addEventListener("click", async (e) => {
    const t = e.target.closest(".tab");
    if (!t) return;
    if (t.id === "tabAdd") return newBoard();
    if (t.dataset.id === S.activeId) return;
    await api().set_active(t.dataset.id);
    S.activeId = t.dataset.id;
    closeDrawer();
    renderAll();
  });

  const grid = $("grid");
  grid.addEventListener("click", (e) => {
    const pad = e.target.closest(".pad");
    if (!pad) return;
    const i = +pad.dataset.i;
    if (S.editing) return openSlotEditor(i);
    pressPad(i);
  });
  grid.addEventListener("contextmenu", (e) => {
    const pad = e.target.closest(".pad");
    if (!pad) return;
    e.preventDefault();
    openSlotEditor(+pad.dataset.i);
  });
  // drag to swap (edit mode)
  let dragFrom = null;
  grid.addEventListener("dragstart", (e) => {
    const pad = e.target.closest(".pad");
    if (!S.editing || !pad) return e.preventDefault();
    dragFrom = +pad.dataset.i;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(dragFrom));
  });
  grid.addEventListener("dragover", (e) => {
    const pad = e.target.closest(".pad");
    if (dragFrom === null || !pad) return;
    e.preventDefault();
    [...grid.children].forEach((c) => c.classList.toggle("drag-over", c === pad));
  });
  grid.addEventListener("dragleave", (e) => { if (e.target.classList) e.target.classList.remove("drag-over"); });
  grid.addEventListener("drop", async (e) => {
    const pad = e.target.closest(".pad");
    [...grid.children].forEach((c) => c.classList.remove("drag-over"));
    if (dragFrom === null || !pad) return;
    e.preventDefault();
    const to = +pad.dataset.i;
    const from = dragFrom;
    dragFrom = null;
    if (from === to) return;
    const r = await api().swap_slots(S.activeId, from, to);
    if (r.ok) { S.presets = r.presets; renderGrid(); }
  });
  grid.addEventListener("dragend", () => { dragFrom = null; });

  $("btnEdit").addEventListener("click", toggleEdit);
  $("btnSettings").addEventListener("click", openSettings);
  $("hkStatus").addEventListener("click", openSettings);
  $("btnBoardEdit").addEventListener("click", openBoardEditor);
  $("drawerClose").addEventListener("click", closeDrawer);
  $("modalClose").addEventListener("click", closeSettings);
  $("modal").addEventListener("mousedown", (e) => { if (e.target.id === "modal") closeSettings(); });
  $("btnPanic").addEventListener("click", panic);

  document.addEventListener("keydown", onKey);
}

async function pressPad(i) {
  const s = active().slots[i];
  if (!s) return;
  const r = await api().trigger(i);
  if (!r.ok && r.error && r.error !== "empty") toast(r.error, true);
}

async function panic() {
  await api().panic();
  const b = $("btnPanic");
  b.classList.add("hit");
  setTimeout(() => b.classList.remove("hit"), 250);
}

function toggleEdit() {
  S.editing = !S.editing;
  if (!S.editing) closeDrawer();
  renderAll();
}

let capturing = null; // hotkey capture callback
function onKey(e) {
  if (capturing) {
    e.preventDefault();
    if (["ControlLeft", "ControlRight", "AltLeft", "AltRight", "ShiftLeft", "ShiftRight", "MetaLeft", "MetaRight"].includes(e.code)) return;
    if (e.code === "Escape") return capturing(null);
    return capturing(e.code);
  }
  const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName);
  if (e.code === "Escape") {
    if ($("modal").classList.contains("open")) return closeSettings();
    if (S.drawer) return closeDrawer();
    if (S.editing) return toggleEdit();
    return;
  }
  // In-window fallback when global hotkeys are unavailable (non-Windows).
  if (!S.globalHotkeys && !typing) {
    const h = hk();
    const want = (m) => h.mods.includes(m);
    if (e.ctrlKey === want("ctrl") && e.altKey === want("alt") && e.shiftKey === want("shift") && e.metaKey === want("win")) {
      if (e.code === h.panic) { e.preventDefault(); return panic(); }
      const i = h.slots.indexOf(e.code);
      if (i >= 0) { e.preventDefault(); return pressPad(i); }
    }
  }
  if (!typing && !e.ctrlKey && !e.altKey && !e.metaKey && e.code === "KeyE" && !$("modal").classList.contains("open")) toggleEdit();
}

/* ------------------------------------------------------------ slot editor */
function openDrawer(title, html) {
  $("drawerTitle").textContent = title;
  $("drawerBody").innerHTML = html;
  $("drawer").classList.add("open");
  $("drawer").setAttribute("aria-hidden", "false");
}
function closeDrawer() {
  if (S.drawer && S.drawer.mode === "slot") api().stop_preview();
  S.drawer = null;
  if (S.presets.length) document.body.dataset.theme = active().theme; // undo live theme preview
  $("drawer").classList.remove("open");
  $("drawer").setAttribute("aria-hidden", "true");
}

function openSlotEditor(i) {
  const p = active();
  const src = p.slots[i];
  const d = src ? { ...src } : { name: "", file: "", filename: "", type: "sfx", volume: 0.85, repeat: "overlap", fade: 0, exists: false };
  S.drawer = { mode: "slot", index: i, draft: d };
  const isStarterFile = p.is_starter && (d.file || "").startsWith("sounds/starter/");
  openDrawer(`Slot ${String(i + 1).padStart(2, "0")} · ${keyLabel(hk().slots[i])}`, `
    <div class="field"><label>Name</label>
      <input class="input" id="eName" maxlength="40" placeholder="e.g. Rain on neon" value="${esc(d.name)}"></div>
    <div class="field"><label>Sound file</label>
      <div class="file-box ${d.file && !d.exists ? "bad" : ""}" id="eFile">${d.file ? esc(d.filename || d.file) + (d.exists ? "" : " — missing") : "no file"}</div>
      <div class="row" style="margin-top:8px">
        <button class="btn small" id="eBrowse">Choose file…</button>
        <button class="btn small" id="btnPreview" ${d.file ? "" : "disabled"}>▶ Preview</button>
        ${isStarterFile ? `<button class="btn small" id="eReroll" title="Get a different sound from Freesound">↻ Re-roll</button>` : ""}
      </div>
      <p class="hint">${S.web ? "OGG, WAV, MP3 or FLAC. The file is kept in this browser." : "OGG, WAV, MP3 or FLAC. Files from other folders are copied into <code>sounds/custom/</code>."}</p></div>
    <div class="field"><label>Type</label>
      <div class="seg" id="eType">
        <button data-v="sfx">SFX · one-shot</button><button data-v="loop">Loop · ambience</button></div></div>
    <div class="field"><label>When pressed again while playing</label>
      <div class="seg" id="eRepeat">
        <button data-v="overlap">Overlap</button><button data-v="restart">Restart</button><button data-v="toggle">Stop</button></div>
      <p class="hint" id="eRepeatHint"></p></div>
    <div class="field"><label>Volume <span id="eVolOut"></span></label>
      <input type="range" id="eVol" min="0" max="100" value="${Math.round(d.volume * 100)}"></div>
    <div class="field"><label>Fade in / out (ms)</label>
      <input class="input" id="eFade" type="number" min="0" max="10000" step="100" value="${d.fade}"></div>
    <div class="actions">
      <button class="btn primary" id="eSave">Save</button>
      <button class="btn" id="eCancel">Cancel</button>
      <span class="spacer"></span>
      ${src ? `<button class="btn danger" id="eClear">Clear slot</button>` : ""}
    </div>`);

  const seg = (id, key, after) => {
    const box = $(id);
    const paint = () => box.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === d[key]));
    box.addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      d[key] = b.dataset.v; if (after) after(); paint(); paintRepeat();
    });
    paint();
    return paint;
  };
  const paintRepeat = () => {
    $("eRepeatHint").textContent = {
      overlap: "Each press plays another copy on top — good for gunshots.",
      restart: "Starts the sound over from the beginning.",
      toggle: "Second press stops it (with fade) — good for ambience.",
    }[d.repeat];
  };
  let paintRep;
  seg("eType", "type", () => {
    if (d.type === "loop") { d.repeat = "toggle"; if (!+$("eFade").value) $("eFade").value = 1500; }
    else { d.repeat = "overlap"; $("eFade").value = 0; }
    paintRep && paintRep();
  });
  paintRep = seg("eRepeat", "repeat");
  paintRepeat();

  const vol = $("eVol");
  const paintVol = () => { paintRange(vol); $("eVolOut").textContent = vol.value + "%"; };
  vol.addEventListener("input", paintVol); paintVol();

  $("eBrowse").addEventListener("click", async () => {
    const r = await api().browse_file(S.activeId);
    if (!r.ok) { if (!r.cancelled) toast(r.error || "Could not use that file", true); return; }
    d.file = r.file; d.filename = r.filename; d.exists = true;
    if (!$("eName").value.trim()) $("eName").value = r.suggested_name;
    const fb = $("eFile"); fb.textContent = r.filename; fb.classList.remove("bad");
    $("btnPreview").disabled = false;
  });
  $("btnPreview").addEventListener("click", async () => {
    if ($("btnPreview").textContent.includes("Stop")) return api().stop_preview();
    const r = await api().preview(d.file, vol.value / 100, d.type);
    if (!r.ok) toast(r.error || "Cannot play", true);
  });
  if ($("eReroll")) $("eReroll").addEventListener("click", async () => {
    if (!S.key) { toast("Add your Freesound API key in Settings first.", true); return openSettings(); }
    const r = await api().start_download(null, true, S.activeId, i);
    if (!r.ok) return toast(r.error, true);
    toast("Looking for a different sound…");
    closeDrawer();
  });
  $("eSave").addEventListener("click", async () => {
    d.name = $("eName").value.trim() || d.filename.replace(/\.[^.]+$/, "") || "Untitled";
    d.volume = vol.value / 100;
    d.fade = Math.max(0, Math.min(10000, parseInt($("eFade").value || "0", 10)));
    if (!d.file) return toast("Choose a sound file first.", true);
    const r = await api().save_slot(S.activeId, i, d);
    if (!r.ok) return toast(r.error || "Could not save", true);
    S.presets = r.presets; renderGrid(); closeDrawer();
  });
  $("eCancel").addEventListener("click", closeDrawer);
  if ($("eClear")) $("eClear").addEventListener("click", async () => {
    const r = await api().save_slot(S.activeId, i, null);
    if (r.ok) { S.presets = r.presets; renderGrid(); closeDrawer(); }
  });
  setTimeout(() => $("eName").focus(), 50);
}

/* ----------------------------------------------------------- board editor */
function openBoardEditor() {
  const p = active();
  S.drawer = { mode: "board" };
  let theme = p.theme;
  openDrawer("Board settings", `
    <div class="field"><label>Board name</label><input class="input" id="bName" maxlength="32" value="${esc(p.name)}"></div>
    <div class="field"><label>Subtitle</label><input class="input" id="bSub" maxlength="60" value="${esc(p.subtitle)}" placeholder="e.g. Session 4 · the docks"></div>
    <div class="field"><label>Theme</label>
      <div class="themes" id="bThemes">${["cyber", "gothic", "neutral"].map((t) =>
        `<button class="theme-card" data-t="${t}"><div class="sw ${t}"></div><span>${THEME_NAMES[t]}</span></button>`).join("")}</div></div>
    <div class="actions">
      <button class="btn primary" id="bSave">Save</button>
      <button class="btn" id="bLeft" title="Move left">◀</button>
      <button class="btn" id="bRight" title="Move right">▶</button>
      <button class="btn" id="bDup">Duplicate</button>
      <span class="spacer"></span>
      <button class="btn danger" id="bDel">Delete</button>
    </div>
    <p class="hint">Switching boards stops all sound. Hotkeys ${comboKbd(hk().mods, hk().slots[0])} … always play slots 1–12 of the board that is open.</p>`);
  const paint = () => $("bThemes").querySelectorAll(".theme-card").forEach((c) => c.classList.toggle("on", c.dataset.t === theme));
  $("bThemes").addEventListener("click", (e) => {
    const c = e.target.closest(".theme-card"); if (!c) return;
    theme = c.dataset.t; paint(); document.body.dataset.theme = theme; // live preview
  });
  paint();
  $("bSave").addEventListener("click", async () => {
    const r = await api().update_preset(p.id, $("bName").value, $("bSub").value, theme);
    if (r.ok) { S.presets = r.presets; renderAll(); closeDrawer(); }
  });
  const move = async (dir) => { const r = await api().move_preset(p.id, dir); if (r.ok) { S.presets = r.presets; renderTabs(); } };
  $("bLeft").addEventListener("click", () => move(-1));
  $("bRight").addEventListener("click", () => move(1));
  $("bDup").addEventListener("click", async () => {
    const r = await api().duplicate_preset(p.id);
    if (r.ok) { S.presets = r.presets; S.activeId = r.id; renderAll(); openBoardEditor(); }
  });
  let armed = false;
  $("bDel").addEventListener("click", async () => {
    if (!armed) { armed = true; $("bDel").textContent = "Click again to delete"; return; }
    const r = await api().delete_preset(p.id);
    if (!r.ok) return toast(r.error || "Cannot delete", true);
    S.presets = r.presets; S.activeId = r.active; closeDrawer(); renderAll();
  });
}

async function newBoard() {
  const r = await api().create_preset("New board", active().theme, "");
  if (!r.ok) return;
  S.presets = r.presets; S.activeId = r.id;
  renderAll(); openBoardEditor();
  setTimeout(() => { $("bName").select(); }, 50);
}

/* --------------------------------------------------------------- settings */
let draftHk = null;
function openSettings() {
  closeDrawer();
  draftHk = JSON.parse(JSON.stringify(hk()));
  $("modalBody").innerHTML = `
    <div class="section">
      <div class="section-title">Hotkeys</div>
      <div class="field"><label>Modifier (held for every hotkey)</label>
        <div class="row" id="sMods">${MOD_ORDER.map((m) => `<button class="btn small" data-m="${m}">${modLabel(m)}</button>`).join("")}</div>
        <p class="hint">${S.globalHotkeys
          ? "Hotkeys are global: they work while Foundry, Roll20, Discord or a browser is focused."
          : S.web ? "In the browser, hotkeys work while this tab is open and focused."
          : "Global hotkeys need Windows — here they work only while this window is focused."}</p></div>
      <div class="field"><label>Slot keys — click a key, then press the new one</label>
        <div class="hk-grid" id="sSlots"></div></div>
      <div class="field"><label>Silence (stop everything)</label>
        <div class="row"><div class="hk-grid" style="grid-template-columns:repeat(1, 220px)" id="sPanic"></div>
        <span class="hint" style="margin:0 0 0 8px">Fade</span>
        <input class="input" id="sPanicFade" type="number" min="0" max="5000" step="100" style="width:90px" value="${S.settings.panic_fade ?? 700}">
        <span class="hint" style="margin:0">ms</span></div></div>
      <div class="errors" id="sErrors"></div>
      <div class="actions">
        <button class="btn primary" id="sApply">Apply hotkeys</button>
        <button class="btn" id="sReset">Reset to Ctrl+Alt+1…=</button>
      </div>
    </div>
    ${S.web ? `<div class="section">
      <div class="section-title">Storage</div>
      <p class="hint" style="margin:0 0 12px">Boards, settings and the sound files you add are saved in this browser only.
        Another browser or device starts with the default boards. Starter sounds are CC0.</p>
      <div class="row"><button class="btn small danger" id="sResetBoards">Reset all boards to default</button></div>
    </div>` : `<div class="section">
      <div class="section-title">Starter sounds · Freesound (CC0)</div>
      <p class="hint" style="margin:0 0 12px">The Night City and Elysium boards use free CC0 sounds from freesound.org.
        You need a free API key: <a id="sGetKey">create an account and get a key</a> (takes ~2 minutes), paste it below and press Download.</p>
      <div class="field"><label>Freesound API key</label>
        <div class="row"><input class="input grow" id="sKey" placeholder="paste your API key" value="${esc(S.key)}" spellcheck="false"></div></div>
      <div class="actions" style="margin-top:4px">
        <button class="btn primary" id="sDownload">Download missing sounds</button>
        <button class="btn" id="sReroll" title="Replace every starter sound with a different pick">Re-roll all</button>
      </div>
      <div class="progress"><i id="sProg"></i></div>
      <div class="hint" id="sCurrent"></div>
      <div class="log" id="sLog"></div>
    </div>
    <div class="section">
      <div class="section-title">Files</div>
      <div class="row"><button class="btn small" id="sFolder">Open sounds folder</button></div>
      <p class="hint">Boards are saved in <code>presets.json</code>, settings in <code>settings.json</code> next to the program. Copy the whole folder to move everything to another PC.</p>
    </div>`}`;
  paintHotkeys();
  $("sMods").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const m = b.dataset.m;
    draftHk.mods = draftHk.mods.includes(m) ? draftHk.mods.filter((x) => x !== m) : [...draftHk.mods, m];
    paintHotkeys();
  });
  $("sApply").addEventListener("click", applyHotkeys);
  $("sReset").addEventListener("click", () => { draftHk = JSON.parse(JSON.stringify(S.defaults)); paintHotkeys(); });
  $("sPanicFade").addEventListener("change", (e) => { const v = +e.target.value || 0; S.settings.panic_fade = v; api().set_panic_fade(v); });
  if (S.web) {
    let armed = false;
    $("sResetBoards").addEventListener("click", async () => {
      if (!armed) { armed = true; $("sResetBoards").textContent = "Click again — your boards will be replaced"; return; }
      const r = await api().reset_boards();
      S.presets = r.presets; S.activeId = r.active; closeSettings(); renderAll();
      toast("Boards reset to default.");
    });
  } else {
    $("sGetKey").addEventListener("click", () => api().open_url("https://freesound.org/apiv2/apply"));
    $("sKey").addEventListener("change", (e) => { S.key = e.target.value.trim(); api().set_freesound_key(S.key); });
    $("sDownload").addEventListener("click", () => startDownload(false));
    $("sReroll").addEventListener("click", () => startDownload(true));
    $("sFolder").addEventListener("click", () => api().open_sounds_folder());
  }
  $("modal").classList.add("open");
  $("modal").setAttribute("aria-hidden", "false");
}
function closeSettings() {
  capturing = null;
  $("modal").classList.remove("open");
  $("modal").setAttribute("aria-hidden", "true");
}

function paintHotkeys() {
  $("sMods").querySelectorAll("button").forEach((b) => b.classList.toggle("on", draftHk.mods.includes(b.dataset.m)));
  const modsTxt = MOD_ORDER.filter((m) => draftHk.mods.includes(m)).map(modLabel).join("+");
  const errs = S.hotkeyErrors || {};
  const cell = (label, code, action) => `
    <div class="hk ${errs[action] ? "err" : ""}" data-a="${action}" title="${esc(errs[action] || "")}">
      <small>${label}</small>
      <span><small>${esc(modsTxt)}${modsTxt ? "+" : ""}</small><button class="cap">${esc(keyLabel(code))}</button>
      <button class="x" title="Unassign">✕</button></span></div>`;
  $("sSlots").innerHTML = draftHk.slots.map((c, i) => cell(String(i + 1).padStart(2, "0"), c, "slot" + i)).join("");
  $("sPanic").innerHTML = cell("SILENCE", draftHk.panic, "panic");
  document.querySelectorAll("#sSlots .hk, #sPanic .hk").forEach((box) => {
    const a = box.dataset.a;
    const set = (code) => {
      if (a === "panic") draftHk.panic = code; else draftHk.slots[+a.slice(4)] = code;
    };
    box.querySelector(".cap").addEventListener("click", () => {
      document.querySelectorAll(".hk.listening").forEach((x) => x.classList.remove("listening"));
      box.classList.add("listening");
      box.querySelector(".cap").textContent = "press…";
      capturing = (code) => { capturing = null; if (code) set(code); paintHotkeys(); };
    });
    box.querySelector(".x").addEventListener("click", () => { set(""); paintHotkeys(); });
  });
  const list = Object.entries(errs).map(([a, e]) => `${a === "panic" ? "Silence" : "Slot " + (+a.slice(4) + 1)}: ${e}`);
  $("sErrors").innerHTML = list.length ? list.map(esc).join("<br>") : "";
}

async function applyHotkeys() {
  const r = await api().save_hotkeys(draftHk);
  if (!r.ok) { $("sErrors").textContent = r.error; return; }
  S.settings.hotkeys = r.hotkeys;
  S.hotkeyErrors = r.errors || {};
  paintHotkeys(); renderAll();
  toast(Object.keys(S.hotkeyErrors).length ? "Applied — some combos are taken by other programs." : "Hotkeys applied.", Object.keys(S.hotkeyErrors).length > 0);
}

async function startDownload(reroll) {
  const key = $("sKey").value.trim();
  if (!key) return toast("Paste your Freesound API key first.", true);
  S.key = key;
  const r = await api().start_download(key, reroll, null, null);
  if (!r.ok) toast(r.error, true);
}

function updateDownload(dl) {
  if (!dl) return;
  if (S.dlRunning && !dl.running) {
    toast(dl.error ? dl.error : "Starter sounds updated.", !!dl.error);
  }
  S.dlRunning = dl.running;
  const prog = $("sProg");
  if (!prog || S.web) return;
  prog.style.width = dl.total ? (dl.done / dl.total) * 100 + "%" : (dl.running ? "3%" : "0");
  $("sCurrent").textContent = dl.running ? `Downloading ${dl.done + 1}/${dl.total || "…"} — ${dl.current}` : (dl.error || "");
  const log = $("sLog");
  if (dl.log.length) {
    log.classList.add("show");
    const txt = dl.log.join("\n");
    if (log.textContent !== txt) { log.textContent = txt; log.scrollTop = log.scrollHeight; }
  }
  $("sDownload").disabled = dl.running;
  $("sReroll").disabled = dl.running;
}
