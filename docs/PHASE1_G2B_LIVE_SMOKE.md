# Phase 1-B — G2B 사용자검색 live end-to-end 검증

작성: 2026-09-04

## 목적

Phase 1-A(PR #29)는 검증된 G2B 검색을 사용자 화면에 연결했지만, 검증은 fixture 기반 CI뿐이었다. fixture는 배선(wiring)은 확인하지만 **live 서비스와의 계약**은 확인하지 못한다. 파라미터 이름, 응답 envelope, pagination totalCount, verified mapping은 테스트를 하나도 깨뜨리지 않고 드리프트할 수 있다.

이 문서는 실제 서비스키 환경에서 다음 전 구간을 호출한 결과를 기록한다.

```text
UI 진입점 → collector registry → adaptive G2B search → live API
  → parser → matcher(F3) → pricing safety gate → 사용자 표시값
```

## 재현 방법

```bash
python -m purchase_price.scripts.run_g2b_user_search_smoke \
  --lookback-days 90 \
  --quote 3500000 \
  --output-dir artifacts/g2b-live-smoke
```

이 스크립트는 `pages/1_통합검색.py`가 호출하는 것과 **동일한 진입점**(`build_collectors()` → `search_all()` → `assess_prices()`)을 사용한다. 따라서 통과하면 사용자 화면 자체가 동작한다는 뜻이다.

- `DATA_GO_KR_SERVICE_KEY`가 없으면 exit 2로 skip한다. **CI에서 실행되지 않는다.**
- 서비스키는 출력하지 않는다.
- 결과 0건은 정상 결과다(해당 기간에 조달실적이 없을 수 있음). 따라서 **pipeline 고장**(collector 오류, 키가 있는데 G2B collector 미구성)일 때만 exit 1로 실패한다.

## 검증 결과 — 2026-09-04, 최근 90일(2026-06-07 ~ 2026-09-04)

| 모델 | 세부품명 | status | G2B 행 | 등급 | 관측범위(KRW) | 독립출처 |
| --- | --- | --- | --- | --- | --- | --- |
| ApeosPrint C5570 GK | 레이저프린터 | ok | 12 | A | 2,981,000 ~ 5,500,000 | 2 |
| NT960XJG-K72AG | 노트북컴퓨터 | no_g2b_candidate | 0 | - | - | 0 |
| Sophie | 인공호흡기 | no_g2b_candidate | 0 | - | - | 0 |
| ThinkStation P2 Tower | 워크스테이션 | no_g2b_candidate | 0 | - | - | 0 |

```text
models=4 broken=0 no_g2b_candidate=3 with_g2b_rows=1
smoke_status=ok
```

### 실제로 확인된 것

**1. exact-model A 판정이 live에서 실제로 발생한다.**

`ApeosPrint C5570 GK` 12건이 모두 `MatchGrade.A`, 전량 2,981,000 KRW, item-level 근거 ID가 붙어 있다.

```text
2026-06-16  1대  delivery:R26TB02028138|change:00|product:24888744|line:1
2026-08-27  1대  delivery:R26TB02263211|change:00|product:24888744|line:1
```

원문 제목 `레이저프린터, Fujifilm, (CN)ApeosPrint C5570 GK, A3, 55ppm/55ppm`에서 F3가 `(CN)`을 검증된 원산지 한정어로 처리하고, 제조사 alias(`Fujifilm` → `FUJIFILM Business Innovation`)와 규격(A3/55ppm)까지 확인해 A를 부여했다. **F7 계약이 live 데이터에서 그대로 성립한다.**

**2. Adaptive date partitioning이 live 거래량에서 실제로 동작한다.**

`노트북컴퓨터` 90일 조회는 pagination cap을 초과해 2개 구간으로 이분할됐고, 두 구간 모두 `records_seen == reported_total_count`로 **완전수집**됐다.

```text
2026-06-07~2026-07-21  depth=1  pages=14  seen=1368  total=1368
2026-07-22~2026-09-04  depth=1  pages=14  seen=1382  total=1382
```

즉 0건은 수집 실패가 아니라 2,750건을 전부 확인한 뒤의 **근거 있는 0건**이다.

**3. Pricing safety gate가 live에서 fail-closed로 동작한다.**

견적 3,500,000원을 입력해도 `quote_position`은 `None`이었다.

> 직접 가격근거는 관측됐지만 VAT·단위·배송·설치·옵션·보증 등 비교조건이 충분히 검증되지 않아 현재 견적의 높고 낮음을 판정하지 않음.

관측 직접근거 13건·독립출처 2개·신뢰도 "높음"이 확보된 상황에서도 조건검증 없이는 고저 판정을 하지 않는다. 계약대로다.

**4. multi-source 비교가 live에서 성립한다.**

`ApeosPrint C5570 GK`는 제조사 공식몰(1건)과 나라장터(12건) 두 독립출처에서 동시에 관측됐다.

**5. `ThinkStation P2 Tower` mapping의 live source-hit이 처음으로 확인됐다.**

registry에 `live API source-hit 미검증`으로 남아 있던 항목이다. 이제 mapping 자체는 정상 동작하고 해당 기간 exact-model 거래가 없음이 확인됐다.

## 이 검증으로 발견해 수정한 결함 — 실패한 API 호출이 "결과 0건"으로 보이던 문제

live 호출 중 필수 파라미터가 빠진 요청에 대해 서비스가 다음을 반환하는 것을 확인했다.

```json
{"nkoneps.com.response.ResponseError": {"header": {"resultCode": "08", "resultMsg": "필수값 입력 에러"}}}
```

이 envelope은 문서화된 `response` / `OpenAPI_ServiceResponse` 어느 쪽도 아니다. 그 결과:

- `_payload_error_fields()`는 두 형태만 검사하므로 **오류를 인식하지 못하고** 정상 payload로 통과시켰다.
- `unwrap_g2b_page()`는 `payload.get("response", payload)`로 fallback하는데, 이 payload에는 최상위 `header`도 `body`도 없다. 따라서 **resultCode 검사가 건너뛰어지고 빈 페이지가 반환**됐다.

최종 결과는 사용자 화면에 이렇게 나타난다.

> 현재 연결된 공개가격 source에서 비교자료를 찾지 못했습니다.

즉 **호출이 실패했는데도 "이 제품은 조달실적이 없다"와 구분되지 않았다.** 근거 부족을 근거 있는 0건처럼 보이게 하는 fail-open이며, 이 프로젝트의 fail-closed 원칙에 정면으로 어긋난다.

### 수정

`*ResponseError`로 끝나는 최상위 envelope을 두 계층 모두에서 오류로 인식한다.

- `clients/data_go_kr.py` — `_candidate_error_envelopes()`가 `response`와 `*ResponseError` envelope을 모두 검사한다. 성공 코드 집합은 `SUCCESS_RESULT_CODES`로 공유한다.
- `collectors/g2b_shopping.py` — `unwrap_g2b_page()`가 `*ResponseError` envelope을 만나면 header의 resultCode/resultMsg로 실패하고, header 형태가 예상과 달라도 빈 페이지 대신 실패한다.

수정 후 동일한 live 호출은 다음과 같이 실패한다.

```text
PublicDataClientError: Public Data Portal API error: error=필수값 입력 에러 code=08
```

regression test는 `tests/test_g2b_error_envelope.py`에 live에서 캡처한 payload로 고정했다.

## 부록 — 조건 완전성(Condition Completeness) 실측 필드 조사

`getSpcifyPrdlstPrcureInfoList` 응답의 실제 필드를 확인했다(레이저프린터, 2026-08-01~08-13, 100건 표본).

| 조건 항목 | 응답 필드 | 실측값 | 판정 |
| --- | --- | --- | --- |
| 배송 | `dlvryCndtnNm` | `현장설치도` ×100 | **확인 가능** |
| 설치 | `dlvryCndtnNm` | `현장설치도`에 포함 | **확인 가능** |
| 납품기한 | `dlvrTmlmtDate` | 20260902~20260911 | 확인 가능 |
| 단위 | `prdctUnit` | `대` ×100 | 확인 가능 |
| 계약형태 | `cntrctDivNm` | `제3자단가계약` ×100 | 확인 가능 |
| **VAT** | — | **필드 없음** | **확인 불가** |
| 옵션 | — | 필드 없음 | 확인 불가 |
| 보증 | — | 필드 없음 | 확인 불가 |

`dlvryCndtnNm=현장설치도`는 배송과 현장설치가 단가에 포함된다는 뜻으로 읽히지만, **이 해석은 아직 공식 코드정의 문서로 검증하지 않았다.** 현재는 관찰된 문자열로만 기록한다.

핵심 제약: **VAT 포함 여부를 이 endpoint에서 확인할 수 없다.** 따라서 후속 Condition Completeness 작업은 이 endpoint만으로 `quote_comparable` 승격을 완성할 수 없고, 별도 근거(계약정보 서비스, 조달청 코드정의 문서 등)가 필요하다.

## 미검증

- **Streamlit 위젯 렌더링은 검증하지 않았다.** 스크립트는 UI가 호출하는 서비스 계층 전체를 동일 진입점으로 실행하지만, 브라우저에서의 실제 화면 표시는 포함하지 않는다.
- `dlvryCndtnNm` 코드값의 공식 의미는 미검증이다.
- verified mapping 4건 외 나머지 16개 benchmark 제품은 mapping이 없어 이 검증 범위 밖이다.
- 90일 외 기간(30/180/365일)은 실행하지 않았다.
