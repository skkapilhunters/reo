import asyncio
import os
import pathlib
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Configure bot intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

async def get_dynamic_prefix(bot_instance, message: discord.Message):
    cog = bot_instance.get_cog("BotSettingsCog")
    if cog:
        return cog.get_prefix_for_message(message)
    return "!"

bot = commands.Bot(command_prefix=get_dynamic_prefix, intents=intents)

#bot = commands.Bot(command_prefix="!", intents=intents)

async def load_functions():
    """Recursively scans 'functions' and all subfolders to load every .py module."""
    functions_path = pathlib.Path("functions")

    if not functions_path.exists():
        print("[-] 'functions' directory not found. Creating one...")
        functions_path.mkdir(exist_ok=True)
        return

    print("[*] Loading dynamic modules...")
    # rglob("*.py") fetches .py files inside /functions/ and every subfolder level
    for file_path in functions_path.rglob("*.py"):
        # Ignore __init__.py, __pycache__, hidden files, or helper files starting with '_'
        if any(part.startswith(("_", ".")) for part in file_path.parts):
            continue

        # Convert path to dotted format across Windows/Linux:
        # e.g., functions\healthfunctionfolder\waterdrink.py -> functions.healthfunctionfolder.waterdrink
        extension_name = ".".join(file_path.with_suffix("").parts)

        try:
            await bot.load_extension(extension_name)
            print(f"    [+] Loaded: {extension_name}")
        except commands.NoEntryPointError:
            print(f"    [!] Skipped (missing setup function): {extension_name}")
        except Exception as e:
            print(f"    [-] Failed to load {extension_name}: {e}")

@bot.event
async def on_ready():
    print("-----------------------------------------")
    print(f" Logged in as: {bot.user} (ID: {bot.user.id})")
    print(" Status: Online & Ready for Operations")
    print("-----------------------------------------")

async def main():
    async with bot:
        # Load all modules dynamically before starting bot connection
        await load_functions()
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())