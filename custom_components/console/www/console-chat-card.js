// Console chat card: talk to Console, this home's agent, from a dashboard.
//
// It asks through Console's own websocket command (console/chat), which answers as the turn happens:
// where the request went and why, the model's thinking, each tool it used and what came back, and the
// reply as it is written. Replies are rich text you can select and copy. What was said is kept on the
// box (never in this card, never off the box), so a reload picks the conversation up, and scrolling up
// past the top brings back earlier messages ten at a time.
const SENSOR = "sensor.console_cloud_agent";
const PAGE = 10;
const RECENT_MS = 30 * 60 * 1000;

const STYLE = `
  :host { display: block; height: 100%; }
  ha-card { display: flex; flex-direction: column; height: 100%; min-height: var(--console-chat-height, 460px); overflow: hidden; }
  .banner { padding: 10px 16px; font-size: 14px; line-height: 20px; }
  .banner.warn { background: color-mix(in srgb, var(--warning-color, #ffa600) 18%, transparent); }
  .banner.stop { background: color-mix(in srgb, var(--error-color, #db4437) 18%, transparent); }
  .banner.offline, .banner.off { background: color-mix(in srgb, var(--secondary-text-color, #888) 16%, transparent); }
  .banner.support { background: color-mix(in srgb, var(--warning-color, #ffa600) 26%, transparent); }
  .banner a, .earlier, .new { color: var(--primary-color); cursor: pointer; text-decoration: underline; white-space: nowrap; }
  .log { flex: 1; overflow-y: auto; padding: 12px 16px 6px; display: flex; flex-direction: column; gap: 10px; overscroll-behavior: contain;
         user-select: text; -webkit-user-select: text; }
  .top { display: flex; justify-content: space-between; font-size: 12px; color: var(--secondary-text-color); min-height: 16px; }
  .rule { align-self: center; font-size: 11px; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: .08em; }
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
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip { border: 1px solid var(--divider-color); border-radius: 16px; padding: 6px 12px; font-size: 13px; background: none; color: var(--primary-text-color); cursor: pointer; font-family: inherit; }
  form { display: flex; gap: 8px; padding: 10px 12px 12px; border-top: 1px solid var(--divider-color); align-items: flex-end; }
  textarea { flex: 1; min-width: 0; min-height: 42px; max-height: 140px; padding: 10px 14px; border-radius: 21px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); font: inherit; font-size: 15px; line-height: 20px; resize: none; box-sizing: border-box; }
  textarea:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
  button.send { height: 42px; padding: 0 18px; border-radius: 21px; border: 0; background: var(--primary-color); color: var(--text-primary-color, #fff); font: inherit; font-weight: 600; cursor: pointer; }
  button.send[disabled] { opacity: .5; cursor: default; }
`;

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

class ConsoleChatCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._busy = false;
    this._banner = "";
    this._from = null;      // index of the oldest history message on screen
    this._more = false;     // whether the box holds earlier ones
    this._shown = 0;        // how many earlier messages are on screen (given to the agent as context)
    try { this._conversation = sessionStorage.getItem("console-chat-conversation") || undefined; } catch (e) { this._conversation = undefined; }
  }

  setConfig(config) { this._config = { title: "Console", ...config }; this._build(); }
  static getStubConfig() { return { title: "Console" }; }
  getCardSize() { return 8; }
  getGridOptions() { return { columns: 12, rows: 8, min_rows: 5 }; }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const sensor = hass.states[SENSOR];
    const key = sensor ? `${sensor.state}|${sensor.attributes.banner || ""}` : "none";
    if (key !== this._banner) { this._banner = key; this._drawBanner(sensor); }
    if (first) this._start();
  }

  async _start() {
    try {
      const status = await this._hass.callWS({ type: "console/status" });
      this._welcome = status.onboarding || {};
    } catch (e) { this._welcome = {}; }
    try {
      const page = await this._hass.callWS({ type: "console/chat/history", limit: PAGE });
      this._more = page.total > 0;
      this._from = page.total;
      const last = page.messages[page.messages.length - 1];
      if (last && Date.now() - new Date(last.at).getTime() < RECENT_MS) {   // the same sitting: show it
        this._from = page.from; this._more = page.more;
        for (const message of page.messages) this._addStored(message, false);
        this._shown = page.messages.length;
        this._hello.remove();
      }
    } catch (e) { this._more = false; }
    this._drawTop();
    this._drawHello();
    this._log.scrollTop = this._log.scrollHeight;
  }

  _build() {
    const root = this.shadowRoot;
    root.innerHTML = `<style>${STYLE}</style>
      <ha-card>
        <div class="banner" hidden></div>
        <div class="log" role="log" aria-live="polite"><div class="top"></div><div class="hello"></div></div>
        <form><textarea rows="1" placeholder="Ask Console" aria-label="Ask Console" enterkeyhint="send"></textarea>
        <button class="send" type="submit">Send</button></form>
      </ha-card>`;
    if (this._config.title) root.querySelector("ha-card").setAttribute("header", this._config.title);
    this._log = root.querySelector(".log");
    this._top = root.querySelector(".top");
    this._hello = root.querySelector(".hello");
    const area = root.querySelector("textarea");
    const submit = () => { const text = area.value.trim(); if (text && !this._busy) { area.value = ""; area.style.height = ""; this._send(text); } };
    root.querySelector("form").addEventListener("submit", (event) => { event.preventDefault(); submit(); });
    area.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); } });
    area.addEventListener("input", () => { area.style.height = "auto"; area.style.height = `${Math.min(area.scrollHeight + 2, 140)}px`; });
    // Earlier messages come when the person pulls up past the top, as in the old Console app.
    this._log.addEventListener("wheel", (event) => { if (event.deltaY < 0 && this._log.scrollTop < 2) this._earlier(); }, { passive: true });
    let touchY = null;
    this._log.addEventListener("touchstart", (event) => { touchY = this._log.scrollTop < 2 ? event.touches[0].clientY : null; }, { passive: true });
    this._log.addEventListener("touchmove", (event) => { if (touchY !== null && event.touches[0].clientY - touchY > 60) { touchY = null; this._earlier(); } }, { passive: true });
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
    if (this._more) { const earlier = el("span", "earlier", "Load earlier messages"); earlier.addEventListener("click", () => this._earlier()); this._top.appendChild(earlier); }
    else this._top.appendChild(el("span"));
    if (this._log.querySelector(".turn")) { const fresh = el("span", "new", "New chat"); fresh.addEventListener("click", () => this._newChat()); this._top.appendChild(fresh); }
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
      this._hello.appendChild(el("div", "", "Ask for anything in your home: “turn off the kitchen lights”, “play jazz in the kitchen”, “add a dashboard for the kids' room”."));
    }
    const chips = el("div", "chips");
    chips.style.marginTop = "10px";
    const offers = [];
    if (welcome.available && !welcome.done) {
      offers.push([welcome.state === "started" ? "Pick up the welcome" : "Show me around", "Show me around."]);
      if (!welcome.offered) offers.push(["Not now", null]);
    }
    offers.push(["What's on right now?", "What's on right now?"]);
    for (const [label, text] of offers) {
      const chip = el("button", "chip", label);
      chip.type = "button";
      chip.addEventListener("click", () => {
        if (welcome.available && !welcome.offered) { welcome.offered = true; this._hass.callWS({ type: "console/onboarding/offered" }).catch(() => {}); }
        if (text) this._send(text); else this._drawHello();
      });
      chips.appendChild(chip);
    }
    this._hello.appendChild(chips);
  }

  _newChat() {
    this._conversation = undefined;
    try { sessionStorage.removeItem("console-chat-conversation"); } catch (e) { /* private window */ }
    this._log.querySelectorAll(".turn, .rule").forEach((node) => node.remove());
    this._shown = 0;
    if (!this._hello.isConnected) this._top.after(this._hello);
    this._hass.callWS({ type: "console/chat/history", limit: 1 }).then((page) => { this._from = page.total; this._more = page.total > 0; this._drawTop(); }).catch(() => {});
    this._drawHello();
  }

  async _earlier() {
    if (!this._more || this._loading) return;
    this._loading = true;
    try {
      const page = await this._hass.callWS({ type: "console/chat/history", before: this._from, limit: PAGE });
      const anchor = this._log.querySelector(".turn, .rule");
      const height = this._log.scrollHeight;
      if (!this._log.querySelector(".rule.now") && anchor) this._log.insertBefore(el("div", "rule now", "Now"), anchor);
      const first = this._log.querySelector(".turn, .rule");
      for (const message of page.messages) this._addStored(message, true, first);
      if (!this._log.querySelector(".rule.earlier")) this._top.after(el("div", "rule earlier", "Earlier"));
      this._from = page.from; this._more = page.more; this._shown += page.messages.length;
      this._hello.remove();
      this._drawTop();
      this._log.scrollTop = this._log.scrollHeight - height;   // stay where the person was reading
    } catch (e) { /* nothing earlier to show */ }
    this._loading = false;
  }

  _addStored(message, earlier, before) {
    const turn = this._turn(message.who === "you" ? "me" : "it", message.text, { error: message.failed, at: message.at });
    if (before) this._log.insertBefore(turn.node, before); else this._log.appendChild(turn.node);
  }

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

  _atBottom() { return this._log.scrollHeight - this._log.scrollTop - this._log.clientHeight < 60; }
  _follow(was) { if (was) this._log.scrollTop = this._log.scrollHeight; }

  async _send(text) {
    if (this._busy || !this._hass) return;
    this._busy = true;
    const send = this.shadowRoot.querySelector("button.send");
    send.disabled = true;
    this._hello.remove();
    this._log.appendChild(this._turn("me", text).node);
    const turn = this._turn("it", "");
    turn.bubble.hidden = true; turn.foot.hidden = true;
    const steps = el("details", "steps"), summary = el("summary"), list = el("div", "steplist");
    const dot = el("span", "dot"), label = el("span", "", "Working…");
    summary.append(dot, label); steps.append(summary, list);
    turn.node.insertBefore(steps, turn.bubble);
    this._log.appendChild(turn.node);
    this._drawTop();
    this._log.scrollTop = this._log.scrollHeight;

    const started = performance.now();
    const byKey = new Map();
    let streamed = "", thinking = null, meta = {}, count = 0, frame = 0, done = false;
    const paint = () => { frame = 0; const was = this._atBottom(); turn.bubble.hidden = !streamed; if (streamed) markdown(turn.bubble, streamed); this._follow(was); };
    const repaint = () => { if (!frame) frame = requestAnimationFrame(paint); };
    const addStep = (cls, title) => { const row = el("div", `step ${cls}`), t = el("div", "t", title), d = el("div", "d"); row.append(t, d); list.appendChild(row); count += 1; return { row, t, d }; };

    const finish = (event) => {
      if (done) return;
      done = true;
      if (frame) cancelAnimationFrame(frame);
      const was = this._atBottom();
      turn.text = event.reply || streamed || "Done.";
      markdown(turn.bubble, turn.text);
      turn.bubble.hidden = false; turn.foot.hidden = false;
      if (event.error) turn.bubble.classList.add("error");
      if (event.conversation_id) { this._conversation = event.conversation_id; try { sessionStorage.setItem("console-chat-conversation", event.conversation_id); } catch (e) { /* private window */ } }
      const seconds = ((event.ms || performance.now() - started) / 1000).toFixed(1);
      dot.remove();
      const home = meta.route === "local";
      label.textContent = home ? `Answered at home · ${seconds} s` : `${count} step${count === 1 ? "" : "s"} · ${seconds} s${meta.cost_usd ? ` · ${credits(meta.cost_usd)} credits` : ""}`;
      if (!count) steps.remove();
      this._busy = false; send.disabled = false;
      this._follow(was);
    };

    const onEvent = (event) => {
      const was = this._atBottom();
      if (event.kind === "step") {
        let step = byKey.get(event.key);
        if (!step) { step = addStep("", event.title || "Step"); byKey.set(event.key, step); if (event.detail) step.d.textContent = event.detail; }
        if (event.result) step.d.textContent = (step.d.textContent ? step.d.textContent + "\n→ " : "") + event.result;
        if (event.state === "failed") step.row.classList.add("failed");
        if (event.title && !done) label.textContent = event.title + (event.state === "running" ? "…" : "");
        thinking = null;
      } else if (event.kind === "thinking") {
        if (!thinking) { thinking = addStep("think", "Thinking"); if (!done) label.textContent = "Thinking…"; }
        thinking.d.textContent += event.text;
      } else if (event.kind === "said") {
        const said = addStep("", "Said"); said.d.textContent = event.text; streamed = ""; repaint(); thinking = null;
      } else if (event.kind === "text") { streamed += event.text; if (!done) label.textContent = "Writing…"; repaint(); thinking = null; }
      else if (event.kind === "reset") { streamed = ""; repaint(); }
      else if (event.kind === "meta") { meta = event; }
      else if (event.kind === "done") { finish(event); }
      this._follow(was);
    };

    try {
      const stop = await this._hass.connection.subscribeMessage(onEvent, {
        type: "console/chat", text, conversation_id: this._conversation || null, earlier: Math.min(this._shown, 20),
      });
      const wait = setInterval(() => { if (done) { clearInterval(wait); try { stop(); } catch (e) { /* already closed */ } } }, 500);
    } catch (error) {
      if (error && error.code === "unknown_command") {   // an older Console on the box: one answer, no trail
        try {
          const answer = await this._hass.callWS({ type: "conversation/process", text, agent_id: "conversation.console", conversation_id: this._conversation, language: this._hass.language });
          const speech = (((answer.response || {}).speech || {}).plain || {}).speech;
          finish({ reply: speech || "Done.", conversation_id: answer.conversation_id, error: (answer.response || {}).response_type === "error" });
        } catch (e) { finish({ reply: "I couldn't reach Console's agent in Home Assistant. Try again in a moment.", error: true }); }
      } else finish({ reply: "I couldn't reach Console's agent in Home Assistant. Try again in a moment.", error: true });
    }
  }
}

if (!customElements.get("console-chat-card")) {
  customElements.define("console-chat-card", ConsoleChatCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "console-chat-card",
    name: "Console chat",
    description: "Talk to Console, this home's agent: live steps, rich replies you can copy, and your earlier messages.",
    preview: false,
  });
}
