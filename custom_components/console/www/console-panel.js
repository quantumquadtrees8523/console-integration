// The Console page in Home Assistant's sidebar.
// Three tabs: "Plan and usage", "What the house knows about you", and "Settings".
const CATEGORY_NAMES = { control: "Controlling things", status: "Questions about the house", customization: "Customizing", setup: "Setting up", troubleshooting: "Fixing problems", other: "Other" };
const ROUTE_NAMES = { local: "Answered at home (no cloud)", flash_fast: "Cloud agent, quick", flash: "Cloud agent", pro: "Cloud agent, stronger model", fallback: "Cloud agent unavailable", other_agent: "Another agent (Claude)" };
const AGENT_NAMES = { console: "Console", other_agents: "Other agents (Claude)" };
const STATE_NAMES = { ok: "Working", near_limit: "Working, allowance running low", over_limit: "Paused until next month", not_linked: "Not connected", cloud_off: "Off: cloud access is turned off (Settings → Cloud access)", ai_off: "Off: AI is turned off (Settings → AI in this house)" };
const TABS = [["plan", "Plan and usage"], ["knows", "What the house knows about you"], ["settings", "Settings"]];

const STYLE = `
  :host { display: block; background: var(--primary-background-color); min-height: 100vh; color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  header { display: flex; align-items: center; height: 56px; padding: 0 12px; background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff); font-size: 20px; gap: 12px; }
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

const credits = (n) => `${n} credit${Number(n) === 1 ? "" : "s"}`;
const esc = (text) => String(text ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const day = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: "long", day: "numeric" }) : "");
const utcDay = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: "long", day: "numeric", timeZone: "UTC" }) : "");
const stamp = (seconds) => (seconds ? new Date(seconds * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "");
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
    const key = sensor ? sensor.state + sensor.attributes.percent_used + (sensor.attributes.support || "") + sensor.attributes.banner_kind : "";
    if (first || key !== this._key) { this._key = key; this._load(); }
  }
  set narrow(value) { this._narrow = value; const menu = this.shadowRoot.querySelector("ha-menu-button"); if (menu) menu.narrow = value; }
  set panel(value) { this._panel = value; }

  _ws(message) { return this._hass.callWS(message); }

  async _load() {
    try {
      this._status = await this._ws({ type: "console/status" });
      if (this._tab === "knows") this._knows = await this._ws({ type: "console/knows" });
      if (this._tab === "settings") this._backup = await this._ws({ type: "console/backup/status" });
      if (this._tab === "settings") { try { this._sugg = await this._ws({ type: "console/suggestions" }); } catch (e) { this._sugg = null; } }
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
        <p><b>${esc(plan.tier_name)}</b> · Console's cloud agent can use up to ${credits(s.credits.allowed)} a month.</p>
        <div class="bar ${kind}"><div style="width:${percent}%"></div></div>
        <p class="soft">${s.percent}% used this month (${s.credits.used} of ${credits(s.credits.allowed)}). Starts again on ${utcDay(s.resets)}.</p>
        <p class="soft">One credit is one cent of AI use. A plain request costs about a twentieth of a credit; a long one that takes several steps can cost a few tenths.</p>
        <p class="soft">${more}</p>
      </section>
      ${s.site ? `<section>
        <h2>Console's site</h2>
        <p class="soft">Where this house is reached from away from home, and where you manage hubs, support mode and sign-in.</p>
        <div class="row"><a href="${esc(s.site)}/_console/" target="_blank" rel="noopener">Open Console's site</a><a href="${esc(s.site)}/" target="_blank" rel="noopener">Open this house through it</a></div>
      </section>` : ""}
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
      ? (k.memory.length ? `<table>${k.memory.map((m) => `<tr><td><a href="#" data-do="mem-open" data-name="${esc(m.name)}">${esc(m.name)}</a><div class="soft">${esc(m.first_line || "")}</div></td><td class="soft">${esc(stamp(m.changed))}</td></tr>`).join("")}</table>` : `<p class="soft">Nothing remembered yet.</p>`)
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
        <p class="soft">What you and Console say in the chat card is kept on this box, so the conversation is still there after a reload. It never leaves the box, and each person signed in to Home Assistant has their own. Yours holds <b>${k.my_chat_messages}</b> message${k.my_chat_messages === 1 ? "" : "s"} (the newest 400 are kept).</p>
        <div class="row"><button class="act danger" data-do="chat-clear" ${k.my_chat_messages ? "" : "disabled"}>Delete my chat history</button></div>
        <p class="soft" style="margin-top:12px">Home Assistant itself also holds the last few voice requests in memory for its own debug view, until it restarts. Right now it holds <b>${k.assist_runs}</b>.</p>
        ${admin ? `<div class="row"><button class="act" data-do="assist-clear" ${k.assist_runs ? "" : "disabled"}>Clear them now</button></div>` : ""}</section>
      <section><h2>Learned sentences</h2>
        <p class="soft">Phrasings this household says often, taught to Home Assistant's own agent so they run at home without the cloud.</p>${learned}</section>
      <section><h2>The monthly summary that is sent out</h2>
        <p class="soft">Once in a while Console sends this month's totals to Console's relay, and nothing else: no messages, no device names, no rooms, no times of day. This is exactly what is sent (<code>spend_usd</code> is in dollars: 0.12 there is 12 credits):</p>
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
      ${this._suggestionsSection(admin)}
      <section><h2>Off switches</h2>
        <p><b>Cloud access: ${s.switches.cloud ? "on" : "off"}</b></p>
        <p class="soft">Off: this house is off Console's relay. Nothing reaches it from outside: no opening it away from home, no Claude through the connector, no access for Console's operator. And Console sends nothing out: its cloud agent is off, no key is renewed, no usage totals are reported. Plain commands still work. <b>It can only be turned back on from inside the house</b>, on your home network. It is not a firewall: other things on this box that use the internet by themselves (Home Assistant Cloud, a music service, HACS) carry on.</p>
        <div class="row"><button class="act ${s.switches.cloud ? "danger" : ""}" data-do="switch" data-entity="switch.console_cloud_access" data-on="${s.switches.cloud ? "0" : "1"}">${s.switches.cloud ? "Turn cloud access off" : "Turn cloud access on"}</button></div>
        <p style="margin-top:14px"><b>AI in this house: ${s.switches.ai ? "on" : "off"}</b></p>
        <p class="soft">Off: no AI agent can read or change anything in this house through its tools. That means Console's cloud agent, Claude through the connector, and any other AI set up in Home Assistant. Only Home Assistant's own sentence matching answers, so plain commands still work. Two limits: an add-on that reloads is covered again within 15 seconds, and something holding a Home Assistant password or token of its own is not stopped by this switch.</p>
        <div class="row"><button class="act ${s.switches.ai ? "danger" : ""}" data-do="switch" data-entity="switch.console_ai" data-on="${s.switches.ai ? "0" : "1"}">${s.switches.ai ? "Turn all AI off" : "Turn AI back on"}</button></div>
        <p class="soft">Both are also switches in Home Assistant (<code>switch.console_cloud_access</code>, <code>switch.console_ai</code>) and tiles on the Home dashboard.</p>
      </section>
      <section><h2>Connect Claude</h2>
        <p class="soft">Claude can work on this house with the same tools as the chat, plus the things the chat can't do (a browser, the router's pages, a shell). ${s.site ? `In a terminal, add this house to Claude Code:` : "This house isn't linked to Console's site yet."}</p>
        ${s.site ? `<pre>claude mcp add --transport http --scope user console ${esc(s.site)}/api/mcp/sunrise</pre>
        <p class="soft">Then, inside Claude Code, type <code>/mcp</code>, pick <b>console</b> and choose <b>Authenticate</b>. A browser opens: sign in with Google if it asks, then with your Home Assistant username and password. (Newer versions of Claude Code can also do this step from the terminal: <code>claude mcp login console</code>.)</p>
        <p class="soft">In Claude on the web or phone: Settings → Connectors → Add custom connector, with the address <code>${esc(s.site)}/api/mcp/sunrise</code>.</p>` : ""}
      </section>
      <section><h2>Backups and your recovery code</h2>
        ${this._backup && this._backup.available ? `
        <p><b>${this._backup.encrypted ? "Backups are encrypted with your recovery code" : "No recovery code yet"}</b></p>
        <p class="soft">Every Home Assistant backup from this box, including any copy that leaves it, is locked with your recovery code. Console's relay never keeps the code, and a backup can't be opened without it: not by Console's operator, not by anyone. Keep it somewhere safe that isn't this box. To restore on a new Home Assistant you need two things only: the backup file and this code.</p>
        <p class="soft">Copies go to: ${esc((this._backup.copies_go_to || []).join(", "))}. ${this._backup.automatic ? "Automatic backups are on." : "Automatic backups are off: turn them on under Settings → System → Backups."}</p>
        ${admin ? `<div class="row"><button class="act" data-do="code-show">${this._backup.encrypted ? "Show my recovery code" : "Make my recovery code"}</button><button class="act" data-do="code-download">Download recovery code</button><button class="act" data-do="backup-now">Back up now</button></div>` : ""}
        ${this._code ? `<pre id="code">${esc(this._code)}</pre>` : ""}
        <p class="soft">${esc(this._backupSaid || "")}</p>` : `<p class="soft">Home Assistant's backups aren't set up on this box.</p>`}
      </section>
      <section><h2>Support mode</h2>
        <p class="soft">Off unless you turn it on. While it's on, Console's operator can open this house through Console's site and see what's in it, including the chat history kept on this box, to help you. It turns itself off after 7 days, and everything the operator opens is listed here.</p>
        <p><b>${s.support.on ? `On until ${dayTime(s.support.until)}` : "Off"}</b></p>
        ${admin ? `<div class="row"><button class="act" data-do="support" data-on="${s.support.on ? "0" : "1"}">${s.support.on ? "Turn support mode off" : "Turn support mode on"}</button></div>` : ""}
        ${(s.support.log || []).length ? `<table>${s.support.log.slice().reverse().map((l) => `<tr><td>${esc(l.what)}</td><td class="soft">${dayTime(l.at)}</td></tr>`).join("")}</table>` : `<p class="soft">Nothing has been done in support mode.</p>`}
      </section>
      ${s.unlinked ? `<section><h2>Connect this house to Console again</h2>
        <p class="soft">This house's Console data was erased here, and it has been refusing Console's relay since. Connecting again lets the relay hand it a cloud-agent key the next time it checks in (within two hours, or sooner if Console's operator asks).</p>
        ${admin ? `<div class="row"><button class="act" data-do="relink">Connect again</button></div>` : ""}</section>` : ""}
      ${admin ? `<section><h2>Erase Console and Sunrise data</h2>
        <p class="soft">Erases what Console and Sunrise keep on this box: everyone's chat history, the agents' notes (Sunrise's memory, its history and any skills you edited), learned sentences, this month's counts, the cloud-agent key and plan, and this house's link to Console's relay. Your devices, dashboards, automations and Home Assistant itself are not touched. To go ahead, type <b>erase my data</b>.</p>
        <div class="row"><input type="text" id="wipe-data" placeholder="erase my data" autocomplete="off" style="max-width:220px"><button class="act danger" data-do="wipe" data-level="data">Erase Console and Sunrise data</button></div>
      </section>
      <section><h2>Factory reset Home Assistant</h2>
        <p class="soft">Erases everything in Home Assistant on this box: every device, room, dashboard, automation, user and setting, and all of Console's and Sunrise's data. Home Assistant restarts as a new install and asks you to create an account. Only the installed add-on integrations (so Console and Sunrise can be set up again) and the backups folder are kept. <b>This can't be undone.</b> To go ahead, type <b>factory reset</b>.</p>
        <div class="row"><input type="text" id="wipe-factory" placeholder="factory reset" autocomplete="off" style="max-width:220px"><button class="act danger" data-do="wipe" data-level="factory">Factory reset Home Assistant</button></div>
      </section>` : `<section><p class="soft">Erasing data and factory reset are for Home Assistant administrators.</p></section>`}
      <p class="soft">${esc(this._wipeSaid || "")}</p>`;
  }

  _suggestionsSection(admin) {
    const g = this._sugg;
    if (!g) return "";
    if (!g.available) return `<section><h2>Suggested routines</h2><p class="soft">Suggested routines need Sunrise, and it isn't installed.</p></section>`;
    const last = g.last_run;
    const lastLine = last ? (last.ran ? `Last run ${dayTime(last.at)}: ${last.made} new, ${credits(Math.round((last.cost_usd || 0) * 1000) / 10)} used.` : `Last run ${dayTime(last.at)} was skipped (${esc(last.why)}).`) : "It hasn't run yet.";
    const items = (g.items || []).map((i) => `<tr><td>${esc(i.name)}<div class="soft">${esc(i.description || "")}</div></td><td>${i.taps} of ${i.keep_after} runs${admin ? ` <button class="act" data-do="sugg-dismiss" data-id="${esc(i.id)}">Remove</button>` : ""}</td></tr>`).join("");
    const kept = (g.kept || []).slice().reverse().map((k) => `<tr><td>${esc(k.name)}</td><td class="soft">kept ${dayTime(k.at)}</td></tr>`).join("");
    return `<section><h2>Suggested routines</h2>
        <p><b>Nightly suggestions: ${g.on ? "on" : "off"}</b></p>
        <p class="soft">Each night Console's cloud agent looks at how the house is used and suggests up to 3 routines in the chat. A suggestion is a real automation, switched off and labelled “Suggested”: it only runs when someone taps it. After 5 taps it's kept and runs by itself. One nobody taps for 7 days is removed, and a removed one is never suggested again.</p>
        <div class="note">${esc(g.cost_note)}</div>
        ${admin ? `<div class="row"><button class="act" data-do="sugg-set" data-on="${g.on ? "0" : "1"}">${g.on ? "Turn nightly suggestions off" : "Turn nightly suggestions on"}</button><button class="act" data-do="sugg-run">Suggest now</button></div>` : ""}
        <p class="soft">${esc(lastLine)}</p>
        ${items ? `<table>${items}</table>` : `<p class="soft">No suggestions waiting.</p>`}
        ${kept ? `<h2 style="margin-top:16px">Kept</h2><table>${kept}</table><p class="soft">A kept routine is an ordinary automation: change or remove it under Settings → Automations, or ask the chat to undo it.</p>` : ""}
        <p class="soft">${esc(this._suggSaid || "")}</p></section>`;
  }

  _draw() {
    const s = this._status;
    if (!s) return;
    const root = this.shadowRoot;
    if (s.error) { root.innerHTML = `<style>${STYLE}</style><header>Console</header><main><section><h2>Console didn't answer</h2><p class="soft">${esc(s.error)}</p></section></main>`; return; }
    const body = this._tab === "plan" ? this._plan(s) : this._tab === "knows" ? this._knowsTab(s) : this._settings(s);
    root.innerHTML = `<style>${STYLE}</style>
      <header><span id="menu"></span><span>Console</span></header>
      <nav>${TABS.map(([key, name]) => `<button data-tab="${key}" class="${key === this._tab ? "on" : ""}">${name}</button>`).join("")}</nav>
      <main>${s.support && s.support.on ? `<div class="note on">Support mode is on until ${dayTime(s.support.until)}. Console's operator can open this house.</div>` : ""}${body}
        <p class="soft" style="text-align:center">Console ${esc(s.version)}${s.sunrise ? " · with Sunrise" : " · Sunrise isn't installed"}</p>
      </main>`;
    const menu = document.createElement("ha-menu-button");   // opens the sidebar on phones and narrow windows
    menu.hass = this._hass; menu.narrow = this._narrow;
    root.getElementById("menu").appendChild(menu);
    root.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => { this._tab = b.dataset.tab; this._said = ""; this._editing = null; this._code = null; this._load(); }));
    root.querySelectorAll("[data-do]").forEach((el) => el.addEventListener("click", (event) => { event.preventDefault(); this._do(el.dataset.do, el.dataset); }));
  }

  async _do(what, at) {
    try {
      if (what === "mem-open") { this._editing = await this._ws({ type: "console/memory/read", name: at.name }); this._said = ""; }
      else if (what === "mem-close") { this._editing = null; }
      else if (what === "mem-save") { await this._ws({ type: "console/memory/write", name: this._editing.name, text: this.shadowRoot.getElementById("memtext").value }); this._editing = null; this._said = "Saved."; }
      else if (what === "mem-delete") { if (!confirm(`Delete the note “${this._editing.name}”? It can be brought back from Sunrise's history.`)) return; await this._ws({ type: "console/memory/delete", name: this._editing.name }); this._editing = null; this._said = "Deleted."; }
      else if (what === "forget") { await this._ws({ type: "console/learned/forget", sentence_id: at.id }); this._said = "Forgotten. That sentence goes to the cloud agent again."; }
      else if (what === "chat-clear") { if (!confirm("Delete your chat history from this box? It can't be brought back.")) return; const r = await this._ws({ type: "console/chat/clear" }); this._said = `Deleted ${r.deleted} messages.`; }
      else if (what === "assist-clear") { const r = await this._ws({ type: "console/assist/clear" }); this._said = `Cleared ${r.cleared}.`; }
      else if (what === "rebuild") { const r = await this._ws({ type: "console/dashboard/rebuild" }); this._said = r.ok ? `Home dashboard: ${r.did}.` : r.why; }
      else if (what === "switch") {
        if (at.entity === "switch.console_cloud_access" && at.on === "0" && !confirm("Turn cloud access off? This house leaves Console's relay at once. If you're looking at this page from away from home it will stop loading, and it can only be turned back on from inside the house.")) return;
        await this._hass.callService("switch", at.on === "1" ? "turn_on" : "turn_off", { entity_id: at.entity }); await new Promise((done) => setTimeout(done, 300));
      }
      else if (what === "code-show") { this._code = (await this._ws({ type: "console/backup/recovery_code" })).code; }
      else if (what === "code-download") {
        const got = await this._ws({ type: "console/backup/recovery_code" });
        const text = `Console recovery code\n\n${got.code}\n\nKeep this somewhere safe that isn't your Home Assistant box.\nTo restore a backup on a new Home Assistant: choose "Restore from backup" on its first screen, upload the backup file, and type this code when it asks for the encryption key.\nConsole's relay doesn't have this code. If you lose it, your backups can't be opened.\n`;
        const link = document.createElement("a");
        link.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
        link.download = "console-recovery-code.txt";
        link.click();
        this._backupSaid = "Downloaded console-recovery-code.txt.";
      }
      else if (what === "backup-now") { const r = await this._ws({ type: "console/backup/now" }); this._backupSaid = `Started \u201c${r.name}\u201d. It appears under Settings → System → Backups when it's done.`; }
      else if (what === "support") { await this._ws({ type: "console/support/set", on: at.on === "1" }); this._said = ""; }
      else if (what === "sugg-set") {
        if (at.on === "1" && !confirm("Turn nightly suggestions on? Each night's run uses some of this month's credits, so the allowance runs down faster.")) return;
        await this._ws({ type: "console/suggestions/set", on: at.on === "1" }); this._suggSaid = "";
      }
      else if (what === "sugg-run") { this._suggSaid = "Looking at the house…"; this._draw(); const r = await this._ws({ type: "console/suggestions/run" }); this._suggSaid = r.ran ? `${r.made} new suggestion${r.made === 1 ? "" : "s"}.` : `Skipped: ${r.why}.`; }
      else if (what === "sugg-dismiss") { const r = await this._ws({ type: "console/suggestions/dismiss", suggestion_id: at.id }); this._suggSaid = r.reply; }
      else if (what === "relink") { await this._ws({ type: "console/relink" }); this._wipeSaid = "Connected again. The cloud agent comes back when the relay next checks in."; }
      else if (what === "wipe") {
        const typed = this.shadowRoot.getElementById(`wipe-${at.level}`).value;
        const r = await this._ws({ type: "console/wipe", level: at.level, confirm: typed });
        this._wipeSaid = at.level === "factory" ? "Home Assistant is restarting as a new install. This page will stop answering." : "Erased. Console and Sunrise have started again with nothing remembered, and this house is no longer connected to Console.";
        if (r.restarting) return this._draw();
      }
    } catch (error) { if (what.startsWith("code-") || what === "backup-now") this._backupSaid = String(error.message || error); else if (what === "wipe" || what === "relink") this._wipeSaid = String(error.message || error); else if (what.startsWith("sugg-")) this._suggSaid = String(error.message || error); else this._said = String(error.message || error); }
    await this._load();
  }
}

if (!customElements.get("console-panel")) customElements.define("console-panel", ConsolePanel);
window.ConsolePanel = ConsolePanel;
