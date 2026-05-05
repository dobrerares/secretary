#!/usr/bin/env python3
"""Interactive onboarding wizard for Secretary."""

import secrets
import sys
from pathlib import Path

try:
    from InquirerPy import inquirer
    from InquirerPy.separator import Separator
except ImportError:
    print("Missing dependency. Run: pip install InquirerPy")
    sys.exit(1)

ENV_PATH = Path(__file__).parent / ".env"
DATA_DIR = Path(__file__).parent / "data"

# ── Theme ────────────────────────────────────────────────────────────────

R = "\033[0m"
B = "\033[1m"
D = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
MAGENTA = "\033[35m"

LOGO = f"""{CYAN}
   ___                  _
  / __| ___ __ _ _ ___ | |_ __ _ _ _ _  _
  \\__ \\/ -_) _| '_/ -_)|  _/ _` | '_| || |
  |___/\\___\\__|_| \\___| \\__\\__,_|_|  \\_, |
                                      |__/
{R}"""


def banner(title: str) -> None:
    w = 52
    print(f"\n{CYAN}{'─' * w}{R}")
    print(f"{CYAN}  {title}{R}")
    print(f"{CYAN}{'─' * w}{R}\n")


def note(lines: list[str], title: str | None = None) -> None:
    w = 52
    border = f"{D}│{R}"
    if title:
        pad = w - len(title) - 4
        print(f"{D}┌─ {R}{B}{title}{R}{D} {'─' * max(pad, 1)}┐{R}")
    else:
        print(f"{D}┌{'─' * w}┐{R}")
    for line in lines:
        visible = len(
            line.replace(B, "")
            .replace(D, "")
            .replace(R, "")
            .replace(GREEN, "")
            .replace(YELLOW, "")
            .replace(CYAN, "")
            .replace(RED, "")
            .replace(MAGENTA, "")
        )
        padding = max(w - visible - 2, 0)
        print(f"{border} {line}{' ' * padding}{border}")
    print(f"{D}└{'─' * w}┘{R}")


def success(msg: str) -> None:
    print(f"  {GREEN}✓{R} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}!{R} {msg}")


# ── Models database ──────────────────────────────────────────────────────

