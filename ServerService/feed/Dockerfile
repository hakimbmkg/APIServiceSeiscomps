FROM python:3.9-slim-buster


WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Salin isi direktori saat ini ke dalam kontainer di /app
COPY . /app

RUN pip install --no-cache-dir obspy influxdb-client lxml numpy

# Jalankan main.py saat kontainer diluncurkan
CMD ["python3", "main.py"]