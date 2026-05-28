import asyncio
import aiohttp
import json
import os
import random
import logging
from datetime import datetime, timedelta
from typing import Optional

# ========== CONFIG ==========
TOKENS = [
    os.getenv("TOKEN_1", ""),
    os.getenv("TOKEN_2", ""),
    os.getenv("TOKEN_3", ""),
    os.getenv("TOKEN_4", "")
]
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

BOTS = {
    "disboard": 302050872383242240,
    "topgg": 422087909634736160
}

STATE_FILE = "bump_state.json"
DELAY_MIN = 15   # minutes
DELAY_MAX = 30   # minutes

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_state():
    default = {
        "current_account": 0,
        "bumps_done": 0,
        "next_bump_time": None,
        "last_bump_time": None
    }
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            # migrate if missing keys
            for k, v in default.items():
                if k not in data:
                    data[k] = v
            return data
    return default

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    logger.info("State saved")

async def send_slash_command(session, token, app_id, cmd_name):
    """Send slash command via HTTP, no gateway connection"""
    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }
    payload = {
        "type": 2,
        "application_id": str(app_id),
        "guild_id": str(GUILD_ID),
        "channel_id": str(CHANNEL_ID),
        "session_id": str(random.getrandbits(64)),
        "data": {
            "type": 1,
            "name": cmd_name,
            "options": []
        }
    }
    async with session.post(
        "https://discord.com/api/v10/interactions",
        headers=headers,
        json=payload
    ) as resp:
        if resp.status in (200, 204):
            logger.info(f"✓ {cmd_name} sent successfully")
            return True
        else:
            text = await resp.text()
            logger.error(f"✗ {cmd_name} failed: {resp.status} - {text[:200]}")
            return False

async def bump_both(account_idx, token):
    """Bump Disboard and Top.gg using the given token"""
    async with aiohttp.ClientSession() as session:
        success = True
        for bot_name, app_id in BOTS.items():
            cmd = "bump" if bot_name == "disboard" else "vote"
            ok = await send_slash_command(session, token, app_id, cmd)
            if not ok:
                success = False
            await asyncio.sleep(1)  # tiny gap
        return success

async def main():
    state = load_state()
    now = datetime.utcnow()

    # Determine if it's time to bump
    next_time = None
    if state["next_bump_time"]:
        next_time = datetime.fromisoformat(state["next_bump_time"])

    if next_time is None or now >= next_time:
        account = state["current_account"]
        token = TOKENS[account]
        if not token:
            logger.error(f"Token {account+1} is missing")
            return

        logger.info(f"Bumping with account {account+1} (bump #{state['bumps_done']+1}/3)")
        ok = await bump_both(account, token)

        if ok:
            # Update state
            state["last_bump_time"] = now.isoformat()
            state["bumps_done"] += 1

            if state["bumps_done"] >= 3:
                state["current_account"] = (account + 1) % 4
                state["bumps_done"] = 0
                logger.info(f"Rotated to account {state['current_account']+1}")

            # Schedule next bump: 2h + random(15-30) min
            delay_minutes = 120 + random.randint(DELAY_MIN, DELAY_MAX)
            next_bump = now + timedelta(minutes=delay_minutes)
            state["next_bump_time"] = next_bump.isoformat()
            logger.info(f"Next bump scheduled at {next_bump.strftime('%Y-%m-%d %H:%M:%S')} UTC")

            save_state(state)
        else:
            logger.warning("Bump failed, state not updated")
    else:
        logger.info(f"Not yet time. Next bump at {next_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")

if __name__ == "__main__":
    asyncio.run(main())