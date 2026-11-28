// Console chat card: talk to Console, this home's agent, from a dashboard.
//
// Chats are threads. Each chat a person has is kept on the box (never in this card, never off the box)
// with the work behind every reply: where the request went and why, the model's thinking, each tool it
// used and what came back. The list of chats opens from the top bar; opening one shows the whole of it,
// ten messages at a time from the newest.
//
// A turn is asked through Console's own websocket command (console/chat), which answers as the turn
// happens. One message is one turn: the command is never sent again when the connection comes back
// (resubscribe: false). A turn runs on the box whoever is listening, so a card that reloads, reconnects
// or opens the chat on another screen watches the running turn (console/chat/watch) or finds the reply
// in the thread.
//
// Above the box you type in: always three suggestions, each a tap that runs something now. Under it:
// quick actions, the suggestions this household keeps using (suggestions.py).
const SENSOR = "sensor.console_cloud_agent";
const PAGE = 10;
const RECENT_MS = 30 * 60 * 1000;
const REFRESH_MS = 5 * 60 * 1000;
const STORE = "console-chat-thread";

const STYLE = `
  :host { display: block; height: 100%; }
  [hidden] { display: none !important; }
  ha-card { display: flex; flex-direction: column; height: 100%; min-height: var(--console-chat-height, 420px); overflow: hidden; position: relative; }
  .banner { padding: 10px 16px; font-size: 14px; line-height: 20px; }
  .banner.warn { background: color-mix(in srgb, var(--warning-color, #ffa600) 18%, transparent); }
  .banner.stop { background: color-mix(in srgb, var(--error-color, #db4437) 18%, transparent); }
  .banner.offline, .banner.off { background: color-mix(in srgb, var(--secondary-text-color, #888) 16%, transparent); }
  .banner.support { background: color-mix(in srgb, var(--warning-color, #ffa600) 26%, transparent); }
  .banner a, .earlier { color: var(--primary-color); cursor: pointer; text-decoration: underline; white-space: nowrap; }
  .bar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--divider-color); min-height: 28px; }
  .bar .name { flex: 1; min-width: 0; color: var(--primary-text-color); font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bar button, .threads .head button { font: inherit; font-size: 13px; padding: 5px 12px; border-radius: 14px; border: 1px solid var(--divider-color); background: none; color: var(--primary-color); cursor: pointer; white-space: nowrap; }
  .bar button[aria-expanded="true"] { background: color-mix(in srgb, var(--primary-color) 14%, transparent); }
  .body { flex: 1; min-height: 0; position: relative; display: flex; }
  .threads { position: absolute; inset: 0; z-index: 2; background: var(--card-background-color, #fff); display: flex; flex-direction: column; overflow: hidden; }
  .threads .head { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 10px 14px 6px; font-size: 12px; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: .06em; }
  .threads .rows { flex: 1; overflow-y: auto; padding: 0 8px 10px; }
  .thread { display: flex; align-items: stretch; gap: 4px; border-radius: 10px; }
  .thread.on { background: color-mix(in srgb, var(--primary-color) 12%, transparent); }
  .thread .open { flex: 1; min-width: 0; text-align: left; border: 0; background: none; color: var(--primary-text-color); font: inherit; padding: 9px 10px; cursor: pointer; border-radius: 10px; }
  .thread .open:hover { background: color-mix(in srgb, var(--primary-text-color) 6%, transparent); }
  .thread .t { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .thread .s { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px; }
  .thread .x, .chip .x { border: 0; background: none; color: var(--secondary-text-color); cursor: pointer; font-size: 13px; padding: 0 10px; }
  .none { padding: 14px; color: var(--secondary-text-color); font-size: 14px; }
  .log { flex: 1; min-width: 0; overflow-y: auto; padding: 12px 16px 6px; display: flex; flex-direction: column; gap: 10px; overscroll-behavior: contain;
         user-select: text; -webkit-user-select: text; }
  .top { display: flex; justify-content: center; font-size: 12px; color: var(--secondary-text-color); min-height: 4px; }
  .hello { color: var(--secondary-text-color); font-size: 14px; line-height: 20px; }
  .turn { display: flex; flex-direction: column; gap: 4px; max-width: 92%; }
  .turn.me { align-self: flex-end; align-items: flex-end; }
  .turn.it { align-self: flex-start; align-items: stretch; }
  .msg { padding: 9px 13px; border-radius: 16px; font-size: 15px; line-height: 22px; overflow-wrap: anywhere; user-select: text; -webkit-user-select: text; cursor: text; }
  .me .msg { background: var(--primary-color); color: var(--text-primary-color, #fff); border-bottom-right-radius: 5px; white-space: pre-wrap; }
  .it .msg { background: var(--secondary-background-color); color: var(--primary-text-color); border-bottom-left-radius: 5px; }
  .it .msg.error { border: 1px solid var(--error-color, #db4437); }
  .msg > :first-child { margin-top: 0; } .msg > :last-child { margin-bottom: 0; }
  .msg p { margin: 0 0 8px; } .msg ul, .msg ol { margin: 0 0 8px; padding-left: 22px; } .msg li { margin: 2px 0; }
  .msg h3, .msg h4 { margin: 10px 0 6px; font-size: 15px; font-weight: 700; }
  .msg blockquote { margin: 0 0 8px; padding-left: 10px; border-left: 3px solid var(--divider-color); color: var(--secondary-text-color); }
  .msg code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; background: color-mix(in srgb, var(--primary-text-color) 10%, transparent); padding: 1px 5px; border-radius: 5px; }
  .code { position: relative; margin: 0 0 8px; }
  .code pre { margin: 0; padding: 10px 12px; border-radius: 10px; background: color-mix(in srgb, var(--primary-text-color) 9%, transparent); overflow-x: auto; white-space: pre-wrap; word-break: break-word; }
  .code pre code { background: none; padding: 0; }
  .copy { font: inherit; font-size: 12px; padding: 3px 9px; border-radius: 12px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-color); cursor: pointer; }
  .code .copy { position: absolute; top: 6px; right: 6px; }
  .foot { display: flex; gap: 10px; align-items: center; font-size: 11px; color: var(--secondary-text-color); padding-left: 6px; }
  .foot .copy { border: 0; background: none; padding: 0; text-decoration: underline; }
  details.steps { font-size: 13px; color: var(--secondary-text-color); margin: 0 0 2px 4px; }
  details.steps summary { cursor: pointer; list-style: none; display: flex; align-items: center; gap: 6px; padding: 2px 0; }
  details.steps summary::-webkit-details-marker { display: none; }
  details.steps summary::after { content: "\\25BE"; font-size: 11px; }
  details.steps[open] summary::after { content: "\\25B4"; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--primary-color); animation: pulse 1s ease-in-out infinite; }
  @keyframes pulse { 0%, 100% { opacity: .25; } 50% { opacity: 1; } }
  @media (prefers-reduced-motion: reduce) { .dot { animation: none; } }
  .steplist { margin: 4px 0 6px; padding: 0 0 0 12px; border-left: 2px solid var(--divider-color); display: flex; flex-direction: column; gap: 6px; }
  .step .t { color: var(--primary-text-color); }
  .step.failed .t { color: var(--error-color, #db4437); }
  .step .d { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; user-select: text; -webkit-user-select: text; }
  .step.think .d { font-style: italic; }
  .step .more { font: inherit; font-size: 11px; margin-left: 8px; padding: 0; border: 0; background: none; color: var(--primary-color); text-decoration: underline; cursor: pointer; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .strip { display: flex; align-items: baseline; gap: 8px; padding: 8px 12px 0; }
  .strip.quick { padding: 0 12px 10px; }
  .strip .row { display: flex; gap: 6px 8px; min-width: 0; }
  .strip.suggested .row { flex-wrap: wrap; }   /* all three are always in view, on a phone too */
  .strip.quick .row { overflow-x: auto; padding-bottom: 2px; scrollbar-width: thin; }
  .chip { display: inline-flex; align-items: center; flex: none; max-width: 100%; border: 1px solid var(--divider-color); border-radius: 16px; font-size: 13px; background: none; color: var(--primary-text-color); font-family: inherit; white-space: nowrap; }
  button.chip, .chip .go { cursor: pointer; }
  button.chip { padding: 6px 12px; }
  .chip .go { border: 0; background: none; color: inherit; font: inherit; padding: 6px 12px; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .chip .go + .x { padding: 0 9px 0 0; }
  .chip.quick { border-color: color-mix(in srgb, var(--primary-color) 55%, var(--divider-color)); background: color-mix(in srgb, var(--primary-color) 9%, transparent); }
  .chip[disabled], .chip .go[disabled] { opacity: .5; cursor: default; }
  form { display: flex; gap: 8px; padding: 8px 12px 10px; align-items: flex-end; }
  textarea { flex: 1; min-width: 0; min-height: 42px; max-height: 140px; padding: 10px 14px; border-radius: 21px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); font: inherit; font-size: 15px; line-height: 20px; resize: none; box-sizing: border-box; }
  textarea:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
  button.send { height: 42px; padding: 0 18px; border-radius: 21px; border: 0; background: var(--primary-color); color: var(--text-primary-color, #fff); font: inherit; font-weight: 600; cursor: pointer; }
  button.send[disabled] { opacity: .5; cursor: default; }
`;

