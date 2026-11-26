// The Console page in Home Assistant's sidebar: the plan, this month's usage, and what's sent out.
const CATEGORY_NAMES = { control: "Controlling things", status: "Questions about the house", customization: "Customizing", setup: "Setting up", troubleshooting: "Fixing problems", other: "Other" };
const ROUTE_NAMES = { local: "Answered at home (no cloud)", flash_fast: "Cloud agent, quick", flash: "Cloud agent", pro: "Cloud agent, stronger model", fallback: "Cloud agent unavailable" };
const STATE_NAMES = { ok: "Working", near_limit: "Working, allowance running low", over_limit: "Paused until next month", not_linked: "Not connected" };

const STYLE = `
  :host { display: block; background: var(--primary-background-color); min-height: 100vh; color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  header { display: flex; align-items: center; height: 56px; padding: 0 16px; background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff); font-size: 20px; gap: 12px; }
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
  td { padding: 6px 0; border-top: 1px solid var(--divider-color); }
  td:last-child { text-align: right; font-variant-numeric: tabular-nums; }
  .note { padding: 10px 14px; border-radius: 10px; background: var(--secondary-background-color); font-size: 14px; line-height: 20px; }
  pre { white-space: pre-wrap; word-break: break-word; font-size: 12.5px; background: var(--secondary-background-color); padding: 12px; border-radius: 10px; margin: 8px 0 0; }
`;

class ConsolePanel extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._status = null; }
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const sensor = hass.states["sensor.console_cloud_agent"];
    const key = sensor ? sensor.state + sensor.attributes.percent_used : "";
    if (first || key !== this._key) { this._key = key; this._load(); }
  }
  set narrow(value) { this._narrow = value; }
  set panel(value) { this._panel = value; }

  async _load() {
    try { this._status = await this._hass.callWS({ type: "console/status" }); } catch (error) { this._status = { error: String(error.message || error) }; }
    this._draw();
  }

  _rows(names, counts) {
    return Object.entries(names).filter(([key]) => (counts || {})[key]).map(([key, name]) => `<tr><td>${name}</td><td>${counts[key]}</td></tr>`).join("") || `<tr><td class="soft">Nothing yet this month.</td><td></td></tr>`;
  }

  _draw() {
    const s = this._status;
    if (!s) return;
    if (s.error) { this.shadowRoot.innerHTML = `<style>${STYLE}</style><header>Console</header><main><section><h2>Console didn't answer</h2><p class="soft">${s.error}</p></section></main>`; return; }
    const plan = s.plan || {}, usage = s.usage || {};
    const percent = Math.min(100, s.percent || 0);
    const kind = s.cloud_agent === "over_limit" ? "stop" : s.cloud_agent === "near_limit" ? "warn" : "";
    const resets = new Date(s.resets).toLocaleDateString(undefined, { month: "long", day: "numeric" });
    const more = plan.next ? `${plan.next.name} is ${plan.next.price}. To change plans, contact ${plan.contact}.` : `To change plans, contact ${plan.contact}.`;
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <header>Console</header>
      <main>
        ${s.banner ? `<div class="note">${s.banner.text}</div>` : ""}
        <section>
          <h2>Your plan</h2>
          <p><b>${plan.tier_name}</b> · Console's cloud agent can use up to $${Number(plan.cap_usd).toFixed(2)} of AI a month.</p>
          <div class="bar ${kind}"><div style="width:${percent}%"></div></div>
          <p class="soft">${s.percent}% used this month ($${Number(usage.spend_usd || 0).toFixed(2)} of $${Number(plan.cap_usd).toFixed(2)}). Starts again on ${resets}.</p>
          <p class="soft">${more}</p>
        </section>
        <section>
          <h2>Cloud agent</h2>
          <p>${STATE_NAMES[s.cloud_agent] || s.cloud_agent}</p>
          <p class="soft">When the cloud agent is paused or out of reach, your house still works: lights, routines and plain commands run at home, and Claude is unaffected.</p>
        </section>
        <section>
          <h2>This month</h2>
          <p class="soft">${usage.turns || 0} requests · ${usage.ok || 0} done · ${usage.failed || 0} not done</p>
          <table>${this._rows(CATEGORY_NAMES, usage.by_category)}</table>
          <h2 style="margin-top:16px">How they were answered</h2>
          <table>${this._rows(ROUTE_NAMES, usage.by_route)}</table>
        </section>
        <section>
          <h2>What Console sends out</h2>
          <p class="soft">Once a month's worth of totals, and nothing else: no messages, no device names, no rooms, no times of day. This is exactly what is sent:</p>
          <pre>${JSON.stringify(usage, null, 2)}</pre>
        </section>
        <p class="soft" style="text-align:center">Console ${s.version}${s.sunrise ? " · with Sunrise" : " · Sunrise isn't installed"}</p>
      </main>`;
  }
}

if (!customElements.get("console-panel")) customElements.define("console-panel", ConsolePanel);
