FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py vaultdrop_cli.py ./
COPY templates ./templates
COPY static ./static
ENV VAULTDROP_DIR=/data
VOLUME ["/data"]
EXPOSE 5000
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "server:app"]
