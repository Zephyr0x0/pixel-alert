# bot.py
# Python 3.10+
# pip install -U discord.py

import os
import time
import json
from pathlib import Path
from typing import Dict, Any, Optional

import discord
from discord.ext import commands, tasks
from discord import app_commands

# ----------------- Token via environment variable -----------------
import os, sys

raw = os.getenv("DISCORD_TOKEN")
if not raw:
    raise SystemExit("Set DISCORD_TOKEN environment variable before running.")

raw = raw.strip()
if raw.lower().startswith("bot "):   # people paste "Bot abc..."
    raw = raw[4:].strip()

# Bot tokens have 3 parts separated by dots
if raw.count(".") != 2 or len(raw) < 50:
    raise SystemExit("DISCORD_TOKEN looks wrong. Re-copy it from Developer Portal → Bot tab.")

TOKEN = raw

DATA_FILE = Path("timers.json")
CONFIG_FILE = Path("config.json")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

from discord.app_commands import CommandInvokeError, MissingPermissions, CheckFailure

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    print("Slash command error:", repr(error))
    try:
        if isinstance(error, (MissingPermissions, CheckFailure)):
            await interaction.response.send_message(
                "You need **Manage Server** to run this command.", ephemeral=True
            )
        elif isinstance(error, CommandInvokeError) and error.__cause__:
            await interaction.response.send_message(
                f"Command failed: {error.__cause__}", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Something went wrong running this command.", ephemeral=True
            )
    except discord.InteractionResponded:
        await interaction.followup.send(
            "Something went wrong running this command.", ephemeral=True
        )

# timers[key] => dict with: guild_id, channel_id, user_id, interval, next_at
# key format: f"{guild_id}:{channel_id}:{user_id}"
timers: Dict[str, Dict[str, Any]] = {}

# config: { "<guild_id>": {"output_channel_id": int, "langs": { "<user_id>": "en|es" }} }
config: Dict[str, Dict[str, Any]] = {}

# ----------------- i18n (EN/ES) -----------------

def default_lang_from_interaction(inter: discord.Interaction) -> str:
    """
    Returns 'es' if the user's locale starts with 'es', otherwise 'en'.
    Handles discord.Locale enum safely.
    """
    try:
        loc = getattr(inter, "locale", None)
        if loc is None:
            return "en"
        # Locale may be an enum; prefer .value if present
        s = str(getattr(loc, "value", loc)).lower()
        return "es" if s.startswith("es") else "en"
    except Exception:
        return "en"
T = {
    "en": {
        "timer_set": "⏳ {mention}, your pixels will be ready in: {interval}s ({mins}m {secs}s). Pings will be sent in {channel}.",
        "no_output": "No output channel set yet. An admin must run /setoutput #channel first.",
        "invalid_output": "Configured output channel is invalid or missing. Ask an admin to run /setoutput again.",
        "gt_timer_none": "No active timer for you in {channel}.",
        "stopped": "Stopped your timer in {channel}.",
        "next": "Your timer in {channel} pings every {interval}s. Next ping in ~{remaining}s.",
        "ping": "⏰ {mention} — your pixels are ready! ({interval}s).",
        "lang_set_en": "✅ Language set to English.",
        "lang_set_es": "✅ Language set to Spanish.",
        "lang_show_en": "Your language is set to English.",
        "lang_show_es": "Your language is set to Spanish.",
        "run_in_server": "Run this in a server.",
        "number_gt_zero": "Number must be > 0.",
        "output_set": "✅ Output channel set to {channel}.",
        "no_timer_title": "No active timer.",
    },
    "es": {
        "timer_set": "⏳ {mention}, tus pixeles estaran listos en: {interval}s ({mins}m {secs}s). Los avisos se enviarán en {channel}.",
        "no_output": "Aún no hay canal de salida. Un admin debe ejecutar /setoutput #canal primero.",
        "invalid_output": "El canal de salida configurado es inválido o no existe. Pide a un admin que ejecute /setoutput de nuevo.",
        "gt_timer_none": "No tienes un temporizador activo en {channel}.",
        "stopped": "Se detuvo tu temporizador en {channel}.",
        "next": "Tu temporizador en {channel} avisa cada {interval}s. Próximo aviso en ~{remaining}s.",
        "ping": "⏰ {mention} — tus pixeles estan listos! ({interval}s).",
        "lang_set_en": "✅ Idioma configurado a Inglés.",
        "lang_set_es": "✅ Idioma configurado a Español.",
        "lang_show_en": "Tu idioma está configurado a Inglés.",
        "lang_show_es": "Tu idioma está configurado a Español.",
        "run_in_server": "Ejecuta esto en un servidor.",
        "number_gt_zero": "El número debe ser > 0.",
        "output_set": "✅ Canal de salida configurado a {channel}.",
        "no_timer_title": "No hay temporizador activo.",
    }
}

