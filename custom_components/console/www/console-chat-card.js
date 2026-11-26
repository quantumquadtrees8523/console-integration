// Console chat card: talk to Console, this home's agent, from a dashboard.
// It speaks to conversation.console through Home Assistant's own conversation API, and shows the
// allowance banner from sensor.console_cloud_agent. Nothing typed here is kept by the card: a reload
// starts a new conversation.
const AGENT = "conversation.console";
const SENSOR = "sensor.console_cloud_agent";

const STYLE = `
  :host { display: block; }
  ha-card { display: flex; flex-direction: column; height: var(--console-chat-height, 420px); overflow: hidden; }
  .banner { padding: 10px 16px; font-size: 14px; line-height: 20px; display: flex; gap: 10px; align-items: flex-start; }
  .banner.warn { background: color-mix(in srgb, var(--warning-color, #ffa600) 18%, transparent); }
  .banner.stop { background: color-mix(in srgb, var(--error-color, #db4437) 18%, transparent); }
  .banner.offline { background: color-mix(in srgb, var(--secondary-text-color, #888) 14%, transparent); }
  .banner.off { background: color-mix(in srgb, var(--secondary-text-color, #888) 20%, transparent); }
  .banner.support { background: color-mix(in srgb, var(--warning-color, #ffa600) 26%, transparent); }
  .banner a { color: var(--primary-color); white-space: nowrap; cursor: pointer; text-decoration: underline; }
  .log { flex: 1; overflow-y: auto; padding: 14px 16px 6px; display: flex; flex-direction: column; gap: 10px; }
  .hello { color: var(--secondary-text-color); font-size: 14px; line-height: 20px; }
  .msg { max-width: 86%; padding: 9px 13px; border-radius: 16px; font-size: 15px; line-height: 21px; white-space: pre-wrap; overflow-wrap: anywhere; }
  .me { align-self: flex-end; background: var(--primary-color); color: var(--text-primary-color, #fff); border-bottom-right-radius: 5px; }
  .it { align-self: flex-start; background: var(--secondary-background-color); color: var(--primary-text-color); border-bottom-left-radius: 5px; }
  .it.error { border: 1px solid var(--error-color, #db4437); }
  .took { align-self: flex-start; margin: -6px 0 0 6px; font-size: 11px; color: var(--secondary-text-color); }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip { border: 1px solid var(--divider-color); border-radius: 16px; padding: 6px 12px; font-size: 13px; background: none; color: var(--primary-text-color); cursor: pointer; font-family: inherit; }
  form { display: flex; gap: 8px; padding: 10px 12px 12px; border-top: 1px solid var(--divider-color); }
  input { flex: 1; min-width: 0; height: 42px; padding: 0 14px; border-radius: 21px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); font: inherit; font-size: 15px; }
  input:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
  button.send { height: 42px; padding: 0 18px; border-radius: 21px; border: 0; background: var(--primary-color); color: var(--text-primary-color, #fff); font: inherit; font-weight: 600; cursor: pointer; }
  button.send[disabled] { opacity: .5; cursor: default; }
`;

class ConsoleChatCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._messages = [];
    this._busy = false;
    this._conversation = undefined;
    this._banner = "";
  }

  setConfig(config) {
    this._config = { title: "Console", ...config };
    this._build();
  }

  static getStubConfig() { return { title: "Console" }; }
  getCardSize() { return 7; }
  getGridOptions() { return { columns: 12, rows: 7, min_rows: 4 }; }

  set hass(hass) {
    this._hass = hass;
    const sensor = hass.states[SENSOR];
    const key = sensor ? `${sensor.state}|${sensor.attributes.banner || ""}` : "none";
    if (key !== this._banner) { this._banner = key; this._drawBanner(sensor); }
    if (this._welcome === undefined) this._loadStatus();
  }

  async _loadStatus() {
    this._welcome = null;
    try {
      const status = await this._hass.callWS({ type: "console/status" });
      this._welcome = status.onboarding || {};
      this._contact = (status.plan || {}).contact || "Surya";
      this._drawLog();
    } catch (e) { /* an older Console: the card still chats */ }
  }

  _build() {
    const root = this.shadowRoot;
    root.innerHTML = `<style>${STYLE}</style>
      <ha-card>
        <div class="banner" hidden></div>
        <div class="log" role="log" aria-live="polite"></div>
        <form><input type="text" placeholder="Ask Console" aria-label="Ask Console" autocomplete="off" enterkeyhint="send">
        <button class="send" type="submit">Send</button></form>
      </ha-card>`;
    if (this._config.title) root.querySelector("ha-card").setAttribute("header", this._config.title);
    root.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault();
      const input = root.querySelector("input");
      const text = input.value.trim();
      if (text) { input.value = ""; this._send(text); }
    });
    this._drawLog();
  }

  _drawBanner(sensor) {
    const el = this.shadowRoot.querySelector(".banner");
    if (!el) return;
    const text = sensor && sensor.attributes.banner;
    el.hidden = !text;
    if (!text) return;
    el.className = `banner ${sensor.attributes.banner_kind || "warn"}`;
    el.textContent = text + " ";
    const link = document.createElement("a");
    const kind = sensor.attributes.banner_kind;
    link.textContent = kind === "offline" ? "Details" : kind === "support" ? "Turn it off" : kind === "off" ? "Settings" : "Need more?";
    link.addEventListener("click", () => {
      history.pushState(null, "", "/console");
      window.dispatchEvent(new CustomEvent("location-changed"));
    });
    el.appendChild(link);
  }

  _drawLog() {
    const log = this.shadowRoot.querySelector(".log");
    if (!log) return;
    log.replaceChildren();
    if (!this._messages.length) {
      const hello = document.createElement("div");
      hello.className = "hello";
      hello.textContent = "Ask for anything in your home: “turn off the kitchen lights”, “what's on right now?”, “add a dashboard for the kids' room”.";
      log.appendChild(hello);
      const welcome = this._welcome || {};
      if (welcome.available && !welcome.offered && !welcome.done) {
        // First run: Console speaks first, once.
        const offer = document.createElement("div");
        offer.className = "msg it";
        offer.textContent = "Welcome. I'm Console, this home's agent. Want me to show you around? I'll learn your rooms and devices, add anything that's waiting, and set up one routine with you. It takes a few minutes and you can stop any time.";
        log.appendChild(offer);
      }
      const chips = document.createElement("div");
      chips.className = "chips";
      const offers = [];
      if (welcome.available && !welcome.done) {
        offers.push([welcome.state === "started" ? "Pick up the welcome" : "Show me around", "Show me around."]);
        if (!welcome.offered) offers.push(["Not now", null]);
      }
      offers.push(["What's on right now?", "What's on right now?"]);
      for (const [label, text] of offers) {
        const chip = document.createElement("button");
        chip.className = "chip"; chip.type = "button"; chip.textContent = label;
        chip.addEventListener("click", () => {
          if (welcome.available && !welcome.offered) {
            welcome.offered = true;
            this._hass.callWS({ type: "console/onboarding/offered" }).catch(() => {});
          }
          if (text) this._send(text); else this._drawLog();
        });
        chips.appendChild(chip);
      }
      log.appendChild(chips);
    }
    for (const message of this._messages) {
      const bubble = document.createElement("div");
      bubble.className = `msg ${message.who}${message.error ? " error" : ""}`;
      bubble.textContent = message.text;
      log.appendChild(bubble);
      if (message.ms) {
        const took = document.createElement("div");
        took.className = "took";
        took.textContent = `${(message.ms / 1000).toFixed(1)} s`;
        log.appendChild(took);
      }
    }
    log.scrollTop = log.scrollHeight;
  }

  async _send(text) {
    if (this._busy || !this._hass) return;
    this._busy = true;
    this.shadowRoot.querySelector("button.send").disabled = true;
    this._messages.push({ who: "me", text });
    this._messages.push({ who: "it", text: "…" });
    this._drawLog();
    const started = performance.now();
    let reply = { who: "it", text: "" };
    try {
      const answer = await this._hass.callWS({
        type: "conversation/process", text, agent_id: AGENT,
        conversation_id: this._conversation, language: this._hass.language,
      });
      this._conversation = answer.conversation_id || this._conversation;
      const speech = (((answer.response || {}).speech || {}).plain || {}).speech;
      reply.text = speech || "Done.";
      reply.error = (answer.response || {}).response_type === "error";
      reply.ms = Math.round(performance.now() - started);
    } catch (error) {
      reply = { who: "it", text: "I couldn't reach Console's agent in Home Assistant. Try again in a moment.", error: true };
    }
    this._messages[this._messages.length - 1] = reply;
    this._busy = false;
    this.shadowRoot.querySelector("button.send").disabled = false;
    this._drawLog();
  }
}

if (!customElements.get("console-chat-card")) {
  customElements.define("console-chat-card", ConsoleChatCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "console-chat-card",
    name: "Console chat",
    description: "Talk to Console, this home's agent. Shows a banner when the month's allowance runs low.",
    preview: false,
  });
}
