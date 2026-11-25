import os
import json
import asyncio
import discord
from discord.ext import commands
from groq import Groq

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

FALLBACK_MODELS = [
    os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"),
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "allam-2-7b"
]

TODO_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_todo_task",
            "description": "Add a single task to the todo list. Call this once for each task if the user gives multiple tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short and clear task title."
                    },
                    "details": {
                        "type": "string",
                        "description": "Optional details/sub-points for the task."
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Optional date in YYYY-MM-DD, DD-MM-YYYY, or DD/MM/YYYY format."
                    },
                    "actor": {
                        "type": "string",
                        "description": "Who requested the task."
                    }
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_todo_tasks",
            "description": "Get current pending tasks and their IDs/count from the todo list.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mark_todo_done",
            "description": "Mark one or more pending tasks as completed using their numeric task IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of task IDs to mark as done."
                    }
                },
                "required": ["task_ids"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_todo_tasks",
            "description": "Delete one or more tasks permanently using their numeric task IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of task IDs to delete."
                    }
                },
                "required": ["task_ids"]
            }
        }
    }
]


class AISupport(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.private_guild_id = int(os.getenv("PRIVATE_GUILD_ID", 0))
        self.private_log_channel_id = int(os.getenv("PRIVATE_LOG_CHANNEL_ID", 0))
        self.sessions = {}
        self.thread_to_target = {}

    def _get_todo_cog(self):
        return self.bot.get_cog("TodoDashboardCog")

    async def _execute_tool_call(self, tool_call, default_actor: str, thread=None) -> str:
        fn_name = tool_call.function.name
        raw_args = tool_call.function.arguments or "{}"

        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            return json.dumps({"ok": False, "error": "Invalid JSON arguments"})

        todo_cog = self._get_todo_cog()
        if not todo_cog:
            return json.dumps({"ok": False, "error": "TodoDashboardCog is not loaded."})

        if fn_name == "add_todo_task":
            title = (args.get("title") or "").strip()
            if not title:
                return json.dumps({"ok": False, "error": "Task title is required."})

            result = await todo_cog.add_task_for_ai(
                title=title,
                details=args.get("details") or "",
                end_date=args.get("end_date"),
                actor=(args.get("actor") or default_actor or "AI").strip()
            )
            if thread:
                info = f"Added #{result.get('task_id')} `{result.get('title')}`" if result.get("ok") else f"Add failed: {result.get('error')}"
                await thread.send(f"🛠️ **Tool `add_todo_task`:** {info}")
            return json.dumps(result, default=str)

        if fn_name == "list_todo_tasks":
            tasks = await todo_cog.storage.get_pending_tasks()
            return json.dumps({"ok": True, "count": len(tasks), "tasks": tasks}, default=str)

        if fn_name == "mark_todo_done":
            ids = [int(x) for x in (args.get("task_ids") or [])]
            done_ids = await todo_cog.storage.mark_tasks_done(ids)
            if done_ids:
                await todo_cog.sync_dashboard_message()
            if thread:
                await thread.send(f"🛠️ **Tool `mark_todo_done`:** {done_ids}")
            return json.dumps({"ok": True, "marked_done": done_ids})

        if fn_name == "delete_todo_tasks":
            ids = [int(x) for x in (args.get("task_ids") or [])]
            deleted_ids = await todo_cog.storage.delete_tasks(ids)
            if deleted_ids:
                await todo_cog.sync_dashboard_message()
            if thread:
                await thread.send(f"🛠️ **Tool `delete_todo_tasks`:** {deleted_ids}")
            return json.dumps({"ok": True, "deleted": deleted_ids})

        return json.dumps({"ok": False, "error": f"Unknown tool: {fn_name}"})

    async def _get_or_create_memory_channel(self, private_guild: discord.Guild, identifier: str, display_name: str) -> discord.TextChannel:
        category_name = "🤖 AI-Memory"
        category = discord.utils.get(private_guild.categories, name=category_name)
        if not category:
            category = await private_guild.create_category(category_name)

        target_channel_name = f"mem-{identifier}"
        mem_channel = discord.utils.get(category.text_channels, name=target_channel_name)

        if not mem_channel:
            mem_channel = await private_guild.create_text_channel(
                name=target_channel_name,
                category=category,
                topic=f"Shared server memory logs for: {display_name} (ID: {identifier})"
            )
        return mem_channel

    async def _fetch_past_memory(self, mem_channel: discord.TextChannel) -> str:
        memory_snippets = []
        try:
            threads = list(mem_channel.threads)
            async for archived_thread in mem_channel.archived_threads(limit=5):
                threads.append(archived_thread)

            for th in threads[:3]:
                async for msg in th.history(limit=10, oldest_first=False):
                    if msg.content and not msg.content.startswith("🟢") and not msg.content.startswith("🔴"):
                        memory_snippets.append(f"{msg.author.name}: {msg.content}")

            memory_snippets.reverse()
            return "\n".join(memory_snippets[-15:])
        except Exception as e:
            print(f"[Memory Fetch Error]: {e}")
            return ""

    @commands.command(name="asr")
    async def asr_command(self, ctx: commands.Context):
        await self._stop_session(ctx)

    async def _stop_session(self, target):
        session_key = target.guild.id if getattr(target, "guild", None) else target.channel.id
        channel = getattr(target, "channel", target)

        if session_key in self.sessions:
            thread_id = self.sessions[session_key].get("thread_id")
            if thread_id:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    await thread.send("🔴 **Session terminated via !asr command.**")
                if thread_id in self.thread_to_target:
                    del self.thread_to_target[thread_id]
            del self.sessions[session_key]
            await channel.send("🛑 **Interactive server session ended.** Mention me again in any channel to start a new chat!")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if message.guild and message.guild.id == self.private_guild_id:
            if isinstance(message.channel, discord.Thread) and message.channel.id in self.thread_to_target:
                target_channel_id = self.thread_to_target[message.channel.id]
                target_channel = self.bot.get_channel(target_channel_id)
                if target_channel:
                    await target_channel.send(f"**[Support]**: {message.content}")
                return

        session_key = message.guild.id if message.guild else message.channel.id

        if message.content.strip().lower() == "!asr":
            await self._stop_session(message)
            return

        raw_name = message.guild.name if message.guild else f"dm-{message.author.name}"
        clean_name = "".join(c if c.isalnum() else "-" for c in raw_name.lower())
        identifier = f"server-{message.guild.id}" if message.guild else f"user-{message.author.id}"

        is_mentioned = self.bot.user in message.mentions

        if is_mentioned and session_key not in self.sessions:
            private_guild = self.bot.get_guild(self.private_guild_id)
            thread = None

            if private_guild:
                mem_channel = await self._get_or_create_memory_channel(private_guild, identifier, raw_name)
                thread_name = f"Chat-{clean_name}"
                thread = await mem_channel.create_thread(
                    name=thread_name,
                    type=discord.ChannelType.public_thread
                )

            past_memory = ""
            if private_guild:
                mem_channel = await self._get_or_create_memory_channel(private_guild, identifier, raw_name)
                past_memory = await self._fetch_past_memory(mem_channel)

            self.sessions[session_key] = {
                "thread_id": thread.id if thread else None,
                "history": [],
                "memory": past_memory
            }

            if thread:
                self.thread_to_target[thread.id] = message.channel.id
                await thread.send(f"🟢 **New Server Session Started** for **{raw_name}** by **{message.author}** in #{getattr(message.channel, 'name', 'DM')}")

        if session_key not in self.sessions:
            return

        session = self.sessions[session_key]
        thread_id = session.get("thread_id")
        thread = self.bot.get_channel(thread_id) if thread_id else None

        if thread_id:
            self.thread_to_target[thread_id] = message.channel.id

        clean_prompt = (
            message.content
            .replace(f"<@{self.bot.user.id}>", "")
            .replace(f"<@!{self.bot.user.id}>", "")
            .strip()
        )
        if not clean_prompt:
            clean_prompt = "Hello"

        if thread:
            channel_label = getattr(message.channel, 'name', 'DM')
            user_log = f"👤 **{message.author.name}** (in #{channel_label}): {message.content}"
            if len(user_log) > 2000:
                user_log = user_log[:1995] + "..."
            await thread.send(user_log)

        bot_name = self.bot.user.display_name if self.bot.user else "A-S-R"
        todo_available = self._get_todo_cog() is not None

        system_prompt = (
            f"You are '{bot_name}', a helpful Discord AI assistant for the entire server.\n"
            f"RULES:\n"
            f"1. You are in an active server-wide session. Respond naturally and helpfully.\n"
            f"2. NEVER say you are ChatGPT, OpenAI, Meta, or Groq. Your name is strictly '{bot_name}'.\n"
            f"3. ONLY output '[SKIP]' if the message is clearly addressing another user.\n"
            f"4. For todo list requests (add, list/count, mark done, delete): always use the provided todo tools (`add_todo_task`, `list_todo_tasks`, `mark_todo_done`, `delete_todo_tasks`). If the user asks to delete or mark done by name instead of ID, call `list_todo_tasks` first to find the matching ID(s).\n"
            f"5. If multiple tasks are given to add, call `add_todo_task` for each task.\n"
        )
        if session.get("memory"):
            system_prompt += f"\n[SHARED SERVER MEMORY FROM PAST CONVERSATIONS]:\n{session['memory']}\n"

        messages_payload = [{"role": "system", "content": system_prompt}]
        messages_payload.extend(session["history"][-8:])
        messages_payload.append({"role": "user", "content": f"{message.author.name}: {clean_prompt}"})

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return

        ai_reply = ""
        for model in FALLBACK_MODELS:
            try:
                working_messages = list(messages_payload)

                for _ in range(6):
                    request_kwargs = {
                        "messages": working_messages,
                        "model": model,
                        "temperature": 0.7,
                    }
                    if todo_available:
                        request_kwargs["tools"] = TODO_TOOLS
                        request_kwargs["tool_choice"] = "auto"

                    response = await asyncio.to_thread(
                        groq_client.chat.completions.create,
                        **request_kwargs
                    )
                    msg = response.choices[0].message

                    if getattr(msg, "tool_calls", None):
                        working_messages.append({
                            "role": "assistant",
                            "content": msg.content or "",
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments
                                    }
                                }
                                for tc in msg.tool_calls
                            ]
                        })

                        for tc in msg.tool_calls:
                            tool_result = await self._execute_tool_call(
                                tc,
                                default_actor=f"AI ({message.author.name})",
                                thread=thread
                            )
                            working_messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": tool_result
                            })
                    else:
                        ai_reply = (msg.content or "").strip()
                        break

                if ai_reply:
                    break
            except Exception as e:
                if thread:
                    await thread.send(f"⚠️ *Model `{model}` limit hit or error: {e}. Falling back...*")
                continue

        if not ai_reply or ai_reply.upper() == "[SKIP]":
            if thread:
                await thread.send("🤫 *[AI skipped reply]*")
            return

        if len(ai_reply) > 2000:
            ai_reply = ai_reply[:1995] + "..."

        session["history"].append({"role": "user", "content": f"{message.author.name}: {clean_prompt}"})
        session["history"].append({"role": "assistant", "content": ai_reply})

        await message.reply(ai_reply)

        if thread:
            bot_log = f"🤖 **{bot_name}**: {ai_reply}"
            if len(bot_log) > 2000:
                bot_log = bot_log[:1995] + "..."
            await thread.send(bot_log)


async def setup(bot):
    await bot.add_cog(AISupport(bot))