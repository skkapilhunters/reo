import re
import discord
from discord.ext import commands
from data.embeds.bases import build_th_response

class BasesFunction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # Matches commands like !th5, !th11, !th15 etc.
        match = re.match(r"^!th(\d+)$", message.content.strip().lower())
        if match:
            th_level = int(match.group(1))
            embeds, view = build_th_response(th_level)
            
            if not embeds:
                await message.reply(f"❌ No base data found for Town Hall {th_level} in MongoDB.", mention_author=False)
                return

            await message.channel.send(embeds=embeds, view=view)

async def setup(bot):
    await bot.add_cog(BasesFunction(bot))