PROVIDERS = [
    # ── Tier 1: Major cloud providers ────────────────────────────────
    {
        "name": "OpenAI",
        "value": "openai",
        "env_key": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com/api-keys",
        "models": [
            {"name": "GPT-4.1             latest, smartest", "value": "gpt-4.1"},
            {"name": "GPT-4.1 Mini        latest, balanced", "value": "gpt-4.1-mini"},
            {"name": "GPT-4.1 Nano        latest, fastest", "value": "gpt-4.1-nano"},
            {"name": "GPT-4o              proven all-round", "value": "gpt-4o"},
            {"name": "GPT-4o Mini         fast & cheap", "value": "gpt-4o-mini"},
            {"name": "o3                  deep reasoning", "value": "o3"},
            {"name": "o4 Mini             reasoning, cheap", "value": "o4-mini"},
        ],
    },
    {
        "name": "Anthropic",
        "value": "anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "key_url": "https://console.anthropic.com/settings/keys",
        "models": [
            {"name": "Claude Sonnet 4     best balance", "value": "claude-sonnet-4-20250514"},
            {"name": "Claude Opus 4       most capable", "value": "claude-opus-4-20250514"},
            {"name": "Claude Haiku 3.5    fast & cheap", "value": "claude-haiku-4-5-20251001"},
        ],
    },
    {
        "name": "Google Gemini",
        "value": "google",
        "env_key": "GEMINI_API_KEY",
        "key_url": "https://aistudio.google.com/apikey",
        "models": [
            {"name": "Gemini 2.5 Pro      best balance", "value": "gemini/gemini-2.5-pro"},
            {"name": "Gemini 2.5 Flash    fast & cheap", "value": "gemini/gemini-2.5-flash"},
            {"name": "Gemini 2.0 Flash    stable", "value": "gemini/gemini-2.0-flash"},
        ],
    },
    {
        "name": "xAI (Grok)",
        "value": "xai",
        "env_key": "XAI_API_KEY",
        "key_url": "https://console.x.ai",
        "models": [
            {"name": "Grok 4              most capable", "value": "xai/grok-4"},
            {"name": "Grok 4.1 Fast       fast reasoning", "value": "xai/grok-4-1-fast"},
            {"name": "Grok 3 Mini         cheap & fast", "value": "xai/grok-3-mini-beta"},
        ],
    },
    # ── Tier 2: Fast / specialized ───────────────────────────────────
    {
        "name": "Groq (fastest inference)",
        "value": "groq",
        "env_key": "GROQ_API_KEY",
        "key_url": "https://console.groq.com/keys",
        "models": [
            {"name": "Llama 3.3 70B       best quality", "value": "groq/llama-3.3-70b-versatile"},
            {"name": "Llama 3.1 8B        ultra fast", "value": "groq/llama-3.1-8b-instant"},
            {"name": "Mixtral 8x7B        MoE, balanced", "value": "groq/mixtral-8x7b-32768"},
            {"name": "Gemma 2 9B          lightweight", "value": "groq/gemma2-9b-it"},
        ],
    },
    {
        "name": "DeepSeek",
        "value": "deepseek",
        "env_key": "DEEPSEEK_API_KEY",
        "key_url": "https://platform.deepseek.com/api_keys",
        "models": [
            {"name": "DeepSeek Chat       general, very cheap", "value": "deepseek/deepseek-chat"},
            {"name": "DeepSeek Reasoner   reasoning model", "value": "deepseek/deepseek-reasoner"},
        ],
    },
    {
        "name": "Mistral AI",
        "value": "mistral",
        "env_key": "MISTRAL_API_KEY",
        "key_url": "https://console.mistral.ai/api-keys",
        "models": [
            {"name": "Mistral Large       most capable", "value": "mistral/mistral-large-latest"},
            {"name": "Mistral Medium      balanced", "value": "mistral/mistral-medium-latest"},
            {"name": "Mistral Small       fast & cheap", "value": "mistral/mistral-small-latest"},
            {"name": "Codestral           code specialist", "value": "mistral/codestral-latest"},
        ],
    },
    {
        "name": "Cohere",
        "value": "cohere",
        "env_key": "COHERE_API_KEY",
        "key_url": "https://dashboard.cohere.com/api-keys",
        "models": [
            {"name": "Command R+          most capable", "value": "cohere/command-r-plus"},
            {"name": "Command R           balanced", "value": "cohere/command-r"},
            {"name": "Command Light       fast & cheap", "value": "cohere/command-light"},
        ],
    },
    # ── Tier 3: Hosting platforms ────────────────────────────────────
    {
        "name": "Together AI",
        "value": "together",
        "env_key": "TOGETHER_API_KEY",
        "key_url": "https://api.together.xyz/settings/api-keys",
        "models": [
            {
                "name": "Llama 3.3 70B       best open model",
                "value": "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
            },
            {"name": "Qwen 2.5 72B        strong all-round", "value": "together_ai/Qwen/Qwen2.5-72B-Instruct-Turbo"},
            {"name": "DeepSeek V3         very capable", "value": "together_ai/deepseek-ai/DeepSeek-V3"},
            {"name": "Mixtral 8x22B       large MoE", "value": "together_ai/mistralai/Mixtral-8x22B-Instruct-v0.1"},
        ],
    },
    {
        "name": "Fireworks AI",
        "value": "fireworks",
        "env_key": "FIREWORKS_API_KEY",
        "key_url": "https://fireworks.ai/account/api-keys",
        "models": [
            {
                "name": "Llama 3.3 70B       fast & capable",
                "value": "fireworks_ai/accounts/fireworks/models/llama-v3p3-70b-instruct",
            },
            {
                "name": "Qwen 2.5 72B        strong coder",
                "value": "fireworks_ai/accounts/fireworks/models/qwen2p5-72b-instruct",
            },
            {
                "name": "Mixtral MoE 8x7B    efficient",
                "value": "fireworks_ai/accounts/fireworks/models/mixtral-8x7b-instruct",
            },
        ],
    },
    {
        "name": "Perplexity (built-in web search)",
        "value": "perplexity",
        "env_key": "PERPLEXITY_API_KEY",
        "key_url": "https://www.perplexity.ai/settings/api",
        "models": [
            {"name": "Sonar Pro           best, web-grounded", "value": "perplexity/sonar-pro"},
            {"name": "Sonar               fast, web-grounded", "value": "perplexity/sonar"},
            {"name": "Sonar Reasoning     deep research", "value": "perplexity/sonar-reasoning-pro"},
        ],
    },
    {
        "name": "OpenRouter (700+ models, one key)",
        "value": "openrouter",
        "env_key": "OPENROUTER_API_KEY",
        "key_url": "https://openrouter.ai/keys",
        "models": [
            {"name": "Auto                best available", "value": "openrouter/auto"},
            {"name": "Claude Sonnet 4     via OpenRouter", "value": "openrouter/anthropic/claude-sonnet-4-20250514"},
            {"name": "GPT-4o              via OpenRouter", "value": "openrouter/openai/gpt-4o"},
            {"name": "Llama 3.3 70B       via OpenRouter", "value": "openrouter/meta-llama/llama-3.3-70b-instruct"},
            {"name": "DeepSeek V3         via OpenRouter", "value": "openrouter/deepseek/deepseek-chat"},
        ],
    },
    # ── Tier 4: Self-hosted / local ──────────────────────────────────
    {
        "name": "Ollama (local, no API key)",
        "value": "ollama",
        "env_key": "",
        "key_url": "",
        "models": [
            {"name": "Llama 3.3 70B       best local model", "value": "ollama/llama3.3"},
            {"name": "Llama 3.1 8B        fast, lightweight", "value": "ollama/llama3.1"},
            {"name": "Qwen 2.5 32B        strong all-round", "value": "ollama/qwen2.5:32b"},
            {"name": "Mistral Small       balanced", "value": "ollama/mistral-small"},
            {"name": "Phi-4               Microsoft, small", "value": "ollama/phi4"},
            {"name": "Gemma 2 27B         Google, capable", "value": "ollama/gemma2:27b"},
            {"name": "DeepSeek R1 14B     reasoning", "value": "ollama/deepseek-r1:14b"},
        ],
    },
    {
        "name": "Azure OpenAI",
        "value": "azure",
        "env_key": "AZURE_API_KEY",
        "key_url": "https://portal.azure.com",
        "models": [
            {"name": "GPT-4o              your deployment", "value": "azure/gpt-4o"},
            {"name": "GPT-4               your deployment", "value": "azure/gpt-4"},
            {"name": "GPT-4o Mini         your deployment", "value": "azure/gpt-4o-mini"},
        ],
    },
    {
        "name": "AWS Bedrock",
        "value": "bedrock",
        "env_key": "",
        "key_url": "https://console.aws.amazon.com/bedrock",
        "models": [
            {"name": "Claude Sonnet 4     via Bedrock", "value": "bedrock/anthropic.claude-sonnet-4-20250514-v1:0"},
            {"name": "Claude Haiku 3.5    via Bedrock", "value": "bedrock/anthropic.claude-haiku-4-5-20251001-v1:0"},
            {"name": "Llama 3.1 70B       via Bedrock", "value": "bedrock/meta.llama3-1-70b-instruct-v1:0"},
        ],
    },
]


