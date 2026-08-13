"""
馬達特性曲線測試監控系統 — Flask 後端

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LabVIEW → Python  POST 端點
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

① POST /api/motor/upload   ← 馬達測試資料
② POST /api/upload_frame   ← CCD 影像

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Python → 網頁  GET 端點
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET  /api/motor/data        ← 網頁輪詢用
GET  /api/status            ← 首頁狀態
GET  /stream                ← MJPEG CCD 串流

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LabVIEW 送法說明
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【測試開始】送一次：
{
    "done":       false,
    "model":      "BLDC-24V-01",
    "input_mode": "DC"
}

【測試進行中】每筆持續送：
{
    "done":       false,
    "motor_v":    24.0,
    "motor_a":    2.569,
    "n_rpm":      1835,
    "torque":     725.9,
    "eff":        47.5,
    "po":         13.67,
    "temp":       27.7,
    "room_temp":  24.5,
    "break_v":    5.554,
    "break_a":    0.000
}

【CCD 畫面】每筆持續送到 /api/upload_frame：
{
    "frame": "<Base64 JPEG 字串>"
}

【測試結束】送一次：
{
    "done":        true,
    "Eff_Max_N":   3198,
    "Eff_Max_I":   0.663,
    "Eff_Max_T":   161.8,
    "Eff_Max_Po":  5.31,
    "Eff_Max_Eff": 68.5,
    "PO_Max_N":    1835,
    "PO_Max_I":    2.569,
    "PO_Max_T":    725.9,
    "PO_Max_Po":   13.67,
    "PO_Max_Eff":  47.5
}
"""

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import base64
import os
import time

app = Flask(__name__)
CORS(app)

# ── 狀態記憶體 ──────────────────────────────────────────
frame = None   # CCD JPEG bytes

motor_state = {
    # 狀態
    "status":     "Idle",
    "done":       False,
    # 基本資訊（開始時送入）
    "model":      "",
    "input_mode": "",
    # 即時數值（測試中持續更新）
    "motor_v":    None,
    "motor_a":    None,
    "n_rpm":      None,
    "torque":     None,
    "eff":        None,
    "po":         None,
    "temp":       None,
    "room_temp":  None,
    "break_v":    None,
    "break_a":    None,
    # 結束時的關鍵操作點
    "Eff_Max_N":   None,
    "Eff_Max_I":   None,
    "Eff_Max_T":   None,
    "Eff_Max_Po":  None,
    "Eff_Max_Eff": None,
    "PO_Max_N":    None,
    "PO_Max_I":    None,
    "PO_Max_T":    None,
    "PO_Max_Po":   None,
    "PO_Max_Eff":  None,
}

motor_history = []  # 每筆的圖表曲線資料點（供重整重建）


# ── CCD ─────────────────────────────────────────────────
@app.route("/api/upload_frame", methods=["POST"])
def upload_frame():
    global frame
    data = request.get_json(force=True)
    if "frame" in data:
        frame = base64.b64decode(data["frame"])
    return jsonify({"status": "ok"})


@app.route("/stream")
def stream():
    # 改成回傳單張 JPEG，讓網頁用 polling 取代 MJPEG 長連線
    # 這樣不會佔住 thread
    if frame:
        return Response(frame, mimetype="image/jpeg",
                        headers={"Cache-Control": "no-cache, no-store"})
    return Response(status=204)


@app.route("/api/latest_frame")
def latest_frame():
    if frame:
        import base64
        return jsonify({"frame": base64.b64encode(frame).decode()})
    return jsonify({"frame": None})


# ── 馬達測試資料 ─────────────────────────────────────────
@app.route("/api/motor/upload", methods=["POST"])
def motor_upload():
    data = request.get_json(force=True)

    # F 訊號：done=false 且帶 model，但沒有即時數值(torque) → 一定是新測試開始
    # 不依賴「上次是否 done」，避免 T 訊號漏收或時序問題導致舊資料殘留、接到上一次測試的點
    is_start = (not data.get("done")) and ("model" in data) and (data.get("torque") is None)
    if is_start or (not data.get("done") and motor_state["done"]):
        for k in motor_state:
            if k not in ("status", "done"):
                motor_state[k] = None if k not in ("model", "input_mode") else ""
        motor_state["done"] = False
        motor_history.clear()  # 清除歷史，避免新測試接到上次的點

    # 更新所有有傳入的欄位
    for k in motor_state:
        if k in data:
            motor_state[k] = data[k]

    if motor_state["done"]:
        motor_state["status"] = "Done"
        print(f"[Motor] DONE — Eff_Max={motor_state['Eff_Max_Eff']}%  PO_Max={motor_state['PO_Max_Po']}W  ({len(motor_history)} pts)")
    else:
        motor_state["status"] = "Running"
        print(f"[Motor] rpm={motor_state['n_rpm']}  tq={motor_state['torque']}  eff={motor_state['eff']}")

        # 存歷史：測試中每筆有 torque(x軸) 的即時資料 → append（去重）
        if motor_state["torque"] is not None:
            tq = motor_state["torque"]
            if not motor_history or motor_history[-1]["torque"] != tq:
                motor_history.append({
                    "torque":  tq,
                    "n_rpm":   motor_state["n_rpm"],
                    "motor_a": motor_state["motor_a"],
                    "eff":     motor_state["eff"],
                    "po":      motor_state["po"],
                })

    return jsonify({"status": "ok"})


