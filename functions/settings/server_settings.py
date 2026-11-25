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

STORAGE_DIR = pathlib.Path("storage/server_dp")


async def download_and_delete_icon(url: str, filename: str) -> bytes:
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


class ServerSettingsModal(Modal, title="Server Settings"):
    def __init__(
        self,
        cog: "ServerSettingsCog",
        source_message: discord.Message | None = None,
        current_name: str = "",
    ):
        super().__init__()
        self.cog = cog
        self.source_message = source_message

        self.server_name = TextInput(
            label="Server Name",
            placeholder="Enter new server name",
            default=current_name,
            required=False,
            max_length=100,
        )
        self.icon_url = TextInput(
            label="Server Icon URL (DP)",
            placeholder="Direct PNG/JPG/WEBP image URL for server icon",
            required=False,
            style=TextStyle.paragraph,
        )

        self.add_item(self.server_name)
        self.add_item(self.icon_url)

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        updates = []
        errors = []

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("This action can only be used inside a server.", ephemeral=True)
            return

        # 1. Change Server Name
        name_val = self.server_name.value.strip()
        if name_val and name_val != guild.name:
            try:
                await guild.edit(name=name_val)
                updates.append(f"Server Name -> `{name_val}`")
            except Exception as e:
                errors.append(f"Server name update error: {e}")

        # 2. Change Server Icon (DP)
        icon_val = self.icon_url.value.strip()
        if icon_val:
            temp_name = f"{guild.id}_{interaction.id}.png"
            try:
                img_bytes = await download_and_delete_icon(icon_val, temp_name)
                await guild.edit(icon=img_bytes)
                updates.append("Server Icon updated & temp file cleaned up")
            except Exception as e:
                errors.append(f"Server Icon error: {e}")

        # Refresh panel message live
        target_msg = self.source_message or interaction.message
        if target_msg and updates:
            try:
                refreshed_view = ServerControlLayoutView(self.cog, guild=guild)
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


