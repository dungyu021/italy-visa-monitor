"""
Prenotami 簽證預約監測腳本
- 登入 prenotami.esteri.it
- 按照固定流程進入簽證預約月曆
- 偵測到可選日期時發 Telegram 通知（備用 Email）
- 失敗時退避，避免帳號被風控

使用前：
1. pip install camoufox python-dotenv requests
2. python -m camoufox fetch
3. 建立同目錄的 .env 檔（範本見 .env.example）
4. python prenotami_monitor.py
"""

import os
import sys
import time
import random
import smtplib
import logging
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from camoufox.sync_api import Camoufox

# ---------- 設定 ----------
load_dotenv()

EMAIL = os.getenv("PRENOTAMI_EMAIL")
PASSWORD = os.getenv("PRENOTAMI_PASSWORD")
PASSPORT_NUMBER = os.getenv("PASSPORT_NUMBER")
NATIONALITY = os.getenv("NATIONALITY", "Taiwan")

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

NOTIFY_FROM = os.getenv("NOTIFY_EMAIL_FROM")
NOTIFY_APP_PASS = os.getenv("NOTIFY_EMAIL_APP_PASSWORD")
NOTIFY_TO = os.getenv("NOTIFY_EMAIL_TO")

CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", "90"))
CHECK_INTERVAL_MAX = int(os.getenv("CHECK_INTERVAL_MAX", "240"))

LOG_DIR = Path("./logs")
LOG_DIR.mkdir(exist_ok=True)
SCREENSHOT_DIR = Path("./screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "monitor.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

LOGIN_URL = "https://prenotami.esteri.it/"


# ---------- 工具函式 ----------

def human_sleep(a=0.8, b=2.5):
    time.sleep(random.uniform(a, b))


def send_telegram(message: str, screenshot_path: Path | None = None) -> bool:
    if not (TG_BOT_TOKEN and TG_CHAT_ID):
        log.warning("Telegram 設定不完整，跳過 Telegram 通知")
        return False
    try:
        if screenshot_path and screenshot_path.exists():
            photo_url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
            with open(screenshot_path, "rb") as f:
                requests.post(photo_url, data={"chat_id": TG_CHAT_ID}, files={"photo": f}, timeout=15)

        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, data={"chat_id": TG_CHAT_ID, "text": message}, timeout=15)
        resp.raise_for_status()
        log.info("Telegram 通知已送出")
        return True
    except requests.HTTPError as e:
        # 不直接 log 例外訊息，避免 URL 中的 Bot Token 洩漏到 log 檔
        log.error(f"Telegram 通知失敗：HTTP {e.response.status_code} {e.response.reason}")
        return False
    except Exception as e:
        log.error(f"Telegram 通知失敗：{type(e).__name__}")
        return False


