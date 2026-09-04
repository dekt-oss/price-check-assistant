# Streamlit 웹 배포

## 목표

공개 PoC를 브라우저에서 접속 가능한 `streamlit.app` 주소로 배포한다.

이 저장소는 다음 파일을 포함해 Streamlit Community Cloud 배포 준비를 완료한다.

- `Home.py` — 앱 entrypoint
- `requirements.txt` — 저장소 자체 패키지를 editable install
- `.streamlit/config.toml` — headless/web 설정

## 배포 대상

- Repository: `dekt-oss/price-check-assistant`
- Branch: `main`
- Main file path: `Home.py`

## 필수 Secret

식약처와 나라장터의 활용승인/인증키가 서로 달라질 수 있으므로 source별 Secret을 분리한다.

```toml
MFDS_SERVICE_KEY = "<식약처 API에 승인된 공공데이터포털 서비스키>"
G2B_SERVICE_KEY = "<나라장터 API에 승인된 공공데이터포털 서비스키>"
```

기존 배포와 로컬 환경의 하위호환을 위해 `DATA_GO_KR_SERVICE_KEY`도 fallback으로 계속 지원한다.

```toml
DATA_GO_KR_SERVICE_KEY = "<기존 공공데이터포털 서비스키>"
```

우선순위는 `MFDS_SERVICE_KEY` / `G2B_SERVICE_KEY`가 각각 `DATA_GO_KR_SERVICE_KEY`보다 높다. 현재 두 source의 신규 키 값이 같더라도 Secret 이름은 분리해 둔다.

Streamlit의 root-level secrets는 환경변수로도 노출되므로 현재 `pydantic-settings` 환경변수 계약을 그대로 사용할 수 있다.

실제 키는 GitHub, `.env.example`, 문서, 화면, 로그에 넣지 않는다.

## Community Cloud 절차

1. `share.streamlit.io`에 GitHub 계정으로 로그인
2. GitHub public repository 접근 권한 연결
3. Create app
4. repository `dekt-oss/price-check-assistant` 선택
5. branch `main`
6. entrypoint `Home.py`
7. Python은 프로젝트 지원범위인 3.11 이상 선택
8. Advanced settings → Secrets에 `MFDS_SERVICE_KEY`, `G2B_SERVICE_KEY` 등록
9. 필요하면 기존 `DATA_GO_KR_SERVICE_KEY`도 그대로 유지
10. Deploy 또는 Reboot
11. 배포 URL에서 다음 smoke 확인
   - 홈 렌더
   - 통합검색 렌더
   - 견적서 분석 렌더
   - 의료기기 시장조사 렌더
   - 화면의 `API 연결설정 · 식약처: 설정됨 · 나라장터: 설정됨` 확인
   - 식약처 형명정보 live 호출
   - 식약처 업체 업허가 live 호출
   - 나라장터 live 호출
   - 서비스키 값이 화면/로그에 노출되지 않음

## 조회 실패와 0건의 구분

- API 인증/권한/통신 실패: `조회 실패`로 표시하고 0건으로 취급하지 않는다.
- API 호출이 정상 완료됐으나 항목이 없음: 실제 `검색결과 0건`으로 취급한다.
- 사용목적/주요사양 기반 대체탐색은 두 번째 경우에만 열어야 한다.

## 현재 한계

Community Cloud 배포 자체는 저장소 코드 변경만으로 완료되지 않는다. 최초 1회 GitHub OAuth/Streamlit 계정 권한 부여가 필요하다.

코드와 dependency/config는 저장소에서 준비하고, 계정 권한이 연결된 뒤 실제 배포 URL을 검증한다.