class CreateRoleModal(Modal, title="Create New Server Role"):
    role_name = TextInput(
        label="Role Name",
        placeholder="e.g. VIP / Admin / Member",
        required=True,
        max_length=100,
    )
    role_color = TextInput(
        label="Hex Color (Optional)",
        placeholder="e.g. #3498db or #ff0000",
        required=False,
        max_length=7,
    )

    async def on_submit(self, interaction: Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Must be inside a server.", ephemeral=True)
            return

        color = discord.Color.default()
        if self.role_color.value.strip():
            try:
                clean_hex = self.role_color.value.strip().lstrip('#')
                color = discord.Color(int(clean_hex, 16))
            except ValueError:
                pass

        try:
            role = await guild.create_role(name=self.role_name.value.strip(), color=color)
            await interaction.response.send_message(f"Role `{role.name}` created successfully!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to create role: {e}", ephemeral=True)


class ServerControlLayoutView(LayoutView):
    def __init__(self, cog: "ServerSettingsCog", guild: discord.Guild | None = None):
        super().__init__(timeout=None)
        self.cog = cog

        server_name = guild.name if guild else "Server"
        server_id = guild.id if guild else 0
        member_count = guild.member_count if guild else 0
        role_count = len(guild.roles) if guild else 0
        text_channels = len(guild.text_channels) if guild else 0
        voice_channels = len(guild.voice_channels) if guild else 0

        # Active Server Icon
        if guild and guild.icon:
            server_icon_url = guild.icon.url
        else:
            server_icon_url = "https://cdn.discordapp.com/embed/avatars/0.png"

        # 1st Button: Server Settings (Modal for Name & Icon)
        btn_settings = Button(
            label="Server Settings",
            style=discord.ButtonStyle.secondary,
            emoji=discord.PartialEmoji(name="commentary", id=1510893583530463373),
            custom_id="server_settings_open_modal",
        )
        btn_settings.callback = self.open_settings_modal

        # 2nd Button: Create Role (Modal)
        btn_create_role = Button(
            label="Create Role",
            style=discord.ButtonStyle.secondary,
            emoji=discord.PartialEmoji(name="commentary", id=1510893583530463373),
            custom_id="server_create_role_modal",
        )
        btn_create_role.callback = self.open_role_modal

        # 3rd Button: Refresh Panel
        btn_refresh = Button(
            label="Refresh",
            style=discord.ButtonStyle.secondary,
            emoji=discord.PartialEmoji(name="commentary", id=1510893583530463373),
            custom_id="server_refresh_panel",
        )
        btn_refresh.callback = self.refresh_panel

        # Dropdowns (Same component layout)
        user_select = UserSelect(
            placeholder="Select Member",
            min_values=1,
            max_values=1,
            custom_id="server_user_select_placeholder",
        )
        user_select.callback = self.user_select_callback

        channel_select = Select(
            placeholder="Server Actions",
            min_values=1,
            max_values=1,
            custom_id="server_action_select",
            options=[
                discord.SelectOption(label="Server Info", value="info", emoji="📊"),
                discord.SelectOption(label="Lockdown Channel", value="lock", emoji="🔒"),
                discord.SelectOption(label="Unlock Channel", value="unlock", emoji="🔓"),
            ],
        )
        channel_select.callback = self.channel_select_callback

        container = Container(
            TextDisplay(f"## <:commentary:1510893583530463373> {server_name} Settings"),
            Separator(),
            Section(
                TextDisplay(
                    f"**Server Name:** `{server_name}`\n"
                    f"**Total Members:** `{member_count}`\n"
                    f"**Total Roles:** `{role_count}`"
                ),
                accessory=Thumbnail(
                    media=server_icon_url,
                    description=f"{server_name} Icon",
                    spoiler=False,
                ),
            ),
            Separator(),
            TextDisplay(
                "**Server Overview :**\n"
                f"-# <:personalcard:1510894288353890345> Server ID: `{server_id}`\n"
                f"-# 💬 Text Channels: `{text_channels}` | 🔊 Voice: `{voice_channels}`\n"
                "-# <:aitagprice:1510894796104007690> Access Level : Owner Only\n"
                "-# <:messagetime:1510896797315235991> Control Panel Active"
            ),
            Separator(),
            ActionRow(btn_settings, btn_create_role, btn_refresh),
        )

        self.add_item(container)
        self.add_item(ActionRow(user_select))
        self.add_item(ActionRow(channel_select))

    async def open_settings_modal(self, interaction: Interaction):
        guild = interaction.guild
        current_name = guild.name if guild else ""

        modal = ServerSettingsModal(
            cog=self.cog,
            source_message=interaction.message,
            current_name=current_name,
        )
        await interaction.response.send_modal(modal)

    async def open_role_modal(self, interaction: Interaction):
        await interaction.response.send_modal(CreateRoleModal())

    async def refresh_panel(self, interaction: Interaction):
        refreshed_view = ServerControlLayoutView(self.cog, guild=interaction.guild)
        await interaction.response.edit_message(view=refreshed_view)

    async def user_select_callback(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

    async def channel_select_callback(self, interaction: Interaction):
        choice = interaction.data["values"][0]
        if choice == "info":
            guild = interaction.guild
            await interaction.response.send_message(
                f"**Server Info:**\n- Name: {guild.name}\n- Owner: {guild.owner}\n- Created: <t:{int(guild.created_at.timestamp())}:R>",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(f"Action `{choice}` executed.", ephemeral=True)


class ServerSettingsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._views_registered = False

    @commands.Cog.listener()
    async def on_ready(self):
        if not self._views_registered:
            view = ServerControlLayoutView(self)
            self.bot.add_view(view)
            self._views_registered = True

    @commands.command(name="serverpanel")
    async def open_server_panel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        target = channel or discord.utils.get(ctx.guild.text_channels, name="server-settings") or ctx.channel
        try:
            view = ServerControlLayoutView(self, guild=ctx.guild)
            await target.send(view=view)
            if target != ctx.channel:
                await ctx.send(f"Server settings panel sent to {target.mention}.", delete_after=5)
        except Exception as e:
            await ctx.send(f"Error: `{e}`")


async def setup(bot: commands.Bot):
    cog = ServerSettingsCog(bot)
    await bot.add_cog(cog)