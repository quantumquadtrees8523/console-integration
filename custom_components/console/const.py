"""Names and settings in one place."""

DOMAIN = "console"
NAME = "Console"
VERSION = "0.13.0"

AGENT_NAME = "Console"

# The router's models (OpenRouter ids). Flash answers everything it can; Pro only after Flash fails or
# hands a hard case up.
MODEL_FLASH = "deepseek/deepseek-v4.1-flash"
MODEL_PRO = "deepseek/deepseek-v4-pro-0813"
EFFORT_FAST = "none"  # plain device commands: thinking off
EFFORT_FULL = "low"  # everything else: a little thinking
MODEL_TIMEOUT_S = 25
MAX_TOOL_ROUNDS = 8  # for a plain command
MAX_TOOL_ROUNDS_FULL = 24  # for everything else: a skill like welcome reads memory, the house and other skills

OPENROUTER_URL = "https://openrouter.ai/api/v1"

# The routes a turn can take, in the order the router tries them.
ROUTE_LOCAL = "local"  # Home Assistant's own agent: no model, no internet
ROUTE_FAST = "flash_fast"  # Flash, thinking off
ROUTE_FULL = "flash"  # Flash, thinking low
ROUTE_PRO = "pro"  # Pro, after a failure or a hard case
ROUTE_FALLBACK = "fallback"  # the cloud agent couldn't be used; the person was told so
ROUTE_OTHER = "other_agent"  # another agent (Claude, through the MCP server) did it with Sunrise's tools
ROUTES = (ROUTE_LOCAL, ROUTE_FAST, ROUTE_FULL, ROUTE_PRO, ROUTE_FALLBACK, ROUTE_OTHER)

# Where a request came from (the Plan tab's "Where it went"). Kept on the box only.
PATH_CHAT = "chat"  # the chat card
PATH_VOICE = "voice"  # a voice speaker or satellite
PATH_ASSIST = "assist"  # Assist in Home Assistant's own app or the Companion app, someone signed in
PATH_SUGGESTIONS = "suggestions"  # the weekly suggested-routines run
PATH_STYLE = "style"  # the weekly reply-style run (style.py)
PATH_AUTOMATIONS = "automations"  # an automation or script asking the agent (conversation.process)
PATH_TAPS = "suggestion_taps"  # a tap on a suggested routine: runs at home, no AI
PATH_CLAUDE = "claude"  # Claude and other agents, through the MCP server
PATH_SUPPORT = "support"  # other agents' requests while support mode was on
PATHS = (PATH_CHAT, PATH_VOICE, PATH_ASSIST, PATH_SUGGESTIONS, PATH_STYLE, PATH_AUTOMATIONS, PATH_TAPS, PATH_CLAUDE, PATH_SUPPORT)

# What each turn is counted as. Only these labels and their counts ever leave the box.
CATEGORIES = ("control", "status", "customization", "setup", "troubleshooting", "other")

# The allowance: the share of the month's cap at which the banner shows, and at which the cloud agent stops.
WARN_AT = 0.8
STOP_AT = 1.0

# What the house is on until the relay says otherwise.
DEFAULT_PLAN = {
    "tier": "free",
    "tier_name": "Free",
    "cap_usd": 1.0,
    "next": {"name": "Standard", "price": "$6.50 a month"},
    "contact": "Surya",
}

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1
MONTHS_KEPT = 12

STATIC_URL = "/console_static"
PANEL_URL = "console"

LLM_API_SUNRISE = "sunrise"
LLM_API_ASSIST = "assist"

SUPPORT_DAYS = 7
