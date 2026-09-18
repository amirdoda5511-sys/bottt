
import os
import sqlite3
import logging
import asyncio
import html
import threading
from datetime import datetime

from aiohttp import web
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Render PORT
PORT = int(os.getenv("PORT", "10000"))

# ADMIN_IDS yoki eski ADMIN_ID formatini qabul qiladi
admin_ids_raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")

ADMIN_IDS = {
    int(x.strip())
    for x in admin_ids_raw.split(",")
    if x.strip().isdigit()
}

DATABASE = "kino_bot.db"


# ============================================================
# ENV HELPERS
# ============================================================

def parse_chat_ids(value: str) -> list[int]:
    result = []

    for item in value.split(","):
        item = item.strip()

        if not item:
            continue

        try:
            result.append(int(item))
        except ValueError:
            logger.warning(
                "Noto'g'ri REQUIRED_CHAT_ID: %s",
                item
            )

    return result


def parse_chat_links(value: str) -> list[str]:
    result = []

    for item in value.split(","):
        item = item.strip()

        if not item:
            continue

        if item.startswith("@"):
            item = f"https://t.me/{item[1:]}"
        elif not item.startswith(
            ("https://", "http://", "tg://")
        ):
            item = f"https://t.me/{item}"

        result.append(item)

    return result


REQUIRED_CHAT_IDS = parse_chat_ids(
    os.getenv("REQUIRED_CHAT_ID", "")
)

REQUIRED_CHAT_LINKS = parse_chat_links(
    os.getenv("REQUIRED_CHAT_LINK", "")
)


if len(REQUIRED_CHAT_IDS) != len(REQUIRED_CHAT_LINKS):
    logger.error(
        "REQUIRED_CHAT_ID va REQUIRED_CHAT_LINK soni teng emas! "
        "ID=%s, LINK=%s",
        len(REQUIRED_CHAT_IDS),
        len(REQUIRED_CHAT_LINKS),
    )
    raise SystemExit(1)


CHANNELS = []

for index, chat_id in enumerate(REQUIRED_CHAT_IDS):
    CHANNELS.append(
        {
            "chat_id": chat_id,
            "url": REQUIRED_CHAT_LINKS[index],
            "name": f"📢 {index + 1}-kanal/guruhga qo‘shilish",
        }
    )


CATALOG_CHANNEL_LINK = os.getenv(
    "CATALOG_CHANNEL_LINK",
    "https://t.me/wittkino"
).strip()


# ============================================================
# CONVERSATION STATES
# ============================================================

MOVIE_CODE = 1
MOVIE_FILE = 2
MOVIE_NAME = 3
MOVIE_DESCRIPTION = 4
MOVIE_CATEGORY = 5
MOVIE_ACCESS = 6

BROADCAST_TEXT = 10

STATUS_ACTION = 20
STATUS_USER_ID = 21
STATUS_VALUE = 22


# ============================================================
# DATABASE
# ============================================================

def get_db():
    return sqlite3.connect(DATABASE)


def get_table_columns(cursor, table_name):
    cursor.execute(
        f"PRAGMA table_info({table_name})"
    )

    return {
        row[1]
        for row in cursor.fetchall()
    }


def add_column_if_missing(
    cursor,
    table_name,
    column_name,
    column_definition
):
    columns = get_table_columns(
        cursor,
        table_name
    )

    if column_name not in columns:
        cursor.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name} {column_definition}
            """
        )

        logger.info(
            "Database migration: %s.%s qo‘shildi.",
            table_name,
            column_name
        )


def init_db():

    conn = get_db()
    cursor = conn.cursor()

    # ========================================================
    # USERS
    # ========================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            status TEXT DEFAULT 'USER',
            joined_at TEXT
        )
    """)

    add_column_if_missing(
        cursor,
        "users",
        "username",
        "TEXT"
    )

    add_column_if_missing(
        cursor,
        "users",
        "first_name",
        "TEXT"
    )

    add_column_if_missing(
        cursor,
        "users",
        "status",
        "TEXT DEFAULT 'USER'"
    )

    add_column_if_missing(
        cursor,
        "users",
        "joined_at",
        "TEXT"
    )

    # ========================================================
    # MOVIES
    # ========================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            name TEXT,
            description TEXT,
            category TEXT,
            file_id TEXT,
            file_type TEXT,
            access TEXT DEFAULT 'FREE',
            views INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    add_column_if_missing(
        cursor,
        "movies",
        "code",
        "TEXT"
    )

    add_column_if_missing(
        cursor,
        "movies",
        "name",
        "TEXT"
    )

    add_column_if_missing(
        cursor,
        "movies",
        "description",
        "TEXT"
    )

    add_column_if_missing(
        cursor,
        "movies",
        "category",
        "TEXT"
    )

    add_column_if_missing(
        cursor,
        "movies",
        "file_id",
        "TEXT"
    )

    add_column_if_missing(
        cursor,
        "movies",
        "file_type",
        "TEXT"
    )

    add_column_if_missing(
        cursor,
        "movies",
        "access",
        "TEXT DEFAULT 'FREE'"
    )

    add_column_if_missing(
        cursor,
        "movies",
        "views",
        "INTEGER DEFAULT 0"
    )

    add_column_if_missing(
        cursor,
        "movies",
        "created_at",
        "TEXT"
    )

    # ========================================================
    # RATINGS
    # ========================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            movie_id INTEGER,
            rating INTEGER,
            UNIQUE(user_id, movie_id)
        )
    """)

    # ========================================================
    # SETTINGS
    # ========================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()

    logger.info("Database tayyor.")


# ============================================================
# USER FUNCTIONS
# ============================================================

def register_user(user):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM users WHERE id = ?",
        (user.id,)
    )

    exists = cursor.fetchone()

    if not exists:

        cursor.execute(
            """
            INSERT INTO users
            (
                id,
                username,
                first_name,
                status,
                joined_at
            )
            VALUES (?, ?, ?, 'USER', ?)
            """,
            (
                user.id,
                user.username or "",
                user.first_name or "",
                datetime.now().isoformat(),
            ),
        )

    else:

        cursor.execute(
            """
            UPDATE users
            SET username = ?,
                first_name = ?
            WHERE id = ?
            """,
            (
                user.username or "",
                user.first_name or "",
                user.id,
            ),
        )

    conn.commit()
    conn.close()


def get_user(user_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            username,
            first_name,
            status,
            joined_at
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    )

    user = cursor.fetchone()

    conn.close()

    return user


def get_user_status(user_id):

    # .env dagi adminlar doimiy ADMIN
    if user_id in ADMIN_IDS:
        return "ADMIN"

    user = get_user(user_id)

    if not user:
        return "USER"

    status = user[3]

    if not status:
        return "USER"

    return status.upper()


def is_admin(user_id):

    # 1. .env admin
    if user_id in ADMIN_IDS:
        return True

    # 2. DB orqali berilgan ADMIN
    return get_user_status(user_id) == "ADMIN"


def set_user_status(user_id, status):

    status = status.upper()

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE users
        SET status = ?
        WHERE id = ?
        """,
        (
            status,
            user_id
        )
    )

    affected = cursor.rowcount

    conn.commit()
    conn.close()

    return affected > 0


