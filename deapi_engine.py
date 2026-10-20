#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
🎬 deAPI Engine (Web Edition) 🎬
================================================================================
deAPI VİDEO KURALLARI & NORMALİZASYON DEĞERLERİ (ÖZET REFERANS):
--------------------------------------------------------------------------------
1. FPS Kuralı:
   - Kesinlikle ve sadece 24 FPS zorunludur (MiniMax & LTX 2.5).
   - 5 Saniye: MiniMax = 124 kare, LTX 2.5 = 120 kare.
   - 10 Saniye: MiniMax = 243 kare, LTX 2.5 = 241 kare.

2. Çözünürlük ve Boyut Sınırları:
   - Maksimum kenar: 1344 px.
   - Maksimum piksel alanı: 1344 x 768 = 1.032.192 px (bu alanı aşamaz).
   - Normalizasyon Değerleri (768p Standart):
     * 16:9 -> 1344 x 768 (veya 1024 x 576)
     * 9:16 -> 768 x 1344 (veya 576 x 1024)
     * 1:1  -> 768 x 768
     * 4:3  -> 1024 x 768
     * 3:4  -> 768 x 1024
     * 21:9 -> 1344 x 576

3. Model Limitleri & RPD (Requests Per Day):
   - Hız Sınırı: Her iki modelde de 1 RPM (dakikada 1 istek).
   - MiniMax H3: RPD = 3 (Hesap başına günlük 3 video).
   - LTX 2.5:    RPD = 15 (Hesap başına günlük 15 video), payload'da steps: 1 zorunludur.

4. Medya Referans Kuralları:
   - MiniMax H3: En fazla 3 referans medya (görsel + video + ses <= 3).
     * Görsel maks 3 (ref_images[0..2]), Video maks 1 (ref_videos[0]), Ses maks 1 (ref_audios[0]).
     * Ses referansı tek başına verilemez (yanında en az 1 görsel veya video şart).
   - LTX 2.5: Sadece Start veya Start+End Keyframe kabul eder. Harici ses veya video referansı almaz.
   - Keyframe modu (first_frame_image / last_frame_image) ile Full-Reference modu birbirini dışlar.
