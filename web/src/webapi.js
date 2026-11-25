/* GM Soundboard — browser backend.
 * Implements the same API the desktop app exposes through pywebview, so the
 * UI (app.js) runs unchanged: Web Audio for sound, localStorage for boards and
 * settings, IndexedDB for sound files the user adds. */
"use strict";
(() => {
  const SLOTS = 12;
  const STARTER = /*STARTER_JSON*/[];
  const DEFAULT_HOTKEYS = {
    mods: ["ctrl", "alt"],
    slots: ["Digit1", "Digit2", "Digit3", "Digit4", "Digit5", "Digit6", "Digit7", "Digit8", "Digit9", "Digit0", "Minus", "Equal"],
    panic: "Space",
  };
  const DEFAULT_SETTINGS = {
    active_preset: "night-city", master: 0.9, groups: { sfx: 0.9, ambient: 0.75 },
    hotkeys: DEFAULT_HOTKEYS, panic_fade: 700,
  };
  const THEMES = ["cyber", "gothic", "neutral"];
  const LS_PRESETS = "gmsb.presets.v1";
  const LS_SETTINGS = "gmsb.settings.v1";
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const clamp01 = (v) => Math.max(0, Math.min(1, +v || 0));
  const curve = (x) => clamp01(x) ** 2;

  /* ------------------------------------------------------------ storage */
  function load(key, fallback) {
    try { const v = JSON.parse(localStorage.getItem(key)); return v ?? fallback; } catch { return fallback; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { console.warn("save failed", e); }
  }

  function cleanSlot(s) {
    if (!s || typeof s !== "object" || !s.file) return null;
    const type = s.type === "loop" ? "loop" : "sfx";
    const repeat = ["overlap", "restart", "toggle"].includes(s.repeat) ? s.repeat : (type === "loop" ? "toggle" : "overlap");
    return {
      name: String(s.name || "Untitled").slice(0, 40), file: String(s.file), type, repeat,
      volume: Math.round(clamp01(s.volume ?? 0.85) * 1000) / 1000,
      fade: Math.max(0, Math.min(10000, parseInt(s.fade || 0, 10) || 0)),
    };
  }
  function cleanPreset(p) {
    const slots = (p.slots || []).slice(0, SLOTS);
    while (slots.length < SLOTS) slots.push(null);
    return {
      id: String(p.id || Math.random().toString(16).slice(2, 10)),
      name: String(p.name || "New board").slice(0, 32), subtitle: String(p.subtitle || "").slice(0, 60),
      theme: THEMES.includes(p.theme) ? p.theme : "neutral", slots: slots.map(cleanSlot),
    };
  }
  function cleanHotkeys(h) {
    h = h || {};
    const mods = ["ctrl", "alt", "shift", "win"].filter((m) => (Array.isArray(h.mods) ? h.mods : DEFAULT_HOTKEYS.mods).includes(m));
    const slots = (h.slots || DEFAULT_HOTKEYS.slots).slice(0, SLOTS).map((x) => String(x || ""));
    while (slots.length < SLOTS) slots.push(DEFAULT_HOTKEYS.slots[slots.length]);
    return { mods, slots, panic: String(h.panic ?? DEFAULT_HOTKEYS.panic) };
  }

  let presets = (load(LS_PRESETS, null) || clone(STARTER)).map(cleanPreset);
  if (!presets.length) presets = clone(STARTER).map(cleanPreset);
  const stored = load(LS_SETTINGS, {}) || {};
  const settings = { ...clone(DEFAULT_SETTINGS), ...stored };
  settings.groups = { ...DEFAULT_SETTINGS.groups, ...(stored.groups || {}) };
  settings.hotkeys = cleanHotkeys(stored.hotkeys);
  if (!presets.some((p) => p.id === settings.active_preset)) settings.active_preset = presets[0].id;
  const savePresets = () => save(LS_PRESETS, presets);
  const saveSettings = () => save(LS_SETTINGS, settings);
  let settingsTimer;
  const saveSettingsLater = () => { clearTimeout(settingsTimer); settingsTimer = setTimeout(saveSettings, 500); };
  const getPreset = (id) => presets.find((p) => p.id === id);
  const activePreset = () => getPreset(settings.active_preset) || presets[0];

  /* ------------------------------------------------- IndexedDB for user files */
  const idb = new Promise((resolve) => {
    if (!("indexedDB" in window)) return resolve(null);
    const req = indexedDB.open("gmsb-files", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("files");
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => resolve(null);
  });
  const idbIds = new Set();
  const idbReady = idb.then((db) => new Promise((resolve) => {
    if (!db) return resolve();
    const r = db.transaction("files").objectStore("files").getAllKeys();
    r.onsuccess = () => { r.result.forEach((k) => idbIds.add(String(k))); resolve(); };
    r.onerror = () => resolve();
  }));
  async function idbPut(id, blob) {
    const db = await idb;
    if (!db) throw new Error("This browser cannot store files (IndexedDB is off).");
    await new Promise((res, rej) => {
      const tx = db.transaction("files", "readwrite");
      tx.objectStore("files").put(blob, id);
      tx.oncomplete = res; tx.onerror = () => rej(tx.error);
    });
    idbIds.add(id);
  }
  async function idbGet(id) {
    const db = await idb;
    if (!db) return null;
    return new Promise((res) => {
      const r = db.transaction("files").objectStore("files").get(id);
      r.onsuccess = () => res(r.result || null); r.onerror = () => res(null);
    });
  }
  const idbIdOf = (file) => (file || "").startsWith("idb:") ? file.slice(4).split("/")[0] : null;
  const fileExists = (file) => (idbIdOf(file) ? idbIds.has(idbIdOf(file)) : !!file);
  const baseName = (file) => (file || "").split("/").pop();

  /* --------------------------------------------------------- audio engine */
  const AC = window.AudioContext || window.webkitAudioContext;
  const ctx = new AC();
  const masterGain = ctx.createGain();
  masterGain.connect(ctx.destination);
  const groupGain = { sfx: ctx.createGain(), ambient: ctx.createGain() };
  Object.values(groupGain).forEach((g) => g.connect(masterGain));
  const setGain = (node, v) => node.gain.setTargetAtTime(v, ctx.currentTime, 0.03);
  masterGain.gain.value = curve(settings.master);
  groupGain.sfx.gain.value = curve(settings.groups.sfx);
  groupGain.ambient.gain.value = curve(settings.groups.ambient);
  const unlock = () => { if (ctx.state !== "running") ctx.resume(); };
  ["pointerdown", "keydown", "touchstart"].forEach((ev) => window.addEventListener(ev, unlock, { capture: true }));

  const buffers = new Map();
  function loadBuffer(file) {
    if (!buffers.has(file)) {
      const p = (async () => {
        let data;
        const id = idbIdOf(file);
        if (id) {
          const blob = await idbGet(id);
          if (!blob) throw new Error("File not found — pick it again in the editor.");
          data = await blob.arrayBuffer();
        } else {
          const r = await fetch(file);
          if (!r.ok) throw new Error("File not found: " + file);
          data = await r.arrayBuffer();
        }
        return await ctx.decodeAudioData(data);
      })();
      p.catch(() => buffers.delete(file));
      buffers.set(file, p);
    }
    return buffers.get(file);
  }
  function preloadActive() {
    const keep = new Set(activePreset().slots.filter(Boolean).map((s) => s.file));
    for (const f of [...buffers.keys()]) if (!keep.has(f)) buffers.delete(f);
    keep.forEach((f) => loadBuffer(f).catch(() => {}));
  }

  let voices = [];
  const activeVoices = (key) => voices.filter((v) => v.key === key && !v.stopping);
  function fadeOut(v, ms) {
    v.stopping = true;
    const now = ctx.currentTime;
    const g = v.gain.gain;
    g.cancelScheduledValues(now);
    g.setValueAtTime(g.value, now);
    g.linearRampToValueAtTime(0, now + Math.max(ms, 10) / 1000);
    try { v.src.stop(now + Math.max(ms, 10) / 1000 + 0.05); } catch { /* already stopped */ }
  }
  async function play(key, file, { group = "sfx", volume = 0.85, loop = false, repeat = "overlap", fade = 0 } = {}) {
    unlock();
    const cur = activeVoices(key);
    if (cur.length && repeat === "toggle") { cur.forEach((v) => fadeOut(v, fade)); return "stopped"; }
    if (cur.length && repeat === "restart") cur.forEach((v) => fadeOut(v, 15));
    const buf = await loadBuffer(file);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.loop = loop;
    const gain = ctx.createGain();
    const target = curve(volume);
    const now = ctx.currentTime;
    if (fade > 0) { gain.gain.setValueAtTime(0, now); gain.gain.linearRampToValueAtTime(target, now + fade / 1000); }
    else gain.gain.value = target;
    src.connect(gain).connect(groupGain[group] || groupGain.sfx);
    const v = { key, src, gain, loop, start: now, duration: buf.duration, stopping: false };
    src.onended = () => { voices = voices.filter((x) => x !== v); };
    voices.push(v);
    src.start();
    return "started";
  }
  const stopKey = (key, ms = 0) => voices.filter((v) => v.key === key).forEach((v) => fadeOut(v, ms));
  const stopAll = (ms = 0) => voices.forEach((v) => fadeOut(v, ms));

  /* ------------------------------------------------------------------- API */
  const triggers = new Array(SLOTS).fill(0);
  const keyOf = (i) => `${activePreset().id}:${i}`;
  const presetView = (p) => ({
    ...p, is_starter: false,
    slots: p.slots.map((s) => s && { ...s, exists: fileExists(s.file), filename: baseName(s.file) }),
  });
  const presetsView = () => presets.map(presetView);
  const ok = (extra = {}) => ({ ok: true, ...extra });
  const newId = (name) => {
    const base = (name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "board").slice(0, 20);
    let id = base, n = 2;
    while (getPreset(id)) id = `${base}-${n++}`;
    return id;
  };
  function setActive(id) {
    if (!getPreset(id)) return false;
    if (id !== settings.active_preset) {
      stopAll(300);
      settings.active_preset = id;
      saveSettings();
      preloadActive();
    }
    return true;
  }

  const api = {
    async get_init() {
      await idbReady;
      preloadActive();
      return {
        version: "1.0.0-web", web: true, presets: presetsView(), settings: clone(settings),
        has_freesound_key: false, freesound_key: "", global_hotkeys: false, hotkey_errors: {},
        default_hotkeys: DEFAULT_HOTKEYS, themes: THEMES,
      };
    },
    async get_presets() { return presetsView(); },
    async get_state() {
      const prefix = activePreset().id + ":";
      const playing = {};
      const now = ctx.currentTime;
      for (const v of voices) {
        if (v.stopping || !v.key.startsWith(prefix)) continue;
        const i = v.key.slice(prefix.length);
        const el = now - v.start;
        const prog = v.loop ? (el % v.duration) / v.duration : Math.min(1, el / v.duration);
        const e = playing[i] || (playing[i] = { progress: prog, count: 0, loop: v.loop });
        e.count++;
        e.progress = v.loop ? prog : Math.max(e.progress, prog);
      }
      return {
        active: activePreset().id, playing, preview: voices.some((v) => v.key === "preview" && !v.stopping),
        triggers: triggers.slice(), files_version: 1, hotkey_errors: {},
        download: { running: false, done: 0, total: 0, current: "", log: [], error: "" },
      };
    },
    async trigger(i) {
      const s = activePreset().slots[i];
      if (!s || !s.file) return { ok: false, error: "empty" };
      triggers[i]++;
      try {
        const result = await play(keyOf(i), s.file, {
          group: s.type === "loop" ? "ambient" : "sfx", volume: s.volume,
          loop: s.type === "loop", repeat: s.repeat, fade: s.fade,
        });
        return ok({ result });
      } catch (e) { return { ok: false, error: "Cannot play: " + (e.message || e) }; }
    },
    async stop_slot(i) { const s = activePreset().slots[i]; stopKey(keyOf(i), s ? s.fade : 0); return true; },
    async panic() { stopAll(+settings.panic_fade || 0); return true; },
    async set_volume(kind, value) {
      value = clamp01(value);
      if (kind === "master") { settings.master = value; setGain(masterGain, curve(value)); }
      else if (groupGain[kind]) { settings.groups[kind] = value; setGain(groupGain[kind], curve(value)); }
      saveSettingsLater();
      return true;
    },
    async preview(file, volume = 0.85) {
      stopKey("preview");
      try { await play("preview", file, { volume, repeat: "restart" }); return ok(); }
      catch (e) { return { ok: false, error: e.message || String(e) }; }
    },
    async stop_preview() { stopKey("preview", 150); return true; },
    async set_active(id) { return setActive(id); },
    async save_slot(pid, i, slot) {
      const p = getPreset(pid);
      if (!p) return { ok: false, error: "board not found" };
      const s = slot ? cleanSlot(slot) : null;
      p.slots[i] = s;
      savePresets();
      const key = `${pid}:${i}`;
      if (!s) stopKey(key, 200);
      else voices.filter((v) => v.key === key && !v.stopping).forEach((v) => v.gain.gain.setTargetAtTime(curve(s.volume), ctx.currentTime, 0.05));
      if (pid === activePreset().id) preloadActive();
      return ok({ presets: presetsView() });
    },
    async swap_slots(pid, a, b) {
      const p = getPreset(pid);
      if (!p) return { ok: false };
      [p.slots[a], p.slots[b]] = [p.slots[b], p.slots[a]];
      voices.filter((v) => v.key.startsWith(pid + ":")).forEach((v) => fadeOut(v, 200));
      savePresets();
      return ok({ presets: presetsView() });
    },
    async create_preset(name = "New board", theme = "neutral", subtitle = "") {
      const p = cleanPreset({ id: newId(name), name, theme, subtitle, slots: [] });
      presets.push(p); savePresets(); setActive(p.id);
      return ok({ id: p.id, presets: presetsView() });
    },
    async duplicate_preset(pid) {
      const src = getPreset(pid);
      if (!src) return { ok: false };
      const p = cleanPreset({ ...clone(src), id: newId(src.name + " copy"), name: (src.name + " copy").slice(0, 32) });
      presets.splice(presets.indexOf(src) + 1, 0, p); savePresets(); setActive(p.id);
      return ok({ id: p.id, presets: presetsView() });
    },
    async update_preset(pid, name, subtitle, theme) {
      const p = getPreset(pid);
      if (!p) return { ok: false };
      p.name = (String(name).trim() || p.name).slice(0, 32);
      p.subtitle = String(subtitle || "").slice(0, 60);
      if (THEMES.includes(theme)) p.theme = theme;
      savePresets();
      return ok({ presets: presetsView() });
    },
    async delete_preset(pid) {
      if (presets.length <= 1) return { ok: false, error: "Keep at least one board." };
      const p = getPreset(pid);
      if (!p) return { ok: false };
      const i = presets.indexOf(p);
      presets.splice(i, 1); savePresets();
      if (settings.active_preset === pid) setActive(presets[Math.max(0, i - 1)].id);
      return ok({ presets: presetsView(), active: activePreset().id });
    },
    async move_preset(pid, dir) {
      const p = getPreset(pid);
      if (!p) return { ok: false };
      const i = presets.indexOf(p), j = Math.max(0, Math.min(presets.length - 1, i + (dir > 0 ? 1 : -1)));
      [presets[i], presets[j]] = [presets[j], presets[i]]; savePresets();
      return ok({ presets: presetsView() });
    },
    browse_file() {
      // Must open the picker synchronously inside the click that called us.
      return new Promise((resolve) => {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "audio/*,.ogg,.wav,.mp3,.flac,.opus,.m4a";
        let done = false;
        const finish = (r) => { if (!done) { done = true; resolve(r); } };
        input.addEventListener("cancel", () => finish({ ok: false, cancelled: true }));
        input.addEventListener("change", async () => {
          const f = input.files && input.files[0];
          if (!f) return finish({ ok: false, cancelled: true });
          try {
            const id = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).replace(/[^a-z0-9-]/gi, "");
            await idbPut(id, f);
            const name = f.name.replace(/\//g, "_");
            const stem = name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
            finish(ok({ file: `idb:${id}/${name}`, filename: name, suggested_name: stem.slice(0, 40).replace(/\b\w/g, (c) => c.toUpperCase()) }));
          } catch (e) { finish({ ok: false, error: e.message || String(e) }); }
        });
        input.click();
      });
    },
    async open_url(url) { if (String(url).startsWith("https://")) window.open(url, "_blank", "noopener"); return true; },
    async open_sounds_folder() { return false; },
    async save_hotkeys(h) {
      h = cleanHotkeys(h);
      if (!h.mods.length) return { ok: false, error: "Pick at least one modifier so hotkeys do not trigger while you type." };
      const codes = [...h.slots, h.panic].filter(Boolean);
      const dups = [...new Set(codes.filter((c, i) => codes.indexOf(c) !== i))];
      if (dups.length) return { ok: false, error: "Same key used twice: " + dups.join(", ") };
      settings.hotkeys = h; saveSettings();
      return ok({ hotkeys: h, errors: {} });
    },
    async set_panic_fade(ms) { settings.panic_fade = Math.max(0, Math.min(5000, parseInt(ms, 10) || 0)); saveSettings(); return true; },
    async set_freesound_key() { return true; },
    async start_download() { return { ok: false, error: "Not available in the web version." }; },
    async reset_boards() {
      stopAll(200);
      presets = clone(STARTER).map(cleanPreset);
      settings.active_preset = presets[0].id;
      savePresets(); saveSettings(); preloadActive();
      return ok({ presets: presetsView(), active: settings.active_preset });
    },
  };

  window.pywebview = { api };
})();