# ============================================================
# SUBSCRIPTION
# ============================================================

async def check_one_subscription(
    bot,
    user_id,
    chat_id
):

    try:

        member = await bot.get_chat_member(
            chat_id=chat_id,
            user_id=user_id
        )

        status = str(
            member.status
        ).lower()

        if status in {
            "left",
            "kicked",
            "banned"
        }:
            return False

        if status == "restricted":

            return bool(
                getattr(
                    member,
                    "is_member",
                    False
                )
            )

        return True

    except Exception as e:

        logger.error(
            "Subscription tekshirish xatosi: "
            "chat=%s user=%s error=%s",
            chat_id,
            user_id,
            e,
        )

        return False


async def check_subscription(
    bot,
    user_id
):

    if not CHANNELS:
        return True

    for channel in CHANNELS:

        subscribed = await check_one_subscription(
            bot,
            user_id,
            channel["chat_id"]
        )

        if not subscribed:
            return False

    return True


def subscription_keyboard():

    buttons = []

    for channel in CHANNELS:

        buttons.append(
            [
                InlineKeyboardButton(
                    channel["name"],
                    url=channel["url"]
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "✅ Obunani tekshirish",
                callback_data="check_subscription"
            )
        ]
    )

    return InlineKeyboardMarkup(buttons)


async def show_subscription_required(
    message
):

    await message.reply_text(
        "🔐 <b>Botdan foydalanish uchun avval "
        "barcha kanal/guruhlarga qo‘shiling.</b>\n\n"
        "1️⃣ Quyidagi tugmalar orqali qo‘shiling.\n"
        "2️⃣ Keyin <b>Obunani tekshirish</b> "
        "tugmasini bosing.",
        reply_markup=subscription_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# KEYBOARDS
# ============================================================

def main_reply_keyboard(user_id):

    rows = [
        [
            "🔎 Kino qidirish",
            "🔥 Mashhur kinolar"
        ],
        [
            "🆕 Yangi kinolar",
            "🎬 Kategoriyalar"
        ],
        [
            "👤 Profil"
        ],
    ]

    if is_admin(user_id):

        rows.append(
            [
                "⚙️ Admin panel"
            ]
        )

    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True
    )


def main_inline_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔥 Mashhur",
                    callback_data="popular"
                ),
                InlineKeyboardButton(
                    "🆕 Yangi",
                    callback_data="latest"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎬 Kategoriyalar",
                    callback_data="categories"
                ),
            ],
            [
                InlineKeyboardButton(
                    "👤 Profil",
                    callback_data="status"
                ),
            ],
        ]
    )


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    register_user(user)

    subscribed = await check_subscription(
        context.bot,
        user.id
    )

    if not subscribed:

        await show_subscription_required(
            update.message
        )

        return

    status = get_user_status(
        user.id
    )

    await update.message.reply_text(
        f"🎬 <b>Assalomu alaykum, "
        f"{html.escape(user.first_name or 'do‘st')}!</b>\n\n"
        "🍿 Kino botimizga xush kelibsiz!\n\n"
        f"⭐ Statusingiz: <b>{html.escape(status)}</b>\n\n"
        "🔎 Kino kodini yoki nomini yuboring.",
        parse_mode="HTML",
        reply_markup=main_reply_keyboard(
            user.id
        ),
    )

    await update.message.reply_text(
        "👇 Menyudan kerakli bo‘limni tanlang:",
        reply_markup=main_inline_keyboard()
    )


# ============================================================
# SEARCH
# ============================================================

def search_movies(query):

    conn = get_db()
    cursor = conn.cursor()

    search = f"%{query}%"

    cursor.execute(
        """
        SELECT
            id,
            code,
            name,
            description,
            category,
            file_id,
            file_type,
            access,
            views
        FROM movies
        WHERE code LIKE ?
           OR name LIKE ?
           OR description LIKE ?
           OR category LIKE ?
        ORDER BY views DESC
        LIMIT 20
        """,
        (
            search,
            search,
            search,
            search
        )
    )

    movies = cursor.fetchall()

    conn.close()

    return movies


def get_movie_by_code(code):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            code,
            name,
            description,
            category,
            file_id,
            file_type,
            access,
            views
        FROM movies
        WHERE LOWER(code) = LOWER(?)
        """,
        (code.strip(),)
    )

    movie = cursor.fetchone()

    conn.close()

    return movie


def get_movie(movie_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            code,
            name,
            description,
            category,
            file_id,
            file_type,
            access,
            views
        FROM movies
        WHERE id = ?
        """,
        (movie_id,)
    )

    movie = cursor.fetchone()

    conn.close()

    return movie


