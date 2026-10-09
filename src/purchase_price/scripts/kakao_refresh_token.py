"""카카오톡 '나에게 보내기' 알림용 리프레시 토큰 받기 (처음 한 번).

1) 아래 명령으로 로그인 주소를 출력하고, 브라우저에서 열어 동의합니다.
       python -m purchase_price.scripts.kakao_refresh_token --rest-key <REST API 키> --redirect-uri <등록한 Redirect URI>
2) 이동한 주소의 ``code=`` 뒤 값을 복사해 다시 실행합니다.
       python -m purchase_price.scripts.kakao_refresh_token --rest-key ... --redirect-uri ... --code <복사한 값>
3) 출력된 리프레시 토큰을 GitHub Secrets ``KAKAO_REFRESH_TOKEN``에 넣습니다. 이후 갱신은 수집 작업이
   R2에 저장하며 자동으로 이어 갑니다. 토큰 값은 화면에만 한 번 출력되고 파일로 저장하지 않습니다.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"


def authorize_url(rest_key: str, redirect_uri: str) -> str:
    query = {"client_id": rest_key, "redirect_uri": redirect_uri, "response_type": "code", "scope": "talk_message"}
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def exchange_code(rest_key: str, redirect_uri: str, code: str, client_secret: str | None = None, *, transport=None) -> dict:
    data = {"grant_type": "authorization_code", "client_id": rest_key, "redirect_uri": redirect_uri, "code": code}
    if client_secret:
        data["client_secret"] = client_secret
    with httpx.Client(timeout=20, transport=transport) as client:
        response = client.post(TOKEN_URL, data=data)
    response.raise_for_status()
    return response.json()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rest-key", required=True)
    parser.add_argument("--redirect-uri", required=True)
    parser.add_argument("--code")
    parser.add_argument("--client-secret")
    args = parser.parse_args(argv)
    if not args.code:
        print("브라우저에서 이 주소를 열고 동의한 뒤, 이동한 주소의 code= 값을 --code로 넘겨 다시 실행하세요:")
        print(authorize_url(args.rest_key, args.redirect_uri))
        return 0
    payload = exchange_code(args.rest_key, args.redirect_uri, args.code, args.client_secret)
    token = payload.get("refresh_token")
    if not token:
        print("리프레시 토큰을 받지 못했습니다. 동의 항목(talk_message)과 Redirect URI를 확인하세요.")
        return 1
    print("GitHub Secrets KAKAO_REFRESH_TOKEN에 아래 값을 넣으세요 (다른 곳에 저장하지 마세요):")
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
