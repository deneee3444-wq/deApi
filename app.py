#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import uuid
import time
import random
import threading
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory

from browser_manager import BrowserManager
import deapi_engine

app = Flask(__name__)

CURRENT_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOADS_DIR = os.path.join(CURRENT_DIR, "uploads")
OUTPUTS_DIR = os.path.join(CURRENT_DIR, "outputs")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# Arka planda tarayıcıyı başlatan ve açık tutan Thread-Safe yönetici
print("[*] BrowserManager başlatılıyor...", flush=True)
browser_manager = BrowserManager()

# Sunucu taraflı runtime bellek (sayfa yenilendiğinde kaybolmaması için)
RUNTIME_STATE = {
    "last_api_key": ""
}
JOBS = {}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/state", methods=["GET"])
def api_get_state():
    """Sayfa yenilendiğinde mevcut API key ve tüm iş geçmişini döndürür."""
    # En yeniden en eskiye sırala
    job_list = sorted(list(JOBS.values()), key=lambda x: x.get("created_at_ts", 0), reverse=True)
    return jsonify({
        "success": True,
        "api_key": RUNTIME_STATE.get("last_api_key", ""),
        "jobs": job_list
    })

@app.route("/api/set-key", methods=["POST"])
def api_set_key():
    """Kullanıcı input'a key yazdığında runtime belleğine kaydeder."""
    data = request.json or {}
    key = data.get("api_key", "").strip()
    if key:
        RUNTIME_STATE["last_api_key"] = key
    return jsonify({"success": True})

@app.route("/api/create-account", methods=["POST"])
def api_create_account():
    """
    Arka plandaki açık tarayıcıyı kullanarak yeni bir $5 kredili
    deAPI hesabı açar ve API anahtarını döndürür.
    """
    try:
        new_key = deapi_engine.create_new_account_key(browser_manager)
        if new_key:
            RUNTIME_STATE["last_api_key"] = new_key
        return jsonify({"success": True, "api_key": new_key})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/models", methods=["GET"])
def api_models():
    api_key = request.args.get("api_key", "").strip()
    if not api_key:
        api_key = RUNTIME_STATE.get("last_api_key", "")
    if not api_key:
        return jsonify({"success": False, "error": "API Key gerekli"}), 400
    models = deapi_engine.fetch_models(api_key)
    return jsonify({"success": True, "models": models})

@app.route("/api/model-info", methods=["GET"])
def api_model_info():
    api_key = request.args.get("api_key", "").strip() or RUNTIME_STATE.get("last_api_key", "")
    model_slug = request.args.get("model", "").strip()
    if not api_key or not model_slug:
        return jsonify({"success": False, "error": "api_key ve model parametreleri gerekli"}), 400
    info = deapi_engine.fetch_model_info(api_key, model_slug)
    return jsonify({"success": True, "model_info": info})

@app.route("/api/estimate-price", methods=["POST"])
def api_estimate_price():
    data = request.json or {}
    api_key = data.get("api_key", "").strip() or RUNTIME_STATE.get("last_api_key", "")
    if not api_key:
        return jsonify({"success": False, "error": "API Key gerekli"}), 400

    payload = {
        "model": data.get("model", "MiniMaxH3_33B_Turbo_INT8"),
        "width": int(data.get("width", 1024)),
        "height": int(data.get("height", 576)),
        "frames": int(data.get("frames", 243)),
        "fps": int(data.get("fps", 24)),
    }
    steps = data.get("steps")
    if steps is not None and str(steps).strip() != "":
        try:
            payload["steps"] = int(steps)
        except (ValueError, TypeError):
            pass
    elif "ltxv" in payload["model"].lower():
        payload["steps"] = 1

    is_animation = bool(data.get("is_animation", False))
    ref_counts = {
        "images": int(data.get("ref_images_count", 0)),
        "videos": int(data.get("ref_videos_count", 0)),
        "audios": int(data.get("ref_audios_count", 0)),
    }

    price_info = deapi_engine.estimate_price(api_key, is_animation, payload, ref_counts)
    return jsonify({"success": True, "price_info": price_info})

