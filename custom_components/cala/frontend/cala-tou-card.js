/* cala-tou-card — Lovelace card for entering a Cala TOU schedule as a flat
 * rule list (see tou_editor.js for all derivation logic). Served by the Cala
 * integration and auto-registered; add with:
 *   type: custom:cala-tou-card
 * The water heater is picked in the visual editor (or auto-detected when there
 * is only one); `device_id:` stays supported as a manual override.
 */

import {
  DAY_LABELS,
  WEEKDAYS,
  completeRule,
  daysLabel,
  deriveSchedule,
  editorContexts,
  findConflicts,
  formatRate,
  formatTime12,
  padMonthDay,
  parseTime,
  patternFromPeriods,
  dayPeriodsForContext,
  reverseDerive,
  scheduleIssues,
  validateSchedule,
} from "./tou_editor.js";

const RATE_COLORS = ["#f4623a", "#e9a13b", "#6fb3a4", "#8f7ff0", "#5aa9e6", "#e05c7e"];

const STYLE = `
  :host { display: block; }
  * { box-sizing: border-box; }
  .content { padding: 12px 16px 16px; color: var(--primary-text-color); font-size: 14px; }
  .sub { color: var(--secondary-text-color); font-size: 12.5px; margin: 2px 0 4px; }
  .panel { border: 1px solid var(--divider-color); border-radius: 10px; padding: 12px 14px; margin-top: 12px; }
  .panel h2 { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .8px;
              color: var(--secondary-text-color); margin: 0 0 10px; }
  input, select {
    background: var(--card-background-color); border: 1px solid var(--divider-color);
    border-radius: 6px; color: var(--primary-text-color); font: inherit; padding: 5px 8px; outline: none;
  }
  input:focus, select:focus { border-color: var(--primary-color); }
  input.bad { border-color: var(--error-color); color: var(--error-color); }
  .defline { display: flex; align-items: center; gap: 8px; }
  .defline .lbl { color: var(--secondary-text-color); }
  .defline input { width: 70px; text-align: right; }

  .seasonline label { display: flex; align-items: center; gap: 7px; cursor: pointer; }
  .seasonline input[type=checkbox] { accent-color: var(--primary-color); width: 15px; height: 15px; }
  .seasondefs { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
  .seasondef { display: flex; align-items: center; gap: 8px; color: var(--secondary-text-color); font-size: 13px; flex-wrap: wrap; }
  .seasondef input.nm { width: 110px; }
  .seasondef input.dt { width: 72px; text-align: center; }
  .seasondef .x { background: none; border: none; color: var(--secondary-text-color); cursor: pointer; font-size: 14px; padding: 2px 6px; }
  .seasondef .x:hover { color: var(--error-color); }
  .seasondef.rest { font-style: italic; }
  .addseason { background: none; border: none; color: var(--primary-color); font: inherit; font-size: 12.5px; cursor: pointer; align-self: flex-start; padding: 2px 0; }

  .rule { display: flex; align-items: center; gap: 6px; padding: 4px 0; flex-wrap: wrap; }
  .rule select.season { width: 118px; }
  .rule .chips { display: flex; gap: 3px; }
  .dchip { font-size: 11px; padding: 4px 6px; border-radius: 5px; cursor: pointer; user-select: none;
           background: var(--card-background-color); border: 1px solid var(--divider-color);
           color: var(--secondary-text-color); }
  .dchip.on { background: var(--primary-color); border-color: var(--primary-color);
              color: var(--text-primary-color, #fff); }
  .rule input.tm { width: 84px; text-align: center; }
  .rule .dash { color: var(--secondary-text-color); }
  .rule .ratewrap { position: relative; }
  .rule .ratewrap input { width: 80px; padding-left: 18px; text-align: right; }
  .rule .ratewrap::before { content: "$"; position: absolute; left: 7px; top: 6px;
                            color: var(--secondary-text-color); font-size: 13px; }
  .rule .warnic { color: var(--warning-color, #e0a83b); font-size: 15px; visibility: hidden; cursor: default; }
  .rule .warnic.on { visibility: visible; }
  .rule .del { background: none; border: none; color: var(--secondary-text-color); cursor: pointer; font-size: 15px; padding: 3px; }
  .rule .del:hover { color: var(--error-color); }
  .addrule { margin-top: 8px; background: none; border: 1.5px dashed var(--divider-color); border-radius: 7px;
             color: var(--secondary-text-color); font: inherit; padding: 7px 14px; cursor: pointer; }
  .addrule:hover { color: var(--primary-color); border-color: var(--primary-color); }
  .entry-hint { color: var(--secondary-text-color); font-size: 12px; margin-top: 8px; }
  .entry-hint .kbd { border: 1px solid var(--divider-color); border-radius: 4px; padding: 0 5px; font-size: 11px; }

  .warnbox { display: none; margin-top: 10px; padding: 8px 11px; border-radius: 7px; font-size: 12.5px;
             border: 1px solid var(--warning-color, #e0a83b); color: var(--warning-color, #e0a83b); }
  .warnbox.on { display: block; }

  .pv-season { margin-bottom: 14px; }
  .pv-title { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
  .pv-title .r { color: var(--secondary-text-color); font-weight: 400; }
  .pv-row { display: grid; grid-template-columns: 110px 1fr; gap: 8px; align-items: center; margin-bottom: 5px; }
  .pv-days { font-size: 12px; color: var(--secondary-text-color); text-align: right; }
  .pv-bar { display: flex; height: 20px; border-radius: 4px; overflow: hidden;
            background: var(--secondary-background-color); }
  .pv-seg { height: 100%; }
  .pv-ax { display: grid; grid-template-columns: 110px 1fr; gap: 8px; margin-top: 2px; }
  .pv-ax .lbls { position: relative; height: 14px; font-size: 10px; color: var(--secondary-text-color); }
  .pv-ax .lbls span { position: absolute; transform: translateX(-50%); }
  .legend { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 10px; font-size: 12px; color: var(--secondary-text-color); }
  .legend .it { display: flex; align-items: center; gap: 5px; }
  .legend .dot { width: 10px; height: 10px; border-radius: 3px; border: 1px solid var(--divider-color); }

  details { margin-top: 10px; }
  summary { color: var(--secondary-text-color); font-size: 12.5px; cursor: pointer; }
  pre { background: var(--secondary-background-color); border-radius: 8px; padding: 10px;
        font-size: 11.5px; overflow: auto; max-height: 280px; }

  .feedbanner { margin: 4px 0 0; padding: 10px 12px; border-radius: 8px; font-size: 13px;
                border: 1px solid var(--primary-color); color: var(--primary-text-color);
                background: color-mix(in srgb, var(--primary-color) 12%, transparent); }
  .editor.locked { opacity: .55; pointer-events: none; }
  .footer { display: flex; align-items: center; justify-content: flex-end; gap: 10px; margin-top: 14px; }
  .status { margin-right: auto; font-size: 12.5px; }
  .status.ok { color: var(--success-color, #4caf50); }
  .status.error { color: var(--error-color); }
  .btn { border-radius: 7px; padding: 8px 20px; font: inherit; font-weight: 600; cursor: pointer;
         border: 1px solid var(--divider-color); background: var(--card-background-color);
         color: var(--primary-text-color); }
  .btn.primary { background: var(--primary-color); border-color: var(--primary-color);
                 color: var(--text-primary-color, #fff); }
`;

