#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║         🚀 AutoPost Pro — بوت النشر التلقائي المتقدم            ║
║              Powered by Telethon  |  Version 2.0                 ║
╚══════════════════════════════════════════════════════════════════╝

▸ النشر من الحساب الشخصي (Userbot) عبر Telethon
▸ تحكم كامل بالقنوات والجداول الزمنية
▸ لوحة إحصائيات متقدمة
▸ دعم متعدد الحسابات والقنوات
▸ نظام اشتراكات وأدوار

قبل التشغيل:
    1. روح https://my.telegram.org وسجل دخول
    2. API development tools → سوي تطبيق جديد
    3. احط api_id و api_hash بالأسفل أو بمتغيرات البيئة

تثبيت:
    pip install telethon --break-system-packages

تشغيل:
    python3 autopost_userbot_v2.py
"""

import asyncio
import datetime
import logging
import os
import re
import sqlite3
import uuid

from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PhoneNumberInvalidError,
    FloodWaitError,
    UsernameNotOccupiedError,
    RPCError,
)

# ═══════════════════════════════ الإعدادات ═══════════════════════════════

API_ID   = int(os.getenv("API_ID",   "36238013"))
API_HASH =      os.getenv("API_HASH", "2be03a350efb289604019e119184d2a4")
BOT_TOKEN=      os.getenv("BOT_TOKEN","8875226097:AAHUzlOBaS1OsIP0yk2QXQQodwJ-a1VcxJA")
OWNER_ID = int(os.getenv("OWNER_ID", "8631892566"))

DB_PATH            = os.getenv("DB_PATH",   "bot_data.db")
MEDIA_DIR          = os.getenv("MEDIA_DIR", "media_files")
SCHEDULER_INTERVAL = 20   # ثانية

os.makedirs(MEDIA_DIR, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s │ %(name)s │ %(levelname)s │ %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("autopost_pro")

# ═══════════════════════════════ الأدوار ═══════════════════════════════

ROLE_OWNER      = "owner"
ROLE_ADMIN      = "admin"
ROLE_SUBSCRIBER = "subscriber"
ROLE_USER       = "user"

ROLE_ICONS = {
    ROLE_OWNER:      "👑",
    ROLE_ADMIN:      "🛡️",
    ROLE_SUBSCRIBER: "💎",
    ROLE_USER:       "👤",
}

# ═══════════════════════════════ قاعدة البيانات ═══════════════════════════════

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id            INTEGER PRIMARY KEY,
            username           TEXT,
            role               TEXT    NOT NULL DEFAULT 'user',
            subscription_expiry TEXT,
            autopost_enabled   INTEGER NOT NULL DEFAULT 1,
            added_by           INTEGER,
            created_at         TEXT,
            last_seen          TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id  INTEGER NOT NULL,
            label          TEXT,
            session_string TEXT    NOT NULL,
            added_at       TEXT,
            last_used      TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER NOT NULL,
            account_id    INTEGER NOT NULL,
            channel_ref   TEXT    NOT NULL,
            title         TEXT,
            added_at      TEXT,
            FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id    INTEGER NOT NULL,
            channel_db_id    INTEGER NOT NULL,
            content_type     TEXT    NOT NULL,
            content_text     TEXT,
            media_path       TEXT,
            schedule_type    TEXT    NOT NULL,
            interval_seconds INTEGER,
            scheduled_time   TEXT,
            next_run         TEXT,
            status           TEXT    NOT NULL DEFAULT 'active',
            created_at       TEXT,
            publish_count    INTEGER NOT NULL DEFAULT 0,
            last_published   TEXT,
            FOREIGN KEY (channel_db_id) REFERENCES channels (id) ON DELETE CASCADE
        )
    """)

    # إضافة عمود publish_count لو ما موجود (ترقية قاعدة بيانات قديمة)
    try:
        cur.execute("ALTER TABLE posts ADD COLUMN publish_count INTEGER NOT NULL DEFAULT 0")
        cur.execute("ALTER TABLE posts ADD COLUMN last_published TEXT")
    except Exception:
        pass

    try:
        cur.execute("ALTER TABLE users ADD COLUMN last_seen TEXT")
    except Exception:
        pass

    try:
        cur.execute("ALTER TABLE accounts ADD COLUMN last_used TEXT")
    except Exception:
        pass

    conn.commit()
    conn.close()


def _now():
    return datetime.datetime.utcnow().isoformat()


# ─────────────── المستخدمون ───────────────

def ensure_user(user_id, username=None):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        role = ROLE_OWNER if user_id == OWNER_ID else ROLE_USER
        conn.execute(
            "INSERT INTO users (user_id, username, role, created_at, last_seen) VALUES (?,?,?,?,?)",
            (user_id, username, role, _now(), _now()),
        )
    else:
        conn.execute(
            "UPDATE users SET username=?, last_seen=? WHERE user_id=?",
            (username, _now(), user_id),
        )
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row


def get_role(user_id):
    row = get_user(user_id)
    return row["role"] if row else ROLE_USER


def set_role(user_id, role, added_by=None):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET role=?, added_by=? WHERE user_id=?",
        (role, added_by, user_id),
    )
    conn.commit()
    conn.close()


def remove_role(user_id):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET role='user', subscription_expiry=NULL WHERE user_id=?",
        (user_id,),
    )
    conn.commit()
    conn.close()


def list_by_role(role):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users WHERE role=?", (role,)).fetchall()
    conn.close()
    return rows


def all_users():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return rows


def set_subscription(user_id, days, added_by=None):
    row = get_user(user_id)
    now  = datetime.datetime.utcnow()
    base = now
    if row and row["subscription_expiry"]:
        try:
            cur_exp = datetime.datetime.fromisoformat(row["subscription_expiry"])
            if cur_exp > now:
                base = cur_exp
        except ValueError:
            pass
    new_expiry = base + datetime.timedelta(days=days)
    conn = get_conn()
    conn.execute(
        "UPDATE users SET role=?, subscription_expiry=?, added_by=? WHERE user_id=?",
        (ROLE_SUBSCRIBER, new_expiry.isoformat(), added_by, user_id),
    )
    conn.commit()
    conn.close()
    return new_expiry


def is_subscription_active(user_id):
    row = get_user(user_id)
    if not row:
        return False
    if row["role"] in (ROLE_OWNER, ROLE_ADMIN):
        return True
    if row["role"] == ROLE_SUBSCRIBER and row["subscription_expiry"]:
        try:
            return datetime.datetime.fromisoformat(row["subscription_expiry"]) > datetime.datetime.utcnow()
        except ValueError:
            return False
    return False


def has_access(user_id):
    role = get_role(user_id)
    if role in (ROLE_OWNER, ROLE_ADMIN):
        return True
    if role == ROLE_SUBSCRIBER:
        return is_subscription_active(user_id)
    return False


def set_autopost_enabled(user_id, enabled):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET autopost_enabled=? WHERE user_id=?",
        (1 if enabled else 0, user_id),
    )
    conn.commit()
    conn.close()


def get_autopost_enabled(user_id):
    row = get_user(user_id)
    return bool(row["autopost_enabled"]) if row else False


# ─────────────── الحسابات ───────────────

def add_account(owner_user_id, label, session_string):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO accounts (owner_user_id, label, session_string, added_at) VALUES (?,?,?,?)",
        (owner_user_id, label, session_string, _now()),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def list_accounts(owner_user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM accounts WHERE owner_user_id=? ORDER BY id DESC",
        (owner_user_id,),
    ).fetchall()
    conn.close()
    return rows


