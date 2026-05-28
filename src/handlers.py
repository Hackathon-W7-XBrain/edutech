"""Endpoint handlers for the Bank -> Folder workspace flow."""
import io
import json
import re
import uuid
from collections import Counter


PROMPT_TEMPLATE = """You are a study assistant. Answer the student's question using ONLY the
context retrieved from their uploaded lecture notes. Cite the source by chunk
number where possible. If the context does not contain the answer, say so
plainly. Do not invent information.

CONTEXT:
{context}

QUESTION: {question}

ANSWER:"""

TOPIC_PROMPT_TEMPLATE = """You are a study assistant. Read the folder content and generate exactly 5 study topics.

Return raw JSON only, no markdown:
[
  {{
    "title": "Topic title",
    "summary": "2-3 sentence study guide summary"
  }}
]

FOLDER CONTENT:
{content}
"""

QUIZ_PROMPT_TEMPLATE = """You are a study assistant. Based on the study content below, generate exactly {question_count} multiple-choice quiz questions.

RULES:
- Each question must have exactly 4 options labeled A, B, C, D.
- Exactly one option is correct.
- Questions should test understanding, not just memorisation.
- Cover different parts of the content.

Return your answer as a JSON array with this exact structure (no markdown fences, just raw JSON):
[
  {{
    "id": 1,
    "question": "...",
    "options": {{"A": "...", "B": "...", "C": "...", "D": "..." }},
    "answer": "A",
    "explanation": "Short explanation why this is correct."
  }}
]

STUDY CONTENT:
{content}
"""

TOPIC_CHAT_PROMPT_TEMPLATE = """You are a study assistant helping inside a workspace for the topic "{topic_title}".

Topic study guide:
{topic_summary}

Use the retrieved lecture context below when answering. Keep the answer grounded and mention when context is weak.

CONTEXT:
{context}

QUESTION: {question}

ANSWER:"""

STOPWORDS = {
    "about", "after", "again", "against", "also", "because", "before", "being", "between", "could",
    "each", "from", "have", "into", "lecture", "notes", "only", "other", "should", "their", "there",
    "these", "those", "through", "under", "using", "what", "when", "where", "which", "with", "would",
    "your", "this", "that", "they", "them", "then", "than", "such", "over", "while", "slide",
    "slides", "topic", "topics", "study", "students", "student", "content", "document",
}


def _extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError:
            return "(pypdf not installed — install requirements.txt)"
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text)]


def _title_from_text(text: str, fallback: str) -> str:
    words = [word for word in _tokenize(text) if word not in STOPWORDS]
    common = [word.title() for word, _ in Counter(words).most_common(3)]
    return " ".join(common) if common else fallback


def _summarize_text(text: str, max_chars: int = 240) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _split_topic_segments(doc_texts: list[dict], count: int = 5) -> list[dict]:
    segments = []
    for doc in doc_texts:
        sentences = re.split(r"(?<=[.!?])\s+", doc["text"])
        bucket = []
        for sentence in sentences:
            if len(" ".join(bucket)) + len(sentence) < 500:
                bucket.append(sentence)
            else:
                segment = " ".join(bucket).strip()
                if segment:
                    segments.append({"doc_id": doc["doc_id"], "text": segment})
                bucket = [sentence]
        segment = " ".join(bucket).strip()
        if segment:
            segments.append({"doc_id": doc["doc_id"], "text": segment})
    if not segments:
        return []
    if len(segments) <= count:
        return segments
    step = max(1, len(segments) // count)
    selected = []
    for index in range(0, len(segments), step):
        selected.append(segments[index])
        if len(selected) == count:
            break
    return selected


def _parse_json_array(raw: str) -> list:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:])
    if cleaned.endswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[:-1])
    data = json.loads(cleaned)
    return data if isinstance(data, list) else []


