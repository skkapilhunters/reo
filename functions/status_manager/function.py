import discord
from discord.ext import commands, tasks
import sqlite3
import asyncio
from pathlib import Path

class StatusManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # Project root (Bot/) se data/db folder ka path set karna
        self.root_dir = Path(__file__).resolve().parent.parent.parent
        self.db_dir = self.root_dir / "data" / "db"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / "tasks.db"
        
        self.db_lock = asyncio.Lock()
        self.init_db()
        self.update_status_loop.start()

    def init_db(self):
        """Database initialize with category and weight columns"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT UNIQUE,
                task_name TEXT,
                category TEXT DEFAULT 'user',
                weight INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    async def add_task(self, task_id, task_name, category="user", weight=1):
        """Task start hone par category aur weight ke sath add karega"""
        async with self.db_lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO active_tasks (task_id, task_name, category, weight) 
                    VALUES (?, ?, ?, ?) 
                    ON CONFLICT(task_id) DO UPDATE SET weight=excluded.weight, category=excluded.category
                ''', (task_id, task_name, category, weight))
                conn.commit()
            except Exception as e:
                print(f"[-] DB Error (Add): {e}")
            finally:
                conn.close()

    async def remove_task(self, task_id):
        """Task khatam hone par remove karega"""
        async with self.db_lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM active_tasks WHERE task_id = ?", (task_id,))
                conn.commit()
            except Exception as e:
                print(f"[-] DB Error (Remove): {e}")
            finally:
                conn.close()

    async def get_total_weight(self):
        """Sirf un tasks ka weight sum karega jo status affect karte hain (weight > 0)"""
        async with self.db_lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT SUM(weight) FROM active_tasks")
                result = cursor.fetchone()[0]
                return result if result is not None else 0
            except Exception as e:
                print(f"[-] DB Error (Weight): {e}")
                return 0
            finally:
                conn.close()

    async def get_tasks_by_category(self, category=None):
        """Category ke hisaab se active tasks nikalne ke liye"""
        async with self.db_lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                if category:
                    cursor.execute("SELECT task_id, task_name, weight, created_at FROM active_tasks WHERE category = ?", (category,))
                else:
                    cursor.execute("SELECT task_id, task_name, category, weight, created_at FROM active_tasks")
                return cursor.fetchall()
            except Exception as e:
                print(f"[-] DB Error (Fetch): {e}")
                return []
            finally:
                conn.close()

    @tasks.loop(seconds=10)
    async def update_status_loop(self):
        """Total weight ke basis par status change karega"""
        total_weight = await self.get_total_weight()

        if total_weight == 0:
            activity = discord.Activity(type=discord.ActivityType.watching, name="for tasks | Idle 🟢")
            await self.bot.change_presence(activity=activity, status=discord.Status.idle)
        elif 1 <= total_weight < 10:
            activity = discord.Activity(type=discord.ActivityType.playing, name=f"Running {total_weight} task(s) ⚡")
            await self.bot.change_presence(activity=activity, status=discord.Status.online)
        else:
            activity = discord.Activity(type=discord.ActivityType.watching, name="High Workload / Updating 🔴")
            await self.bot.change_presence(activity=activity, status=discord.Status.dnd)

    @update_status_loop.before_loop
    async def before_update_status(self):
        await self.bot.wait_until_ready()

    def cog_unload(self):
        self.update_status_loop.cancel()

async def setup(bot):
    await bot.add_cog(StatusManager(bot))