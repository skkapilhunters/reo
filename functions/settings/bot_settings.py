import os
import pathlib
import aiohttp
import discord
from discord.ext import commands
from discord import Interaction, TextStyle
from discord.ui import (
    ActionRow,
    Button,
    Container,
    LayoutView,
    Modal,
    Section,
    Select,
    Separator,
    TextDisplay,
    TextInput,
    Thumbnail,
    UserSelect,
)

STORAGE_DIR = pathlib.Path("storage/bot_dp")


async def download_and_delete_dp(url: str, filename: str) -> bytes:
    """Downloads image into storage folder, reads bytes, and deletes the file."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    file_path = STORAGE_DIR / filename

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url.strip(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    raise ValueError(f"Image download failed with HTTP {resp.status}")
                content_type = resp.headers.get("Content-Type", "").lower()
                if content_type and not content_type.startswith("image/"):
                    raise ValueError("Provided URL is not a valid image.")
                data = await resp.read()
                if not data:
                    raise ValueError("Downloaded image file is empty.")

        file_path.write_bytes(data)
        return file_path.read_bytes()
    finally:
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass


class BotSettingsModal(Modal, title="Bot Settings"):
    def __init__(
        self,
        cog: "BotSettingsCog",
        source_message: discord.Message | None = None,
        current_nick: str = "",
        current_prefix: str = "!",
        current_activity: str = "",
    ):
        super().__init__()
        self.cog = cog
        self.source_message = source_message

        self.nickname = TextInput(
            label="Bot Server Nickname",
            placeholder="Enter server nickname",
            default=current_nick,
            required=False,
            max_length=32,
        )
        self.prefix = TextInput(
            label="Bot Prefix Change",
            placeholder="e.g. ! or . or sk!",
            default=current_prefix,
            required=False,
            max_length=10,
        )
        self.activity_text = TextInput(
            label="Bot Custom Status / Activity",
            placeholder="e.g. Playing with tasks",
            default=current_activity,
            required=False,
            max_length=128,
        )
        self.dp_url = TextInput(
            label="Bot DP URL (Server-specific)",
            placeholder="Direct PNG/JPG/WEBP image URL",
            required=False,
            style=TextStyle.paragraph,
        )

        self.add_item(self.nickname)
        self.add_item(self.prefix)
        self.add_item(self.activity_text)
        self.add_item(self.dp_url)

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        updates = []
        errors = []

        guild = interaction.guild
        me = guild.me if guild else None

        # 1. Server Nickname
        nick_val = self.nickname.value.strip()
        if me and nick_val != (me.nick or ""):
            try:
                await me.edit(nick=nick_val if nick_val else None)
                updates.append(f"Nickname -> `{nick_val if nick_val else 'Default'}`")
            except Exception as e:
                errors.append(f"Nickname error: {e}")

        # 2. Bot Prefix
        prefix_val = self.prefix.value.strip()
        if prefix_val:
            scope_id = str(guild.id) if guild else "global"
            self.cog.prefixes[scope_id] = prefix_val
            updates.append(f"Prefix -> `{prefix_val}`")

        # 3. Custom Status / Activity
        act_val = self.activity_text.value.strip()
        current_act = me.activity.name if (me and me.activity) else ""
        if act_val != current_act:
            try:
                current_status = me.status if me else discord.Status.online
                new_activity = discord.Game(name=act_val) if act_val else None
                await self.cog.bot.change_presence(
                    status=current_status,
                    activity=new_activity,
                )
                updates.append(f"Activity -> `{act_val if act_val else 'Cleared'}`")
            except Exception as e:
                errors.append(f"Activity error: {e}")

        # 4. Server-specific Bot DP
        dp_val = self.dp_url.value.strip()
        if dp_val:
            if not me:
                errors.append("Server-specific DP can only be set inside a server.")
            else:
                temp_name = f"{guild.id}_{interaction.id}.png"
                try:
                    img_bytes = await download_and_delete_dp(dp_val, temp_name)
                    await me.edit(avatar=img_bytes)
                    updates.append("Server DP updated & temp file cleaned up")
                except Exception as e:
                    errors.append(f"DP error: {e}")

        # Refresh panel message live
        target_msg = self.source_message or interaction.message
        if target_msg and updates:
            try:
                refreshed_view = BotControlLayoutView(
                    self.cog,
                    self.cog.build_invite_url(),
                    guild=guild,
                )
                await target_msg.edit(view=refreshed_view)
            except Exception as e:
                errors.append(f"Panel refresh warning: {e}")

        msg_lines = []
        if updates:
            msg_lines.append("**Updated:**\n" + "\n".join(f"- {u}" for u in updates))
        if errors:
            msg_lines.append("**Issues:**\n" + "\n".join(f"- {err}" for err in errors))
        if not msg_lines:
            msg_lines.append("No changes were made.")

        await interaction.followup.send("\n\n".join(msg_lines), ephemeral=True)


class BotControlLayoutView(LayoutView):
    def __init__(self, cog: "BotSettingsCog", invite_url: str, guild: discord.Guild | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        bot_user = cog.bot.user
        base_bot_name = bot_user.name if bot_user else "Bot"
        display_bot_name = (guild.me.display_name if guild and guild.me else None) or base_bot_name
        bot_id = bot_user.id if bot_user else 965295354805383228

        # Active DP (Server avatar if set, else bot display avatar)
        if guild and guild.me and guild.me.guild_avatar:
            bot_dp_url = guild.me.guild_avatar.url
        elif bot_user and bot_user.display_avatar:
            bot_dp_url = bot_user.display_avatar.url
        else:
            bot_dp_url = "https://cdn.discordapp.com/embed/avatars/0.png"

        # Active Prefix & Working flag
        scope_id = str(guild.id) if guild else "global"
        current_prefix = cog.prefixes.get(scope_id, cog.prefixes.get("global", "!"))
        working_enabled = cog.working_enabled.get(scope_id, True)

        # 1st Button: Bot Settings (Modal) with original custom emoji
        btn_settings = Button(
            label="Bot Settings",
            style=discord.ButtonStyle.secondary,
            emoji=discord.PartialEmoji(name="commentary", id=1510893583530463373),
            custom_id="bot_settings_open_modal",
        )
        btn_settings.callback = self.open_settings_modal

        # 2nd Button: Invite Bot (Link Button) with original custom emoji
        btn_invite_link = Button(
            label="Invite Bot",
            style=discord.ButtonStyle.link,
            url=invite_url,
            emoji=discord.PartialEmoji(name="commentary", id=1510893583530463373),
        )

        # 3rd Button: Bot Codes (Sends token privately) with original custom emoji
        btn_codes = Button(
            label="Bot Codes",
            style=discord.ButtonStyle.secondary,
            emoji=discord.PartialEmoji(name="commentary", id=1510893583530463373),
            custom_id="bot_codes_send_token",
        )
        btn_codes.callback = self.send_bot_codes

        # 5th Component: Presence status (type 5 UserSelect)
        presence_select = UserSelect(
            placeholder="Presence status",
            min_values=1,
            max_values=1,
            custom_id="bot_presence_status_untouched",
        )
        presence_select.callback = self.presence_untouched

        # 6th Component: Online status (type 3 StringSelect)
        online_select = Select(
            placeholder="Online status",
            min_values=1,
            max_values=1,
            custom_id="bot_online_status_select",
            options=[
                discord.SelectOption(label="Online", value="online", emoji="🟢"),
                discord.SelectOption(label="Idle", value="idle", emoji="🌙"),
                discord.SelectOption(label="Do Not Disturb", value="dnd", emoji="🔴"),
                discord.SelectOption(label="Offline", value="invisible", emoji="⚫"),
            ],
        )
        online_select.callback = self.change_online_status

        container = Container(
            TextDisplay(f"## <:commentary:1510893583530463373> {base_bot_name} Settings"),
            Separator(),
            Section(
                TextDisplay(
                    f"**Current Bot Name:** `{display_bot_name}`\n"
                    f"**Current Prefix:** `{current_prefix}`\n"
                    f"**Working:** `{working_enabled}`"
                ),
                accessory=Thumbnail(
                    media=bot_dp_url,
                    description=f"{display_bot_name} avatar",
                    spoiler=False,
                ),
            ),
            Separator(),
            TextDisplay(
                "**Presence status :** Working\n"
                f"-# <:personalcard:1510894288353890345> Bot ID: `{bot_id}`\n"
                f"-# ⚙️ Bot Prefix: `{current_prefix}`\n"
                "-# <:aitagprice:1510894796104007690> Bot Permission : Admin\n"
                "-# <:messagetime:1510896797315235991> Joined <t:1786864765:f>"
            ),
            Separator(),
            ActionRow(btn_settings, btn_invite_link, btn_codes),
        )

        self.add_item(container)
        self.add_item(ActionRow(presence_select))
        self.add_item(ActionRow(online_select))

    async def open_settings_modal(self, interaction: Interaction):
        guild = interaction.guild
        me = guild.me if guild else None

        current_nick = me.nick if me and me.nick else ""
        scope_id = str(guild.id) if guild else "global"
        current_prefix = self.cog.prefixes.get(scope_id, self.cog.prefixes.get("global", "!"))
        current_activity = me.activity.name if (me and me.activity) else ""

        modal = BotSettingsModal(
            cog=self.cog,
            source_message=interaction.message,
            current_nick=current_nick,
            current_prefix=current_prefix,
            current_activity=current_activity,
        )
        await interaction.response.send_modal(modal)

    async def send_bot_codes(self, interaction: Interaction):
        token = os.getenv("DISCORD_BOT_TOKEN") or self.cog.bot.http.token
        if not token:
            await interaction.response.send_message("Token not found in environment.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"**Bot Token:**\n`{token}`",
            ephemeral=True,
        )

    async def presence_untouched(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

    async def change_online_status(self, interaction: Interaction):
        choice = interaction.data["values"][0]
        status_map = {
            "online": discord.Status.online,
            "idle": discord.Status.idle,
            "dnd": discord.Status.dnd,
            "invisible": discord.Status.invisible,
        }
        target_status = status_map[choice]
        current_activity = (
            interaction.guild.me.activity
            if interaction.guild and interaction.guild.me
            else None
        )
        await self.cog.bot.change_presence(status=target_status, activity=current_activity)
        label_map = {
            "online": "Online",
            "idle": "Idle",
            "dnd": "DND",
            "invisible": "Offline",
        }
        await interaction.response.send_message(
            f"Bot status set to **{label_map[choice]}**.",
            ephemeral=True,
        )


class BotSettingsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.prefixes: dict[str, str] = {}
        self.working_enabled: dict[str, bool] = {}
        self._views_registered = False

    def get_prefix_for_message(self, message: discord.Message) -> str:
        if message.guild:
            return self.prefixes.get(str(message.guild.id), self.prefixes.get("global", "!"))
        return self.prefixes.get("global", "!")

    def build_invite_url(self) -> str:
        app_id = self.bot.user.id if self.bot.user else 965295354805383228
        return discord.utils.oauth_url(
            app_id,
            permissions=discord.Permissions(administrator=True),
            scopes=("bot", "applications.commands"),
        )

    @commands.Cog.listener()
    async def on_ready(self):
        if not self._views_registered:
            view = BotControlLayoutView(self, self.build_invite_url())
            self.bot.add_view(view)
            self._views_registered = True

    @commands.command(name="botpanel")
    async def open_bot_panel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        target = channel or discord.utils.get(ctx.guild.text_channels, name="bot-settings") or ctx.channel
        try:
            view = BotControlLayoutView(self, self.build_invite_url(), guild=ctx.guild)
            await target.send(view=view)
            if target != ctx.channel:
                await ctx.send(f"Bot settings panel sent to {target.mention}.", delete_after=5)
        except Exception as e:
            await ctx.send(f"Error: `{e}`")


async def setup(bot: commands.Bot):
    cog = BotSettingsCog(bot)
    await bot.add_cog(cog)