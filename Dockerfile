FROM python:3.12-alpine
WORKDIR /app
COPY app.py ./
COPY static ./static
RUN adduser -D app && mkdir /data && chown app:app /data
USER app
ENV DATA_DIR=/data
EXPOSE 8080
CMD ["python", "app.py"]