def increase_views(movie_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE movies
        SET views = views + 1
        WHERE id = ?
        """,
        (movie_id,)
    )

    conn.commit()
    conn.close()


# ============================================================
# SEND MOVIE
# ============================================================

async def send_movie(
    message,
    movie
):

    if not movie:
        return

    (
        movie_id,
        code,
        name,
        description,
        category,
        file_id,
        file_type,
        access,
        views,
    ) = movie

    increase_views(movie_id)

    safe_name = html.escape(
        name or ""
    )

    safe_description = html.escape(
        description or ""
    )

    safe_category = html.escape(
        category or ""
    )

    safe_code = html.escape(
        code or ""
    )

    caption = (
        f"🎬 <b>{safe_name}</b>\n\n"
        f"📝 {safe_description}\n\n"
        f"🏷 Kategoriya: "
        f"<b>{safe_category}</b>\n"
        f"🔐 Access: <b>{html.escape(access or 'FREE')}</b>\n"
        f"🔢 Kod: <code>{safe_code}</code>\n"
        f"👁 Ko‘rishlar: {views + 1}"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⭐ 1",
                    callback_data=f"rate:{movie_id}:1"
                ),
                InlineKeyboardButton(
                    "⭐ 2",
                    callback_data=f"rate:{movie_id}:2"
                ),
                InlineKeyboardButton(
                    "⭐ 3",
                    callback_data=f"rate:{movie_id}:3"
                ),
                InlineKeyboardButton(
                    "⭐ 4",
                    callback_data=f"rate:{movie_id}:4"
                ),
                InlineKeyboardButton(
                    "⭐ 5",
                    callback_data=f"rate:{movie_id}:5"
                ),
            ]
        ]
    )

    try:

        if file_type == "video":

            await message.reply_video(
                video=file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        elif file_type == "document":

            await message.reply_document(
                document=file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

    except Exception as e:

        logger.error(
            "Kino yuborishda xato: %s",
            e
        )

        await message.reply_text(
            "❌ Kino yuborishda xatolik yuz berdi."
        )


# ============================================================
# MOVIE LISTS
# ============================================================

async def popular_movies(message):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            code,
            name,
            category,
            views
        FROM movies
        ORDER BY views DESC
        LIMIT 10
        """
    )

    movies = cursor.fetchall()

    conn.close()

    if not movies:

        await message.reply_text(
            "📭 Hozircha kinolar mavjud emas."
        )

        return

    buttons = []

    for (
        movie_id,
        code,
        name,
        category,
        views
    ) in movies:

        buttons.append(
            [
                InlineKeyboardButton(
                    f"🔥 {name} — 👁 {views}",
                    callback_data=f"movie:{movie_id}"
                )
            ]
        )

    await message.reply_text(
        "🔥 <b>Mashhur kinolar</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


async def latest_movies(message):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            code,
            name,
            category
        FROM movies
        ORDER BY id DESC
        LIMIT 10
        """
    )

    movies = cursor.fetchall()

    conn.close()

    if not movies:

        await message.reply_text(
            "📭 Hozircha kinolar mavjud emas."
        )

        return

    buttons = []

    for (
        movie_id,
        code,
        name,
        category
    ) in movies:

        buttons.append(
            [
                InlineKeyboardButton(
                    f"🆕 {name}",
                    callback_data=f"movie:{movie_id}"
                )
            ]
        )

    await message.reply_text(
        "🆕 <b>Yangi kinolar</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


async def categories(message):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT DISTINCT category
        FROM movies
        WHERE category IS NOT NULL
          AND category != ''
        ORDER BY category
        """
    )

    rows = cursor.fetchall()

    conn.close()

    if not rows:

        await message.reply_text(
            "📭 Kategoriyalar mavjud emas."
        )

        return

    buttons = []

    for row in rows:

        category = row[0]

        buttons.append(
            [
                InlineKeyboardButton(
                    f"🎬 {category}",
                    callback_data=f"category:{category}"
                )
            ]
        )

    await message.reply_text(
        "🎬 <b>Kategoriyalar</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


async def category_movies(
    message,
    category
):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            name
        FROM movies
        WHERE category = ?
        ORDER BY id DESC
        LIMIT 30
        """,
        (category,)
    )

    movies = cursor.fetchall()

    conn.close()

    if not movies:

        await message.reply_text(
            "📭 Bu kategoriyada kino topilmadi."
        )

        return

    buttons = []

    for movie_id, name in movies:

        buttons.append(
            [
                InlineKeyboardButton(
                    f"🎬 {name}",
                    callback_data=f"movie:{movie_id}"
                )
            ]
        )

    await message.reply_text(
        f"🎬 <b>{html.escape(category)}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


# ============================================================
# PROFILE / STATUS
# ============================================================

async def show_status(
    message,
    user_id
):

    user = get_user(user_id)

    if not user:

        await message.reply_text(
            "❌ Profil topilmadi."
        )

        return

    status = get_user_status(
        user_id
    )

    if status == "USER":

        await message.reply_text(
            "👤 <b>Sizning profilingiz</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"👤 Ism: "
            f"{html.escape(user[2] or '')}\n"
            f"⭐ Status: <b>USER</b>\n\n"
            "📈 <b>Statusingizni oshirishni "
            "xohlaysizmi?</b>\n\n"
            "⭐ VIP yoki PREMIUM status olish "
            "uchun admin bilan bog‘laning:\n"
            '👤 <a href="https://t.me/wittmen">@wittmen</a>',
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

        return

    if status == "VIP":

        status_text = (
            "⭐ <b>VIP</b>"
        )

    elif status == "PREMIUM":

        status_text = (
            "💎 <b>PREMIUM</b>"
        )

    elif status == "ADMIN":

        status_text = (
            "👑 <b>ADMIN</b>"
        )

    else:

        status_text = (
            f"⭐ <b>{html.escape(status)}</b>"
        )

    await message.reply_text(
        "👤 <b>Sizning profilingiz</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Ism: "
        f"{html.escape(user[2] or '')}\n"
        f"⭐ Status: {status_text}",
        parse_mode="HTML",
    )


# ============================================================
# RATING
# ============================================================

async def rating_callback(
    query,
    movie_id,
    rating
):

    user_id = query.from_user.id

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO ratings
        (
            user_id,
            movie_id,
            rating
        )
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, movie_id)
        DO UPDATE SET rating = excluded.rating
        """,
        (
            user_id,
            movie_id,
            rating
        )
    )

    conn.commit()
    conn.close()

    await query.answer(
        f"⭐ {rating}/5 baho qabul qilindi!",
        show_alert=False
    )


# ============================================================
# INLINE MOVIE
# ============================================================

async def inline_movie_callback(
    query,
    movie_id
):

    movie = get_movie(
        movie_id
    )

    if not movie:

        await query.answer(
            "❌ Kino topilmadi.",
            show_alert=True
        )

        return

    (
        movie_id,
        code,
        name,
        description,
        category,
        file_id,
        file_type,
        access,
        views,
    ) = movie

    text = (
        f"🎬 <b>{html.escape(name or '')}</b>\n\n"
        f"📝 {html.escape(description or '')}\n\n"
        f"🏷 {html.escape(category or '')}\n"
        f"🔐 Access: <b>{html.escape(access or 'FREE')}</b>\n"
        f"🔢 Kod: "
        f"<code>{html.escape(code or '')}</code>\n"
        f"👁 Ko‘rishlar: {views}"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎬 Kinoni olish",
                    callback_data=f"getmovie:{movie_id}"
                )
            ]
        ]
    )

    await query.answer()

    try:

        await query.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    except Exception:

        await query.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )


async def get_movie_callback(
    query,
    movie_id
):

    movie = get_movie(
        movie_id
    )

    if not movie:

        await query.answer(
            "❌ Kino topilmadi.",
            show_alert=True
        )

        return

    await query.answer(
        "🎬 Kino yuborilmoqda..."
    )

    await send_movie(
        query.message,
        movie
    )


