# 실제 견적 UAT 측정

기존 `data/uat/controlled_uat_template.csv`의 컬럼 구조를 그대로 사용해 실제 견적 검토 결과를 기록한다.

핵심 원칙:

- 사람 검토 결과를 ground truth로 두고 system 결과와 분리한다.
- false positive와 false negative를 별도로 기록한다.
- 특히 **false positive(다른 제품/조건을 동일비교로 잘못 승격)** 를 critical signal로 본다.
- false negative는 보수적 규칙의 비용을 측정하는 신호이며 반복된 실제 표본 없이 자동 규칙 완화 근거로 사용하지 않는다.
- 원문 URL, source record ID, fingerprint 추적성을 함께 기록한다.
- 수작업 시간, 시스템 사용시간, 시간절감, 재사용 가치(1~5)를 기록한다.

## 실행

```bash
python -m purchase_price.scripts.summarize_real_quote_uat \
  --input path/to/reviewed-real-uat.csv \
  --output-dir artifacts/real-quote-uat
```

출력:

- `real-quote-uat-summary.json`
- `real-quote-uat-summary.md`

요약 지표:

- 제품식별 FP/FN 건수·비율
- 비교판정 FP/FN 건수·비율
- API 정상 0건 / 실패 구분 오류
- 직접가격 근거 회수율
- source record / URL / fingerprint 추적성 성공률
- 평균 수작업·시스템 시간
- 평균/중앙 시간절감
- 평균 재사용 가치
- critical false positive / critical error 합계

실제 견적 파일 자체를 저장소에 넣을 필요는 없다. 병원 내부 문서나 민감정보는 저장소에 커밋하지 않고, 검토자가 비식별 결과 행만 작성한다.
