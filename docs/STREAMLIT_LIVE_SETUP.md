# Streamlit live setup

## Required secret

The deployed app needs one public-data portal service key for both G2B and MFDS live APIs.

In Streamlit Community Cloud:

1. Open the deployed app.
2. Click the app menu (⋮) -> Settings.
3. Open **Secrets**.
4. Add the following root-level value:

```toml
DATA_GO_KR_SERVICE_KEY = "<your data.go.kr service key>"
```

5. Save and reboot the app if Streamlit does not restart it automatically.

Do not commit the real key to GitHub or paste it into `.env.example`.

## Expected UI after setup

- The G2B lookback selector on the quote-analysis page is enabled.
- The medical-device market-research page no longer shows the `DATA_GO_KR_SERVICE_KEY` disabled warning.
- MFDS/G2B live requests may still fail if the key has not been approved for the corresponding data.go.kr API; in that case the UI should show the API error rather than silently returning an empty result.
