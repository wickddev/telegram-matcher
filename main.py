from eth_account import Account
import secrets
import telebot
import threading
import time
from datetime import datetime
import traceback
import logging

# ========== CONFIG ==========
BOT_TOKEN = '8031276311:AAEkUMZPfgMd75dVAOXlB0zAx9uSoafwxDs'
THREAD_COUNT = 4

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
target_prefix = None
target_suffix = None
searching = False
wallets_generated = 0
matches_found = 0
start_time = None
match_lock = False
lock = threading.Lock()

# ========== LOGGING ==========
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ========== HELPERS ==========

def get_speed_estimate():
    if not start_time:
        return 0
    elapsed = time.time() - start_time
    return wallets_generated / elapsed if elapsed > 0 else 0

def get_estimated_time(speed):
    total_combinations = 16 ** 3 * 16 ** 4
    return total_combinations / speed if speed > 0 else None

def log_match(level, address, private_key):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open("match_log.csv", "a") as f:
        f.write(f"{timestamp},{level},{address},{private_key},{wallets_generated}\n")

# ========== WALLET GENERATOR ==========

def wallet_generator(chat_id, worker_id):
    global searching, wallets_generated, matches_found, match_lock

    logging.info(f"Worker-{worker_id} started")

    try:
        while searching:
            acct = Account.create(secrets.token_hex(32))
            addr = acct.address[2:].lower()
            priv = acct.key.hex()

            with lock:
                wallets_generated += 1

            # ==== MATCH CHECKS ====
            full_match = addr.startswith(target_prefix) and addr.endswith(target_suffix)

            partial_matches = {
                "First 3 Only": addr.startswith(target_prefix),
                "Last 4 Only": addr.endswith(target_suffix),
                "First 2 + Last 2": addr.startswith(target_prefix[:2]) and addr.endswith(target_suffix[-2:]),
                "First 2 + Last 3": addr.startswith(target_prefix[:2]) and addr.endswith(target_suffix[-3:]),
                "First 3 + Last 2": addr.startswith(target_prefix) and addr.endswith(target_suffix[-2:]),
                "First 2 + Last 4": addr.startswith(target_prefix[:2]) and addr.endswith(target_suffix),
                "First 1 + Last 4": addr.startswith(target_prefix[:1]) and addr.endswith(target_suffix),
            }

            if full_match:
                with lock:
                    if match_lock:
                        return
                    match_lock = True
                    searching = False
                    matches_found += 1

                log_match("FULL", "0x" + addr, priv)

                bot.send_message(
                    chat_id,
                    f"🎯 <b>FULL MATCH FOUND</b>\n\n"
                    f"🔗 Address:\n0x{addr}\n\n"
                    f"🔑 Private Key:\n{priv}\n\n"
                    f"📊 Wallets Generated: {wallets_generated:,}"
                )

                logging.info("✅ Full match found — stopping all workers")
                return

            # ==== Notify on partial match ====
            for label, matched in partial_matches.items():
                if matched:
                    log_match(label, "0x" + addr, priv)
                    bot.send_message(
                        chat_id,
                        f"🔍 <b>{label}</b>\n\n"
                        f"🔗 0x{addr}\n"
                        f"🔑 {priv}\n"
                        f"📦 Count: {wallets_generated:,}"
                    )
                    break

            # ==== Progress update ====
            if worker_id == 0 and wallets_generated % 2000 == 0:
                speed = get_speed_estimate()
                eta = get_estimated_time(speed)
                eta_str = f"{int(eta//3600)}h {int((eta%3600)//60)}m" if eta else "Unknown"
                bot.send_message(
                    chat_id,
                    f"🔄 Wallets Checked: {wallets_generated:,}\n"
                    f"⚡ Speed: {int(speed)} wallets/sec\n"
                    f"⏳ Est. Time to Match: {eta_str}"
                )

    except Exception:
        logging.error(f"❌ ERROR in Worker-{worker_id}")
        logging.error(traceback.format_exc())
        searching = False

# ========== BOT COMMANDS ==========

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "👋 <b>Wallet Matcher Bot</b>\n\n"
        "Send the FULL wallet address you want to match.\n"
        "Then use /run to begin."
    )

@bot.message_handler(commands=['run'])
def run(message):
    global searching, start_time, wallets_generated, match_lock

    if not target_prefix or not target_suffix:
        bot.send_message(message.chat.id, "⚠️ Send a target address first.")
        return

    if searching:
        bot.send_message(message.chat.id, "⚙️ Already running.")
        return

    searching = True
    match_lock = False
    wallets_generated = 0
    start_time = time.time()

    for i in range(THREAD_COUNT):
        t = threading.Thread(target=wallet_generator, args=(message.chat.id, i), daemon=True)
        t.start()

    bot.send_message(message.chat.id, f"🚀 Generation started with {THREAD_COUNT} threads.")

@bot.message_handler(commands=['pause'])
def pause(message):
    global searching
    searching = False
    bot.send_message(message.chat.id, "⏸️ Paused.")

@bot.message_handler(commands=['stats'])
def stats(message):
    speed = get_speed_estimate()
    eta = get_estimated_time(speed)
    eta_str = f"{int(eta//3600)}h {int((eta%3600)//60)}m" if eta else "Unknown"

    bot.send_message(
        message.chat.id,
        f"📊 <b>Stats</b>\n\n"
        f"Wallets Generated: {wallets_generated:,}\n"
        f"Matches Found: {matches_found}\n"
        f"Speed: {int(speed)} wallets/sec\n"
        f"ETA: {eta_str}"
    )

# ========== ADDRESS HANDLER ==========

@bot.message_handler(func=lambda m: True)
def receive_wallet(message):
    global target_prefix, target_suffix

    text = message.text.strip().lower()
    if not text.startswith("0x") or len(text) < 10:
        bot.send_message(message.chat.id, "❌ Invalid Ethereum address.")
        return

    clean = text[2:]
    target_prefix = clean[:3]
    target_suffix = clean[-4:]

    bot.send_message(
        message.chat.id,
        f"🎯 Target Set\n\n"
        f"First 3: <code>{target_prefix}</code>\n"
        f"Last 4: <code>{target_suffix}</code>\n\n"
        f"Use /run to start."
    )

# ========== FLASK FAKE SERVER FOR RENDER ==========
from flask import Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "Wallet Matcher Bot is running 🚀"

# ========== START BOT ==========
def run_bot():
    try:
        logging.info("Bot polling started")
        bot.infinity_polling(skip_pending=True, timeout=30)
    except KeyboardInterrupt:
        logging.warning("Bot stopped by user")
    except Exception:
        logging.critical("BOT CRASHED")
        logging.critical(traceback.format_exc())

if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=10000)
