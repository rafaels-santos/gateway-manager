FROM python:3.12-alpine
WORKDIR /app
COPY app.py ./
COPY services ./services
COPY gateway_adapters ./gateway_adapters
COPY static ./static
RUN adduser -D app && mkdir /data && chown app:app /data
USER app
ENV DATA_DIR=/data PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "app.py"]