def _fallback_topics(doc_texts: list[dict], count: int = 5) -> list[dict]:
    segments = _split_topic_segments(doc_texts, count=count)
    topics = []
    for index, segment in enumerate(segments, start=1):
        title = _title_from_text(segment["text"], f"Topic {index}")
        topics.append(
            {
                "title": title,
                "summary": _summarize_text(segment["text"]),
                "source_doc_ids": [segment["doc_id"]],
            }
        )
    while len(topics) < count:
        index = len(topics) + 1
        topics.append(
            {
                "title": f"Topic {index}",
                "summary": "Local fallback topic generated from the folder content. Add richer source material for better topic quality.",
                "source_doc_ids": [doc["doc_id"] for doc in doc_texts[:1]],
            }
        )
    return topics[:count]


def _fallback_quiz(topic_title: str, topic_summary: str, question_count: int) -> list[dict]:
    keywords = [word.title() for word in _tokenize(topic_summary) if word not in STOPWORDS]
    keywords = list(dict.fromkeys(keywords))[: max(4, question_count + 2)]
    if len(keywords) < 4:
        keywords.extend(["Concept", "Evidence", "Practice", "Review"])
    quiz = []
    for index in range(question_count):
        correct = keywords[index % len(keywords)]
        distractors = []
        for word in keywords:
            if word != correct and word not in distractors:
                distractors.append(word)
            if len(distractors) == 3:
                break
        options = {"A": correct, "B": distractors[0], "C": distractors[1], "D": distractors[2]}
        quiz.append(
            {
                "id": index + 1,
                "question": f"Which concept is most closely associated with the topic '{topic_title}'?",
                "options": options,
                "answer": "A",
                "explanation": f"{correct} appears in the topic study guide and is treated as a key idea in this local fallback quiz.",
            }
        )
    return quiz


def _get_doc_text(user_id: str, doc_id: str, vector_store) -> str:
    if hasattr(vector_store, "docs"):
        matched = [text for (_cid, text, md) in vector_store.docs if md.get("doc_id") == doc_id]
        if matched:
            return "\n\n".join(matched)
    chunks = vector_store.search("summary overview key concepts", top_k=50, filter={"doc_id": doc_id})
    if chunks:
        return "\n\n".join(chunk["text"] for chunk in chunks)
    return ""


def _get_folder_doc_texts(user_id: str, folder_id: str, userstore, vector_store) -> list[dict]:
    docs = userstore.get_folder_docs(user_id, folder_id)
    results = []
    for doc in docs:
        text = _get_doc_text(user_id, doc["doc_id"], vector_store)
        if text:
            results.append({"doc_id": doc["doc_id"], "filename": doc["filename"], "text": text})
    return results


def handle_upload(user_id: str, filename: str, data: bytes, storage, userstore) -> dict:
    """Save raw file to S3 + record metadata in DynamoDB.

    Text extraction and vector ingestion are handled asynchronously by the
    S3-triggered ingest Lambda (src/ingest.py).  The document is created with
    status='processing' and updated to 'ready' once ingestion completes.
    """
    doc_id = str(uuid.uuid4())
    key = f"{user_id}/{doc_id}/{filename}"
    location = storage.put(key, data)
    userstore.add_doc(
        user_id=user_id,
        doc_id=doc_id,
        metadata={
            "filename": filename,
            "size": len(data),
            "location": location,
            "status": "processing",
            "mime_type": "",
        },
    )
    return {
        "doc_id": doc_id,
        "filename": filename,
        "size": len(data),
        "status": "processing",
        "location": location,
    }


def handle_upload_url(user_id: str, filename: str, size: int, content_type: str, storage, userstore) -> dict:
    if not filename:
        return {"error": "Filename is required"}
    filename = filename.replace("/", "_").replace("\\", "_")
    if not hasattr(storage, "create_presigned_put"):
        return {"error": "Presigned upload is only supported with S3 storage backend"}
    doc_id = str(uuid.uuid4())
    key = f"{user_id}/{doc_id}/{filename}"
    result = storage.create_presigned_put(key=key, content_type=content_type or "application/octet-stream")
    userstore.add_doc(
        user_id=user_id,
        doc_id=doc_id,
        metadata={
            "filename": filename,
            "size": size,
            "location": result["location"],
            "status": "processing",
            "mime_type": content_type or "application/octet-stream",
        },
    )
    return {
        "doc_id": doc_id,
        "filename": filename,
        "size": size,
        "status": "processing",
        "location": result["location"],
        "upload": {
            "url": result["url"],
            "method": result["method"],
            "headers": {"Content-Type": content_type or "application/octet-stream"},
        },
    }


