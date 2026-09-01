/* cala-card — Lovelace card showing live Cala water-heater status as a cutaway
 * diagram, styled after the Cala app. Served by the Cala integration and
 * auto-registered; add with:
 *   type: custom:cala-card
 *   device: <home assistant device id>   # optional; auto-detected when omitted
 *
 * Written by Matt (@cecilkootz) and contributed in cala-systems/cala-home-assistant#23;
 * also published standalone as cecilkootz/homeassistant-cala-card.
 * Copyright (c) 2026 Matt (@cecilkootz). Licensed under the MIT License.
 */

const CARD_VERSION = "1.1.2";  /* keep in step with STATUS_CARD_VERSION in const.py */

/* sensor key -> entity_id suffix produced by the cala integration */
const SENSOR_SUFFIX = {
  ambient: "ambient_temperature",
  delivery: "delivery_temperature",
  top: "top_temperature",
  middle: "upper_temperature",
  bottom: "lower_temperature",
  compressor: "compressor_frequency",
  fan: "fan_on",
  fan_high: "fan_speed_high",
  upper_element: "upper_element_on",
  lower_element: "lower_element_on",
  boost: "boost_mode_on",
  available: "water_available",
  flow: "flow_rate",
  power: "power",
  connection: "connection",
};

/* Tank fill colour by temperature (°F): cool blue -> hot ember */
const RAMP = [
  [70, [162, 199, 216]],
  [95, [231, 195, 160]],
  [112, [244, 168, 108]],
  [128, [235, 122, 54]],
  [142, [216, 78, 24]],
  [158, [184, 46, 10]],
];

function rgbStr(c) {
  return "rgb(" + c[0] + "," + c[1] + "," + c[2] + ")";
}

function tempColor(f) {
  if (f === null || f === undefined || isNaN(f)) return "#cfc8bd";
  if (f <= RAMP[0][0]) return rgbStr(RAMP[0][1]);
  for (let i = 1; i < RAMP.length; i++) {
    if (f <= RAMP[i][0]) {
      const a = RAMP[i - 1], b = RAMP[i];
      const t = (f - a[0]) / (b[0] - a[0]);
      return rgbStr(a[1].map((v, j) => Math.round(v + (b[1][j] - v) * t)));
    }
  }
  return rgbStr(RAMP[RAMP.length - 1][1]);
}

/* Geometry of every callout slot, in the 920x900 diagram viewBox. */
const SLOTS = [
  { slot: "l1", side: "left",  x: 290, ly: 42,  vy: 80,  dot: [417, 111], inside: false, path: "M298 34 H 372 L 417 111" },
  { slot: "l2", side: "left",  x: 290, ly: 170, vy: 208, dot: [417, 145], inside: false, path: "M298 162 H 366 L 417 145" },
  { slot: "l3", side: "left",  x: 290, ly: 305, vy: 343, dot: [332, 232], inside: false, path: "M298 296 L 334 238" },
  { slot: "l4", side: "left",  x: 182, ly: 474, vy: 512, dot: [305, 553], inside: false, path: "M190 466 H 252 L 305 553" },
  { slot: "l5", side: "left",  x: 182, ly: 676, vy: 714, dot: [305, 753], inside: false, path: "M190 668 H 252 L 305 753" },
  { slot: "r1", side: "right", x: 706, ly: 111, vy: 149, dot: [566, 189], inside: false, path: "M698 103 H 640 L 566 189" },
  { slot: "r2", side: "right", x: 610, ly: 308, vy: 346, dot: [467, 325], inside: true,  path: "M602 300 H 548 Q 500 300 469 324" },
  { slot: "r3", side: "right", x: 648, ly: 431, vy: 469, dot: [566, 452], inside: true,  path: "M640 452 H 572" },
  { slot: "r4", side: "right", x: 613, ly: 537, vy: 575, dot: [463, 478], inside: true,  path: "M605 529 H 560 L 466 481" },
  { slot: "r5", side: "right", x: 648, ly: 641, vy: 679, dot: [566, 630], inside: true,  path: "M640 630 H 572" },
  { slot: "r6", side: "right", x: 610, ly: 747, vy: 785, dot: [463, 655], inside: true,  path: "M602 739 H 560 L 466 658" },
];

