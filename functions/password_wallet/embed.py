import os
import time
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from functions.password_wallet.get_back import (
    get_password_entries,
    get_recovery_entries,
    get_totp_entries,
)
from functions.password_wallet.register import (
    save_password_entry,
    save_recovery_entry,
    save_totp_entry,
)

OWNER_ID_RAW = os.getenv("DISCORD_OWNER_ID", "0")
OWNER_ID = int(OWNER_ID_RAW) if OWNER_ID_RAW.isdigit() else 0

WELCOME_GIF_URL = (
    "https://cdn.discordapp.com/attachments/1503014110156030023/"
    "1503179655799115796/welcome_20.gif?ex=6b0182e5&is=6b003165"
    "&hm=5effae22a9e5201a1e050771bf49d5da5d220f1594925788614888eec85fd866&"
)


def is_authorized_user(interaction_or_ctx) -> tuple[bool, str]:
    user = getattr(interaction_or_ctx, "user", None) or getattr(interaction_or_ctx, "author", None)
    if OWNER_ID and (user is None or user.id != OWNER_ID):
        return False, "This wallet is private and restricted to its owner."
    return True, ""


def build_welcome_embed() -> discord.Embed:
    description = (
        "**Welcome to Clash Wallet!** 👋\n\n"
        "We’re thrilled to have you as part of our community! To help you get settled "
        "and find your way around, please take a look at the following channels:\n\n"
        "> 〢  ** Press Start Verification and Proceed  **\n"
        ">  〢 ** Press Start Verification and Proceed  **\n\n"
        "> If you have any questions or need assistance, feel free to reach out to "
        "our team at any time. \n"
        "> **Have fun and enjoy your stay!** 🚀"
    )
    embed = discord.Embed(description=description, color=10181046)
    embed.set_image(url=WELCOME_GIF_URL)
    return embed


async def send_v2_followup(interaction: discord.Interaction, payload: dict, ephemeral: bool = True):
    """Sends a Components V2 payload cleanly via Discord REST API without payload validation issues."""
    body = dict(payload)
    body["flags"] = 32768 | (64 if ephemeral else 0)

    url = f"https://discord.com/api/v10/webhooks/{interaction.application_id}/{interaction.token}"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body) as resp:
            if resp.status not in (200, 201, 204):
                err_text = await resp.text()
                raise RuntimeError(f"Discord V2 send failed ({resp.status}): {err_text}")


# --- Components V2 Payload Builder Functions ---

def build_totp_v2_payload(totp_data: dict, max_chars: int = 3400) -> dict:
    header_content = (
        "# Generated Auth Keys\n"
        "A support member will reply here. Use the controls below to manage this ticket."
    )
    footer_brand = "-# Powered by Reo"

    items = totp_data.get("items") or []
    now_sec = int(time.time())
    expires_at = totp_data.get("expires_at") or (((now_sec // 30) + 1) * 30)
    cur_expires_at = totp_data.get("current_expires_at") or (((now_sec // 30) + 1) * 30)
    is_lookahead = bool(totp_data.get("is_lookahead"))

    if is_lookahead:
        expiry_line = f"Next code active <t:{cur_expires_at}:R> • Expires <t:{expires_at}:R>"
    else:
        expiry_line = f"Expires <t:{expires_at}:R>"

    sub_components = [{"id": 2, "type": 10, "content": header_content}]

    if not items:
        sub_components.append({"type": 14})
        sub_components.append({
            "type": 10,
            "content": "```\nNo TOTP keys registered yet.\n```",
        })
    else:
        blocks = []
        for item in items:
            label_part = f" ({item['account_label']})" if item.get("account_label") else ""
            if item.get("error"):
                line = f"{item['service_name']}{label_part} | Error: {item['error']}"
            else:
                code_label = item.get("code_label") or "OTP"
                line = f"{item['service_name']}{label_part} | {code_label}: {item['otp_code']}"
            blocks.append(f"```\n{line}\n```")

        combined_lines = []
        current_len = 0
        shown_count = 0

        for blk in blocks:
            if current_len + len(blk) + 1 > max_chars:
                break
            combined_lines.append(blk)
            current_len += len(blk) + 1
            shown_count += 1

        remaining_count = len(items) - shown_count

        sub_components.append({"type": 14})
        sub_components.append({
            "type": 10,
            "content": "\n".join(combined_lines),
        })

        if remaining_count > 0:
            sub_components.append({
                "type": 10,
                "content": f"-# Showing {shown_count}/{len(items)} codes • +{remaining_count} more not shown (limit protection)",
            })

        sub_components.append({"type": 14})
        sub_components.append({"type": 10, "content": expiry_line})

    sub_components.append({"type": 10, "content": footer_brand})

    return {
        "flags": 32768,
        "components": [
            {
                "id": 1,
                "type": 17,
                "accent_color": None,
                "spoiler": False,
                "components": sub_components,
            }
        ],
    }


def build_recovery_v2_payload(rows: list[dict]) -> dict:
    sub_components = [
        {
            "id": 2,
            "type": 10,
            "content": "# Stored Recovery Keys\nA support member will reply here. Use the controls below to manage this ticket."
        }
    ]

    if not rows:
        sub_components.append({"type": 14})
        sub_components.append({
            "type": 10,
            "content": "**No Recovery Keys Found**\n```\nNo recovery keys registered yet.\n```"
        })
    else:
        for item in rows:
            sub_components.append({"type": 14})
            sub_components.append({
                "type": 10,
                "content": f"**{item['service_name']}**\n```\n{item['recovery_keys']}\n```"
            })

    sub_components.append({
        "type": 10,
        "content": "-# Powered by Reo"
    })

    return {
        "flags": 32768,
        "components": [
            {
                "id": 1,
                "type": 17,
                "accent_color": None,
                "spoiler": False,
                "components": sub_components
            }
        ]
    }


def build_password_v2_payload(rows: list[dict]) -> dict:
    sub_components = [
        {
            "id": 2,
            "type": 10,
            "content": "# Stored Password Keys\nA support member will reply here. Use the controls below to manage this ticket."
        },
        {
            "id": 3,
            "type": 14,
            "divider": True,
            "spacing": 1
        }
    ]

    if not rows:
        sub_components.append({
            "id": 4,
            "type": 10,
            "content": "**No Passwords Found**\n\n No passwords stored yet.\n\n"
        })
    else:
        for idx, item in enumerate(rows):
            if idx > 0:
                sub_components.append({"type": 14, "spacing": 2})

            user_str = item.get("username_or_email") or "N/A"
            sub_components.append({
                "type": 10,
                "content": f"**{item['service_name']}**\n\n Mail : ```{user_str}``` Password : ```{item['password']}```\n\n"
            })

    sub_components.append({
        "type": 10,
        "content": "-# Powered by Reo"
    })

    return {
        "flags": 32768,
        "components": [
            {
                "id": 1,
                "type": 17,
                "accent_color": None,
                "spoiler": False,
                "components": sub_components
            }
        ]
    }


# --- Register Modals ---

class PasswordRegisterModal(discord.ui.Modal, title="Register Password"):
    service_name = discord.ui.TextInput(
        label="Service / App Name",
        placeholder="e.g., Discord, GitHub",
        required=True,
        max_length=100,
    )
    username_or_email = discord.ui.TextInput(
        label="Username or Email (Optional)",
        placeholder="e.g., user@example.com",
        required=False,
        max_length=150,
    )
    password = discord.ui.TextInput(
        label="Password",
        placeholder="Enter password to encrypt",
        required=True,
        max_length=500,
    )
    notes = discord.ui.TextInput(
        label="Notes (Optional)",
        placeholder="e.g., Personal login",
        required=False,
        max_length=300,
    )

    async def on_submit(self, interaction: discord.Interaction):
        save_password_entry(
            user_id=interaction.user.id,
            service_name=self.service_name.value,
            password=self.password.value,
            username_or_email=self.username_or_email.value,
            notes=self.notes.value,
        )
        await interaction.response.send_message(
            f"Saved encrypted password for **{self.service_name.value}**.",
            ephemeral=True,
        )


class TotpRegisterModal(discord.ui.Modal, title="Register TOTP (2FA)"):
    service_name = discord.ui.TextInput(
        label="Service / App Name",
        placeholder="e.g., GitHub",
        required=True,
        max_length=100,
    )
    account_label = discord.ui.TextInput(
        label="Account Label (Optional)",
        placeholder="e.g., main-account",
        required=False,
        max_length=150,
    )
    totp_secret = discord.ui.TextInput(
        label="Base32 Secret Key",
        placeholder="e.g., JBSWY3DPEHPK3PXP",
        required=True,
        max_length=250,
    )
    notes = discord.ui.TextInput(
        label="Notes (Optional)",
        placeholder="Optional note",
        required=False,
        max_length=300,
    )

    async def on_submit(self, interaction: discord.Interaction):
        save_totp_entry(
            user_id=interaction.user.id,
            service_name=self.service_name.value,
            totp_secret=self.totp_secret.value,
            account_label=self.account_label.value,
            notes=self.notes.value,
        )
        await interaction.response.send_message(
            f"Saved encrypted TOTP secret for **{self.service_name.value}**.",
            ephemeral=True,
        )


class RecoveryRegisterModal(discord.ui.Modal, title="Register Recovery Keys"):
    service_name = discord.ui.TextInput(
        label="Service / Wallet Name",
        placeholder="e.g., Google, BTC Wallet",
        required=True,
        max_length=100,
    )
    recovery_keys = discord.ui.TextInput(
        label="Recovery Codes / Seed Phrase",
        style=discord.TextStyle.paragraph,
        placeholder="Paste backup codes or recovery phrase",
        required=True,
        max_length=2000,
    )
    notes = discord.ui.TextInput(
        label="Notes (Optional)",
        placeholder="Optional note",
        required=False,
        max_length=300,
    )

    async def on_submit(self, interaction: discord.Interaction):
        save_recovery_entry(
            user_id=interaction.user.id,
            service_name=self.service_name.value,
            recovery_keys=self.recovery_keys.value,
            notes=self.notes.value,
        )
        await interaction.response.send_message(
            f"Saved encrypted recovery keys for **{self.service_name.value}**.",
            ephemeral=True,
        )


# --- Dropdown Menus ---

CATEGORY_OPTIONS = [
    discord.SelectOption(label="Password", value="password", description="Account password"),
    discord.SelectOption(label="TOTP (2FA)", value="totp", description="Time-based 2FA key / code"),
    discord.SelectOption(label="Recovery Keys", value="recovery", description="Backup codes or seed phrase"),
]


class RegisterSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            custom_id="p_370905787473596424",
            placeholder="1. Register (Password / TOTP / Recovery)...",
            min_values=1,
            max_values=1,
            options=CATEGORY_OPTIONS,
        )

    async def callback(self, interaction: discord.Interaction):
        allowed, reason = is_authorized_user(interaction)
        if not allowed:
            await interaction.response.send_message(reason, ephemeral=True)
            return

        selected = self.values[0]
        if selected == "password":
            await interaction.response.send_modal(PasswordRegisterModal())
        elif selected == "totp":
            await interaction.response.send_modal(TotpRegisterModal())
        else:
            await interaction.response.send_modal(RecoveryRegisterModal())


class LookupSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            custom_id="p_370905748210716679",
            placeholder="2. Lookup (Password / TOTP / Recovery)...",
            min_values=1,
            max_values=1,
            options=CATEGORY_OPTIONS,
        )

    async def callback(self, interaction: discord.Interaction):
        allowed, reason = is_authorized_user(interaction)
        if not allowed:
            await interaction.response.send_message(reason, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        uid = interaction.user.id
        selected = self.values[0]

        try:
            if selected == "totp":
                totp_data = get_totp_entries(uid)
                payload = build_totp_v2_payload(totp_data)
            elif selected == "recovery":
                rows = get_recovery_entries(uid)
                payload = build_recovery_v2_payload(rows)
            elif selected == "password":
                rows = get_password_entries(uid)
                payload = build_password_v2_payload(rows)
            else:
                await interaction.followup.send("Invalid selection.", ephemeral=True)
                return

            await send_v2_followup(interaction, payload, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"Lookup error: `{e}`", ephemeral=True)


class WalletMainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RegisterSelect())
        self.add_item(LookupSelect())


class PasswordWalletCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="wallet", description="Open Clash Wallet")
    async def wallet_slash(self, interaction: discord.Interaction):
        allowed, reason = is_authorized_user(interaction)
        if not allowed:
            await interaction.response.send_message(reason, ephemeral=True)
            return

        await interaction.response.send_message(
            embed=build_welcome_embed(),
            view=WalletMainView(),
            ephemeral=True,
        )

    @commands.command(name="wallet")
    async def wallet_prefix(self, ctx: commands.Context):
        allowed, reason = is_authorized_user(ctx)
        if not allowed:
            await ctx.reply(reason, mention_author=False)
            return

        await ctx.send(embed=build_welcome_embed(), view=WalletMainView())


async def setup(bot: commands.Bot):
    bot.add_view(WalletMainView())
    await bot.add_cog(PasswordWalletCog(bot))