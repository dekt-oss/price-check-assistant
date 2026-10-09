# 병원 News Radar 즉시 알림 설정 (카카오톡 · 이메일 · 문자)

10분마다 도는 수집 작업(`.github/workflows/news-radar-collect.yml`)이 새 기사를 찾으면, **제목에 키워드가
실제로 들어 있는** "즉시" 키워드 기사만 알림으로 보냅니다. 본문에만 단어가 있는 기사는 보내지 않습니다.
채널은 `data/news_keywords.json`의 그룹별 `notify`로 정합니다.

| 그룹 | 언제 | 채널 |
| --- | --- | --- |
| 우리병원 (부산백병원·인제대 백병원·백중앙의료원) | 제목에 나오면 즉시(10분 이내) | 카카오톡, 이메일, 문자, 웹훅, 이메일 구독자 |
| 같은 의료원 병원·경쟁병원·경영·AI·구매 | 매일 오전 8시 30분 요약 | 요약 구독자 이메일, 작업 요약 |

우리병원 즉시 알림은 좋은 기사·나쁜 기사를 가리지 않고, 제목에 우리병원이 나오면 모두 보냅니다
(2026-09-18~10-05 저장분 기준 14건: 모자의료센터 10주년, 김해 분원 논의, 소방 합동훈련, 임금협약 등).

필요한 값은 모두 GitHub 저장소 → Settings → Secrets and variables → Actions → **New repository secret**에
넣습니다. 값이 없는 채널은 조용히 건너뛰고, 값은 로그에 나오지 않습니다. 알림 내용은 기사 제목·출처·시각·링크뿐이며
AI를 거치지 않습니다(네이버 검색 API 이용약관).

## 1. 이메일 (가장 쉬움, 무료)

Gmail 예시:
1. Google 계정 → 보안 → **2단계 인증** 켜기.
2. Google 계정 → 보안 → **앱 비밀번호** 만들기(앱 이름 예: News Radar). 16자리 비밀번호가 나옵니다.
3. Secrets 등록:

| 이름 | 값 |
| --- | --- |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | 보내는 Gmail 주소 |
| `SMTP_PASSWORD` | 2번의 앱 비밀번호 |
| `ALERT_EMAIL_TO` | 받을 주소(여러 명은 쉼표로) |

## 2. 카카오톡 "나에게 보내기" (무료, 본인 카톡으로 받음)

1. <https://developers.kakao.com> 로그인 → 내 애플리케이션 → **애플리케이션 추가하기**.
2. 앱 설정 → 앱 키에서 **REST API 키** 확인.
3. 제품 설정 → **카카오 로그인** 활성화, Redirect URI 등록(예: `https://localhost:8080/kakao`).
4. 제품 설정 → 카카오 로그인 → 동의항목에서 **카카오톡 메시지 전송(talk_message)** 을 "선택 동의"로 설정.
5. 앱 설정 → 플랫폼 → **Web** 에 `https://bp-price-research.streamlit.app` 등록(알림의 "News Radar 열기" 버튼 링크).
6. 리프레시 토큰 받기(처음 한 번):

```bash
python -m purchase_price.scripts.kakao_refresh_token --rest-key <REST API 키> --redirect-uri https://localhost:8080/kakao
```

   출력된 주소를 브라우저에서 열고 동의하면 `https://localhost:8080/kakao?code=...`로 이동합니다(페이지가 안 열려도 됩니다).
   주소창의 `code=` 뒤 값을 복사해 다시 실행합니다.

```bash
python -m purchase_price.scripts.kakao_refresh_token --rest-key <REST API 키> --redirect-uri https://localhost:8080/kakao --code <복사한 값>
```

7. Secrets 등록: `KAKAO_REST_API_KEY`, `KAKAO_REFRESH_TOKEN`(6번 출력값). 앱에서 Client Secret을 켰다면
   `KAKAO_CLIENT_SECRET`도 넣습니다.

리프레시 토큰은 약 2개월 유효하고, 남은 기간이 1개월 미만이면 카카오가 새 토큰을 줍니다. 수집 작업이 새 토큰을
R2(`private/v1/kakao_refresh_token.json`)에 저장하고 다음부터 그 값을 쓰므로 Secret은 처음 한 번만 넣으면 됩니다.
"나에게 보내기"는 앱에 동의한 **본인 카톡**으로만 갑니다. 다른 직원에게 보내려면 각자 동의가 필요한 친구 API나
유료 알림톡(비즈니스 채널)이 필요합니다.

## 3. 문자 (유료, SOLAPI)

1. <https://solapi.com> 가입, 충전(단문 문자 약 20원, 장문 약 50원 수준 — 가입 시 요금표 확인).
2. **발신번호 등록**(본인 휴대폰 또는 병원 대표번호, 인증 필요).
3. 콘솔 → 개발/연동 → **API Key 관리**에서 API Key / API Secret 발급.
4. Secrets 등록:

| 이름 | 값 |
| --- | --- |
| `SOLAPI_API_KEY` | API Key |
| `SOLAPI_API_SECRET` | API Secret |
| `SMS_FROM` | 등록한 발신번호 |
| `SMS_TO` | 받을 번호(여러 개는 쉼표로) |

문자는 우리병원 그룹에만 보내고, 한 번에 "첫 기사 제목 + 외 N건 + News Radar 주소" 한 통만 보냅니다.

## 확인 방법

GitHub → Actions → **News Radar Collect** → Run workflow(mode=collect). 우리병원 즉시 키워드의 새 기사가 있으면
작업 요약의 "즉시 알림" 줄에 `kakao sent, email sent, sms sent`처럼 채널별 결과가 나옵니다. 새 기사가 없으면
"not needed"입니다.

## 4. 직원이 직접 이메일 알림 신청하기 (확인 메일 방식)

News Radar 화면 맨 아래 **이메일 알림 받기**에서 주소를 넣고 "우리병원 기사 즉시 알림"과
"매일 아침 병원 동향 요약" 중 원하는 것을 고릅니다. 10분 안에 확인 메일이 가고, 메일 속 링크를 눌러야
알림이 시작됩니다. 모든 알림 메일 끝에 수신 거부 링크가 있고, 누르면 등록 정보가 바로 지워집니다.
확인하지 않은 신청은 7일 뒤 지웁니다. 같은 주소는 하루 3번까지만 신청할 수 있습니다.

신청 명단은 증거 자료와 섞이지 않도록 **별도 R2 버킷**에 둡니다. 처음 한 번 설정:

1. Cloudflare 대시보드 → R2 → **Create bucket** → 이름 예: `price-check-subscribers`.
2. R2 → **Manage R2 API Tokens** → Create API token → 권한 **Object Read & Write**,
   적용 버킷은 1번 버킷만 지정 → Access Key ID / Secret Access Key 복사.
3. Streamlit Cloud 앱 → Settings → Secrets에 추가(앱이 신청을 저장):

```toml
SUBSCRIBER_R2_BUCKET = "price-check-subscribers"
SUBSCRIBER_R2_ACCESS_KEY_ID = "2번 Access Key ID"
SUBSCRIBER_R2_SECRET_ACCESS_KEY = "2번 Secret Access Key"
```

4. GitHub Secrets에도 같은 세 이름으로 추가(수집 작업이 확인 메일·알림을 보냄). 이메일 발송용 `SMTP_*`
   Secrets(1번 항목)도 있어야 메일이 나갑니다.

설정 전에는 화면에 "이메일 알림 신청은 관리자 설정이 끝나면 열립니다"라고만 나옵니다.
