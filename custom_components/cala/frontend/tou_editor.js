/* Pure logic for the flat "rule list" TOU schedule editor. The user enters a
 * flat list of rules (season, days, from, to, rate); the nested canonical
 * touSchedule the firmware expects is derived, never hand-built. Kept DOM-free
 * so the card file is presentation only. Ported from the dashboard's
 * touRuleEditor.ts — keep the derivation semantics in sync. */

export const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
export const ALL_DAYS = [1, 1, 1, 1, 1, 1, 1];
export const WEEKDAYS = [1, 1, 1, 1, 1, 0, 0];

export const TOU_SCHEDULE_VERSION = 1;
export const MAX_SEASONS = 4;
export const MAX_DAY_SCHEDULES = 4;
export const MAX_PERIODS = 8;

/* ---------------- time parsing ---------------- */

// Forgiving free-text time parser: "4:30pm", "430p", "16:30", "9pm", "9" (24h),
// "24:00". Returns minutes past midnight (0..1440) or null.
export function parseTime(input) {
  if (input == null) return null;
  const s = String(input).trim().toLowerCase().replace(/\./g, "").replace(/\s+/g, "");
  if (!s) return null;
  const m = s.match(/^(\d{1,2})(?::?(\d{2}))?(am|pm|a|p)?$/);
  if (!m) return null;
  let hour = Number(m[1]);
  const minute = m[2] ? Number(m[2]) : 0;
  const meridiem = m[3];
  if (minute > 59) return null;
  if (meridiem) {
    if (hour < 1 || hour > 12) return null;
    if (meridiem[0] === "p" && hour !== 12) hour += 12;
    if (meridiem[0] === "a" && hour === 12) hour = 0;
  } else if (hour > 24 || (hour === 24 && minute > 0)) {
    return null;
  }
  return hour * 60 + minute;
}

// Renders minutes as canonical "h:mm AM/PM"; 1440 wraps to 12:00 AM.
export function formatTime12(minutes) {
  const wrapped = ((minutes % 1440) + 1440) % 1440;
  const hour = Math.floor(wrapped / 60);
  const minute = wrapped % 60;
  const suffix = hour < 12 ? "AM" : "PM";
  const hour12 = hour % 12 === 0 ? 12 : hour % 12;
  return `${hour12}:${String(minute).padStart(2, "0")} ${suffix}`;
}

// Renders a rate with the fewest decimals (min 2, max 4) that round-trip.
export function formatRate(value) {
  if (!isFinite(value)) return "";
  for (const digits of [2, 3]) {
    const s = value.toFixed(digits);
    if (Math.abs(parseFloat(s) - value) < 1e-9) return s;
  }
  return value.toFixed(4);
}

/* ---------------- rule helpers ---------------- */

// Concrete minute intervals for a rule; end "12:00 AM" means end of day (1440)
// and overnight ranges split into two segments. Null when unparseable.
export function ruleSegments(rule) {
  const startRaw = parseTime(rule.start);
  const endRaw = parseTime(rule.end);
  if (startRaw == null || endRaw == null) return null;
  const start = startRaw === 1440 ? 0 : startRaw;
  const end = endRaw === 0 ? 1440 : endRaw;
  if (start === end) return null;
  if (start < end) return [[start, end]];
  return [
    [start, 1440],
    [0, end],
  ];
}

// A rule participates in preview/payload/conflicts only when complete.
export function completeRule(rule) {
  return (
    ruleSegments(rule) != null &&
    !isNaN(parseFloat(rule.rate)) &&
    rule.days.some((v) => v)
  );
}

// Compact label for a Mon..Sun flag set, e.g. "Mon–Fri", "Mon, Wed–Fri".
export function daysLabel(set) {
  const idx = [];
  set.forEach((v, i) => {
    if (v) {
      idx.push(i);
    }
  });
  if (!idx.length) return "no days";
  const parts = [];
  let i = 0;
  while (i < idx.length) {
    let j = i;
    while (j + 1 < idx.length && idx[j + 1] === idx[j] + 1) {
      j++;
    }
    parts.push(j > i ? `${DAY_LABELS[idx[i]]}–${DAY_LABELS[idx[j]]}` : DAY_LABELS[idx[i]]);
    i = j + 1;
  }
  return parts.join(", ");
}

/* ---------------- season date math ---------------- */

const MONTH_LABELS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

const DAYS_IN_YEAR = 365; // fixed non-leap reference year

