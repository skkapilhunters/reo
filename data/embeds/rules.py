import discord
from discord.ext import commands


RULES_TEXT = (
    "A-S-R Rules\n\n"
    "<a:blackdot:1561985458173378591> Be active daily and participate in wars and CWL.\n\n"
    "<a:blackdot:1561985458173378591> Always use both war attacks — missing attacks may lead to demotion.\n\n"
    "<a:blackdot:1561985458173378591> Donate correct troops only as requested.\n\n"
    "<a:blackdot:1561985458173378591> Respect all members — teamwork builds victory.\n\n"
    "<a:blackdot:1561985458173378591> No rushed bases allowed in main clan — use feeder clans if needed.\n\n"
    "<a:blackdot:1561985458173378591> Maintain a healthy competitive spirit, no toxicity."
)


class RulesLayoutView(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        container = discord.ui.Container(
            discord.ui.TextDisplay(RULES_TEXT)
        )
        self.add_item(container)


class RulesFunction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="rules")
    async def rules_command(self, ctx: commands.Context):
        # 32768 = IS_COMPONENTS_V2 flag
        await ctx.send(view=RulesLayoutView(), flags=discord.MessageFlags(value=32768))


async def setup(bot):
    await bot.add_cog(RulesFunction(bot))