def get_user_lang(guild_id: Optional[int], user_id: int, fallback: str = "en") -> str:
    if guild_id is None:
        return fallback
    gid = str(guild_id)
    entry = config.get(gid, {})
    langs = entry.get("langs", {})
    return langs.get(str(user_id), fallback)

def set_user_lang(guild_id: int, user_id: int, lang: str) -> None:
    gid = str(guild_id)
    if gid not in config:
        config[gid] = {}
    if "langs" not in config[gid]:
        config[gid]["langs"] = {}
    config[gid]["langs"][str(user_id)] = lang
    save_config()

# ----------------- Persistence -----------------

def load_timers():
    global timers
    if DATA_FILE.exists():
        try:
            timers = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            for k, v in list(timers.items()):
                if not all(x in v for x in ("guild_id", "channel_id", "user_id", "interval", "next_at")):
                    timers.pop(k, None)
        except Exception:
            timers = {}
    else:
        timers = {}

def save_timers():
    try:
        DATA_FILE.write_text(json.dumps(timers, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def load_config():
    global config
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            config = {}
    else:
        config = {}

def save_config():
    try:
        CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def get_output_channel_id(guild_id: Optional[int]) -> Optional[int]:
    if guild_id is None:
        return None
    entry = config.get(str(guild_id))
    return entry.get("output_channel_id") if entry else None

def make_key(guild_id: int, channel_id: int, user_id: int) -> str:
    return f"{guild_id}:{channel_id}:{user_id}"

# ----------------- Bot lifecycle -----------------

@bot.event
async def on_ready():
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN not set. Export it and restart.")
    try:
        synced = await bot.tree.sync()  # global sync
        print(f"Synced {len(synced)} global slash commands.")
    except Exception as e:
        print(f"Slash sync failed: {e}")

    load_config()
    load_timers()
    if not ticker.is_running():
        ticker.start()
    print(f"Logged in as {bot.user} | timers loaded: {len(timers)}")

# ----------------- Admin: set/get output channel -----------------

@bot.tree.command(
    name="setoutput",
    description="Set the channel where ALL pings will be sent (admin only)."
)
@app_commands.describe(channel="Pick a TEXT channel (not category/voice).")
@app_commands.checks.has_permissions(manage_guild=True)
async def setoutput_cmd(interaction: discord.Interaction, channel: discord.TextChannel):
    lang = get_user_lang(interaction.guild_id, interaction.user.id, default_lang_from_interaction(interaction))

    if interaction.guild_id is None:
        await interaction.response.send_message(T[lang]["run_in_server"], ephemeral=True)
        return

    # Double-check permissions
    me = interaction.guild.me or await interaction.guild.fetch_member(bot.user.id)
    perms = channel.permissions_for(me)
    if not (perms.view_channel and perms.send_messages):
        await interaction.response.send_message(
            f"I don’t have permission to send messages in {channel.mention}. "
            f"Give me **View Channel** and **Send Messages** there, then try again.",
            ephemeral=True
        )
        return

    gid = str(interaction.guild_id)
    if gid not in config:
        config[gid] = {}
    config[gid]["output_channel_id"] = channel.id
    save_config()

    await interaction.response.send_message(T[lang]["output_set"].format(channel=channel.mention))

@bot.tree.command(name="getoutput", description="Show the current output channel for this server.")
async def getoutput_cmd(interaction: discord.Interaction):
    lang = get_user_lang(interaction.guild_id, interaction.user.id, default_lang_from_interaction(interaction))
    oc = get_output_channel_id(interaction.guild_id)
    if oc:
        ch = interaction.guild.get_channel(oc)
        await interaction.response.send_message(
            f"Current output channel: {ch.mention if ch else f'<#{oc}>'}", ephemeral=True
        )
    else:
        await interaction.response.send_message(T[lang]["no_output"], ephemeral=True)

# ----------------- Language commands -----------------

@bot.tree.command(name="setlang", description="Set your language / Configura tu idioma")
@app_commands.describe(language="en or es")
async def setlang_cmd(interaction: discord.Interaction, language: str):
    language = language.lower()
    if language not in ("en", "es"):
        await interaction.response.send_message("Use: en / es", ephemeral=True)
        return
    if interaction.guild_id is None:
        await interaction.response.send_message("Run this in a server.", ephemeral=True)
        return
    set_user_lang(interaction.guild_id, interaction.user.id, language)
    await interaction.response.send_message(
        T[language]["lang_set_en"] if language == "en" else T[language]["lang_set_es"],
        ephemeral=True
    )

@bot.tree.command(name="mylang", description="Show your language / Ver tu idioma")
async def mylang_cmd(interaction: discord.Interaction):
    lang = get_user_lang(interaction.guild_id, interaction.user.id, default_lang_from_interaction(interaction))
    await interaction.response.send_message(
        T[lang]["lang_show_en"] if lang == "en" else T[lang]["lang_show_es"],
        ephemeral=True
    )

# ----------------- User commands -----------------

@bot.tree.command(name="timer", description="Set a permanent repeating timer: number × 30 seconds.")
@app_commands.describe(number="Base number to multiply by 30 seconds (e.g., 128).")
async def timer_cmd(interaction: discord.Interaction, number: int):
    lang = get_user_lang(interaction.guild_id, interaction.user.id, default_lang_from_interaction(interaction))

    if number <= 0:
        await interaction.response.send_message(T[lang]["number_gt_zero"], ephemeral=True)
        return

    output_id = get_output_channel_id(interaction.guild_id)
    if output_id is None:
        await interaction.response.send_message(T[lang]["no_output"], ephemeral=True)
        return

    target_channel = interaction.guild.get_channel(output_id)
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message(T[lang]["invalid_output"], ephemeral=True)
        return

    interval = number * 30  # seconds
    now = time.time()
    key = make_key(interaction.guild_id, target_channel.id, interaction.user.id)

    timers[key] = {
        "guild_id": interaction.guild_id,
        "channel_id": target_channel.id,
        "user_id": interaction.user.id,
        "interval": interval,
        "next_at": now + interval
    }
    save_timers()

    mins = interval // 60
    secs = interval % 60
    await interaction.response.send_message(
        T[lang]["timer_set"].format(
            mention=interaction.user.mention,
            number=number,
            interval=interval,
            mins=int(mins),
            secs=int(secs),
            channel=target_channel.mention
        ),
        ephemeral=False
    )

@bot.tree.command(name="stop", description="Stop your permanent timer in this server's output channel.")
async def stop_cmd(interaction: discord.Interaction):
    lang = get_user_lang(interaction.guild_id, interaction.user.id, default_lang_from_interaction(interaction))

    output_id = get_output_channel_id(interaction.guild_id)
    if output_id is None:
        await interaction.response.send_message(T[lang]["no_output"], ephemeral=True)
        return

    key = make_key(interaction.guild_id, output_id, interaction.user.id)
    ch = interaction.guild.get_channel(output_id)

    if key in timers:
        timers.pop(key, None)
        save_timers()
        await interaction.response.send_message(
            T[lang]["stopped"].format(channel=ch.mention if ch else "#unknown")
        )
    else:
        await interaction.response.send_message(
            T[lang]["gt_timer_none"].format(channel=ch.mention if ch else "#unknown"),
            ephemeral=True
        )

@bot.tree.command(name="mytimer", description="Show your timer in this server's output channel.")
async def mytimer_cmd(interaction: discord.Interaction):
    lang = get_user_lang(interaction.guild_id, interaction.user.id, default_lang_from_interaction(interaction))

    output_id = get_output_channel_id(interaction.guild_id)
    if output_id is None:
        await interaction.response.send_message(T[lang]["no_output"], ephemeral=True)
        return

    key = make_key(interaction.guild_id, output_id, interaction.user.id)
    ch = interaction.guild.get_channel(output_id)
    t = timers.get(key)

    if not t:
        await interaction.response.send_message(
            T[lang]["gt_timer_none"].format(channel=ch.mention if ch else "#unknown"),
            ephemeral=True
        )
        return

    remaining = max(0, int(t["next_at"] - time.time()))
    await interaction.response.send_message(
        T[lang]["next"].format(
            channel=ch.mention if ch else "#unknown",
            interval=t["interval"],
            remaining=remaining
        )
    )

# ----------------- Background loop -----------------

@tasks.loop(seconds=10)
async def ticker():
    now = time.time()
    dirty = False
    for key, t in list(timers.items()):
        try:
            if now >= t["next_at"]:
                guild = bot.get_guild(int(t["guild_id"]))
                if guild is None:
                    continue
                channel = guild.get_channel(int(t["channel_id"]))
                if not isinstance(channel, discord.TextChannel):
                    continue

                member = guild.get_member(int(t["user_id"])) or await guild.fetch_member(int(t["user_id"]))
                mention = member.mention if member else f"<@{t['user_id']}>"

                # Language for this member
                lang = get_user_lang(int(t["guild_id"]), int(t["user_id"]), "en")

                await channel.send(
                    T[lang]["ping"].format(mention=mention, interval=t["interval"])
                )

                # Catch up if the bot was down
                while t["next_at"] <= now:
                    t["next_at"] += t["interval"]
                timers[key] = t
                dirty = True
        except Exception:
            continue

    if dirty:
        save_timers()

# ----------------- Run -----------------
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Set DISCORD_TOKEN environment variable before running.")
    bot.run(TOKEN)