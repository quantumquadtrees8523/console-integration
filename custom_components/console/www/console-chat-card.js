// Console chat card: talk to Console, this home's agent, from a dashboard.
//
// The card is one feed of chats, and each chat is a thread inside it (owner, 2026-11-28: "a feed of chats
// and each chat has its own mini history ... like a Facebook comment thread"). It is drawn as comments:
// each one an avatar, a name and its words in a bubble, with a line under it (when, Reply). What you ask
// is a top-level comment; Console's answer and everything after are replies indented under it. The box at
// the bottom starts a new chat. Reply opens a box inside that thread, and what's written there goes into
// that chat alone: only its messages are the model's context. View more replies opens a chat's own
// history in place. Everything is kept on the box (never in this card, never off the
// box) with the work behind every reply: where the request went and why, the model's thinking, each tool
// it used and what came back. Ten chats at a time from the newest.
//
// A turn is asked through Console's own websocket command (console/chat), which answers as the turn
// happens. One message is one turn: the command is never sent again when the connection comes back
// (resubscribe: false). A turn runs on the box whoever is listening, so a card that reloads, reconnects
// or opens the feed on another screen watches the running turn (console/chat/watch) or finds the reply
// in its chat.
//
// Above the box you type in: always three suggestions, each a tap that runs something now. Under it:
// quick actions, the suggestions this household keeps using (suggestions.py).
const SENSOR = "sensor.console_cloud_agent";
const PAGE = 10;
const REPLIES = 50;   // a chat's replies, read at a time
const OPENING = 2;    // a chat's opening in the feed: what was asked and the reply (history.py)
const REFRESH_MS = 5 * 60 * 1000;

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
  .post { display: flex; flex-direction: column; gap: 6px; padding-bottom: 6px; }
  .thread { display: flex; flex-direction: column; gap: 6px; margin-left: 40px; }
  .first, .replies { display: flex; flex-direction: column; gap: 6px; }
  .view, .replies .earlier { align-self: flex-start; font: inherit; font-size: 13px; font-weight: 600; border: 0; background: none; padding: 2px 0 2px 4px; color: var(--secondary-text-color); cursor: pointer; }
  .view:hover, .replies .earlier:hover, .foot button:hover { text-decoration: underline; }
  .av { flex: none; width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; font-size: 14px; font-weight: 700; text-transform: uppercase;
        background: color-mix(in srgb, var(--primary-text-color) 16%, transparent); color: var(--primary-text-color); }
  .it > .av { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .thread .av { width: 24px; height: 24px; font-size: 11px; }
  .rbox { display: flex; gap: 8px; align-items: center; padding: 0; }
  .rbox textarea { min-height: 34px; padding: 7px 12px; border-radius: 17px; font-size: 14px; line-height: 18px; background: var(--secondary-background-color); border-color: transparent; }
  .none { padding: 14px; color: var(--secondary-text-color); font-size: 14px; }
  .log { flex: 1; min-height: 0; min-width: 0; overflow-y: auto; padding: 12px 16px 6px; display: flex; flex-direction: column; gap: 10px; overscroll-behavior: contain;
         user-select: text; -webkit-user-select: text; }
  .top { display: flex; justify-content: center; font-size: 12px; color: var(--secondary-text-color); min-height: 4px; }
  .hello { color: var(--secondary-text-color); font-size: 14px; line-height: 20px; }
  .turn { display: flex; gap: 8px; align-items: flex-start; }
  .cb { min-width: 0; display: flex; flex-direction: column; gap: 2px; align-items: flex-start; }
  .bubble { max-width: 100%; padding: 7px 12px; border-radius: 16px; background: var(--secondary-background-color); color: var(--primary-text-color); }
  .who { display: block; font-size: 13px; font-weight: 700; line-height: 18px; }
  .msg { font-size: 15px; line-height: 20px; overflow-wrap: anywhere; user-select: text; -webkit-user-select: text; cursor: text; }
  .me .msg { white-space: pre-wrap; }
  .msg.error { color: var(--error-color, #db4437); }
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
  .foot { display: flex; gap: 12px; align-items: center; font-size: 12px; color: var(--secondary-text-color); padding-left: 12px; }
  .foot button, .foot .copy { font: inherit; font-size: 12px; font-weight: 700; border: 0; background: none; padding: 0; color: var(--secondary-text-color); cursor: pointer; border-radius: 0; }
  details.steps { font-size: 12px; color: var(--secondary-text-color); margin: 0 0 0 12px; align-self: stretch; }
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
    this._busy = false;      // a turn is running in one of the chats on screen
    this._loaded = false;    // the first read of the box is done
    this._banner = "";
    this._posts = new Map(); // the chats on screen, by id
    this._reply = null;      // the chat being replied in (null: what's typed starts a new chat)
    this._from = 0;          // index of the oldest chat on screen, in the feed
    this._more = false;      // whether the feed holds earlier ones
    this._sig = "";          // the feed as it was last read: a change means read it again
    this._seq = 0;           // goes up whenever the feed is drawn again: a late answer for the old one is dropped
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
    this._loadSuggested();
    await this._loadFeed();
    this._loaded = true;
    this._bottom();
  }

  _build() {
    const root = this.shadowRoot;
    root.innerHTML = `<style>${STYLE}</style>
      <ha-card>
        <div class="banner" hidden></div>
        <div class="log" role="log" aria-live="polite"><div class="top"></div><div class="hello"></div></div>
        <div class="strip suggested" hidden><div class="row" role="group" aria-label="Suggestions"></div></div>
        <form><textarea rows="1" placeholder="Ask Console" aria-label="Ask Console" enterkeyhint="send"></textarea>
        <button class="send" type="submit">Send</button></form>
        <div class="strip quick" hidden><div class="row" role="group" aria-label="Quick actions"></div></div>
      </ha-card>`;
    if (this._config.title) root.querySelector("ha-card").setAttribute("header", this._config.title);
    this._log = root.querySelector(".log");
    this._top = root.querySelector(".top");
    this._hello = root.querySelector(".hello");
    this._suggestedRow = root.querySelector(".strip.suggested");
    this._quickRow = root.querySelector(".strip.quick");
    const area = root.querySelector("form:not(.rbox) textarea");
    const submit = () => { const text = area.value.trim(); if (text && !this._busy && this._loaded) { area.value = ""; area.style.height = ""; this._send(text); } };
    root.querySelector("form").addEventListener("submit", (event) => { event.preventDefault(); submit(); });
    area.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); } });
    area.addEventListener("input", () => { area.style.height = "auto"; area.style.height = `${Math.min(area.scrollHeight + 2, 140)}px`; });
    // Earlier chats come when the person pulls up past the top.
    this._log.addEventListener("wheel", (event) => { if (event.deltaY < 0 && this._log.scrollTop < 2) this._earlier(); }, { passive: true });
    let touchY = null;
    this._log.addEventListener("touchstart", (event) => { touchY = this._log.scrollTop < 2 ? event.touches[0].clientY : null; }, { passive: true });
    this._log.addEventListener("touchmove", (event) => { if (touchY !== null && event.touches[0].clientY - touchY > 60) { touchY = null; this._earlier(); } }, { passive: true });
    // A suggestion counts as seen when it is really on screen, not when the dashboard merely holds this card.
    if (window.IntersectionObserver) new IntersectionObserver((entries) => { this._onScreen = entries.some((entry) => entry.isIntersecting); this._seen(); }).observe(this._suggestedRow);
    else this._onScreen = true;
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

  _drawTop() {
    this._top.replaceChildren();
    if (this._more) { const earlier = el("span", "earlier", "Load earlier chats"); earlier.addEventListener("click", () => this._earlier()); this._top.appendChild(earlier); }
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
    const seq = this._seq, into = null;   // a tap under the feed is a new chat
    let done = null, failed = null;
    try { done = await this._ws({ type: "console/suggestions/tap", suggestion_id: item.id, thread_id: into ? into.id : null }); } catch (e) { failed = String(e.message || e); }
    this._busy = false;
    if (done && done.ask) { this._send(done.ask); this._loadSuggested(); return; }   // something to ask: sent like any message
    if (seq !== this._seq) return;
    const post = await this._postFor(into, `Run “${item.name}”`);
    this._append(post, this._turn("me", `Run “${item.name}”`, { post }));
    if (done) {
      this._name(post, done.thread_id);
      this._append(post, this._stored({ who: "console", text: done.reply, steps: [{ title: "Ran at home", detail: "A tap on a suggestion: no AI, no internet." }], meta: { route: "local" } }, post));
    } else this._append(post, this._turn("it", failed, { error: true, post }));
    this._drawActs(post);
    post.node.scrollIntoView({ block: "nearest" });
    this._loadSuggested();
  }

  async _dismiss(item) {
    try { await this._ws({ type: "console/suggestions/dismiss", suggestion_id: item.id }); } catch (e) { /* it's gone already */ }
    this._loadSuggested();
  }

  // --- the feed, and each chat a thread inside it ----------------------------------------------------

  // One chat in the feed, as a comment thread: the ask on top, then, indented under it, Console's answer,
  // the rest of the replies (closed until asked for) and the box to reply in.
  _post(chat) {
    const node = el("div", "post"), top = el("div", "top"), thread = el("div", "thread"), first = el("div", "first"), replies = el("div", "replies");
    const post = { id: chat.id || null, title: chat.title || "", count: 0, node, top, first, replies, open: false, from: null };
    replies.hidden = true;
    post.view = el("button", "view"); post.view.type = "button";
    post.view.addEventListener("click", () => { if (post.open) this._closeReplies(post); else this._openReplies(post); });
    post.box = el("form", "rbox"); post.box.hidden = true;
    const area = el("textarea"); area.rows = 1; area.placeholder = "Reply in this thread…"; area.setAttribute("aria-label", "Reply in this thread"); area.enterKeyHint = "send";
    const submit = () => { const text = area.value.trim(); if (text && !this._busy && this._loaded) { area.value = ""; this._send(text, post); } };
    post.box.addEventListener("submit", (event) => { event.preventDefault(); submit(); });
    area.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); } if (event.key === "Escape") this._setReply(null); });
    post.box.append(this._avatar("me"), area);
    thread.append(first, post.view, replies, post.box);
    node.append(top, thread);
    for (const message of chat.opening || []) this._append(post, this._stored(message, post));
    post.count = chat.count || post.count;
    if (post.id) this._posts.set(post.id, post);
    this._drawActs(post);
    return post;
  }

  _drawActs(post) {
    const more = Math.max(0, post.count - OPENING);
    post.view.hidden = !more;
    post.view.textContent = post.open ? "Hide replies" : `View ${more} more ${more === 1 ? "reply" : "replies"}`;
  }

  // A chat learns its id from the box when its first turn starts.
  _name(post, id) {
    if (!id || post.id === id) return;
    post.id = id;
    this._posts.set(id, post);
  }

  // Put a comment into a chat on screen: the ask on top, the answer under it, then its replies.
  _append(post, turn) {
    if (post.count === 0) {
      post.top.appendChild(turn.node);
      const gone = el("button", "", "Delete"); gone.type = "button";
      gone.addEventListener("click", () => this._delete(post));
      turn.foot.appendChild(gone);
    } else if (post.count < OPENING) post.first.appendChild(turn.node);
    else { post.replies.hidden = false; post.open = true; if (post.from === null) post.from = OPENING; post.replies.appendChild(turn.node); }
    post.count += 1;
  }

  // The chat a message goes into: the one being replied in (with its replies open), or a new one at the
  // bottom of the feed.
  async _postFor(into, title) {
    this._hello.remove();
    if (into) { await this._openReplies(into); return into; }
    const post = this._post({ title: title.length > 60 ? `${title.slice(0, 59).trimEnd()}…` : title });
    this._log.appendChild(post.node);
    this._bottom();
    return post;
  }

  // A chat's own history, opened in place: its newest replies, and a way to the earlier ones.
  async _openReplies(post) {
    if (post.open) return;
    post.open = true;
    post.replies.hidden = false;
    if (post.from === null && post.id && post.count > OPENING) await this._moreReplies(post);
    else if (post.from === null) post.from = OPENING;
    this._drawActs(post);
  }

  _closeReplies(post) {
    post.open = false;
    post.replies.hidden = true;
    this._drawActs(post);
  }

  async _moreReplies(post) {
    const seq = this._seq;
    let page = null;
    try { page = await this._ws({ type: "console/chat/history", thread_id: post.id, limit: REPLIES, ...(post.from !== null ? { before: post.from } : {}) }); } catch (e) { /* nothing more to show */ }
    if (seq !== this._seq) return;
    const earlier = post.replies.querySelector(".earlier");
    if (earlier) earlier.remove();
    if (!page) { if (post.from === null) post.from = OPENING; return; }
    const start = Math.max(page.from, OPENING);   // the opening is already in the feed
    const first = post.replies.firstChild;
    for (const message of page.messages.slice(start - page.from)) post.replies.insertBefore(this._stored(message, post).node, first);
    if (post.from === null) post.count = page.total;
    post.from = start;
    if (start > OPENING) {
      const link = el("button", "earlier", "Show earlier replies"); link.type = "button";
      link.addEventListener("click", () => this._moreReplies(post));
      post.replies.insertBefore(link, post.replies.firstChild);
    }
  }

  // Reply: open that thread's own box (one at a time). What's written there goes into that chat alone.
  _setReply(post) {
    const was = this._reply;
    this._reply = post && post.id ? post : null;
    if (was && was !== this._reply) was.box.hidden = true;
    if (!this._reply) return;
    post.box.hidden = false;
    this._openReplies(post).then(() => { post.box.scrollIntoView({ block: "nearest" }); post.box.querySelector("textarea").focus(); });
  }

  async _delete(post) {
    if (!confirm(`Delete the chat “${post.title || "Chat"}” from this box? It can't be brought back.`)) return;
    if (post.id) { try { await this._ws({ type: "console/chat/thread/delete", thread_id: post.id }); } catch (e) { /* gone already */ } this._posts.delete(post.id); }
    if (this._reply === post) this._setReply(null);
    post.node.remove();
    if (!this._log.querySelector(".post")) this._showHello();
  }

  _showHello() {
    if (!this._hello.isConnected) this._top.after(this._hello);
    this._drawHello();
  }

  _clear() {
    this._seq += 1;
    if (this._stop) { try { this._stop(); } catch (e) { /* already closed */ } this._stop = null; }
    this._busy = false;
    this.shadowRoot.querySelector("button.send").disabled = false;
    this._log.querySelectorAll(".post").forEach((node) => node.remove());
    this._posts.clear();
    this._from = 0; this._more = false;
  }

  static _signature(feed) { return feed.chats.map((chat) => `${chat.id}:${chat.count}:${chat.working ? 1 : 0}`).join("|") + `/${feed.total}`; }

  // Draw the feed from the box: its newest chats, each closed on its opening, except the ones that were
  // open (and the one being replied in), which open again. A turn running in one of them is watched.
  async _loadFeed() {
    let feed = null;
    try { feed = await this._ws({ type: "console/chat/feed", limit: PAGE }); } catch (e) { /* nothing kept yet, or still offline */ }
    if (!feed) { if (!this._loaded) this._showHello(); return; }
    const open = [...this._posts.values()].filter((post) => post.open).map((post) => post.id);
    const replying = this._reply && this._reply.id;
    this._clear();
    this._reply = null;
    for (const chat of feed.chats) this._log.appendChild(this._post(chat).node);
    this._from = feed.from; this._more = feed.more; this._sig = ConsoleChatCard._signature(feed);
    if (feed.chats.length) this._hello.remove(); else this._showHello();
    this._drawTop();
    const seq = this._seq;
    for (const id of open) if (this._posts.has(id)) await this._openReplies(this._posts.get(id));
    if (seq !== this._seq) return;
    if (replying && this._posts.get(replying)) this._setReply(this._posts.get(replying));
    const working = feed.chats.filter((chat) => chat.working).pop();
    if (working) await this._watch(this._posts.get(working.id));
  }

  // The feed, read again from the box: after a reconnect, or when the page comes back into view. A turn
  // that finished meanwhile shows its reply; one still running is watched.
  async _resync(force) {
    if (this._busy && !force) return;
    let changed = force;
    if (!changed) {
      try { changed = ConsoleChatCard._signature(await this._ws({ type: "console/chat/feed", limit: PAGE })) !== this._sig; } catch (e) { return; }
    }
    if (changed) { const was = this._atBottom(); await this._loadFeed(); this._follow(was); }
    this._loadSuggested();
  }

  async _earlier() {
    if (!this._more || this._loading) return;
    this._loading = true;
    const seq = this._seq;
    try {
      const feed = await this._ws({ type: "console/chat/feed", before: this._from, limit: PAGE });
      if (seq === this._seq) {
        const first = this._log.querySelector(".post");
        const height = this._log.scrollHeight;
        for (const chat of feed.chats) if (!this._posts.has(chat.id)) this._log.insertBefore(this._post(chat).node, first);
        this._from = feed.from; this._more = feed.more;
        this._drawTop();
        this._log.scrollTop = this._log.scrollHeight - height;   // stay where the person was reading
      }
    } catch (e) { /* nothing earlier to show */ }
    this._loading = false;
  }

  // --- one message on screen ----------------------------------------------------------------------

  _avatar(who) {
    const name = who === "me" ? this._me() : "Console";
    const av = el("div", "av", name.slice(0, 1)); av.setAttribute("aria-hidden", "true");
    return av;
  }

  _me() { return (this._hass && this._hass.user && this._hass.user.name) || "You"; }

  // One comment: avatar, then the name and the words in a bubble, and under it when, Reply and Copy.
  _turn(who, text, opts = {}) {
    const node = el("div", `turn ${who}`), body = el("div", "cb"), shell = el("div", "bubble");
    const bubble = el("div", `msg${opts.error ? " error" : ""}`);
    if (who === "me") bubble.textContent = text; else markdown(bubble, text);
    shell.append(el("span", "who", who === "me" ? this._me() : "Console"), bubble);
    const foot = el("div", "foot");
    foot.appendChild(el("span", "", opts.at ? ago(opts.at) : "just now"));
    const turn = { node, body, bubble, foot, text };
    if (opts.post) {
      const reply = el("button", "", "Reply"); reply.type = "button";
      reply.addEventListener("click", () => this._setReply(opts.post));
      foot.appendChild(reply);
    }
    if (who === "it") {
      const copy = el("button", "copy", "Copy"); copy.type = "button";
      copy.addEventListener("click", () => copyText(turn.text, copy));
      foot.appendChild(copy);
    }
    body.append(shell, foot);
    node.append(this._avatar(who), body);
    return turn;
  }

  // The work behind a reply: a line that opens into its steps. The same for a reply being written now
  // and for one read back from the thread.
  _work(turn) {
    const steps = el("details", "steps"), summary = el("summary"), list = el("div", "steplist");
    const dot = el("span", "dot"), label = el("span", "", "Working…");
    summary.append(dot, label); steps.append(summary, list);
    turn.body.appendChild(steps);
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
  _stored(message, post) {
    if (message.who === "you") return this._turn("me", message.text, { at: message.at, post });
    const turn = this._turn("it", message.text, { error: message.failed, at: message.at, post });
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
  _live(post) {
    const seq = this._seq;
    const send = this.shadowRoot.querySelector("button.send");
    this._busy = true;
    send.disabled = true;
    const turn = this._turn("it", "", { post });
    turn.bubble.hidden = true; turn.foot.hidden = true;
    const work = this._work(turn);
    this._append(post, turn);
    turn.node.scrollIntoView({ block: "nearest" });
    const started = performance.now();
    let streamed = "", meta = {}, frame = 0, done = false;
    const paint = () => { frame = 0; const was = this._atBottom(); turn.bubble.hidden = !streamed; if (streamed) markdown(turn.bubble, streamed); this._follow(was); };
    const repaint = () => { if (!frame) frame = requestAnimationFrame(paint); };

    const finish = (event) => {
      if (done) return;
      done = true;
      if (frame) cancelAnimationFrame(frame);
      if (seq !== this._seq) return;   // the feed was drawn again meanwhile: this reply is in its chat
      const was = this._atBottom();
      turn.text = event.reply || streamed || "Done.";
      markdown(turn.bubble, turn.text);
      turn.bubble.hidden = false; turn.foot.hidden = false;
      if (event.error) turn.bubble.classList.add("error");
      this._name(post, event.thread_id);
      work.close(meta, event.ms || performance.now() - started);
      this._busy = false; send.disabled = false;
      this._sig = "";   // the feed on the box moved on: the next look reads it again
      if (this._stop) { try { this._stop(); } catch (e) { /* already closed */ } this._stop = null; }
      this._drawActs(post);
      this._follow(was);
      this._loadSuggested();   // the house may look different now: what's worth suggesting too
    };

    const onEvent = (event) => {
      if (seq !== this._seq || done) return;
      const was = this._atBottom();
      if (event.kind === "thread") this._name(post, event.thread_id);
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
      else if (event.kind === "gone") { done = true; turn.node.remove(); post.count -= 1; this._busy = false; send.disabled = false; this._resync(true); }   // it ended a moment ago: read the feed
      this._follow(was);
    };
    return { onEvent, finish, seq };
  }

  // One message is one turn: `resubscribe: false` keeps Home Assistant from sending the command again
  // when the connection comes back. The "ready" listener reads the feed from the box instead.
  async _subscribe(live, message) {
    try {
      const stop = await this._hass.connection.subscribeMessage(live.onEvent, message, { resubscribe: false });
      if (live.seq === this._seq && this._busy) this._stop = stop; else { try { stop(); } catch (e) { /* already closed */ } }
    } catch (error) {
      live.finish({ reply: error && error.code === "busy" ? String(error.message) : "I couldn't reach Console's agent in Home Assistant. Try again in a moment.", error: true });
    }
  }

  // What's typed in a thread's own box goes into that chat; what's typed under the feed starts a new chat.
  async _send(text, into) {
    if (this._busy || !this._hass) return;
    this._busy = true;   // held from here: opening a chat's replies may take a moment
    const seq = this._seq;
    const post = await this._postFor(into || null, text);
    if (seq !== this._seq) { this._busy = false; return; }
    this._append(post, this._turn("me", text, { post }));
    this._drawActs(post);
    await this._subscribe(this._live(post), { type: "console/chat", text, thread_id: post.id });
  }

  // A turn already running in a chat (the card reloaded, reconnected, or opened the feed on another screen).
  async _watch(post) {
    if (!post) return;
    const seq = this._seq;
    if (post.count > OPENING) await this._openReplies(post);
    if (seq !== this._seq) return;
    await this._subscribe(this._live(post), { type: "console/chat/watch", thread_id: post.id });
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
    description: "Talk to Console, this home's agent: one feed of your chats, each a thread you can reply in, with the work behind each reply, suggestions to tap, and quick actions.",
    preview: false,
  });
}
