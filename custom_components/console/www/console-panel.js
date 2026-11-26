// The Console page in Home Assistant's sidebar.
// Three tabs: "Plan and usage", "What the house knows about you", and "Settings".
const CATEGORY_NAMES = { control: "Controlling things", status: "Questions about the house", customization: "Customizing", setup: "Setting up", troubleshooting: "Fixing problems", other: "Other" };
const ROUTE_NAMES = { local: "Answered at home (no cloud)", flash_fast: "Cloud agent, quick", flash: "Cloud agent", pro: "Cloud agent, stronger model", fallback: "Cloud agent unavailable", other_agent: "Another agent (Claude)" };
const AGENT_NAMES = { console: "Console", other_agents: "Other agents (Claude)" };
const STATE_NAMES = { ok: "Working", near_limit: "Working, allowance running low", over_limit: "Paused until next month", not_linked: "Not connected" };
const TABS = [["plan", "Plan and usage"], ["knows", "What the house knows about you"], ["settings", "Settings"]];

const STYLE = `
  :host { display: block; background: var(--primary-background-color); min-height: 100vh; color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  header { display: flex; align-items: center; height: 56px; padding: 0 16px; background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff); font-size: 20px; gap: 12px; }
  nav { display: flex; gap: 4px; padding: 0 12px; background: var(--app-header-background-color, var(--primary-color)); overflow-x: auto; }
  nav button { background: none; border: 0; border-bottom: 2px solid transparent; color: var(--app-header-text-color, #fff); opacity: .75; padding: 10px 12px; font: inherit; font-size: 14px; cursor: pointer; white-space: nowrap; }
  nav button.on { opacity: 1; border-color: currentColor; }
  main { max-width: 760px; margin: 0 auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
  section { background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px); border: 1px solid var(--divider-color); padding: 16px 20px; }
  h2 { font-size: 18px; font-weight: 500; margin: 0 0 10px; }
  p { margin: 6px 0; line-height: 22px; }
  .soft { color: var(--secondary-text-color); font-size: 14px; }
  .bar { height: 10px; border-radius: 5px; background: var(--divider-color); overflow: hidden; margin: 10px 0 6px; }
  .bar > div { height: 100%; background: var(--primary-color); }
  .bar.warn > div { background: var(--warning-color, #ffa600); }
  .bar.stop > div { background: var(--error-color, #db4437); }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  td { padding: 6px 0; border-top: 1px solid var(--divider-color); vertical-align: top; }
  td:last-child { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .note { padding: 10px 14px; border-radius: 10px; background: var(--secondary-background-color); font-size: 14px; line-height: 20px; }
  .note.on { background: color-mix(in srgb, var(--warning-color, #ffa600) 22%, transparent); }
  pre { white-space: pre-wrap; word-break: break-word; font-size: 12.5px; background: var(--secondary-background-color); padding: 12px; border-radius: 10px; margin: 8px 0 0; }
  button.act { font: inherit; font-size: 14px; padding: 7px 14px; border-radius: 18px; border: 1px solid var(--divider-color); background: none; color: var(--primary-color); cursor: pointer; }
  button.act.danger { color: var(--error-color, #db4437); border-color: var(--error-color, #db4437); }
  button.act[disabled] { opacity: .5; cursor: default; }
  textarea, input[type=text] { width: 100%; box-sizing: border-box; font: inherit; font-size: 14px; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
  textarea { min-height: 180px; font-family: ui-monospace, Menlo, monospace; font-size: 13px; }
  .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
  a { color: var(--primary-color); }
`;

const esc = (text) => String(text ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const day = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: "long", day: "numeric" }) : "");
const dayTime = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "");

class ConsolePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._status = null; this._knows = null; this._tab = "plan"; this._editing = null; this._said = "";
  }
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const sensor = hass.states["sensor.console_cloud_agent"];
    const key = sensor ? sensor.state + sensor.attributes.percent_used + (sensor.attributes.support || "") : "";
    if (first || key !== this._key) { this._key = key; this._load(); }
  }
  set narrow(value) { this._narrow = value; }
  set panel(value) { this._panel = value; }

  _ws(message) { return this._hass.callWS(message); }

  async _load() {
    try {
      this._status = await this._ws({ type: "console/status" });
      if (this._tab === "knows") this._knows = await this._ws({ type: "console/knows" });
    } catch (error) { this._status = { error: String(error.message || error) }; }
    this._draw();
  }

  _rows(names, counts) {
    return Object.entries(names).filter(([key]) => (counts || {})[key]).map(([key, name]) => `<tr><td>${name}</td><td>${counts[key]}</td></tr>`).join("") || `<tr><td class="soft">Nothing yet this month.</td><td></td></tr>`;
  }

  _plan(s) {
    const plan = s.plan || {}, usage = s.usage || {};
    const percent = Math.min(100, s.percent || 0);
    const kind = s.cloud_agent === "over_limit" ? "stop" : s.cloud_agent === "near_limit" ? "warn" : "";
    const more = plan.next ? `${esc(plan.next.name)} is ${esc(plan.next.price)}. To change plans, contact ${esc(plan.contact)}.` : `To change plans, contact ${esc(plan.contact)}.`;
    return `
      ${s.banner ? `<div class="note">${esc(s.banner.text)}</div>` : ""}
      <section>
        <h2>Your plan</h2>
        <p><b>${esc(plan.tier_name)}</b> · Console's cloud agent can use up to $${Number(plan.cap_usd).toFixed(2)} of AI a month.</p>
        <div class="bar ${kind}"><div style="width:${percent}%"></div></div>
        <p class="soft">${s.percent}% used this month ($${Number(usage.spend_usd || 0).toFixed(2)} of $${Number(plan.cap_usd).toFixed(2)}). Starts again on ${day(s.resets)}.</p>
        <p class="soft">${more}</p>
      </section>
      <section>
        <h2>Cloud agent</h2>
        <p>${STATE_NAMES[s.cloud_agent] || esc(s.cloud_agent)}</p>
        <p class="soft">When the cloud agent is paused or out of reach, your house still works: lights, routines and plain commands run at home, and Claude is unaffected.</p>
      </section>
      <section>
        <h2>This month</h2>
        <p class="soft">${usage.turns || 0} requests · ${usage.ok || 0} done · ${usage.failed || 0} not done</p>
        <table>${this._rows(CATEGORY_NAMES, usage.by_category)}</table>
        <h2 style="margin-top:16px">How they were answered</h2>
        <table>${this._rows(ROUTE_NAMES, usage.by_route)}</table>
        <h2 style="margin-top:16px">Who answered</h2>
        <table>${this._rows(AGENT_NAMES, usage.by_agent)}</table>
      </section>`;
  }

  _knowsTab(s) {
    const k = this._knows;
    if (!k) return `<section><p class="soft">Loading…</p></section>`;
    const admin = s.is_admin;
    if (this._editing) {
      const e = this._editing;
      return `<section><h2>${esc(e.name)}</h2>
        <p class="soft">A note the agents keep about this house. Change it and save, or delete it.</p>
        <textarea id="memtext" ${admin ? "" : "readonly"}>${esc(e.text)}</textarea>
        <div class="row">${admin ? `<button class="act" data-do="mem-save">Save</button><button class="act danger" data-do="mem-delete">Delete this note</button>` : ""}<button class="act" data-do="mem-close">Back</button></div>
        <p class="soft">${esc(this._said)}</p></section>`;
    }
    const memory = k.sunrise
      ? (k.memory.length ? `<table>${k.memory.map((m) => `<tr><td><a href="#" data-do="mem-open" data-name="${esc(m.name)}">${esc(m.name)}</a><div class="soft">${esc(m.first_line || "")}</div></td><td class="soft">${esc(String(m.modified || m.changed || "").slice(0, 10))}</td></tr>`).join("")}</table>` : `<p class="soft">Nothing remembered yet.</p>`)
      : `<p class="soft">Sunrise isn't installed, so there are no notes.</p>`;
    const presence = k.presence.length ? `<table>${k.presence.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.state === "home" ? "Home" : p.state === "not_home" ? "Away" : p.state)} · since ${dayTime(p.since)}</td></tr>`).join("")}</table>` : `<p class="soft">Home Assistant isn't tracking anyone's presence.</p>`;
    const learned = k.learned.length ? `<table>${k.learned.map((l) => `<tr><td>“${esc(l.sentence)}”<div class="soft">${esc(l.names || "")} · learned ${day(l.learned_at)} · used ${l.uses || 0} times</div></td><td>${admin ? `<button class="act" data-do="forget" data-id="${esc(l.id)}">Forget</button>` : ""}</td></tr>`).join("")}</table>` : `<p class="soft">None yet. When you ask for the same thing the same way three times, Console teaches it to Home Assistant so it runs at home.</p>`;
    return `
      <section><h2>Notes the agents keep</h2>
        <p class="soft">Sunrise's memory: what Console's agent and Claude have written down about this house and what you prefer. Kept on this box only. Open a note to read, change or delete it.</p>${memory}</section>
      <section><h2>Who's home</h2>
        <p class="soft">What Home Assistant thinks right now. To change who is tracked, or how: Settings → People.</p>${presence}
        <div class="row"><a href="/config/person">Open People</a></div></section>
      <section><h2>What you've asked</h2>
        <p class="soft">Console keeps nothing you say: a request leaves only a count (see the monthly summary below). Home Assistant itself holds the last few voice requests in memory for its own debug view, until it restarts. Right now it holds <b>${k.assist_runs}</b>.</p>
        ${admin ? `<div class="row"><button class="act" data-do="assist-clear" ${k.assist_runs ? "" : "disabled"}>Clear them now</button></div>` : ""}</section>
      <section><h2>Learned sentences</h2>
        <p class="soft">Phrasings this household says often, taught to Home Assistant's own agent so they run at home without the cloud.</p>${learned}</section>
      <section><h2>The monthly summary that is sent out</h2>
        <p class="soft">Once in a while Console sends this month's totals to Console's relay, and nothing else: no messages, no device names, no rooms, no times of day. This is exactly what is sent:</p>
        <pre>${esc(JSON.stringify(k.usage, null, 2))}</pre>
        <p class="soft">To erase these counts along with everything else Console keeps, use Settings → Erase Console and Sunrise data.</p></section>
      <p class="soft">${esc(this._said)}</p>`;
  }

  _settings(s) {
    const admin = s.is_admin;
    return `
      <section><h2>Home dashboard</h2>
        <p class="soft">Console builds the Home dashboard from your house: the chat, then lights, speakers and the rest of what you've exposed to Assist. It keeps it up to date until you edit it by hand.</p>
        <div class="row"><a href="${esc((s.dashboard || {}).url || "/console-home")}">Open Home</a>${admin ? `<button class="act" data-do="rebuild">Rebuild it from the house</button>` : ""}</div>
        <p class="soft">${esc(this._said)}</p></section>
      ${this._settingsExtra ? this._settingsExtra(s) : ""}`;
  }

  _draw() {
    const s = this._status;
    if (!s) return;
    const root = this.shadowRoot;
    if (s.error) { root.innerHTML = `<style>${STYLE}</style><header>Console</header><main><section><h2>Console didn't answer</h2><p class="soft">${esc(s.error)}</p></section></main>`; return; }
    const body = this._tab === "plan" ? this._plan(s) : this._tab === "knows" ? this._knowsTab(s) : this._settings(s);
    root.innerHTML = `<style>${STYLE}</style>
      <header>Console</header>
      <nav>${TABS.map(([key, name]) => `<button data-tab="${key}" class="${key === this._tab ? "on" : ""}">${name}</button>`).join("")}</nav>
      <main>${s.support && s.support.on ? `<div class="note on">Support mode is on until ${dayTime(s.support.until)}. Console's operator can open this house.</div>` : ""}${body}
        <p class="soft" style="text-align:center">Console ${esc(s.version)}${s.sunrise ? " · with Sunrise" : " · Sunrise isn't installed"}</p>
      </main>`;
    root.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => { this._tab = b.dataset.tab; this._said = ""; this._editing = null; this._load(); }));
    root.querySelectorAll("[data-do]").forEach((el) => el.addEventListener("click", (event) => { event.preventDefault(); this._do(el.dataset.do, el.dataset); }));
  }

  async _do(what, at) {
    try {
      if (what === "mem-open") { this._editing = await this._ws({ type: "console/memory/read", name: at.name }); this._said = ""; }
      else if (what === "mem-close") { this._editing = null; }
      else if (what === "mem-save") { await this._ws({ type: "console/memory/write", name: this._editing.name, text: this.shadowRoot.getElementById("memtext").value }); this._editing = null; this._said = "Saved."; }
      else if (what === "mem-delete") { if (!confirm(`Delete the note “${this._editing.name}”? It can be brought back from Sunrise's history.`)) return; await this._ws({ type: "console/memory/delete", name: this._editing.name }); this._editing = null; this._said = "Deleted."; }
      else if (what === "forget") { await this._ws({ type: "console/learned/forget", sentence_id: at.id }); this._said = "Forgotten. That sentence goes to the cloud agent again."; }
      else if (what === "assist-clear") { const r = await this._ws({ type: "console/assist/clear" }); this._said = `Cleared ${r.cleared}.`; }
      else if (what === "rebuild") { const r = await this._ws({ type: "console/dashboard/rebuild" }); this._said = r.ok ? `Home dashboard: ${r.did}.` : r.why; }
      else if (this._doExtra) { await this._doExtra(what, at); }
    } catch (error) { this._said = String(error.message || error); }
    await this._load();
  }
}

if (!customElements.get("console-panel")) customElements.define("console-panel", ConsolePanel);
window.ConsolePanel = ConsolePanel;