@app.route("/api/motor/data")
def motor_data():
    return jsonify({**motor_state, "history": motor_history})


# ── 首頁狀態 ─────────────────────────────────────────────
def _noise_status():
    if noise_state["done"] is True:
        return "Done"
    if noise_state["state"] in ("bg", "ind", "ind_stop") or noise_state["done"] is False:
        return "Running"
    return "Idle"

@app.route("/api/status")
def get_status():
    return jsonify({
        "motor": motor_state["status"],
        "noise": _noise_status(),
        "gear":  "Idle",   # gear 尚無真實後端，永遠回報 Idle
        "life":  torque_state["status"],   # index.html 用 life key 對應扭力測試
        "lifenew": life_state["status"],   # index.html 用 lifenew key 對應壽命測試
    })


@app.route("/")
def home():
    return "Test Monitor Backend OK"

@app.route("/<path:filename>")
def serve_file(filename):
    directory = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(directory, filename)


# ════════════════════════════════════════════════
#  扭力測試
# ════════════════════════════════════════════════

torque_history = []  # 每圈的歷史資料
torque_start_time = None  # 測試開始時間戳

torque_state = {
    "status":       "Idle",
    "done":         False,
    # 開始時送入
    "model":        "",
    "gear_ratio":   None,   # 減速比
    "angle_move":   None,   # 轉動角度
    "total_cycles": None,   # 總測試圈數
    # 測試中持續送入
    "torque_cw":    None,   # 正轉扭矩
    "torque_ccw":   None,   # 反轉扭矩
    "angle_cw":     None,   # 正轉角度
    "angle_ccw":    None,   # 反轉角度
    "rpm":          None,   # 轉速
    "cycles":       None,   # 目前圈數
    "max_cw":       None,   # 正轉最大值
    "max_ccw":      None,   # 反轉最大值
}


@app.route("/api/torque/upload", methods=["POST"])
def torque_upload():
    global torque_start_time
    """
    【測試開始】送一次：
    {
        "done":         false,
        "model":        "Product-A1",
        "gear_ratio":   20,
        "angle_move":   80,
        "total_cycles": 50000
    }

    【測試進行中】每筆持續送：
    {
        "done":       false,
        "torque_cw":  9.842,
        "torque_ccw": -0.502,
        "angle_cw":   85.6,
        "angle_ccw":  8.74,
        "rpm":        1524,
        "cycles":     1525,
        "max_cw":     9.8259,
        "max_ccw":    0.8806
    }

    【測試結束】送一次：
    { "done": true }
    """
    data = request.get_json(force=True)

    # F 訊號：done=false 且帶 model，但沒有即時數值(cycles) → 一定是新測試開始
    is_start = (not data.get("done")) and ("model" in data) and (data.get("cycles") is None)
    if is_start or (not data.get("done") and torque_state["done"]):
        for k in torque_state:
            if k not in ("status", "done"):
                torque_state[k] = None if k != "model" else ""
        torque_state["done"] = False
        torque_history.clear()  # 清除歷史，避免新測試接到上次的點
        torque_start_time = None

    # Then update fields
    for k in torque_state:
        if k in data:
            if k == "cycles" and data[k] == 0:
                continue
            torque_state[k] = data[k]

    if torque_state["done"]:
        torque_state["status"] = "Done"
        print(f"[Torque] DONE — cycles={torque_state['cycles']}")
    else:
        if torque_state["status"] != "Running" and torque_start_time is None:
            torque_start_time = time.time()
        torque_state["status"] = "Running"
        print(f"[Torque] cycles={torque_state['cycles']}  max_cw={torque_state['max_cw']}  max_ccw={torque_state['max_ccw']}")
        # 存歷史：cycles=N 帶的是第 N-1 圈的 max，存在 N-1 的位置
        if torque_state["cycles"] and torque_state["cycles"] >= 2 and torque_state["max_cw"] is not None:
            plot_cycle = torque_state["cycles"] - 1
            if not torque_history or torque_history[-1]["cycles"] != plot_cycle:
                torque_history.append({
                    "cycles": plot_cycle,
                    "max_cw": torque_state["max_cw"],
                    "max_ccw": torque_state["max_ccw"],
                })

    return jsonify({"status": "ok"})