# ============================================================
# SUBSCRIPTION CALLBACK
# ============================================================

async def subscription_callback(
    query,
    context
):

    user_id = query.from_user.id

    subscribed = await check_subscription(
        context.bot,
        user_id
    )

    if not subscribed:

        await query.answer(
            "❌ Hali barcha kanal/guruhlarga "
            "qo‘shilmagansiz.",
            show_alert=True
        )

        return

    await query.answer(
        "✅ Obuna tasdiqlandi!"
    )

    try:

        await query.edit_message_text(
            "✅ <b>Obuna tasdiqlandi!</b>\n\n"
            "🎬 Endi botdan foydalanishingiz mumkin.",
            parse_mode="HTML",
        )

    except Exception:
        pass

    if query.message:

        await query.message.reply_text(
            "👇 Menyudan foydalaning:",
            reply_markup=main_reply_keyboard(
                user_id
            )
        )

        await query.message.reply_text(
            "🎬 Asosiy menyu:",
            reply_markup=main_inline_keyboard()
        )


# ============================================================
# ADMIN PANEL
# ============================================================

def admin_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Kino qo‘shish",
                    callback_data="admin_add"
                ),
                InlineKeyboardButton(
                    "🗑 Kino o‘chirish",
                    callback_data="admin_delete"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📊 Statistika",
                    callback_data="admin_stats"
                ),
                InlineKeyboardButton(
                    "👥 Foydalanuvchilar",
                    callback_data="admin_users"
                ),
            ],
            [
                InlineKeyboardButton(
                    "⭐ Status boshqarish",
                    callback_data="admin_status"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📢 Reklama yuborish",
                    callback_data="admin_broadcast"
                ),
            ],
        ]
    )


def status_admin_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⭐ Status berish",
                    callback_data="status_give"
                ),
            ],
            [
                InlineKeyboardButton(
                    "❌ Statusni olib tashlash",
                    callback_data="status_remove"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📋 Statuslar haqida",
                    callback_data="status_info"
                ),
            ],
        ]
    )


async def admin_command(
    update,
    context
):

    user = update.effective_user

    if not user or not is_admin(user.id):

        await update.message.reply_text(
            "❌ Siz admin emassiz."
        )

        return

    await update.message.reply_text(
        "⚙️ <b>Admin panel</b>\n\n"
        "Kerakli bo‘limni tanlang:",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


# ============================================================
# ADMIN STATUS MANAGEMENT
# ============================================================

async def status_panel(
    query
):

    if not is_admin(
        query.from_user.id
    ):

        await query.answer(
            "❌ Siz admin emassiz.",
            show_alert=True
        )

        return

    await query.answer()

    await query.message.reply_text(
        "⭐ <b>Status boshqaruvi</b>\n\n"
        "Bu bo‘lim orqali foydalanuvchiga "
        "VIP, PREMIUM yoki ADMIN status "
        "berishingiz mumkin.\n\n"
        "Yoki statusni butunlay olib "
        "tashlashingiz mumkin.",
        parse_mode="HTML",
        reply_markup=status_admin_keyboard()
    )


async def status_give_start(
    update,
    context
):

    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):

        await query.answer(
            "❌ Siz admin emassiz.",
            show_alert=True
        )

        return ConversationHandler.END

    await query.answer()

    await query.message.reply_text(
        "⭐ <b>Status berish</b>\n\n"
        "Avval foydalanuvchi ID sini yuboring.\n\n"
        "Masalan:\n"
        "<code>123456789</code>",
        parse_mode="HTML"
    )

    return STATUS_USER_ID


async def status_user_id(
    update,
    context
):

    text = update.message.text.strip()

    if not text.isdigit():

        await update.message.reply_text(
            "❌ ID faqat raqamlardan iborat bo‘lishi kerak.\n\n"
            "Masalan: <code>123456789</code>",
            parse_mode="HTML"
        )

        return STATUS_USER_ID

    user_id = int(text)

    user = get_user(
        user_id
    )

    if not user:

        await update.message.reply_text(
            "❌ Bu ID bilan foydalanuvchi "
            "bazada topilmadi.\n\n"
            "Foydalanuvchi botni kamida bir "
            "marta ishga tushirgan bo‘lishi kerak.",
        )

        return STATUS_USER_ID

    context.user_data[
        "status_user_id"
    ] = user_id

    await update.message.reply_text(
        "2️⃣ Endi statusni tanlang yoki "
        "matn ko‘rinishida yuboring:\n\n"
        "<code>ADMIN</code>\n"
        "<code>VIP</code>\n"
        "<code>PREMIUM</code>\n"
        "<code>USER</code>",
        parse_mode="HTML"
    )

    return STATUS_VALUE


async def status_value(
    update,
    context
):

    status = update.message.text.strip().upper()

    allowed = {
        "ADMIN",
        "VIP",
        "PREMIUM",
        "USER",
        "REMOVE",
    }

    if status not in allowed:

        await update.message.reply_text(
            "❌ Noto‘g‘ri status.\n\n"
            "Faqat:\n"
            "ADMIN\n"
            "VIP\n"
            "PREMIUM\n"
            "USER\n"
            "REMOVE"
        )

        return STATUS_VALUE

    user_id = context.user_data.get(
        "status_user_id"
    )

    if not user_id:

        await update.message.reply_text(
            "❌ Foydalanuvchi ID topilmadi."
        )

        context.user_data.clear()

        return ConversationHandler.END

    # REMOVE = USER
    if status == "REMOVE":
        status = "USER"

    # .env adminni DB orqali olib tashlash mumkin emas
    if user_id in ADMIN_IDS and status != "ADMIN":

        await update.message.reply_text(
            "⚠️ Bu foydalanuvchi "
            "<b>.env</b> orqali asosiy admin.\n\n"
            "Uni USER/VIP/PREMIUM qilish mumkin emas, "
            "chunki u ADMIN_IDS ichida turibdi.",
            parse_mode="HTML"
        )

        context.user_data.clear()

        return ConversationHandler.END

    updated = set_user_status(
        user_id,
        status
    )

    if not updated:

        await update.message.reply_text(
            "❌ Statusni o‘zgartirib bo‘lmadi."
        )

        context.user_data.clear()

        return ConversationHandler.END

    if status == "ADMIN":

        message = (
            "👑 <b>ADMIN status berildi!</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            "⭐ Status: <b>ADMIN</b>\n\n"
            "✅ Endi bu foydalanuvchi "
            "admin paneliga kira oladi."
        )

    elif status == "VIP":

        message = (
            "⭐ <b>VIP status berildi!</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            "⭐ Status: <b>VIP</b>"
        )

    elif status == "PREMIUM":

        message = (
            "💎 <b>PREMIUM status berildi!</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            "💎 Status: <b>PREMIUM</b>"
        )

    else:

        message = (
            "❌ <b>Status olib tashlandi!</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            "⭐ Status: <b>USER</b>"
        )

    await update.message.reply_text(
        message,
        parse_mode="HTML"
    )

    context.user_data.clear()

    return ConversationHandler.END


