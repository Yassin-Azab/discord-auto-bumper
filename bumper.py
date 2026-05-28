import asyncio
import aiohttp
import json
import os
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List

import discord
from discord import Client

# ========== CONFIGURATION ==========
# These are injected via GitHub Secrets (environment variables)
TOKENS = [
    os.getenv("TOKEN_1"),
    os.getenv("TOKEN_2"),
    os.getenv("TOKEN_3"),
    os.getenv("TOKEN_4")
]
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

# Bot IDs (provided by you)
BOTS = {
    "disboard": {"app_id": 302050872383242240, "cmd_name": "bump"},
    "topgg": {"app_id": 422087909634736160, "cmd_name": "vote"}
}

STATE_FILE = "bump_state.json"
RANDOM_DELAY_MIN = 15   # minutes
RANDOM_DELAY_MAX = 30   # minutes

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BumpManager:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.clients: List[Client] = []
        self.state = self.load_state()

    def load_state(self) -> dict:
        """Load state from JSON file, create default if missing"""
        default = {
            "current_account": 0,            # 0,1,2,3
            "bumps_done_this_account": 0,    # 0,1,2 (3 = rotate)
            "next_bump_time": None,          # ISO format string or null
            "last_bump_time": None
        }
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                # Ensure all keys exist
                for k, v in default.items():
                    if k not in data:
                        data[k] = v
                return data
        return default

    def save_state(self):
        """Write state back to JSON file (will be committed by GitHub Action)"""
        with open(STATE_FILE, "w") as f:
            json.dump(self.state, f, indent=2)
        logger.info("State saved")

    async def init_clients(self):
        """Login with all 4 user tokens (only the active one will be used)"""
        self.session = aiohttp.ClientSession()
        for i, token in enumerate(TOKENS):
            if not token or token == "":
                logger.warning(f"Token {i+1} is empty, skipping")
                continue
            client = Client()

            @client.event
            async def on_ready():
                logger.info(f"Client {i+1} ready as {client.user.name}")

            try:
                await client.login(token)
                await client.connect()
                self.clients.append(client)
                logger.info(f"Logged in client {i+1}")
            except Exception as e:
                logger.error(f"Failed to login client {i+1}: {e}")
        logger.info(f"Total active clients: {len(self.clients)}")

    async def send_slash_command(self, client: Client, app_id: int, cmd_name: str) -> bool:
        """Send slash command via HTTP API (type 2 interaction)"""
        try:
            headers = {
                "Authorization": client.http.token,
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
            async with self.session.post(
                "https://discord.com/api/v10/interactions",
                headers=headers,
                json=payload
            ) as resp:
                if resp.status in (200, 204):
                    logger.info(f"Slash command '{cmd_name}' sent successfully")
                    return True
                else:
                    text = await resp.text()
                    logger.error(f"Failed: {resp.status} - {text}")
                    return False
        except Exception as e:
            logger.error(f"Error sending slash: {e}")
            return False

    async def bump_both_bots(self, account_index: int) -> bool:
        """Bump Disboard and Top.gg using the given account"""
        if account_index >= len(self.clients):
            logger.error(f"Account {account_index} not available")
            return False
        client = self.clients[account_index]
        success = True
        for bot_name, bot_info in BOTS.items():
            logger.info(f"Bumping {bot_name} with account {account_index+1}")
            ok = await self.send_slash_command(client, bot_info["app_id"], bot_info["cmd_name"])
            if not ok:
                logger.warning(f"{bot_name} bump failed (bot may not be in server, skipping)")
                success = False
            await asyncio.sleep(2)  # small delay between commands
        return success

    async def run_check(self):
        """Main logic: check if it's time to bump, do it, update state"""
        # Ensure we have clients
        if not self.clients:
            logger.error("No clients connected. Check tokens.")
            return

        now = datetime.utcnow()
        next_bump = None
        if self.state["next_bump_time"]:
            next_bump = datetime.fromisoformat(self.state["next_bump_time"])

        # If first run or time has come
        if next_bump is None or now >= next_bump:
            account_idx = self.state["current_account"]
            logger.info(f"Bumping using account {account_idx+1} (bump #{self.state['bumps_done_this_account']+1} of 3)")

            # Perform the bump
            success = await self.bump_both_bots(account_idx)

            # Update state
            self.state["last_bump_time"] = now.isoformat()
            self.state["bumps_done_this_account"] += 1

            # If 3 bumps done with this account, rotate to next
            if self.state["bumps_done_this_account"] >= 3:
                self.state["current_account"] = (self.state["current_account"] + 1) % 4
                self.state["bumps_done_this_account"] = 0
                logger.info(f"Rotated to account {self.state['current_account']+1}")

            # Compute next bump time = now + 2h + random(15-30)min
            delay_minutes = 120 + random.randint(RANDOM_DELAY_MIN, RANDOM_DELAY_MAX)
            next_time = now + timedelta(minutes=delay_minutes)
            self.state["next_bump_time"] = next_time.isoformat()
            logger.info(f"Next bump scheduled at {next_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")

            self.save_state()
        else:
            logger.info(f"Not yet time. Next bump at {next_bump.strftime('%Y-%m-%d %H:%M:%S')} UTC")

    async def cleanup(self):
        if self.session:
            await self.session.close()
        for client in self.clients:
            await client.close()

async def main():
    manager = BumpManager()
    await manager.init_clients()
    await manager.run_check()
    await manager.cleanup()

if __name__ == "__main__":
    asyncio.run(main())