def handle_list_docs(user_id: str, userstore) -> dict:
    return {"user_id": user_id, "docs": userstore.list_docs(user_id)}


def handle_register(username: str, password: str, userstore) -> dict:
    if not username or not password:
        return {"error": "Username and password are required"}
    if len(username) < 3:
        return {"error": "Username must be at least 3 characters"}
    if len(password) < 4:
        return {"error": "Password must be at least 4 characters"}
    return userstore.register_user(username, password)


def handle_login(username: str, password: str, userstore) -> dict:
    if not username or not password:
        return {"error": "Username and password are required"}
    user = userstore.authenticate_user(username, password)
    if not user:
        return {"error": "Invalid username or password"}
    return {"user_id": user["user_id"], "username": user["username"]}


def handle_create_folder(user_id: str, name: str, userstore) -> dict:
    try:
        return {"folder": userstore.create_folder(user_id, name)}
    except ValueError as exc:
        return {"error": str(exc)}


def handle_rename_folder(user_id: str, folder_id: str, name: str, userstore) -> dict:
    try:
        return {"folder": userstore.rename_folder(user_id, folder_id, name)}
    except ValueError as exc:
        return {"error": str(exc)}


def handle_list_folders(user_id: str, userstore) -> dict:
    return {"folders": userstore.list_folders(user_id)}


def handle_get_folder(user_id: str, folder_id: str, userstore) -> dict:
    try:
        folder = userstore.get_folder(user_id, folder_id)
        if not folder:
            return {"error": "Folder not found"}
        return {"folder": folder, "docs": userstore.get_folder_docs(user_id, folder_id)}
    except ValueError as exc:
        return {"error": str(exc)}


def handle_add_documents_to_folder(user_id: str, folder_id: str, doc_ids: list[str], userstore) -> dict:
    try:
        folder = userstore.add_docs_to_folder(user_id, folder_id, doc_ids)
        return {"folder": folder, "docs": userstore.get_folder_docs(user_id, folder_id)}
    except ValueError as exc:
        return {"error": str(exc)}


def handle_generate_topics(user_id: str, folder_id: str, ai_client, userstore, vector_store) -> dict:
    try:
        doc_texts = _get_folder_doc_texts(user_id, folder_id, userstore, vector_store)
        if not doc_texts:
            return {"error": "Folder has no retrievable content yet."}
        combined = "\n\n".join(f"[DOC {doc['doc_id']}] {doc['text']}" for doc in doc_texts)[:15000]
        raw = ai_client.invoke(TOPIC_PROMPT_TEMPLATE.format(content=combined), max_tokens=1024)
        try:
            parsed = _parse_json_array(raw)
            topics = [
                {
                    "title": item.get("title", f"Topic {index}"),
                    "summary": item.get("summary", "Study guide topic"),
                    "source_doc_ids": [doc["doc_id"] for doc in doc_texts],
                }
                for index, item in enumerate(parsed[:5], start=1)
            ]
            if not topics:
                raise ValueError("No topics")
        except Exception:
            topics = _fallback_topics(doc_texts, count=5)
        return {"topics": userstore.replace_folder_topics(user_id, folder_id, topics), "raw": raw}
    except ValueError as exc:
        return {"error": str(exc)}


def handle_list_topics(user_id: str, folder_id: str, userstore) -> dict:
    try:
        return {"topics": userstore.list_folder_topics(user_id, folder_id)}
    except ValueError as exc:
        return {"error": str(exc)}


def handle_folder_dashboard(user_id: str, folder_id: str, userstore) -> dict:
    try:
        return userstore.get_folder_dashboard(user_id, folder_id)
    except ValueError as exc:
        return {"error": str(exc)}


def handle_create_chat_session(user_id: str, folder_id: str, title: str | None, topic_id: str | None, userstore) -> dict:
    try:
        return {"session": userstore.create_chat_session(user_id, folder_id, title=title, active_topic_id=topic_id)}
    except ValueError as exc:
        return {"error": str(exc)}


