# price-check-assistant — Architecture v0.1

## 목표

공개 웹 PoC에서 검증된 동일 코드베이스를 병원 내부환경으로 이전할 수 있도록 UI, 도메인 로직, 데이터수집, 저장소를 분리한다.

## 계층

1. **UI (`Home.py`, `pages/`)**: Streamlit. 입력과 근거 표시만 담당.
2. **Services (`services/`)**: 제품정규화, 비교등급, 참고가격대, 신뢰도 등 핵심 규칙.
3. **Collectors (`collectors/`)**: 나라장터/API/공개웹별 어댑터. 장애가 다른 출처 검색을 막지 않게 격리.
4. **Repositories (`repositories/`)**: PostgreSQL 읽기/쓰기.
5. **Models (`models.py`)**: 제품·가격관측값의 영속 모델.

## 중요한 계약

- A/B만 직접 가격범위 계산에 사용한다.
- C/D는 참고자료, X는 비교 제외한다.
- 가격관측값에는 출처와 수집일을 필수로 둔다.
- 근거가 없으면 참고가격을 생성하지 않는다.
- 외부 수집기 결과와 내부 병원가격은 향후에도 source type을 분리한다.
- 공개 PoC 견적 업로드는 영구 저장하지 않는 것을 기본값으로 한다.
