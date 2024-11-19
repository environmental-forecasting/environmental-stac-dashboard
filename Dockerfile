FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
COPY . /app

RUN pip install --no-cache-dir -r /tmp/requirements.txt

EXPOSE 8001

# Setting PYTHONPATH to `/app/src` so Gunicorn can find the submodules, else, error.
ENV PYTHONPATH=/app/src

CMD ["gunicorn", "src.app:server", "-b", "0.0.0.0:8001"]