================================================================================
"""

import os
import re
import time
import json
import html
import secrets
import string
import mimetypes
from contextlib import ExitStack
import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

BASE_URL = "https://api.deapi.ai/api/v2"
APP_URL = "https://app.deapi.ai"

def random_box(length=10):
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length))

def random_name():
    first_names = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez"]
    return f"{secrets.choice(first_names)} {secrets.choice(last_names)}"

def random_password():
    chars = string.ascii_letters + string.digits
    return "DeApi#" + "".join(secrets.choice(chars) for _ in range(8)) + "1"

CACHED_SESSION = {
    "cf_cookies": {},
    "user_agent": None,
    "timestamp": 0
}

def get_registration_page(browser_manager):
    """
    Öncelikle mevcut cf_clearance çereziyle doğrudan curl_cffi üzerinden
    hızlıca /register sayfasını çekmeyi dener. Eğer Cloudflare engeli gelirse
    veya süresi dolmuşsa arka plan tarayıcısından yeni bir Turnstile oturumu alır.
    """
    global CACHED_SESSION
    now = time.time()
    
    # Eğer önbellekte cf_cookies varsa ve 35 dakikadan yeniyse doğrudan dene
    if CACHED_SESSION.get("cf_cookies") and CACHED_SESSION.get("user_agent") and (now - CACHED_SESSION.get("timestamp", 0) < 2100):
        try:
            print("[*] Mevcut cf_clearance önbelleği kontrol ediliyor (Hızlı Mod)...", flush=True)
            fast_session = cffi_requests.Session(impersonate="chrome120")
            if browser_manager.proxy:
                fast_session.proxies = {"http": browser_manager.proxy, "https": browser_manager.proxy}
            fast_session.cookies.update(CACHED_SESSION["cf_cookies"])
            fast_session.headers.update({
                "user-agent": CACHED_SESSION["user_agent"],
                "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            })
            r = fast_session.get(f"{APP_URL}/register", timeout=15)
            if r.status_code == 200 and "wire:snapshot" in r.text and "csrf-token" in r.text and "Just a moment" not in r.text:
                print("[+] Mevcut cf_clearance hâlâ aktif! Tarayıcı açılmadan 1 saniyede kayıt formu alındı.", flush=True)
                return fast_session, r.text, CACHED_SESSION["user_agent"]
        except Exception as fast_err:
            print(f"[*] Hızlı kontrol hatası: {fast_err}", flush=True)

    # Önbellek yoksa veya bayatlamışsa / hata vermişse tarayıcıdan taze Turnstile oturumu al
    print("[*] cf_clearance süresi dolmuş veya mevcut değil. Arka plan tarayıcısıyla yeni oturum alınıyor...", flush=True)
    session_data = browser_manager.get_fresh_session()
    raw_cookies = session_data["cookies"]
    ua = session_data["user_agent"]
    html_content = session_data["html"]

    # Sadece Cloudflare çerezlerini önbellekte tut, eski kullanıcı session çerezlerini at
    cf_cookies = {k: v for k, v in raw_cookies.items() if "cf" in k.lower()}
    if not cf_cookies:
        cf_cookies = raw_cookies

    CACHED_SESSION = {
        "cf_cookies": cf_cookies,
        "user_agent": ua,
        "timestamp": time.time()
    }

    session = cffi_requests.Session(impersonate="chrome120")
    if browser_manager.proxy:
        session.proxies = {"http": browser_manager.proxy, "https": browser_manager.proxy}
    session.cookies.update(raw_cookies)
    session.headers.update({
        "user-agent": ua,
        "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    return session, html_content, ua

def create_new_account_key(browser_manager) -> str:
    """
    Önbellekteki veya tarayıcıdan taze alınan cf_clearance ile
    hızlıca yeni bir hesap açar ve $5 kredili API anahtarını döndürür.
    """
    print("[*] Yeni hesap oluşturma süreci başlatılıyor...", flush=True)
    session, register_html, ua = get_registration_page(browser_manager)

    soup = BeautifulSoup(register_html, "html.parser")
    csrf_elem = soup.find("meta", {"name": "csrf-token"})
    if not csrf_elem:
        raise RuntimeError("Kayıt sayfasında CSRF token bulunamadı.")
    csrf_token = csrf_elem.get("content")

    elem = soup.find(attrs={"wire:snapshot": True})
    if not elem:
        raise RuntimeError("Kayıt sayfasında Livewire snapshot bulunamadı.")
    raw_snapshot = elem["wire:snapshot"]
    lw_script = soup.find("script", attrs={"data-update-uri": True})
    if lw_script:
        update_uri = lw_script["data-update-uri"]
        csrf_token = lw_script.get("data-csrf") or csrf_token
    else:
        update_uri = re.search(r'data-update-uri="([^"]+)"', register_html).group(1)
    if update_uri.startswith("/"):
        update_uri = APP_URL + update_uri

    box = random_box()
    email = f"{box}@tm.od2.in"
    name = random_name()
    password = random_password()

    print(f"[+] Oluşturulan Geçici Hesap: {email} | {name}", flush=True)

    # 1. Kayıt isteği (Livewire)
    payload = {
        "_token": csrf_token,
        "components": [
            {
                "snapshot": raw_snapshot,
                "updates": {
                    "name": name,
                    "email": email,
                    "password": password,
                    "password_confirmation": password
                },
                "calls": [{"method": "register", "params": [], "metadata": {}}]
            }
        ]
    }
    lw_headers = {
        "content-type": "application/json",
        "x-livewire": "1",
        "referer": f"{APP_URL}/register",
        "origin": APP_URL,
        "accept": "*/*",
    }
    r_post = session.post(update_uri, json=payload, headers=lw_headers)
    if r_post.status_code != 200:
        CACHED_SESSION["timestamp"] = 0
        raise RuntimeError(f"Kayıt isteği başarısız: HTTP {r_post.status_code}")

    # 2. Doğrulama e-postasını bekle (od2.in)
    print(f"[*] Aktivasyon e-postası bekleniyor (Kutu: {box})...", flush=True)
    verify_url = None
    t_start = time.time()
    while time.time() - t_start < 120:
        try:
            m_res = requests.get(
                "https://od2.in/api/get-email",
                params={"id": box},
                headers={
                    "user-agent": "Mozilla/5.0",
                    "accept": "*/*",
                    "referer": f"https://od2.in/temp-mail?id={box}",
                },
                timeout=15
            ).json()
            if m_res and isinstance(m_res, list) and len(m_res) > 0:
                for item in m_res:
                    email_id = item.get("_id")
                    if not email_id:
                        continue
                    try:
                        msg = requests.get(
                            "https://od2.in/api/get-email",
                            params={"emailId": email_id},
                            headers={"user-agent": "Mozilla/5.0"},
                            timeout=15
                        ).json()
                        content = (msg.get("text") or "") + "\n" + (msg.get("html") or "")
                        match = re.search(r'https://app\.deapi\.ai/verify-email/[^\s"\'<>]+', content)
                        if not match:
                            match = re.search(r'https?://[^\s"\'<>]*verify-email[^\s"\'<>]*', content)
                        if match:
                            raw_url = html.unescape(match.group(0))
                            verify_url = raw_url.rstrip("])}>.,;\"'")
                            print(f"[+] Doğrulama linki bulundu: {verify_url}", flush=True)
                            break
                    except Exception as sub_err:
                        print(f"[*] Mesaj detayı okuma hatası: {sub_err}", flush=True)
                if verify_url:
                    break
        except Exception:
            pass
        time.sleep(3)

    if not verify_url:
        raise RuntimeError("Doğrulama e-postası zamanında ulaşmadı.")

    # 3. E-postayı doğrula
    print("[+] E-posta onaylanıyor...", flush=True)
    session.get(verify_url)

    # 4. API Keys sayfasından yeni anahtar üret
    print("[+] API Keys sayfasından anahtar talep ediliyor...", flush=True)
    r_keys = session.get(f"{APP_URL}/settings/api-keys")
    soup_keys = BeautifulSoup(r_keys.text, "html.parser")
    
    lw_keys_script = soup_keys.find("script", attrs={"data-update-uri": True})
    if lw_keys_script:
        update_uri_keys = lw_keys_script["data-update-uri"]
        csrf_keys = lw_keys_script.get("data-csrf") or soup_keys.find("meta", {"name": "csrf-token"}).get("content")
    else:
        csrf_keys = soup_keys.find("meta", {"name": "csrf-token"}).get("content")
        update_uri_keys = re.search(r'data-update-uri="([^"]+)"', r_keys.text).group(1)
    if update_uri_keys.startswith("/"):
        update_uri_keys = APP_URL + update_uri_keys

    elem_keys = soup_keys.find("section", {"wire:name": "settings.api-keys"})
    if not elem_keys:
        elem_keys = soup_keys.find(attrs={"wire:snapshot": True})

    raw_snap_keys = elem_keys["wire:snapshot"]

    key_payload = {
        "_token": csrf_keys,
        "components": [
            {
                "snapshot": raw_snap_keys,
                "updates": {"keyName": f"Key_{random_box(4)}"},
                "calls": [{"method": "createKey", "params": [], "metadata": {}}]
            }
        ]
    }
    lw_headers["referer"] = f"{APP_URL}/settings/api-keys"
    r_create = session.post(update_uri_keys, json=key_payload, headers=lw_headers)

    m_key = re.search(r'\b(\d{5}\|[a-zA-Z0-9]{40,65})\b', r_create.text)
    if not m_key:
        m_key = re.search(r'createdKey\\?":\s*\\?"([^\\"]+)', r_create.text)

    if m_key:
        api_key = m_key.group(1)
        print(f"[OK] Yeni API Key başarıyla üretildi: {api_key}", flush=True)
        return api_key
    else:
        raise RuntimeError("API anahtarı yanıttan okunamadı.")

# =====================================================================
# DEAPI V2 API VE VİDEO YÖNETİMİ
# =====================================================================

def get_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key.strip()}",
        "Accept": "application/json"
    }

def fetch_models(api_key: str) -> list:
    url = f"{BASE_URL}/models?limit=50"
    try:
        resp = requests.get(url, headers=get_headers(api_key), timeout=25)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            models = []
            for m in data:
                itypes = m.get("inference_types", [])
                if any(t in ["txt2video", "img2video", "video_generation", "audio2video"] for t in itypes):
                    models.append(m)
            # MiniMax'ı ilk sıraya al
            models.sort(key=lambda x: 0 if "minimax" in x.get("slug", "").lower() else 1)
            return models
        return []
    except Exception:
        return []

def fetch_model_info(api_key: str, model_slug: str) -> dict:
    url = f"{BASE_URL}/models?limit=50"
    try:
        resp = requests.get(url, headers=get_headers(api_key), timeout=25)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            for m in data:
                if m.get("slug") == model_slug:
                    return m
        return {}
    except Exception:
        return {}

def open_clean_mime(stack: ExitStack, filepath: str):
    mime_type, _ = mimetypes.guess_type(filepath)
    if not mime_type:
        mime_type = "application/octet-stream"
    f = stack.enter_context(open(filepath, "rb"))
    return (os.path.basename(filepath), f, mime_type)

def estimate_price(api_key: str, is_animation: bool, payload: dict, ref_counts: dict) -> dict:
    endpoint = f"{BASE_URL}/videos/animations/price" if is_animation else f"{BASE_URL}/videos/generations/price"
    price_payload = {
        "model": payload["model"],
        "width": int(payload["width"]),
        "height": int(payload["height"]),
        "frames": int(payload["frames"]),
        "fps": 24, # deAPI'de daima ve sadece 24 FPS zorunludur
    }
    model_slug = payload.get("model", "")
    if "ltxv" in model_slug.lower():
        price_payload["steps"] = 1

    if is_animation:
        price_payload["ref_images_count"] = int(ref_counts.get("images", 0))
        price_payload["ref_videos_count"] = int(ref_counts.get("videos", 0))
        price_payload["ref_audios_count"] = int(ref_counts.get("audios", 0))

    try:
        resp = requests.post(endpoint, headers=get_headers(api_key), json=price_payload, timeout=20)
        if resp.status_code == 200:
            return resp.json().get("data", {})
        return {"error": resp.text, "status": resp.status_code}
    except Exception as e:
        return {"error": str(e)}

def submit_video_job(api_key: str, payload: dict, file_paths: dict) -> dict:
    """
    Video üretim isteğini API'ye iletir (Text-to-Video JSON veya Animation Multipart).
    Tüm referans ve keyframe kurallarını eksiksiz uygular.
    """
    payload["fps"] = 24 # deAPI'de daima ve sadece 24 FPS zorunludur
    model_slug = payload.get("model", "")
    if "ltxv" in model_slug.lower():
        payload["steps"] = 1
    else:
        payload.pop("steps", None)

    has_keyframes = bool(file_paths.get("first_frame") or file_paths.get("last_frame"))
    has_refs = bool(file_paths.get("ref_images") or file_paths.get("ref_videos") or file_paths.get("ref_audios"))

    # Kural Doğrulaması (deAPI v2 kuralları)
    if has_keyframes and has_refs:
        return {
            "success": False,
            "error": "deAPI Kural Hatası: Keyframe modu (İlk/Son Kare) ile Full-Reference modu (Referans Resim/Video/Ses) aynı anda kullanılamaz!"
        }

    if file_paths.get("last_frame") and not file_paths.get("first_frame"):
        return {
            "success": False,
            "error": "deAPI Kural Hatası: Son kare (last_frame) belirtebilmek için ilk kare (first_frame) de yüklenmelidir!"
        }

    if file_paths.get("ref_audios") and not (file_paths.get("ref_images") or file_paths.get("ref_videos")):
        return {
            "success": False,
            "error": "deAPI Kural Hatası: Ses referansı tek başına kullanılamaz! Yanında en az bir resim veya video referansı bulunmalıdır."
        }

    is_animation = has_keyframes or has_refs

    if is_animation:
        endpoint = f"{BASE_URL}/videos/animations"
        form_data = {}
        for k, v in payload.items():
            if v is not None:
                if isinstance(v, bool):
                    form_data[k] = "true" if v else "false"
                else:
                    form_data[k] = str(v)

        with ExitStack() as stack:
            files = []
            if file_paths.get("first_frame"):
                files.append(("first_frame_image", open_clean_mime(stack, file_paths["first_frame"])))
            if file_paths.get("last_frame"):
                files.append(("last_frame_image", open_clean_mime(stack, file_paths["last_frame"])))

            if file_paths.get("ref_images"):
                for idx, img_path in enumerate(file_paths["ref_images"]):
                    files.append((f"ref_images[{idx}]", open_clean_mime(stack, img_path)))

            if file_paths.get("ref_videos"):
                for idx, vid_path in enumerate(file_paths["ref_videos"]):
                    files.append((f"ref_videos[{idx}]", open_clean_mime(stack, vid_path)))

            if file_paths.get("ref_audios"):
                for idx, aud_path in enumerate(file_paths["ref_audios"]):
                    files.append((f"ref_audios[{idx}]", open_clean_mime(stack, aud_path)))

            try:
                resp = requests.post(endpoint, headers=get_headers(api_key), data=form_data, files=files, timeout=120)
            except Exception as e:
                return {"success": False, "error": f"API Bağlantı Hatası: {e}"}
    else:
        endpoint = f"{BASE_URL}/videos/generations"
        json_payload = {k: v for k, v in payload.items() if v is not None}
        try:
            resp = requests.post(endpoint, headers=get_headers(api_key), json=json_payload, timeout=60)
        except Exception as e:
            return {"success": False, "error": f"API Bağlantı Hatası: {e}"}

    if resp.status_code != 200:
        err_msg = resp.text
        try:
            err_json = resp.json()
            if "message" in err_json:
                err_msg = err_json["message"]
            if "errors" in err_json:
                err_msg += " -> " + json.dumps(err_json["errors"], ensure_ascii=False)
        except Exception:
            pass
        return {"success": False, "error": err_msg, "status_code": resp.status_code}

    data = resp.json().get("data", {})
    return {"success": True, "request_id": data.get("request_id"), "data": data}

def check_job_status(api_key: str, request_id: str) -> dict:
    url = f"{BASE_URL}/jobs/{request_id}"
    try:
        resp = requests.get(url, headers=get_headers(api_key), timeout=25)
        if resp.status_code == 200:
            return resp.json().get("data", {})
        return {"status": "error", "error": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def download_video_file(url: str, save_path: str):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    return save_path
