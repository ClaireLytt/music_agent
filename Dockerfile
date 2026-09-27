FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir ".[all]"

COPY data/ data/
COPY scripts/ scripts/

EXPOSE 7860

CMD ["lyric-agent", "serve", "--port", "7860"]
