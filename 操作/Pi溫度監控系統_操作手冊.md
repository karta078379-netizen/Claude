# Raspberry Pi 溫度監控系統 — 操作手冊

專案位置：`/home/jlc/Benson`

---

## 一、每次啟動流程

需要開啟 **兩個 SSH 分頁**，兩個程式都要保持執行、不能中斷。

### 分頁一：啟動 Flask 網站伺服器

```bash
cd ~/Benson
source venv/bin/activate
python app.py
```

看到以下訊息代表成功：
```
Running on http://<Pi的IP>:5000
```

> ⚠️ 這個視窗要一直開著，不要按 Ctrl+C，關掉網頁就會連不上。

---

### 分頁二：啟動溫度記錄腳本

開新分頁，重新 SSH 連進 Pi：

```bash
cd ~/Benson
source venv/bin/activate
python logger.py
```

看到每 5 秒印出一行代表正常運作：
```
上傳溫度: 43.8°C -> 201
```

> ⚠️ 這個視窗也要一直開著，關掉就不會再有新資料上傳。

---

### 查看網頁

先確認 Pi 目前的 IP：
```bash
hostname -I
```

在電腦瀏覽器輸入：

| 功能 | 網址 |
|---|---|
| 即時圖表 | `http://<Pi的IP>:5000` |
| 資料表格 + 下載備份 | `http://<Pi的IP>:5000/data` |

---

## 二、關閉系統

在兩個分頁分別按 `Ctrl+C`，先停哪個都可以。

---

## 三、常見錯誤排除

### 錯誤：`Address already in use`

代表舊的 Flask 行程沒關乾淨，先清掉再重啟：
```bash
sudo fuser -k 5000/tcp
python app.py
```

### 查看目前佔用 5000 port 的行程

```bash
sudo lsof -i :5000
```
找到 PID 後手動關閉：
```bash
kill -9 <PID>
```

---

## 四、換網路的步驟

換到不同的 Wi-Fi / 路由器後，Pi 的 IP 幾乎一定會改變，需要重新確認。

### 第一步：讓 Pi 連上新的 Wi-Fi

```bash
sudo nmtui
```
選擇 `Activate a connection`，輸入新 Wi-Fi 名稱與密碼。

> ⚠️ 如果目前是靠舊 Wi-Fi 做 SSH 連線，換網路瞬間連線會斷掉，這是正常現象。

### 第二步：重新用新網路 SSH 連進 Pi

去路由器管理頁面查詢，或用手機熱點時自行得知連線的 IP，用 MobaXterm 重新建立 SSH 連線。

### 第三步：確認新 IP

連進 Pi 之後執行：
```bash
hostname -I
```

### 第四步：用新 IP 打開網頁

之後所有網址都要換成新查到的 IP：
```
http://<新IP>:5000
http://<新IP>:5000/data
```

### 注意事項

- 電腦跟 Pi 必須連在**同一個網路**下，才能用瀏覽器互相連線。
- 之後啟動流程（分頁一、分頁二）跟平常一樣，不受換網路影響，只有連線用的 IP 網址會變。

---

## 五、專案檔案位置一覽

| 檔案 | 說明 |
|---|---|
| `~/Benson/app.py` | Flask 後端主程式 |
| `~/Benson/logger.py` | 定時讀取溫度並上傳的腳本 |
| `~/Benson/data.db` | SQLite 資料庫，所有溫度紀錄存於此 |
| `~/Benson/templates/index.html` | 首頁即時圖表頁面 |
| `~/Benson/templates/data.html` | 資料表格與下載備份頁面 |

---

## 六、目前已知問題

- **系統時間可能不準確**：Pi 沒有內建電池 RTC，若長期沒有連上網路做 NTP 校時，開機後的系統時間可能與實際時間有落差，記錄的時間戳記會受影響。暫時可用以下指令手動校正（需自行帶入正確日期時間）：
  ```bash
  sudo date -s "YYYY-MM-DD HH:MM:SS"
  ```
