# OCR execution readiness

운영진단의 OCR READY는 설치 여부만 의미하지 않는다.

다음 단계가 모두 READY여야 한다.

1. `pypdfium2`, `pytesseract` Python 모듈
2. Tesseract 실행파일
3. Tesseract 명령 실행
4. `kor`, `eng` 언어팩
5. synthetic PDF를 생성하여 `pypdfium2`로 rasterize하고 Tesseract가 고정 토큰을 실제 인식하는 실행 검증

synthetic 검증에는 사용자 문서, 견적정보, 병원정보, 업체정보를 사용하지 않으며 외부 네트워크도 사용하지 않는다.

이 진단이 READY여도 실제 스캔 견적서의 인식 정확도를 보증하지 않는다. Production 실제 견적 OCR은 별도의 controlled UAT가 필요하다.
