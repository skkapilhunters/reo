import os
import uuid
from datetime import date, datetime
import certifi
import discord
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument

TODO_CHANNEL_ID = 1573728962973016164
DOT_EMOJI = "<a:blackdot:1574327232933924874>"

MONGO_URI = os.getenv("MONGO_URI", "").strip()
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "reo_bot").strip() or "reo_bot"

ADD_BTN_ID = "p_371914447872069634"
DONE_BTN_ID = "p_371914489152409605"
DEL_BTN_ID = "p_371914480822521860"
DETAILS_SEL_ID = "p_371913441012617217"


def _log(action: str, user: str | None = None) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    if user:
        print(f"[{ts}] Todo  | {action} by {user}")
    else:
        print(f"[{ts}] Todo  | {action}")


def _today_str() -> str:
    return date.today().isoformat()


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _days_pending(created_str: str) -> int:
    created = _parse_date(created_str)
    if not created:
        return 0
    return max(0, (date.today() - created).days)


class MongoTaskStorage:
    def __init__(self):
        if not MONGO_URI:
            raise RuntimeError("MONGO_URI is missing in environment.")

        kwargs = {}
        if MONGO_URI.startswith("mongodb+srv://") or "tls=true" in MONGO_URI.lower():
            kwargs["tlsCAFile"] = certifi.where()

        self._client = AsyncIOMotorClient(MONGO_URI, **kwargs)
        db = self._client[MONGO_DB_NAME]
        self._tasks_col = db["todo_tasks"]
        self._meta_col = db["todo_dashboard_meta"]

    async def get_meta(self) -> dict:
        doc = await self._meta_col.find_one({"_id": "main"}) or {}
        return {
            "channel_id": doc.get("channel_id"),
            "message_id": doc.get("message_id"),
        }

    async def set_meta(self, channel_id: int | None, message_id: int | None) -> None:
        await self._meta_col.update_one(
            {"_id": "main"},
            {"$set": {"channel_id": channel_id, "message_id": message_id}},
            upsert=True,
        )

    async def get_pending_tasks(self) -> list[dict]:
        cursor = self._tasks_col.find({"done": {"$ne": True}}, {"_id": 0}).sort("id", 1)
        return await cursor.to_list(length=100)

    async def get_task(self, task_id: int) -> dict | None:
        return await self._tasks_col.find_one({"id": task_id}, {"_id": 0})

    async def add_task(
        self,
        title: str,
        details: str = "",
        end_date: str | None = None,
        added_by: str = "",
    ) -> dict:
        counter = await self._meta_col.find_one_and_update(
            {"_id": "task_seq"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        next_id = int(counter["seq"])
        task = {
            "id": next_id,
            "title": title.strip(),
            "details": details.strip(),
            "done": False,
            "created_at": _today_str(),
            "end_date": end_date,
            "completed_at": None,
            "added_by": added_by,
        }
        await self._tasks_col.insert_one(dict(task))
        return task

    async def mark_tasks_done(self, task_ids: list[int]) -> list[int]:
        if not task_ids:
            return []
        id_set = list(set(task_ids))
        today = _today_str()
        cursor = self._tasks_col.find({"id": {"$in": id_set}, "done": {"$ne": True}}, {"id": 1})
        docs = await cursor.to_list(length=100)
        done_ids = [d["id"] for d in docs]
        if done_ids:
            await self._tasks_col.update_many(
                {"id": {"$in": done_ids}},
                {"$set": {"done": True, "completed_at": today}},
            )
        return done_ids

    async def delete_tasks(self, task_ids: list[int]) -> list[int]:
        if not task_ids:
            return []
        id_set = list(set(task_ids))
        cursor = self._tasks_col.find({"id": {"$in": id_set}}, {"id": 1})
        docs = await cursor.to_list(length=100)
        deleted_ids = [d["id"] for d in docs]
        if deleted_ids:
            await self._tasks_col.delete_many({"id": {"$in": deleted_ids}})
        return deleted_ids


class AddTaskModal(discord.ui.Modal, title="Add New Task"):
    task_name = discord.ui.TextInput(
        label="Task Name",
        placeholder="e.g. Donate war troops before 8 PM",
        required=True,
        max_length=100,
    )
    task_details = discord.ui.TextInput(
        label="Task Details (Optional)",
        style=discord.TextStyle.paragraph,
        placeholder="Kaam ki complete details yahan likhein...",
        required=False,
        max_length=600,
    )
    end_date = discord.ui.TextInput(
        label="End / Last Date (Optional)",
        placeholder="YYYY-MM-DD or DD-MM-YYYY (e.g. 2026-11-30)",
        required=False,
        max_length=20,
    )

    def __init__(self, cog: "TodoDashboardCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        raw_date = self.end_date.value.strip()
        parsed_end = _parse_date(raw_date)
        if raw_date and not parsed_end:
            await interaction.response.send_message(
                "End date format galat hai. `YYYY-MM-DD` ya `DD-MM-YYYY` mein likhein (jaise `2026-11-30`).",
                ephemeral=True,
            )
            return

        async def _action():
            task = await self.cog.storage.add_task(
                title=self.task_name.value,
                details=self.task_details.value,
                end_date=parsed_end.isoformat() if parsed_end else None,
                added_by=str(interaction.user),
            )
            _log("Add Task", interaction.user.name)
            await interaction.response.send_message(
                f"Task **#{task['id']} — {task['title']}** add ho gaya!",
                ephemeral=True,
            )
            await self.cog.sync_dashboard_message()

        await self.cog.run_with_status(
            _action,
            prefix="todo_add",
            task_name="Adding Todo Task",
            category="todo",
            weight=1,
        )


class MultiTaskActionSelect(discord.ui.Select):
    def __init__(self, cog: "TodoDashboardCog", tasks: list[dict], mode: str):
        self.cog = cog
        self.mode = mode  # "done" or "delete"

        options = [
            discord.SelectOption(
                label=f"#{t['id']} {t['title']}"[:100],
                value=str(t["id"]),
                description=f"Added: {t['created_at']} | Pending: {_days_pending(t['created_at'])}d"[:100],
            )
            for t in tasks[:25]
        ]

        placeholder = (
            "Done tasks chunein (list se hat jayenge, DB mein safe rahenge)..."
            if mode == "done"
            else "Delete karne ke liye tasks chunein..."
        )
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        ids = [int(v) for v in self.values]
        is_done = self.mode == "done"

        async def _action():
            if is_done:
                done_ids = await self.cog.storage.mark_tasks_done(ids)
                if done_ids:
                    _log("Done Task", interaction.user.name)
                msg = (
                    "Done mark hue tasks: " + ", ".join(f"#{i}" for i in done_ids)
                    if done_ids
                    else "Koi task update nahi hua."
                )
            else:
                del_ids = await self.cog.storage.delete_tasks(ids)
                if del_ids:
                    _log("Deleted Task", interaction.user.name)
                msg = (
                    "Delete hue tasks: " + ", ".join(f"#{i}" for i in del_ids)
                    if del_ids
                    else "Koi task delete nahi hua."
                )

            await interaction.response.send_message(msg, ephemeral=True)
            await self.cog.sync_dashboard_message()

        await self.cog.run_with_status(
            _action,
            prefix="todo_done" if is_done else "todo_delete",
            task_name="Completing Todo Tasks" if is_done else "Deleting Todo Tasks",
            category="todo",
            weight=1,
        )


class MultiTaskActionView(discord.ui.View):
    def __init__(self, cog: "TodoDashboardCog", tasks: list[dict], mode: str):
        super().__init__(timeout=120)
        self.add_item(MultiTaskActionSelect(cog=cog, tasks=tasks, mode=mode))


class TodoDashboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.storage = MongoTaskStorage()

    async def run_with_status(
        self,
        coro_factory,
        prefix: str = "todo",
        task_name: str = "Todo Action",
        category: str = "todo",
        weight: int = 1,
    ):
        status_cog = self.bot.get_cog("StatusManager")
        if not status_cog:
            return await coro_factory()

        unique_task_id = f"{prefix}_{uuid.uuid4().hex[:8]}"
        await status_cog.add_task(
            task_id=unique_task_id,
            task_name=task_name,
            category=category,
            weight=weight,
        )
        try:
            return await coro_factory()
        finally:
            await status_cog.remove_task(task_id=unique_task_id)

    async def add_task_for_ai(
        self,
        title: str,
        details: str = "",
        end_date: str | None = None,
        actor: str = "AI",
    ) -> dict:
        """Callable helper for future AI tool-calling to add a task & refresh dashboard."""
        clean_title = (title or "").strip()
        if not clean_title:
            return {"ok": False, "error": "Task title cannot be empty."}

        parsed_end = _parse_date(end_date)
        if end_date and not parsed_end:
            return {"ok": False, "error": "Invalid end_date format. Use YYYY-MM-DD."}

        async def _action():
            task = await self.storage.add_task(
                title=clean_title,
                details=details or "",
                end_date=parsed_end.isoformat() if parsed_end else None,
                added_by=actor,
            )
            _log("Add Task", actor)
            await self.sync_dashboard_message()
            return {
                "ok": True,
                "task_id": task["id"],
                "title": task["title"],
                "created_at": task["created_at"],
                "end_date": task["end_date"],
            }

        return await self.run_with_status(
            _action,
            prefix="todo_add",
            task_name="Adding Todo Task",
            category="todo",
            weight=1,
        )

    def _build_v2_payload(self, tasks: list[dict]) -> dict:
        if tasks:
            lines = [f"{DOT_EMOJI} **{t['title']}**" for t in tasks]
            tasks_block_content = "\n" + "\n\n".join(lines) + "\n"
        else:
            tasks_block_content = "\nNo pending tasks right now.\n"

        select_options = [
            {
                "label": f"#{t['id']} {t['title']}"[:100],
                "value": str(t["id"]),
            }
            for t in tasks[:25]
        ]
        if not select_options:
            select_options = [
                {
                    "label": "No pending tasks",
                    "value": "none",
                }
            ]

        return {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "components": [
                        {
                            "type": 10,
                            "content": "# Generated Task List\n",
                        },
                        {
                            "type": 10,
                            "content": tasks_block_content[:4000],
                        },
                        {
                            "type": 14,
                            "spacing": 2,
                        },
                        {
                            "type": 1,
                            "components": [
                                {
                                    "style": 2,
                                    "type": 2,
                                    "custom_id": ADD_BTN_ID,
                                    "label": "Add Task",
                                },
                                {
                                    "style": 2,
                                    "type": 2,
                                    "custom_id": DONE_BTN_ID,
                                    "label": "Done task",
                                },
                                {
                                    "style": 2,
                                    "type": 2,
                                    "custom_id": DEL_BTN_ID,
                                    "label": "Delete Task",
                                },
                            ],
                        },
                        {
                            "type": 10,
                            "content": "-# Powered by Reo",
                        },
                    ],
                },
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 3,
                            "options": select_options,
                            "custom_id": DETAILS_SEL_ID,
                            "min_values": 1,
                            "max_values": 1,
                            "placeholder": "View Task Complete Details",
                        }
                    ],
                },
            ],
        }

    async def _resolve_channel(
        self, fallback_channel: discord.TextChannel | None = None
    ) -> discord.TextChannel | None:
        meta = await self.storage.get_meta()
        target_id = TODO_CHANNEL_ID or meta.get("channel_id")
        if target_id:
            ch = self.bot.get_channel(int(target_id))
            if ch is None:
                try:
                    ch = await self.bot.fetch_channel(int(target_id))
                except discord.HTTPException:
                    ch = None
            if isinstance(ch, discord.TextChannel):
                return ch
        return fallback_channel

    async def _send_or_edit_v2(
        self, channel: discord.TextChannel, message_id: int | None, tasks: list[dict]
    ) -> int:
        payload = self._build_v2_payload(tasks)

        if message_id:
            try:
                route_edit = discord.http.Route(
                    "PATCH",
                    "/channels/{channel_id}/messages/{message_id}",
                    channel_id=channel.id,
                    message_id=message_id,
                )
                data = await self.bot.http.request(route_edit, json=payload)
                return int(data["id"])
            except discord.HTTPException:
                pass

        route_create = discord.http.Route(
            "POST", "/channels/{channel_id}/messages", channel_id=channel.id
        )
        data = await self.bot.http.request(route_create, json=payload)
        return int(data["id"])

    async def sync_dashboard_message(
        self,
        fallback_channel: discord.TextChannel | None = None,
        force_new: bool = False,
    ) -> discord.TextChannel | None:
        channel = await self._resolve_channel(fallback_channel)
        if channel is None:
            return None

        tasks = await self.storage.get_pending_tasks()
        meta = await self.storage.get_meta()
        msg_id = None if force_new else meta.get("message_id")
        new_msg_id = await self._send_or_edit_v2(channel, msg_id, tasks)
        await self.storage.set_meta(channel.id, new_msg_id)
        return channel

    @commands.command(name="posttodo")
    async def post_todo_command(self, ctx: commands.Context):
        fallback = ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
        channel = await self.sync_dashboard_message(fallback_channel=fallback, force_new=True)
        if channel:
            _log("Post Todo", ctx.author.name)
            await ctx.send(f"Todo dashboard {channel.mention} mein post ho gaya.", delete_after=5)
        else:
            await ctx.send("Text channel nahi mila.")

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await self.sync_dashboard_message()
        except Exception as e:
            _log(f"Sync Error: {e}")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = (interaction.data or {}).get("custom_id")
        if custom_id not in {ADD_BTN_ID, DONE_BTN_ID, DEL_BTN_ID, DETAILS_SEL_ID}:
            return

        if custom_id == ADD_BTN_ID:
            await interaction.response.send_modal(AddTaskModal(self))
            return

        if custom_id == DONE_BTN_ID:
            pending = await self.storage.get_pending_tasks()
            if not pending:
                await interaction.response.send_message(
                    "Mark karne ke liye koi pending task nahi hai.", ephemeral=True
                )
                return
            await interaction.response.send_message(
                "Jin tasks ko **Done** mark karna hai unhe chunein:",
                view=MultiTaskActionView(self, pending, mode="done"),
                ephemeral=True,
            )
            return

        if custom_id == DEL_BTN_ID:
            pending = await self.storage.get_pending_tasks()
            if not pending:
                await interaction.response.send_message(
                    "Delete karne ke liye koi pending task nahi hai.", ephemeral=True
                )
                return
            await interaction.response.send_message(
                "Jin tasks ko **Delete** karna hai unhe chunein:",
                view=MultiTaskActionView(self, pending, mode="delete"),
                ephemeral=True,
            )
            return

        if custom_id == DETAILS_SEL_ID:
            values = (interaction.data or {}).get("values") or []
            if not values or values[0] == "none":
                await interaction.response.send_message(
                    "Abhi koi pending task list mein nahi hai.", ephemeral=True
                )
                return

            task = await self.storage.get_task(int(values[0]))
            if not task:
                await interaction.response.send_message(
                    "Task nahi mila.", ephemeral=True
                )
                return

            days_pending = _days_pending(task["created_at"])
            status_val = (
                f"Completed ({task['completed_at']})"
                if task.get("done")
                else f"Pending ({days_pending} din se)"
            )
            details_val = task.get("details") or "Koi extra detail add nahi ki gayi."
            end_val = task.get("end_date") or "Koi end/last date set nahi hai."

            embed = discord.Embed(
                title=f"Task #{task['id']}: {task['title']}",
                description=details_val,
                color=discord.Color.green() if task.get("done") else discord.Color.dark_theme(),
            )
            embed.add_field(name="Status", value=status_val, inline=True)
            embed.add_field(name="Added On", value=task["created_at"], inline=True)
            embed.add_field(name="End / Last Date", value=end_val, inline=True)
            if task.get("added_by"):
                embed.set_footer(text=f"Added by {task['added_by']}")

            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TodoDashboardCog(bot))