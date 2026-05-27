"""Lambda handler — S3-triggered PDF ingest pipeline.

Flow:
  S3 ObjectCreated (.pdf) → this Lambda
    1. Download raw PDF from S3
    2. Extract text (pypdf)
    3. Chunk text
    4. Write chunks to S3 processed/ prefix (Bedrock KB Data Source reads here)
    5. Start Bedrock KB ingestion job
    6. Update DynamoDB doc status → "ready"

Anti-loop protection (2 layers):
  Layer 1 — template.yaml S3 event filter: suffix=.pdf (chunks are .txt → won't trigger)
  Layer 2 — code guard: skip any key starting with PROCESSED_PREFIX
"""
import io
import os
import re
import urllib.parse

import boto3

# ── Config from environment ──────────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION_OVERRIDE") or os.environ.get("AWS_REGION", "ap-southeast-1")
USERSTORE_TABLE = os.environ.get("USERSTORE_TABLE", "")
VECTOR_BEDROCK_KB_ID = os.environ.get("VECTOR_BEDROCK_KB_ID", "")
VECTOR_BEDROCK_DATA_SOURCE_ID = os.environ.get("VECTOR_BEDROCK_DATA_SOURCE_ID", "")
PROCESSED_PREFIX = "processed/"

# ── AWS clients (reused across warm invocations) ─────────────────────────────
s3 = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_text_from_pdf(data: bytes) -> str:
    """Extract text from PDF bytes using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    """Split text into chunks at sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) < chunk_size:
            current += " " + sentence
        else:
            if current.strip():
                chunks.append(current.strip())
            current = sentence
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text]


def _update_doc_status(user_id: str, doc_id: str, status: str, chars: int) -> None:
    """Update document record in DynamoDB with new status and char count."""
    if not USERSTORE_TABLE:
        print("USERSTORE_TABLE not set, skipping DynamoDB update")
        return
    table = dynamodb.Table(USERSTORE_TABLE)
    table.update_item(
        Key={"user_id": user_id, "sk": f"DOC#{doc_id}"},
        UpdateExpression="SET #s = :s, chars = :c",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status, ":c": chars},
    )
    print(f"Updated doc {doc_id} status → '{status}', chars={chars}")


def _start_bedrock_ingestion() -> None:
    """Trigger Bedrock KB to sync new data from the processed/ S3 prefix."""
    if not VECTOR_BEDROCK_KB_ID or not VECTOR_BEDROCK_DATA_SOURCE_ID:
        print("Bedrock KB not configured (KB_ID or DATA_SOURCE_ID missing), skipping ingestion")
        return
    try:
        bedrock_agent = boto3.client("bedrock-agent", region_name=REGION)
        resp = bedrock_agent.start_ingestion_job(
            knowledgeBaseId=VECTOR_BEDROCK_KB_ID,
            dataSourceId=VECTOR_BEDROCK_DATA_SOURCE_ID,
        )
        job_id = resp.get("ingestionJob", {}).get("ingestionJobId", "unknown")
        print(f"Started Bedrock KB ingestion job: {job_id} (KB={VECTOR_BEDROCK_KB_ID})")
    except Exception as exc:
        print(f"Failed to start Bedrock KB ingestion: {exc}")


# ── Main handler ─────────────────────────────────────────────────────────────

def handler(event, context):
    """S3 event handler — processes each uploaded PDF."""
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        raw_key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        # ── Anti-loop guard (Layer 2) ────────────────────────────────────
        if raw_key.startswith(PROCESSED_PREFIX):
            print(f"SKIP: key starts with '{PROCESSED_PREFIX}': {raw_key}")
            continue

        # ── Parse S3 key: {user_id}/{doc_id}/{filename} ─────────────────
        parts = raw_key.split("/", 2)
        if len(parts) < 3:
            print(f"SKIP: unexpected key format (need user_id/doc_id/filename): {raw_key}")
            continue

        user_id, doc_id, filename = parts[0], parts[1], parts[2]
        print(f"Processing: user={user_id}, doc={doc_id}, file={filename}")

        # ── 1. Download raw PDF from S3 ─────────────────────────────────
        resp = s3.get_object(Bucket=bucket, Key=raw_key)
        data = resp["Body"].read()
        print(f"Downloaded {len(data)} bytes from s3://{bucket}/{raw_key}")

        # ── 2. Extract text ─────────────────────────────────────────────
        if filename.lower().endswith(".pdf"):
            text = _extract_text_from_pdf(data)
        else:
            text = data.decode("utf-8", errors="replace")

        if not text.strip():
            print(f"No text extracted from {filename}, marking as ready (empty)")
            _update_doc_status(user_id, doc_id, status="ready", chars=0)
            continue

        # ── 3. Chunk text ───────────────────────────────────────────────
        chunks = _chunk_text(text)
        print(f"Extracted {len(text)} chars → {len(chunks)} chunks")

        # ── 4. Write chunks to S3 processed/ prefix ─────────────────────
        for i, chunk in enumerate(chunks):
            chunk_key = f"{PROCESSED_PREFIX}{user_id}/{doc_id}/chunk_{i:04d}.txt"
            s3.put_object(
                Bucket=bucket,
                Key=chunk_key,
                Body=chunk.encode("utf-8"),
                ContentType="text/plain",
                Metadata={
                    "user_id": user_id,
                    "doc_id": doc_id,
                    "source_filename": filename,
                    "chunk_index": str(i),
                },
            )
        print(f"Wrote {len(chunks)} chunks to s3://{bucket}/{PROCESSED_PREFIX}{user_id}/{doc_id}/")

        # ── 5. Start Bedrock KB ingestion ───────────────────────────────
        _start_bedrock_ingestion()

        # ── 6. Update DynamoDB doc status → "ready" ─────────────────────
        _update_doc_status(user_id, doc_id, status="ready", chars=len(text))

    return {"statusCode": 200, "body": "Ingest complete"}
