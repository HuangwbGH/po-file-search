FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends cifs-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 18765
CMD ["python", "-m", "po_file_search", "--config", "config.json", "serve"]