/* The Cala app shows ambient humidity and inlet temperature; the integration
   exposes neither, so those two slots carry power and flow instead. */
const DEFAULT_SLOTS = {
  l1: { key: "ambient",       label: "Amb. Temp",   fmt: "temp" },
  l2: { key: "power",         label: "Power",       fmt: "power" },
  l3: { key: "compressor",    label: "Comp. Speed", fmt: "hz" },
  l4: { key: "delivery",      label: "Delivery",    fmt: "temp" },
  l5: { key: "flow",          label: "Flow",        fmt: "flow" },
  r1: { key: "fan",           label: "Fan",         fmt: "onoff" },
  r2: { key: "top",           label: "Top Tank",    fmt: "temp" },
  r3: { key: "upper_element", label: "Upper Elem.", fmt: "onoff" },
  r4: { key: "middle",        label: "Middle Tank", fmt: "temp" },
  r5: { key: "lower_element", label: "Lower Elem.", fmt: "onoff" },
  r6: { key: "bottom",        label: "Bottom Tank", fmt: "temp" },
};

/* HA appends `_2`, `_3`, ... to the entity ids of a second device registered
   under the same name, so every id below may carry one. */
const DEDUPE_RE = /_\d+$/;
const TOP_RE = /^sensor\..*cala.*_top_temperature(?:_\d+)?$/;

function stripDedupe(id) {
  return id.replace(DEDUPE_RE, "");
}

/* First Cala top-temperature sensor that is actually reporting; a stale unit
   is only returned if nothing live is found. */
function detectTopSensor(hass) {
  if (!hass) return null;
  let stale = null;
  for (const id in hass.states) {
    if (!TOP_RE.test(id)) continue;
    const st = hass.states[id].state;
    if (st !== "unavailable" && st !== "unknown") return id;
    if (!stale) stale = id;
  }
  return stale;
}

function detectDevice(hass) {
  const id = detectTopSensor(hass);
  const entry = id && hass && hass.entities ? hass.entities[id] : null;
  return entry && entry.device_id ? entry.device_id : null;
}

/* Entity-ID stem, for installs with no device-registry entry to resolve against. */
function detectPrefix(hass) {
  const id = detectTopSensor(hass);
  const m = id && stripDedupe(id).match(/^sensor\.(.*)_top_temperature$/);
  return m ? m[1] : null;
}

function numState(st) {
  if (!st) return null;
  const v = parseFloat(st.state);
  return isNaN(v) ? null : v;
}

function fmtValue(kind, st) {
  if (!st || st.state === "unknown" || st.state === "unavailable") return "—";
  const u = st.attributes.unit_of_measurement || "";
  const v = parseFloat(st.state);
  switch (kind) {
    case "temp":  return isNaN(v) ? "—" : Math.round(v) + (u || "°");
    case "hz":    return isNaN(v) ? "—" : Math.round(v) + " " + (u || "Hz");
    case "power": return isNaN(v) ? "—" : (Math.abs(v) < 10 ? v.toFixed(2) : Math.round(v)) + " " + u;
    case "flow":  return isNaN(v) ? "—" : v.toFixed(1) + " " + (u === "gal/min" ? "gpm" : u);
    case "gal":   return isNaN(v) ? "—" : v.toFixed(1) + " " + u;
    case "onoff": return st.state === "on" ? "On" : st.state === "off" ? "Off" : st.state;
    default:      return st.state + (u ? " " + u : "");
  }
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ha-form and its selectors only exist once some card editor has pulled them
   in, so force the built-in entities-card editor to load first. */
let haFormPromise;
function loadHaForm() {
  if (customElements.get("ha-form") && customElements.get("ha-selector")) return Promise.resolve();
  if (!haFormPromise) {
    haFormPromise = (async () => {
      const helpers = window.loadCardHelpers ? await window.loadCardHelpers() : null;
      if (!helpers) return;
      const card = await helpers.createCardElement({ type: "entities", entities: [] });
      if (card && card.constructor && card.constructor.getConfigElement) {
        await card.constructor.getConfigElement();
      }
    })().catch(() => {});
  }
  return haFormPromise;
}

const EDITOR_SCHEMA = [
  { name: "device", selector: { device: { integration: "cala" } } },
  {
    type: "grid",
    name: "",
    schema: [
      { name: "show_history", selector: { boolean: {} } },
      { name: "history_hours", selector: { number: { min: 1, max: 168, mode: "box" } } },
    ],
  },
  {
    name: "dark_mode",
    selector: {
      select: {
        mode: "dropdown",
        options: [
          { value: "auto", label: "Follow the Home Assistant theme" },
          { value: "never", label: "Always use the light Cala palette" },
        ],
      },
    },
  },
  {
    type: "expandable",
    name: "",
    title: "Advanced",
    icon: "mdi:tune",
    schema: [{ name: "prefix", selector: { text: {} } }],
  },
];

const EDITOR_LABELS = {
  device: "Water heater",
  show_history: "Show history",
  history_hours: "History window (hours)",
  dark_mode: "Theme",
  prefix: "Entity ID prefix",
};

const EDITOR_HELPERS = {
  device: "Pick the Cala device. Leave empty to auto-detect the first one found.",
  prefix: "Only needed if you have no device registry entry, e.g. 1_car_garage_cala_water_heater.",
};

class CalaCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (sc) => EDITOR_LABELS[sc.name] || sc.name;
      this._form.computeHelper = (sc) => EDITOR_HELPERS[sc.name] || "";
      this._form.addEventListener("value-changed", (ev) => this._valueChanged(ev));
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = EDITOR_SCHEMA;
    this._form.data = Object.assign(
      { show_history: true, history_hours: 24, dark_mode: "auto" },
      this._config
    );
  }

  _valueChanged(ev) {
    ev.stopPropagation();
    /* spread over the existing config so keys the form does not manage
       (entities, callouts, grid_options) survive an edit */
    const config = Object.assign({}, this._config, ev.detail.value);
    for (const k of ["device", "prefix"]) {
      if (config[k] === "" || config[k] === null || config[k] === undefined) delete config[k];
    }
    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true })
    );
  }
}

