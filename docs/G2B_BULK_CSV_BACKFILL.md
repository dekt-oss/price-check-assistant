# G2B bulk CSV backfill + API gap fill

## Decision

Initial historical collection is **bulk-first**. The Track B per-classification API remains a fallback and freshness-gap source, not the primary one-year backfill mechanism.

Official source:

- Public Data Portal dataset: `15053481`
- Report: `UI-ADOXAA-038R`
- Name: `조달청_나라장터쇼핑몰 납품요구 물품 내역`
- Metadata page: `https://www.data.go.kr/data/15053481/fileData.do`
- Institution download link: `https://data.g2b.go.kr/link/AISC001_01/?reptNm=UI-ADOXAA-038R`

The official metadata declares:

- CSV
- automatic/rolling updates
- coverage through **D-1**
- date basis: `결재일자`
- no fee and unrestricted use
- fields include contract/delivery unit prices, quantities, amounts, delivery-request number and change order, item sequence, 10-digit detail classification, item identifier/name, demand agency and vendor.

## Access constraint

The institution download link currently redirects an unauthenticated request to the G2B SSO/OIDC flow. Do not scrape around that authentication boundary or store browser credentials in GitHub Actions.

Therefore the first production-safe path is:

1. obtain the official CSV through an authorized G2B browser session;
2. run the ingest CLI against the downloaded file;
3. store filtered public provenance in the dedicated R2 bucket;
4. use Track B API only for a freshness window not yet covered by the bulk file and only for exact requested/gap codes.

If G2B later exposes a supported unattended bulk-download credential or endpoint, acquisition can be automated without changing the ingest contract.

## Ingest contract

```bash
python -m purchase_price.scripts.ingest_g2b_bulk_csv \
  path/to/g2b-shopping-delivery.csv \
  --retrieved-date 2026-09-12 \
  --end-date 2026-09-11 \
  --days 365 \
  --output artifacts/g2b-bulk/summary.json
```

The ingest is streaming and supports UTF-8/UTF-8-BOM and CP949 exports. It:

- computes SHA-256 of the source file;
- fails closed when required columns are missing;
- filters to hospital-priority segments `42, 41, 43, 44, 23, 27, 46, 39`;
- filters to the requested date window;
- preserves every selected source column as text;
- adds normalized 10-digit code/date fields;
- adds stable source key `납품요구번호|변경차수|품목순번` when those columns are present;
- writes content-addressed R2 JSON+gzip chunks plus a manifest;
- remains protected by the R2 zero-cost hard write guard.

The bulk file is treated as authoritative through `retrieved_date - 1 day`, following the published D-1 contract. An empty code in the bulk file is **not** converted into thousands of API zero-result probes.

## Gap-fill contract

For the fixed initial backfill ending `2026-09-11`:

- CSV retrieved on `2026-09-11` is authoritative through `2026-09-10`; the only freshness gap is `2026-09-11`.
- CSV retrieved on or after `2026-09-12` is authoritative through `2026-09-11`; no historical Track B sweep is required.

Track B now accepts an explicit exact-code file and can skip the 24-call Unit10 dictionary scan:

```bash
python -m purchase_price.scripts.collect_g2b_track_b_r2 \
  --codes-file artifacts/gaps/codes.json \
  --begin-date 2026-09-11 \
  --end-date 2026-09-11 \
  --request-budget 100 \
  --output artifacts/gaps/track-b.json
```

`codes.json` may be a JSON list, `{ "codes": [...] }`, or newline-delimited exact 10-digit codes.

The collector still preserves all change orders by omitting `fnlCntrctDlvrReqChgOrdYn`; it never derives a unit price from amount/quantity and never treats an API failure as a zero result.

## What is intentionally not done here

- No automatic bypass of G2B SSO.
- No repeat 5,208-code historical API sweep after the authoritative bulk CSV is available.
- No PostgreSQL normalization yet. DB1 will consume the R2 bulk/API raw objects and keep only normalized serving fields + provenance pointers in PostgreSQL.
- No merge without explicit user approval.
