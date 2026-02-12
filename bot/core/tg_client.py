from pyrogram import Client, enums
from pyrogram.errors import FloodWait
from asyncio import Lock, gather, sleep
from inspect import signature
from time import time as now

from .. import LOGGER
from .config_manager import Config

# --- Persistent FloodWait cooldown ---
# Saves the earliest-safe-retry timestamp to disk so that even if the
# process crashes and Docker restarts it, we never hit Telegram before
# the cooldown expires.  This prevents the cascade where each restart
# attempt adds MORE seconds to the ban.
_FLOODWAIT_FILE = ".floodwait"


def _read_cooldown() -> float:
    """Return the UNIX timestamp before which we must NOT contact Telegram."""
    try:
        with open(_FLOODWAIT_FILE) as f:
            return float(f.read().strip())
    except Exception:
        return 0.0


def _write_cooldown(until: float):
    """Persist the cooldown deadline to disk."""
    try:
        with open(_FLOODWAIT_FILE, "w") as f:
            f.write(f"{until}\n")
        LOGGER.info(f"FloodWait cooldown saved to disk (wait until {until:.0f})")
    except Exception as e:
        LOGGER.error(f"Could not write FloodWait file: {e}")


def _clear_cooldown():
    """Remove the cooldown file after a successful connection."""
    import os
    try:
        os.remove(_FLOODWAIT_FILE)
    except FileNotFoundError:
        pass
    except Exception as e:
        LOGGER.error(f"Could not remove FloodWait file: {e}")


async def _wait_for_cooldown(label: str = ""):
    """If a FloodWait cooldown is saved on disk, sleep until it expires."""
    deadline = _read_cooldown()
    remaining = deadline - now()
    if remaining > 0:
        LOGGER.warning(
            f"[{label}] Previous FloodWait still active — sleeping {remaining:.0f}s "
            f"before contacting Telegram..."
        )
        await sleep(remaining + 2)  # +2s safety margin


async def _handle_floodwait(e: FloodWait, label: str):
    """Central FloodWait handler: log, persist to disk, then sleep."""
    wait_secs = e.value + 10  # +10s safety margin
    deadline = now() + wait_secs
    LOGGER.warning(
        f"[{label}] FloodWait received! Must wait {e.value}s. "
        f"Sleeping {wait_secs}s (until timestamp {deadline:.0f})..."
    )
    _write_cooldown(deadline)
    await sleep(wait_secs)


class TgClient:
    _lock = Lock()
    _hlock = Lock()

    bot = None
    user = None
    helper_bots = {}
    helper_loads = {}

    BNAME = ""
    ID = 0
    IS_PREMIUM_USER = False
    MAX_SPLIT_SIZE = 2097152000

    @classmethod
    def wztgClient(cls, *args, **kwargs):
        kwargs["api_id"] = Config.TELEGRAM_API
        kwargs["api_hash"] = Config.TELEGRAM_HASH
        kwargs["proxy"] = Config.TG_PROXY
        kwargs["parse_mode"] = enums.ParseMode.HTML
        kwargs["in_memory"] = True
        for param, value in {
            "max_concurrent_transmissions": 100,
            "skip_updates": False,
        }.items():
            if param in signature(Client.__init__).parameters:
                kwargs[param] = value
        return Client(*args, **kwargs)

    @classmethod
    async def start_hclient(cls, no, b_token):
        try:
            hbot = cls.wztgClient(
                f"WZ-HBot{no}",
                bot_token=b_token,
                no_updates=True,
            )
            await _wait_for_cooldown(f"HelperBot-{no}")
            while True:
                try:
                    await hbot.start()
                    break
                except FloodWait as e:
                    await _handle_floodwait(e, f"HelperBot-{no}")
            LOGGER.info(f"Helper Bot [@{hbot.me.username}] Started!")
            cls.helper_bots[no], cls.helper_loads[no] = hbot, 0
        except Exception as e:
            LOGGER.error(f"Failed to start helper bot {no} from HELPER_TOKENS. {e}")
            cls.helper_bots.pop(no, None)

    @classmethod
    async def start_helper_bots(cls):
        if not Config.HELPER_TOKENS:
            return
        LOGGER.info("Generating helper client from HELPER_TOKENS")
        async with cls._hlock:
            await gather(
                *(
                    cls.start_hclient(no, b_token)
                    for no, b_token in enumerate(Config.HELPER_TOKENS.split(), start=1)
                )
            )

    @classmethod
    async def start_bot(cls):
        LOGGER.info("Generating client from BOT_TOKEN")
        cls.ID = Config.BOT_TOKEN.split(":", 1)[0]
        cls.bot = cls.wztgClient(
            f"MM-Bot{cls.ID}",
            bot_token=Config.BOT_TOKEN,
            workdir=".",
        )
        # Respect any cooldown from a previous crash
        await _wait_for_cooldown("Bot")
        while True:
            try:
                await cls.bot.start()
                _clear_cooldown()  # Success! Remove cooldown file
                break
            except FloodWait as e:
                await _handle_floodwait(e, "Bot")
        cls.BNAME = cls.bot.me.username
        cls.ID = Config.BOT_TOKEN.split(":", 1)[0]
        LOGGER.info(f"MM_LeechBot : [@{cls.BNAME}] Started!")

    @classmethod
    async def start_user(cls):
        if Config.USER_SESSION_STRING:
            LOGGER.info("Generating client from USER_SESSION_STRING")
            try:
                cls.user = cls.wztgClient(
                    "WZ-User",
                    session_string=Config.USER_SESSION_STRING,
                    sleep_threshold=60,
                    no_updates=True,
                )
                await _wait_for_cooldown("User")
                while True:
                    try:
                        await cls.user.start()
                        _clear_cooldown()
                        break
                    except FloodWait as e:
                        await _handle_floodwait(e, "User")
                cls.IS_PREMIUM_USER = cls.user.me.is_premium
                if cls.IS_PREMIUM_USER:
                    cls.MAX_SPLIT_SIZE = 4194304000
                uname = cls.user.me.username or cls.user.me.first_name
                LOGGER.info(f"WZ User : [{uname}] Started!")
            except Exception as e:
                LOGGER.error(f"Failed to start client from USER_SESSION_STRING. {e}")
                cls.IS_PREMIUM_USER = False
                cls.user = None

    @classmethod
    async def stop(cls):
        async with cls._lock:
            if cls.bot:
                await cls.bot.stop()
                cls.bot = None
            if cls.user:
                await cls.user.stop()
                cls.user = None
            if cls.helper_bots:
                await gather(*[h_bot.stop() for h_bot in cls.helper_bots.values()])
                cls.helper_bots = {}
            LOGGER.info("All Client(s) stopped")

    @classmethod
    async def reload(cls):
        async with cls._lock:
            await cls.bot.restart()
            if cls.user:
                await cls.user.restart()
            if cls.helper_bots:
                await gather(*[h_bot.restart() for h_bot in cls.helper_bots.values()])
            LOGGER.info("All Client(s) restarted")