@app.route("/api/torque/data")
def torque_data():
    return jsonify({**torque_state, "history": torque_history, "start_time": torque_start_time})



# ════════════════════════════════════════════════
#  壽命測試
# ════════════════════════════════════════════════

life_history = []      # 每圈的歷史資料
life_start_time = None # 測試開始時間戳

life_state = {
    "status":       "Idle",
    "done":         False,
    # 開始時送入
    "model":        "",
    "total_cycles": None,   # 目標圈數
    # 每圈送入（cycles 與該圈數值同批送）
    "cycles":       None,   # 目前圈數
    "motor_temp":   None,   # 馬達溫度
    "room_temp":    None,   # 室溫
    "temp_diff":    None,   # 溫差
    "load_current": None,   # 馬達電流
    "rise_max":     None,   # 上升電流最大值
    "fall_max":     None,   # 下降電流最大值
}


@app.route("/api/life/upload", methods=["POST"])
def life_upload():
    global life_start_time
    """
    【開始】送一次：
    { "done": false, "model": "Product-A1", "total_cycles": 50000 }

    【每圈送】（先送 cycles，再送該圈各項數值，皆屬於同一圈）：
    {
        "done":         false,
        "cycles":       1,
        "motor_temp":   45.2,
        "room_temp":    25.0,
        "temp_diff":    20.2,
        "load_current": 1.23,
        "rise_max":     2.45,
        "fall_max":     1.88
    }

    【結束】送一次：
    { "done": true }
    """
    data = request.get_json(force=True)

    # F 訊號：done=false 且帶 model，但沒有即時數值(cycles) → 一定是新測試開始
    is_start = (not data.get("done")) and ("model" in data) and (data.get("cycles") is None)
    if is_start or (not data.get("done") and life_state["done"]):
        for k in life_state:
            if k not in ("status", "done"):
                life_state[k] = None if k != "model" else ""
        life_state["done"] = False
        life_history.clear()  # 清除歷史，避免新測試接到上次的點
        life_start_time = None

    # 更新欄位
    for k in life_state:
        if k in data:
            life_state[k] = data[k]

    if life_state["done"]:
        life_state["status"] = "Done"
        print(f"[Life] DONE — cycles={life_state['cycles']}")
    else:
        if life_state["status"] != "Running" and life_start_time is None:
            life_start_time = time.time()
        life_state["status"] = "Running"
        print(f"[Life] cycles={life_state['cycles']}  rise_max={life_state['rise_max']}  fall_max={life_state['fall_max']}")

        # 存歷史：cycles=N 帶的就是第 N 圈的數值，直接存
        cyc = life_state["cycles"]
        if (cyc and cyc > 0 and life_state["rise_max"] is not None
                and life_state["fall_max"] is not None
                and life_state["motor_temp"] is not None
                and life_state["room_temp"] is not None):
            if not life_history or life_history[-1]["cycles"] != cyc:
                life_history.append({
                    "cycles":     cyc,
                    "rise_max":   life_state["rise_max"],
                    "fall_max":   life_state["fall_max"],
                    "motor_temp": life_state["motor_temp"],
                    "room_temp":  life_state["room_temp"],
                    "temp_diff":  life_state["temp_diff"],
                })

    return jsonify({"status": "ok"})


@app.route("/api/life/data")
def life_data():
    return jsonify({**life_state, "history": life_history, "start_time": life_start_time})


# ════════════════════════════════════════════════
#  噪音振動測試
# ════════════════════════════════════════════════

noise_history = []  # 每筆 ind 測量歷史

noise_state = {
    "state":        "idle",   # idle / bg / ind / ind_stop / done
    "model":        "",
    "done":         None,  # None=未開始, False=測試中, True=完成
    "mic_distance": None,
    "mic_direction":"",
    "acc_position": "",
    "has_vibration": True,   # 布林：true/T=噪音+振動(預設)，false/F=兩個都是噪音(第二欄顯示成噪音2)
    # 狀態布林
    "bg_noise":     False,
    "ind_noise":    False,
    # Background Noise
    "bg_leq":       None,
    # Industrial Noise
    "ind_leq":      None,
    "ind_run_leq":  None,
    "ind_max":      None,
    # Vibration
    "vib_rms":      None,
    "vib_run_rms":  None,
    "vib_max":      None,
    # Time
    "time_interval": 1,
}