if (!customElements.get("cala-card-editor")) customElements.define("cala-card-editor", CalaCardEditor);

const STYLE = `
:host { display: block; }
ha-card {
  --c-bg: #faf6ee; --c-ink: #0e3b3b; --c-ink2: #43696a; --c-line: #dd8a5c;
  --c-dot: #dd6b34; --c-shell: #ffffff; --c-metal: #b9bfc2; --c-metal-d: #2b2f31;
  --c-ring: rgba(224,86,31,.09); --c-accent: #e0561f; --c-soft: rgba(14,59,59,.10);
  --ha-card-background: var(--c-bg);
  display: block; background: var(--c-bg); color: var(--c-ink); overflow: hidden;
  padding: 10px 12px 16px;
}
:host(.dark) ha-card {
  --c-bg: #17191a; --c-ink: #eaeee9; --c-ink2: #9fb0ad; --c-line: #c4703f;
  --c-dot: #e2743a; --c-shell: #23262a; --c-metal: #737a7f; --c-metal-d: #101314;
  --c-ring: rgba(226,116,58,.12); --c-accent: #e2743a; --c-soft: rgba(234,238,233,.12);
}
:host(.off) ha-card { opacity: .55; }
header { display: grid; grid-template-columns: 40px 1fr 40px; align-items: center; }
.brand { text-align: center; line-height: 1.05; }
.logo {
  position: relative; display: inline-block; font-size: 30px; font-weight: 700;
  letter-spacing: -.5px; color: var(--c-ink);
  font-family: "Avenir Next","Nunito","Segoe UI",system-ui,sans-serif;
}
.logo i { position: absolute; right: -7px; top: 3px; width: 7px; height: 7px; border-radius: 50%; background: var(--c-accent); }
.updated { display: block; font-size: 12px; color: var(--c-ink2); margin-top: 2px; }
.iconbtn {
  background: none; border: 0; cursor: pointer; color: var(--c-accent);
  padding: 4px; justify-self: end; --mdc-icon-size: 22px;
}
.iconbtn[disabled] { opacity: .35; cursor: default; }
.status { justify-self: start; width: 9px; height: 9px; border-radius: 50%; background: #4caf50; margin-left: 6px; }
.status.bad { background: #d0342c; }
svg.diagram { display: block; width: 100%; height: auto; }
.ring { fill: none; stroke: var(--c-ring); stroke-width: 2; }
.rings.run .ring { animation: pulse 3.2s ease-in-out infinite; transform-origin: 460px 530px; }
.rings.run .ring:nth-child(2) { animation-delay: .4s; }
.rings.run .ring:nth-child(3) { animation-delay: .8s; }
.rings.run .ring:nth-child(4) { animation-delay: 1.2s; }
@keyframes pulse { 0%,100% { opacity: .5; transform: scale(1); } 50% { opacity: 1; transform: scale(1.03); } }
.pipe { fill: none; stroke: var(--c-metal); stroke-width: 15; stroke-linecap: round; stroke-linejoin: round; }
.shell { fill: var(--c-shell); stroke: var(--c-soft); stroke-width: 2; }
.gloss { fill: #fff; opacity: .09; }
.plinth { fill: var(--c-accent); }
.coil { fill: #d7dbdd; stroke: #aeb4b7; stroke-width: 2; }
.fins line { stroke: #9aa1a5; stroke-width: 2; }
.comp { fill: var(--c-metal-d); }
.tube { fill: none; stroke: var(--c-accent); stroke-width: 7; stroke-linecap: round; }
.fanbox { fill: var(--c-metal-d); }
.fanhub { fill: #3b4145; }
.fan path { fill: #cfd5d8; stroke: #3b4145; stroke-width: 1.5; }
.fan { transform-box: fill-box; transform-origin: center; }
.fan .anchor { fill: none; stroke: none; }
.fan.spin { animation: spin 1.6s linear infinite; }
.fan.spin.fast { animation-duration: .7s; }
@keyframes spin { to { transform: rotate(360deg); } }
.fancap { fill: #7d858a; }
.rod { stroke: #8b9296; stroke-width: 14; stroke-linecap: round; }
.rodcap { fill: #d5dadd; }
.elem.on { filter: url(#calaGlow); }
.elem.on .rod { stroke: #ffd08a; }
.elem.on .rodcap { fill: #fff3e0; }
.leader { fill: none; stroke: var(--c-line); stroke-width: 2.5; }
.dot { fill: var(--c-dot); }
.dot.inside { fill: #fff; stroke: var(--c-dot); stroke-width: 3; }
.lbl { font: 700 28px "Avenir Next","Nunito","Segoe UI",system-ui,sans-serif; fill: var(--c-ink); }
.val { font: 400 28px "Avenir Next","Nunito","Segoe UI",system-ui,sans-serif; fill: var(--c-ink2); }
.home { font: 700 26px "Avenir Next","Nunito","Segoe UI",system-ui,sans-serif; fill: var(--c-ink); letter-spacing: 2px; }
.callout { cursor: pointer; }
.callout:hover .lbl, .callout:hover .val { fill: var(--c-accent); }
.avail { text-align: center; margin: -4px 0 12px; cursor: pointer; }
.avail .num { font-size: 26px; font-weight: 700; color: var(--c-accent); }
.avail .unit { font-size: 15px; font-weight: 600; color: var(--c-accent); margin-left: 3px; }
.avail .cap { display: block; font-size: 12px; color: var(--c-ink2); letter-spacing: .3px; }
.boost {
  display: block; width: 100%; border: 0; border-radius: 999px; cursor: pointer;
  background: var(--c-accent); color: #fff; padding: 18px 0; font-size: 19px;
  font-weight: 600; letter-spacing: 1.2px;
  font-family: "Avenir Next","Nunito","Segoe UI",system-ui,sans-serif;
}
.boost:hover { filter: brightness(1.07); }
.boost:disabled { opacity: .5; cursor: default; }
.boost.active { background: #1d5b57; }
.boost.active::after { content: ""; }
.fc { margin-top: 20px; }
.fc-head { display: flex; align-items: center; gap: 12px; color: var(--c-ink); font-size: 14px; font-weight: 600; }
.fc-head::before, .fc-head::after { content: ""; flex: 1; height: 1px; background: var(--c-soft); }
.fc-sub { text-align: center; font-size: 12px; color: var(--c-ink2); margin-top: 4px; }
svg.chart { display: block; width: 100%; height: auto; margin-top: 6px; }
.chart .grid { stroke: var(--c-soft); stroke-width: 1; }
.chart .area { fill: var(--c-accent); opacity: .18; }
.chart .line { fill: none; stroke: var(--c-accent); stroke-width: 2.5; stroke-linejoin: round; stroke-linecap: round; }
.chart text { font: 400 11px system-ui,sans-serif; fill: var(--c-ink2); }
.chart .msg { font-size: 12px; }
`;

