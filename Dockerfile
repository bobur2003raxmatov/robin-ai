FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HOST=0.0.0.0 PORT=8000 DEPLOY_RESTART=true LOCAL_EXECUTION=false
RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN grep -vE '^(pyautogui|pynput|pywebview|playwright)' requirements.txt > req.txt && pip install -r req.txt
COPY . .
EXPOSE 8000
CMD ["python", "-m", "backend.main"]
