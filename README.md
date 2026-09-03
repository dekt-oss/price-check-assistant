# price-check-assistant

공개된 외부 가격자료를 수집·정리해 구매 담당자의 시장가격 검토를 보조하는 공개 PoC입니다. 1차 적용 맥락은 병원 관리부 구매업무이며, 향후 내부 이식을 고려한 구조로 설계합니다.

> 현재 버전은 **초기 골격(v0.1)** 입니다. 실제 나라장터·제조사·유통 가격 수집기는 아직 연결하지 않았고, end-to-end 확인을 위한 개발용 샘플 수집기만 포함합니다.


## 공개 저장소 운영 경계

이 저장소는 초기 PoC 단계에서 **Public**으로 운영합니다. 따라서 다음 자료는 커밋하지 않습니다.

- 실제 본원 구매단가 및 거래업체별 계약단가
- 실제 업체 견적서 원본 및 내부 결재문서
- 개인정보·병원 내부정보가 포함된 파일
- API 키, 비밀번호, 토큰 등 secret

공개 저장소에는 공개정보, 샘플 데이터, 비식별 테스트 자료만 포함합니다. 실제 내부자료 연계는 별도 승인 후 비공개/내부 환경에서 수행합니다.

## 기술 스택

- Python 3.11+
- Streamlit
- PostgreSQL 16
- SQLAlchemy 2
- pytest

## Windows 빠른 실행

### 가장 쉬운 방법

PowerShell에서 프로젝트 폴더로 이동한 뒤:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
.\scripts\run.ps1
```

`setup.ps1`은 가상환경 생성, Python 패키지 설치, PostgreSQL 시작, DB 테이블 생성, 샘플 데이터 입력까지 수행합니다.

### 수동 방법

#### 1. 사전 준비

- Python 3.11 이상
- Docker Desktop
- Git

#### 2. 프로젝트 환경

PowerShell에서:

```powershell
cd price-check-assistant
Copy-Item .env.example .env
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
```

#### 3. PostgreSQL 시작

```powershell
docker compose up -d db
```

#### 4. DB 테이블 생성

```powershell
python -m purchase_price.scripts.init_db
python -m purchase_price.scripts.seed_demo
```

#### 5. Streamlit 실행

```powershell
streamlit run Home.py
```

브라우저에서 일반적으로 `http://localhost:8501`이 열립니다.

## 샘플 검색

통합검색에서 모델명에 `XYZ-100`을 입력하면 개발용 가격관측값이 나타납니다. 이 값은 **실제 시장자료가 아닙니다.**

## 테스트

```powershell
pytest -q
ruff check .
```

## 구조

```text
Home.py / pages/             Streamlit UI
src/purchase_price/services  제품매칭·가격분석 규칙
src/purchase_price/collectors 외부 데이터 source adapter
src/purchase_price/repositories PostgreSQL 접근
src/purchase_price/models.py 제품·가격관측 DB 모델
data/                        Phase 0 조사 템플릿
docs/                        설계·다음 구현순서
tests/                       핵심 규칙 테스트
```

## 보안 원칙

- 실제 본원 구매단가를 공개 PoC에 저장하지 않습니다.
- 실제 견적서 업로드는 내부 승인 전 영구 저장하지 않는 구조를 기본값으로 합니다.
- API 키/비밀번호는 `.env` 또는 배포환경의 secret으로 관리하고 Git에 커밋하지 않습니다.

## 다음 작업

가장 먼저 **Phase 0 대표품목 10~20개와 첫 실제 공개 데이터 source**를 확정한 뒤, `collectors/`에 실제 수집기 하나를 end-to-end로 구현합니다. 자세한 순서는 `docs/NEXT_IMPLEMENTATION.md`를 참고하세요.
