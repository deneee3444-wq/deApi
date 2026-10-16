# deAPI.ai Web Studio - Render.com Dağıtım Kılavuzu

Bu proje, **deAPI.ai** için otomatik $5 kredili hesap açma, Cloudflare Turnstile bypass ve tam teşekküllü video üretim arayüzünü (Web UI) içeren Flask tabanlı bir stüdyodur.

---

## 🚀 Render.com Üzerinde Ücretsiz Deploy Etme Adımları

1. **GitHub Deposu Oluşturma:**
   * Bu `deApiAI/web` klasöründeki dosyaları kendi GitHub hesabınızda yeni bir depoya (repository) yükleyin veya mevcut deponuza ekleyin.

2. **Render.com'da Yeni Servis Açma:**
   * [Render Dashboard](https://dashboard.render.com/) adresine gidin.
   * **New +** butonuna basıp **Web Service** seçin.
   * GitHub deponuzu bağlayın.

3. **Servis Ayarları:**
   * **Language / Environment:** `Docker` seçin (Projedeki `Dockerfile` otomatik algılanacaktır).
   * **Region:** İstediğiniz bir lokasyon seçin (Örn: Frankfurt veya Oregon).
   * **Instance Type:** `Free` seçin.

4. **Ortam Değişkenleri (Environment Variables - Opsiyonel):**
   * Proxy değiştirmek isterseniz `PROXY` değişkeni ekleyebilirsiniz:
     * Key: `PROXY`
     * Value: `http://tghpxuwn:dxrsnpsyz3df@45.38.107.97:6014` (Varsayılan olarak kod içinde de ayarlıdır).

5. **Deploy:**
   * **Deploy Web Service** butonuna basın. Docker imajı derlenecek ve web siteniz canlıya alınacaktır!

---

## 💻 Yerel Ortamda Test Etme
Gerekli paketleri kurup doğrudan çalıştırabilirsiniz:
```bash
pip install -r requirements.txt
python app.py
```
Tarayıcınızda açın: `http://localhost:5000`
