# cross_account_copy.py
"""
Copies all objects from source S3 bucket (Account A)
to destination S3 bucket (Account B) with progress,
error handling, retries and resumability.

Usage:
  python cross_account_copy.py
  python cross_account_copy.py --prefix uploads/
  python cross_account_copy.py --dry-run
"""

import boto3
import argparse
import json
import os
from datetime import datetime
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Config ────────────────────────────────────────────────────────
SOURCE_BUCKET  = "xo-client-data"
DEST_BUCKET    = "xo-client-data-mv"
SOURCE_REGION  = "us-west-1"
DEST_REGION    = "eu-west-2"
SOURCE_PROFILE = "scratchworks"
DEST_PROFILE   = "default"
MAX_WORKERS    = 10      # parallel copy threads
PROGRESS_FILE  = "copy_progress.json"


# ── Boto3 sessions ────────────────────────────────────────────────
source_session = boto3.Session(profile_name=SOURCE_PROFILE, region_name=SOURCE_REGION)
dest_session   = boto3.Session(profile_name=DEST_PROFILE,   region_name=DEST_REGION)

source_s3 = source_session.client("s3")
dest_s3   = dest_session.client("s3")


# ── Progress tracking ─────────────────────────────────────────────
def load_progress() -> set:
    """Load already-copied keys to allow resuming."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return set(json.load(f).get("copied", []))
    return set()


def save_progress(copied: set):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({"copied": list(copied), "updated_at": datetime.now().isoformat()}, f)


# ── List all objects ──────────────────────────────────────────────
def list_all_objects(prefix: str = "") -> list[dict]:
    """List every object in source bucket handling pagination."""
    objects    = []
    paginator  = source_s3.get_paginator("list_objects_v2")
    pages      = paginator.paginate(
        Bucket=SOURCE_BUCKET,
        Prefix=prefix
    )
    for page in pages:
        for obj in page.get("Contents", []):
            objects.append({
                "key" : obj["Key"],
                "size": obj["Size"],
                "etag": obj["ETag"]
            })

    return objects


# ── Copy single object ────────────────────────────────────────────
def copy_object(key: str, dry_run: bool = False) -> tuple[bool, str]:
    """
    Copy one object from source to dest.
    Uses server-side copy for objects < 5GB.
    Uses multipart copy for objects >= 5GB.
    Returns (success, key).
    """
    try:
        if dry_run:
            return True, key

        # Get source object metadata
        head = source_s3.head_object(Bucket=SOURCE_BUCKET, Key=key)
        size = head["ContentLength"]

        if size >= 5 * 1024 ** 3:
            # ── Multipart copy for large files ────────────────────
            copy_large_object(key, size)
        else:
            # ── Standard copy ─────────────────────────────────────
            copy_source = {
                "Bucket": SOURCE_BUCKET,
                "Key"   : key
            }
            dest_s3.copy_object(
                CopySource           = copy_source,
                Bucket               = DEST_BUCKET,
                Key                  = key,
                MetadataDirective    = "COPY",
                TaggingDirective     = "COPY",
                ACL                  = "bucket-owner-full-control"
            )

        return True, key

    except ClientError as e:
        print(f"  ❌ Failed: {key} — {e.response['Error']['Code']}: {e.response['Error']['Message']}")
        return False, key

    except Exception as e:
        print(f"  ❌ Unexpected error for {key}: {str(e)}")
        return False, key


def copy_large_object(key: str, size: int):
    """Multipart copy for objects >= 5GB."""
    CHUNK_SIZE  = 500 * 1024 * 1024   # 500MB chunks

    # Initiate multipart upload on destination
    mpu = dest_s3.create_multipart_upload(
        Bucket = DEST_BUCKET,
        Key    = key,
        ACL    = "bucket-owner-full-control"
    )
    upload_id = mpu["UploadId"]
    parts     = []

    try:
        part_num = 1
        offset   = 0

        while offset < size:
            end  = min(offset + CHUNK_SIZE - 1, size - 1)
            resp = dest_s3.upload_part_copy(
                Bucket              = DEST_BUCKET,
                Key                 = key,
                UploadId            = upload_id,
                PartNumber          = part_num,
                CopySource          = {"Bucket": SOURCE_BUCKET, "Key": key},
                CopySourceRange     = f"bytes={offset}-{end}"
            )
            parts.append({
                "PartNumber": part_num,
                "ETag"      : resp["CopyPartResult"]["ETag"]
            })
            part_num += 1
            offset   += CHUNK_SIZE

        # Complete multipart upload
        dest_s3.complete_multipart_upload(
            Bucket          = DEST_BUCKET,
            Key             = key,
            UploadId        = upload_id,
            MultipartUpload = {"Parts": parts}
        )

    except Exception as e:
        # Abort on failure to avoid incomplete multipart storage charges
        dest_s3.abort_multipart_upload(
            Bucket   = DEST_BUCKET,
            Key      = key,
            UploadId = upload_id
        )
        raise e


# ── Main copy function ────────────────────────────────────────────
def copy_bucket(prefix: str = "", dry_run: bool = False):
    start     = datetime.now()
    copied    = load_progress()

    print("╔══════════════════════════════════════════════════════╗")
    print("║   Cross-Account S3 Copy                             ║")
    print("╚══════════════════════════════════════════════════════╝")
    print(f"  Source : s3://{SOURCE_BUCKET}/{prefix}")
    print(f"  Dest   : s3://{DEST_BUCKET}/{prefix}")
    print(f"  Dry Run: {dry_run}")
    print(f"  Workers: {MAX_WORKERS}\n")

    # List all objects
    print("→ Listing objects...")
    all_objects = list_all_objects(prefix)
    total       = len(all_objects)
    total_size  = sum(o["size"] for o in all_objects)
    skipped     = [o for o in all_objects if o["key"] in copied]
    to_copy     = [o for o in all_objects if o["key"] not in copied]

    print(f"  Total objects : {total:,}")
    print(f"  Total size    : {total_size / 1024**3:.2f} GB")
    print(f"  Already copied: {len(skipped):,} (resuming)")
    print(f"  To copy       : {len(to_copy):,}\n")

    if dry_run:
        print("  [DRY RUN] — no files will be copied")
        for obj in to_copy[:10]:
            print(f"    Would copy: {obj['key']} ({obj['size'] / 1024:.1f} KB)")
        if len(to_copy) > 10:
            print(f"    ... and {len(to_copy) - 10} more")
        return

    # Copy in parallel
    success_count = len(skipped)
    fail_count    = 0
    failed_keys   = []

    print("→ Copying...\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(copy_object, obj["key"], dry_run): obj
            for obj in to_copy
        }
        for i, future in enumerate(as_completed(futures), 1):
            success, key = future.result()

            if success:
                success_count += 1
                copied.add(key)
                print(f"  ✅ [{i:>5}/{len(to_copy)}] {key}")
            else:
                fail_count += 1
                failed_keys.append(key)
                print(f"  ❌ [{i:>5}/{len(to_copy)}] FAILED: {key}")

            # Save progress every 100 files
            if i % 100 == 0:
                save_progress(copied)

    # Final save
    save_progress(copied)

    duration = (datetime.now() - start).total_seconds()
    print(f"\n{'═'*55}")
    print(f"  ✅ Copied  : {success_count:,} objects")
    print(f"  ❌ Failed  : {fail_count:,} objects")
    print(f"  ⏱  Duration: {duration:.0f} seconds")
    print(f"  📦 Progress: {PROGRESS_FILE}")

    if failed_keys:
        print(f"\n  Failed keys:")
        for k in failed_keys:
            print(f"    - {k}")

    print(f"{'═'*55}\n")


# ── Entry point ───────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix",  default="",    help="Only copy keys with this prefix")
    parser.add_argument("--dry-run", action="store_true", help="List only, no actual copy")
    args = parser.parse_args()

    copy_bucket(prefix=args.prefix, dry_run=args.dry_run)