def _background_job_worker(job_id, api_key, payload, file_paths):
    """Arka planda video işini API'ye gönderir, takip eder ve indirir."""
    try:
        JOBS[job_id]["status"] = "submitting"
        JOBS[job_id]["progress"] = 5.0

        resp = deapi_engine.submit_video_job(api_key, payload, file_paths)
        if not resp.get("success"):
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = resp.get("error", "İş API tarafından reddedildi.")
            return

        request_id = resp["request_id"]
        JOBS[job_id]["request_id"] = request_id
        JOBS[job_id]["status"] = "processing"
        JOBS[job_id]["progress"] = 10.0

        def _extract_url(job_info):
            """deAPI yanıtındaki result_url veya alternatif result alanlarını güvenle tarar."""
            if not job_info:
                return None
            u = job_info.get("result_url")
            if u and isinstance(u, str) and u.startswith("http"):
                return u
            res = job_info.get("result")
            if res and isinstance(res, str) and res.startswith("http"):
                return res
            if isinstance(res, dict):
                u2 = res.get("url") or res.get("video_url")
                if u2 and isinstance(u2, str) and u2.startswith("http"):
                    return u2
            v_u = job_info.get("video_url")
            if v_u and isinstance(v_u, str) and v_u.startswith("http"):
                return v_u
            return None

        # Takip döngüsü (Polling)
        while True:
            time.sleep(3)
            info = deapi_engine.check_job_status(api_key, request_id)
            status = info.get("status", "processing")
            progress = info.get("progress", 0.0)

            calc_progress = max(10.0, min(95.0, float(progress)))
            JOBS[job_id]["progress"] = round(calc_progress, 1)

            if status == "done":
                # deAPI üretimi tamamladı; video sunucuya indirilene kadar durumu 'downloading' yap
                JOBS[job_id]["status"] = "downloading"
                JOBS[job_id]["progress"] = 98.0

                # deAPI CDN / S3 yükleme gecikmesi için result_url dolana kadar bekle
                result_url = _extract_url(info)
                retries = 0
                while not result_url and retries < 12:
                    time.sleep(2)
                    retries += 1
                    sub_info = deapi_engine.check_job_status(api_key, request_id)
                    result_url = _extract_url(sub_info)

                if result_url:
                    filename = f"video_{request_id[:8]}_{int(time.time())}.mp4"
                    save_path = os.path.join(OUTPUTS_DIR, filename)
                    deapi_engine.download_video_file(result_url, save_path)
                    
                    # Dosya tam indirildi ve hazır -> Sadece şimdi 'done' yap!
                    JOBS[job_id]["video_url"] = f"/outputs/{filename}"
                    JOBS[job_id]["filename"] = filename
                    JOBS[job_id]["progress"] = 100.0
                    JOBS[job_id]["status"] = "done"
                else:
                    JOBS[job_id]["status"] = "error"
                    JOBS[job_id]["error"] = "Video üretildi fakat indirme bağlantısı (result_url) CDN tarafından zamanında sağlanamadı."
                break
            elif status == "error":
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["error"] = f"{info.get('error_code', 'ERROR')}: {info.get('error_reason', 'Bilinmeyen hata')}"
                break
            else:
                JOBS[job_id]["status"] = status

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(e)

