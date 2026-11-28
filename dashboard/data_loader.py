"""로컬 디렉터리와 S3 exports/를 같은 인터페이스로 읽는 대시보드 데이터 로더."""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd


@dataclass(frozen=True)
class DashboardBundle:
    """대시보드 3화면 렌더링에 필요한 공식 실행 데이터 묶음."""

    official: dict[str, Any]
    documents: pd.DataFrame
    axis4_judgments: pd.DataFrame
    residual_summary: dict[str, Any]
    sanction_validation: pd.DataFrame | None
    sanction_summary: dict[str, Any] | None
    section_scores: pd.DataFrame | None
    sensitivity_summary: dict[str, Any] | None


def _read_streamlit_secret(key: str) -> str:
    try:
        import streamlit as st
    except ImportError:
        return ""
    try:
        val = st.secrets.get(key)
    except (FileNotFoundError, KeyError, RuntimeError):
        return ""
    return str(val).strip() if val else ""


def resolve_data_root(default_local: Path) -> str:
    """환경 변수·Streamlit 비밀값·기본 로컬 경로 순으로 데이터 루트를 결정한다."""
    env_root = os.environ.get("DASHBOARD_DATA_ROOT", "").strip()
    if env_root:
        return env_root

    secret_root = _read_streamlit_secret("DASHBOARD_DATA_ROOT")
    if secret_root:
        return secret_root

    return str(default_local)


def _s3_client():
    import boto3

    kwargs: dict[str, str] = {}
    for secret_key, boto_key in (
        ("AWS_ACCESS_KEY_ID", "aws_access_key_id"),
        ("AWS_SECRET_ACCESS_KEY", "aws_secret_access_key"),
        ("AWS_DEFAULT_REGION", "region_name"),
    ):
        val = _read_streamlit_secret(secret_key)
        if val:
            kwargs[boto_key] = val
    return boto3.client("s3", **kwargs)


def _validate_relative_path(relative_path: str) -> str:
    rel = relative_path.strip()
    path = Path(rel)
    if not rel or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"허용되지 않는 상대 경로입니다: {relative_path}")
    return rel


def _read_bytes(data_root: str, relative_path: str) -> bytes | None:
    safe_rel = _validate_relative_path(relative_path)
    if data_root.startswith("s3://"):
        from botocore.exceptions import ClientError

        parsed = urlparse(data_root)
        bucket = parsed.netloc
        prefix = parsed.path.lstrip("/").rstrip("/")
        key = f"{prefix}/{safe_rel}" if prefix else safe_rel
        client = _s3_client()
        try:
            resp = client.get_object(Bucket=bucket, Key=key)
            return resp["Body"].read()
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "404"}:
                return None
            raise

    base = Path(data_root).resolve()
    target = (base / safe_rel).resolve()
    if base not in target.parents and target != base:
        raise ValueError(f"데이터 루트 밖 경로 접근 차단: {relative_path}")
    if not target.exists():
        return None
    return target.read_bytes()


def _read_json(
    data_root: str, relative_path: str | None, *, required: bool
) -> dict[str, Any] | None:
    if not relative_path:
        if required:
            raise FileNotFoundError("필수 JSON 경로가 official.json에 비어 있습니다.")
        return None
    payload = _read_bytes(data_root, relative_path)
    if payload is None:
        if required:
            raise FileNotFoundError(
                f"필수 JSON 파일을 찾을 수 없습니다: {relative_path}"
            )
        return None
    return json.loads(payload.decode("utf-8"))


def _read_parquet(
    data_root: str, relative_path: str | None, *, required: bool
) -> pd.DataFrame | None:
    if not relative_path:
        if required:
            raise FileNotFoundError(
                "필수 Parquet 경로가 official.json에 비어 있습니다."
            )
        return None
    payload = _read_bytes(data_root, relative_path)
    if payload is None:
        if required:
            raise FileNotFoundError(
                f"필수 Parquet 파일을 찾을 수 없습니다: {relative_path}"
            )
        return None
    return pd.read_parquet(io.BytesIO(payload))


def load_bundle(data_root: str) -> DashboardBundle:
    """official.json을 먼저 읽고 가리키는 공식 실행의 Parquet·JSON 파일을 로드한다."""
    official = _read_json(data_root, "official.json", required=True)
    assert official is not None
    files = official.get("files", {})

    documents = _read_parquet(data_root, files.get("documents"), required=True)
    axis4_judgments = _read_parquet(
        data_root, files.get("axis4_judgments"), required=True
    )
    residual_summary = _read_json(
        data_root, files.get("residual_summary"), required=True
    )
    assert documents is not None
    assert axis4_judgments is not None
    assert residual_summary is not None

    return DashboardBundle(
        official=official,
        documents=documents,
        axis4_judgments=axis4_judgments,
        residual_summary=residual_summary,
        sanction_validation=_read_parquet(
            data_root, files.get("sanction_validation"), required=False
        ),
        sanction_summary=_read_json(
            data_root, files.get("sanction_summary"), required=False
        ),
        section_scores=_read_parquet(
            data_root, files.get("section_scores"), required=False
        ),
        sensitivity_summary=_read_json(
            data_root, files.get("sensitivity_summary"), required=False
        ),
    )
