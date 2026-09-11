"""Object-storage adapters used by purchase-price ingestion pipelines."""

from .r2 import R2RawEvidenceStore, RawObjectRef

__all__ = ["R2RawEvidenceStore", "RawObjectRef"]
