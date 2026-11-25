import os
import io
import time
import discord
from discord.ext import commands
import chat_exporter
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
client = MongoClient(os.getenv("MONGO_URI"))
db = client["clash_bot"] # Adjust database name if needed

class TranscriptFunction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="transcript", aliases=["close"])
    async def create_transcript(self, ctx):
        """Generates channel HTML transcript, creates a thread in closed_transcripts, and logs to admin."""
        channel = ctx.channel
        guild = ctx.guild

        # 1. Fetch guild settings from MongoDB
        guild_data = db["guilds"].find_one({"guildId": str(guild.id)})
        if not guild_data or not guild_data.get("channels", {}).get("closed_transcripts"):
            await ctx.send("❌ `closed_transcripts` channel ID is not configured in MongoDB for this guild.")
            return

        closed_transcripts_channel_id = int(guild_data["channels"]["closed_transcripts"])
        target_channel = guild.get_channel(closed_transcripts_channel_id)

        if not target_channel:
            await ctx.send("❌ Could not find the configured `closed_transcripts` channel in this server.")
            return

        # 2. Export chat transcript
        transcript_html = await chat_exporter.export(channel)
        if not transcript_html:
            await ctx.send("❌ Failed to generate channel transcript.")
            return

        # 3. Create a thread under the closed_transcripts channel
        thread = await target_channel.create_thread(
            name=f"ticket-{channel.name}",
            type=discord.ChannelType.public_thread
        )

        # Send full chat dump/HTML file into the thread for permanent archive
        transcript_file = discord.File(
            io.BytesIO(transcript_html.encode("utf-8")),
            filename=f"transcript-{channel.name}.html"
        )
        await thread.send(
            content=f"📁 **Archive Log for Ticket #{channel.name}** (Channel ID: `{channel.id}`)",
            file=transcript_file
        )

        # 4. Prepare Embed and UI components for admin notification
        created_at_ts = int(channel.created_at.timestamp())
        closed_at_ts = int(time.time())

        # Fix raw custom emoji display issues in Discord embeds by mapping or using standard text
        embed_content = (
            f"## Ticket #{channel.name} Closed\n"
            f"**🆔 ID**: `1`\n"
            f"**🛡️ Guild**: {guild.name}\n"
            f"**👤 Creator**: {ctx.author.mention}\n"
            f"**🔒 Closed By**: {ctx.author.mention}\n"
            f"**🕒 Created At**: <t:{created_at_ts}:F>\n"
            f"**🔒 Closed At**: <t:{closed_at_ts}:F>\n"
            f"**📝 Topic**: Closed by {ctx.author.mention}\n"
            f"**#️⃣ Channel ID**: `{channel.id}`\n"
            f"-# Powered by Reo"
        )

        # Button linking directly to the newly created thread
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="View Thread",
                emoji="📜",
                url=thread.jump_url
            )
        )

        # 5. Send notification to admin channel / command source channel
        await ctx.send(content=embed_content, view=view)

async def setup(bot):
    await bot.add_cog(TranscriptFunction(bot))