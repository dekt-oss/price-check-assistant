from enum import StrEnum


class MatchGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    X = "X"


class SourceType(StrEnum):
    PUBLIC_CONTRACT = "public_contract"
    PROCUREMENT = "procurement"
    MANUFACTURER = "manufacturer"
    B2B = "b2b"
    RETAIL = "retail"
    OTHER = "other"
