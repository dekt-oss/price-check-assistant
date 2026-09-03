# G2B Ground Truth Evidence

이 디렉터리는 F3 제품 동일성 matcher의 **실제 공개자료 검증용 최소 Evidence**만 보관합니다.

## 2026-07-14 ~ 2026-08-13 표본

파일: `f3_ground_truth_sample_20260714_20260813.csv`

- 원천: 조달청 나라장터쇼핑몰 품목정보 서비스
- operation: `getSpcifyPrdlstPrcureInfoList`
- capture run: https://github.com/dekt-oss/price-check-assistant/actions/runs/33767200916
- capture artifact digest: `sha256:773f156bb07726557a6d54b86cb8880492125aa042ca8f358e49e3f98d05c363`
- 조회기간: 2026-07-14 ~ 2026-08-13
- verified 분류: `인공호흡기` / `노트북컴퓨터`
- live 결과: Sophie 분류 9건, NT960XJG-K72AG 분류 1,021건
- Ground Truth 표본 수집: Sophie 9건 전체 + 노트북 첫 페이지 100건 중 25건
- 이 디렉터리에는 동일 identity 반복을 제거한 대표 10건만 보존

## 주의

- 이 파일은 **완전수집 결과가 아니라 matcher 검증용 표본**입니다.
- `DATA_GO_KR_SERVICE_KEY` 등 인증정보는 저장하지 않습니다.
- 공개 API 응답의 제품명·레코드 ID·가격·일자·수량 등 Ground Truth 검토에 필요한 필드만 보존합니다.
- `expected_grade`는 이 Evidence 파일에 넣지 않습니다. 사람 검토 결과는 `data/phase0_match_ground_truth.csv`에서 별도로 관리합니다.
- 해당 조회기간의 전체 분류 스캔에서 두 benchmark 모두 exact 모델 토큰 후보가 0건이었으므로, 이 표본만으로 A/B precision·recall을 검증할 수는 없습니다.
