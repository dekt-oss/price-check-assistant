# OCR execution readiness

운영진단의 OCR READY는 설치 여부만 의미하지 않는다.

다음 단계가 모두 READY여야 한다.

1. `pypdfium2`, `pytesseract` Python 모듈
2. 사용 가능한 Tesseract 실행파일
   - `auto`: `kor+eng`가 완비된 system Tesseract를 우선 사용
   - system 구성이 불완전하거나 없는 Linux에서는 pinned `tesseract-bin==1.1.0` 실행파일로 fallback
3. Tesseract 명령 실행
4. `kor`, `eng` 언어모델
5. synthetic PDF를 생성하여 `pypdfium2`로 rasterize하고 Tesseract가 고정 토큰을 실제 인식하는 실행 검증

## Streamlit Community Cloud 배포 계약

스캔 PDF OCR은 더 이상 `packages.txt` 또는 Streamlit의 apt 설치 성공을 필수조건으로 두지 않는다. `packages.txt`는 두지 않으며, `packages.ocr.txt`는 OS 패키지를 사용할 수 있는 다른 배포환경을 위한 참고 manifest로만 유지한다.

Linux fallback은 Python wheel에 포함된 Tesseract 실행파일을 사용한다. `eng.traineddata`는 wheel에 포함된 모델을 로컬 cache로 복사하고, `kor.traineddata`가 없으면 공식 `tesseract-ocr/tessdata_fast`의 고정 버전 모델만 내려받는다. Korean 모델은 고정 SHA-512와 일치해야만 cache에 반영하며, 불일치하면 fail-closed한다.

언어모델 최초 준비 시 외부 네트워크를 사용할 수 있지만 **사용자 PDF 바이트, OCR 결과, 견적정보, 병원정보, 업체정보는 외부로 전송하지 않는다.** 실제 문서 OCR 처리는 계속 로컬 프로세스에서 수행한다.

GitHub `OCR Readiness` workflow는 `PRICE_CHECK_TESSERACT_MODE=bundled`로 system apt에 의존하지 않는 경로를 강제하고 다음을 실제 실행한다.

- runtime/hash/cache safeguard tests
- synthetic PDF rasterize → Tesseract execution
- image-only PDF → `kor+eng` OCR → production quote parser E2E

이 진단이 READY여도 실제 스캔 견적서의 인식 정확도를 보증하지 않는다. Production 실제 견적 OCR은 별도의 controlled UAT가 필요하다.
