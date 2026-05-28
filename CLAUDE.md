# Italy Visa Monitor — 專案說明

## 目標

監測義大利簽證預約系統 prenotami.esteri.it，當有人取消釋出時段時通知我立即手動預約。
**8 月底必須出發義大利交換**，5-6 月需要辦好簽證，但目前預約都滿了。

## 核心原則(請嚴格遵守)

1. **只做監測 + 通知**，絕對不要實作「自動完成預約」邏輯
2. 改檔前必須先告訴我要改什麼,等我同意
3. 不要把帳密、護照號碼寫進程式碼,一律從 `.env` 讀取
4. 全程用繁體中文回答
5. 我是商管背景,不是工程師,技術細節請簡單解釋

## prenotami 操作流程(腳本要模擬的步驟)

### 登入
1. 進入 https://prenotami.esteri.it/
2. 點擊「Effettuare il Login per accedere al portale」按鈕
3. 輸入 Email + Password(從 .env 讀取)
4. 送出登入

### 進到預約查詢頁
5. 點擊「Prenota」
6. 選擇「VISTI」
7. 再次點擊「Prenota」進入表單頁

### 填寫表單
8. Tipo Prenotazione 欄位:選「Prenotazione Singola」
9. Altra/e cittadinanza/e 欄位:輸入「Taiwan」(從 .env 的 NATIONALITY 讀取)
10. Numero di passaporto 欄位:輸入護照號碼(從 .env 的 PASSPORT_NUMBER 讀取)
11. 勾選「Ho preso visione e accetto l'Informativa per la privacy」
12. 點擊「Avanti」按鈕
13. 彈出視窗點「確定」

### 檢查可預約時段
14. 進入後查看月曆,偵測是否有可選日期
15. 偵測到 → 截圖 + 發 Telegram 通知 + log
16. 沒偵測到 → 截圖留底,結束

### 登出
17. 點擊「Disconnetti」登出

## 防偵測策略

- 檢查間隔:90-240 分鐘隨機(不要固定整點)
- 用 Playwright headless Chromium,不要用純 requests
- 加 stealth 設定隱藏 webdriver 特徵
- 模擬人類延遲:每個動作之間 sleep 0.5-3 秒隨機
- 連續錯誤要 exponential backoff,避免帳號被風控

## 通知方式優先順序

1. **Telegram bot**(優先,即時推播)
2. Email (備用)

## 檔案結構

- `prenotami_monitor.py` — 主腳本
- `.env` — 機密設定(不 commit)
- `.env.example` — 設定範本(可 commit)
- `.gitignore` — git 忽略清單
- `screenshots/` — 每次檢查的截圖(不 commit)
- `logs/` — 執行 log(不 commit)

## 我的環境

- macOS
- Python 3.11+
- VS Code
- 用 nvm 管理 Node.js (path: `/Users/dongyu.021/.nvm/versions/node/v22.17.0`)

## 已知風險

- prenotami 有 Cloudflare 防護,過於頻繁會觸發 challenge
- 帳號被偵測為 bot 可能被封鎖,影響真正的簽證申請
- 因此防偵測 > 高頻率,寧可錯過也不要被擋