function blankState() {
  return { defaultRate: "", seasonsEnabled: false, seasons: [], rules: [] };
}

/* ---------- device resolution ----------
   The card's config carries an HA device-registry id (`device`, what the
   picker writes), but `cala.set_tou_schedule` wants the Cala device id. The
   TOU schedule sensor already carries both — its `cala_tou_device` attribute
   is the Cala id — so every lookup hops through it. `device_id:` in the
   config bypasses the hop and is passed to the service verbatim. */

function calaIdForHaDevice(hass, haDeviceId) {
  if (!hass || !haDeviceId || !hass.entities) return null;
  for (const id in hass.entities) {
    if (hass.entities[id].device_id !== haDeviceId) continue;
    const st = hass.states[id];
    const cala = st && st.attributes && st.attributes.cala_tou_device;
    if (cala) return cala;
  }
  return null;
}

function haDeviceForCalaId(hass, calaId) {
  if (!hass || !calaId || !hass.entities) return null;
  for (const id in hass.entities) {
    const st = hass.states[id];
    if (st && st.attributes && st.attributes.cala_tou_device === calaId) {
      return hass.entities[id].device_id || null;
    }
  }
  return null;
}

/* The single Cala device, or null when there are none or several — with more
   than one unit the pick has to be deliberate. */
