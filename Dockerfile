FROM python:3.8

WORKDIR /app
COPY requirements.txt ./
RUN pip3.8 install --no-cache-dir -r requirements.txt
COPY hub.py ./
COPY hub_config.ini ./

CMD ["python3.8", "/app/hub.py"]