import os
import json
import asyncio
from datetime import datetime

import discord
from discord.ext import commands
from discord import app_commands


# ----------------------
# Константы и утилиты
# ----------------------
DATA_DIR = "data"
WARNINGS_FILE = os.path.join(DATA_DIR, "warnings.json")
LOG_FILE = os.path.join(DATA_DIR, "logs.txt")
CONFIG_FILE = "config.json"


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(WARNINGS_FILE):
        with open(WARNINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("")


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        # Создадим шаблон конфига, если его нет
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "token": "YOUR_BOT_TOKEN",
                "prefix": "!",
                "log_channel": "logs"
            }, f, ensure_ascii=False, indent=2)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


class PersistentWarnings:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self._lock = asyncio.Lock()

    async def _read(self) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._read_sync)

    def _read_sync(self) -> dict:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    async def _write(self, data: dict) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._write_sync, data)

    def _write_sync(self, data: dict) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    async def increment(self, guild_id: int, user_id: int) -> int:
        async with self._lock:
            data = await self._read()
            guild_key = str(guild_id)
            user_key = str(user_id)
            if guild_key not in data:
                data[guild_key] = {}
            data[guild_key][user_key] = int(data[guild_key].get(user_key, 0)) + 1
            await self._write(data)
            return data[guild_key][user_key]

    async def decrement(self, guild_id: int, user_id: int) -> int:
        async with self._lock:
            data = await self._read()
            guild_key = str(guild_id)
            user_key = str(user_id)
            current = int(data.get(guild_key, {}).get(user_key, 0))
            new_val = max(0, current - 1)
            if guild_key not in data:
                data[guild_key] = {}
            data[guild_key][user_key] = new_val
            await self._write(data)
            return new_val

    async def get(self, guild_id: int, user_id: int) -> int:
        data = await self._read()
        return int(data.get(str(guild_id), {}).get(str(user_id), 0))


class Logger:
    def __init__(self, file_path: str):
        self.file_path = file_path

    async def log(self, text: str, channel: discord.abc.Messageable | None = None) -> None:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{timestamp}] {text}"

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._append_sync, line)

        if channel is not None:
            try:
                await channel.send(line)
            except Exception:
                pass

    def _append_sync(self, line: str) -> None:
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ----------------------
# Персистентные настройки (на сервер)
# ----------------------
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


class PersistentSettings:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self._lock = asyncio.Lock()
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)

    async def _read(self) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._read_sync)

    def _read_sync(self) -> dict:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    async def _write(self, data: dict) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._write_sync, data)

    def _write_sync(self, data: dict) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    async def get_guild_settings(self, guild_id: int) -> dict:
        data = await self._read()
        return data.get(str(guild_id), {})

    async def update_guild_settings(self, guild_id: int, updates: dict) -> dict:
        async with self._lock:
            data = await self._read()
            g = data.get(str(guild_id), {})
            g.update(updates)
            data[str(guild_id)] = g
            await self._write(data)
            return g

    async def get_autopunish(self, guild_id: int) -> tuple[int, int, int]:
        g = await self.get_guild_settings(guild_id)
        warn_to_mute = int(g.get("warn_to_mute", 3))
        auto_mute_seconds = int(g.get("auto_mute_seconds", 600))
        warn_to_ban = int(g.get("warn_to_ban", 5))
        return warn_to_mute, auto_mute_seconds, warn_to_ban

    async def set_autopunish(self, guild_id: int, warn_to_mute: int, auto_mute_seconds: int, warn_to_ban: int) -> dict:
        return await self.update_guild_settings(
            guild_id,
            {
                "warn_to_mute": int(warn_to_mute),
                "auto_mute_seconds": int(auto_mute_seconds),
                "warn_to_ban": int(warn_to_ban),
            },
        )

    async def get_log_channel_id(self, guild_id: int) -> int | None:
        g = await self.get_guild_settings(guild_id)
        cid = g.get("log_channel_id")
        return int(cid) if cid is not None else None

    async def set_log_channel_id(self, guild_id: int, channel_id: int | None) -> dict:
        updates = {"log_channel_id": int(channel_id)} if channel_id is not None else {"log_channel_id": None}
        return await self.update_guild_settings(guild_id, updates)


# ----------------------
# Вспомогательные функции
# ----------------------
def parse_duration_to_seconds(value: str) -> int | None:
    v = value.strip().lower()
    if not v:
        return None
    # Чисто число → секунды
    if v.isdigit():
        return int(v)
    units = {
        "s": 1,
        "sec": 1,
        "m": 60,
        "min": 60,
        "h": 3600,
        "hr": 3600,
        "d": 86400,
        "day": 86400,
    }
    # Соберём число + суффикс
    num = ""
    suf = ""
    for ch in v:
        if ch.isdigit():
            num += ch
        else:
            suf += ch
    if not num:
        return None
    mul = units.get(suf, None)
    if mul is None:
        return None
    return int(num) * mul

