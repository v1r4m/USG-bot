FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 의존성을 먼저 설치해 레이어 캐시를 활용합니다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사.
COPY hayangi ./hayangi

# 보안을 위해 비루트 사용자로 실행합니다.
RUN useradd --create-home --uid 1000 hayangi \
    && mkdir -p /app/data \
    && chown hayangi:hayangi /app/data
USER hayangi

CMD ["python", "-m", "hayangi"]