def handle_list_chat_sessions(user_id: str, folder_id: str, userstore) -> dict:
    try:
        return {"sessions": userstore.list_chat_sessions(user_id, folder_id)}
    except ValueError as exc:
        return {"error": str(exc)}


def handle_list_chat_messages(user_id: str, session_id: str, userstore) -> dict:
    try:
        session = userstore.get_chat_session(user_id, session_id)
        if not session:
            return {"error": "Session not found"}
        return {"session": session, "messages": userstore.list_chat_messages(user_id, session_id)}
    except ValueError as exc:
        return {"error": str(exc)}


def handle_chat_message(user_id: str, session_id: str, message: str, topic_id: str | None, ai_client, userstore, vector_store, vector_backend: str, bedrock_kb_id: str) -> dict:
    session = userstore.get_chat_session(user_id, session_id)
    if not session:
        return {"error": "Session not found"}

    user_message = userstore.add_chat_message(user_id, session_id, "user", message, topic_id=topic_id)
    topic = userstore.get_topic(user_id, topic_id) if topic_id else None

    if vector_backend == "bedrock_kb":
        result = ai_client.retrieve_and_generate(query=message, kb_id=bedrock_kb_id)
        answer = result["answer"]
        citations = result["citations"]
    else:
        chunks = vector_store.search(message, top_k=5, filter={"user_id": user_id})
        citations = [
            {"chunk": index + 1, "doc_id": chunk["doc_id"], "score": chunk["score"], "text": chunk["text"][:200]}
            for index, chunk in enumerate(chunks)
        ]
        context = "\n\n".join(f"[chunk {index + 1}] {chunk['text']}" for index, chunk in enumerate(chunks))
        if not context:
            answer = "No relevant content found in your uploaded documents yet."
        else:
            prompt = (
                TOPIC_CHAT_PROMPT_TEMPLATE.format(
                    topic_title=topic["title"],
                    topic_summary=topic["summary"],
                    context=context,
                    question=message,
                )
                if topic
                else PROMPT_TEMPLATE.format(context=context, question=message)
            )
            answer = ai_client.invoke(prompt, max_tokens=512)

    assistant_message = userstore.add_chat_message(
        user_id=user_id,
        session_id=session_id,
        role="assistant",
        content=answer,
        topic_id=topic_id,
        citations=citations,
    )
    if topic_id and session["folder_id"]:
        userstore.touch_topic_question(user_id, session["folder_id"], topic_id)
    return {"session": userstore.get_chat_session(user_id, session_id), "user_message": user_message, "assistant_message": assistant_message}


def handle_topic_quiz(user_id: str, topic_id: str, question_count: int, ai_client, userstore, vector_store) -> dict:
    topic = userstore.get_topic(user_id, topic_id)
    if not topic:
        return {"error": "Topic not found"}
    docs = userstore.get_topic_source_docs(user_id, topic_id)
    doc_texts = []
    for doc in docs:
        text = _get_doc_text(user_id, doc["doc_id"], vector_store)
        if text:
            doc_texts.append(text)
    content = f"Topic: {topic['title']}\nSummary: {topic['summary']}\n\n" + "\n\n".join(doc_texts[:3])
    raw = ai_client.invoke(QUIZ_PROMPT_TEMPLATE.format(content=content[:12000], question_count=question_count), max_tokens=2048)
    try:
        quiz = _parse_json_array(raw)
    except Exception:
        quiz = _fallback_quiz(topic["title"], topic["summary"], question_count)
    return {"topic": topic, "quiz": quiz, "raw": raw}


def handle_topic_quiz_submit(user_id: str, topic_id: str, question_count: int, score: int, total: int, userstore, session_id: str | None = None) -> dict:
    topic = userstore.get_topic(user_id, topic_id)
    if not topic:
        return {"error": "Topic not found"}
    attempt = userstore.record_topic_quiz_attempt(
        user_id=user_id,
        folder_id=topic["folder_id"],
        topic_id=topic_id,
        question_count=question_count,
        score=score,
        total=total,
        session_id=session_id,
    )
    return {"attempt": attempt}