async def status_remove_start(
    query
):

    if not is_admin(
        query.from_user.id
    ):

        await query.answer(
            "❌ Siz admin emassiz.",
            show_alert=True
        )

        return

    await query.answer()

    await query.message.reply_text(
        "❌ <b>Statusni olib tashlash</b>\n\n"
        "Foydalanuvchi ID sini yuboring.\n\n"
        "Masalan:\n"
        "<code>123456789</code>\n\n"
        "Natija: <b>USER</b>",
        parse_mode="HTML"
    )


async def process_status_command(
    update
):

    parts = (
        update.message.text
        .strip()
        .split()
    )

    if len(parts) != 2:
        return False

    if not parts[0].isdigit():
        return False

    user_id = int(
        parts[0]
    )

    status = parts[1].upper()

    allowed = {
        "ADMIN",
        "VIP",
        "PREMIUM",
        "USER",
        "REMOVE",
    }

    if status not in allowed:
        return False

    user = get_user(
        user_id
    )

    if not user:

        await update.message.reply_text(
            "❌ Bunday foydalanuvchi "
            "topilmadi."
        )

        return True

    if status == "REMOVE":
        status = "USER"

    if user_id in ADMIN_IDS and status != "ADMIN":

        await update.message.reply_text(
            "⚠️ Bu foydalanuvchi "
            "ADMIN_IDS ichidagi asosiy admin."
        )

        return True

    set_user_status(
        user_id,
        status
    )

    if status == "ADMIN":

        await update.message.reply_text(
            f"👑 <b>ADMIN status berildi!</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"⭐ Status: <b>ADMIN</b>\n\n"
            "✅ Endi bu foydalanuvchi "
            "admin paneliga kira oladi.",
            parse_mode="HTML"
        )

    elif status == "USER":

        await update.message.reply_text(
            f"❌ <b>Status olib tashlandi!</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            "⭐ Status: <b>USER</b>",
            parse_mode="HTML"
        )

    else:

        await update.message.reply_text(
            f"✅ <b>Status o‘zgartirildi!</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"⭐ Status: <b>{status}</b>",
            parse_mode="HTML"
        )

    return True


# ============================================================
# STATUS INFO
# ============================================================

async def status_info(
    query
):

    if not is_admin(
        query.from_user.id
    ):

        await query.answer(
            "❌ Siz admin emassiz.",
            show_alert=True
        )

        return

    await query.answer()

    await query.message.reply_text(
        "⭐ <b>Status tizimi</b>\n\n"
        "👤 <b>USER</b> — oddiy foydalanuvchi\n"
        "⭐ <b>VIP</b> — VIP foydalanuvchi\n"
        "💎 <b>PREMIUM</b> — Premium foydalanuvchi\n"
        "👑 <b>ADMIN</b> — admin panelga kirish huquqi\n\n"
        "📌 Tezkor buyruqlar:\n\n"
        "<code>ID ADMIN</code>\n"
        "<code>ID VIP</code>\n"
        "<code>ID PREMIUM</code>\n"
        "<code>ID USER</code>\n"
        "<code>ID REMOVE</code>\n\n"
        "Masalan:\n"
        "<code>123456789 ADMIN</code>",
        parse_mode="HTML"
    )


# ============================================================
# ADD MOVIE
# ============================================================

async def add_movie_start(
    update,
    context
):

    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):

        await query.answer(
            "❌ Siz admin emassiz.",
            show_alert=True
        )

        return ConversationHandler.END

    await query.answer()

    await query.message.reply_text(
        "➕ <b>Kino qo‘shish</b>\n\n"
        "1️⃣ Kino kodini yuboring.\n\n"
        "Masalan: <code>123</code>",
        parse_mode="HTML"
    )

    return MOVIE_CODE


async def add_movie_code(
    update,
    context
):

    code = update.message.text.strip()

    if not code:

        await update.message.reply_text(
            "❌ Kod bo‘sh bo‘lmasligi kerak."
        )

        return MOVIE_CODE

    existing = get_movie_by_code(
        code
    )

    if existing:

        await update.message.reply_text(
            "❌ Bu kod allaqachon mavjud.\n"
            "Boshqa kod yuboring."
        )

        return MOVIE_CODE

    context.user_data[
        "movie_code"
    ] = code

    await update.message.reply_text(
        "2️⃣ Endi kino "
        "<b>video yoki document</b> "
        "faylini yuboring.",
        parse_mode="HTML"
    )

    return MOVIE_FILE


async def add_movie_file(
    update,
    context
):

    if update.message.video:

        context.user_data[
            "file_id"
        ] = update.message.video.file_id

        context.user_data[
            "file_type"
        ] = "video"

    elif update.message.document:

        context.user_data[
            "file_id"
        ] = update.message.document.file_id

        context.user_data[
            "file_type"
        ] = "document"

    else:

        await update.message.reply_text(
            "❌ Iltimos, video yoki fayl yuboring."
        )

        return MOVIE_FILE

    await update.message.reply_text(
        "3️⃣ Kino nomini yuboring."
    )

    return MOVIE_NAME


async def add_movie_name(
    update,
    context
):

    name = update.message.text.strip()

    if not name:

        await update.message.reply_text(
            "❌ Kino nomi bo‘sh bo‘lmasligi kerak."
        )

        return MOVIE_NAME

    context.user_data[
        "movie_name"
    ] = name

    await update.message.reply_text(
        "4️⃣ Kino tavsifini yuboring."
    )

    return MOVIE_DESCRIPTION


async def add_movie_description(
    update,
    context
):

    description = update.message.text.strip()

    context.user_data[
        "movie_description"
    ] = description

    await update.message.reply_text(
        "5️⃣ Kategoriya nomini yuboring.\n\n"
        "Masalan: <code>Jangari</code>",
        parse_mode="HTML"
    )

    return MOVIE_CATEGORY