def pick_model(provider: dict) -> str:
    models = provider["models"]
    choices = [{"name": m["name"], "value": m["value"]} for m in models]
    choices.append(Separator())
    choices.append({"name": "Enter a custom model ID...", "value": "__custom__"})

    selected = inquirer.select(
        message=f"Pick a model ({provider['name']})",
        choices=choices,
        default=models[0]["value"],
        pointer="❯",
        show_cursor=False,
    ).execute()

    if selected == "__custom__":
        return (
            inquirer.text(
                message="Model ID (LiteLLM format)",
                validate=lambda v: len(v.strip()) > 0,
            )
            .execute()
            .strip()
        )

    return selected


# ── Main flow ────────────────────────────────────────────────────────────


def main() -> None:
    print(LOGO)
    note(
        [
            f"Welcome to the {B}Secretary{R} setup wizard.",
            "",
            "This will configure your AI personal secretary.",
            "It takes about 2 minutes.",
            "",
            f"{D}You can re-run this anytime: python setup.py{R}",
        ],
        "Setup",
    )

    if ENV_PATH.exists():
        overwrite = inquirer.confirm(
            message=".env already exists. Overwrite?",
            default=False,
        ).execute()
        if not overwrite:
            print(f"\n  Keeping existing .env. Run {B}python setup.py{R} again to reconfigure.\n")
            return

    config: dict[str, str] = {}

    # ── Telegram ─────────────────────────────────────────────────────

    banner("Telegram Bot")

    note(
        [
            f"1. Open Telegram, message {B}@BotFather{R}",
            f"2. Send {B}/newbot{R}, follow the prompts",
            f"3. Copy the token (looks like {D}123456:ABC...{R})",
        ],
        "Create a bot",
    )
    print()

    token = inquirer.secret(
        message="Bot token",
        validate=lambda v: ":" in v or "Token must contain ':'",
        transformer=lambda v: "•" * min(len(v), 20) if v else "",
    ).execute()
    config["SECRETARY_TELEGRAM_BOT_TOKEN"] = token
    success("Bot token saved")

    print()
    note(
        [
            "Secretary only responds to YOUR messages.",
            "It needs your numeric Telegram user ID to identify you.",
            "",
            "How to find it:",
            f"  1. Message {B}@userinfobot{R} on Telegram",
            "  2. It instantly replies with your ID",
            f"     (a number like {D}123456789{R})",
            "",
            f"{D}This is NOT your username — it's a number.{R}",
        ],
        "Your user ID",
    )
    print()

    user_id = (
        inquirer.text(
            message="Telegram user ID (number)",
            validate=lambda v: v.strip().isdigit() or "Must be a number — message @userinfobot on Telegram to get it",
        )
        .execute()
        .strip()
    )
    config["SECRETARY_TELEGRAM_USER_ID"] = user_id
    success(f"User ID: {user_id}")

    # ── LLM Provider ─────────────────────────────────────────────────

    banner("AI Model")

    # Group providers with separators
    tiers = [
        ("Cloud providers", ["openai", "anthropic", "google", "xai"]),
        ("Fast / specialized", ["groq", "deepseek", "mistral", "cohere"]),
        ("Hosting platforms", ["together", "fireworks", "perplexity", "openrouter"]),
        ("Self-hosted / enterprise", ["ollama", "azure", "bedrock"]),
    ]
    provider_choices = []
    for tier_name, tier_ids in tiers:
        provider_choices.append(Separator(f"── {tier_name} ──"))
        for pid in tier_ids:
            p = next((p for p in PROVIDERS if p["value"] == pid), None)
            if p:
                provider_choices.append({"name": p["name"], "value": p["value"]})
    provider_choices.append(Separator())
    provider_choices.append({"name": "Custom provider (enter manually)...", "value": "__custom__"})

    provider_id = inquirer.select(
        message="Choose your AI provider",
        choices=provider_choices,
        default="openai",
        pointer="❯",
        show_cursor=False,
    ).execute()

    if provider_id == "__custom__":
        model = (
            inquirer.text(
                message="LiteLLM model string (e.g. groq/llama3-70b)",
                validate=lambda v: len(v.strip()) > 0,
            )
            .execute()
            .strip()
        )
        config["SECRETARY_LLM_MODEL"] = model

        api_key = inquirer.secret(
            message="API key (leave empty if none)",
            transformer=lambda v: "•" * min(len(v), 20) if v else "(none)",
        ).execute()
        config["SECRETARY_LLM_API_KEY"] = api_key
    else:
        provider = next(p for p in PROVIDERS if p["value"] == provider_id)
        model = pick_model(provider)
        config["SECRETARY_LLM_MODEL"] = model
        success(f"Model: {model}")

        if provider_id == "azure":
            print()
            note(
                [
                    "Azure OpenAI needs your deployment endpoint.",
                    f"Find it in {B}portal.azure.com{R} > your resource > Keys and Endpoint.",
                ],
                "Azure Config",
            )
            print()
            azure_base = (
                inquirer.text(
                    message="Azure endpoint URL (https://xxx.openai.azure.com/)",
                    validate=lambda v: v.strip().startswith("http") or "Must be a URL",
                )
                .execute()
                .strip()
            )
            config["AZURE_API_BASE"] = azure_base
            api_key = inquirer.secret(
                message="Azure API key",
                validate=lambda v: len(v.strip()) > 0 or "Required",
            ).execute()
            config["SECRETARY_LLM_API_KEY"] = api_key
            config["AZURE_API_KEY"] = api_key
            success("Azure configured")
        elif provider_id == "bedrock":
            print()
            note(
                [
                    "AWS Bedrock uses your AWS credentials.",
                    f"Set {B}AWS_ACCESS_KEY_ID{R} and {B}AWS_SECRET_ACCESS_KEY{R}",
                    "in your environment, or configure the AWS CLI.",
                ],
                "AWS Bedrock",
            )
            print()
            aws_region = (
                inquirer.text(
                    message="AWS region",
                    default="us-east-1",
                )
                .execute()
                .strip()
            )
            config["AWS_REGION_NAME"] = aws_region
            config["SECRETARY_LLM_API_KEY"] = ""
            success(f"Bedrock configured (region: {aws_region})")
        elif provider["env_key"]:
            print()
            note([f"Get your key: {B}{provider['key_url']}{R}"], "API Key")
            print()
            api_key = inquirer.secret(
                message=f"{provider['name']} API key",
                validate=lambda v: len(v.strip()) > 0 or "API key required",
                transformer=lambda v: "•" * min(len(v), 20) if v else "",
            ).execute()
            config["SECRETARY_LLM_API_KEY"] = api_key
            config[provider["env_key"]] = api_key
            success("API key saved")
        else:
            config["SECRETARY_LLM_API_KEY"] = ""
            if provider_id == "ollama":
                warn("Make sure Ollama is running: ollama serve")

    # ── Voice ────────────────────────────────────────────────────────

    banner("Voice Notes")

    whisper_mode = inquirer.select(
        message="Transcription engine for voice messages",
        choices=[
            {"name": "Local  — faster-whisper (private, runs on your server)", "value": "local"},
            {"name": "Cloud  — OpenAI Whisper API ($0.006/min, faster)", "value": "cloud"},
            {"name": "Skip   — disable voice note support", "value": "skip"},
        ],
        default="local",
        pointer="❯",
        show_cursor=False,
    ).execute()

    config["SECRETARY_WHISPER_MODE"] = "local" if whisper_mode == "skip" else whisper_mode

    if whisper_mode == "local":
        size = inquirer.select(
            message="Whisper model size",
            choices=[
                {"name": "Tiny    ~75MB   (fast, lower accuracy)", "value": "tiny"},
                {"name": "Small   ~500MB  (good balance)", "value": "small"},
                {"name": "Medium  ~1.5GB  (high accuracy)", "value": "medium"},
            ],
            default="small",
            pointer="❯",
            show_cursor=False,
        ).execute()
        config["SECRETARY_WHISPER_MODEL_SIZE"] = size
    elif whisper_mode == "cloud":
        if "OPENAI_API_KEY" in config:
            reuse = inquirer.confirm(
                message="Reuse OpenAI key for Whisper?",
                default=True,
            ).execute()
            if reuse:
                config["SECRETARY_OPENAI_API_KEY"] = config["OPENAI_API_KEY"]
            else:
                config["SECRETARY_OPENAI_API_KEY"] = inquirer.secret(
                    message="OpenAI API key for Whisper",
                ).execute()
        else:
            config["SECRETARY_OPENAI_API_KEY"] = inquirer.secret(
                message="OpenAI API key for Whisper",
            ).execute()
        success("Whisper configured")

    # ── Calendar ─────────────────────────────────────────────────────

    banner("Calendar Sync")

    note(
        [
            "Secretary can read your existing calendars and",
            "show events alongside tasks in a unified view.",
            "",
            f"{D}You can set this up later from Settings.{R}",
        ],
        "Calendars",
    )
    print()

    cal_choices = inquirer.checkbox(
        message="Connect calendars (space to select, enter to continue)",
        choices=[
            {"name": "Google Calendar", "value": "google"},
            {"name": "CalDAV (iCloud, Fastmail, Nextcloud, ...)", "value": "caldav"},
        ],
        pointer="❯",
        show_cursor=False,
    ).execute()

    config["SECRETARY_GOOGLE_CALENDAR_ENABLED"] = "true" if "google" in cal_choices else "false"

    if "google" in cal_choices:
        print()
        note(
            [
                f"1. Go to {B}console.cloud.google.com/apis/credentials{R}",
                "2. Create OAuth 2.0 Client ID (Web application)",
                f"3. Redirect URI: {D}http://localhost:8000/web/settings/google/callback{R}",
                "4. Copy Client ID and Client Secret",
            ],
            "Google OAuth",
        )
        print()
        config["SECRETARY_GOOGLE_CLIENT_ID"] = (
            inquirer.text(
                message="Google Client ID",
            )
            .execute()
            .strip()
        )
        config["SECRETARY_GOOGLE_CLIENT_SECRET"] = inquirer.secret(
            message="Google Client Secret",
        ).execute()
        success("Google Calendar configured")
        warn("Complete the OAuth flow in Settings after starting Secretary.")

    if "caldav" in cal_choices:
        print()
        note(
            [
                "Common CalDAV server URLs:",
                f"  iCloud:    {D}https://caldav.icloud.com{R}",
                f"  Fastmail:  {D}https://caldav.fastmail.com/dav/calendars{R}",
                f"  Nextcloud: {D}https://your-server/remote.php/dav{R}",
            ],
            "CalDAV",
        )
        print()
        config["SECRETARY_CALDAV_URL"] = (
            inquirer.text(
                message="CalDAV server URL",
                validate=lambda v: v.strip().startswith("http") or "URL must start with http(s)://",
            )
            .execute()
            .strip()
        )
        config["SECRETARY_CALDAV_USERNAME"] = (
            inquirer.text(
                message="CalDAV username",
            )
            .execute()
            .strip()
        )
        config["SECRETARY_CALDAV_PASSWORD"] = inquirer.secret(
            message="CalDAV password",
        ).execute()
        success("CalDAV configured")

    # ── Web UI ───────────────────────────────────────────────────────

    banner("Web Dashboard")

    auth_mode = inquirer.select(
        message="Web UI authentication",
        choices=[
            {"name": "Auto-generate a secure token (recommended)", "value": "auto"},
            {"name": "Enter my own password/token", "value": "custom"},
            {"name": "No auth (Tailscale / trusted network only)", "value": "none"},
        ],
        default="auto",
        pointer="❯",
        show_cursor=False,
    ).execute()

    if auth_mode == "auto":
        web_token = secrets.token_urlsafe(32)
        config["SECRETARY_WEB_AUTH_TOKEN"] = web_token
    elif auth_mode == "custom":
        web_token = inquirer.secret(message="Auth token").execute()
        config["SECRETARY_WEB_AUTH_TOKEN"] = web_token
    else:
        web_token = ""
        config["SECRETARY_WEB_AUTH_TOKEN"] = ""
        warn("No auth — make sure the server isn't publicly accessible.")

    # ── Defaults ─────────────────────────────────────────────────────

    config.setdefault("SECRETARY_DATABASE_URL", "sqlite+aiosqlite:///data/secretary.db")
    config.setdefault("SECRETARY_LOG_LEVEL", "INFO")
    config.setdefault("SECRETARY_BOT_MODE", "polling")
    config.setdefault("SECRETARY_WEBHOOK_URL", "")
    config.setdefault("SECRETARY_WHISPER_MODEL_SIZE", "small")
    config.setdefault("SECRETARY_OPENAI_API_KEY", "")
    config.setdefault("SECRETARY_GOOGLE_CALENDAR_ENABLED", "false")
    config.setdefault("SECRETARY_GOOGLE_CLIENT_ID", "")
    config.setdefault("SECRETARY_GOOGLE_CLIENT_SECRET", "")
    config.setdefault("SECRETARY_CALDAV_URL", "")
    config.setdefault("SECRETARY_CALDAV_USERNAME", "")
    config.setdefault("SECRETARY_CALDAV_PASSWORD", "")
    config.setdefault("SECRETARY_CALENDAR_SYNC_INTERVAL_MINUTES", "15")

    # ── Write .env ───────────────────────────────────────────────────

    banner("Writing configuration")

    lines = [
        "# Secretary — generated by setup wizard",
        "",
        "# Telegram",
        f"SECRETARY_TELEGRAM_BOT_TOKEN={config['SECRETARY_TELEGRAM_BOT_TOKEN']}",
        f"SECRETARY_TELEGRAM_USER_ID={config['SECRETARY_TELEGRAM_USER_ID']}",
        "",
        "# AI Model",
        f"SECRETARY_LLM_MODEL={config['SECRETARY_LLM_MODEL']}",
        f"SECRETARY_LLM_API_KEY={config['SECRETARY_LLM_API_KEY']}",
    ]

    env_keys = [p["env_key"] for p in PROVIDERS if p["env_key"]]
    for key in env_keys:
        if key in config and config[key]:
            lines.append(f"{key}={config[key]}")
    for extra in ("AZURE_API_BASE", "AWS_REGION_NAME"):
        if extra in config and config[extra]:
            lines.append(f"{extra}={config[extra]}")

    lines += [
        "",
        "# Web UI",
        f"SECRETARY_WEB_AUTH_TOKEN={config['SECRETARY_WEB_AUTH_TOKEN']}",
        "",
        "# Voice",
        f"SECRETARY_WHISPER_MODE={config['SECRETARY_WHISPER_MODE']}",
        f"SECRETARY_WHISPER_MODEL_SIZE={config['SECRETARY_WHISPER_MODEL_SIZE']}",
        f"SECRETARY_OPENAI_API_KEY={config['SECRETARY_OPENAI_API_KEY']}",
        "",
        "# Database",
        f"SECRETARY_DATABASE_URL={config['SECRETARY_DATABASE_URL']}",
        f"SECRETARY_LOG_LEVEL={config['SECRETARY_LOG_LEVEL']}",
        "",
        "# Bot",
        f"SECRETARY_BOT_MODE={config['SECRETARY_BOT_MODE']}",
        f"SECRETARY_WEBHOOK_URL={config['SECRETARY_WEBHOOK_URL']}",
        "",
        "# Calendar",
        f"SECRETARY_GOOGLE_CALENDAR_ENABLED={config['SECRETARY_GOOGLE_CALENDAR_ENABLED']}",
        f"SECRETARY_GOOGLE_CLIENT_ID={config['SECRETARY_GOOGLE_CLIENT_ID']}",
        f"SECRETARY_GOOGLE_CLIENT_SECRET={config['SECRETARY_GOOGLE_CLIENT_SECRET']}",
        f"SECRETARY_CALDAV_URL={config['SECRETARY_CALDAV_URL']}",
        f"SECRETARY_CALDAV_USERNAME={config['SECRETARY_CALDAV_USERNAME']}",
        f"SECRETARY_CALDAV_PASSWORD={config['SECRETARY_CALDAV_PASSWORD']}",
        f"SECRETARY_CALENDAR_SYNC_INTERVAL_MINUTES={config['SECRETARY_CALENDAR_SYNC_INTERVAL_MINUTES']}",
    ]

    DATA_DIR.mkdir(exist_ok=True)
    ENV_PATH.write_text("\n".join(lines) + "\n")
    success(f"Wrote {ENV_PATH}")

    # ── Done ─────────────────────────────────────────────────────────

    start_lines = [
        f"{B}Start Secretary:{R}",
        "",
        f"  {CYAN}docker compose up{R}",
        "",
        "  or without Docker:",
        "",
        f"  {CYAN}pip install -e .{R}",
        f"  {CYAN}uvicorn secretary.main:app --host 0.0.0.0 --port 8000{R}",
    ]

    access_lines = [
        f"{B}Telegram:{R}  Open your bot and send /help",
    ]
    if web_token:
        access_lines += [
            "",
            f"{B}Web UI:{R}",
            f"  {CYAN}http://localhost:8000/web/tasks?token={web_token}{R}",
            "",
            f"{D}Save this token — you'll need it to log in.{R}",
        ]
    else:
        access_lines += [
            "",
            f"{B}Web UI:{R}   {CYAN}http://localhost:8000/web/tasks{R}",
        ]

    note(start_lines, "Start")
    print()
    note(access_lines, "Access")
    print()
    note(
        [
            f"Edit {B}.env{R} to change settings anytime.",
            f"Use {B}/settings{R} in Telegram or the web dashboard",
            "to configure areas, wake time, and auto-approve.",
        ],
        "Tips",
    )
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {D}Setup cancelled.{R}\n")
        sys.exit(1)
