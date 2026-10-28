FROM python:3.12-alpine
WORKDIR /app
COPY app.py ./
COPY static ./static
RUN adduser -D app
USER app
EXPOSE 8080
CMD ["python", "app.py"]