@app.route("/api/generate", methods=["POST"])
def api_generate():
    api_key = request.form.get("api_key", "").strip() or RUNTIME_STATE.get("last_api_key", "")
    if not api_key:
        return jsonify({"success": False, "error": "API Key gerekli"}), 400

    RUNTIME_STATE["last_api_key"] = api_key

    prompt = request.form.get("prompt", "").strip()
    if not prompt:
        return jsonify({"success": False, "error": "Prompt gerekli"}), 400

    mode = request.form.get("mode", "t2v")
    model = request.form.get("model", "MiniMaxH3_33B_Turbo_INT8")
    width = int(request.form.get("width", 1024))
    height = int(request.form.get("height", 576))
    frames = int(request.form.get("frames", 243))
    fps = int(request.form.get("fps", 24))

    seed_val = request.form.get("seed", "-1").strip()
    if seed_val and seed_val != "-1":
        try:
            seed = int(seed_val)
        except ValueError:
            seed = random.randint(1, 2147483647)
    else:
        seed = random.randint(1, 2147483647)

    payload = {
        "model": model,
        "prompt": prompt,
        "width": width,
        "height": height,
        "frames": frames,
        "fps": fps,
        "seed": seed,
    }

    negative_prompt = request.form.get("negative_prompt", "").strip()
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt

    steps_val = request.form.get("steps", "").strip()
    if steps_val:
        try:
            payload["steps"] = int(steps_val)
        except ValueError:
            pass
    elif "ltxv" in model.lower():
        payload["steps"] = 1

    guidance_val = request.form.get("guidance", "").strip()
    if guidance_val:
        try:
            payload["guidance"] = float(guidance_val)
        except ValueError:
            pass

    enhance = request.form.get("enhance_prompt", "false").lower() == "true"
    if enhance:
        payload["enhance_prompt"] = True

    # Dosya İşleme (Mode ayrımı)
    file_paths = {
        "first_frame": None,
        "last_frame": None,
        "ref_images": [],
        "ref_videos": [],
        "ref_audios": [],
    }

    if mode == "keyframe":
        if "first_frame" in request.files and request.files["first_frame"].filename:
            ff = request.files["first_frame"]
            fname = f"ff_{uuid.uuid4().hex[:8]}_{ff.filename}"
            fpath = os.path.join(UPLOADS_DIR, fname)
            ff.save(fpath)
            file_paths["first_frame"] = fpath
        else:
            return jsonify({"success": False, "error": "Keyframe modunda İlk Kare (first_frame) zorunludur."}), 400

        if "last_frame" in request.files and request.files["last_frame"].filename:
            lf = request.files["last_frame"]
            fname = f"lf_{uuid.uuid4().hex[:8]}_{lf.filename}"
            fpath = os.path.join(UPLOADS_DIR, fname)
            lf.save(fpath)
            file_paths["last_frame"] = fpath

    elif mode == "reference":
        ref_imgs = request.files.getlist("ref_images")
        for img in ref_imgs:
            if img and img.filename:
                fname = f"refimg_{uuid.uuid4().hex[:8]}_{img.filename}"
                fpath = os.path.join(UPLOADS_DIR, fname)
                img.save(fpath)
                file_paths["ref_images"].append(fpath)

        ref_vids = request.files.getlist("ref_videos")
        for vid in ref_vids:
            if vid and vid.filename:
                fname = f"refvid_{uuid.uuid4().hex[:8]}_{vid.filename}"
                fpath = os.path.join(UPLOADS_DIR, fname)
                vid.save(fpath)
                file_paths["ref_videos"].append(fpath)

        ref_auds = request.files.getlist("ref_audios")
        for aud in ref_auds:
            if aud and aud.filename:
                fname = f"refaud_{uuid.uuid4().hex[:8]}_{aud.filename}"
                fpath = os.path.join(UPLOADS_DIR, fname)
                aud.save(fpath)
                file_paths["ref_audios"].append(fpath)

        if not file_paths["ref_images"] and not file_paths["ref_videos"] and not file_paths["ref_audios"]:
            return jsonify({"success": False, "error": "Referans modunda en az 1 referans dosyası yüklemelisiniz."}), 400

        if file_paths["ref_audios"] and not (file_paths["ref_images"] or file_paths["ref_videos"]):
            return jsonify({"success": False, "error": "Ses referansı tek başına kullanılamaz! Yanında en az bir resim veya video referansı olmalıdır."}), 400

    now = datetime.now()
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        "id": job_id,
        "prompt": prompt,
        "model": model,
        "mode": mode,
        "status": "queued",
        "progress": 0.0,
        "video_url": None,
        "error": None,
        "created_at": now.strftime("%H:%M:%S"),
        "created_at_ts": now.timestamp()
    }

    t = threading.Thread(
        target=_background_job_worker,
        args=(job_id, api_key, payload, file_paths),
        daemon=True,
        name=f"JobWorker-{job_id}"
    )
    t.start()

    return jsonify({"success": True, "job_id": job_id})

@app.route("/api/job-status/<job_id>", methods=["GET"])
def api_job_status(job_id):
    job = JOBS.get(job_id)
    if not job:
