import os
import discord
from discord.ext import commands

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


class ImageFetcher(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        raw_channel_id = os.getenv("MEDIA_CHANNEL_ID", "").strip()
        self.media_channel_id = int(raw_channel_id) if raw_channel_id.isdigit() else None

    def _is_image_attachment(self, attachment: discord.Attachment) -> bool:
        if attachment.content_type and attachment.content_type.startswith("image/"):
            return True
        return attachment.filename.lower().endswith(IMAGE_EXTENSIONS)

    async def _get_target_channel(self, guild: discord.Guild) -> discord.TextChannel | discord.Thread | None:
        if not self.media_channel_id:
            return None

        channel = self.bot.get_channel(self.media_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self.media_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None

        if isinstance(channel, (discord.TextChannel, discord.Thread)) and channel.guild.id == guild.id:
            return channel
        return None

    def _build_layout(
        self,
        message: discord.Message,
        media_items: list[discord.MediaGalleryItem],
        image_url: str,
    ) -> discord.ui.LayoutView:
        created_ts = int(message.created_at.timestamp())
        caption_line = f"\n**📝 Caption**: {message.content[:500]}" if message.content else ""
        user_name = message.author.display_name

        header_text = discord.ui.TextDisplay(
            "# Stored Shared Item\n"
            "Automatic media archive from server channels."
        )

        gallery = discord.ui.MediaGallery(*media_items)

        meta_text = discord.ui.TextDisplay(
            f"\n**👤 Send By**: {user_name}\n"
            f"**🕒 Created At**: <t:{created_ts}:F>\n"
            f"**#️⃣ Channel ID**: `{message.channel.id}`"
            f"{caption_line}\n"
        )

        buttons = discord.ui.ActionRow(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="Jump to Message",
                emoji="🧩",
                url=message.jump_url,
            ),
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="Image Url",
                emoji="📜",
                url=image_url,
            ),
        )

        footer_text = discord.ui.TextDisplay("-# Powered by Reo")

        container = discord.ui.Container(
            header_text,
            discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            gallery,
            discord.ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small),
            meta_text,
            discord.ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small),
            buttons,
            footer_text,
            spoiler=False,
        )

        view = discord.ui.LayoutView(timeout=None)
        view.add_item(container)
        return view

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        target_channel = await self._get_target_channel(message.guild)
        if target_channel is None or message.channel.id == target_channel.id:
            return

        image_attachments = [att for att in message.attachments if self._is_image_attachment(att)]
        if not image_attachments:
            return

        image_attachments = image_attachments[:10]

        files: list[discord.File] = []
        media_items: list[discord.MediaGalleryItem] = []

        for idx, att in enumerate(image_attachments):
            ext = os.path.splitext(att.filename)[1].lower() or ".png"
            safe_name = f"media_{idx}{ext}"
            try:
                file_obj = await att.to_file(filename=safe_name, spoiler=att.is_spoiler())
                files.append(file_obj)
                media_items.append(
                    discord.MediaGalleryItem(
                        media=f"attachment://{safe_name}",
                        spoiler=att.is_spoiler(),
                    )
                )
            except (discord.HTTPException, discord.Forbidden):
                continue

        if not files or not media_items:
            return

        first_url = image_attachments[0].url
        view = self._build_layout(message, media_items, first_url)

        try:
            await target_channel.send(view=view, files=files)
        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"[!] ImageFetcher send error: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(ImageFetcher(bot))