async def add_movie_category(
    update,
    context
):

    category = update.message.text.strip()

    if not category:

        await update.message.reply_text(
            "❌ Kategoriya bo‘sh bo‘lmasligi kerak."
        )

        return MOVIE_CATEGORY

    context.user_data[
        "movie_category"
    ] = category

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🆓 FREE",
                    callback_data="access:FREE"
                ),
                InlineKeyboardButton(
                    "⭐ VIP",
                    callback_data="access:VIP"
                ),
            ],
            [
                InlineKeyboardButton(
                    "💎 PREMIUM",
                    callback_data="access:PREMIUM"
                ),
            ],
        ]
    )

    await update.message.reply_text(
        "6️⃣ Kino uchun kirish turini tanlang:",
        reply_markup=keyboard
    )

    return MOVIE_ACCESS


async def add_movie_access(
    update,
    context
):

    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):

        await query.answer(
            "❌ Siz admin emassiz.",
            show_alert=True
        )

        return ConversationHandler.END

    access = query.data.split(
        ":",
        1
    )[1]

    context.user_data[
        "movie_access"
    ] = access

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO movies
        (
            code,
            name,
            description,
            category,
            file_id,
            file_type,
            access,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context.user_data["movie_code"],
            context.user_data["movie_name"],
            context.user_data["movie_description"],
            context.user_data["movie_category"],
            context.user_data["file_id"],
            context.user_data["file_type"],
            context.user_data["movie_access"],
            datetime.now().isoformat(),
        )
    )

    conn.commit()
    conn.close()

    await query.answer(
        "✅ Kino qo‘shildi!"
    )

    await query.message.reply_text(
        "✅ <b>Kino muvaffaqiyatli qo‘shildi!</b>\n\n"
        f"🔢 Kod: "
        f"<code>{html.escape(context.user_data['movie_code'])}</code>\n"
        f"🎬 Nom: "
        f"<b>{html.escape(context.user_data['movie_name'])}</b>\n"
        f"🏷 Kategoriya: "
        f"{html.escape(context.user_data['movie_category'])}\n"
        f"🔐 Access: "
        f"<b>{context.user_data['movie_access']}</b>",
        parse_mode="HTML"
    )

    context.user_data.clear()

    return ConversationHandler.END


async def cancel_conversation(
    update,
    context
):

    context.user_data.clear()

    await update.message.reply_text(
        "❌ Amal bekor qilindi."
    )

    return ConversationHandler.END


# ============================================================
# DELETE MOVIE
# ============================================================

async def delete_movie_start(
    query
):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, code, name
        FROM movies
        ORDER BY id DESC
        LIMIT 30
        """
    )

    movies = cursor.fetchall()

    conn.close()

    if not movies:

        await query.answer(
            "📭 Kinolar yo‘q.",
            show_alert=True
        )

        return

    buttons = []

    for (
        movie_id,
        code,
        name
    ) in movies:

        buttons.append(
            [
                InlineKeyboardButton(
                    f"🗑 {code} — {name}",
                    callback_data=f"delete:{movie_id}"
                )
            ]
        )

    await query.answer()

    await query.message.reply_text(
        "🗑 O‘chirish uchun kinoni tanlang:",
        reply_markup=InlineKeyboardMarkup(
            buttons
        )
    )


async def delete_movie(
    query,
    movie_id
):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT name
        FROM movies
        WHERE id = ?
        """,
        (movie_id,)
    )

    movie = cursor.fetchone()

    if not movie:

        conn.close()

        await query.answer(
            "❌ Kino topilmadi.",
            show_alert=True
        )

        return

    cursor.execute(
        """
        DELETE FROM ratings
        WHERE movie_id = ?
        """,
        (movie_id,)
    )

    cursor.execute(
        """
        DELETE FROM movies
        WHERE id = ?
        """,
        (movie_id,)
    )

    conn.commit()
    conn.close()

    await query.answer(
        "✅ Kino o‘chirildi."
    )

    await query.message.reply_text(
        f"🗑 <b>{html.escape(movie[0])}</b> "
        f"o‘chirildi.",
        parse_mode="HTML"
    )


# ============================================================
# ADMIN STATS
# ============================================================

async def admin_stats(
    query
):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM users"
    )

    users = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM movies"
    )

    movies = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COALESCE(
            SUM(views),
            0
        )
        FROM movies
        """
    )

    views = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE status = 'ADMIN'
        """
    )

    db_admins = cursor.fetchone()[0]

    conn.close()

    total_admins = len(ADMIN_IDS) + db_admins

    await query.answer()

    await query.message.reply_text(
        "📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: "
        f"<b>{users}</b>\n"
        f"🎬 Kinolar: "
        f"<b>{movies}</b>\n"
        f"👁 Umumiy ko‘rishlar: "
        f"<b>{views}</b>\n"
        f"👑 Adminlar: "
        f"<b>{total_admins}</b>",
        parse_mode="HTML"
    )


# ============================================================
# ADMIN USERS
# ============================================================

