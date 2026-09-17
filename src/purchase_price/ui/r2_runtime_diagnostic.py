from __future__ import annotations

from dataclasses import dataclass

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.exc import SQLAlchemyError

from purchase_price.config import Settings
from purchase_price.services.track_b_pipeline_state import SERVING_INDEX_STATE_NAME
from purchase_price.services.track_b_r2_quote_index import _local_index_path
from purchase_price.storage.r2 import R2ConfigurationError, R2IntegrityError
from purchase_price.storage.r2_state import R2OperationalStateStore


@dataclass(frozen=True)
class R2RuntimeDiagnostic:
    code: str
    detail: str = ""


def _client_error_code(exc: ClientError, *, stage: str) -> R2RuntimeDiagnostic:
    response = exc.response or {}
    error = response.get("Error") or {}
    response_meta = response.get("ResponseMetadata") or {}
    code = str(error.get("Code") or "").strip()
    http_status = int(response_meta.get("HTTPStatusCode") or 0)
    if http_status in {401, 403} or code in {
        "AccessDenied",
        "InvalidAccessKeyId",
        "SignatureDoesNotMatch",
        "Unauthorized",
    }:
        return R2RuntimeDiagnostic(f"{stage}_auth_or_permission")
    if http_status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
        return R2RuntimeDiagnostic(f"{stage}_not_found")
    return R2RuntimeDiagnostic(f"{stage}_client_error")


def diagnose_track_b_r2_runtime() -> R2RuntimeDiagnostic:
    """Return a secret-safe Production R2 health code.

    The diagnostic intentionally reports only missing configuration component names and coarse
    failure categories. Credential values, bucket names, object keys, account IDs, endpoints and
    exception messages are never returned.
    """

    settings = Settings()
    missing: list[str] = []
    if not settings.resolved_r2_endpoint_url:
        missing.append("endpoint")
    if not settings.resolved_r2_bucket_name:
        missing.append("bucket")
    if not settings.r2_access_key_id:
        missing.append("access_key")
    if not settings.r2_secret_access_key:
        missing.append("secret_key")
    if missing:
        return R2RuntimeDiagnostic("config_missing", ",".join(missing))

    try:
        pointer = R2OperationalStateStore.from_settings(settings).read_json(SERVING_INDEX_STATE_NAME)
    except ClientError as exc:
        return _client_error_code(exc, stage="pointer")
    except BotoCoreError:
        return R2RuntimeDiagnostic("pointer_transport_error")
    except R2ConfigurationError:
        return R2RuntimeDiagnostic("config_invalid")
    except R2IntegrityError:
        return R2RuntimeDiagnostic("pointer_integrity_error")
    except (OSError, ValueError):
        return R2RuntimeDiagnostic("pointer_runtime_error")

    if pointer is None:
        return R2RuntimeDiagnostic("pointer_missing")

    try:
        path = _local_index_path(settings)
    except ClientError as exc:
        return _client_error_code(exc, stage="index")
    except BotoCoreError:
        return R2RuntimeDiagnostic("index_transport_error")
    except R2ConfigurationError:
        return R2RuntimeDiagnostic("config_invalid")
    except R2IntegrityError:
        return R2RuntimeDiagnostic("index_integrity_error")
    except SQLAlchemyError:
        return R2RuntimeDiagnostic("index_sqlite_error")
    except (OSError, ValueError):
        return R2RuntimeDiagnostic("index_runtime_error")

    if path is None:
        return R2RuntimeDiagnostic("pointer_missing")
    if not path.exists():
        return R2RuntimeDiagnostic("index_cache_missing")
    return R2RuntimeDiagnostic("ready")
