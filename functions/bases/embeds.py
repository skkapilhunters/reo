import importlib
import pathlib
import discord
from discord.ext import commands


class AutoEmbedsFunction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.registry = self._discover_embeds()

    def _discover_embeds(self) -> dict:
        """
        Scans 'data/embeds' for modules and collects builders automatically.
        Supports:
          1) Any function named `build_<topic>_payload` or `build_<topic>_embed`
          2) Optional `EMBEDS = {"topic": builder_or_payload}` dict inside any module
        """
        found = {}
        embeds_dir = pathlib.Path("data/embeds")

        if not embeds_dir.exists():
            return found

        for file_path in embeds_dir.rglob("*.py"):
            if any(part.startswith(("_", ".")) for part in file_path.parts):
                continue

            module_name = ".".join(file_path.with_suffix("").parts)
            try:
                module = importlib.import_module(module_name)
            except Exception as e:
                print(f"    [-] Failed importing embed module {module_name}: {e}")
                continue

            # 1. Dict support if a file defines EMBEDS = {...}
            if isinstance(getattr(module, "EMBEDS", None), dict):
                for key, val in module.EMBEDS.items():
                    found[str(key).lower()] = val

            # 2. Auto-detect functions like `build_rules_payload` or `build_war_embed`
            for attr_name in dir(module):
                if attr_name.startswith("_"):
                    continue
                if attr_name.startswith("build_") and (
                    attr_name.endswith("_payload") or attr_name.endswith("_embed")
                ):
                    topic = attr_name[len("build_") :]
                    if topic.endswith("_payload"):
                        topic = topic[: -len("_payload")]
                    elif topic.endswith("_embed"):
                        topic = topic[: -len("_embed")]

                    if topic:
                        found[topic.lower()] = getattr(module, attr_name)

        return found

    @commands.command(name="embed", aliases=["show"])
    async def send_embed(self, ctx: commands.Context, topic: str = None):
        if not topic:
            available = ", ".join(sorted(self.registry.keys())) or "none"
            await ctx.send(f"Available embeds: `{available}`")
            return

        key = topic.strip().lower()
        builder = self.registry.get(key)

        if not builder:
            await ctx.send(f"❌ `{topic}` ke liye koi embed nahi mila.")
            return

        data = builder() if callable(builder) else builder

        # Case A: Components v2 dict with flags & components
        if isinstance(data, dict) and "components" in data:
            await self.bot.http.send_message(
                ctx.channel.id,
                params={},
                content=data.get("content"),
                components=data["components"],
                flags=data.get("flags", 0),
            )
            return

        # Case B: Single discord.Embed or list of discord.Embeds
        if isinstance(data, discord.Embed):
            await ctx.send(embed=data)
        elif isinstance(data, (list, tuple)) and all(isinstance(x, discord.Embed) for x in data):
            await ctx.send(embeds=list(data))
        else:
            await ctx.send("⚠️ Unsupported embed format returned by builder.")


async def setup(bot):
    await bot.add_cog(AutoEmbedsFunction(bot))