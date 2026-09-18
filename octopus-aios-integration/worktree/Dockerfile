FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY . .
RUN python -m pip install --upgrade pip setuptools wheel     && python -m pip install .     && python -m pip install cryptography psutil
CMD ["python", "/deploy/run_node.py", "/etc/octopus/config.yaml", "8000"]
