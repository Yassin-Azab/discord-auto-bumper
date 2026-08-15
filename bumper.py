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

DISBOARD_APP_ID = "302050872383242240"
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
        "last_bump_time": None,
        "cached_cmd_version": None,  # Cache the version
        "version_last_updated": None
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

async def fetch_command_data(session, token, app_id, guild_id):
    """Fetch the current Disboard bump command data including version"""
    headers = {
        "Authorization": token,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    # Try to get commands from the guild's application command index
    url = f"https://discord.com/api/v9/guilds/{guild_id}/application-command-index"
    
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                logger.error(f"Failed to fetch commands: {resp.status}")
                return None
            
            data = await resp.json()
            
            # Search for Disboard's bump command
            if "application_commands" in data:
                for cmd in data["application_commands"]:
                    if (cmd.get("application_id") == app_id and 
                        cmd.get("name") == DISBOARD_CMD_NAME):
                        logger.info(f"Found bump command - ID: {cmd['id']}, Version: {cmd['version']}")
                        return {
                            "id": cmd["id"],
                            "version": cmd["version"],
                            "description": cmd.get("description", ""),
                            "full_data": cmd
                        }
            
            logger.error("Bump command not found in guild commands")
            return None
            
    except Exception as e:
        logger.error(f"Error fetching command data: {e}")
        return None

async def send_slash_command(session, token, guild_id, channel_id, cmd_data):
    """Send interaction with dynamically fetched command data"""
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    payload = {
        "type": 2,
        "application_id": DISBOARD_APP_ID,
        "guild_id": str(guild_id),
        "channel_id": str(channel_id),
        "session_id": "".join(random.choices("0123456789abcdef", k=32)),
        "data": {
            "version": cmd_data["version"],
            "id": cmd_data["id"],
            "name": DISBOARD_CMD_NAME,
            "type": 1,
            "options": [],
            "application_command": cmd_data.get("full_data", {
                "id": cmd_data["id"],
                "type": 1,
                "application_id": DISBOARD_APP_ID,
                "version": cmd_data["version"],
                "name": DISBOARD_CMD_NAME,
                "description": cmd_data.get("description", "Bump this server"),
            }),
            "attachments": []
        },
        "nonce": generate_nonce(),
        "analytics_location": "slash_ui"
    }
    
    async with session.post(
        "https://discord.com/api/v9/interactions",
        headers=headers,
        json=payload
    ) as resp:
        if resp.status in (200, 204):
            logger.info(f"✓ Bump sent successfully")
            return True
        else:
            text = await resp.text()
            logger.error(f"✗ Bump failed: {resp.status} - {text[:300]}")
            return False

async def bump_disboard(token, state):
    async with aiohttp.ClientSession() as session:
        # Check if we need to refresh the command version
        # Refresh if: no cached version, or last update was >24h ago, or it failed
        needs_refresh = (
            not state.get("cached_cmd_version") or
            not state.get("version_last_updated") or
            (datetime.utcnow() - datetime.fromisoformat(state["version_last_updated"])).total_seconds() > 86400
        )
        
        if needs_refresh:
            logger.info("Fetching latest Disboard command version...")
            cmd_data = await fetch_command_data(session, token, DISBOARD_APP_ID, GUILD_ID)
            
            if cmd_data:
                state["cached_cmd_version"] = cmd_data
                state["version_last_updated"] = datetime.utcnow().isoformat()
                logger.info(f"Updated command version: {cmd_data['version']}")
            else:
                if state.get("cached_cmd_version"):
                    logger.warning("Using cached version as fallback")
                    cmd_data = state["cached_cmd_version"]
                else:
                    logger.error("No command data available")
                    return False
        else:
            cmd_data = state["cached_cmd_version"]
            logger.info(f"Using cached command version: {cmd_data['version']}")
        
        return await send_slash_command(session, token, GUILD_ID, CHANNEL_ID, cmd_data)

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
        ok = await bump_disboard(token, state)

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
            logger.warning("Bump failed, retrying command fetch on next run")
            # Clear cached version to force refresh
            state["cached_cmd_version"] = None
            save_state(state)
    else:
        logger.info(f"Not yet time. Next bump at {next_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")

if __name__ == "__main__":
    asyncio.run(main())