class CalaCard extends HTMLElement {
  static async getConfigElement() {
    /* Priming ha-form is best-effort. loadCardHelpers()/createCardElement()
       can stay pending on some HA builds, and awaiting that unguarded leaves
       the editor dialog spinning forever, so cap the wait and carry on. */
    await Promise.race([loadHaForm(), new Promise((r) => setTimeout(r, 2000))]);
    return document.createElement("cala-card-editor");
  }

  static getStubConfig(hass) {
    const device = detectDevice(hass);
    if (device) return { type: "custom:cala-card", device: device };
    return { type: "custom:cala-card", prefix: detectPrefix(hass) || "" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._built = false;
    this._sig = "";
    this._history = null;
    this._histAt = 0;
  }

  setConfig(config) {
    this._config = Object.assign({ show_history: true, history_hours: 24 }, config || {});
    this._slots = Object.assign({}, DEFAULT_SLOTS);
    const over = this._config.callouts;
    if (over) {
      for (const k in over) {
        if (!over[k]) delete this._slots[k];
        else this._slots[k] = Object.assign({}, DEFAULT_SLOTS[k], over[k]);
      }
    }
    this._showChart = this._config.show_history !== false;
    this._built = false;
    this._sig = "";
    this._entMap = null;
    this._entReg = undefined;
    this._histAt = 0;
    this.shadowRoot.innerHTML = "";
  }

  getCardSize() { return this._showChart ? 16 : 12; }
  getGridOptions() { return { columns: 12, rows: this._showChart ? 20 : 15, min_columns: 6 }; }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    if (!this._built) this._build();
    this._update();
    if (this._showChart) this._fetchHistory();
  }

