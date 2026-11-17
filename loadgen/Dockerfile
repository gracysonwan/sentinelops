FROM python:3.11-slim
WORKDIR /app
COPY loadgen.py .
ENV PYTHONUNBUFFERED=1
CMD ["python", "loadgen.py"]
