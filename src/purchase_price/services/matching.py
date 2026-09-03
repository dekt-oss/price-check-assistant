import re


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.casefold().strip()
    return re.sub(r"[^0-9a-z가-힣]+", "", value)


def exact_model_match(query_model: str | None, candidate_model: str | None) -> bool:
    q = normalize_text(query_model)
    c = normalize_text(candidate_model)
    return bool(q and c and q == c)