  /* ---------- entities ---------- */

  _entities() {
    /* cached against the entity-registry object identity: resolving by device
       walks every entity, and _st() is called ~20x per update */
    const reg = this._hass.entities;
    if (this._entMap && this._entReg === reg) return this._entMap;
    this._entReg = reg;
    this._entMap = this._computeEntities(reg);
    return this._entMap;
  }

  _computeEntities(reg) {
    const c = this._config;
    const map = {};

    /* an explicit pick wins; otherwise resolve the device from the entity
       registry, which keeps a single-unit install zero-config */
    const device = c.device || (c.prefix ? null : detectDevice(this._hass));

    if (device && reg) {
      for (const id in reg) {
        if (reg[id].device_id !== device) continue;
        /* match the stem, not the raw id: a second unit carries HA's `_2`
           suffix on every entity. The device filter above already makes the
           stem unambiguous. */
        const stem = stripDedupe(id);
        if (id.slice(0, 7) === "sensor.") {
          for (const k in SENSOR_SUFFIX) {
            if (stem.endsWith("_" + SENSOR_SUFFIX[k])) map[k] = id;
          }
        } else if (id.slice(0, 7) === "button." && stem.endsWith("_start_24h_boost")) {
          map.boost_button = id;
        }
      }
    }

    /* Prefix is the escape hatch for installs with no device-registry entry.
       Deliberately not reached when a device was picked: falling through
       there would silently bind the card to whichever heater sorts first. */
    if (!map.top && !device) {
      const p = c.prefix;
      if (p) {
        for (const k in SENSOR_SUFFIX) map[k] = map[k] || "sensor." + p + "_" + SENSOR_SUFFIX[k];
        map.boost_button = map.boost_button || "button." + p + "_start_24h_boost";
      }
    }

    if (!map.top && !c.entities) {
      console.warn(
        "cala-card: no Cala entities resolved" +
          (c.device ? " for device " + c.device : "") +
          " — the card will render empty"
      );
    }

    const ov = c.entities || {};
    for (const k in ov) map[k] = ov[k];
    for (const k in SENSOR_SUFFIX) if (!map[k]) map[k] = null;
    return map;
  }

  _st(key) {
    const id = this._entities()[key];
    return id ? this._hass.states[id] : undefined;
  }

  /* ---------- markup ---------- */