# ----------------------
# Инициализация бота
# ----------------------
ensure_data_dir()
config = load_config()

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=config.get("prefix", "!"), intents=intents)
warnings_store = PersistentWarnings(WARNINGS_FILE)
logger = Logger(LOG_FILE)
settings_store = PersistentSettings(SETTINGS_FILE)


def is_mod():
    async def predicate(interaction: discord.Interaction):
        perms = interaction.user.guild_permissions
        if perms.kick_members or perms.ban_members or perms.manage_guild or perms.manage_messages:
            return True
        try:
            await interaction.response.send_message(
                "❌ У тебя нет прав для использования этой команды.", ephemeral=True
            )
        except Exception:
            pass
        return False
    return app_commands.check(predicate)


async def get_log_channel(guild: discord.Guild) -> discord.abc.Messageable | None:
    # приоритет: per-guild настройка → config.json
    guild_log_id = await settings_store.get_log_channel_id(guild.id)
    if guild_log_id is not None:
        ch = guild.get_channel(guild_log_id)
        if ch is None:
            try:
                ch = await guild.fetch_channel(guild_log_id)
            except Exception:
                ch = None
        if ch is not None:
            return ch

    log_cfg = str(config.get("log_channel", "logs")).strip()
    if not log_cfg:
        return None
    # Попробуем как ID
    try:
        channel_id = int(log_cfg)
        ch = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)
        return ch
    except Exception:
        pass
    # По имени
    for ch in guild.text_channels:
        if ch.name == log_cfg:
            return ch
    return None


async def ensure_muted_role(guild: discord.Guild) -> discord.Role:
    role = discord.utils.get(guild.roles, name="Muted")
    if role is None:
        role = await guild.create_role(name="Muted", reason="Create Muted role for moderation")
        for channel in guild.channels:
            try:
                await channel.set_permissions(role, send_messages=False, speak=False, add_reactions=False)
            except Exception:
                continue
    return role


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Slash-команды синхронизированы: {len(synced)}")
    except Exception as e:
        print(f"Ошибка синхронизации команд: {e}")
    print(f"✅ Бот {bot.user} запущен!")


# ---------------- WARN ---------------- #
@bot.tree.command(name="ping", description="Проверка работоспособности")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Я тут!")