def send_email(subject: str, body: str, screenshot_path: Path | None = None):
    if not (NOTIFY_FROM and NOTIFY_APP_PASS and NOTIFY_TO):
        log.warning("Email 設定不完整，跳過 Email 通知")
        return
    msg = MIMEMultipart()
    msg["From"] = NOTIFY_FROM
    msg["To"] = NOTIFY_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if screenshot_path and screenshot_path.exists():
        with open(screenshot_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={screenshot_path.name}")
        msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(NOTIFY_FROM, NOTIFY_APP_PASS)
            server.send_message(msg)
        log.info(f"Email 通知已寄出：{subject}")
    except Exception as e:
        log.error(f"寄信失敗：{e}")


def send_notification(subject: str, body: str, screenshot_path: Path | None = None):
    """優先 Telegram，失敗才用 Email"""
    tg_ok = send_telegram(body, screenshot_path)
    if not tg_ok:
        send_email(subject, body, screenshot_path)


# ---------- 核心檢查邏輯 ----------

def check_availability() -> tuple[bool, str, Path | None]:
    """
    按照 CLAUDE.md 的 17 步驟完整操作，回傳 (是否找到可預約時段, 說明訊息, 截圖路徑)
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = SCREENSHOT_DIR / f"check_{timestamp}.png"

    with Camoufox(headless=True, locale="it-IT") as browser:
        page = browser.new_page(viewport={"width": 1366, "height": 800})

        try:
            # 步驟 1：開啟首頁
            log.info("步驟 1：開啟登入頁面...")
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            human_sleep(2, 4)

            # 檢查 bot 偵測封鎖（Radware / Cloudflare）
            if "perfdrive.com" in page.url or "Access temporarily restricted" in page.content() or "Just a moment" in page.content():
                log.warning("遇到 bot 偵測封鎖，這次跳過")
                page.screenshot(path=str(screenshot_path))
                return False, "Bot 偵測封鎖，這次跳過", screenshot_path

            # 步驟 2：點擊「Effettuare il Login per accedere al portale」按鈕
            log.info("步驟 2：點擊登入入口按鈕...")
            try:
                login_entry = page.locator(
                    "a:has-text('Effettuare il Login'), button:has-text('Effettuare il Login')"
                )
                if login_entry.count() > 0:
                    login_entry.first.click()
                    # iam.esteri.it 是 JS 渲染，需等到頁面完全載入
                    page.wait_for_load_state("networkidle", timeout=30000)
                    human_sleep(2, 4)
            except Exception:
                pass

            # 步驟 3 & 4：填入帳號密碼並送出（欄位在 iam.esteri.it）
            log.info("步驟 3-4：填入帳號密碼並送出...")
            page.wait_for_selector('input[name="callback_1"]', timeout=15000)
            page.fill('input[name="callback_1"]', EMAIL)
            human_sleep(0.5, 1.5)
            page.fill('input[name="callback_2"]', PASSWORD)
            human_sleep(0.5, 1.5)
            page.click('button:has-text("Entra")')
            page.wait_for_load_state("networkidle", timeout=30000)
            human_sleep(3, 5)

            # 若 OAuth 重導向尚未完成，手動跳到 prenotami
            if "prenotami.esteri.it" not in page.url:
                log.info("等待 OAuth 重導向...")
                page.goto("https://prenotami.esteri.it/UserArea", wait_until="networkidle", timeout=30000)
                human_sleep(1, 2)

            if "prenotami.esteri.it" not in page.url:
                page.screenshot(path=str(screenshot_path))
                return False, "登入失敗，請檢查帳密", screenshot_path

            log.info("登入成功")

            # 步驟 5：點擊上方導覽列「Prenota」進入服務列表
            log.info("步驟 5：點擊 Prenota 進入服務列表...")
            page.wait_for_selector("nav a:has-text('Prenota')", timeout=15000)
            page.locator("nav a:has-text('Prenota')").first.click()
            page.wait_for_load_state("networkidle", timeout=20000)
            human_sleep(1, 2.5)

            # 步驟 6-7：點擊 VISTI 那一列的 PRENOTA 按鈕進入表單頁
            log.info("步驟 6-7：點擊 VISTI 列的 PRENOTA 按鈕...")
            page.wait_for_selector(
                "tr:has-text('VISTI (dal 1.5.2023)') button:has-text('PRENOTA')", timeout=15000
            )
            page.locator(
                "tr:has-text('VISTI (dal 1.5.2023)') button:has-text('PRENOTA')"
            ).first.click()
            page.wait_for_load_state("networkidle", timeout=20000)
            human_sleep(1.5, 3)

            # 步驟 8：選擇「Prenotazione Singola」
            log.info("步驟 8：選擇 Prenotazione Singola...")
            page.wait_for_selector("#typeofbookingddl", timeout=15000)
            page.select_option("#typeofbookingddl", value="1")
            human_sleep(1, 2)

            # 步驟 9：填入國籍（選完 Tipo 後欄位才出現）
            log.info(f"步驟 9：填入國籍 {NATIONALITY}...")
            page.wait_for_selector("#DatiAddizionaliPrenotante_0___testo", state="visible", timeout=10000)
            page.fill("#DatiAddizionaliPrenotante_0___testo", NATIONALITY)
            human_sleep(0.8, 1.5)

            # 步驟 10：填入護照號碼
            log.info("步驟 10：填入護照號碼...")
            page.fill("#DatiAddizionaliPrenotante_1___testo", PASSPORT_NUMBER)
            human_sleep(0.5, 1.5)

            # 步驟 11：勾選隱私政策
            log.info("步驟 11：勾選隱私政策...")
            if not page.locator("#PrivacyCheck").is_checked():
                page.locator("#PrivacyCheck").click()
            human_sleep(0.5, 1)

            # 步驟 12-13：點擊「AVANTI」並自動接受原生確認對話框
            log.info("步驟 12-13：點擊 AVANTI 並確認彈窗...")
            page.on("dialog", lambda dialog: dialog.accept())
            page.locator("#btnAvanti").click()
            # 明確等待跳轉到月曆頁，避免 networkidle 誤判
            try:
                page.wait_for_url(lambda url: "BookingCalendar" in url, timeout=20000)
            except Exception:
                page.screenshot(path=str(screenshot_path))
                return False, f"未到達月曆頁面，目前在：{page.url}", screenshot_path
            human_sleep(1, 2)

            # 步驟 14-16：查看月曆，偵測當月＋往後三個月（共四個月）的可選日期
            log.info("步驟 14-16：偵測月曆可選日期（當月＋往後三個月）...")

            available_months = []  # 收集有時段的月份名稱

            month_name_map = {
                # 義大利文
                "gennaio": ("1月", 1), "febbraio": ("2月", 2), "marzo": ("3月", 3),
                "aprile": ("4月", 4), "maggio": ("5月", 5), "giugno": ("6月", 6),
                "luglio": ("7月", 7), "agosto": ("8月", 8), "settembre": ("9月", 9),
                "ottobre": ("10月", 10), "novembre": ("11月", 11), "dicembre": ("12月", 12),
                # 英文（備用）
                "january": ("1月", 1), "february": ("2月", 2), "march": ("3月", 3),
                "april": ("4月", 4), "may": ("5月", 5), "june": ("6月", 6),
                "july": ("7月", 7), "august": ("8月", 8), "september": ("9月", 9),
                "october": ("10月", 10), "november": ("11月", 11), "december": ("12月", 12),
            }
            weekday_zh = ["一", "二", "三", "四", "五", "六", "日"]

            for i in range(4):
                # 讀取月曆標題（格式通常為「maggio 2026」或「May 2026」）
                month_num = None
                year_num = None
                try:
                    raw_label = page.locator(".datepicker-switch").first.inner_text(timeout=5000).strip()
                    parts = raw_label.split()
                    zh_month, month_num = month_name_map.get(parts[0].lower(), (parts[0], None))
                    year_num = int(parts[1]) if len(parts) >= 2 else None
                    month_label = f"{parts[1]}年{zh_month}" if len(parts) >= 2 else raw_label
                except Exception:
                    month_label = f"第 {i+1} 個月"

                # 偵測可選日期並逐一讀取日期數字
                day_cells = page.locator("td.day:not(.disabled):not(.old):not(.new)")
                available_days = day_cells.count()
                log.info(f"{month_label}：偵測到 {available_days} 個可選日期")

                if available_days > 0:
                    date_strs = []
                    for j in range(available_days):
                        try:
                            day_num = int(day_cells.nth(j).inner_text().strip())
                            if month_num and year_num:
                                dt = datetime(year_num, month_num, day_num)
                                weekday = weekday_zh[dt.weekday()]
                                date_strs.append(f"{month_num}/{day_num}({weekday})")
                            else:
                                date_strs.append(str(day_num))
                        except Exception:
                            pass
                    available_months.append(f"{month_label}：{'、'.join(date_strs)}")

                # 最後一個月不需要翻頁
                if i < 3:
                    next_selectors = [
                        "th.next",
                        ".datepicker-days th.next",
                        ".datepicker th.next",
                        "th[class*='next']",
                        "[data-action='next']",
                        "button.next",
                    ]
                    clicked = False
                    for sel in next_selectors:
                        try:
                            btn = page.locator(sel).first
                            btn.wait_for(state="visible", timeout=3000)
                            btn.click()
                            clicked = True
                            break
                        except Exception:
                            continue
                    if not clicked:
                        log.warning("找不到下個月按鈕，停止翻頁")
                        break
                    human_sleep(0.8, 1.5)

            # 截圖留底（停在最後翻到的月份）
            page.screenshot(path=str(screenshot_path), full_page=True)
            log.info(f"截圖已儲存：{screenshot_path.name}")

            if available_months:
                months_str = "、".join(available_months)
                log.info(f"偵測到可預約時段：{months_str}")
                return True, f"以下月份有可預約時段：{months_str}　立即登入手動預約！", screenshot_path

            return False, "目前無可預約時段（五～八月月曆均無可選日期）", screenshot_path

        except Exception as e:
            log.error(f"檢查時發生錯誤：{e}")
            try:
                page.screenshot(path=str(screenshot_path))
            except Exception:
                pass
            return False, f"錯誤：{e}", screenshot_path

        finally:
            # 步驟 17：點擊「Disconnetti」登出
            try:
                log.info("步驟 17：登出...")
                disconnetti = page.locator(
                    "a:has-text('Disconnetti'), button:has-text('Disconnetti')"
                )
                if disconnetti.count() > 0:
                    disconnetti.first.click()
                    human_sleep(1, 2)
                else:
                    page.goto("https://prenotami.esteri.it/Home/Logout", timeout=10000)
            except Exception:
                pass
            browser.close()


# ---------- 主迴圈 ----------

def main_loop():
    consecutive_errors = 0

    while True:
        log.info("=" * 50)
        log.info("開始本輪檢查")

        try:
            found, msg, shot = check_availability()
            log.info(f"結果：{msg}")
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if found:
                consecutive_errors = 0
                wait_min = random.randint(30, 60)
                send_notification(
                    subject="✅ 義大利簽證有可預約時段！立即登入！",
                    body=(
                        f"✅ 有可預約時段！\n"
                        f"時間：{now}\n"
                        f"訊息：{msg}\n\n"
                        f"立刻去 https://prenotami.esteri.it/ 手動預約！"
                    ),
                    screenshot_path=shot,
                )
            else:
                is_error = "錯誤" in msg or "封鎖" in msg or "失敗" in msg
                if is_error:
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0
                wait_min = random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)

                # 連續錯誤 → exponential backoff
                if consecutive_errors >= 2:
                    backoff = min(2 ** consecutive_errors, 12)
                    wait_min = random.randint(
                        CHECK_INTERVAL_MIN * backoff,
                        CHECK_INTERVAL_MAX * backoff,
                    )
                    log.warning(f"連續錯誤 {consecutive_errors} 次，退避 {wait_min} 分鐘")

                send_notification(
                    subject=f"❌ 義大利簽證監測：無時段",
                    body=(
                        f"❌ 無可預約時段\n"
                        f"時間：{now}\n"
                        f"訊息：{msg}\n"
                        f"下次檢查：約 {wait_min} 分鐘後"
                    ),
                    screenshot_path=shot,
                )

        except Exception as e:
            log.error(f"主迴圈異常：{e}")
            consecutive_errors += 1
            wait_min = random.randint(120, 300)
            send_notification(
                subject="❌ 義大利簽證監測：執行異常",
                body=(
                    f"❌ 主迴圈發生錯誤\n"
                    f"時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"錯誤：{e}"
                ),
            )

        log.info(f"等待 {wait_min} 分鐘後再次檢查...")
        time.sleep(wait_min * 60)


if __name__ == "__main__":
    if not EMAIL or not PASSWORD:
        log.error("請先在 .env 設定 PRENOTAMI_EMAIL 和 PRENOTAMI_PASSWORD")
        sys.exit(1)
    if not PASSPORT_NUMBER:
        log.error("請先在 .env 設定 PASSPORT_NUMBER")
        sys.exit(1)
    main_loop()