// The model's thinking, as one line: its first sentence (or what it has so far), at most GIST characters.
// The whole of it stays one tap away ("Show all"). Owner, 2026-11-27: the full stream was too noisy.
const GIST = 110;
const gist = (text) => {
  const flat = String(text || "").replace(/[*_`#>]+/g, "").replace(/\s+/g, " ").trim();
  const end = flat.search(/[.!?](\s|$)/);
  const first = end >= 0 ? flat.slice(0, end + 1) : flat;
  return first.length > GIST ? `${first.slice(0, GIST - 1).trimEnd()}…` : first;
};
const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; };
const credits = (usd) => { const c = (usd || 0) * 100; return c >= 10 ? String(Math.round(c)) : c >= 0.1 ? c.toFixed(1) : c.toFixed(2); };
const copyText = async (text, button) => {
  try { await navigator.clipboard.writeText(text); }
  catch (e) { const area = el("textarea"); area.value = text; document.body.appendChild(area); area.select(); try { document.execCommand("copy"); } catch (e2) { /* nothing more to try */ } area.remove(); }
  if (button) { const was = button.textContent; button.textContent = "Copied"; setTimeout(() => { button.textContent = was; }, 1400); }
};

// --- Markdown, built as DOM nodes (never as HTML), so nothing in a reply can run -------------------
function inline(parent, text) {
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g;
  let last = 0, match;
  while ((match = pattern.exec(text))) {
    if (match.index > last) parent.appendChild(document.createTextNode(text.slice(last, match.index)));
    const token = match[0];
    if (token[0] === "`") parent.appendChild(el("code", "", token.slice(1, -1)));
    else if (token.startsWith("**")) { const b = el("strong"); inline(b, token.slice(2, -2)); parent.appendChild(b); }
    else if (token[0] === "*") { const i = el("em"); inline(i, token.slice(1, -1)); parent.appendChild(i); }
    else { const parts = /\[([^\]]+)\]\((.+)\)/.exec(token); const a = el("a", "", parts[1]); a.href = parts[2]; a.target = "_blank"; a.rel = "noopener noreferrer"; parent.appendChild(a); }
    last = match.index + token.length;
  }
  if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
}