  _svg() {
    const rings = [200, 285, 370, 455]
      .map((r) => '<circle class="ring" cx="460" cy="530" r="' + r + '"/>').join("");

    let fins = "";
    for (let x = 386; x <= 474; x += 7) fins += '<line x1="' + x + '" y1="161" x2="' + x + '" y2="251"/>';

    let blades = "";
    for (let i = 0; i < 5; i++) {
      blades += '<path d="M0 0 C 5 -17 21 -30 29 -18 C 25 -5 12 1 0 0 Z" transform="rotate(' + i * 72 + ')"/>';
    }

    const callouts = SLOTS.map((s) => {
      const cfg = this._slots[s.slot];
      if (!cfg) return "";
      const anchor = s.side === "left" ? "end" : "start";
      return (
        '<g class="callout" data-slot="' + s.slot + '">' +
        '<path class="leader" d="' + s.path + '"/>' +
        '<circle class="dot' + (s.inside ? " inside" : "") + '" cx="' + s.dot[0] + '" cy="' + s.dot[1] + '" r="9"/>' +
        '<text class="lbl" x="' + s.x + '" y="' + s.ly + '" text-anchor="' + anchor + '">' + esc(cfg.label) + "</text>" +
        '<text class="val" x="' + s.x + '" y="' + s.vy + '" text-anchor="' + anchor + '" data-val="' + s.slot + '">—</text>' +
        "</g>"
      );
    }).join("");

    return (
      '<svg class="diagram" viewBox="0 0 920 900" role="img" aria-label="Cala water heater status">' +
      "<defs>" +
      '<linearGradient id="calaTank" x1="0" y1="0" x2="0" y2="1">' +
      '<stop id="gs0" offset="0" stop-color="#e8622a"/>' +
      '<stop id="gs1" offset="0.5" stop-color="#ec7434"/>' +
      '<stop id="gs2" offset="1" stop-color="#f0a06a"/>' +
      "</linearGradient>" +
      '<filter id="calaGlow" x="-25%" y="-200%" width="150%" height="500%">' +
      '<feGaussianBlur stdDeviation="6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>' +
      "</filter>" +
      "</defs>" +
      '<g class="rings" id="rings">' + rings + "</g>" +
      '<g class="pipe"><path d="M305 345 H 364"/><path d="M305 345 V 753"/><path d="M305 753 H 386"/></g>' +
      '<rect class="shell" x="333" y="276" width="248" height="534" rx="18"/>' +
      '<path id="tank" fill="url(#calaTank)" d="M345 348 A112 40 0 0 1 569 348 L569 766 A24 24 0 0 1 545 790 L369 790 A24 24 0 0 1 345 766 Z"/>' +
      '<rect class="gloss" x="362" y="360" width="24" height="410" rx="12"/>' +
      '<g class="elem" id="elem-upper"><line class="rod" x1="452" y1="452" x2="566" y2="452"/><circle class="rodcap" cx="458" cy="452" r="10"/></g>' +
      '<g class="elem" id="elem-lower"><line class="rod" x1="452" y1="630" x2="566" y2="630"/><circle class="rodcap" cx="458" cy="630" r="10"/></g>' +
      '<rect class="plinth" x="322" y="256" width="270" height="28" rx="8"/>' +
      '<rect class="coil" x="380" y="156" width="98" height="100" rx="4"/>' +
      '<g class="fins">' + fins + "</g>" +
      '<rect class="comp" x="316" y="192" width="50" height="64" rx="12"/>' +
      '<path class="tube" d="M382 172 H 348 a13 13 0 0 0 0 26 H 382"/>' +
      '<path class="tube" d="M382 214 H 340 a13 13 0 0 0 0 26 H 382"/>' +
      '<rect class="fanbox" x="478" y="170" width="88" height="86" rx="8"/>' +
      '<circle class="fanhub" cx="522" cy="213" r="34"/>' +
      '<g transform="translate(522 213)"><g class="fan" id="fan"><circle class="anchor" cx="0" cy="0" r="30"/>' + blades + "</g></g>" +
      '<circle class="fancap" cx="522" cy="213" r="7"/>' +
      callouts +
      '<text class="home" x="460" y="856" text-anchor="middle">HOME</text>' +
      "</svg>"
    );
  }

