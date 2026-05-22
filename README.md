# 🤍 하양이 (Hayangi)

USG CTF 팀을 위한 디스코드 봇입니다. CTF 대회 운영을 도와주는 헬퍼 봇을 목표로,
[Eruditus](https://github.com/hfz1337/Eruditus) 프로젝트에서 영감을 받아 만들고 있습니다.

> **이름 유래** — 화이트햇 해커(white hat) → **하양이** 🤍

## 현재 상태

`v0.2.0` — **CTF 라이프사이클 단계**. 봇이 디스코드에 접속하고, CTF 대회를
카테고리·채널·역할 단위로 만들고 관리할 수 있습니다.

### 명령어

| 명령어 | 설명 | 필요 권한 |
| --- | --- | --- |
| `/help` | 사용할 수 있는 명령어를 보여줍니다 | 누구나 |
| `/ping` | 봇 상태와 응답 지연을 확인합니다 | 누구나 |
| `/ctf create <이름>` | 새 CTF 생성 (카테고리·채널·전용 역할 자동 생성) | 채널·역할 관리 |
| `/ctf join <이름>` | 진행 중인 CTF에 참가 | 누구나 |
| `/ctf leave <이름>` | 참가 중인 CTF에서 나가기 | 누구나 |
| `/ctf list` | 이 서버의 CTF 목록 보기 | 누구나 |
| `/ctf archive <이름>` | CTF 보관 (채널을 읽기 전용으로 전환) | 채널 관리 |
| `/ctf unarchive <이름>` | 보관한 CTF를 다시 활성화 | 채널 관리 |
| `/ctf delete <이름>` | CTF 완전 삭제 (확인 후, 되돌릴 수 없음) | 채널·역할 관리 |

## 동작 방식 — 별도 DB 없음

하양이는 데이터베이스 없이 **Discord 자체를 상태 저장소**로 사용합니다.

- **CTF 1개** = 카테고리 1개 + 그와 이름이 같은 전용 역할 1개
- 카테고리는 `@everyone` 에게 숨겨지고, 전용 역할을 가진 멤버만 채널을 봅니다
- `/ctf join` 은 역할을 부여하고, `/ctf leave` 는 역할을 회수합니다
- **보관**된 CTF는 카테고리 이름 앞에 `🗄️` 가 붙고 채널이 읽기 전용이 됩니다

> ⚠️ 하양이가 만든 카테고리·역할을 손으로 삭제하거나 이름을 바꾸면
> 봇이 해당 CTF를 인식하지 못할 수 있습니다.

## 기술 스택

- Python 3.12+
- [discord.py](https://discordpy.readthedocs.io/) 2.5+ (슬래시 커맨드)
- Docker / Docker Compose (배포)

## 빠른 시작

### 1. 디스코드 봇 만들기

1. [Discord Developer Portal](https://discord.com/developers/applications) 에서 **New Application** 으로 애플리케이션 생성
2. **Bot** 탭에서 봇을 만들고 **Reset Token** 으로 토큰 발급 → 복사해 둡니다
3. **OAuth2 → URL Generator** 에서 아래를 선택하고 생성된 URL로 봇을 서버에 초대합니다
   - **Scopes**: `bot`, `applications.commands`
   - **Bot Permissions**: `Manage Roles`, `Manage Channels`, `View Channels`,
     `Send Messages`, `Embed Links`, `Read Message History`
4. 서버 설정 → **역할** 에서 **하양이의 역할을 CTF 참가 역할들보다 위로** 올려 주세요.
   (역할은 자기보다 낮은 역할만 관리할 수 있습니다.)

### 2. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어 값을 채웁니다.

- `DISCORD_TOKEN` — 위에서 발급받은 봇 토큰 (**필수**)
- `DISCORD_GUILD_ID` — 개발 중인 서버 ID. 지정하면 슬래시 커맨드가 즉시 반영됩니다 (선택)
- `LOG_LEVEL` — 로그 레벨 (선택, 기본값 `INFO`)

### 3. 실행

**로컬 실행**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m hayangi
```

**Docker 실행**

```bash
docker compose up -d --build
```

## 프로젝트 구조

```
usg-bot/
├── hayangi/                # 봇 패키지
│   ├── __main__.py         # 실행 진입점 (python -m hayangi)
│   ├── bot.py              # HayangiBot — 봇 본체, 확장 로드 / 커맨드 동기화 / 오류 처리
│   ├── config.py           # 환경 변수 기반 설정
│   ├── logger.py           # 로깅 설정
│   ├── ctf.py              # CTF 상태 추론 로직 (DB 없이 Discord에서 추론)
│   └── cogs/               # 명령어 모듈(코그)
│       ├── general.py      # /help, /ping
│       └── ctf.py          # /ctf 명령어 그룹
├── requirements.txt
├── pyproject.toml          # ruff 설정
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

새 기능은 `hayangi/cogs/` 에 코그를 추가하고 `hayangi/bot.py` 의
`INITIAL_EXTENSIONS` 에 등록하면 됩니다.

## 로드맵

- [x] 프로젝트 뼈대 · 봇 접속 · `/help`, `/ping`
- [x] CTF 라이프사이클: 생성 / 참가 / 보관 / 삭제
- [x] 채널 · 역할 · 권한 자동 관리
- [ ] 챌린지 등록 및 진행 상황 추적
- [ ] 플래그 제출 (CTFd / rCTF 연동)
- [ ] CTFtime 연동 (다가오는 대회 알림)
- [ ] 인코딩 / 암호 유틸리티
