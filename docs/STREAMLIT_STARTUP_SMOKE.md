# Streamlit page startup smoke gate

Production에서 페이지 모듈 import 단계의 런타임 의존성 누락을 CI가 놓치지 않도록 모든 Streamlit entrypoint를 실제 ScriptRunner로 초기 실행한다.

## 대상

- `Home.py`
- `pages/*.py` 전체

## 검증 방식

`streamlit.testing.v1.AppTest`로 각 파일을 실행하고 `app.exception`이 비어 있음을 확인한다. 사용자의 버튼 클릭은 수행하지 않으므로 외부 API 검색이나 실제 구매판정 작업은 시작하지 않는다.

## 잡아야 하는 문제

- 배포환경 런타임 dependency 누락으로 인한 `ModuleNotFoundError`
- 페이지 import 시점의 잘못된 설정/파일 참조
- Streamlit 초기 render 단계의 예외

## 잡지 않는 문제

- 실제 G2B/MFDS API 성공 여부
- 사용자가 파일을 업로드한 뒤의 전체 workflow
- Streamlit Community Cloud 자체의 배포/네트워크 장애

따라서 이 gate는 live UAT를 대체하지 않고, Production startup 회귀를 조기에 차단하는 역할만 한다.
