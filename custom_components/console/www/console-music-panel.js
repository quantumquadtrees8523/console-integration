// Music Assistant in Home Assistant's sidebar (music_app.py): its own app, relayed by Home Assistant at
// /console_music/, signed in with the Home Assistant login. The words come from wording.py (panel config).
const MA_TOKEN = "ma_access_token"; // where Music Assistant's app keeps its sign-in (same origin, through the relay)

function heldToken(raw) {
  if (!raw) return null;
  try {
    const exp = Number(JSON.parse(atob(raw.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))).exp || 0);
    return exp && exp * 1000 < Date.now() ? null : raw;
  } catch (e) {
    return raw;
  }
}

const STYLE = `
  :host { display: flex; flex-direction: column; height: 100vh; background: var(--primary-background-color); color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  header { display: flex; align-items: center; height: 56px; padding: 0 12px; gap: 12px; flex: none; background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff); font-size: 20px; }
  header button { background: none; border: 0; color: inherit; cursor: pointer; padding: 8px; display: none; }
  :host([narrow]) header button { display: block; }
  iframe { flex: 1; width: 100%; border: 0; min-height: 0; background: #181818; }
  .strip { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 10px 16px; border-bottom: 1px solid var(--divider-color); background: var(--card-background-color); font-size: 14px; }
  .strip p { margin: 0; flex: 1; min-width: 240px; line-height: 20px; }
  .bad { color: var(--error-color, #db4437); }
  .center { margin: 48px auto; max-width: 520px; padding: 0 24px; line-height: 22px; }
  button.act { font: inherit; font-size: 14px; padding: 7px 14px; border-radius: 18px; border: 1px solid var(--divider-color); background: none; color: var(--primary-color); cursor: pointer; }
  button.act[disabled] { opacity: .5; cursor: default; }
`;

class ConsoleMusicPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._phase = "loading";
    this._src = "";
    this._haLogin = true;
    this._note = "";
    this._linking = false;
    this._started = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._started) { this._started = true; this._open(); }
  }

  set narrow(narrow) { this.toggleAttribute("narrow", !!narrow); }

  set panel(panel) {
    this._words = (panel && panel.config && panel.config.words) || {};
    this._title = (panel && panel.config && panel.config.title) || "Music Assistant";
    this._render();
  }

  _w(key) { return (this._words || {})[key] || key; }

  async _post(path, body) {
    const r = await this._hass.fetchWithAuth(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
    return d;
  }

  _show(path, code) {
    // A fresh src each time, so the app reloads with the new sign-in.
    this._src = `${path}?${code ? `code=${encodeURIComponent(code)}&` : ""}t=${Date.now()}`;
    this._phase = "ready";
  }

  async _open() {
    this._phase = "loading";
    this._render();
    try {
      const s = await this._post("/api/console/music/session", { fresh: !heldToken(localStorage.getItem(MA_TOKEN)) });
      if (!s.up) this._phase = "down";
      else { this._haLogin = !!s.ha_login; this._show(s.path || "/console_music/", s.code); }
    } catch (e) {
      this._note = e.message || String(e);
      this._phase = "error";
    }
    this._render();
  }

  async _link() {
    const token = heldToken(localStorage.getItem(MA_TOKEN));
    if (!token) { this._note = this._w("sign_in_first"); this._render(); return; }
    this._linking = true;
    this._note = "";
    this._render();
    try {
      const s = await this._post("/api/console/music/link", { ma_token: token });
      this._haLogin = true;
      this._show("/console_music/", s.code);
    } catch (e) {
      this._note = e.message || String(e);
    }
    this._linking = false;
    this._render();
  }

  _render() {
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    const header = `<header><button id="menu" aria-label="Menu">☰</button>${esc(this._title || "Music Assistant")}</header>`;
    let body;
    if (this._phase === "loading") body = `<p class="center">${esc(this._w("opening"))}</p>`;
    else if (this._phase === "down") body = `<div class="center"><p>${esc(this._w("down"))}</p><button class="act" id="retry">${esc(this._w("retry"))}</button></div>`;
    else if (this._phase === "error") body = `<div class="center"><p>${esc(this._w("failed"))} ${esc(this._note)}</p><button class="act" id="retry">${esc(this._w("retry"))}</button></div>`;
    else {
      const strip = this._haLogin ? "" : `<div class="strip"><p>${esc(this._w("link"))}${this._note ? `<br><span class="bad">${esc(this._note)}</span>` : ""}</p>
        <button class="act" id="link" ${this._linking ? "disabled" : ""}>${esc(this._linking ? this._w("linking") : this._w("link_button"))}</button></div>`;
      const frame = this.shadowRoot.querySelector("iframe");
      if (frame && frame.getAttribute("src") === this._src) {
        // Keep the running app: only the strip changes.
        const old = this.shadowRoot.querySelector(".strip");
        if (old) old.remove();
        if (strip) frame.insertAdjacentHTML("beforebegin", strip);
        this._wire();
        return;
      }
      body = `${strip}<iframe title="Music Assistant" allow="autoplay; fullscreen" src="${esc(this._src)}"></iframe>`;
    }
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>${header}${body}`;
    this._wire();
  }

  _wire() {
    const on = (id, fn) => { const el = this.shadowRoot.getElementById(id); if (el) el.onclick = fn; };
    on("retry", () => this._open());
    on("link", () => this._link());
    on("menu", () => this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true })));
  }
}

customElements.define("console-music-panel", ConsoleMusicPanel);
