import os
import discord
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

# Initialize MongoDB Client
client = MongoClient(MONGO_URI)
db = client["clash_bot"] # Change to your database name if different
collection = db["bases"]

def get_base_data(th_level: int):
    """Fetches base data for a specific Town Hall level from MongoDB."""
    return collection.find_one({"th": th_level})

def build_th_response(th_level: int):
    """Builds the 3 embeds and view components from MongoDB data."""
    data = get_base_data(th_level)
    if not data:
        return None, None

    GREEN_COLOR = 65280

    # 1. Create the 3 embeds
    embed_fwa = discord.Embed(title="FWA Base", color=GREEN_COLOR)
    if data.get("fwa_image"):
        embed_fwa.set_image(url=data["fwa_image"])

    embed_war = discord.Embed(title="War Base", color=GREEN_COLOR)
    if data.get("war_image"):
        embed_war.set_image(url=data["war_image"])

    embed_rushing = discord.Embed(title="Rushing", color=GREEN_COLOR)
    if data.get("rushing_image"):
        embed_rushing.set_image(url=data["rushing_image"])

    embeds = [embed_fwa, embed_war, embed_rushing]

    # 2. Create the View with Link Buttons
    view = discord.ui.View()
    
    if data.get("fwa_link"):
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label="FWA Base", url=data["fwa_link"]))
    if data.get("war_link"):
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label="War Base", url=data["war_link"]))
    if data.get("rushing_link"):
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label="Rushing", url=data["rushing_link"]))

    return embeds, view