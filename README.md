# 🤍 하양이 (Hayangi)

USG CTF 팀을 위한 디스코드 봇입니다. CTF 대회 운영을 도와주는 헬퍼 봇을 목표로,
[Eruditus](https://github.com/hfz1337/Eruditus) 프로젝트에서 영감을 받아 만들고 있습니다.

> **이름 유래** — 화이트햇 해커(white hat) → **하양이** 🤍

## 현재 상태

`v0.3.0` — **문제 관리 + CTFd 연동 단계**. CTF 대회를 카테고리·채널·역할 단위로
관리하고, 문제마다 스레드를 만들어 풀이 현황을 추적합니다. CTFd 대회와 연동하면
문제를 자동으로 가져오고 새 문제·우리 팀 풀이를 주기적으로 반영합니다.

### 명령어

| 명령어 | 설명 | 필요 권한 |
| --- | --- | --- |
| `/help` | 사용할 수 있는 명령어를 보여줍니다 | 누구나 |
| `/ping` | 봇 상태와 응답 지연을 확인합니다 | 누구나 |
| `/ctf create <이름> [url] [token]` | 새 CTF 생성 (카테고리·채널·전용 역할 자동 생성). `url`·`token` 을 주면 CTFd 와 바로 연동 | 채널·역할 관리 |
| `/ctf join <이름>` | 진행 중인 CTF에 참가 | 누구나 |
| `/ctf leave <이름>` | 참가 중인 CTF에서 나가기 | 누구나 |
| `/ctf list` | 이 서버의 CTF 목록 보기 | 누구나 |
| `/ctf archive <이름>` | CTF 보관 (채널을 읽기 전용으로 전환) | 채널 관리 |
| `/ctf unarchive <이름>` | 보관한 CTF를 다시 활성화 | 채널 관리 |
| `/ctf delete <이름>` | CTF 완전 삭제 (확인 후, 되돌릴 수 없음) | 채널·역할 관리 |
| `/chal add <이름> <카테고리> [설명]` | 현재 CTF에 문제 스레드 만들기 | 누구나 (CTF 참가자) |
| `/chal solve` | 문제 스레드 안에서 해결 표시 (`✅`) + 공지 | 누구나 |
| `/chal unsolve` | 해결 표시 취소 | 누구나 |
| `/chal list` | 현재 CTF의 문제 목록과 풀이 현황 | 누구나 |
| `/ctfd link <url> <token> [ctf]` | CTF를 CTFd 대회와 연동하고 문제 가져오기 | 채널 관리 |
| `/ctfd sync [ctf]` | CTFd 에서 지금 바로 동기화 | 채널 관리 |
| `/ctfd unlink [ctf]` | 연동 해제 (저장된 토큰 삭제, 스레드는 유지) | 채널 관리 |
| `/ctfd status` | 연동 현황 보기 | 채널 관리 |

`[ctf]` 를 비우면 명령을 실행한 채널이 속한 CTF 가 대상이 됩니다.

## 동작 방식 — 별도 DB 없음

하양이는 데이터베이스 없이 **Discord 자체를 상태 저장소**로 사용합니다.

- **CTF 1개** = 카테고리 1개 + 그와 이름이 같은 전용 역할 1개
- 카테고리는 `@everyone` 에게 숨겨지고, 전용 역할을 가진 멤버만 채널을 봅니다
- `/ctf join` 은 역할을 부여하고, `/ctf leave` 는 역할을 회수합니다
- **보관**된 CTF는 카테고리 이름 앞에 `🗄️` 가 붙고 채널이 읽기 전용이 됩니다

- **문제 카테고리** = CTF 카테고리 안의 `#🧩-<카테고리>` 채널 (토픽으로 식별)
- **문제 1개** = 그 채널의 공개 스레드 1개. 해결하면 스레드 이름 앞에 `✅` 가 붙습니다
  (스레드를 쓰기 때문에 문제가 많아도 카테고리당 채널 50개 제한에 걸리지 않아요)

> ⚠️ 하양이가 만든 카테고리·역할을 손으로 삭제하거나 이름을 바꾸면
> 봇이 해당 CTF를 인식하지 못할 수 있습니다.

### CTFd 연동

CTFd 인증 정보만큼은 채널에 남기면 안 되므로 봇 서버의 `DATA_DIR/ctfd.json`
(권한 600, Docker 에서는 `hayangi-data` 볼륨)에 따로 저장합니다.

- **인증**: CTFd 설정 → *Access Tokens* 에서 발급한 토큰(`ctfd_...`) 권장.
  토큰 발급을 막아 둔 대회라면 브라우저의 `session` 쿠키 값을 넣어도 됩니다.
  팀 계정으로 로그인한 토큰이어야 우리 팀 풀이가 반영돼요.
- **자동 동기화**: `CTFD_POLL_MINUTES` (기본 5분) 마다 새 문제는 스레드를 만들고,
  우리 팀이 푼 문제는 `✅` 표시 후 `📢-공지` 에 알립니다. 보관된 CTF는 건너뜁니다.
- 새 문제 스레드에는 설명·점수·태그·접속 정보·첨부 파일 링크가 들어갑니다.
- `/chal add` 로 미리 만든 같은 이름의 스레드가 있으면 새로 만들지 않고 이어 씁니다.
- 손으로 `/chal unsolve` 한 문제는 다시 자동 해결 처리하지 않습니다.
- 토큰이 채팅에 남지 않도록 `/ctfd link` 의 응답은 본인에게만 보입니다.

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
     `Send Messages`, `Embed Links`, `Read Message History`,
     `Create Public Threads`, `Send Messages in Threads`, `Manage Threads`
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
- `DATA_DIR` — CTFd 연동 정보 저장 위치 (선택, 기본값 `data`, Docker 에서는 `/app/data` 로 고정)
- `CTFD_POLL_MINUTES` — CTFd 확인 주기(분) (선택, 기본값 `5`)

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
│   ├── challenges.py       # 문제 채널·스레드 추론 로직
│   ├── ctfd.py             # CTFd REST API 클라이언트
│   ├── store.py            # CTFd 연동 정보(JSON) 저장소
│   └── cogs/               # 명령어 모듈(코그)
│       ├── general.py      # /help, /ping
│       ├── ctf.py          # /ctf 명령어 그룹
│       ├── chal.py         # /chal 명령어 그룹
│       └── ctfd.py         # /ctfd 명령어 그룹 + 자동 동기화
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
- [x] 챌린지 등록 및 진행 상황 추적
- [x] CTFd 연동: 문제 자동 가져오기 · 새 문제 / 풀이 자동 반영
- [ ] 플래그 제출 (CTFd / rCTF 연동)
- [ ] rCTF 등 다른 플랫폼 지원
- [ ] CTFtime 연동 (다가오는 대회 알림)
- [ ] 인코딩 / 암호 유틸리티
