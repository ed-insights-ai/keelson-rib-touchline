# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3==1.35.99"]
# ///
"""Sync a built site to the site bucket, uploading only files whose content changed.

`aws s3 sync` compares size and modification time, and every build writes every
file fresh, so it would re-upload the whole site (15,000+ files) daily. This
compares content instead: each local file's MD5 against the object's ETag,
which for a single-part upload under SSE-S3 is the MD5 of its bytes. Every
upload here is single-part (put_object), so the ETags stay comparable.

Order, so a reader never gets a page whose assets are missing:
  1. new and changed non-HTML files (hashed assets, images, sitemaps),
  2. new and changed HTML,
  3. deletes of objects the build no longer has.

A deploy that would delete more than --max-delete-fraction of the bucket
stops before touching anything, unless --allow-mass-delete: a half-built dist/
must not empty the live site.

    uv run site/sync.py --dist ui/dist --bucket touchline-site-<account> [--dry-run]

Prints a JSON summary on the last line; --changed-out writes the changed and
deleted keys, one per line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Types mimetypes gets wrong or does not know on a bare runner.
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".webmanifest": "application/manifest+json",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".avif": "image/avif",
}

# Astro's content-hashed assets never change under the same name.
IMMUTABLE = "public, max-age=31536000, immutable"
# Everything else: CloudFront's pages policy (max 3600) keeps it this long,
# and so does a browser, so a daily deploy shows within minutes.
PAGES = "public, max-age=300"


def content_type(path: Path) -> str:
    return (
        TYPES.get(path.suffix.lower())
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )


def cache_control(key: str) -> str:
    return IMMUTABLE if "_astro/" in key else PAGES


def md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def local_files(dist: Path) -> dict[str, Path]:
    return {
        p.relative_to(dist).as_posix(): p
        for p in sorted(dist.rglob("*"))
        if p.is_file()
    }


def remote_etags(s3, bucket: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            out[obj["Key"]] = obj["ETag"].strip('"')
    return out


def plan(
    local: dict[str, Path], remote: dict[str, str], workers: int
) -> tuple[list[str], list[str]]:
    """(keys to upload, keys to delete). A multipart ETag ("...-N") never matches an MD5."""
    with ThreadPoolExecutor(workers) as pool:
        hashes = dict(zip(local, pool.map(md5, local.values())))
    upload = [k for k, h in hashes.items() if remote.get(k) != h]
    delete = sorted(set(remote) - set(local))
    # Non-HTML first, then HTML, each in path order.
    upload.sort(key=lambda k: (k.endswith(".html"), k))
    return upload, delete


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dist", required=True, type=Path)
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-mass-delete", action="store_true")
    ap.add_argument("--max-delete-fraction", type=float, default=0.25)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--changed-out", type=Path)
    args = ap.parse_args(argv)

    import boto3
    from botocore.config import Config

    dist = args.dist.resolve()
    local = local_files(dist)
    if not (dist / "index.html").is_file():
        raise SystemExit(f"{dist} has no index.html; refusing to deploy it")

    s3 = boto3.client(
        "s3",
        config=Config(max_pool_connections=args.workers, retries={"mode": "standard"}),
    )
    remote = remote_etags(s3, args.bucket)
    upload, delete = plan(local, remote, args.workers)

    # A bucket of a handful of objects (a first deploy, a test) has no site to protect.
    if (
        len(remote) >= 50
        and len(delete) > args.max_delete_fraction * len(remote)
        and not args.allow_mass_delete
    ):
        raise SystemExit(
            f"this deploy would delete {len(delete)} of {len(remote)} objects "
            f"(over {args.max_delete_fraction:.0%}); rerun with --allow-mass-delete if that is intended"
        )

    def put(key: str) -> int:
        path = local[key]
        with path.open("rb") as body:
            s3.put_object(
                Bucket=args.bucket,
                Key=key,
                Body=body,
                ContentType=content_type(path),
                CacheControl=cache_control(key),
            )
        return path.stat().st_size

    uploaded_bytes = 0
    if not args.dry_run:
        html_from = next(
            (i for i, k in enumerate(upload) if k.endswith(".html")), len(upload)
        )
        with ThreadPoolExecutor(args.workers) as pool:
            # Assets land before any page that names them.
            uploaded_bytes += sum(pool.map(put, upload[:html_from]))
            uploaded_bytes += sum(pool.map(put, upload[html_from:]))
        for i in range(0, len(delete), 1000):
            batch = delete[i : i + 1000]
            resp = s3.delete_objects(
                Bucket=args.bucket,
                Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
            )
            if resp.get("Errors"):
                raise SystemExit(f"delete failed: {resp['Errors'][:3]}")

    if args.changed_out:
        args.changed_out.write_text("".join(f"{k}\n" for k in upload + delete))
    summary = {
        "files": len(local),
        "uploaded": len(upload),
        "uploaded_mb": round(uploaded_bytes / 1e6, 1),
        "deleted": len(delete),
        "unchanged": len(local) - len(upload),
        "dry_run": args.dry_run,
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
