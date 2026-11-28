// Console chat card: talk to Console, this home's agent, from a dashboard.
//
// The card lists your conversations the way a collapsed comment thread looks: what you asked, and under it
// one line peeking at Console's latest reply. Tap a conversation and the whole thread opens in a drawer
// (from the side on a wide card, from the bottom on a phone): what started it, every reply indented under
// it, the work behind each of Console's replies a tap away, and a box to reply in (owner, 2026-11-28:
// "facebook comment threads", "within a drawer though. not completely visible").
//
// Several agents can run at once, each in its own conversation: start one, start another, reply in a
// third, and close the drawer while they work. Each conversation has a dot: pulsing while its agent works,
// red when it ended in an error, green when it finished with a reply you haven't opened. Opening it clears
// the dot, on every device (console/chat/seen). The card hears turns start and finish from anywhere
// (console/chat/status), so a conversation started on another screen shows up here too.
//
// Where you write says what Console may draw on: the box at the bottom starts a new conversation, which is
// told about your other recent ones; a reply in the drawer stays inside its conversation. One conversation,
// or all of them, can be copied out as text.
//
// Everything said is kept on the box (never in this card, never off the box). One message is one turn: the
// chat command is never sent again when the connection comes back (resubscribe: false). A turn runs on the
// box whoever is listening, so a card that reloads or reconnects watches it (console/chat/watch) or finds
// the reply in its conversation.
//
// Above the box: always three suggestions, each a tap that runs something now. Under it: quick actions,
// the suggestions this household keeps using (suggestions.py).
const SENSOR = "sensor.console_cloud_agent";
const THREADS = 8;   // conversations loaded at a time
const PAGE = 10;     // earlier replies loaded at a time
const REFRESH_MS = 5 * 60 * 1000;
const AGENT = "Console";
const WIDE = 720;    // a card at least this wide opens the drawer from the side
const STATUS_WORDS = { working: "Working", done: "New reply", error: "Didn't finish" };