def get_account(account_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    conn.close()
    return row


def delete_account(account_id):
    conn = get_conn()
    conn.execute(
        "DELETE FROM posts WHERE channel_db_id IN (SELECT id FROM channels WHERE account_id=?)",
        (account_id,),
    )
    conn.execute("DELETE FROM channels WHERE account_id=?", (account_id,))
    conn.execute("DELETE FROM accounts WHERE id=?",         (account_id,))
    conn.commit()
    conn.close()


def touch_account(account_id):
    conn = get_conn()
    conn.execute("UPDATE accounts SET last_used=? WHERE id=?", (_now(), account_id))
    conn.commit()
    conn.close()


# ─────────────── القنوات ───────────────

def add_channel(owner_user_id, account_id, channel_ref, title):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO channels (owner_user_id, account_id, channel_ref, title, added_at) VALUES (?,?,?,?,?)",
        (owner_user_id, account_id, channel_ref, title, _now()),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def list_channels(owner_user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM channels WHERE owner_user_id=? ORDER BY id DESC",
        (owner_user_id,),
    ).fetchall()
    conn.close()
    return rows


def get_channel(channel_db_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM channels WHERE id=?", (channel_db_id,)).fetchone()
    conn.close()
    return row


def delete_channel(channel_db_id):
    conn = get_conn()
    conn.execute("DELETE FROM posts WHERE channel_db_id=?", (channel_db_id,))
    conn.execute("DELETE FROM channels WHERE id=?",          (channel_db_id,))
    conn.commit()
    conn.close()


# ─────────────── المنشورات ───────────────

def add_post(owner_user_id, channel_db_id, content_type, content_text, media_path,
             schedule_type, interval_seconds, scheduled_time, next_run):
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO posts
           (owner_user_id, channel_db_id, content_type, content_text, media_path,
            schedule_type, interval_seconds, scheduled_time, next_run, status, created_at, publish_count)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (owner_user_id, channel_db_id, content_type, content_text, media_path,
         schedule_type, interval_seconds, scheduled_time, next_run, "active", _now(), 0),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def list_posts(owner_user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM posts WHERE owner_user_id=? ORDER BY id DESC",
        (owner_user_id,),
    ).fetchall()
    conn.close()
    return rows


def get_post(post_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    conn.close()
    return row


def delete_post(post_id):
    conn = get_conn()
    conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
    conn.commit()
    conn.close()


def toggle_post_status(post_id):
    row = get_post(post_id)
    if not row:
        return None
    new_status = "paused" if row["status"] == "active" else "active"
    conn = get_conn()
    conn.execute("UPDATE posts SET status=? WHERE id=?", (new_status, post_id))
    conn.commit()
    conn.close()
    return new_status


def update_next_run(post_id, next_run_iso):
    conn = get_conn()
    conn.execute("UPDATE posts SET next_run=? WHERE id=?", (next_run_iso, post_id))
    conn.commit()
    conn.close()


def mark_post_done(post_id):
    conn = get_conn()
    conn.execute("UPDATE posts SET status='done' WHERE id=?", (post_id,))
    conn.commit()
    conn.close()


def increment_publish_count(post_id):
    conn = get_conn()
    conn.execute(
        "UPDATE posts SET publish_count = publish_count + 1, last_published=? WHERE id=?",
        (_now(), post_id),
    )
    conn.commit()
    conn.close()


def get_due_posts():
    now_iso = _now()
    conn = get_conn()
    rows = conn.execute(
        """SELECT posts.*, channels.channel_ref, channels.account_id
           FROM posts JOIN channels ON posts.channel_db_id = channels.id
           WHERE posts.status='active'
             AND posts.next_run IS NOT NULL
             AND posts.next_run <= ?""",
        (now_iso,),
    ).fetchall()
    conn.close()
    return rows


def global_stats():
    """إحصائيات عامة للمالك"""
    conn = get_conn()
    total_users    = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_accounts = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    total_channels = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
    total_posts    = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    active_posts   = conn.execute("SELECT COUNT(*) FROM posts WHERE status='active'").fetchone()[0]
    total_sent     = conn.execute("SELECT SUM(publish_count) FROM posts").fetchone()[0] or 0
    conn.close()
    return {
        "users":    total_users,
        "accounts": total_accounts,
        "channels": total_channels,
        "posts":    total_posts,
        "active":   active_posts,
        "sent":     total_sent,
    }


# ═══════════════════════════════ Telethon ═══════════════════════════════

bot = TelegramClient("control_bot_session", API_ID, API_HASH)

active_userbots: dict = {}   # account_id → TelegramClient
STATE: dict = {}              # user_id → dict


def clear_state(user_id):
    STATE.pop(user_id, None)


async def get_userbot_client(account_row):
    acc_id = account_row["id"]
    client = active_userbots.get(acc_id)
    if client and client.is_connected():
        return client
    client = TelegramClient(StringSession(account_row["session_string"]), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("جلسة هذا الحساب منتهية أو غير صالحة")
    active_userbots[acc_id] = client
    touch_account(acc_id)
    return client


async def reconnect_all_accounts():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM accounts").fetchall()
    conn.close()
    for row in rows:
        try:
            await get_userbot_client(row)
            logger.info(f"✅ متصل بالحساب #{row['id']} ({row['label']})")
        except Exception as e:
            logger.warning(f"⚠️  فشل الاتصال بالحساب #{row['id']}: {e}")


# ═══════════════════════════════ الأزرار (تصميم متطور) ═══════════════════════════════

def main_menu_buttons(role):
    """لوحة القائمة الرئيسية — صفان متوازيان"""
    rows = [
        [
            Button.inline("👤 الحسابات",  "menu_accounts"),
            Button.inline("📡 القنوات",   "menu_channels"),
        ],
        [
            Button.inline("📝 المنشورات", "menu_posts"),
            Button.inline("⚙️ التحكم",    "menu_control"),
        ],
        [
            Button.inline("📊 الإحصائيات", "menu_stats"),
        ],
    ]
    if role in (ROLE_OWNER, ROLE_ADMIN):
        rows.append([Button.inline("🛡️ المشرفون", "menu_admins")])
    if role == ROLE_OWNER:
        rows.append([
            Button.inline("💎 الاشتراكات", "menu_subs"),
            Button.inline("🌐 لوحة المالك", "menu_owner"),
        ])
    return rows


def back_button(target="menu_main"):
    return [[Button.inline("◀️ رجوع", target)]]


def cancel_button():
    return [[Button.inline("✖️ إلغاء", "menu_main")]]


def confirm_buttons(yes_data, no_data="menu_main"):
    return [
        [
            Button.inline("✅ تأكيد", yes_data),
            Button.inline("✖️ إلغاء", no_data),
        ]
    ]


# ═══════════════════════════════ /start والقائمة الرئيسية ═══════════════════════════════

WELCOME_TEXT = (
    "✨ *أهلاً بك في AutoPost Pro*\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "🤖 بوت النشر التلقائي المتقدم\n\n"
    "اختر ما تريد من القائمة أدناه 👇"
)

OWNER_USERNAME = "sssseessse"   # يوزرنيم المالك للتواصل

def guest_menu_buttons():
    """أزرار للزوار — يشوفونها بس ما يقدرون يستخدمونها"""
    return [
        [
            Button.inline("👤 الحسابات",   "guest_locked"),
            Button.inline("📡 القنوات",    "guest_locked"),
        ],
        [
            Button.inline("📝 المنشورات",  "guest_locked"),
            Button.inline("⚙️ التحكم",     "guest_locked"),
        ],
        [Button.inline("📊 الإحصائيات",   "guest_locked")],
        [Button.url(f"💬 اشترك الآن — تواصل مع المالك", f"https://t.me/{OWNER_USERNAME}")],
    ]


@bot.on(events.NewMessage(pattern="/start"))
async def cmd_start(event):
    user = await event.get_sender()
    ensure_user(user.id, user.username)
    clear_state(user.id)

    if not has_access(user.id):
        # يشوف الواجهة كاملة بس مقفولة
        await event.respond(
            "✨ *أهلاً بك في AutoPost Pro*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🤖 بوت النشر التلقائي المتقدم\n\n"
            "👇 شاهد ما يقدمه البوت\n"
            "🔒 _للاستخدام راسل المالك للاشتراك_",
            buttons=guest_menu_buttons(),
        )
        return

    role = get_role(user.id)
    icon = ROLE_ICONS.get(role, "👤")
    await event.respond(
        f"{WELCOME_TEXT}\n\n{icon} دورك: `{role}`",
        buttons=main_menu_buttons(role),
    )


@bot.on(events.NewMessage(pattern="/stats"))
async def cmd_stats(event):
    user = await event.get_sender()
    ensure_user(user.id, user.username)
    if get_role(user.id) != ROLE_OWNER:
        return
    s = global_stats()
    await event.respond(
        f"📊 *إحصائيات النظام*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 المستخدمون : `{s['users']}`\n"
        f"👤 الحسابات   : `{s['accounts']}`\n"
        f"📡 القنوات    : `{s['channels']}`\n"
        f"📝 المنشورات  : `{s['posts']}` (🟢 نشط: {s['active']})\n"
        f"📤 إجمالي الإرسال: `{s['sent']}`"
    )


async def show_main_menu(event):
    user_id = event.sender_id
    role = get_role(user_id)
    await event.edit(WELCOME_TEXT, buttons=main_menu_buttons(role))


async def guest_locked(event):
    """لما الزائر يضغط أي زر مقفول"""
    await event.answer(
        f"🔒 هذه الميزة تحتاج اشتراك!\nراسل @{OWNER_USERNAME} للاشتراك.",
        alert=True,
    )


# ═══════════════════════════════ إدارة الحسابات ═══════════════════════════════

async def menu_accounts(event):
    user_id  = event.sender_id
    accounts = list_accounts(user_id)

    rows = [
        [
            Button.inline("📱 إضافة برقم الهاتف",   "acc_add_phone"),
            Button.inline("🔑 إضافة بـ Session",     "acc_add_session"),
        ],
    ]
    for acc in accounts:
        rows.append([
            Button.inline(f"✏️ {acc['label']}", f"acc_view:{acc['id']}"),
            Button.inline("🗑️",                 f"acc_delete_confirm:{acc['id']}"),
        ])
    rows += back_button()

    lines = ["👤 *إدارة الحسابات*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
    if accounts:
        for a in accounts:
            status = "🟢" if a["id"] in active_userbots else "🔴"
            lines.append(f"{status} `{a['label']}` — ID: `{a['id']}`")
    else:
        lines.append("_لا توجد حسابات مضافة بعد._")

    await event.edit("\n".join(lines), buttons=rows)


async def acc_view(event):
    account_id  = int(event.data.decode().split(":")[1])
    account_row = get_account(account_id)
    if not account_row:
        await event.answer("الحساب غير موجود!", alert=True)
        return
    connected = account_id in active_userbots and active_userbots[account_id].is_connected()
    text = (
        f"👤 *تفاصيل الحساب*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ الاسم     : `{account_row['label']}`\n"
        f"🔢 المعرف    : `{account_row['id']}`\n"
        f"📅 أُضيف في  : `{account_row['added_at'][:10] if account_row['added_at'] else 'غير معروف'}`\n"
        f"🔗 الحالة    : {'🟢 متصل' if connected else '🔴 غير متصل'}"
    )
    rows = [
        [Button.inline("🗑️ حذف الحساب", f"acc_delete_confirm:{account_id}")],
    ] + back_button("menu_accounts")
    await event.edit(text, buttons=rows)


async def acc_delete_confirm(event):
    account_id = int(event.data.decode().split(":")[1])
    acc = get_account(account_id)
    if not acc:
        await event.answer("الحساب غير موجود!", alert=True)
        return
    await event.edit(
        f"⚠️ *تأكيد الحذف*\n\nهل تريد حذف الحساب:\n`{acc['label']}`؟\n\n"
        "سيتم حذف جميع القنوات والمنشورات المرتبطة به.",
        buttons=confirm_buttons(f"acc_delete:{account_id}", "menu_accounts"),
    )


async def acc_add_phone_start(event):
    user_id = event.sender_id
    if not API_ID or not API_HASH:
        await event.answer("لازم تحط API_ID و API_HASH أولاً!", alert=True)
        return
    STATE[user_id] = {"action": "waiting_phone"}
    await event.edit(
        "📱 *إضافة حساب برقم الهاتف*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل رقم هاتفك مع رمز الدولة:\n\n"
        "_مثال: +9647701234567_",
        buttons=cancel_button(),
    )


async def acc_add_session_start(event):
    user_id = event.sender_id
    if not API_ID or not API_HASH:
        await event.answer("لازم تحط API_ID و API_HASH أولاً!", alert=True)
        return
    STATE[user_id] = {"action": "waiting_session_string"}
    await event.edit(
        "🔑 *إضافة حساب بـ Session String*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل الـ Session String للحساب.\n\n"
        "⚠️ _هذا النص يعادل كلمة سر حسابك. لا تشاركه مع أحد._",
        buttons=cancel_button(),
    )


async def acc_delete(event):
    account_id = int(event.data.decode().split(":")[1])
    client = active_userbots.pop(account_id, None)
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
    delete_account(account_id)
    await event.answer("✅ تم حذف الحساب")
    await menu_accounts(event)


# ─── استقبال رقم الهاتف ───

async def handle_waiting_phone(event, st):
    phone   = event.raw_text.strip()
    user_id = event.sender_id

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
    except PhoneNumberInvalidError:
        await event.respond(
            "❌ *رقم الهاتف غير صحيح*\n\nتأكد من الصيغة الدولية وحاول مجدداً.",
            buttons=cancel_button(),
        )
        await client.disconnect()
        return
    except FloodWaitError as e:
        await event.respond(
            f"⏳ *انتظر {e.seconds} ثانية* ثم حاول مجدداً.",
        )
        await client.disconnect()
        clear_state(user_id)
        return

    STATE[user_id] = {
        "action":          "waiting_code",
        "phone":           phone,
        "phone_code_hash": sent.phone_code_hash,
        "temp_client":     client,
    }
    await event.respond(
        "📩 *تم إرسال كود التفعيل*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل الكود الذي وصلك في تلجرام.\n\n"
        "💡 _يمكنك إرساله بمسافات أو بدونها — مثلاً: `1 2 3 4 5` أو `12345`_",
        buttons=cancel_button(),
    )


async def handle_waiting_code(event, st):
    user_id = event.sender_id
    # ✅ الإصلاح الرئيسي: نزيل كل الفراغات والشرطات من الكود
    raw  = event.raw_text.strip()
    code = re.sub(r"[\s\-\.\,]+", "", raw)   # يقبل: "8 3 3 8 6" أو "8-3-3-8-6" أو "83386"

    client = st["temp_client"]
    try:
        await client.sign_in(
            phone=st["phone"],
            code=code,
            phone_code_hash=st["phone_code_hash"],
        )
    except SessionPasswordNeededError:
        STATE[user_id]["action"] = "waiting_password"
        await event.respond(
            "🔐 *هذا الحساب محمي بالتحقق بخطوتين (2FA)*\n\nأرسل كلمة المرور.",
            buttons=cancel_button(),
        )
        return
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        await event.respond(
            "❌ *الكود غير صحيح أو منتهي الصلاحية*\n\nأرسل الكود مجدداً أو اضغط إلغاء.",
            buttons=cancel_button(),
        )
        return
    except FloodWaitError as e:
        await event.respond(f"⏳ انتظر `{e.seconds}` ثانية ثم حاول.")
        clear_state(user_id)
        await client.disconnect()
        return

    await _finalize_account_login(event, client, st["phone"])


async def handle_waiting_password(event, st):
    user_id  = event.sender_id
    password = event.raw_text.strip()
    client   = st["temp_client"]
    try:
        await client.sign_in(password=password)
    except Exception as e:
        await event.respond(
            f"❌ *كلمة المرور غير صحيحة*\n\n`{e}`\n\nحاول مجدداً أو اضغط إلغاء.",
            buttons=cancel_button(),
        )
        return
    await _finalize_account_login(event, client, st["phone"])


async def _finalize_account_login(event, client, phone):
    user_id = event.sender_id
    me      = await client.get_me()
    session = client.session.save()
    label   = f"{me.first_name or ''} ({phone})".strip()

    account_id = add_account(user_id, label, session)
    active_userbots[account_id] = client
    clear_state(user_id)

    role = get_role(user_id)
    await event.respond(
        f"✅ *تم تسجيل الدخول بنجاح!*\n\n"
        f"👤 الحساب: `{label}`\n"
        f"🔢 المعرف: `{account_id}`",
        buttons=main_menu_buttons(role),
    )


# ─── استقبال Session String ───

async def handle_waiting_session_string(event, st):
    user_id     = event.sender_id
    session_str = event.raw_text.strip()

    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            await event.respond(
                "❌ *الـ Session String غير صالح أو منتهي*\n\nحاول مجدداً.",
                buttons=cancel_button(),
            )
            await client.disconnect()
            return
        me = await client.get_me()
    except Exception as e:
        await event.respond(f"❌ خطأ: `{e}`", buttons=cancel_button())
        return

    label      = f"{me.first_name or ''} (@{me.username or me.id})".strip()
    account_id = add_account(user_id, label, session_str)
    active_userbots[account_id] = client
    clear_state(user_id)

    role = get_role(user_id)
    await event.respond(
        f"✅ *تم ربط الحساب بنجاح!*\n\n👤 `{label}`",
        buttons=main_menu_buttons(role),
    )


# ═══════════════════════════════ إدارة القنوات ═══════════════════════════════

async def menu_channels(event):
    user_id  = event.sender_id
    accounts = list_accounts(user_id)
    if not accounts:
        await event.edit(
            "⚠️ *لا توجد حسابات*\n\nأضف حساباً أولاً من قسم الحسابات.",
            buttons=back_button(),
        )
        return

    channels = list_channels(user_id)
    rows     = [[Button.inline("➕ إضافة قناة", "channel_add_pick_account")]]
    for ch in channels:
        rows.append([
            Button.inline(f"📡 {ch['title'] or ch['channel_ref']}", f"channel_view:{ch['id']}"),
            Button.inline("🗑️", f"channel_delete_confirm:{ch['id']}"),
        ])
    rows += back_button()

    lines = ["📡 *إدارة القنوات*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
    if channels:
        for c in channels:
            lines.append(f"• `{c['title'] or c['channel_ref']}` — ID: `{c['id']}`")
    else:
        lines.append("_لا توجد قنوات مضافة بعد._")

    await event.edit("\n".join(lines), buttons=rows)


async def channel_view(event):
    channel_id  = int(event.data.decode().split(":")[1])
    ch          = get_channel(channel_id)
    if not ch:
        await event.answer("القناة غير موجودة!", alert=True)
        return
    posts = [p for p in list_posts(event.sender_id) if p["channel_db_id"] == channel_id]
    text  = (
        f"📡 *تفاصيل القناة*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ الاسم  : `{ch['title']}`\n"
        f"🔗 المعرف : `{ch['channel_ref']}`\n"
        f"📝 المنشورات: `{len(posts)}`\n"
        f"📅 أُضيف  : `{ch['added_at'][:10] if ch['added_at'] else '—'}`"
    )
    rows = [
        [Button.inline("🗑️ حذف القناة", f"channel_delete_confirm:{channel_id}")],
    ] + back_button("menu_channels")
    await event.edit(text, buttons=rows)


async def channel_add_pick_account(event):
    user_id  = event.sender_id
    accounts = list_accounts(user_id)
    rows     = [[Button.inline(f"👤 {a['label']}", f"channel_use_account:{a['id']}")] for a in accounts]
    rows    += cancel_button()
    await event.edit("اختر الحساب الذي سينشر في القناة:", buttons=rows)


async def channel_use_account(event):
    user_id    = event.sender_id
    account_id = int(event.data.decode().split(":")[1])
    STATE[user_id] = {"action": "waiting_channel_ref", "account_id": account_id}
    await event.edit(
        "📡 *إضافة قناة*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل معرف القناة أو رابطها:\n\n"
        "_مثال: @my\\_channel أو -100123456789_\n\n"
        "⚠️ تأكد أن الحساب المختار عضو أو مشرف في القناة.",
        buttons=cancel_button(),
    )


async def handle_waiting_channel_ref(event, st):
    user_id     = event.sender_id
    channel_ref = event.raw_text.strip()
    account_row = get_account(st["account_id"])

    try:
        client = await get_userbot_client(account_row)
        entity = await client.get_entity(channel_ref)
        title  = getattr(entity, "title", None) or getattr(entity, "username", None) or channel_ref
    except (UsernameNotOccupiedError, ValueError):
        await event.respond(
            "❌ *لم يتم العثور على القناة*\n\nتأكد أن الحساب عضو فيها وحاول مجدداً.",
            buttons=cancel_button(),
        )
        return
    except RPCError as e:
        await event.respond(f"❌ خطأ: `{e}`", buttons=cancel_button())
        return

    add_channel(user_id, st["account_id"], channel_ref, title)
    clear_state(user_id)
    role = get_role(user_id)
    await event.respond(
        f"✅ *تمت إضافة القناة بنجاح!*\n\n📡 `{title}`",
        buttons=main_menu_buttons(role),
    )


async def channel_delete_confirm(event):
    channel_id = int(event.data.decode().split(":")[1])
    ch = get_channel(channel_id)
    if not ch:
        await event.answer("القناة غير موجودة!", alert=True)
        return
    await event.edit(
        f"⚠️ *تأكيد الحذف*\n\nهل تريد حذف القناة:\n`{ch['title'] or ch['channel_ref']}`؟\n\n"
        "سيتم حذف جميع المنشورات المرتبطة بها.",
        buttons=confirm_buttons(f"channel_delete:{channel_id}", "menu_channels"),
    )


async def channel_delete(event):
    channel_db_id = int(event.data.decode().split(":")[1])
    delete_channel(channel_db_id)
    await event.answer("✅ تم الحذف")
    await menu_channels(event)


# ═══════════════════════════════ إدارة المنشورات ═══════════════════════════════

def parse_interval_to_seconds(text):
    text = text.strip().lower()
    if text.isdigit():
        return int(text)
    m = re.fullmatch(r"(\d+)\s*(s|m|h|d)", text)
    if not m:
        return None
    value, unit = int(m.group(1)), m.group(2)
    return value * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def parse_datetime(text):
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M"):
        try:
            return datetime.datetime.strptime(text.strip(), fmt)
        except ValueError:
            pass
    return None


async def menu_posts(event):
    rows = [
        [
            Button.inline("➕ إضافة منشور",   "post_add_pick_channel"),
            Button.inline("📋 عرض المنشورات", "posts_list"),
        ],
        [Button.inline("⚡ نشر فوري",         "post_instant_pick_channel")],
    ] + back_button()
    await event.edit(
        "📝 *إدارة المنشورات*\n━━━━━━━━━━━━━━━━━━━━━━━━",
        buttons=rows,
    )


async def post_add_pick_channel(event):
    user_id  = event.sender_id
    channels = list_channels(user_id)
    if not channels:
        await event.edit(
            "⚠️ *لا توجد قنوات*\n\nأضف قناة أولاً.",
            buttons=back_button("menu_posts"),
        )
        return
    rows = [[Button.inline(f"📡 {c['title'] or c['channel_ref']}", f"post_use_channel:{c['id']}")] for c in channels]
    rows += cancel_button()
    await event.edit("اختر القناة التي تريد النشر فيها:", buttons=rows)


# النشر الفوري
async def post_instant_pick_channel(event):
    user_id  = event.sender_id
    channels = list_channels(user_id)
    if not channels:
        await event.edit("⚠️ لا توجد قنوات.", buttons=back_button("menu_posts"))
        return
    rows = [[Button.inline(f"📡 {c['title'] or c['channel_ref']}", f"instant_use_channel:{c['id']}")] for c in channels]
    rows += cancel_button()
    await event.edit(
        "⚡ *النشر الفوري*\n\nاختر القناة:",
        buttons=rows,
    )


async def instant_use_channel(event):
    user_id       = event.sender_id
    channel_db_id = int(event.data.decode().split(":")[1])
    STATE[user_id] = {"action": "waiting_instant_content", "channel_db_id": channel_db_id}
    await event.edit(
        "⚡ *النشر الفوري*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل المحتوى الآن (نص أو صورة أو فيديو).\n"
        "سيتم نشره فوراً في القناة.",
        buttons=cancel_button(),
    )


async def handle_waiting_instant_content(event, st):
    user_id = event.sender_id
    channel = get_channel(st["channel_db_id"])
    if not channel:
        await event.respond("❌ القناة غير موجودة.", buttons=cancel_button())
        clear_state(user_id)
        return

    conn = get_conn()
    account_row = conn.execute(
        "SELECT * FROM accounts WHERE id=?", (channel["account_id"],)
    ).fetchone()
    conn.close()

    try:
        client = await get_userbot_client(account_row)
        target = channel["channel_ref"]

        if event.message.media:
            media_path = await event.download_media(
                file=os.path.join(MEDIA_DIR, uuid.uuid4().hex)
            )
            await client.send_file(target, media_path, caption=event.message.text or None)
        elif event.raw_text:
            await client.send_message(target, event.raw_text)
        else:
            await event.respond("❌ نوع المحتوى غير مدعوم.", buttons=cancel_button())
            return
    except Exception as e:
        await event.respond(f"❌ فشل النشر: `{e}`", buttons=cancel_button())
        clear_state(user_id)
        return

    clear_state(user_id)
    role = get_role(user_id)
    await event.respond(
        f"✅ *تم النشر الفوري بنجاح!*\n📡 في: `{channel['title'] or target}`",
        buttons=main_menu_buttons(role),
    )


async def post_use_channel(event):
    user_id       = event.sender_id
    channel_db_id = int(event.data.decode().split(":")[1])
    STATE[user_id] = {"action": "waiting_post_content", "channel_db_id": channel_db_id}
    await event.edit(
        "📝 *إضافة منشور جديد*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل محتوى المنشور:\n\n"
        "• نص عادي\n"
        "• صورة (مع تعليق اختياري)\n"
        "• فيديو (مع تعليق اختياري)\n"
        "• ملف",
        buttons=cancel_button(),
    )


async def handle_waiting_post_content(event, st):
    user_id    = event.sender_id
    media_path = None
    content_type  = "text"
    content_text  = event.raw_text

    if event.message.media:
        filename   = uuid.uuid4().hex
        media_path = await event.download_media(file=os.path.join(MEDIA_DIR, filename))
        content_text = event.message.text or None
        if   event.photo:   content_type = "photo"
        elif event.video:   content_type = "video"
        else:               content_type = "document"
    elif not event.raw_text:
        await event.respond("❌ نوع المحتوى غير مدعوم. أرسل نصاً أو صورة.")
        return

    STATE[user_id].update({
        "content_type": content_type,
        "content_text": content_text,
        "media_path":   media_path,
        "action":       "waiting_schedule_choice",
    })

    rows = [
        [Button.inline("🔁 نشر متكرر (كل فترة)", "sched_interval")],
        [Button.inline("📅 نشر مرة واحدة (وقت محدد)", "sched_once")],
    ] + cancel_button()
    await event.respond(
        "🗓️ *اختر نوع الجدولة:*",
        buttons=rows,
    )


async def sched_interval(event):
    user_id = event.sender_id
    STATE[user_id]["action"] = "waiting_interval"
    await event.edit(
        "🔁 *الجدولة المتكررة*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل الفاصل الزمني:\n\n"
        "• `30s` = كل 30 ثانية\n"
        "• `10m` = كل 10 دقائق\n"
        "• `2h`  = كل ساعتين\n"
        "• `1d`  = كل يوم\n\n"
        "_الحد الأدنى: 10 ثواني_",
        buttons=cancel_button(),
    )


async def sched_once(event):
    user_id = event.sender_id
    STATE[user_id]["action"] = "waiting_datetime"
    await event.edit(
        "📅 *النشر مرة واحدة*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل التاريخ والوقت (UTC):\n\n"
        "• `2026-07-20 18:30`\n"
        "• `20/07/2026 18:30`\n"
        "• `20-07-2026 18:30`",
        buttons=cancel_button(),
    )


async def handle_waiting_interval(event, st):
    seconds = parse_interval_to_seconds(event.raw_text)
    if not seconds or seconds < 10:
        await event.respond(
            "❌ *صيغة غير صحيحة* أو الفاصل أقل من 10 ثواني.\n\nحاول مجدداً.",
            buttons=cancel_button(),
        )
        return
    next_run = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
    await _finalize_post(event, st, "interval", seconds, None, next_run)


async def handle_waiting_datetime(event, st):
    dt = parse_datetime(event.raw_text)
    if not dt:
        await event.respond(
            "❌ *صيغة التاريخ غير صحيحة*\n\nاستخدم: `YYYY-MM-DD HH:MM`",
            buttons=cancel_button(),
        )
        return
    if dt <= datetime.datetime.utcnow():
        await event.respond("❌ الوقت يجب أن يكون في المستقبل.", buttons=cancel_button())
        return
    await _finalize_post(event, st, "once", None, dt.isoformat(), dt)


async def _finalize_post(event, st, schedule_type, interval_seconds, scheduled_time, next_run):
    user_id = event.sender_id
    post_id = add_post(
        owner_user_id    = user_id,
        channel_db_id    = st["channel_db_id"],
        content_type     = st["content_type"],
        content_text     = st.get("content_text"),
        media_path       = st.get("media_path"),
        schedule_type    = schedule_type,
        interval_seconds = interval_seconds,
        scheduled_time   = scheduled_time,
        next_run         = next_run.isoformat(),
    )
    clear_state(user_id)
    role = get_role(user_id)

    if schedule_type == "interval":
        sched_str = f"كل `{interval_seconds}` ثانية"
    else:
        sched_str = f"بتاريخ `{next_run.strftime('%Y-%m-%d %H:%M')} UTC`"

    await event.respond(
        f"✅ *تمت إضافة المنشور!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 المعرف : `#{post_id}`\n"
        f"📝 النوع  : `{st['content_type']}`\n"
        f"🗓️ الجدولة: {sched_str}",
        buttons=main_menu_buttons(role),
    )


async def posts_list(event):
    user_id = event.sender_id
    posts   = list_posts(user_id)
    if not posts:
        await event.edit(
            "📋 *لا توجد منشورات*\n\nاضغط ➕ لإضافة منشور جديد.",
            buttons=back_button("menu_posts"),
        )
        return

    rows = []
    for p in posts:
        if   p["status"] == "active": icon = "🟢"
        elif p["status"] == "paused": icon = "⏸️"
        else:                         icon = "✅"
        label = f"{icon} #{p['id']} — {p['content_type']}"
        rows.append([Button.inline(label, f"post_view:{p['id']}")])
    rows += back_button("menu_posts")
    await event.edit(
        f"📋 *المنشورات* ({len(posts)} إجمالاً):",
        buttons=rows,
    )


def _post_detail_text(post):
    channel    = get_channel(post["channel_db_id"])
    ch_label   = channel["title"] if channel else "غير معروف"

    if post["schedule_type"] == "interval":
        secs = post["interval_seconds"] or 0
        if   secs >= 86400: sched = f"كل {secs//86400} يوم"
        elif secs >= 3600:  sched = f"كل {secs//3600} ساعة"
        elif secs >= 60:    sched = f"كل {secs//60} دقيقة"
        else:               sched = f"كل {secs} ثانية"
    else:
        sched = f"مرة واحدة — {post['scheduled_time']}"

    status_icons = {"active": "🟢 نشط", "paused": "⏸️ موقوف", "done": "✅ منتهي"}
    count        = post["publish_count"] if "publish_count" in post.keys() else 0

    return (
        f"📝 *تفاصيل المنشور #{post['id']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 القناة    : `{ch_label}`\n"
        f"🗂️ النوع     : `{post['content_type']}`\n"
        f"🗓️ الجدولة  : {sched}\n"
        f"📊 الحالة   : {status_icons.get(post['status'], post['status'])}\n"
        f"📤 نُشر مرات: `{count}`\n"
        f"⏰ التالي   : `{post['next_run'] or '—'}`"
    )


async def post_view(event):
    post_id = int(event.data.decode().split(":")[1])
    post    = get_post(post_id)
    if not post:
        await event.edit("❌ هذا المنشور محذوف.", buttons=back_button("menu_posts"))
        return
    toggle_label = "⏸️ إيقاف" if post["status"] == "active" else "▶️ تشغيل"
    rows = [
        [
            Button.inline(toggle_label,          f"post_toggle:{post_id}"),
            Button.inline("🗑️ حذف",              f"post_delete_confirm:{post_id}"),
        ],
    ] + back_button("posts_list")
    await event.edit(_post_detail_text(post), buttons=rows)


async def post_toggle(event):
    post_id    = int(event.data.decode().split(":")[1])
    post       = get_post(post_id)
    new_status = toggle_post_status(post_id)
    if new_status == "active" and post and post["schedule_type"] == "interval":
        next_run = datetime.datetime.utcnow() + datetime.timedelta(seconds=post["interval_seconds"])
        update_next_run(post_id, next_run.isoformat())
    await event.answer(f"{'▶️ تم التشغيل' if new_status == 'active' else '⏸️ تم الإيقاف'}")
    post         = get_post(post_id)
    toggle_label = "⏸️ إيقاف" if post["status"] == "active" else "▶️ تشغيل"
    rows = [
        [
            Button.inline(toggle_label,     f"post_toggle:{post_id}"),
            Button.inline("🗑️ حذف",        f"post_delete_confirm:{post_id}"),
        ],
    ] + back_button("posts_list")
    await event.edit(_post_detail_text(post), buttons=rows)


async def post_delete_confirm(event):
    post_id = int(event.data.decode().split(":")[1])
    post    = get_post(post_id)
    if not post:
        await event.answer("المنشور غير موجود!", alert=True)
        return
    await event.edit(
        f"⚠️ *تأكيد حذف المنشور #{post_id}*\n\nهل أنت متأكد؟",
        buttons=confirm_buttons(f"post_delete:{post_id}", "posts_list"),
    )


async def post_delete(event):
    post_id = int(event.data.decode().split(":")[1])
    delete_post(post_id)
    await event.answer("✅ تم الحذف")
    await posts_list(event)


# ═══════════════════════════════ الإحصائيات ═══════════════════════════════

async def menu_stats(event):
    user_id = event.sender_id
    posts   = list_posts(user_id)
    chans   = list_channels(user_id)
    accs    = list_accounts(user_id)

    active_n = sum(1 for p in posts if p["status"] == "active")
    paused_n = sum(1 for p in posts if p["status"] == "paused")
    done_n   = sum(1 for p in posts if p["status"] == "done")
    total_sent = sum((p["publish_count"] if "publish_count" in p.keys() else 0) for p in posts)

    sub_row = get_user(user_id)
    if sub_row and sub_row["subscription_expiry"]:
        try:
            exp = datetime.datetime.fromisoformat(sub_row["subscription_expiry"])
            remaining = (exp - datetime.datetime.utcnow()).days
            sub_info = f"ينتهي بعد `{remaining}` يوم"
        except Exception:
            sub_info = "غير محدد"
    else:
        sub_info = "—"

    text = (
        f"📊 *لوحة الإحصائيات*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 *حسابك*\n"
        f"   🔑 الحسابات المضافة: `{len(accs)}`\n"
        f"   📡 القنوات: `{len(chans)}`\n"
        f"   💎 الاشتراك: {sub_info}\n\n"
        f"📝 *المنشورات*\n"
        f"   🟢 نشطة  : `{active_n}`\n"
        f"   ⏸️ موقوفة : `{paused_n}`\n"
        f"   ✅ منتهية : `{done_n}`\n"
        f"   📤 إجمالي الإرسال: `{total_sent}`"
    )

    rows = back_button()
    # إضافة إحصائيات المالك
    if get_role(user_id) == ROLE_OWNER:
        rows = [[Button.inline("🌐 إحصائيات النظام الكاملة", "owner_global_stats")]] + rows

    await event.edit(text, buttons=rows)


# ═══════════════════════════════ التحكم بالنشر ═══════════════════════════════

async def menu_control(event):
    user_id = event.sender_id
    enabled = get_autopost_enabled(user_id)
    status  = "🟢 يعمل" if enabled else "🔴 متوقف"
    toggle  = Button.inline(
        "⏹️ إيقاف الكل" if enabled else "▶️ تشغيل الكل",
        "control_stop"   if enabled else "control_start",
    )
    rows = [
        [toggle],
        [Button.inline("📊 الحالة التفصيلية", "control_status")],
    ] + back_button()
    await event.edit(
        f"⚙️ *التحكم بالنشر*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"الحالة الحالية: {status}",
        buttons=rows,
    )


async def control_start(event):
    set_autopost_enabled(event.sender_id, True)
    await event.answer("▶️ تم تشغيل النشر التلقائي")
    await menu_control(event)


async def control_stop(event):
    set_autopost_enabled(event.sender_id, False)
    await event.answer("⏹️ تم إيقاف النشر التلقائي")
    await menu_control(event)


async def control_status(event):
    user_id = event.sender_id
    posts   = list_posts(user_id)
    active_n = sum(1 for p in posts if p["status"] == "active")
    paused_n = sum(1 for p in posts if p["status"] == "paused")
    done_n   = sum(1 for p in posts if p["status"] == "done")
    enabled  = get_autopost_enabled(user_id)
    text = (
        f"📊 *الحالة التفصيلية*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"النشر التلقائي: {'🟢 يعمل' if enabled else '🔴 متوقف'}\n\n"
        f"📝 إجمالي المنشورات: `{len(posts)}`\n"
        f"🟢 نشطة   : `{active_n}`\n"
        f"⏸️ موقوفة : `{paused_n}`\n"
        f"✅ منتهية : `{done_n}`"
    )
    await event.edit(text, buttons=back_button("menu_control"))


# ═══════════════════════════════ لوحة المالك ═══════════════════════════════

async def menu_owner(event):
    if get_role(event.sender_id) != ROLE_OWNER:
        await event.answer("خاص بالمالك فقط!", alert=True)
        return
    rows = [
        [
            Button.inline("🛡️ المشرفون",      "menu_admins"),
            Button.inline("💎 الاشتراكات",     "menu_subs"),
        ],
        [Button.inline("🌐 إحصائيات النظام",   "owner_global_stats")],
        [Button.inline("👥 جميع المستخدمين",   "owner_users_list")],
    ] + back_button()
    await event.edit(
        "👑 *لوحة المالك*\n━━━━━━━━━━━━━━━━━━━━━━━━",
        buttons=rows,
    )


async def owner_global_stats(event):
    if get_role(event.sender_id) != ROLE_OWNER:
        await event.answer("خاص بالمالك فقط!", alert=True)
        return
    s    = global_stats()
    subs = list_by_role(ROLE_SUBSCRIBER)
    admins = list_by_role(ROLE_ADMIN)
    text = (
        f"🌐 *إحصائيات النظام الكاملة*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 إجمالي المستخدمين : `{s['users']}`\n"
        f"   ├ 🛡️ مشرفون: `{len(admins)}`\n"
        f"   └ 💎 مشتركون: `{len(subs)}`\n\n"
        f"👤 إجمالي الحسابات  : `{s['accounts']}`\n"
        f"📡 إجمالي القنوات   : `{s['channels']}`\n"
        f"📝 إجمالي المنشورات : `{s['posts']}` (🟢 نشط: {s['active']})\n"
        f"📤 إجمالي الإرسال   : `{s['sent']}`"
    )
    rows = back_button("menu_owner")
    await event.edit(text, buttons=rows)


async def owner_users_list(event):
    if get_role(event.sender_id) != ROLE_OWNER:
        await event.answer("خاص بالمالك فقط!", alert=True)
        return
    users = all_users()
    lines = [f"👥 *المستخدمون* ({len(users)})\n━━━━━━━━━━━━━━━━━━━━━━━━"]
    for u in users[:20]:   # أول 20 مستخدم
        icon = ROLE_ICONS.get(u["role"], "👤")
        name = u["username"] or str(u["user_id"])
        lines.append(f"{icon} `{name}` — `{u['role']}`")
    if len(users) > 20:
        lines.append(f"\n_...و {len(users)-20} آخرين_")
    await event.edit("\n".join(lines), buttons=back_button("menu_owner"))


# ═══════════════════════════════ إدارة المشرفين والاشتراكات ═══════════════════════════════

async def menu_admins(event):
    if get_role(event.sender_id) not in (ROLE_OWNER, ROLE_ADMIN):
        await event.answer("هذا القسم خاص بالمالك والمشرفين!", alert=True)
        return
    admins = list_by_role(ROLE_ADMIN)
    rows   = [[Button.inline("➕ إضافة مشرف", "admin_add")]]
    for a in admins:
        rows.append([
            Button.inline(
                f"🛡️ {a['username'] or a['user_id']}",
                f"admin_remove_confirm:{a['user_id']}",
            )
        ])
    rows += back_button("menu_owner" if get_role(event.sender_id) == ROLE_OWNER else "menu_main")
    await event.edit(
        f"🛡️ *إدارة المشرفين* ({len(admins)})\n━━━━━━━━━━━━━━━━━━━━━━━━",
        buttons=rows,
    )


async def admin_add_start(event):
    if get_role(event.sender_id) != ROLE_OWNER:
        await event.answer("خاص بالمالك فقط!", alert=True)
        return
    STATE[event.sender_id] = {"action": "waiting_admin_id"}
    await event.edit(
        "🛡️ *إضافة مشرف*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل Telegram User ID للمستخدم:",
        buttons=cancel_button(),
    )


async def handle_waiting_admin_id(event, st):
    text = event.raw_text.strip()
    if not text.isdigit():
        await event.respond("❌ معرف غير صحيح. أرسل رقم فقط.", buttons=cancel_button())
        return
    target_id = int(text)
    ensure_user(target_id)
    set_role(target_id, ROLE_ADMIN, added_by=event.sender_id)
    clear_state(event.sender_id)
    role = get_role(event.sender_id)
    await event.respond(
        f"✅ *تمت إضافة المشرف!*\n\nالمعرف: `{target_id}`",
        buttons=main_menu_buttons(role),
    )


async def admin_remove_confirm(event):
    if get_role(event.sender_id) != ROLE_OWNER:
        await event.answer("خاص بالمالك فقط!", alert=True)
        return
    target_id = int(event.data.decode().split(":")[1])
    u = get_user(target_id)
    name = (u["username"] if u else None) or str(target_id)
    await event.edit(
        f"⚠️ *تأكيد إزالة المشرف*\n\n`{name}` ({target_id})\n\nهل تريد إزالته؟",
        buttons=confirm_buttons(f"admin_remove:{target_id}", "menu_admins"),
    )


async def admin_remove(event):
    if get_role(event.sender_id) != ROLE_OWNER:
        await event.answer("خاص بالمالك فقط!", alert=True)
        return
    target_id = int(event.data.decode().split(":")[1])
    remove_role(target_id)
    await event.answer("✅ تمت الإزالة")
    await menu_admins(event)


async def menu_subs(event):
    if get_role(event.sender_id) != ROLE_OWNER:
        await event.answer("خاص بالمالك فقط!", alert=True)
        return
    subs = list_by_role(ROLE_SUBSCRIBER)
    rows = [[Button.inline("➕ إضافة مشترك", "sub_add")]]
    for s in subs:
        name = s["username"] or str(s["user_id"])
        exp  = s["subscription_expiry"][:10] if s["subscription_expiry"] else "—"
        rows.append([
            Button.inline(f"💎 {name} ({exp})", f"sub_view:{s['user_id']}"),
            Button.inline("🗑️",                 f"sub_remove_confirm:{s['user_id']}"),
        ])
    rows += back_button("menu_owner")
    await event.edit(
        f"💎 *إدارة الاشتراكات* ({len(subs)})\n━━━━━━━━━━━━━━━━━━━━━━━━",
        buttons=rows,
    )


async def sub_view(event):
    if get_role(event.sender_id) != ROLE_OWNER:
        await event.answer("خاص بالمالك فقط!", alert=True)
        return
    target_id = int(event.data.decode().split(":")[1])
    u = get_user(target_id)
    if not u:
        await event.answer("المستخدم غير موجود!", alert=True)
        return
    exp = u["subscription_expiry"] or "—"
    try:
        remaining = (datetime.datetime.fromisoformat(exp) - datetime.datetime.utcnow()).days
        exp_str = f"`{exp[:10]}` (بعد {remaining} يوم)"
    except Exception:
        exp_str = f"`{exp}`"
    text = (
        f"💎 *تفاصيل الاشتراك*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 المستخدم : `{u['username'] or target_id}`\n"
        f"🔢 المعرف   : `{target_id}`\n"
        f"📅 ينتهي   : {exp_str}"
    )
    rows = [
        [Button.inline("➕ تمديد الاشتراك",   f"sub_extend:{target_id}")],
        [Button.inline("🗑️ إلغاء الاشتراك",  f"sub_remove_confirm:{target_id}")],
    ] + back_button("menu_subs")
    await event.edit(text, buttons=rows)


async def sub_extend(event):
    if get_role(event.sender_id) != ROLE_OWNER:
        await event.answer("خاص بالمالك فقط!", alert=True)
        return
    target_id = int(event.data.decode().split(":")[1])
    STATE[event.sender_id] = {"action": "waiting_sub_days", "sub_id": target_id}
    await event.edit(
        f"📅 *تمديد اشتراك*\n\nالمستخدم: `{target_id}`\n\nكم عدد أيام التمديد؟",
        buttons=cancel_button(),
    )


async def sub_add_start(event):
    if get_role(event.sender_id) != ROLE_OWNER:
        await event.answer("خاص بالمالك فقط!", alert=True)
        return
    STATE[event.sender_id] = {"action": "waiting_sub_id"}
    await event.edit(
        "💎 *إضافة مشترك*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل Telegram User ID للمستخدم:",
        buttons=cancel_button(),
    )


async def handle_waiting_sub_id(event, st):
    text = event.raw_text.strip()
    if not text.isdigit():
        await event.respond("❌ معرف غير صحيح.", buttons=cancel_button())
        return
    st["sub_id"] = int(text)
    st["action"] = "waiting_sub_days"
    ensure_user(st["sub_id"])
    await event.respond(
        f"📅 كم عدد أيام الاشتراك للمستخدم `{st['sub_id']}`؟",
        buttons=cancel_button(),
    )


async def handle_waiting_sub_days(event, st):
    text = event.raw_text.strip()
    if not text.isdigit() or int(text) <= 0:
        await event.respond("❌ أدخل رقماً صحيحاً.", buttons=cancel_button())
        return
    days   = int(text)
    expiry = set_subscription(st["sub_id"], days, added_by=event.sender_id)
    clear_state(event.sender_id)
    role = get_role(event.sender_id)
    await event.respond(
        f"✅ *تمت إضافة الاشتراك!*\n\n"
        f"👤 المستخدم : `{st['sub_id']}`\n"
        f"📅 المدة    : `{days}` يوم\n"
        f"⏰ ينتهي   : `{expiry.strftime('%Y-%m-%d %H:%M')} UTC`",
        buttons=main_menu_buttons(role),
    )


async def sub_remove_confirm(event):
    if get_role(event.sender_id) != ROLE_OWNER:
        await event.answer("خاص بالمالك فقط!", alert=True)
        return
    target_id = int(event.data.decode().split(":")[1])
    u = get_user(target_id)
    name = (u["username"] if u else None) or str(target_id)
    await event.edit(
        f"⚠️ *تأكيد إلغاء الاشتراك*\n\n`{name}` ({target_id})\n\nهل تريد إلغاء اشتراكه؟",
        buttons=confirm_buttons(f"sub_remove:{target_id}", "menu_subs"),
    )


async def sub_remove(event):
    if get_role(event.sender_id) != ROLE_OWNER:
        await event.answer("خاص بالمالك فقط!", alert=True)
        return
    target_id = int(event.data.decode().split(":")[1])
    remove_role(target_id)
    await event.answer("✅ تم إلغاء الاشتراك")
    await menu_subs(event)


# ═══════════════════════════════ موجّه الأزرار ═══════════════════════════════

CALLBACK_ROUTES = {
    "menu_main":                  show_main_menu,
    "guest_locked":               guest_locked,
    "menu_accounts":              menu_accounts,
    "acc_add_phone":              acc_add_phone_start,
    "acc_add_session":            acc_add_session_start,
    "menu_channels":              menu_channels,
    "channel_add_pick_account":   channel_add_pick_account,
    "menu_posts":                 menu_posts,
    "post_add_pick_channel":      post_add_pick_channel,
    "post_instant_pick_channel":  post_instant_pick_channel,
    "posts_list":                 posts_list,
    "sched_interval":             sched_interval,
    "sched_once":                 sched_once,
    "menu_control":               menu_control,
    "control_start":              control_start,
    "control_stop":               control_stop,
    "control_status":             control_status,
    "menu_stats":                 menu_stats,
    "menu_admins":                menu_admins,
    "admin_add":                  admin_add_start,
    "menu_subs":                  menu_subs,
    "sub_add":                    sub_add_start,
    "menu_owner":                 menu_owner,
    "owner_global_stats":         owner_global_stats,
    "owner_users_list":           owner_users_list,
}

PREFIX_ROUTES = {
    "acc_view:":                  acc_view,
    "acc_delete_confirm:":        acc_delete_confirm,
    "acc_delete:":                acc_delete,
    "channel_view:":              channel_view,
    "channel_use_account:":       channel_use_account,
    "channel_delete_confirm:":    channel_delete_confirm,
    "channel_delete:":            channel_delete,
    "instant_use_channel:":       instant_use_channel,
    "post_use_channel:":          post_use_channel,
    "post_view:":                 post_view,
    "post_toggle:":               post_toggle,
    "post_delete_confirm:":       post_delete_confirm,
    "post_delete:":               post_delete,
    "admin_remove_confirm:":      admin_remove_confirm,
    "admin_remove:":              admin_remove,
    "sub_view:":                  sub_view,
    "sub_extend:":                sub_extend,
    "sub_remove_confirm:":        sub_remove_confirm,
    "sub_remove:":                sub_remove,
}

MESSAGE_STATE_ROUTES = {
    "waiting_phone":            handle_waiting_phone,
    "waiting_code":             handle_waiting_code,
    "waiting_password":         handle_waiting_password,
    "waiting_session_string":   handle_waiting_session_string,
    "waiting_channel_ref":      handle_waiting_channel_ref,
    "waiting_post_content":     handle_waiting_post_content,
    "waiting_instant_content":  handle_waiting_instant_content,
    "waiting_interval":         handle_waiting_interval,
    "waiting_datetime":         handle_waiting_datetime,
    "waiting_admin_id":         handle_waiting_admin_id,
    "waiting_sub_id":           handle_waiting_sub_id,
    "waiting_sub_days":         handle_waiting_sub_days,
}


@bot.on(events.CallbackQuery())
async def callback_router(event):
    user_id = event.sender_id
    ensure_user(user_id, (await event.get_sender()).username)

    data = event.data.decode()

    if data != "menu_main" and not has_access(user_id):
        await event.answer(
            f"🔒 هذه الميزة تحتاج اشتراك!\nراسل @{OWNER_USERNAME} للاشتراك.",
            alert=True,
        )
        return

    if data == "menu_main":
        clear_state(user_id)

    if data in CALLBACK_ROUTES:
        await CALLBACK_ROUTES[data](event)
        return

    for prefix, handler in PREFIX_ROUTES.items():
        if data.startswith(prefix):
            await handler(event)
            return


@bot.on(events.NewMessage())
async def message_router(event):
    if event.raw_text and event.raw_text.startswith("/"):
        return

    user_id = event.sender_id
    st      = STATE.get(user_id)
    if not st:
        return

    if not has_access(user_id):
        clear_state(user_id)
        return

    handler = MESSAGE_STATE_ROUTES.get(st["action"])
    if handler:
        try:
            await handler(event, st)
        except Exception as e:
            logger.exception("خطأ أثناء معالجة الرسالة")
            await event.respond(f"❌ صار خطأ: `{e}`")
            clear_state(user_id)


# ═══════════════════════════════ المجدول ═══════════════════════════════

async def scheduler_loop():
    while True:
        try:
            due_posts = get_due_posts()
            for post in due_posts:
                owner_id = post["owner_user_id"]
                if not get_autopost_enabled(owner_id) or not is_subscription_active(owner_id):
                    continue

                try:
                    conn        = get_conn()
                    account_row = conn.execute(
                        "SELECT * FROM accounts WHERE id=?", (post["account_id"],)
                    ).fetchone()
                    conn.close()

                    if not account_row:
                        raise RuntimeError("الحساب المرتبط بالقناة غير موجود")

                    client = await get_userbot_client(account_row)
                    target = post["channel_ref"]

                    if post["content_type"] == "text":
                        await client.send_message(target, post["content_text"] or "")
                    else:
                        await client.send_file(
                            target,
                            post["media_path"],
                            caption=post["content_text"] or None,
                        )

                    increment_publish_count(post["id"])
                    logger.info(f"✅ نُشر المنشور #{post['id']} في {target}")

                except FloodWaitError as e:
                    logger.warning(f"⏳ FloodWait {e.seconds}s — منشور #{post['id']}")
                    next_run = datetime.datetime.utcnow() + datetime.timedelta(seconds=e.seconds + 5)
                    update_next_run(post["id"], next_run.isoformat())
                    continue

                except Exception as e:
                    logger.error(f"❌ فشل منشور #{post['id']}: {e}")

                if post["schedule_type"] == "interval" and post["interval_seconds"]:
                    next_run = datetime.datetime.utcnow() + datetime.timedelta(seconds=post["interval_seconds"])
                    update_next_run(post["id"], next_run.isoformat())
                else:
                    mark_post_done(post["id"])

        except Exception:
            logger.exception("خطأ عام في المجدول")

        await asyncio.sleep(SCHEDULER_INTERVAL)


# ═══════════════════════════════ التشغيل ═══════════════════════════════

async def main():
    if not API_ID or not API_HASH:
        print("═" * 60)
        print("⚠️  لازم تحط API_ID و API_HASH قبل التشغيل!")
        print("احصل عليهم من: https://my.telegram.org")
        print("═" * 60)

    init_db()
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("🚀 AutoPost Pro يعمل!")

    await reconnect_all_accounts()
    asyncio.create_task(scheduler_loop())
    await bot.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
