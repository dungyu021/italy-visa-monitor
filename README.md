# 🇮🇹 Italy Visa Appointment Monitor

自動監測義大利簽證預約系統 [prenotami.esteri.it](https://prenotami.esteri.it/)，當有人取消釋出時段時，立即發送 Telegram 通知讓你手動完成預約。

---

## 功能特色

- 自動登入、填表、進入預約月曆，完整模擬真人操作
- 偵測到可預約時段時立即發送 **Telegram 通知**（附截圖）
- 使用 [camoufox](https://github.com/daijro/camoufox) 隱藏自動化特徵，繞過 Radware bot 偵測
- 隨機間隔（預設 30–90 分鐘）避免固定頻率被偵測
- 連續錯誤自動退避（exponential backoff）
- 每次檢查結果都發通知（❌ 無時段 / ✅ 有時段），確認腳本仍在運作

---

## 運作邏輯

每次檢查完整執行以下 17 個步驟：

```
登入
  1. 開啟 prenotami.esteri.it
  2. 點擊「Effettuare il Login per accedere al portale」
  3. 輸入 Email（從 .env 讀取）
  4. 輸入 Password 並送出

進入預約頁
  5. 點擊上方導覽列「Prenota」
  6-7. 找到「VISTI (dal 1.5.2023)」那列，點擊「PRENOTA」按鈕

填寫表單
  8. 選擇 Tipo Prenotazione → Prenotazione Singola
  9. 填入國籍（從 .env 的 NATIONALITY 讀取）
  10. 填入護照號碼（從 .env 的 PASSPORT_NUMBER 讀取）
  11. 勾選隱私政策
  12. 點擊「AVANTI」
  13. 自動確認原生彈出視窗

檢查月曆
  14. 進入 /BookingCalendar 頁面
  15. 偵測月曆上是否有非 disabled 的可選日期
  16a. 有 → 截圖 + 發 Telegram 通知
  16b. 無 → 截圖留底，發通知告知無時段

登出
  17. 點擊「Disconnetti」登出
```

**注意**：腳本只負責監測和通知，不會自動完成預約。收到通知後需要立即手動登入搶時段。

---

## 環境需求

- macOS（Windows 未測試）
- Python 3.11+
- Telegram 帳號（用來建立 Bot 並接收通知）

---

## 安裝步驟

### 1. 安裝 Python 套件

```bash
pip3 install camoufox python-dotenv requests
python3 -m camoufox fetch
```

### 2. 建立設定檔

複製範本並填入你的資料：

```bash
cp .env.example .env
```

然後編輯 `.env`（說明見下方）。

### 3. 設定終端機捷徑（選擇性）

將以下內容加入 `~/.zshrc`：

```bash
alias startvisa="cd \"/path/to/italy-visa-monitor\" && python3 prenotami_monitor.py &"
alias endvisa="pkill -f prenotami_monitor.py && echo 簽證監測已停止"

checkvisa() {
  LOG="/path/to/italy-visa-monitor/logs/monitor.log"
  if pgrep -f prenotami_monitor.py > /dev/null 2>&1; then
    echo "✅ 監測中"
    LAST=$(grep "等待 [0-9]* 分鐘後再次檢查" "$LOG" 2>/dev/null | tail -1)
    if [ -n "$LAST" ]; then
      TS=$(echo "$LAST" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}')
      MINS=$(echo "$LAST" | grep -oE '[0-9]+ 分鐘' | grep -oE '[0-9]+')
      if [ -n "$TS" ] && [ -n "$MINS" ]; then
        TS_EPOCH=$(date -j -f "%Y-%m-%d %H:%M:%S" "$TS" "+%s" 2>/dev/null)
        NEXT_EPOCH=$((TS_EPOCH + MINS * 60))
        NOW=$(date +%s)
        REMAIN=$(( (NEXT_EPOCH - NOW) / 60 ))
        NEXT_TIME=$(date -r $NEXT_EPOCH "+%H:%M" 2>/dev/null)
        [ $REMAIN -gt 0 ] && echo "⏰ 下次檢查：$NEXT_TIME（還有 ${REMAIN} 分鐘）"
      fi
    fi
    LAST_RESULT=$(grep "結果：" "$LOG" 2>/dev/null | tail -1 | sed 's/.*結果：//')
    [ -n "$LAST_RESULT" ] && echo "📋 上次結果：$LAST_RESULT"
  else
    echo "❌ 監測已停止"
    LAST_CHECK=$(grep "開始本輪檢查" "$LOG" 2>/dev/null | tail -1 | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}')
    [ -n "$LAST_CHECK" ] && echo "🕐 最後執行時間：$LAST_CHECK"
  fi
}
```

設定完後執行 `source ~/.zshrc`。

---

## .env 設定說明

```env
# Prenotami 帳號
PRENOTAMI_EMAIL=你的帳號email
PRENOTAMI_PASSWORD=你的密碼

# 簽證申請個人資料
PASSPORT_NUMBER=護照號碼
NATIONALITY=Taiwan

# Telegram 通知（必填）
TG_BOT_TOKEN=
TG_CHAT_ID=

# Email 通知（選填，Telegram 失敗時備用）
NOTIFY_EMAIL_FROM=
NOTIFY_EMAIL_APP_PASSWORD=
NOTIFY_EMAIL_TO=

# 檢查間隔（分鐘）
CHECK_INTERVAL_MIN=90
CHECK_INTERVAL_MAX=240
```

---

## Telegram Bot 設定教學

### 取得 Bot Token
1. 在 Telegram 搜尋 **@BotFather**
2. 傳送 `/newbot`
3. 輸入 bot 名稱（例如：`My Visa Monitor`）
4. 輸入 bot 用戶名（必須以 `bot` 結尾，例如：`myvisamonitor_bot`）
5. 複製拿到的 **token**，填入 `.env` 的 `TG_BOT_TOKEN`

### 取得 Chat ID
1. 在 Telegram 搜尋 **@userinfobot**
2. 傳送任意訊息
3. 複製拿到的 **Id**，填入 `.env` 的 `TG_CHAT_ID`

### 啟用 Bot（重要）
設定完成後，**必須先傳一則訊息給你的 Bot**（搜尋 bot 用戶名，按 Start），否則 Bot 無法主動傳訊給你。

---

## 使用方式

### 啟動監測
```bash
startvisa
# 或
python3 prenotami_monitor.py &
```

### 停止監測
```bash
endvisa
# 或
pkill -f prenotami_monitor.py
```

### 查看狀態
```bash
checkvisa
```

輸出範例：
```
✅ 監測中
⏰ 下次檢查：19:15（還有 42 分鐘）
📋 上次結果：目前無可預約時段（月曆無可選日期）
```

---

## 電腦睡眠注意事項

闔上筆電時腳本會暫停。若需要長時間讓電腦運作：

1. **插電**
2. 在另一個終端機視窗執行：
   ```bash
   caffeinate -i -s
   ```
3. 再執行 `startvisa`

重新開機或闔蓋出門後，回來只需重新執行 `startvisa`。

---

## 檔案結構

```
italy-visa-monitor/
├── prenotami_monitor.py   # 主腳本
├── .env                   # 機密設定（不 commit）
├── .env.example           # 設定範本
├── .gitignore
├── CLAUDE.md              # 專案說明與開發規範
├── screenshots/           # 每次檢查截圖（不 commit）
└── logs/                  # 執行 log（不 commit）
```

---

## 已知限制

- prenotami 使用 Radware bot 防護，過於頻繁可能觸發驗證
- 帳號被封鎖會影響真正的簽證申請，**防偵測優先於高頻率**
- Cookie 和 session 由 camoufox 管理，每次重新登入
- 腳本不會自動完成預約，收到通知後需要立即手動操作