const STYLE = `
  :host { display: block; height: 100%; }
  [hidden] { display: none !important; }
  ha-card { display: flex; flex-direction: column; height: 100%; min-height: var(--console-chat-height, 420px); overflow: hidden; position: relative; }
  .banner { padding: 10px 16px; font-size: 14px; line-height: 20px; }
  .banner.warn { background: color-mix(in srgb, var(--warning-color, #ffa600) 18%, transparent); }
  .banner.stop { background: color-mix(in srgb, var(--error-color, #db4437) 18%, transparent); }
  .banner.offline, .banner.off { background: color-mix(in srgb, var(--secondary-text-color, #888) 16%, transparent); }
  .banner.support { background: color-mix(in srgb, var(--warning-color, #ffa600) 26%, transparent); }
  .banner a { color: var(--primary-color); cursor: pointer; text-decoration: underline; white-space: nowrap; }
  .bar { display: flex; align-items: center; gap: 8px; padding: 8px 14px; border-bottom: 1px solid var(--divider-color); }
  .bar .name { font-size: 14px; font-weight: 600; color: var(--primary-text-color); }
  .bar .tally { flex: 1; display: flex; gap: 10px; flex-wrap: wrap; font-size: 12px; color: var(--secondary-text-color); }
  .bar .tally span { display: inline-flex; align-items: center; gap: 5px; }
  .bar button { font: inherit; font-size: 13px; padding: 4px 12px; border-radius: 14px; border: 1px solid var(--divider-color); background: none; color: var(--primary-color); cursor: pointer; }
  .log { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 14px 8px; display: flex; flex-direction: column; gap: 16px; overscroll-behavior: contain; }
  .older { align-self: center; font: inherit; font-size: 13px; font-weight: 600; border: 0; background: none; color: var(--secondary-text-color); cursor: pointer; padding: 2px 6px; }
  .older:hover, .more:hover { text-decoration: underline; }
  .hello { color: var(--secondary-text-color); font-size: 14px; line-height: 20px; }
  .thread { display: flex; flex-direction: column; gap: 6px; }
  .c { display: flex; gap: 8px; align-items: flex-start; position: relative; }
  .av { flex: none; width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 600; user-select: none; }
  .av.me { background: color-mix(in srgb, var(--primary-text-color) 13%, var(--card-background-color, #fff)); color: var(--primary-text-color); }
  .av.it { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .col { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; }
  .bubble { max-width: 100%; box-sizing: border-box; padding: 7px 12px 8px; border-radius: 18px; background: var(--secondary-background-color); }
  .bubble.error { box-shadow: inset 0 0 0 1px var(--error-color, #db4437); }
  .who { font-size: 13px; font-weight: 600; line-height: 17px; color: var(--primary-text-color); }
  .msg { font-size: 15px; line-height: 21px; color: var(--primary-text-color); overflow-wrap: anywhere; user-select: text; -webkit-user-select: text; cursor: text; }
  .me .msg { white-space: pre-wrap; }
  .msg > :first-child { margin-top: 0; } .msg > :last-child { margin-bottom: 0; }
  .msg p { margin: 0 0 8px; } .msg ul, .msg ol { margin: 0 0 8px; padding-left: 22px; } .msg li { margin: 2px 0; }
  .msg h3, .msg h4 { margin: 10px 0 6px; font-size: 15px; font-weight: 700; }
  .msg blockquote { margin: 0 0 8px; padding-left: 10px; border-left: 3px solid var(--divider-color); color: var(--secondary-text-color); }
  .msg code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; background: color-mix(in srgb, var(--primary-text-color) 10%, transparent); padding: 1px 5px; border-radius: 5px; }
  .msg a { color: var(--primary-color); }
  .code { position: relative; margin: 0 0 8px; }
  .code pre { margin: 0; padding: 10px 12px; border-radius: 10px; background: color-mix(in srgb, var(--primary-text-color) 9%, transparent); overflow-x: auto; white-space: pre-wrap; word-break: break-word; }
  .code pre code { background: none; padding: 0; }
  .copy { font: inherit; font-size: 12px; padding: 3px 9px; border-radius: 12px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-color); cursor: pointer; }
  .code .copy { position: absolute; top: 6px; right: 6px; }
  .meta { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 12px; padding: 3px 12px 0; font-size: 12px; line-height: 16px; color: var(--secondary-text-color); }
  .meta button { border: 0; background: none; padding: 0; font: inherit; font-weight: 600; color: var(--secondary-text-color); cursor: pointer; }
  .meta button:hover { text-decoration: underline; }
  .meta button[aria-expanded="true"] { color: var(--primary-text-color); }
  .meta .live { display: inline-flex; align-items: center; gap: 6px; }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--primary-color); animation: pulse 1s ease-in-out infinite; }
  .typing { display: inline-flex; gap: 4px; padding: 6px 0 2px; }
  .typing i { width: 7px; height: 7px; border-radius: 50%; background: var(--secondary-text-color); animation: pulse 1.2s ease-in-out infinite; }
  .typing i:nth-child(2) { animation-delay: .2s; } .typing i:nth-child(3) { animation-delay: .4s; }
  @keyframes pulse { 0%, 100% { opacity: .25; } 50% { opacity: 1; } }
  @media (prefers-reduced-motion: reduce) { .dot, .typing i { animation: none; } }
  /* status dots: working (pulsing), done with a reply not yet opened, error not yet opened */
  .sdot { flex: none; width: 9px; height: 9px; border-radius: 50%; }
  .sdot.working { background: var(--primary-color); animation: pulse 1s ease-in-out infinite; }
  .sdot.done { background: var(--success-color, #43a047); }
  .sdot.error { background: var(--error-color, #db4437); }
  .av { position: relative; }
  .av .sdot { position: absolute; top: -2px; right: -3px; width: 10px; height: 10px; box-shadow: 0 0 0 2px var(--card-background-color, #fff); }
  /* a conversation in the list: what was asked, and one line peeking at the latest reply */
  .convo .c.root .msg { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  .peek { display: flex; align-items: center; gap: 8px; width: 100%; min-width: 0; padding: 4px 10px 4px 4px; border: 0; border-radius: 14px; background: none; font: inherit; text-align: left; cursor: pointer; color: var(--primary-text-color); }
  .peek:hover { background: color-mix(in srgb, var(--primary-text-color) 6%, transparent); }
  .peek .line { flex: 1; min-width: 0; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .peek .line b { font-weight: 600; }
  .peek .line.error { color: var(--error-color, #db4437); }
  .peek .line.working { color: var(--secondary-text-color); }
  .peek .count { flex: none; font-size: 12px; font-weight: 600; color: var(--secondary-text-color); }
  .convo.unread .peek .line { font-weight: 600; }
  /* the drawer: one conversation, whole */
  .scrim { position: absolute; inset: 0; z-index: 3; background: rgba(0, 0, 0, .32); opacity: 0; transition: opacity .2s; }
  .drawer { position: absolute; z-index: 4; display: flex; flex-direction: column; background: var(--card-background-color, #fff); box-shadow: 0 8px 28px rgba(0, 0, 0, .28); transition: transform .22s ease; }
  .drawer.bottom { left: 0; right: 0; bottom: 0; height: 92%; border-radius: 16px 16px 0 0; transform: translateY(100%); }
  .drawer.side { top: 0; right: 0; bottom: 0; width: min(520px, 62%); border-radius: 16px 0 0 16px; transform: translateX(100%); }
  .open .scrim { opacity: 1; }
  .open .drawer { transform: none; }
  @media (prefers-reduced-motion: reduce) { .scrim, .drawer { transition: none; } }
  .drawer .grab { align-self: center; width: 36px; height: 4px; border-radius: 2px; background: var(--divider-color); margin: 8px 0 0; }
  .drawer.side .grab { display: none; }
  .dhead { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--divider-color); }
  .dhead .title { flex: 1; min-width: 0; font-size: 15px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--primary-text-color); }
  .dhead .state { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; }
  .dhead button { flex: none; font: inherit; font-size: 13px; padding: 4px 10px; border-radius: 14px; border: 1px solid var(--divider-color); background: none; color: var(--primary-color); cursor: pointer; }
  .dhead button.shut { border: 0; font-size: 18px; line-height: 1; padding: 4px 6px; color: var(--secondary-text-color); }
  .dbody { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; overscroll-behavior: contain; }
  .dcompose { border-top: 1px solid var(--divider-color); padding: 8px 12px 10px; }
  /* the replies, under what started the conversation, joined to it by a line */
  .replies { position: relative; margin-left: 40px; }
  .rlist { display: flex; flex-direction: column; gap: 6px; }
  .replies .av { width: 24px; height: 24px; font-size: 11px; }
  .thread.joined > .c.root::after { content: ""; position: absolute; left: 15px; top: 36px; bottom: -6px; border-left: 2px solid var(--divider-color); }
  .rlist > *::before { content: ""; position: absolute; left: -25px; top: -6px; width: 19px; height: 18px; border-left: 2px solid var(--divider-color); border-bottom: 2px solid var(--divider-color); border-bottom-left-radius: 10px; }
  .rlist > :not(:last-child)::after { content: ""; position: absolute; left: -25px; top: -6px; bottom: -6px; border-left: 2px solid var(--divider-color); }
  .rlist > * { position: relative; }
  .more { font: inherit; font-size: 13px; font-weight: 600; border: 0; background: none; color: var(--secondary-text-color); cursor: pointer; padding: 3px 0; text-align: left; }
  .work { margin: 6px 0 2px 12px; padding-left: 10px; border-left: 2px solid var(--divider-color); display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--secondary-text-color); max-width: 100%; box-sizing: border-box; }
  .step .t { color: var(--primary-text-color); font-size: 13px; }
  .step.failed .t { color: var(--error-color, #db4437); }
  .step .d { white-space: pre-wrap; overflow-wrap: anywhere; user-select: text; -webkit-user-select: text; }
  .step.think .d { font-style: italic; }
  .step .all { font: inherit; font-size: 11px; margin-left: 8px; padding: 0; border: 0; background: none; color: var(--primary-color); text-decoration: underline; cursor: pointer; }
  .compose form { flex: 1; min-width: 0; display: flex; gap: 6px; align-items: flex-end; padding: 0; }
  .compose textarea { min-height: 34px; padding: 7px 12px; border-radius: 17px; font-size: 14px; }
  .compose button { height: 34px; padding: 0 14px; border-radius: 17px; border: 0; background: var(--primary-color); color: var(--text-primary-color, #fff); font: inherit; font-size: 13px; font-weight: 600; cursor: pointer; }
  .compose button[disabled] { opacity: .5; cursor: default; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .strip { padding: 8px 12px 0; }
  .strip.quick { padding: 0 12px 10px; }
  .strip .row { display: flex; gap: 6px 8px; min-width: 0; }
  .strip.suggested .row { flex-wrap: wrap; }
  .strip.quick .row { overflow-x: auto; padding-bottom: 2px; scrollbar-width: thin; }
  .chip { display: inline-flex; align-items: center; flex: none; max-width: 100%; border: 1px solid var(--divider-color); border-radius: 16px; font-size: 13px; background: none; color: var(--primary-text-color); font-family: inherit; white-space: nowrap; }
  button.chip, .chip .go { cursor: pointer; }
  button.chip { padding: 6px 12px; }
  .chip .go { border: 0; background: none; color: inherit; font: inherit; padding: 6px 12px; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .chip .x { border: 0; background: none; color: var(--secondary-text-color); cursor: pointer; font-size: 13px; padding: 0 9px 0 0; }
  .chip.quick { border-color: color-mix(in srgb, var(--primary-color) 55%, var(--divider-color)); background: color-mix(in srgb, var(--primary-color) 9%, transparent); }
  form.new { display: flex; gap: 8px; padding: 8px 12px 10px; align-items: flex-end; }
  textarea { flex: 1; min-width: 0; min-height: 42px; max-height: 140px; padding: 10px 14px; border-radius: 21px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); font: inherit; font-size: 15px; line-height: 20px; resize: none; box-sizing: border-box; }
  textarea:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
  button.send { height: 42px; padding: 0 18px; border-radius: 21px; border: 0; background: var(--primary-color); color: var(--text-primary-color, #fff); font: inherit; font-weight: 600; cursor: pointer; }
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

// How long ago, the short way comment threads say it: "now", "4m", "2h", "3d", then the date.
const ago = (iso) => {
  if (!iso) return "now";
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)}h`;
  if (minutes < 7 * 24 * 60) return `${Math.round(minutes / 1440)}d`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
};
const grow = (area, max) => { area.style.height = "auto"; area.style.height = `${Math.min(area.scrollHeight + 2, max)}px`; };

class ConsoleChatCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._loaded = false;      // the first read of the box is done
    this._banner = "";
    this._threads = new Map(); // conversation id -> what this card knows of it
    this._skip = 0;            // conversations loaded so far (they load newest first)
    this._older = false;       // whether the box holds older conversations
    this._drawer = null;       // the conversation open in the drawer
    this._drafts = new Map();  // what was typed in a conversation's reply box, by conversation
    this._counts = { working: 0, done: 0, error: 0 };
    this._tmp = 0;
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
    if (!this._timer) this._timer = setInterval(() => { if (document.visibilityState === "visible") this._loadSuggested(); }, REFRESH_MS);
    if (!this._onVisible) {
      this._onVisible = () => { if (document.visibilityState === "visible" && this._loaded && !this._anyLive()) this._loadFeed(); };
      document.addEventListener("visibilitychange", this._onVisible);
    }
  }

  disconnectedCallback() {
    clearInterval(this._timer); this._timer = null;
    if (this._onVisible) { document.removeEventListener("visibilitychange", this._onVisible); this._onVisible = null; }
  }

  _ws(message) { return this._hass.callWS(message); }
  get _me() { return (this._hass && this._hass.user && this._hass.user.name) || "You"; }
  _anyLive() { return [...this._threads.values()].some((t) => t.live); }

  async _start() {
    // When the connection to Home Assistant comes back (the phone woke up, the Wi-Fi returned), read the
    // conversations again from the box: turns that were running went on without this card.
    this._hass.connection.addEventListener("ready", () => { if (this._loaded) this._loadFeed(); });
    try { this._welcome = (await this._ws({ type: "console/status" })).onboarding || {}; } catch (e) { this._welcome = {}; }
    this._loadSuggested();
    await this._loadFeed();
    this._loaded = true;
    // Conversations starting and finishing anywhere (another card, another device): their dots, and their rows.
    try { await this._hass.connection.subscribeMessage((event) => this._onStatus(event), { type: "console/chat/status" }); } catch (e) { /* an older Console on the box */ }
  }

  _build() {
    const root = this.shadowRoot;
    root.innerHTML = `<style>${STYLE}</style>
      <ha-card>
        <div class="banner" hidden></div>
        <div class="bar"><span class="name">Conversations</span><span class="tally" aria-live="polite"></span><button class="all" type="button" title="Copy all your conversations as text">Copy all</button></div>
        <div class="log" role="log"><button class="older" type="button" hidden>View earlier conversations</button><div class="hello" hidden></div></div>
        <div class="strip suggested" hidden><div class="row" role="group" aria-label="Suggestions"></div></div>
        <form class="new"><textarea rows="1" placeholder="Start a new conversation" aria-label="Start a new conversation with Console" enterkeyhint="send"></textarea>
        <button class="send" type="submit">Send</button></form>
        <div class="strip quick" hidden><div class="row" role="group" aria-label="Quick actions"></div></div>
      </ha-card>`;
    if (this._config.title) root.querySelector("ha-card").setAttribute("header", this._config.title);
    this._card = root.querySelector("ha-card");
    this._log = root.querySelector(".log");
    this._olderButton = root.querySelector(".older");
    this._hello = root.querySelector(".hello");
    this._tally = root.querySelector(".tally");
    this._suggestedRow = root.querySelector(".strip.suggested");
    this._quickRow = root.querySelector(".strip.quick");
    const area = root.querySelector("form.new textarea");
    const submit = () => { const text = area.value.trim(); if (text && this._loaded) { area.value = ""; area.style.height = ""; this._send(text, null); } };
    root.querySelector("form.new").addEventListener("submit", (event) => { event.preventDefault(); submit(); });
    area.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); } });
    area.addEventListener("input", () => grow(area, 140));
    const all = root.querySelector(".bar .all");
    all.addEventListener("click", () => this._copy(null, all));
    this._olderButton.addEventListener("click", () => this._loadOlder());
    this._log.addEventListener("wheel", (event) => { if (event.deltaY < 0 && this._log.scrollTop < 2) this._loadOlder(); }, { passive: true });
    root.addEventListener("keydown", (event) => { if (event.key === "Escape" && this._drawer) this._closeDrawer(); });
    // A suggestion counts as seen when it is really on screen, not when the dashboard merely holds this card.
    if (window.IntersectionObserver) new IntersectionObserver((entries) => { this._onScreen = entries.some((entry) => entry.isIntersecting); this._seen(); }).observe(this._suggestedRow);
    else this._onScreen = true;
    this._drawTally();
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

  // The dots in the bar: across all of this person's conversations, loaded here or not.
  _drawTally() {
    const c = this._counts;
    const parts = [["working", `${c.working} working`], ["done", `${c.done} new`], ["error", `${c.error} didn't finish`]].filter(([key]) => c[key]);
    this._tally.replaceChildren(...parts.map(([key, words]) => { const span = el("span"); span.append(el("span", `sdot ${key}`), el("span", "", words)); return span; }));
  }

  _setCounts(counts) { if (counts) { this._counts = { working: 0, done: 0, error: 0, ...counts }; this._drawTally(); } }

  _drawHello() {
    const empty = !this._threads.size;
    this._hello.hidden = !empty;
    this.shadowRoot.querySelector(".bar .all").hidden = empty;
    if (!empty) return;
    this._hello.replaceChildren();
    const welcome = this._welcome || {};
    if (welcome.available && !welcome.offered && !welcome.done) {
      const offer = el("div", "bubble");
      offer.append(el("div", "who", AGENT), el("div", "msg", "Welcome. I'm Console, this home's agent. Want me to show you around? I'll learn your rooms and devices, add anything that's waiting, and set up one routine with you. It takes a few minutes and you can stop any time."));
      offer.style.marginBottom = "10px";
      this._hello.appendChild(offer);
    } else {
      this._hello.appendChild(el("div", "", "Ask for anything in your home: “turn off the kitchen lights”, “play jazz in the kitchen”, “add a dashboard for the kids' room”. Each thing you ask starts a conversation, and several can run at once; tap one to open it and reply. Or tap a suggestion below."));
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
        if (text) this._send(text, null); else this._drawHello();
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

  // A tap goes into the conversation open in the drawer, or starts one of its own.
  async _tap(item) {
    if (!this._loaded) return;
    const into = this._drawer && this._threads.has(this._drawer.id) ? this._drawer.id : null;
    if (into && this._threads.get(into).live) return;
    let done = null, failed = null;
    try { done = await this._ws({ type: "console/suggestions/tap", suggestion_id: item.id, thread_id: into }); } catch (e) { failed = String(e.message || e); }
    if (done && done.ask) { this._send(done.ask, into); this._loadSuggested(); return; }   // something to ask: sent like any message
    const now = new Date().toISOString();
    const said = { who: "you", text: `Run “${item.name}”`, at: now };
    const answer = done
      ? { who: "console", text: done.reply, at: now, steps: [{ title: "Ran at home", detail: "A tap on a suggestion: no AI, no internet." }], meta: { route: "local" } }
      : { who: "console", text: failed, failed: true, at: now };
    const id = (done && done.thread_id) || into;
    let thread = id && this._threads.get(id);
    if (thread) { this._push(thread, said); this._push(thread, answer); }
    else { thread = this._addThread({ id: id || `local-${++this._tmp}`, title: said.text, root: said, replies: [answer], from: 1, total: 2, status: "" }); this._bottom(); }
    this._loadSuggested();
  }

  async _dismiss(item) {
    try { await this._ws({ type: "console/suggestions/dismiss", suggestion_id: item.id }); } catch (e) { /* it's gone already */ }
    this._loadSuggested();
  }

  // --- the list of conversations ------------------------------------------------------------------

  // The newest conversations from the box, drawn again from scratch: on start, after a reconnect, and when
  // the page comes back into view. A conversation open in the drawer stays open, with what was typed.
  async _loadFeed() {
    let got;
    try { got = await this._ws({ type: "console/chat/feed", limit: Math.max(THREADS, this._skip) }); } catch (e) { this._drawHello(); return; }
    const open = this._drawer && this._drawer.id;
    if (this._drawer) this._closeDrawer(true);
    for (const thread of this._threads.values()) { this._stopLive(thread); thread.row.remove(); }
    this._threads.clear();
    for (const item of got.threads.slice().reverse()) this._addThread(item);
    this._skip = got.threads.length;
    this._older = got.more;
    this._olderButton.hidden = !this._older;
    this._setCounts(got.counts);
    this._drawHello();
    this._bottom();
    if (open && this._threads.has(open)) this._openDrawer(open, false, true);
  }

  async _loadOlder() {
    if (!this._older || this._loadingOlder) return;
    this._loadingOlder = true;
    try {
      const got = await this._ws({ type: "console/chat/feed", skip: this._skip, limit: THREADS });
      const height = this._log.scrollHeight;
      for (const item of got.threads) if (!this._threads.has(item.id)) this._addThread(item, true);
      this._skip += got.threads.length;
      this._older = got.more;
      this._olderButton.hidden = !this._older;
      this._log.scrollTop = this._log.scrollHeight - height;   // stay where the person was reading
    } catch (e) { /* nothing older to show */ }
    this._loadingOlder = false;
  }

  _addThread(item, atTop) {
    const thread = { id: item.id, title: item.title, root: item.root || { who: "you", text: item.title }, replies: [...(item.replies || [])],
                     from: item.from || 1, total: item.total || 1, status: item.status || "", live: null, pending: null, row: el("div", "thread convo") };
    thread.row.dataset.id = thread.id;
    this._threads.set(thread.id, thread);
    if (atTop) this._olderButton.after(thread.row); else this._log.appendChild(thread.row);
    this._drawRow(thread);
    if (item.working) this._watch(thread);
    this._drawHello();
    return thread;
  }

  // A conversation in the list: what was asked, and under it one line peeking at where it stands.
  _drawRow(thread) {
    const row = thread.row;
    row.replaceChildren();
    row.classList.toggle("unread", thread.status === "done" || thread.status === "error");
    const root = this._comment(thread.root, thread, true, true);
    const replies = el("div", "replies"), rlist = el("div", "rlist");
    const peek = el("button", "peek"); peek.type = "button";
    const av = el("span", "av it", AGENT.slice(0, 1)); av.setAttribute("aria-hidden", "true");
    const status = thread.live ? "working" : thread.status;
    if (status) av.appendChild(el("span", `sdot ${status}`));
    const last = [...thread.replies].reverse().find((m) => m.who === "console");
    const line = el("span", `line${status === "error" ? " error" : ""}${thread.live ? " working" : ""}`);
    if (thread.live) line.textContent = `${AGENT} · ${thread.liveLabel || "Working…"}`;
    else if (last) { line.append(el("b", "", `${status === "error" ? "Didn't finish" : AGENT}: `), document.createTextNode(String(last.text || "").replace(/[*_`#>]+/g, "").replace(/\s+/g, " "))); }
    else line.textContent = "No reply yet";
    const replyCount = Math.max(0, thread.total - 1);
    peek.append(av, line);
    if (replyCount) peek.appendChild(el("span", "count", `${replyCount} repl${replyCount === 1 ? "y" : "ies"}`));
    peek.setAttribute("aria-label", `Open the conversation “${thread.title || ""}”${status ? `: ${STATUS_WORDS[status]}` : ""}`);
    peek.addEventListener("click", () => this._openDrawer(thread.id, false));
    rlist.appendChild(peek);
    replies.appendChild(rlist);
    row.append(root.node, replies);
    row.classList.add("joined");
  }

  // A message joins a conversation: in the list's peek, and in the drawer when it's open there.
  _push(thread, message) {
    thread.replies.push(message);
    thread.total += 1;
    if (this._drawer && this._drawer.id === thread.id) this._drawerAdd(this._comment(message, thread, false).node);
    this._drawRow(thread);
  }

  // A conversation started here gets its real id from the box's first event.
  _rekey(thread, id) {
    if (!id || thread.id === id) return;
    this._threads.delete(thread.id);
    if (this._drawer && this._drawer.id === thread.id) this._drawer.id = id;
    thread.id = id;
    thread.row.dataset.id = id;
    this._threads.set(id, thread);
  }

  // A conversation started or finished somewhere: its dot here, and its row when another card or device did it.
  async _onStatus(event) {
    if (!event || event.kind !== "status") return;
    this._setCounts(event.counts);
    const thread = this._threads.get(event.thread_id);
    if (thread && thread.live) return;   // this card is following that turn itself
    if (event.status === "working") {
      if (thread) { this._watch(thread); return; }
      const got = await this._fetchOne(event.thread_id);
      if (got && !this._threads.has(got.id)) { const fresh = this._addThread(got); this._bottom(); if (!got.working) this._watch(fresh); }
      return;
    }
    if (thread && event.status === "") { thread.status = ""; this._drawRow(thread); if (this._drawer && this._drawer.id === thread.id) this._drawDrawerState(); return; }
    if (thread) this._refresh(thread);
  }

  async _fetchOne(id) {
    try { return (await this._ws({ type: "console/chat/feed", thread_id: id })).threads[0] || null; } catch (e) { return null; }
  }

  // One conversation, read again from the box: its row, and the drawer if it's open there.
  async _refresh(thread) {
    const got = await this._fetchOne(thread.id);
    if (!got) return;
    Object.assign(thread, { title: got.title, root: got.root, replies: got.replies, from: got.from, total: got.total, status: got.working ? "working" : got.status });
    this._drawRow(thread);
    if (this._drawer && this._drawer.id === thread.id) this._openDrawer(thread.id, false, true);
    if (got.working && !thread.live) this._watch(thread);
  }

  async _copy(id, button) {
    try {
      const got = await this._ws({ type: "console/chat/export", ...(id ? { thread_id: id } : {}) });
      await copyText(got.text, button);
    } catch (e) { if (button) { const was = button.textContent; button.textContent = "Couldn't copy"; setTimeout(() => { button.textContent = was; }, 1400); } }
  }

  async _delete(thread) {
    if (!confirm(`Delete the conversation “${thread.title || "this conversation"}” from this box? It can't be brought back.`)) return;
    try { await this._ws({ type: "console/chat/thread/delete", thread_id: thread.id }); } catch (e) { return; }
    this._stopLive(thread);
    if (this._drawer && this._drawer.id === thread.id) this._closeDrawer();
    thread.row.remove();
    this._threads.delete(thread.id);
    this._skip = Math.max(0, this._skip - 1);
    this._drawHello();
  }

  _atBottom() { return this._log.scrollHeight - this._log.scrollTop - this._log.clientHeight < 80; }
  _bottom() { this._log.scrollTop = this._log.scrollHeight; }

  // --- the drawer: one conversation, whole ----------------------------------------------------------

  _openDrawer(id, focus, keep) {
    const thread = this._threads.get(id);
    if (!thread) return;
    const draft = this._drawer && this._drawer.area ? this._drawer.area.value : null;
    if (this._drawer && this._drawer.id !== id && draft !== null) this._drafts.set(this._drawer.id, draft);
    if (this._drawer) this._closeDrawer(true);
    const wrap = el("div", "drawer-wrap"), scrim = el("div", "scrim"), sheet = el("div", `drawer ${this._card.clientWidth >= WIDE ? "side" : "bottom"}`);
    sheet.setAttribute("role", "dialog"); sheet.setAttribute("aria-label", `Conversation: ${thread.title || ""}`);
    scrim.addEventListener("click", () => this._closeDrawer());
    const head = el("div", "dhead"), shut = el("button", "shut", "✕"), title = el("span", "title", thread.title || "Conversation"), state = el("span", "state");
    shut.type = "button"; shut.setAttribute("aria-label", "Close"); shut.addEventListener("click", () => this._closeDrawer());
    const copy = el("button", "", "Copy"); copy.type = "button"; copy.title = "Copy conversation as text"; copy.addEventListener("click", () => this._copy(thread.id, copy));
    const del = el("button", "", "Delete"); del.type = "button"; del.title = "Delete this conversation"; del.addEventListener("click", () => this._delete(thread));
    head.append(shut, title, state, copy, del);
    const dbody = el("div", "dbody thread");
    const root = this._comment(thread.root, thread, true);
    const replies = el("div", "replies"), rlist = el("div", "rlist");
    replies.appendChild(rlist);
    dbody.append(root.node, replies);
    const compose = el("div", "dcompose"), row = el("div", "c compose");
    const av = el("div", "av me", this._me.slice(0, 1).toUpperCase()); av.setAttribute("aria-hidden", "true");
    const form = el("form"), area = el("textarea"), button = el("button", "", "Reply");
    area.rows = 1; area.placeholder = "Reply in this conversation"; area.setAttribute("aria-label", "Reply in this conversation");
    area.value = this._drafts.get(id) || "";
    button.type = "submit";
    form.append(area, button); row.append(av, form); compose.appendChild(row);
    const submit = () => { const text = area.value.trim(); if (!text || thread.live) return; area.value = ""; area.style.height = ""; this._drafts.delete(thread.id); this._send(text, thread.id); };
    form.addEventListener("submit", (event) => { event.preventDefault(); submit(); });
    area.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); } });
    area.addEventListener("input", () => { this._drafts.set(thread.id, area.value); grow(area, 120); });
    sheet.append(el("div", "grab"), head, dbody, compose);
    wrap.append(scrim, sheet);
    this._card.appendChild(wrap);
    this._drawer = { id: thread.id, wrap, sheet, dbody, rlist, root, state, area, button, more: null };
    this._earlierLink(thread);
    for (const message of thread.replies) rlist.appendChild(this._comment(message, thread, false).node);
    if (thread.pending) rlist.appendChild(thread.pending.node);
    this._drawDrawerState();
    dbody.classList.toggle("joined", !!(thread.replies.length || thread.pending || thread.from > 1));
    requestAnimationFrame(() => { wrap.classList.add("open"); dbody.scrollTop = dbody.scrollHeight; if (focus || !keep) area.focus({ preventScroll: true }); });
    if (keep) wrap.classList.add("open");
    this._markSeen(thread);
  }

  _closeDrawer(instant) {
    const drawer = this._drawer;
    if (!drawer) return;
    if (drawer.area) this._drafts.set(drawer.id, drawer.area.value);
    this._drawer = null;
    if (instant) { drawer.wrap.remove(); return; }
    drawer.wrap.classList.remove("open");
    setTimeout(() => drawer.wrap.remove(), 230);
  }

  _drawerAdd(node) {
    const drawer = this._drawer;
    const was = drawer.dbody.scrollHeight - drawer.dbody.scrollTop - drawer.dbody.clientHeight < 80;
    drawer.rlist.appendChild(node);
    drawer.dbody.classList.add("joined");
    if (was) drawer.dbody.scrollTop = drawer.dbody.scrollHeight;
  }

  _drawDrawerState() {
    const drawer = this._drawer, thread = drawer && this._threads.get(drawer.id);
    if (!thread) return;
    const status = thread.live ? "working" : "";
    drawer.state.replaceChildren();
    if (status) drawer.state.append(el("span", "sdot working"), el("span", "", thread.liveLabel || "Working…"));
    drawer.button.disabled = !!thread.live;
  }

  // Opened: a finished conversation's dot goes, here and on every other card.
  async _markSeen(thread) {
    if (thread.status !== "done" && thread.status !== "error") return;
    thread.status = "";
    this._drawRow(thread);
    if (thread.id.startsWith("local-")) return;
    try { this._setCounts((await this._ws({ type: "console/chat/seen", thread_id: thread.id })).counts); } catch (e) { /* the next load shows it */ }
  }

  // "View N earlier replies": the replies before the ones shown, a page at a time.
  _earlierLink(thread) {
    const drawer = this._drawer;
    if (!drawer || drawer.id !== thread.id) return;
    if (drawer.more) drawer.more.remove();
    drawer.more = null;
    const hidden = thread.from - 1;
    if (hidden <= 0) return;
    const more = el("button", "more", `View ${hidden} earlier repl${hidden === 1 ? "y" : "ies"}`);
    more.type = "button";
    more.addEventListener("click", () => this._earlierReplies(thread));
    drawer.rlist.prepend(more);
    drawer.more = more;
  }

  async _earlierReplies(thread) {
    try {
      const page = await this._ws({ type: "console/chat/history", thread_id: thread.id, before: thread.from, limit: PAGE });
      const messages = page.from === 0 ? page.messages.slice(1) : page.messages;   // what started it is already shown
      thread.replies = [...messages, ...thread.replies];
      thread.from = Math.max(1, page.from);
      const drawer = this._drawer;
      if (drawer && drawer.id === thread.id) {
        const first = drawer.more ? drawer.more.nextSibling : drawer.rlist.firstChild;
        for (const message of messages) drawer.rlist.insertBefore(this._comment(message, thread, false).node, first);
        this._earlierLink(thread);
      }
    } catch (e) { /* nothing earlier to show */ }
  }

  // --- one message ---------------------------------------------------------------------------------

  // A comment: avatar, a bubble with who said it and what, and a line under it (when, Reply, and for
  // Console's replies the work behind it and Copy). In the list (`listed`), Reply opens the drawer.
  _comment(message, thread, isRoot, listed) {
    const mine = message.who === "you";
    const node = el("div", `c ${mine ? "me" : "it"}${isRoot ? " root" : ""}`);
    const av = el("div", `av ${mine ? "me" : "it"}`, (mine ? this._me : AGENT).slice(0, 1).toUpperCase());
    av.setAttribute("aria-hidden", "true");
    const col = el("div", "col"), bubble = el("div", `bubble${message.failed ? " error" : ""}`), msg = el("div", "msg");
    bubble.append(el("div", "who", mine ? this._me : AGENT), msg);
    if (mine) msg.textContent = message.text || ""; else markdown(msg, message.text || "");
    const meta = el("div", "meta");
    col.append(bubble, meta);
    node.append(av, col);
    if (listed) { bubble.style.cursor = "pointer"; msg.style.cursor = "pointer"; bubble.addEventListener("click", () => this._openDrawer(thread.id, false)); }
    const comment = { node, col, bubble, msg, meta, text: message.text || "", message, listed };
    this._meta(comment, thread);
    if (!mine && (message.steps || []).length) {
      const work = this._work(comment);
      for (const step of message.steps) {
        if (step.kind === "think") { work.thinking = null; work.think(step.detail || ""); continue; }
        work.thinking = null;
        const row = work.add(step.failed ? "failed" : "", step.title || "Step");
        row.d.textContent = [step.detail, step.result ? `→ ${step.result}` : ""].filter(Boolean).join("\n");
      }
      work.close(message.meta || {}, (message.meta || {}).ms);
    }
    return comment;
  }

  _meta(comment, thread) {
    const meta = comment.meta;
    meta.replaceChildren();
    if (comment.message.pending) { if (comment.workButton) meta.appendChild(comment.workButton); return; }   // still being written: only its work
    const when = el("span", "", ago(comment.message.at));
    if (comment.message.at) when.title = new Date(comment.message.at).toLocaleString();
    const reply = el("button", "", "Reply"); reply.type = "button";
    reply.addEventListener("click", () => { if (this._drawer && this._drawer.id === thread.id) this._drawer.area.focus(); else this._openDrawer(thread.id, true); });
    meta.append(when, reply);
    if (comment.workButton) meta.appendChild(comment.workButton);
    if (comment.message.who !== "you" && !comment.listed) {
      const copy = el("button", "", "Copy"); copy.type = "button"; copy.title = "Copy this reply";
      copy.addEventListener("click", () => copyText(comment.text, copy));
      meta.appendChild(copy);
    }
  }

  // The work behind a reply: a toggle in its line ("4 steps · 2.1 s"), opening into its steps below.
  _work(comment) {
    const list = el("div", "work"); list.hidden = true;
    const button = el("button"); button.type = "button"; button.setAttribute("aria-expanded", "false");
    button.title = "Show the work behind this reply";
    button.addEventListener("click", () => { list.hidden = !list.hidden; button.setAttribute("aria-expanded", list.hidden ? "false" : "true"); });
    comment.col.appendChild(list);
    comment.workButton = button;
    if (comment.message.pending) comment.meta.replaceChildren(button); else comment.meta.insertBefore(button, comment.meta.children[2] || null);
    const work = { list, button, count: 0, byKey: new Map(), thinking: null };
    work.add = (cls, title) => { const row = el("div", `step ${cls}`), t = el("div", "t", title), d = el("div", "d"); row.append(t, d); list.appendChild(row); work.count += 1; return { row, t, d }; };
    work.think = (text) => {
      if (!work.thinking) {
        const step = work.add("think", "Thinking"), all = el("button", "all", "Show all");
        step.full = ""; step.open = false; all.type = "button"; all.hidden = true;
        all.addEventListener("click", () => { step.open = !step.open; all.textContent = step.open ? "Show less" : "Show all"; step.d.textContent = step.open ? step.full : gist(step.full); });
        step.t.appendChild(all); step.all = all; work.thinking = step;
      }
      const thinking = work.thinking;
      thinking.full += text;
      if (!thinking.open) thinking.d.textContent = gist(thinking.full);
      thinking.all.hidden = gist(thinking.full) === thinking.full.replace(/\s+/g, " ").trim();
    };
    work.label = (text, live) => {
      button.replaceChildren();
      if (live) { const wrap = el("span", "live"); wrap.append(el("span", "dot"), el("span", "", text)); button.appendChild(wrap); }
      else button.textContent = text;
    };
    work.close = (meta, ms) => {
      const seconds = ms ? ` · ${(ms / 1000).toFixed(1)} s` : "";
      const label = meta.route === "local" ? `Answered at home${seconds}` : `${work.count} step${work.count === 1 ? "" : "s"}${seconds}${meta.cost_usd ? ` · ${credits(meta.cost_usd)} credits` : ""}`;
      work.label(label, false);
      if (!work.count) { button.disabled = true; button.style.cursor = "default"; button.style.fontWeight = "400"; }
    };
    work.label("Working…", true);
    return work;
  }

  // --- turns, several at once -----------------------------------------------------------------------

  _stopLive(thread) {
    if (thread.live && thread.live.stop) { try { thread.live.stop(); } catch (e) { /* already closed */ } }
    thread.live = null;
    thread.pending = null;
  }

  // Console's reply being written in one conversation. It is drawn whether or not that conversation is
  // open: the drawer shows it whole when opened, and the list's peek shows what the agent is doing.
  _live(thread) {
    const pending = this._comment({ who: "console", text: "", at: null, pending: true }, thread, false);
    const typing = el("span", "typing"); typing.append(el("i"), el("i"), el("i"));
    pending.msg.replaceChildren(typing);
    const work = this._work(pending);
    const started = performance.now();
    const live = { stop: null, done: false };
    thread.live = live;
    thread.pending = pending;
    thread.liveLabel = "Working…";
    if (this._drawer && this._drawer.id === thread.id) { this._drawerAdd(pending.node); this._drawDrawerState(); }
    this._drawRow(thread);
    let streamed = "", meta = {}, frame = 0;
    const label = (text) => { work.label(text, true); thread.liveLabel = text; this._drawRow(thread); if (this._drawer && this._drawer.id === thread.id) this._drawDrawerState(); };
    const paint = () => { frame = 0; if (streamed) markdown(pending.msg, streamed); const d = this._drawer; if (d && d.id === thread.id) d.dbody.scrollTop = d.dbody.scrollHeight; };
    const repaint = () => { if (!frame) frame = requestAnimationFrame(paint); };

    const finish = (event) => {
      if (live.done) return;
      live.done = true;
      if (frame) cancelAnimationFrame(frame);
      const message = { who: "console", text: event.reply || streamed || "Done.", at: new Date().toISOString(), failed: !!event.error };
      pending.text = message.text;
      pending.message = message;
      markdown(pending.msg, message.text);
      if (event.error) pending.bubble.classList.add("error");
      work.close(meta, event.ms || performance.now() - started);
      this._meta(pending, thread);
      thread.replies.push(message);
      thread.total += 1;
      if (thread.live === live) { this._stopLive(thread); }
      const open = this._drawer && this._drawer.id === thread.id;
      thread.status = open ? "" : event.error ? "error" : "done";
      this._drawRow(thread);
      if (open) { this._drawDrawerState(); if (!thread.id.startsWith("local-")) this._ws({ type: "console/chat/seen", thread_id: thread.id }).then((r) => this._setCounts(r.counts)).catch(() => {}); }
      this._loadSuggested();   // the house may look different now: what's worth suggesting too
    };

    const onEvent = (event) => {
      if (live.done) return;
      if (event.kind === "thread") this._rekey(thread, event.thread_id);
      else if (event.kind === "step") {
        let step = work.byKey.get(event.key);
        if (!step) { step = work.add("", event.title || "Step"); work.byKey.set(event.key, step); if (event.detail) step.d.textContent = event.detail; }
        if (event.result) step.d.textContent = (step.d.textContent ? step.d.textContent + "\n→ " : "") + event.result;
        if (event.state === "failed") step.row.classList.add("failed");
        if (event.title) label(event.title + (event.state === "running" ? "…" : ""));
        work.thinking = null;
      } else if (event.kind === "thinking") { if (!work.thinking) label("Thinking…"); work.think(event.text); }
      else if (event.kind === "said") { const said = work.add("", "Said"); said.d.textContent = event.text; streamed = ""; work.thinking = null; }
      else if (event.kind === "text") { streamed += event.text; if (thread.liveLabel !== "Writing…") label("Writing…"); repaint(); work.thinking = null; }
      else if (event.kind === "reset") { streamed = ""; pending.msg.replaceChildren(typing); }
      else if (event.kind === "meta") { meta = event; }
      else if (event.kind === "done") { finish(event); }
      else if (event.kind === "gone") { live.done = true; pending.node.remove(); this._stopLive(thread); this._refresh(thread); }   // it ended a moment ago: read it again
    };
    return { live, onEvent, finish };
  }

  // One message is one turn: `resubscribe: false` keeps Home Assistant from sending the command again
  // when the connection comes back. The "ready" listener reads the conversations from the box instead.
  async _subscribe(turn, message) {
    try {
      const stop = await this._hass.connection.subscribeMessage(turn.onEvent, message, { resubscribe: false });
      if (turn.live.done) { try { stop(); } catch (e) { /* already closed */ } } else turn.live.stop = stop;
    } catch (error) {
      turn.finish({ reply: error && error.code === "busy" ? String(error.message) : "I couldn't reach Console's agent in Home Assistant. Try again in a moment.", error: true });
    }
  }

  // Say something: a reply in one conversation (`id`), or the start of a new one (null). Any number of
  // conversations can have a turn running; each conversation one at a time.
  async _send(text, id) {
    if (!this._hass) return;
    const said = { who: "you", text, at: new Date().toISOString() };
    let thread = id && this._threads.get(id);
    if (thread && thread.live) return;
    if (thread) this._push(thread, said);
    else {
      thread = this._addThread({ id: `local-${++this._tmp}`, title: text, root: said, replies: [], from: 1, total: 1, status: "" });
      id = null;
      this._bottom();
    }
    const turn = this._live(thread);
    await this._subscribe(turn, { type: "console/chat", text, thread_id: id });
  }

  // A turn already running in a conversation (the card reloaded, reconnected, or it started elsewhere).
  _watch(thread) {
    if (thread.live) return;
    this._subscribe(this._live(thread), { type: "console/chat/watch", thread_id: thread.id });
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
    description: "Talk to Console, this home's agent: conversations as comment threads in a drawer, several agents at once with status dots, suggestions to tap, and quick actions.",
    preview: false,
  });
}