  _build() {
    const root = this.shadowRoot;
    root.innerHTML =
      "<style>" + STYLE + "</style>" +
      "<ha-card>" +
      '<header><span class="status" id="status"></span>' +
      '<div class="brand"><span class="logo">Cala<i></i></span><span class="updated" id="updated"></span></div>' +
      '<button class="iconbtn" id="chartbtn" title="Toggle history"><ha-icon icon="mdi:chart-box-outline"></ha-icon></button>' +
      "</header>" +
      this._svg() +
      '<div class="avail" id="avail"><span class="num">—</span><span class="unit">gal</span>' +
      '<span class="cap">heated water available</span></div>' +
      '<button class="boost" id="boost">BOOST HEAT</button>' +
      '<div class="fc" id="fc" hidden>' +
      '<div class="fc-head">Available Heated Water</div>' +
      '<div class="fc-sub" id="fcsub"></div>' +
      '<svg class="chart" id="chart" viewBox="0 0 420 150"></svg>' +
      "</div>" +
      "</ha-card>";

    root.getElementById("boost").addEventListener("click", () => this._pressBoost());
    root.getElementById("chartbtn").addEventListener("click", () => {
      this._showChart = !this._showChart;
      root.getElementById("fc").hidden = !this._showChart;
      if (this._showChart) this._fetchHistory(true);
    });
    root.getElementById("avail").addEventListener("click", () => this._moreInfo(this._entities().available));
    root.querySelectorAll(".callout").forEach((g) => {
      g.addEventListener("click", () => {
        const cfg = this._slots[g.dataset.slot];
        if (cfg) this._moreInfo(this._entities()[cfg.key]);
      });
    });
    root.getElementById("fc").hidden = !this._showChart;
    this._built = true;
  }

  /* ---------- updates ---------- */

  _update() {
    const root = this.shadowRoot;
    const ents = this._entities();
    const hass = this._hass;

    let sig = "", latest = 0;
    for (const k in ents) {
      const s = ents[k] ? hass.states[ents[k]] : null;
      sig += s ? s.state + "|" : "-|";
      if (s) latest = Math.max(latest, new Date(s.last_updated).getTime());
    }
    root.getElementById("updated").textContent = latest
      ? "Updated " + new Date(latest).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      : "";
    if (sig === this._sig) return;
    this._sig = sig;

    const dark = !!(hass.themes && hass.themes.darkMode) && this._config.dark_mode !== "never";
    this.classList.toggle("dark", dark);

    for (const s of SLOTS) {
      const cfg = this._slots[s.slot];
      if (!cfg) continue;
      const node = root.querySelector('[data-val="' + s.slot + '"]');
      if (node) node.textContent = fmtValue(cfg.fmt, this._st(cfg.key));
    }

    /* tank gradient tracks the three probe temperatures */
    const top = numState(this._st("top"));
    const mid = numState(this._st("middle"));
    const bot = numState(this._st("bottom"));
    root.getElementById("gs0").setAttribute("stop-color", tempColor(top));
    root.getElementById("gs1").setAttribute("stop-color", tempColor(mid));
    root.getElementById("gs2").setAttribute("stop-color", tempColor(bot));

    const on = (k) => { const s = this._st(k); return !!s && s.state === "on"; };
    root.getElementById("elem-upper").classList.toggle("on", on("upper_element"));
    root.getElementById("elem-lower").classList.toggle("on", on("lower_element"));

    const fan = root.getElementById("fan");
    fan.classList.toggle("spin", on("fan"));
    fan.classList.toggle("fast", on("fan_high"));

    const hz = numState(this._st("compressor")) || 0;
    root.getElementById("rings").classList.toggle("run", hz > 0);

    const avail = this._st("available");
    const num = numState(avail);
    root.querySelector("#avail .num").textContent = num === null ? "—" : num.toFixed(1);
    root.querySelector("#avail .unit").textContent = (avail && avail.attributes.unit_of_measurement) || "gal";

    const conn = this._st("connection");
    const online = !conn || /^connected/i.test(conn.state);
    root.getElementById("status").classList.toggle("bad", !online);
    root.getElementById("status").title = conn ? conn.state : "";
    this.classList.toggle("off", !online);

    const boosting = on("boost");
    const btn = root.getElementById("boost");
    btn.textContent = boosting ? "BOOST ACTIVE" : "BOOST HEAT";
    btn.classList.toggle("active", boosting);
    btn.disabled = !ents.boost_button || !hass.states[ents.boost_button];

  }

