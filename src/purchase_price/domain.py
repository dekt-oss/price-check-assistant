from enum import Enum


class MatchGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    X = "X"


class SourceType(str, Enum):
    PUBLIC_CONTRACT = "public_contract"
    PROCUREMENT = "procurement"
    MANUFACTURER = "manufacturer"
    B2B = "b2b"
    RETAIL = "retail"
    OTHER = "other"
