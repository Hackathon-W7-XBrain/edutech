"""Vector store adapters. Pick via VECTOR_BACKEND env var.

Interface:
    ingest(doc_id, text, metadata=None) -> None
    search(query, top_k=5, filter=None) -> list[dict] (each has 'text', 'doc_id', 'score', 'metadata')
"""
import re
from collections import Counter
from typing import Optional


class BedrockKBVector:
    """Production: Bedrock Knowledge Base abstracts the vector store backend.

    Group still chooses the underlying vector store (OpenSearch Serverless, S3 Vectors,
    Aurora pgvector, Pinecone) when creating the KB in AWS console — that choice
    is invisible to this code.

    NOTE: KB ingestion is async via StartIngestionJob, normally triggered by S3 events.
    For simplicity, this adapter is search-only — ingestion happens through the
    Bedrock console or S3 → KB sync pipeline you set up separately.
    """

    def __init__(self, kb_id: str, region: str):
        import boto3
        if not kb_id:
            raise ValueError("VECTOR_BEDROCK_KB_ID must be set for Bedrock KB backend")
        from src.config import config
        self.kb_id = kb_id
        self.data_source_id = config.vector_bedrock_data_source_id
        self.agent_runtime = boto3.client("bedrock-agent-runtime", region_name=region)

    def ingest(self, doc_id: str, text: str, metadata: Optional[dict] = None) -> None:
        if not self.data_source_id:
            return  # Skip if Data Source ID is not provided
        try:
            self.agent_runtime.start_ingestion_job(
                knowledgeBaseId=self.kb_id,
                dataSourceId=self.data_source_id
            )
        except Exception as e:
            print(f"Failed to start Bedrock KB ingestion: {e}")

    def search(self, query: str, top_k: int = 5, filter: Optional[dict] = None) -> list:
        kwargs = {
            "knowledgeBaseId": self.kb_id,
            "retrievalQuery": {"text": query},
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {"numberOfResults": top_k}
            },
        }
        if filter:
            kwargs["retrievalConfiguration"]["vectorSearchConfiguration"]["filter"] = {
                "andAll": [{"equals": {"key": k, "value": v}} for k, v in filter.items()]
            }
        resp = self.agent_runtime.retrieve(**kwargs)
        return [
            {
                "text": r.get("content", {}).get("text", ""),
                "doc_id": r.get("metadata", {}).get("doc_id", ""),
                "score": r.get("score", 0.0),
                "metadata": r.get("metadata", {}),
            }
            for r in resp.get("retrievalResults", [])
        ]


class LocalVector:
    """Simple in-memory inverted index + TF scoring. NOT semantic — keyword only.

    Good enough for verifying the API contract locally. Production needs real
    embeddings + ANN — that's what Bedrock KB provides.
    """

    def __init__(self):
        self.docs: list[tuple[str, str, dict]] = []   # (doc_id, text, metadata)

    @staticmethod
    def _tokens(text: str) -> list:
        return [t.lower() for t in re.findall(r"\w+", text) if len(t) > 2]

    @staticmethod
    def _chunk(text: str, size: int = 500) -> list:
        # Naive chunking by sentence-ish boundaries
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks, current = [], ""
        for s in sentences:
            if len(current) + len(s) < size:
                current += " " + s
            else:
                if current.strip():
                    chunks.append(current.strip())
                current = s
        if current.strip():
            chunks.append(current.strip())
        return chunks or [text]

    def ingest(self, doc_id: str, text: str, metadata: Optional[dict] = None) -> None:
        md = metadata or {}
        for i, chunk in enumerate(self._chunk(text)):
            self.docs.append((f"{doc_id}#{i}", chunk, {**md, "doc_id": doc_id, "chunk_idx": i}))

    def search(self, query: str, top_k: int = 5, filter: Optional[dict] = None) -> list:
        q_tokens = set(self._tokens(query))
        results = []
        for chunk_id, text, md in self.docs:
            if filter and not all(md.get(k) == v for k, v in filter.items()):
                continue
            d_tokens = Counter(self._tokens(text))
            score = sum(d_tokens[t] for t in q_tokens)
            if score > 0:
                results.append({
                    "text": text,
                    "doc_id": md.get("doc_id", chunk_id),
                    "score": float(score),
                    "metadata": md,
                })
        results.sort(key=lambda r: -r["score"])
        return results[:top_k]