  _moreInfo(entityId) {
    if (!entityId) return;
    const ev = new Event("hass-more-info", { bubbles: true, composed: true });
    ev.detail = { entityId };
    this.dispatchEvent(ev);
  }

  _pressBoost() {
    const id = this._entities().boost_button;
    if (id) this._hass.callService("button", "press", { entity_id: id });
  }

  /* ---------- history ---------- */

  async _fetchHistory(force) {
    const now = Date.now();
    if (!force && this._histAt && now - this._histAt < 300000) return;
    this._histAt = now;
    const id = this._entities().available;
    if (!id) return;
    const hours = Number(this._config.history_hours) || 24;
    const start = new Date(now - hours * 3600000).toISOString();
    try {
      const res = await this._hass.callApi(
        "GET",
        "history/period/" + start + "?filter_entity_id=" + id + "&minimal_response&no_attributes"
      );
      const rows = (res && res[0]) || [];
      this._history = rows
        .map((p) => [new Date(p.lu ? p.lu * 1000 : p.last_changed || p.last_updated).getTime(), parseFloat(p.state)])
        .filter((p) => !isNaN(p[1]) && !isNaN(p[0]));
    } catch (e) {
      this._history = null;
    }
    this._renderHistory();
  }

  _renderHistory() {
    const svg = this.shadowRoot.getElementById("chart");
    const sub = this.shadowRoot.getElementById("fcsub");
    if (!svg) return;
    const d = this._history;
    if (!d || d.length < 2) {
      svg.innerHTML = '<text class="msg" x="210" y="78" text-anchor="middle">No recorder history yet</text>';
      sub.textContent = "";
      return;
    }
    const X0 = 44, X1 = 412, Y0 = 12, Y1 = 122;
    const t0 = d[0][0], t1 = d[d.length - 1][0];
    let lo = Infinity, hi = -Infinity;
    for (const p of d) { if (p[1] < lo) lo = p[1]; if (p[1] > hi) hi = p[1]; }
    const step = Math.max(10, Math.ceil((hi - lo || 10) / 3 / 10) * 10);
    lo = Math.max(0, Math.floor(lo / step) * step - (hi === lo ? step : 0));
    hi = Math.ceil(hi / step) * step;
    if (hi === lo) hi = lo + step;

    const px = (t) => X0 + ((t - t0) / (t1 - t0 || 1)) * (X1 - X0);
    const py = (v) => Y1 - ((v - lo) / (hi - lo)) * (Y1 - Y0);

    let line = "";
    d.forEach((p, i) => { line += (i ? "L" : "M") + px(p[0]).toFixed(1) + " " + py(p[1]).toFixed(1) + " "; });
    const area = "M" + X0 + " " + Y1 + " " + line.replace(/^M/, "L") + "L" + X1.toFixed(1) + " " + Y1 + " Z";

    let grid = "";
    for (let v = lo; v <= hi + 0.001; v += step) {
      const y = py(v);
      grid += '<line class="grid" x1="' + X0 + '" y1="' + y.toFixed(1) + '" x2="' + X1 + '" y2="' + y.toFixed(1) + '"/>';
      grid += '<text x="' + (X0 - 6) + '" y="' + (y + 4).toFixed(1) + '" text-anchor="end">' + v + " gal</text>";
    }
    const tf = (t) => new Date(t).toLocaleTimeString([], { hour: "numeric" });
    svg.innerHTML =
      grid +
      '<path class="area" d="' + area + '"/>' +
      '<path class="line" d="' + line.trim() + '"/>' +
      '<text x="' + X0 + '" y="140">' + tf(t0) + "</text>" +
      '<text x="' + X1 + '" y="140" text-anchor="end">' + tf(t1) + "</text>";
    sub.textContent = "Last " + (Number(this._config.history_hours) || 24) + " hours";
  }
}

if (!customElements.get("cala-card")) customElements.define("cala-card", CalaCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "cala-card",
  name: "Cala Water Heater",
  description: "Cutaway diagram of a Cala heat-pump water heater, styled after the Cala app.",
  preview: true,
});

console.info("%c CALA-CARD %c v" + CARD_VERSION + " ", "background:#e0561f;color:#fff;border-radius:3px 0 0 3px", "background:#0e3b3b;color:#fff;border-radius:0 3px 3px 0");