function markdown(target, source) {
  target.replaceChildren();
  const lines = String(source || "").replace(/\r/g, "").split("\n");
  let i = 0, list = null, para = [];
  const flush = () => { if (para.length) { const p = el("p"); inline(p, para.join("\n")); p.style.whiteSpace = "pre-wrap"; target.appendChild(p); para = []; } };
  while (i < lines.length) {
    const line = lines[i];
    const fence = /^\s*```(\w*)\s*$/.exec(line);
    if (fence) {
      flush(); list = null;
      const body = [];
      i += 1;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) { body.push(lines[i]); i += 1; }
      i += 1;
      const box = el("div", "code"), pre = el("pre"), code = el("code", "", body.join("\n")), button = el("button", "copy", "Copy");
      button.type = "button";
      button.addEventListener("click", () => copyText(body.join("\n"), button));
      pre.appendChild(code); box.append(pre, button); target.appendChild(box);
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    const numbered = /^\s*(\d+)[.)]\s+(.*)$/.exec(line);
    const quote = /^>\s?(.*)$/.exec(line);
    if (heading) { flush(); list = null; const h = el(heading[1].length <= 2 ? "h3" : "h4"); inline(h, heading[2]); target.appendChild(h); }
    else if (bullet || numbered) {
      flush();
      const kind = bullet ? "UL" : "OL";
      if (!list || list.tagName !== kind) { list = el(kind.toLowerCase()); if (numbered) list.start = Number(numbered[1]); target.appendChild(list); }
      const item = el("li"); inline(item, (bullet || numbered)[bullet ? 1 : 2]); list.appendChild(item);
    }
    else if (quote) { flush(); list = null; const q = el("blockquote"); inline(q, quote[1]); target.appendChild(q); }
    else if (!line.trim()) { flush(); if (list && !(lines[i + 1] && /^\s*(\d+[.)]|[-*])\s+/.test(lines[i + 1]))) list = null; }
    else if (list && /^\s{2,}\S/.test(line)) { const item = list.lastElementChild; item.appendChild(document.createTextNode(" ")); inline(item, line.trim()); }
    else { list = null; para.push(line); }
    i += 1;
  }
  flush();
}

const ago = (iso) => {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

class ConsoleChatCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._busy = false;      // a turn is running in the chat on screen
    this._loaded = false;    // the first read of the box is done
    this._banner = "";
    this._thread = null;     // the chat on screen (null: a new one, not started)
    this._title = "";
    this._from = 0;          // index of the oldest message on screen, in its thread
    this._more = false;      // whether the thread holds earlier ones
    this._total = 0;         // how many messages the thread held when it was last read
    this._seq = 0;           // goes up whenever the chat on screen changes: a late answer for another chat is dropped
    this._stop = null;       // ends the subscription to the turn being watched
    this._seenSent = "";
  }

  setConfig(config) { this._config = { title: "Console", ...config }; this._build(); }
  static getStubConfig() { return { title: "Console" }; }
  getCardSize() { return 9; }
  getGridOptions() { return { columns: 12, rows: 9, min_rows: 6 }; }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const sensor = hass.states[SENSOR];
    const key = sensor ? `${sensor.state}|${sensor.attributes.banner || ""}` : "none";
    if (key !== this._banner) { this._banner = key; this._drawBanner(sensor); }
    if (first) this._start();
  }

  connectedCallback() {
    if (!this._timer) this._timer = setInterval(() => { if (!this._busy && document.visibilityState === "visible") this._loadSuggested(); }, REFRESH_MS);
    if (!this._onVisible) {
      this._onVisible = () => { if (document.visibilityState === "visible" && this._loaded) this._resync(); };
      document.addEventListener("visibilitychange", this._onVisible);
    }
  }

  disconnectedCallback() {
    clearInterval(this._timer); this._timer = null;
    if (this._onVisible) { document.removeEventListener("visibilitychange", this._onVisible); this._onVisible = null; }
  }

  _ws(message) { return this._hass.callWS(message); }

  async _start() {
    // When the connection to Home Assistant comes back (the phone woke up, the Wi-Fi returned), read the
    // chat again from the box: the turn that was running went on without this card.
    this._hass.connection.addEventListener("ready", () => { if (this._loaded) this._resync(true); });
    try { this._welcome = (await this._ws({ type: "console/status" })).onboarding || {}; } catch (e) { this._welcome = {}; }
    this._ws({ type: "console/metrics/seen", screen: "chat_card" }).catch(() => {});  // usage details: that the card was opened, nothing else
    this._loadSuggested();
    let remembered = null;
    try { remembered = sessionStorage.getItem(STORE); } catch (e) { /* private window */ }
    try {
      const page = await this._ws({ type: "console/chat/history", limit: PAGE, ...(remembered ? { thread_id: remembered } : {}) });
      const last = page.messages[page.messages.length - 1];
      const recent = last && Date.now() - new Date(last.at).getTime() < RECENT_MS;
      // The same sitting (this tab's chat, or one used in the last half hour): show it. Otherwise a new chat.
      if (page.total && (remembered || recent || page.working)) this._show(page);
      else this._setThread(null, "");
    } catch (e) { /* nothing kept yet */ }
    this._loaded = true;
    this._drawBar();
    this._drawHello();
    this._bottom();
  }

  _build() {
    const root = this.shadowRoot;
    root.innerHTML = `<style>${STYLE}</style>
      <ha-card>
        <div class="banner" hidden></div>
        <div class="bar"><button class="list" type="button" aria-expanded="false">Chats</button><span class="name"></span><button class="fresh" type="button">New chat</button></div>
        <div class="body">
          <div class="threads" hidden><div class="head"><span>Your chats</span><button class="shut" type="button">Close</button></div><div class="rows"></div></div>
          <div class="log" role="log" aria-live="polite"><div class="top"></div><div class="hello"></div></div>
        </div>
        <div class="strip suggested" hidden><div class="row" role="group" aria-label="Suggestions"></div></div>
        <form><textarea rows="1" placeholder="Ask Console" aria-label="Ask Console" enterkeyhint="send"></textarea>
        <button class="send" type="submit">Send</button></form>
        <div class="strip quick" hidden><div class="row" role="group" aria-label="Quick actions"></div></div>
      </ha-card>`;
    if (this._config.title) root.querySelector("ha-card").setAttribute("header", this._config.title);
    this._log = root.querySelector(".log");
    this._top = root.querySelector(".top");
    this._hello = root.querySelector(".hello");
    this._threads = root.querySelector(".threads");
    this._suggestedRow = root.querySelector(".strip.suggested");
    this._quickRow = root.querySelector(".strip.quick");
    const area = root.querySelector("textarea");
    const submit = () => { const text = area.value.trim(); if (text && !this._busy && this._loaded) { area.value = ""; area.style.height = ""; this._send(text); } };
    root.querySelector("form").addEventListener("submit", (event) => { event.preventDefault(); submit(); });
    area.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); } });
    area.addEventListener("input", () => { area.style.height = "auto"; area.style.height = `${Math.min(area.scrollHeight + 2, 140)}px`; });
    root.querySelector(".bar .list").addEventListener("click", () => this._toggleThreads());
    root.querySelector(".bar .fresh").addEventListener("click", () => this._newChat());
    root.querySelector(".threads .shut").addEventListener("click", () => this._toggleThreads(false));
    // Earlier messages of this chat come when the person pulls up past the top.
    this._log.addEventListener("wheel", (event) => { if (event.deltaY < 0 && this._log.scrollTop < 2) this._earlier(); }, { passive: true });
    let touchY = null;
    this._log.addEventListener("touchstart", (event) => { touchY = this._log.scrollTop < 2 ? event.touches[0].clientY : null; }, { passive: true });
    this._log.addEventListener("touchmove", (event) => { if (touchY !== null && event.touches[0].clientY - touchY > 60) { touchY = null; this._earlier(); } }, { passive: true });
    // A suggestion counts as seen when it is really on screen, not when the dashboard merely holds this card.
    if (window.IntersectionObserver) new IntersectionObserver((entries) => { this._onScreen = entries.some((entry) => entry.isIntersecting); this._seen(); }).observe(this._suggestedRow);
    else this._onScreen = true;
    this._drawBar();
  }

  _drawBanner(sensor) {
    const banner = this.shadowRoot.querySelector(".banner");
    if (!banner) return;
    const text = sensor && sensor.attributes.banner;
    banner.hidden = !text;
    if (!text) return;
    const kind = sensor.attributes.banner_kind || "warn";
    banner.className = `banner ${kind}`;
    banner.textContent = text + " ";
    const link = el("a", "", kind === "offline" ? "Details" : kind === "support" ? "Turn it off" : kind === "off" ? "Settings" : "Need more?");
    link.addEventListener("click", () => { history.pushState(null, "", "/console"); window.dispatchEvent(new CustomEvent("location-changed")); });
    banner.appendChild(link);
  }

  _drawBar() {
    const root = this.shadowRoot;
    root.querySelector(".bar .name").textContent = this._thread ? this._title || "Chat" : "New chat";
    root.querySelector(".bar .fresh").hidden = !this._thread && !this._log.querySelector(".turn");
    root.querySelector(".bar .list").setAttribute("aria-expanded", this._threads.hidden ? "false" : "true");
    this._top.replaceChildren();
    if (this._more) { const earlier = el("span", "earlier", "Load earlier messages"); earlier.addEventListener("click", () => this._earlier()); this._top.appendChild(earlier); }
  }

  _drawHello() {
    if (!this._hello.isConnected) return;
    this._hello.replaceChildren();
    const welcome = this._welcome || {};
    if (welcome.available && !welcome.offered && !welcome.done) {
      const offer = el("div", "msg", "Welcome. I'm Console, this home's agent. Want me to show you around? I'll learn your rooms and devices, add anything that's waiting, and set up one routine with you. It takes a few minutes and you can stop any time.");
      offer.style.cssText = "background: var(--secondary-background-color); color: var(--primary-text-color); margin-bottom: 10px;";
      this._hello.appendChild(offer);
    } else {
      this._hello.appendChild(el("div", "", "Ask for anything in your home: “turn off the kitchen lights”, “play jazz in the kitchen”, “add a dashboard for the kids' room”. Or tap a suggestion below."));
    }
    if (!(welcome.available && !welcome.done)) return;
    const chips = el("div", "chips");
    chips.style.marginTop = "10px";
    const offers = [[welcome.state === "started" ? "Pick up the welcome" : "Show me around", "Show me around."]];
    if (!welcome.offered) offers.push(["Not now", null]);
    for (const [label, text] of offers) {
      const chip = el("button", "chip", label);
      chip.type = "button";
      chip.addEventListener("click", () => {
        if (!welcome.offered) { welcome.offered = true; this._ws({ type: "console/onboarding/offered" }).catch(() => {}); }
        if (text) this._send(text); else this._drawHello();
      });
      chips.appendChild(chip);
    }
    this._hello.appendChild(chips);
  }

  // --- suggestions (always three, above the box) and quick actions (under it): suggestions.py --------

  async _loadSuggested() {
    try { this._suggested = await this._ws({ type: "console/suggestions" }); } catch (e) { /* keep what's shown */ }
    this._drawSuggested();
    this._drawQuick();
    this._seen();
  }

  _chip(item, quick) {
    const admin = this._suggested && this._suggested.is_admin && item.kind !== "ask";
    const chip = el(admin ? "span" : "button", `chip${quick ? " quick" : ""}`);
    const go = admin ? el("button", "go") : chip;
    go.type = "button";
    go.textContent = `${item.kind === "ask" ? "" : "▶ "}${item.name}`;
    // A suggested routine is off until its second tap; after that it runs by itself (suggestions.py, AUTO_TAPS).
    const routine = item.kind !== "routine" ? "" : item.auto ? "Runs by itself now." : item.taps ? "Tap once more and it runs by itself." : "A routine Console suggests. Tap to run it once; the second tap lets it run by itself.";
    go.title = [item.why, routine || (quick ? "A quick action: you use this one often." : "")].filter(Boolean).join(" ");
    go.addEventListener("click", () => this._tap(item));
    if (admin) {
      const x = el("button", "x", "✕"); x.type = "button"; x.title = "Don't suggest this again"; x.setAttribute("aria-label", `Don't suggest ${item.name} again`);
      x.addEventListener("click", () => this._dismiss(item));
      chip.append(go, x);
    }
    return chip;
  }

  _drawSuggested() {
    const items = (this._suggested && this._suggested.suggested) || [];
    this._suggestedRow.hidden = !items.length;
    this._suggestedRow.querySelector(".row").replaceChildren(...items.map((item) => this._chip(item, false)));
  }

  _drawQuick() {
    const items = (this._suggested && this._suggested.quick) || [];
    this._quickRow.hidden = !items.length;
    this._quickRow.querySelector(".row").replaceChildren(...items.map((item) => this._chip(item, true)));
  }

  // Tell the box which suggestions were on screen. One seen a few times and never tapped is discarded
  // there, and the next one takes its place. The box counts a sighting at most once every few hours.
  async _seen() {
    const ids = ((this._suggested && this._suggested.suggested) || []).map((item) => item.id);
    if (!ids.length || !this._onScreen || document.visibilityState !== "visible") return;
    const key = `${ids.join("|")}@${Math.floor(Date.now() / 3600000)}`;
    if (key === this._seenSent) return;
    this._seenSent = key;
    try { const got = await this._ws({ type: "console/suggestions/seen", ids }); if ((got.discarded || []).length) this._loadSuggested(); } catch (e) { /* an older Console on the box */ }
  }

  async _tap(item) {
    if (this._busy || !this._loaded) return;
    this._busy = true;
    const seq = this._seq;
    let done = null, failed = null;
    try { done = await this._ws({ type: "console/suggestions/tap", suggestion_id: item.id, thread_id: this._thread }); } catch (e) { failed = String(e.message || e); }
    this._busy = false;
    if (done && done.ask) { this._send(done.ask); this._loadSuggested(); return; }   // something to ask: sent like any message
    if (seq !== this._seq) return;
    const was = this._atBottom();
    this._hello.remove();
    this._log.appendChild(this._turn("me", `Run “${item.name}”`).node);
    if (done) {
      this._setThread(done.thread_id, this._title || `Run “${item.name}”`);
      this._total += 2;
      this._log.appendChild(this._stored({ who: "console", text: done.reply, steps: [{ title: "Ran at home", detail: "A tap on a suggestion: no AI, no internet." }], meta: { route: "local" } }).node);
    } else this._log.appendChild(this._turn("it", failed, { error: true }).node);
    this._follow(was || true);
    this._drawBar();
    this._loadSuggested();
  }

  async _dismiss(item) {
    try { await this._ws({ type: "console/suggestions/dismiss", suggestion_id: item.id }); } catch (e) { /* it's gone already */ }
    this._loadSuggested();
  }

  // --- chats as threads ---------------------------------------------------------------------------

  _setThread(id, title) {
    this._thread = id || null;
    if (title !== undefined) this._title = title;
    try { if (id) sessionStorage.setItem(STORE, id); else sessionStorage.removeItem(STORE); } catch (e) { /* private window */ }
  }

  _clear() {
    this._seq += 1;
    if (this._stop) { try { this._stop(); } catch (e) { /* already closed */ } this._stop = null; }
    this._busy = false;
    this.shadowRoot.querySelector("button.send").disabled = false;
    this._log.querySelectorAll(".turn").forEach((node) => node.remove());
    this._from = 0; this._more = false; this._total = 0;
  }

  // Put one page of a thread on screen (the newest), and watch its turn if one is running.
  _show(page) {
    this._clear();
    this._setThread(page.thread_id, page.title);
    for (const message of page.messages) this._log.appendChild(this._stored(message).node);
    this._from = page.from; this._more = page.more;
    this._total = page.total - (page.working ? 1 : 0);   // the running turn adds its two when it ends
    this._hello.remove();
    if (page.working) this._watch();
    this._drawBar();
    this._bottom();
  }

  async _open(id) {
    this._toggleThreads(false);
    try { this._show(await this._ws({ type: "console/chat/history", thread_id: id, limit: PAGE })); }
    catch (e) { this._newChat(); }
  }

  _newChat() {
    this._toggleThreads(false);
    this._clear();
    this._setThread(null, "");
    if (!this._hello.isConnected) this._top.after(this._hello);
    this._drawBar();
    this._drawHello();
  }

  // The chat on screen, read again from the box: after a reconnect, or when the page comes back into
  // view. A turn that finished meanwhile shows its reply; one still running is watched.
  async _resync(force) {
    if (this._busy && !force) return;
    if (!this._thread && !this._busy) { this._loadSuggested(); return; }
    const id = this._thread;
    try {
      const page = await this._ws({ type: "console/chat/history", limit: PAGE, ...(id ? { thread_id: id } : {}) });
      if (id !== this._thread) return;
      if (force || page.working || page.total !== this._total) { if (page.total) this._show(page); else this._newChat(); }
    } catch (e) { /* still offline: the next "ready" tries again */ }
    this._loadSuggested();
  }

  async _toggleThreads(open) {
    const show = open === undefined ? this._threads.hidden : open;
    this._threads.hidden = !show;
    this._drawBar();
    if (!show) return;
    const rows = this._threads.querySelector(".rows");
    rows.replaceChildren(el("div", "none", "Loading…"));
    let threads = [];
    try { threads = (await this._ws({ type: "console/chat/threads" })).threads; } catch (e) { /* none to show */ }
    rows.replaceChildren();
    if (!threads.length) rows.appendChild(el("div", "none", "No chats yet. What you ask Console is kept here, on this box only."));
    for (const thread of threads) {
      const row = el("div", `thread${thread.id === this._thread ? " on" : ""}`);
      const open_ = el("button", "open"); open_.type = "button";
      open_.append(el("div", "t", thread.title || "Chat"), el("div", "s", `${thread.working ? "Working… · " : ""}${ago(thread.at)} · ${thread.last || ""}`));
      open_.addEventListener("click", () => this._open(thread.id));
      const x = el("button", "x", "✕"); x.type = "button"; x.title = "Delete this chat"; x.setAttribute("aria-label", `Delete the chat ${thread.title}`);
      x.addEventListener("click", async () => {
        if (!confirm(`Delete the chat “${thread.title || "Chat"}” from this box? It can't be brought back.`)) return;
        try { await this._ws({ type: "console/chat/thread/delete", thread_id: thread.id }); } catch (e) { /* gone already */ }
        if (thread.id === this._thread) this._newChat();
        this._toggleThreads(true);
      });
      row.append(open_, x);
      rows.appendChild(row);
    }
  }

  async _earlier() {
    if (!this._more || this._loading || !this._thread) return;
    this._loading = true;
    const seq = this._seq;
    try {
      const page = await this._ws({ type: "console/chat/history", thread_id: this._thread, before: this._from, limit: PAGE });
      if (seq === this._seq) {
        const first = this._log.querySelector(".turn");
        const height = this._log.scrollHeight;
        for (const message of page.messages) this._log.insertBefore(this._stored(message).node, first);
        this._from = page.from; this._more = page.more;
        this._drawBar();
        this._log.scrollTop = this._log.scrollHeight - height;   // stay where the person was reading
      }
    } catch (e) { /* nothing earlier to show */ }
    this._loading = false;
  }

  // --- one message on screen ----------------------------------------------------------------------

  _turn(who, text, opts = {}) {
    const node = el("div", `turn ${who}`);
    const bubble = el("div", `msg${opts.error ? " error" : ""}`);
    if (who === "me") bubble.textContent = text; else markdown(bubble, text);
    node.appendChild(bubble);
    const foot = el("div", "foot");
    const turn = { node, bubble, foot, text };
    if (who === "it") {
      const copy = el("button", "copy", "Copy"); copy.type = "button";
      copy.addEventListener("click", () => copyText(turn.text, copy));
      foot.appendChild(copy);
      node.appendChild(foot);
    }
    return turn;
  }

  // The work behind a reply: a line that opens into its steps. The same for a reply being written now
  // and for one read back from the thread.
  _work(turn) {
    const steps = el("details", "steps"), summary = el("summary"), list = el("div", "steplist");
    const dot = el("span", "dot"), label = el("span", "", "Working…");
    summary.append(dot, label); steps.append(summary, list);
    turn.node.insertBefore(steps, turn.bubble);
    const work = { steps, list, dot, label, count: 0, byKey: new Map(), thinking: null };
    work.add = (cls, title) => { const row = el("div", `step ${cls}`), t = el("div", "t", title), d = el("div", "d"); row.append(t, d); list.appendChild(row); work.count += 1; return { row, t, d }; };
    work.think = (text) => {
      if (!work.thinking) {
        const step = work.add("think", "Thinking"), more = el("button", "more", "Show all");
        step.full = ""; step.open = false; more.type = "button"; more.hidden = true;
        more.addEventListener("click", () => { step.open = !step.open; more.textContent = step.open ? "Show less" : "Show all"; step.d.textContent = step.open ? step.full : gist(step.full); });
        step.t.appendChild(more); step.more = more; work.thinking = step;
      }
      const thinking = work.thinking;
      thinking.full += text;
      if (!thinking.open) thinking.d.textContent = gist(thinking.full);
      thinking.more.hidden = gist(thinking.full) === thinking.full.replace(/\s+/g, " ").trim();
    };
    work.close = (meta, ms) => {
      dot.remove();
      const seconds = ms ? ` · ${(ms / 1000).toFixed(1)} s` : "";
      label.textContent = meta.route === "local" ? `Answered at home${seconds}` : `${work.count} step${work.count === 1 ? "" : "s"}${seconds}${meta.cost_usd ? ` · ${credits(meta.cost_usd)} credits` : ""}`;
      if (!work.count) steps.remove();
    };
    return work;
  }

  // A message as the box keeps it. Console's replies come with their steps.
  _stored(message) {
    if (message.who === "you") return this._turn("me", message.text);
    const turn = this._turn("it", message.text, { error: message.failed });
    const work = this._work(turn);
    for (const step of message.steps || []) {
      if (step.kind === "think") { work.thinking = null; work.think(step.detail || ""); continue; }
      work.thinking = null;
      const row = work.add(step.failed ? "failed" : "", step.title || "Step");
      row.d.textContent = [step.detail, step.result ? `→ ${step.result}` : ""].filter(Boolean).join("\n");
    }
    const meta = message.meta || {};
    work.close(meta, meta.ms);
    return turn;
  }

  _atBottom() { return this._log.scrollHeight - this._log.scrollTop - this._log.clientHeight < 60; }
  _follow(was) { if (was) this._log.scrollTop = this._log.scrollHeight; }
  _bottom() { this._log.scrollTop = this._log.scrollHeight; }

  // --- a turn as it happens -----------------------------------------------------------------------

  // The reply being written: its work as it happens, then its words. Returns what to do with each event.
  _live() {
    const seq = this._seq;
    const send = this.shadowRoot.querySelector("button.send");
    this._busy = true;
    send.disabled = true;
    const turn = this._turn("it", "");
    turn.bubble.hidden = true; turn.foot.hidden = true;
    const work = this._work(turn);
    this._log.appendChild(turn.node);
    this._bottom();
    const started = performance.now();
    let streamed = "", meta = {}, frame = 0, done = false;
    const paint = () => { frame = 0; const was = this._atBottom(); turn.bubble.hidden = !streamed; if (streamed) markdown(turn.bubble, streamed); this._follow(was); };
    const repaint = () => { if (!frame) frame = requestAnimationFrame(paint); };

    const finish = (event) => {
      if (done) return;
      done = true;
      if (frame) cancelAnimationFrame(frame);
      if (seq !== this._seq) return;   // the person moved to another chat: this reply is in its own thread
      const was = this._atBottom();
      turn.text = event.reply || streamed || "Done.";
      markdown(turn.bubble, turn.text);
      turn.bubble.hidden = false; turn.foot.hidden = false;
      if (event.error) turn.bubble.classList.add("error");
      if (event.thread_id) this._setThread(event.thread_id);
      work.close(meta, event.ms || performance.now() - started);
      this._busy = false; send.disabled = false;
      this._total += 2;
      if (this._stop) { try { this._stop(); } catch (e) { /* already closed */ } this._stop = null; }
      this._follow(was);
      this._drawBar();
      this._loadSuggested();   // the house may look different now: what's worth suggesting too
    };

    const onEvent = (event) => {
      if (seq !== this._seq || done) return;
      const was = this._atBottom();
      if (event.kind === "thread") { this._setThread(event.thread_id); this._drawBar(); }
      else if (event.kind === "step") {
        let step = work.byKey.get(event.key);
        if (!step) { step = work.add("", event.title || "Step"); work.byKey.set(event.key, step); if (event.detail) step.d.textContent = event.detail; }
        if (event.result) step.d.textContent = (step.d.textContent ? step.d.textContent + "\n→ " : "") + event.result;
        if (event.state === "failed") step.row.classList.add("failed");
        if (event.title) work.label.textContent = event.title + (event.state === "running" ? "…" : "");
        work.thinking = null;
      } else if (event.kind === "thinking") { if (!work.thinking) work.label.textContent = "Thinking…"; work.think(event.text); }
      else if (event.kind === "said") { const said = work.add("", "Said"); said.d.textContent = event.text; streamed = ""; repaint(); work.thinking = null; }
      else if (event.kind === "text") { streamed += event.text; work.label.textContent = "Writing…"; repaint(); work.thinking = null; }
      else if (event.kind === "reset") { streamed = ""; repaint(); }
      else if (event.kind === "meta") { meta = event; }
      else if (event.kind === "done") { finish(event); }
      else if (event.kind === "gone") { done = true; turn.node.remove(); this._busy = false; send.disabled = false; this._resync(true); }   // it ended a moment ago: read the thread
      this._follow(was);
    };
    return { onEvent, finish, seq };
  }

  // One message is one turn: `resubscribe: false` keeps Home Assistant from sending the command again
  // when the connection comes back. The "ready" listener reads the chat from the box instead.
  async _subscribe(live, message) {
    try {
      const stop = await this._hass.connection.subscribeMessage(live.onEvent, message, { resubscribe: false });
      if (live.seq === this._seq && this._busy) this._stop = stop; else { try { stop(); } catch (e) { /* already closed */ } }
    } catch (error) {
      live.finish({ reply: error && error.code === "busy" ? String(error.message) : "I couldn't reach Console's agent in Home Assistant. Try again in a moment.", error: true });
    }
  }

  async _send(text) {
    if (this._busy || !this._hass) return;
    const was = this._title;
    this._hello.remove();
    this._log.appendChild(this._turn("me", text).node);
    if (!this._thread) this._title = text.length > 60 ? `${text.slice(0, 59).trimEnd()}…` : text;
    const live = this._live();
    this._drawBar();
    await this._subscribe(live, { type: "console/chat", text, thread_id: this._thread });
    if (!this._thread && !this._busy) this._title = was;
  }

  // A turn already running in this chat (the card reloaded, reconnected, or opened it on another screen).
  _watch() {
    this._subscribe(this._live(), { type: "console/chat/watch", thread_id: this._thread });
  }
}

// Home Assistant swaps in its own element registry while it starts. A card that registered before the
// swap is gone afterwards, and the dashboard shows "Configuration error" in its place. So: register,
// then look again a few times and register again if the card has been dropped.
const NAME = "console-chat-card";
function register() {
  if (customElements.get(NAME)) return;
  try { customElements.define(NAME, class extends ConsoleChatCard {}); } catch (e) { /* another copy got there first */ }
}
register();
for (const wait of [0, 300, 1000, 2500, 6000, 15000]) setTimeout(register, wait);
window.addEventListener("load", register);
document.addEventListener("visibilitychange", register);

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === NAME)) {
  window.customCards.push({
    type: "console-chat-card",
    name: "Console chat",
    description: "Talk to Console, this home's agent: your chats as threads with the work behind each reply, suggestions to tap, and quick actions.",
    preview: false,
  });
}
