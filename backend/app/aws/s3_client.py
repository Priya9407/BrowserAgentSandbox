"""
s3_client.py — Placeholder S3 client for per-task screenshot storage.

Why this exists (Milestone 3 — AWS Integration + Demo Lock, item C):
  "wire optional S3 storage for per-task screenshots (free tier) so the
  summary card can show a visual." We don't have AWS credentials during
  the hackathon, so upload_screenshot() falls back to returning a local
  file path when AWS isn't configured. On the last day, set the env vars
  below and it starts actually uploading to S3 — no call sites change.

Env vars (all optional — unset means "local fallback mode"):
  AWS_S3_BUCKET          e.g. "frontier-demo-screenshots"
  AWS_ACCESS_KEY_ID
  AWS_SECRET_ACCESS_KEY
  AWS_REGION             default "ap-south-1"
"""

import os

S3_BUCKET = os.getenv("AWS_S3_BUCKET")
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")


def _s3_configured() -> bool:
    return bool(
        S3_BUCKET
        and os.getenv("AWS_ACCESS_KEY_ID")
        and os.getenv("AWS_SECRET_ACCESS_KEY")
    )


def upload_screenshot(local_path: str, key: str) -> str:
    """
    Upload a screenshot to S3 if configured, otherwise return the local
    file path unchanged. Never raises — screenshot upload is a nice-to-have
    for the demo, not something that should crash a task run.

    Returns a URL/path the frontend could use to display the image:
      - local fallback: "file:///abs/path/to/screenshot.png"
      - real S3:         "https://<bucket>.s3.<region>.amazonaws.com/<key>"
    """
    if not _s3_configured():
        return f"file://{os.path.abspath(local_path)}"

    try:
        import boto3  # lazy import — only needed once AWS is configured

        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.upload_file(local_path, S3_BUCKET, key)
        return f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{key}"
    except ImportError:
        print(
            "[s3_client] boto3 not installed — run `pip install boto3` "
            "to enable real S3 upload."
        )
        return f"file://{os.path.abspath(local_path)}"
    except Exception as exc:
        print(f"[s3_client] upload failed, falling back to local path: {exc}")
        return f"file://{os.path.abspath(local_path)}"
