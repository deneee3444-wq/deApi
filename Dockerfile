# ==========================================
# Dockerfile for Render.com Deployment
# ==========================================
FROM python:3.10-slim

# Temel ortam değişkenleri
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=5000

WORKDIR /app

# Chromium ve CloakBrowser için gerekli Linux sistem kütüphaneleri
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    gnupg \
    ca-certificates \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Gereksinimleri yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium bağımlılıklarını doğrula
RUN playwright install chromium || true

# Uygulama kodlarını kopyala
COPY . .

# Çıktı ve yükleme klasörlerini oluştur
RUN mkdir -p uploads outputs browser_profile

EXPOSE 5000

# Tek process çalışması (BrowserManager'ın tek bir thread'de tarayıcıyı tutması için)
CMD ["python", "app.py"]