# Сказать от лица бота (только для администраторов)
@bot.tree.command(name="say", description="Отправить сообщение от лица бота (только для админов)")
async def say(
    interaction: discord.Interaction,
    сообщение: str,
    канал: discord.TextChannel | None = None,
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Эта команда доступна только администраторам.", ephemeral=True)
        return
    target_channel = канал or interaction.channel
    try:
        await target_channel.send(сообщение)
    except Exception:
        await interaction.response.send_message("❌ Не удалось отправить сообщение в указанный канал.", ephemeral=True)
        return

    await interaction.response.send_message("✅ Сообщение отправлено.", ephemeral=True)

    # Лог
    log_channel = await get_log_channel(interaction.guild)
    await logger.log(
        f"SAY -> By: {interaction.user} | Channel: {getattr(target_channel, 'id', 'current')} | Content: {сообщение}",
        channel=log_channel,
    )

# ---------------- WARN ---------------- #
@bot.tree.command(name="warn", description="Выдать предупреждение пользователю")
@is_mod()
async def warn(interaction: discord.Interaction, member: discord.Member, причина: str = "Не указана"):
    count = await warnings_store.increment(interaction.guild_id, member.id)

    await interaction.response.send_message(
        f"⚠️ Пользователь {member.mention} получил предупреждение. Причина: {причина} (Всего: {count})"
    )

    # DM пользователю
    try:
        await member.send(
            f"⚠️ Ты получил предупреждение на сервере {interaction.guild.name}. Причина: {причина}. Всего: {count}"
        )
    except Exception:
        pass

    # Лог
    log_channel = await get_log_channel(interaction.guild)
    await logger.log(
        f"WARN -> User: {member} ({member.id}) | By: {interaction.user} | Reason: {причина} | Total: {count}",
        channel=log_channel,
    )

    # Авто-наказания (настройки сервера)
    warn_to_mute, auto_mute_seconds, warn_to_ban = await settings_store.get_autopunish(interaction.guild_id)

    if warn_to_mute > 0 and count == warn_to_mute:
        role = await ensure_muted_role(interaction.guild)
        try:
            await member.add_roles(role, reason="Авто-мут: 3 предупреждения")
        except Exception:
            pass
        await interaction.channel.send(
            f"🔇 {member.mention} автоматически замьючен на {auto_mute_seconds} сек. за ({warn_to_mute} предупреждения)."
        )

        async def unmute_later():
            await asyncio.sleep(auto_mute_seconds)
            try:
                if role in member.roles:
                    await member.remove_roles(role, reason="Авто-размут после 10 минут")
                    await interaction.channel.send(f"✅ {member.mention} был автоматически размьючен.")
            except Exception:
                pass

        bot.loop.create_task(unmute_later())

    elif warn_to_ban > 0 and count >= warn_to_ban:
        try:
            await member.ban(reason=f"Авто-бан: {warn_to_ban} предупреждений")
            await interaction.channel.send(
                f"⛔ {member.mention} автоматически забанен ({warn_to_ban} предупреждений)."
            )
            try:
                await member.send(
                )
            except Exception:
                pass
        except Exception:
            await interaction.channel.send("❌ Не удалось забанить пользователя. У бота недостаточно прав?")


@bot.tree.command(name="unwarn", description="Снять предупреждение")
@is_mod()
async def unwarn(interaction: discord.Interaction, member: discord.Member):
    current = await warnings_store.get(interaction.guild_id, member.id)
    if current <= 0:
        await interaction.response.send_message("❌ У пользователя нет предупреждений.")
        return

    new_val = await warnings_store.decrement(interaction.guild_id, member.id)
    await interaction.response.send_message(
        f"✅ С пользователя {member.mention} снято предупреждение. Осталось: {new_val}"
    )


# ---------------- INFO ---------------- #
@bot.tree.command(name="warnings", description="Показать количество предупреждений у пользователя")
@is_mod()
async def warnings_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    count = await warnings_store.get(interaction.guild_id, target.id)
    await interaction.response.send_message(
        f"ℹ️ У пользователя {target.mention} предупреждений: {count}"
    )

    # Лог
    log_channel = await get_log_channel(interaction.guild)
    await logger.log(
        f"WARNINGS -> User: {target} ({target.id}) | By: {interaction.user} | Total: {count}",
        channel=log_channel,
    )


# ---------------- MUTE ---------------- #
@bot.tree.command(name="mute", description="Выдать мут пользователю")
@is_mod()
async def mute(
    interaction: discord.Interaction,
    member: discord.Member,
    длительность: str,
    причина: str = "Не указана",
):
    seconds = parse_duration_to_seconds(длительность)
    if seconds is None or seconds <= 0:
        await interaction.response.send_message("❌ Укажите корректную длительность: пример 600, 10m, 2h, 1d.", ephemeral=True)
        return

    role = await ensure_muted_role(interaction.guild)
    try:
        await member.add_roles(role, reason=f"Мут на {seconds} секунд. Причина: {причина}")
    except Exception:
        await interaction.response.send_message("❌ Не удалось выдать мут. У бота недостаточно прав?", ephemeral=True)
        return

    await interaction.response.send_message(
        f"🔇 {member.mention} замьючен на {seconds} секунд. Причина: {причина}"
    )

    # DM пользователю
    try:
        await member.send(
            f"🔇 Ты замьючен на сервере {interaction.guild.name} на {seconds} секунд. Причина: {причина}. Чтобы обжаловать перейдите на https://discord.gg/F3bREJXZXz"
        )
    except Exception:
        pass

    # Лог
    log_channel = await get_log_channel(interaction.guild)
    await logger.log(
        f"MUTE -> User: {member} ({member.id}) | By: {interaction.user} | Time: {seconds}s | Reason: {причина}",
        channel=log_channel,
    )

    async def unmute_later():
        await asyncio.sleep(seconds)
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Авто-размут по таймеру")
                await interaction.channel.send(f"✅ {member.mention} был автоматически размьючен.")
        except Exception:
            pass

    bot.loop.create_task(unmute_later())


@bot.tree.command(name="unmute", description="Снять мут с пользователя")
@is_mod()
async def unmute(interaction: discord.Interaction, member: discord.Member):
    role = discord.utils.get(interaction.guild.roles, name="Muted")
    if role and role in member.roles:
        try:
            await member.remove_roles(role, reason="Размут по команде")
            await interaction.response.send_message(f"✅ {member.mention} размьючен.")
        except Exception:
            await interaction.response.send_message("❌ Не удалось снять мут. У бота недостаточно прав?", ephemeral=True)
            return
    else:
        await interaction.response.send_message("❌ У пользователя нет мута.")
        return

    # Лог
    log_channel = await get_log_channel(interaction.guild)
    await logger.log(
        f"UNMUTE -> User: {member} ({member.id}) | By: {interaction.user}",
        channel=log_channel,
    )


# ---------------- BAN ---------------- #
@bot.tree.command(name="ban", description="Забанить пользователя (по умолчанию временно)")
@is_mod()
async def ban(
    interaction: discord.Interaction,
    member: discord.Member,
    длительность: str | None = None,
    причина: str = "Не указана",
):
    # Если длительность не указана — временный бан на 24 часа
    seconds: int | None
    if длительность is None:
        seconds = 24 * 3600
    else:
        perm_tokens = {"perm", "perma", "forever", "inf", "infinite", "permanent", "p"}
        if длительность.strip().lower() in perm_tokens:
            seconds = None
        else:
            seconds = parse_duration_to_seconds(длительность)
            if seconds is None or seconds <= 0:
                await interaction.response.send_message(
                    "❌ Укажите корректную длительность (например: 10m, 2h, 1d) или 'p' для перманентного бана.",
                    ephemeral=True,
                )
                return

    # Уведомление в ЛС до бана
    try:
        when_text = (f" на {seconds} сек." if seconds else " навсегда")
        await member.send(
            f"⛔ Ты был забанен на сервере {interaction.guild.name}{when_text}. Причина: {причина} Чтобы обжаловать перейдите на https://discord.gg/F3bREJXZXz"
        )
    except Exception:
        pass

    # Бан
    try:
        await member.ban(reason=причина)
    except Exception:
        await interaction.response.send_message("❌ Не удалось забанить пользователя. У бота недостаточно прав?", ephemeral=True)
        return

    # Ответ в канал
    if seconds:
        await interaction.response.send_message(
            f"⛔ {member.mention} забанен на {seconds} сек. Причина: {причина}"
        )
    else:
        await interaction.response.send_message(
            f"⛔ {member.mention} забанен навсегда. Причина: {причина}"
        )

    # Лог
    log_channel = await get_log_channel(interaction.guild)
    await logger.log(
        (
            f"BAN -> User: {member} ({member.id}) | By: {interaction.user} | Reason: {причина}" + (f" | Time: {seconds}s" if seconds else " | Time: permanent")
        ),
        channel=log_channel,
    )

    # Планируем автоматический разбан, если бан временный
    if seconds:
        guild = interaction.guild
        banned_user_id = member.id

        async def unban_later():
            await asyncio.sleep(seconds)
            try:
                user = await bot.fetch_user(banned_user_id)
                await guild.unban(user)
                await interaction.channel.send(
                    f"✅ Пользователь {user.mention} автоматически разбанен после истечения срока."
                )
                ch = await get_log_channel(guild)
                await logger.log(
                    f"AUTO-UNBAN -> User: {user} ({user.id}) | After: {seconds}s",
                    channel=ch,
                )
            except Exception:
                pass

        bot.loop.create_task(unban_later())


@bot.tree.command(name="unban", description="Разбанить пользователя по ID")
@is_mod()
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
    except Exception:
        await interaction.response.send_message("❌ Неверный ID пользователя.", ephemeral=True)
        return

    try:
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ Пользователь {user.mention} разбанен.")
    except Exception:
        await interaction.response.send_message("❌ Не удалось разбанить пользователя. Возможно, он не в бане.")
        return

    # Лог
    log_channel = await get_log_channel(interaction.guild)
    await logger.log(
        f"UNBAN -> User: {user} ({user.id}) | By: {interaction.user}",
        channel=log_channel,
    )


# ---------------- KICK ---------------- #
@bot.tree.command(name="kick", description="Выгнать пользователя")
@is_mod()
async def kick(interaction: discord.Interaction, member: discord.Member, причина: str = "Не указана"):
    try:
        await member.kick(reason=причина)
        await interaction.response.send_message(f"👢 {member.mention} кикнут. Причина: {причина}")
    except Exception:
        await interaction.response.send_message("❌ Не удалось кикнуть пользователя. У бота недостаточно прав?", ephemeral=True)
        return

    log_channel = await get_log_channel(interaction.guild)
    await logger.log(
        f"KICK -> User: {member} ({member.id}) | By: {interaction.user} | Reason: {причина}",
        channel=log_channel,
    )


# ---------------- Запуск ---------------- #
def main():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token is None or not token.strip():
        token = str(config.get("token", "")).strip()
    if not token or token == "YOUR_BOT_TOKEN":
        raise SystemExit(
            "Укажите действительный токен бота в config.json под ключом 'token'."
        )
    bot.run(token)


if __name__ == "__main__":
    main()