export function parseMonthDay(text) {
  const m = /^(\d{1,2})-(\d{1,2})$/.exec((text || "").trim());
  if (!m) return null;
  const mo = Number(m[1]);
  const d = Number(m[2]);
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  const date = new Date(2001, mo - 1, d);
  if (date.getMonth() !== mo - 1 || date.getDate() !== d) return null;
  return { mo, d };
}

export function padMonthDay(text) {
  const p = parseMonthDay(text);
  if (!p) return text;
  return `${String(p.mo).padStart(2, "0")}-${String(p.d).padStart(2, "0")}`;
}

function dayIndex(p) {
  const start = new Date(2001, 0, 1);
  return Math.round((new Date(2001, p.mo - 1, p.d).getTime() - start.getTime()) / 86400000);
}

function indexToMonthDay(index) {
  const date = new Date(2001, 0, 1 + (((index % DAYS_IN_YEAR) + DAYS_IN_YEAR) % DAYS_IN_YEAR));
  return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function monthDayLabel(text) {
  const p = parseMonthDay(text);
  return p ? `${MONTH_LABELS[p.mo - 1]} ${p.d}` : null;
}

export function rangeLabel(range) {
  return `${monthDayLabel(range.start)} – ${monthDayLabel(range.end)}`;
}

export function seasonDatesValid(season) {
  return parseMonthDay(season.start) != null && parseMonthDay(season.end) != null;
}

// Explicit complement of the union of the defined (valid) exception seasons:
// the firmware has no implicit "rest of year", so each uncovered run of the
// calendar becomes its own inclusive MM-DD range. Wrap-around is fine.
export function restOfYearRanges(seasons) {
  const covered = new Array(DAYS_IN_YEAR).fill(false);
  let any = false;
  for (const season of seasons) {
    const start = parseMonthDay(season.start);
    const end = parseMonthDay(season.end);
    if (!start || !end) continue;
    any = true;
    const a = dayIndex(start);
    const b = dayIndex(end);
    for (let i = a; ; i = (i + 1) % DAYS_IN_YEAR) {
      covered[i] = true;
      if (i === b) break;
    }
  }
  if (!any) return [{ start: "01-01", end: "12-31" }];
  if (covered.every((c) => c)) return [];

  const anchor = covered.findIndex((c) => c);
  const ranges = [];
  let runStart = null;
  for (let step = 1; step <= DAYS_IN_YEAR; step++) {
    const i = (anchor + step) % DAYS_IN_YEAR;
    if (!covered[i] && runStart == null) runStart = i;
    if (covered[i] && runStart != null) {
      ranges.push({
        start: indexToMonthDay(runStart),
        end: indexToMonthDay(i - 1),
      });
      runStart = null;
    }
  }
  ranges.sort((x, y) => (x.start < y.start ? -1 : 1));
  return ranges;
}

/* ---------------- contexts ---------------- */

// Every place a rule can apply: each defined season plus the automatic
// rest-of-year (or a single all-year context when seasons are disabled).
export function editorContexts(state) {
  if (!state.seasonsEnabled) {
    return [
      {
        key: "all",
        name: "All year",
        ranges: [{ start: "01-01", end: "12-31" }],
        rangeLabel: "Jan 1 – Dec 31",
      },
    ];
  }
  const contexts = state.seasons.map((season) => {
    const valid = seasonDatesValid(season);
    const range = valid
      ? { start: padMonthDay(season.start), end: padMonthDay(season.end) }
      : null;
    return {
      key: season.id,
      name: season.name,
      ranges: range ? [range] : [],
      rangeLabel: range ? rangeLabel(range) : "dates not set",
    };
  });
  const rest = restOfYearRanges(state.seasons);
  contexts.push({
    key: "rest",
    name: "Rest of year",
    ranges: rest,
    rangeLabel: rest.length ? rest.map(rangeLabel).join(", ") : "no remaining dates",
  });
  return contexts;
}

export function ruleAppliesTo(rule, contextKey) {
  return rule.season === "all" || rule.season === contextKey;
}

function applicableRules(state, contextKey) {
  return state.rules.filter((r) => completeRule(r) && ruleAppliesTo(r, contextKey));
}

/* ---------------- clipping (first rule wins) ---------------- */

function subtractIntervals(segment, covered) {
  let pieces = [segment];
  for (const [c0, c1] of covered) {
    const next = [];
    for (const [p0, p1] of pieces) {
      if (c1 <= p0 || c0 >= p1) {
        next.push([p0, p1]);
        continue;
      }
      if (c0 > p0) next.push([p0, c0]);
      if (c1 < p1) next.push([c1, p1]);
    }
    pieces = next;
  }
  return pieces;
}

// Per-day clipped periods for a context, Mon..Sun. Rules are applied in list
// order and each later rule is clipped against the union of earlier rules'
// segments, so the result never overlaps (earlier rule wins — same semantics
// as the preview). Contiguous equal-rate periods are merged.
export function dayPeriodsForContext(state, contextKey) {
  const rules = applicableRules(state, contextKey);
  return DAY_NAMES.map((_, day) => {
    const covered = [];
    const periods = [];
    for (const rule of rules) {
      if (!rule.days[day]) continue;
      const rate = parseFloat(rule.rate);
      for (const segment of ruleSegments(rule)) {
        for (const [startMin, endMin] of subtractIntervals(segment, covered)) {
          periods.push({ startMin, endMin, rate });
          covered.push([startMin, endMin]);
        }
      }
    }
    periods.sort((a, b) => a.startMin - b.startMin);
    const merged = [];
    for (const period of periods) {
      const last = merged[merged.length - 1];
      if (last && last.endMin === period.startMin && last.rate === period.rate) {
        last.endMin = period.endMin;
      } else {
        merged.push({ ...period });
      }
    }
    return merged;
  });
}

/* ---------------- conflicts (warnings, not errors) ---------------- */

export function findConflicts(state) {
  const conflicted = new Set();
  const messages = [];
  for (const ctx of editorContexts(state)) {
    const rules = applicableRules(state, ctx.key);
    for (let i = 0; i < rules.length; i++) {
      for (let j = i + 1; j < rules.length; j++) {
        const a = rules[i];
        const b = rules[j];
        const shareDay = a.days.some((v, d) => v && b.days[d]);
        if (!shareDay) continue;
        const overlap = ruleSegments(a).some(([a0, a1]) =>
          ruleSegments(b).some(([b0, b1]) => a0 < b1 && b0 < a1)
        );
        if (overlap) {
          conflicted.add(a.id);
          conflicted.add(b.id);
          messages.push(
            `${ctx.name}: “${a.start}–${a.end} $${parseFloat(a.rate).toFixed(2)}” ` +
              `overlaps “${b.start}–${b.end} $${parseFloat(b.rate).toFixed(2)}”`
          );
        }
      }
    }
  }
  return { conflicted, messages };
}

/* ---------------- preview pattern ---------------- */

// 96 15-minute slots for one day; value is the rate or null (default).
// Rasterized from the clipped periods so the preview matches the payload.
export function patternFromPeriods(periods) {
  const slots = new Array(96).fill(null);
  for (const period of periods) {
    const s0 = Math.floor(period.startMin / 15);
    const s1 = Math.ceil(period.endMin / 15);
    for (let s = s0; s < s1 && s < 96; s++) {
      if (slots[s] == null) slots[s] = period.rate;
    }
  }
  return slots;
}

/* ---------------- payload derivation ---------------- */

function groupDaySchedules(perDay) {
  const groups = [];
  perDay.forEach((periods, day) => {
    if (!periods.length) return;
    const key = JSON.stringify(periods);
    let group = groups.find((g) => g.key === key);
    if (!group) {
      group = { key, days: [], periods };
      groups.push(group);
    }
    group.days.push(DAY_NAMES[day]);
  });
  return groups.map((g) => ({
    days: g.days,
    periods: g.periods.map((p) => ({ ...p })),
  }));
}

// Derives the canonical wire schedule from the editor state. Rest-of-year
// becomes explicit complement ranges (one payload season per range); contexts
// with no applicable complete rules are omitted entirely.
export function deriveSchedule(state) {
  const seasons = [];
  const seasonNames = [];
  for (const ctx of editorContexts(state)) {
    if (!ctx.ranges.length) continue;
    const daySchedules = groupDaySchedules(dayPeriodsForContext(state, ctx.key));
    if (!daySchedules.length) continue;
    for (const range of ctx.ranges) {
      seasons.push({
        startDate: range.start,
        endDate: range.end,
        daySchedules: daySchedules.map((ds) => ({
          days: [...ds.days],
          periods: ds.periods.map((p) => ({ ...p })),
        })),
      });
      seasonNames.push(ctx.name);
    }
  }
  return {
    schedule: {
      version: TOU_SCHEDULE_VERSION,
      defaultRate: parseFloat(state.defaultRate),
      seasons,
    },
    seasonNames,
  };
}

/* ---------------- reverse derivation (prefill) ---------------- */

// Rebuilds editor state from a stored canonical schedule. A single all-year
// season (or none) maps to the season-less mode; otherwise each stored season
// becomes a defined season and its day schedules flatten to one rule per
// period.
export function reverseDerive(schedule) {
  const state = {
    defaultRate: formatRate(schedule.defaultRate),
    seasonsEnabled: false,
    seasons: [],
    rules: [],
  };
  let ruleSeq = 1;
  const pushRules = (daySchedules, seasonKey) => {
    for (const ds of daySchedules) {
      const set = DAY_NAMES.map((name) => (ds.days.includes(name) ? 1 : 0));
      for (const period of [...ds.periods].sort((a, b) => a.startMin - b.startMin)) {
        state.rules.push({
          id: `r${ruleSeq++}`,
          season: seasonKey,
          days: [...set],
          start: formatTime12(period.startMin),
          end: formatTime12(period.endMin === 1440 ? 0 : period.endMin),
          rate: formatRate(period.rate),
        });
      }
    }
  };
  const seasons = schedule.seasons || [];
  const allYear =
    seasons.length === 1 &&
    seasons[0].startDate === "01-01" &&
    seasons[0].endDate === "12-31";
  if (seasons.length === 0 || allYear) {
    if (seasons.length === 1) pushRules(seasons[0].daySchedules, "all");
  } else {
    state.seasonsEnabled = true;
    seasons.forEach((season, i) => {
      const id = `s${i + 1}`;
      state.seasons.push({
        id,
        name: `Season ${i + 1}`,
        start: season.startDate,
        end: season.endDate,
      });
      pushRules(season.daySchedules, id);
    });
  }
  return state;
}

/* ---------------- submit validation (plain language) ---------------- */

function seasonDaySet(season) {
  const start = parseMonthDay(season.startDate);
  const end = parseMonthDay(season.endDate);
  const days = new Set();
  const a = dayIndex(start);
  const b = dayIndex(end);
  for (let i = a; ; i = (i + 1) % DAYS_IN_YEAR) {
    days.add(i);
    if (i === b) break;
  }
  return days;
}

// Hard bounds the firmware enforces, phrased against what the user typed.
// Returns an error string or null.
export function validateSchedule(derived) {
  const { schedule, seasonNames } = derived;
  if (!isFinite(schedule.defaultRate) || schedule.defaultRate <= 0) {
    return "Enter a default rate greater than 0.";
  }
  if (schedule.seasons.length > MAX_SEASONS) {
    return (
      `The schedule expands to more than ${MAX_SEASONS} date ranges once ` +
      "rest-of-year is made explicit — remove or merge defined seasons."
    );
  }
  for (let i = 0; i < schedule.seasons.length; i++) {
    const name = seasonNames[i] || `season ${i + 1}`;
    const season = schedule.seasons[i];
    if (season.daySchedules.length > MAX_DAY_SCHEDULES) {
      return (
        `“${name}” needs more than ${MAX_DAY_SCHEDULES} distinct day patterns — ` +
        "merge some rules so more days share the same times."
      );
    }
    for (const ds of season.daySchedules) {
      if (ds.periods.length > MAX_PERIODS) {
        return (
          `“${name}” has more than ${MAX_PERIODS} rate periods for one day ` +
          "pattern — combine adjacent rules."
        );
      }
      for (const period of ds.periods) {
        if (!(period.rate > 0)) {
          return `“${name}” has a rate that is not greater than 0.`;
        }
      }
    }
  }
  const daySets = schedule.seasons.map(seasonDaySet);
  for (let i = 0; i < daySets.length; i++) {
    for (let j = i + 1; j < daySets.length; j++) {
      for (const day of daySets[i]) {
        if (daySets[j].has(day)) {
          return (
            `“${seasonNames[i]}” and “${seasonNames[j]}” have overlapping ` +
            "dates — adjust the season date ranges so they do not share days."
          );
        }
      }
    }
  }
  return null;
}

// Editor-level issues the bounds validator cannot see (warnings, not errors).
export function scheduleIssues(state) {
  const issues = [];
  if (!state.seasonsEnabled) return issues;
  for (const season of state.seasons) {
    const hasRules = state.rules.some((r) => completeRule(r) && r.season === season.id);
    if (!seasonDatesValid(season) && hasRules) {
      issues.push(
        `“${season.name}” has no valid dates (MM-DD) — its rules are left out until dates are set.`
      );
    }
    if (
      seasonDatesValid(season) &&
      !state.rules.some((r) => completeRule(r) && ruleAppliesTo(r, season.id))
    ) {
      issues.push(`“${season.name}” has no rules — those dates use the default rate only.`);
    }
  }
  const restEmpty = restOfYearRanges(state.seasons).length === 0;
  if (restEmpty && state.rules.some((r) => completeRule(r) && r.season === "rest")) {
    issues.push("Your seasons cover the whole year — “Rest of year” rules never apply.");
  }
  return issues;
}