@app.route("/api/noise/upload", methods=["POST"])
def noise_upload():
    """
    【開始】           done=false, model, mic_distance, mic_direction, acc_position
    【BG Noise 開始】  bg_noise=true
    【BG Noise 測量中】bg_leq=33.42
    【BG Noise 結束】  bg_noise=false
    【IND Noise 開始】 ind_noise=true
    【IND Noise 測量中】ind_leq, ind_run_leq, ind_max, vib_rms, vib_run_rms, vib_max, time_interval
    【IND Noise 結束】 ind_noise=false
    【清除重測】        ind_clear=true  → 清除產品噪音資料，回到等待
    【整個測試結束】    done=true
    """
    data = request.get_json(force=True)

    # F 訊號：done=false 且帶 model（一定是新測試開始），或沿用舊的「上次是 done」判斷做保底
    is_start = ("done" in data and data["done"] == False and "model" in data)
    if is_start or ("done" in data and data["done"] == False and noise_state["done"] != False):
        for k in ["bg_leq","ind_leq","ind_run_leq","ind_max","vib_rms","vib_run_rms","vib_max"]:
            noise_state[k] = None
        noise_state["bg_noise"] = False
        noise_state["ind_noise"] = False
        noise_history.clear()
        noise_state["ind_clear"] = True  # 通知網頁清除圖表
        noise_state["state"] = "idle"
        noise_state["done"] = False
        print("[Noise] New test → idle, clear chart")

    # 測試結束
    if "done" in data and data["done"] == True:
        noise_state["state"] = "done"
        noise_state["done"] = True
        print("[Noise] done=true → done")
        return jsonify({"status": "ok"})

    # Basic info
    for k in ["model", "mic_direction", "acc_position"]:
        if k in data:
            noise_state[k] = data[k]
    if "mic_distance" in data:
        noise_state["mic_distance"] = data["mic_distance"]
    if "time_interval" in data:
        noise_state["time_interval"] = data["time_interval"]
    if "has_vibration" in data:
        noise_state["has_vibration"] = data["has_vibration"]

    # BG noise：true=開始, false=結束等待
    if "bg_noise" in data:
        if data["bg_noise"] == True:
            noise_state["state"] = "bg"
            noise_state["bg_noise"] = True
            print("[Noise] bg_noise=true → bg")
        elif data["bg_noise"] == False:
            noise_state["state"] = "idle"
            noise_state["bg_noise"] = False
            print("[Noise] bg_noise=false → idle")

    # IND noise：true=開始, false=測量結束等待 clear 或 done
    if "ind_noise" in data:
        if data["ind_noise"] == True:
            # 只有從 False 變 True 時才清空（第一次進入）
            if noise_state["ind_noise"] == False:
                for k in ["ind_leq","ind_run_leq","ind_max","vib_rms","vib_run_rms","vib_max"]:
                    noise_state[k] = None
                noise_state["ind_clear"] = True
                noise_history.clear()  # 清除歷史
                print("[Noise] ind_noise: False→True, clear data")
            noise_state["state"] = "ind"
            noise_state["ind_noise"] = True
        elif data["ind_noise"] == False:
            noise_state["state"] = "ind_stop"
            noise_state["ind_noise"] = False
            print("[Noise] ind_noise=false → ind_stop")



    # 更新數值（過濾 NaN）
    import math
    for k in ["bg_leq", "ind_leq", "ind_run_leq", "ind_max", "vib_rms", "vib_run_rms", "vib_max"]:
        if k in data and data[k] is not None:
            try:
                val = float(data[k])
                noise_state[k] = None if math.isnan(val) else val
            except (ValueError, TypeError):
                pass

    # 存歷史（測量中，且這批有送任一 ind/vib 數值就存）
    if noise_state["state"] == "ind":
        has_data = any(k in data and data[k] is not None for k in
                        ["ind_leq","ind_run_leq","ind_max","vib_rms","vib_run_rms","vib_max"])
        if has_data:
            noise_history.append({
                "leq":     noise_state["ind_leq"],
                "run_leq": noise_state["ind_run_leq"],
                "vib":     noise_state["vib_rms"],
                "run_vib": noise_state["vib_run_rms"],
            })

    print(f"[Noise] state={noise_state['state']}  leq={noise_state['ind_leq']}  vib={noise_state['vib_rms']}")
    return jsonify({"status": "ok"})


@app.route("/api/noise/data")
def noise_data():
    result = dict(noise_state)
    result["history"] = list(noise_history)
    if noise_state.get("ind_clear"):
        noise_state["ind_clear"] = False
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