async def admin_users(
    query
):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            username,
            first_name,
            status
        FROM users
        ORDER BY joined_at DESC
        LIMIT 30
        """
    )

    users = cursor.fetchall()

    conn.close()

    await query.answer()

    if not users:

        await query.message.reply_text(
            "📭 Foydalanuvchilar yo‘q."
        )

        return

    text = (
        "👥 <b>Oxirgi foydalanuvchilar</b>\n\n"
    )

    for (
        user_id,
        username,
        first_name,
        status
    ) in users:

        # .env adminlarini ADMIN sifatida ko‘rsatamiz
        real_status = get_user_status(
            user_id
        )

        username_text = (
            f"@{username}"
            if username
            else "username yo‘q"
        )

        text += (
            f"🆔 <code>{user_id}</code>\n"
            f"👤 {html.escape(first_name or '')}\n"
            f"🔗 {html.escape(username_text)}\n"
            f"⭐ <b>{html.escape(real_status)}</b>\n\n"
        )

    await query.message.reply_text(
        text,
        parse_mode="HTML"
    )


# ============================================================
# BROADCAST
# ============================================================

async def broadcast_start(
    query
):

    await query.answer()

    await query.message.reply_text(
        "📢 <b>Broadcast</b>\n\n"
        "Yuboriladigan xabarni yozing.\n\n"
        "/cancel — bekor qilish",
        parse_mode="HTML"
    )

    return BROADCAST_TEXT


async def broadcast_send(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):

        return ConversationHandler.END

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM users"
    )

    users = cursor.fetchall()

    conn.close()

    success = 0
    failed = 0

    await update.message.reply_text(
        "📢 Xabar yuborilmoqda..."
    )

    for (user_id,) in users:

        try:

            await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )

            success += 1

            await asyncio.sleep(
                0.05
            )

        except Exception as e:

            failed += 1

            logger.warning(
                "Broadcast error "
                "user=%s: %s",
                user_id,
                e
            )

    await update.message.reply_text(
        "✅ <b>Broadcast tugadi!</b>\n\n"
        f"✅ Yuborildi: "
        f"<b>{success}</b>\n"
        f"❌ Xato: "
        f"<b>{failed}</b>",
        parse_mode="HTML"
    )

    return ConversationHandler.END


# ============================================================
# CALLBACK ROUTER
# ============================================================

async def callback_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query
    data = query.data or ""

    try:

        # ====================================================
        # SUBSCRIPTION
        # ====================================================

        if data == "check_subscription":

            await subscription_callback(
                query,
                context
            )

            return

        # ====================================================
        # ADMIN
        # ====================================================

        if data == "admin_add":

            return await add_movie_start(
                update,
                context
            )

        if data == "admin_delete":

            if not is_admin(
                query.from_user.id
            ):

                await query.answer(
                    "❌ Siz admin emassiz.",
                    show_alert=True
                )

                return

            await delete_movie_start(
                query
            )

            return

        if data == "admin_stats":

            if not is_admin(
                query.from_user.id
            ):

                await query.answer(
                    "❌ Siz admin emassiz.",
                    show_alert=True
                )

                return

            await admin_stats(
                query
            )

            return

        if data == "admin_users":

            if not is_admin(
                query.from_user.id
            ):

                await query.answer(
                    "❌ Siz admin emassiz.",
                    show_alert=True
                )

                return

            await admin_users(
                query
            )

            return

        if data == "admin_status":

            await status_panel(
                query
            )

            return

        if data == "status_info":

            await status_info(
                query
            )

            return

        if data == "status_remove":

            await status_remove_start(
                query
            )

            return

        if data == "admin_broadcast":

            if not is_admin(
                query.from_user.id
            ):

                await query.answer(
                    "❌ Siz admin emassiz.",
                    show_alert=True
                )

                return ConversationHandler.END

            return await broadcast_start(
                query
            )

        # ====================================================
        # ADD MOVIE ACCESS
        # ====================================================

        if data.startswith("access:"):

            return await add_movie_access(
                update,
                context
            )

        # ====================================================
        # RATING
        # ====================================================

        if data.startswith("rate:"):

            parts = data.split(":")

            movie_id = int(
                parts[1]
            )

            rating = int(
                parts[2]
            )

            await rating_callback(
                query,
                movie_id,
                rating
            )

            return

        # ====================================================
        # MOVIE
        # ====================================================

        if data.startswith("movie:"):

            movie_id = int(
                data.split(
                    ":",
                    1
                )[1]
            )

            await inline_movie_callback(
                query,
                movie_id
            )

            return

        if data.startswith("getmovie:"):

            movie_id = int(
                data.split(
                    ":",
                    1
                )[1]
            )

            await get_movie_callback(
                query,
                movie_id
            )

            return

        # ====================================================
        # DELETE
        # ====================================================

        if data.startswith("delete:"):

            if not is_admin(
                query.from_user.id
            ):

                await query.answer(
                    "❌ Siz admin emassiz.",
                    show_alert=True
                )

                return

            movie_id = int(
                data.split(
                    ":",
                    1
                )[1]
            )

            await delete_movie(
                query,
                movie_id
            )

            return

        # ====================================================
        # CATEGORY
        # ====================================================

        if data.startswith("category:"):

            category = data.split(
                ":",
                1
            )[1]

            await query.answer()

            await category_movies(
                query.message,
                category
            )

            return

        # ====================================================
        # SIMPLE MENU
        # ====================================================

        if data == "popular":

            await query.answer()

            await popular_movies(
                query.message
            )

            return

        if data == "latest":

            await query.answer()

            await latest_movies(
                query.message
            )

            return

        if data == "categories":

            await query.answer()

            await categories(
                query.message
            )

            return

        if data == "status":

            await query.answer()

            await show_status(
                query.message,
                query.from_user.id
            )

            return

        await query.answer()

    except Exception as e:

        logger.exception(
            "Callback error: %s",
            e
        )

        try:

            await query.answer(
                "❌ Xatolik yuz berdi.",
                show_alert=True
            )

        except Exception:
            pass


# ============================================================
# TEXT HANDLER
# ============================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    register_user(user)

    # ========================================================
    # ADMIN STATUS QUICK COMMAND
    # ========================================================

    if is_admin(user.id):

        handled = await process_status_command(
            update
        )

        if handled:
            return

    # ========================================================
    # SUBSCRIPTION
    # ========================================================

    subscribed = await check_subscription(
        context.bot,
        user.id
    )

    if not subscribed:

        await show_subscription_required(
            update.message
        )

        return

    text = update.message.text.strip()

    # ========================================================
    # SEARCH
    # ========================================================

    if text == "🔎 Kino qidirish":

        await update.message.reply_text(
            "🔎 Kino kodini yoki nomini yuboring."
        )

        return

    # ========================================================
    # POPULAR
    # ========================================================

    if text == "🔥 Mashhur kinolar":

        await popular_movies(
            update.message
        )

        return

    # ========================================================
    # LATEST
    # ========================================================

    if text == "🆕 Yangi kinolar":

        await latest_movies(
            update.message
        )

        return

    # ========================================================
    # CATEGORIES
    # ========================================================

    if text == "🎬 Kategoriyalar":

        await categories(
            update.message
        )

        return

    # ========================================================
    # PROFILE
    # ========================================================

    if text == "👤 Profil":

        await show_status(
            update.message,
            user.id
        )

        return

    # ========================================================
    # ADMIN PANEL
    # ========================================================

    if text == "⚙️ Admin panel":

        if is_admin(user.id):

            await admin_command(
                update,
                context
            )

        else:

            await update.message.reply_text(
                "❌ Siz admin emassiz."
            )

        return

    # ========================================================
    # MOVIE CODE
    # ========================================================

    movie = get_movie_by_code(
        text
    )

    if movie:

        await send_movie(
            update.message,
            movie
        )

        return

    # ========================================================
    # MOVIE SEARCH
    # ========================================================

    movies = search_movies(
        text
    )

    if not movies:

        await update.message.reply_text(
            "❌ Kino topilmadi.\n\n"
            "🔎 Kino kodi yoki aniqroq "
            "nomini yuboring."
        )

        return

    buttons = []

    for movie in movies:

        movie_id = movie[0]
        name = movie[2]

        buttons.append(
            [
                InlineKeyboardButton(
                    f"🎬 {name}",
                    callback_data=f"movie:{movie_id}"
                )
            ]
        )

    await update.message.reply_text(
        "🔎 <b>Qidiruv natijalari:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            buttons
        )
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context
):

    logger.exception(
        "Unhandled exception: %s",
        context.error
    )


# ============================================================
# STATUS REMOVE HANDLER
# ============================================================

async def async_status_remove_user(
    update,
    context
):

    user_id_text = update.message.text.strip()

    if not user_id_text.isdigit():

        await update.message.reply_text(
            "❌ ID faqat raqamlardan iborat bo‘lishi kerak.\n\n"
            "Masalan: <code>123456789</code>",
            parse_mode="HTML"
        )

        return STATUS_USER_ID

    user_id = int(
        user_id_text
    )

    user = get_user(
        user_id
    )

    if not user:

        await update.message.reply_text(
            "❌ Bu foydalanuvchi bazada topilmadi."
        )

        return STATUS_USER_ID

    # .env adminni olib tashlab bo'lmaydi
    if user_id in ADMIN_IDS:

        await update.message.reply_text(
            "⚠️ Bu foydalanuvchi "
            "<b>ADMIN_IDS</b> ichidagi asosiy admin.\n\n"
            "Uni statusdan olib tashlab bo‘lmaydi.",
            parse_mode="HTML"
        )

        return ConversationHandler.END

    set_user_status(
        user_id,
        "USER"
    )

    await update.message.reply_text(
        "❌ <b>Status olib tashlandi!</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        "⭐ Yangi status: <b>USER</b>",
        parse_mode="HTML"
    )

    context.user_data.clear()

    return ConversationHandler.END


# ============================================================
# RENDER WEB SERVER
# ============================================================

async def health_check(request):

    return web.Response(
        text="KinoBot is running!"
    )


async def start_web_server():

    app = web.Application()

    app.router.add_get(
        "/",
        health_check
    )

    app.router.add_get(
        "/health",
        health_check
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    logger.info(
        "Render web server ishga tushdi: PORT=%s",
        PORT
    )

    while True:
        await asyncio.sleep(3600)


def run_web_server():

    asyncio.run(
        start_web_server()
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        print()
        print("❌ BOT_TOKEN topilmadi!")
        print("   Environment Variables ni tekshiring.")
        print()

        return

    if not ADMIN_IDS:

        print()
        print("⚠️ ADMIN_IDS topilmadi.")
        print("   Environment Variables dagi asosiy admin bo‘lmaydi.")
        print()

    if not REQUIRED_CHAT_IDS:

        print()
        print("❌ REQUIRED_CHAT_ID topilmadi!")
        print("   Environment Variables ni tekshiring.")
        print()

        return

    print()
    print("=" * 60)
    print("🎬 KinoBot ishga tushmoqda...")
    print("=" * 60)

    print(
        f"👑 Asosiy adminlar: {len(ADMIN_IDS)}"
    )

    print(
        f"📢 Majburiy kanal/guruhlar: "
        f"{len(CHANNELS)}"
    )

    for index, channel in enumerate(
        CHANNELS,
        start=1
    ):

        print(
            f"   {index}. "
            f"{channel['chat_id']} -> "
            f"{channel['url']}"
        )

    print("=" * 60)
    print()

    # ========================================================
    # RENDER WEB SERVER
    # ========================================================

    web_thread = threading.Thread(
        target=run_web_server,
        daemon=True
    )

    web_thread.start()

    # ========================================================
    # DATABASE
    # ========================================================

    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # ========================================================
    # ADD MOVIE CONVERSATION
    # ========================================================

    add_movie_conversation = ConversationHandler(

        entry_points=[
            CallbackQueryHandler(
                add_movie_start,
                pattern=r"^admin_add$"
            )
        ],

        states={

            MOVIE_CODE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    add_movie_code
                )
            ],

            MOVIE_FILE: [
                MessageHandler(
                    filters.VIDEO |
                    filters.Document.ALL,
                    add_movie_file
                )
            ],

            MOVIE_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    add_movie_name
                )
            ],

            MOVIE_DESCRIPTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    add_movie_description
                )
            ],

            MOVIE_CATEGORY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    add_movie_category
                )
            ],

            MOVIE_ACCESS: [
                CallbackQueryHandler(
                    add_movie_access,
                    pattern=r"^access:(FREE|VIP|PREMIUM)$"
                )
            ],
        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel_conversation
            )
        ],

        allow_reentry=True,
    )

    # ========================================================
    # STATUS GIVE CONVERSATION
    # ========================================================

    status_give_conversation = ConversationHandler(

        entry_points=[
            CallbackQueryHandler(
                status_give_start,
                pattern=r"^status_give$"
            )
        ],

        states={

            STATUS_USER_ID: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    status_user_id
                )
            ],

            STATUS_VALUE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    status_value
                )
            ],

        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel_conversation
            )
        ],

        allow_reentry=True,
    )

    # ========================================================
    # BROADCAST CONVERSATION
    # ========================================================

    broadcast_conversation = ConversationHandler(

        entry_points=[
            CallbackQueryHandler(
                broadcast_start,
                pattern=r"^admin_broadcast$"
            )
        ],

        states={

            BROADCAST_TEXT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    broadcast_send
                )
            ]

        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel_conversation
            )
        ],

        allow_reentry=True,
    )

    # ========================================================
    # STATUS REMOVE QUICK CONVERSATION
    # ========================================================

    status_remove_conversation = ConversationHandler(

        entry_points=[
            CallbackQueryHandler(
                status_remove_start,
                pattern=r"^status_remove$"
            )
        ],

        states={

            STATUS_USER_ID: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    async_status_remove_user
                )
            ]

        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel_conversation
            )
        ],

        allow_reentry=True,
    )

    # ========================================================
    # HANDLERS
    # ========================================================

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_conversation
        )
    )

    # Add movie
    application.add_handler(
        add_movie_conversation
    )

    # Status berish
    application.add_handler(
        status_give_conversation
    )

    # Status olib tashlash
    application.add_handler(
        status_remove_conversation
    )

    # Broadcast
    application.add_handler(
        broadcast_conversation
    )

    # Callback router
    application.add_handler(
        CallbackQueryHandler(
            callback_router
        )
    )

    # Text
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    application.add_error_handler(
        error_handler
    )

    print("✅ Bot ishga tushdi!")
    print("🌐 Render web server ishga tushdi!")
    print(f"🔌 PORT: {PORT}")
    print("⏳ Telegram polling kutilyapti...")
    print()

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
