import asyncio
import aiohttp
import json
import os
import random
import logging
from datetime import datetime, timedelta

# ========== CONFIG ==========
TOKENS = [
    os.getenv("TOKEN_1", ""),
    os.getenv("TOKEN_2", ""),
    os.getenv("TOKEN_3", ""),
    os.getenv("TOKEN_4", "")
]
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

# Disboard – exact IDs from your captured request
DISBOARD_APP_ID = "302050872383242240"
DISBOARD_CMD_ID = "947088344167366698"
DISBOARD_CMD_VERSION = "1051151064008769576"  # <-- REQUIRED!
DISBOARD_CMD_NAME = "bump"

STATE_FILE = "bump_state.json"
DELAY_MIN = 15
DELAY_MAX = 30

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
            for k, v in default.items():
                if k not in data:
                    data[k] = v
            return data
    return default

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    logger.info("State saved")

def generate_nonce():
    """Generate a snowflake-like nonce"""
    return str((int(datetime.utcnow().timestamp() * 1000) - 1420070400000) << 22 | random.randint(0, 4194303))

async def send_slash_command(session, token, app_id, cmd_id, cmd_version, cmd_name):
    """Send interaction matching the exact captured payload structure"""
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    }
    
    payload = {
        "type": 2,
        "application_id": app_id,
        "guild_id": str(GUILD_ID),
        "channel_id": str(CHANNEL_ID),
        "session_id": "".join(random.choices("0123456789abcdef", k=32)),  # 32-char hex string
        "data": {
            "version": cmd_version,  # <-- THIS WAS MISSING!
            "id": cmd_id,
            "name": cmd_name,
            "type": 1,
            "options": [],
            "application_command": {
                "id": cmd_id,
                "type": 1,
                "application_id": app_id,
                "version": cmd_version,
                "name": cmd_name,
                "description": "Pushes your server to the top of all your server's tags and the front page",
                "description_default": "Pushes your server to the top of all your server's tags and the front page",
                "dm_permission": True,
                "integration_types": [0],
                "global_popularity_rank": 1,
                "options": [],
                "description_localized": "Bump this server.",
                "name_localized": "bump"
            },
            "attachments": []
        },
        "nonce": generate_nonce(),
        "analytics_location": "slash_ui"
    }
    
    async with session.post(
        "https://discord.com/api/v9/interactions",  # v9 as per your request
        headers=headers,
        json=payload
    ) as resp:
        if resp.status in (200, 204):
            logger.info(f"✓ {cmd_name} sent successfully")
            return True
        else:
            text = await resp.text()
            logger.error(f"✗ {cmd_name} failed: {resp.status} - {text[:300]}")
            return False

async def bump_disboard(account_idx, token):
    async with aiohttp.ClientSession() as session:
        return await send_slash_command(
            session, 
            token, 
            DISBOARD_APP_ID, 
            DISBOARD_CMD_ID, 
            DISBOARD_CMD_VERSION,  # <-- Pass version
            DISBOARD_CMD_NAME
        )

async def main():
    state = load_state()
    now = datetime.utcnow()

    next_time = None
    if state["next_bump_time"]:
        next_time = datetime.fromisoformat(state["next_bump_time"])

    if next_time is None or now >= next_time:
        account = state["current_account"]
        token = TOKENS[account]
        if not token:
            logger.error(f"Token {account+1} is missing")
            return

        logger.info(f"Bumping Disboard with account {account+1} (bump #{state['bumps_done']+1}/3)")
        ok = await bump_disboard(account, token)

        if ok:
            state["last_bump_time"] = now.isoformat()
            state["bumps_done"] += 1

            if state["bumps_done"] >= 3:
                state["current_account"] = (account + 1) % 4
                state["bumps_done"] = 0
                logger.info(f"Rotated to account {state['current_account']+1}")

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