function detectTouDevice(hass) {
  if (!hass || !hass.states) return null;
  let found = null;
  for (const st of Object.values(hass.states)) {
    const cala = st.attributes && st.attributes.cala_tou_device;
    if (!cala || cala === found) continue;
    if (found) return null;
    found = cala;
  }
  return found;
}

/* ---------- config editor ---------- */

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

const TOU_EDITOR_SCHEMA = [
  { name: "device", selector: { device: { integration: "cala" } } },
  {
    type: "expandable",
    name: "",
    title: "Advanced",
    icon: "mdi:tune",
    schema: [{ name: "device_id", selector: { text: {} } }],
  },
];

const TOU_EDITOR_LABELS = {
  device: "Water heater",
  device_id: "Cala device id",
};

const TOU_EDITOR_HELPERS = {
  device: "Pick the Cala device. Leave empty to auto-detect when there is only one.",
  device_id: "Overrides the picker. Only needed when the device has no registry entry.",
};

class CalaTouCardEditor extends HTMLElement {
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
      this._form.computeLabel = (sc) => TOU_EDITOR_LABELS[sc.name] || sc.name;
      this._form.computeHelper = (sc) => TOU_EDITOR_HELPERS[sc.name] || "";
      this._form.addEventListener("value-changed", (ev) => this._valueChanged(ev));
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = TOU_EDITOR_SCHEMA;
    this._form.data = Object.assign({}, this._config);
  }

  _valueChanged(ev) {
    ev.stopPropagation();
    const config = Object.assign({}, this._config, ev.detail.value);
    for (const k of ["device", "device_id"]) {
      if (config[k] === "" || config[k] === null || config[k] === undefined) delete config[k];
    }
    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true })
    );
  }
}

if (!customElements.get("cala-tou-card-editor")) {
  customElements.define("cala-tou-card-editor", CalaTouCardEditor);
}

class CalaTouCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._state = blankState();
    this._seasonSeq = 1;
    this._ruleSeq = 1;
    this._prefilled = false;
    this._status = null;
    this._focusAfterRender = null;
  }

  static async getConfigElement() {
    /* Priming ha-form is best-effort. loadCardHelpers()/createCardElement()
       can stay pending on some HA builds, and awaiting that unguarded leaves
       the editor dialog spinning forever, so cap the wait and carry on. */
    await Promise.race([loadHaForm(), new Promise((r) => setTimeout(r, 2000))]);
    return document.createElement("cala-tou-card-editor");
  }

  static getStubConfig(hass) {
    const device = haDeviceForCalaId(hass, detectTouDevice(hass));
    return device
      ? { type: "custom:cala-tou-card", device: device }
      : { type: "custom:cala-tou-card" };
  }

  /* No device is a renderable state, not a fatal one: the card is added from
     the picker before anything is chosen, and a single-unit install resolves
     itself once the device has reported. */
  setConfig(config) {
    this._config = config || {};
    this._prefilled = false;
  }

  getCardSize() {
    return 10;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const feedEntity = this._feedActiveEntity();
    if (!this._prefilled) {
      this._prefill();
      this._prefilled = true;
      this._feedEntity = feedEntity;
      this._render();
      return;
    }
    // Reflect the feed becoming active/inactive while the card is open.
    if (feedEntity !== this._feedEntity) {
      this._feedEntity = feedEntity;
      this._render();
    }
  }

  // The entity_id of a price feed that currently owns the schedule, or null.
  // When set, the card is read-only (the feed wins over manual edits).
  _feedActiveEntity() {
    const entity = this._scheduleEntity();
    return (entity && entity.attributes.feed_active_entity) || null;
  }

  /* The Cala device id the service expects: an explicit override, the picked
     HA device, or the only unit there is. */
  _deviceId() {
    const c = this._config || {};
    if (c.device_id) return c.device_id;
    if (c.device) return calaIdForHaDevice(this._hass, c.device);
    return detectTouDevice(this._hass);
  }

  _scheduleEntity() {
    if (!this._hass) return null;
    const want = this._deviceId();
    if (!want) return null;
    for (const state of Object.values(this._hass.states)) {
      if (
        state.entity_id.startsWith("sensor.") &&
        state.attributes.cala_tou_device === want
      ) {
        return state;
      }
    }
    return null;
  }

  _prefill() {
    const entity = this._scheduleEntity();
    const schedule = entity && entity.attributes.schedule;
    if (schedule && typeof schedule === "object") {
      this._state = reverseDerive(schedule);
      this._seasonSeq = this._state.seasons.length + 1;
      this._ruleSeq = this._state.rules.length + 1;
    } else {
      this._state = blankState();
    }
  }

  /* ---------------- state mutations ---------------- */

  _addRuleAfter(prev) {
    const id = `r${this._ruleSeq++}`;
    const state = this._state;
    const rule = prev
      ? { id, season: prev.season, days: [...prev.days], start: "", end: "", rate: "" }
      : {
          id,
          season: state.seasonsEnabled
            ? (state.seasons[0] ? state.seasons[0].id : "rest")
            : "all",
          days: [...WEEKDAYS],
          start: "",
          end: "",
          rate: "",
        };
    const index = prev ? state.rules.indexOf(prev) + 1 : state.rules.length;
    state.rules.splice(index, 0, rule);
    this._focusAfterRender = { ruleId: id, field: "start" };
    this._render();
  }

  _removeSeason(season) {
    const state = this._state;
    state.seasons = state.seasons.filter((s) => s.id !== season.id);
    for (const rule of state.rules) {
      if (rule.season === season.id) {
        rule.season = state.seasons.length ? "rest" : "all";
      }
    }
    this._render();
  }

  _toggleSeasons(enabled) {
    const state = this._state;
    state.seasonsEnabled = enabled;
    if (!enabled) {
      for (const rule of state.rules) {
        rule.season = "all";
      }
    } else {
      for (const rule of state.rules) {
        if (rule.season === "all") {
          rule.season = state.seasons.length ? state.seasons[0].id : "rest";
        }
      }
    }
    this._render();
  }

  async _save() {
    this._status = null;
    const derived = deriveSchedule(this._state);
    const error = validateSchedule(derived);
    if (error) {
      this._status = { kind: "error", text: error };
      this._render();
      return;
    }
    try {
      await this._hass.callService("cala", "set_tou_schedule", {
        device_id: this._deviceId(),
        schedule: derived.schedule,
      });
      this._status = { kind: "ok", text: "Saved — schedule sent to the device." };
    } catch (err) {
      this._status = {
        kind: "error",
        text: (err && err.message) || "Sending the schedule failed.",
      };
    }
    this._render();
  }

  _cancel() {
    this._prefill();
    this._status = null;
    this._render();
  }

  /* ---------------- rendering ---------------- */

  _render() {
    const root = this.shadowRoot;
    if (!this._deviceId()) {
      root.innerHTML = `
      <style>${STYLE}</style>
      <ha-card header="Time-of-Use Schedule">
        <div class="content">
          <div class="sub">No Cala water heater selected. Pick one in the card editor.</div>
        </div>
      </ha-card>`;
      return;
    }
    const locked = !!this._feedEntity;
    const banner = locked
      ? `<div class="feedbanner">A price feed (<b>${this._feedEntity}</b>) is controlling
           this schedule. Remove it in the integration options to edit manually.</div>`
      : "";
    root.innerHTML = `
      <style>${STYLE}</style>
      <ha-card header="Time-of-Use Schedule">
        <div class="content">
          ${banner}
          <div class="editor${locked ? " locked" : ""}">
          <div class="sub">Type the schedule exactly as it reads on the rate sheet — one line
            per rule. Hours not covered by any rule use the default rate. The preview is
            read-only; use it to spot-check against the paper.</div>
          <div class="panel">
            <h2>Default rate</h2>
            <div class="defline">
              <span class="lbl">All hours not listed below:</span>
              <input id="defRate"><span class="lbl">$/kWh</span>
            </div>
          </div>
          <div class="panel">
            <h2>Seasons</h2>
            <div class="seasonline">
              <label><input type="checkbox" id="seasonToggle"> Rates change by season</label>
            </div>
            <div class="seasondefs" id="seasonDefs"></div>
          </div>
          <div class="panel">
            <h2>Time-of-use rules</h2>
            <div id="rules"></div>
            <button class="addrule" id="addRule">+ Add rule</button>
            <div class="entry-hint">Times accept anything you'd write down:
              <span class="kbd">4:30pm</span> <span class="kbd">430p</span>
              <span class="kbd">16:30</span> <span class="kbd">9pm</span>.
              Press <span class="kbd">Enter</span> in the rate field to start the next line
              with the same season &amp; days. Overnight ranges are fine.</div>
            <div class="warnbox" id="warnbox"></div>
          </div>
          <div class="panel">
            <h2>Preview — check against your rate sheet</h2>
            <div id="preview"></div>
            <details><summary>Payload</summary><pre id="payload"></pre></details>
          </div>
          </div>
          ${
            locked
              ? ""
              : `<div class="footer">
            <span class="status" id="status"></span>
            <button class="btn" id="cancel">Cancel</button>
            <button class="btn primary" id="save">Save to device</button>
          </div>`
          }
        </div>
      </ha-card>`;

    const state = this._state;
    const defRate = root.getElementById("defRate");
    defRate.value = state.defaultRate;
    defRate.addEventListener("focus", () => defRate.select());
    defRate.addEventListener("change", () => {
      const value = parseFloat(defRate.value);
      state.defaultRate = isNaN(value) ? defRate.value : formatRate(value);
      this._render();
    });

    const toggle = root.getElementById("seasonToggle");
    toggle.checked = state.seasonsEnabled;
    toggle.addEventListener("change", () => this._toggleSeasons(toggle.checked));

    this._renderSeasons();
    this._renderRules();
    this._renderDerived();

    root.getElementById("addRule").addEventListener("click", () =>
      this._addRuleAfter(state.rules[state.rules.length - 1] || null)
    );

    const cancel = root.getElementById("cancel");
    const save = root.getElementById("save");
    if (cancel) cancel.addEventListener("click", () => this._cancel());
    if (save) save.addEventListener("click", () => this._save());

    const status = root.getElementById("status");
    if (status && this._status) {
      status.textContent = this._status.text;
      status.className = `status ${this._status.kind}`;
    }

    if (this._focusAfterRender) {
      const row = root.querySelector(`[data-id="${this._focusAfterRender.ruleId}"]`);
      const input = row && row.querySelector(`[data-field="${this._focusAfterRender.field}"]`);
      if (input) input.focus();
      this._focusAfterRender = null;
    }
  }

  _renderSeasons() {
    const root = this.shadowRoot;
    const box = root.getElementById("seasonDefs");
    box.innerHTML = "";
    const state = this._state;
    if (!state.seasonsEnabled) return;

    for (const season of state.seasons) {
      const row = document.createElement("div");
      row.className = "seasondef";
      const name = document.createElement("input");
      name.className = "nm";
      name.value = season.name;
      name.addEventListener("change", () => {
        season.name = name.value || season.name;
        this._render();
      });
      const start = document.createElement("input");
      start.className = "dt";
      start.placeholder = "MM-DD";
      start.value = season.start;
      start.addEventListener("change", () => {
        season.start = padMonthDay(start.value);
        this._render();
      });
      const end = document.createElement("input");
      end.className = "dt";
      end.placeholder = "MM-DD";
      end.value = season.end;
      end.addEventListener("change", () => {
        season.end = padMonthDay(end.value);
        this._render();
      });
      const remove = document.createElement("button");
      remove.className = "x";
      remove.title = "Remove season";
      remove.textContent = "✕";
      remove.addEventListener("click", () => this._removeSeason(season));

      row.appendChild(name);
      row.appendChild(document.createTextNode("applies"));
      row.appendChild(start);
      row.appendChild(document.createTextNode("to"));
      row.appendChild(end);
      row.appendChild(remove);
      box.appendChild(row);
    }

    const restCtx = editorContexts(state).find((c) => c.key === "rest");
    const rest = document.createElement("div");
    rest.className = "seasondef rest";
    rest.textContent = `Rest of year (${restCtx ? restCtx.rangeLabel : ""}) — automatic, always covers everything else.`;
    box.appendChild(rest);

    const add = document.createElement("button");
    add.className = "addseason";
    add.textContent = "+ Add season";
    add.addEventListener("click", () => {
      this._seasonSeq += 1;
      state.seasons.push({
        id: `s${this._seasonSeq}`,
        name: `Season ${this._seasonSeq}`,
        start: "",
        end: "",
      });
      this._render();
    });
    box.appendChild(add);
  }

  _seasonOptions() {
    const state = this._state;
    if (!state.seasonsEnabled) return [["all", "All year"]];
    return [
      ...state.seasons.map((s) => [s.id, s.name]),
      ["rest", "Rest of year"],
      ["all", "All year"],
    ];
  }

  _renderRules() {
    const root = this.shadowRoot;
    const box = root.getElementById("rules");
    box.innerHTML = "";
    const state = this._state;

    for (const rule of state.rules) {
      const row = document.createElement("div");
      row.className = "rule";
      row.dataset.id = rule.id;

      if (state.seasonsEnabled) {
        const select = document.createElement("select");
        select.className = "season";
        for (const [value, label] of this._seasonOptions()) {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = label;
          if (rule.season === value) option.selected = true;
          select.appendChild(option);
        }
        select.addEventListener("change", () => {
          rule.season = select.value;
          this._render();
        });
        row.appendChild(select);
      }

      const chips = document.createElement("div");
      chips.className = "chips";
      DAY_LABELS.forEach((label, i) => {
        const chip = document.createElement("span");
        chip.className = "dchip" + (rule.days[i] ? " on" : "");
        chip.textContent = label;
        chip.addEventListener("click", () => {
          rule.days[i] = rule.days[i] ? 0 : 1;
          this._render();
        });
        chips.appendChild(chip);
      });
      row.appendChild(chips);

      const makeTime = (field, placeholder) => {
        const input = document.createElement("input");
        input.className = "tm";
        input.value = rule[field];
        input.placeholder = placeholder;
        input.dataset.field = field;
        input.addEventListener("focus", () => input.select());
        input.addEventListener("change", () => {
          const value = parseTime(input.value);
          input.classList.toggle("bad", input.value.trim() !== "" && value == null);
          if (value != null) input.value = formatTime12(value === 1440 ? 0 : value);
          rule[field] = input.value;
          this._renderDerived();
        });
        return input;
      };
      row.appendChild(makeTime("start", "4:30 PM"));
      const dash = document.createElement("span");
      dash.className = "dash";
      dash.textContent = "–";
      row.appendChild(dash);
      row.appendChild(makeTime("end", "9:00 PM"));

      const rateWrap = document.createElement("div");
      rateWrap.className = "ratewrap";
      const rate = document.createElement("input");
      rate.value = rule.rate;
      rate.placeholder = "0.00";
      rate.dataset.field = "rate";
      rate.addEventListener("focus", () => rate.select());
      rate.addEventListener("change", () => {
        const value = parseFloat(rate.value);
        rate.classList.toggle("bad", rate.value.trim() !== "" && isNaN(value));
        if (!isNaN(value)) rate.value = formatRate(value);
        rule.rate = rate.value;
        this._renderDerived();
      });
      rate.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          rate.dispatchEvent(new Event("change"));
          this._addRuleAfter(rule);
        }
      });
      rateWrap.appendChild(rate);
      row.appendChild(rateWrap);

      const warn = document.createElement("span");
      warn.className = "warnic";
      warn.textContent = "⚠";
      warn.title = "This rule overlaps another rule for the same season and days.";
      row.appendChild(warn);

      const del = document.createElement("button");
      del.className = "del";
      del.title = "Delete rule";
      del.textContent = "✕";
      del.addEventListener("click", () => {
        state.rules = state.rules.filter((r) => r.id !== rule.id);
        this._render();
      });
      row.appendChild(del);

      box.appendChild(row);
    }
  }

  _rateColorMap() {
    const prices = [
      ...new Set(
        this._state.rules.filter(completeRule).map((r) => parseFloat(r.rate))
      ),
    ].sort((a, b) => b - a);
    const map = new Map();
    prices.forEach((p, i) => map.set(p, RATE_COLORS[i % RATE_COLORS.length]));
    return map;
  }

  _renderDerived() {
    const root = this.shadowRoot;
    const state = this._state;
    const { conflicted, messages } = findConflicts(state);

    root.querySelectorAll(".rule").forEach((row) => {
      const warn = row.querySelector(".warnic");
      warn.classList.toggle("on", conflicted.has(row.dataset.id));
    });

    const warnbox = root.getElementById("warnbox");
    const issues = scheduleIssues(state);
    const lines = [];
    if (messages.length) {
      lines.push("⚠ Overlapping rules — the earlier rule wins where they overlap:");
      for (const message of messages) {
        lines.push(`· ${message}`);
      }
    }
    for (const issue of issues) {
      lines.push(`· ${issue}`);
    }
    warnbox.classList.toggle("on", lines.length > 0);
    warnbox.textContent = lines.join("\n");
    warnbox.style.whiteSpace = "pre-line";

    this._renderPreview();

    const derived = deriveSchedule(state);
    root.getElementById("payload").textContent = JSON.stringify(
      derived.schedule,
      null,
      2
    );
  }

  _renderPreview() {
    const root = this.shadowRoot;
    const el = root.getElementById("preview");
    el.innerHTML = "";
    const state = this._state;
    const colors = this._rateColorMap();
    const defaultRate = parseFloat(state.defaultRate);
    const money = (v) => `$${Number(v).toFixed(2)}`;

    for (const ctx of editorContexts(state)) {
      const section = document.createElement("div");
      section.className = "pv-season";
      const title = document.createElement("div");
      title.className = "pv-title";
      title.innerHTML = `${ctx.name} <span class="r">(${ctx.rangeLabel})</span>`;
      section.appendChild(title);

      const perDay = dayPeriodsForContext(state, ctx.key);
      const patterns = perDay.map(patternFromPeriods);
      const groups = [];
      for (let d = 0; d < 7; d++) {
        const key = patterns[d].join(",");
        let group = groups.find((g) => g.key === key);
        if (!group) {
          group = { key, days: [0, 0, 0, 0, 0, 0, 0], pattern: patterns[d] };
          groups.push(group);
        }
        group.days[d] = 1;
      }

      for (const group of groups) {
        const row = document.createElement("div");
        row.className = "pv-row";
        const label = document.createElement("div");
        label.className = "pv-days";
        label.textContent = daysLabel(group.days);
        row.appendChild(label);
        const bar = document.createElement("div");
        bar.className = "pv-bar";
        let i = 0;
        while (i < 96) {
          let j = i;
          while (j < 96 && group.pattern[j] === group.pattern[i]) {
            j++;
          }
          const seg = document.createElement("div");
          seg.className = "pv-seg";
          seg.style.width = `${((j - i) / 96) * 100}%`;
          if (group.pattern[i] != null) {
            seg.style.background = colors.get(group.pattern[i]) || "#888";
          }
          seg.title =
            `${formatTime12(i * 15)} – ${formatTime12(j * 15)}  ·  ` +
            (group.pattern[i] == null
              ? `Default ${isNaN(defaultRate) ? "—" : money(defaultRate)}`
              : money(group.pattern[i]));
          bar.appendChild(seg);
          i = j;
        }
        row.appendChild(bar);
        section.appendChild(row);
      }

      const axis = document.createElement("div");
      axis.className = "pv-ax";
      axis.innerHTML =
        '<div></div><div class="lbls">' +
        [[0, "12 AM"], [25, "6 AM"], [50, "12 PM"], [75, "6 PM"], [100, "12 AM"]]
          .map(([p, t]) => `<span style="left:${p}%">${t}</span>`)
          .join("") +
        "</div>";
      section.appendChild(axis);
      el.appendChild(section);
    }

    const legend = document.createElement("div");
    legend.className = "legend";
    const items = [
      `<span class="it"><span class="dot"></span>Default ${
        isNaN(defaultRate) ? "—" : money(defaultRate)
      }</span>`,
    ];
    for (const [price, color] of colors) {
      items.push(
        `<span class="it"><span class="dot" style="background:${color}"></span>${money(price)}</span>`
      );
    }
    legend.innerHTML = items.join("");
    el.appendChild(legend);
  }
}

customElements.define("cala-tou-card", CalaTouCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "cala-tou-card",
  name: "Cala TOU Schedule",
  description:
    "Enter a Time-of-Use rate schedule for a Cala water heater as a flat rule list.",
});
