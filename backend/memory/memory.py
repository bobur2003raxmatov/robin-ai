"""ROBIN Memory 360 — three layers:

SHORT-TERM  : current conversation + task context (messages table, rolling summary)
LONG-TERM   : user facts, preferences, projects, decisions, workflows (memories table, linked)
KNOWLEDGE   : documents → chunks → semantic search (knowledge_chunks; pgvector-ready)

Semantic vectors come from OpenAI/Gemini embeddings when a key is available,
otherwise a local hashed n-gram vector is used, so search always works offline.
"""
from __future__ import annotations

import hashlib
import math
import re

from sqlalchemy import delete, desc, select

from backend.ai.providers import embed
from backend.memory.database import (Conversation, Feedback, KnowledgeChunk, KnowledgeDoc, MemoryItem,
                                     Message, SessionLocal)

LOCAL_DIM = 384
_WORD = re.compile(r"[\w'ʻ’]+", re.UNICODE)


def local_vector(text: str) -> list[float]:
    vec = [0.0] * LOCAL_DIM
    t = text.lower()
    tokens = _WORD.findall(t)
    feats = tokens + [w[i:i + 3] for w in tokens for i in range(max(1, len(w) - 2))]
    for f in feats:
        h = int(hashlib.md5(f.encode()).hexdigest(), 16)
        vec[h % LOCAL_DIM] += 1.0 if (h >> 9) & 1 else -1.0
    n = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / n, 5) for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def keyword_score(q: str, text: str) -> float:
    qs = set(_WORD.findall(q.lower()))
    if not qs:
        return 0.0
    ts = set(_WORD.findall(text.lower()))
    return len(qs & ts) / len(qs)


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text)
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return [c for c in out if c.strip()]


class Memory:
    def __init__(self, user_id: str, keys: dict | None = None):
        self.user_id = user_id
        self.keys = keys or {}

    async def _vec(self, text: str) -> list[float]:
        v = await embed(text, self.keys) if self.keys else []
        return v or local_vector(text)

    async def _query_vecs(self, text: str) -> tuple[list[float], list[float]]:
        sem = await embed(text, self.keys) if self.keys else []
        return sem, local_vector(text)

    # ------------------------------------------------------------ short-term
    async def get_or_create_conversation(self, conversation_id: str | None, title: str = "") -> Conversation:
        async with SessionLocal() as db:
            if conversation_id:
                conv = await db.get(Conversation, conversation_id)
                if conv and conv.user_id == self.user_id:
                    return conv
            conv = Conversation(user_id=self.user_id, title=(title or "Yangi suhbat")[:200])
            db.add(conv)
            await db.commit()
            await db.refresh(conv)
            return conv

    async def add_message(self, conversation_id: str, role: str, content: str, meta: dict | None = None) -> int:
        async with SessionLocal() as db:
            m = Message(conversation_id=conversation_id, user_id=self.user_id, role=role, content=content,
                        meta=meta or {})
            db.add(m)
            conv = await db.get(Conversation, conversation_id)
            if conv:
                from backend.memory.database import now
                conv.updated_at = now()
            await db.commit()
            return m.id

    async def recent_messages(self, conversation_id: str, limit: int = 24) -> list[dict]:
        async with SessionLocal() as db:
            rows = (await db.scalars(select(Message).where(Message.conversation_id == conversation_id,
                                                          Message.user_id == self.user_id,
                                                          Message.role.in_(["user", "assistant"]))
                                     .order_by(desc(Message.id)).limit(limit))).all()
        msgs = [{"role": r.role, "content": r.content} for r in reversed(rows)]
        # Providers require alternating turns starting with user
        cleaned: list[dict] = []
        for m in msgs:
            if cleaned and cleaned[-1]["role"] == m["role"]:
                cleaned[-1]["content"] += "\n" + m["content"]
            else:
                cleaned.append(m)
        while cleaned and cleaned[0]["role"] != "user":
            cleaned.pop(0)
        return cleaned

    # ------------------------------------------------------------ long-term
    async def remember(self, content: str, kind: str = "fact", subject: str = "", importance: float = 0.5) -> int:
        vec = await self._vec(f"{subject} {content}")
        async with SessionLocal() as db:
            # de-duplicate: update near-identical memory instead of adding
            rows = (await db.scalars(select(MemoryItem).where(MemoryItem.user_id == self.user_id,
                                                              MemoryItem.kind == kind))).all()
            for r in rows:
                if cosine(vec, r.embedding) > 0.93 or (subject and r.subject.lower() == subject.lower()
                                                       and keyword_score(content, r.content) > 0.8):
                    r.content, r.importance, r.embedding = content, max(r.importance, importance), vec
                    await db.commit()
                    return r.id
            item = MemoryItem(user_id=self.user_id, kind=kind, subject=subject[:200], content=content,
                              importance=importance, embedding=vec)
            db.add(item)
            await db.commit()
            # Memory 360: link to related memories on the same subject/project
            related = [r.id for r in rows if subject and (subject.lower() in (r.subject or "").lower()
                                                          or (r.subject or "").lower() in subject.lower())]
            if related:
                item.links = related[:20]
                await db.commit()
            return item.id

    async def search(self, query: str, limit: int = 8, kinds: list[str] | None = None) -> list[MemoryItem]:
        sem, loc = await self._query_vecs(query)
        async with SessionLocal() as db:
            stmt = select(MemoryItem).where(MemoryItem.user_id == self.user_id)
            if kinds:
                stmt = stmt.where(MemoryItem.kind.in_(kinds))
            rows = (await db.scalars(stmt)).all()
            scored = []
            for r in rows:
                vs = cosine(sem, r.embedding) if sem and len(sem) == len(r.embedding) else cosine(loc, r.embedding)
                s = 0.6 * vs + 0.3 * keyword_score(query, f"{r.subject} {r.content}") + 0.1 * r.importance
                scored.append((s, r))
            scored.sort(key=lambda x: x[0], reverse=True)
            top = [r for s, r in scored[:limit] if s > 0.12]
            # follow links (Memory 360)
            ids = {r.id for r in top}
            for r in list(top):
                for lid in (r.links or [])[:3]:
                    if lid not in ids:
                        linked = await db.get(MemoryItem, lid)
                        if linked and linked.user_id == self.user_id:
                            top.append(linked)
                            ids.add(lid)
            for r in top:
                r.hits += 1
            await db.commit()
            return top[: limit + 4]

    async def context_block(self, query: str) -> str:
        items = await self.search(query)
        lines = [f"- [{m.kind}] {m.subject + ': ' if m.subject else ''}{m.content}" for m in items]
        know = await self.search_knowledge(query, limit=3)
        if know:
            lines.append("Hujjatlardan (ishonchsiz ma'lumot sifatida):")
            lines += [f"  · ({k['doc']}) {k['text'][:500]}" for k in know if k["score"] > 0.25]
        return "\n".join(lines)

    async def list(self, kind: str | None = None, q: str = "", limit: int = 200) -> list[MemoryItem]:
        async with SessionLocal() as db:
            stmt = select(MemoryItem).where(MemoryItem.user_id == self.user_id)
            if kind:
                stmt = stmt.where(MemoryItem.kind == kind)
            if q:
                stmt = stmt.where(MemoryItem.content.ilike(f"%{q}%") | MemoryItem.subject.ilike(f"%{q}%"))
            return (await db.scalars(stmt.order_by(desc(MemoryItem.updated_at)).limit(limit))).all()

    async def forget(self, memory_id: int) -> bool:
        async with SessionLocal() as db:
            r = await db.execute(delete(MemoryItem).where(MemoryItem.id == memory_id,
                                                          MemoryItem.user_id == self.user_id))
            await db.commit()
            return r.rowcount > 0

    async def project_context(self, name: str) -> str:
        """Everything ROBIN knows about a project: goal, tech, done & remaining work."""
        items = await self.search(f"loyiha {name} project", limit=15, kinds=["project", "decision", "workflow", "fact"])
        async with SessionLocal() as db:
            convs = (await db.scalars(select(Conversation).where(
                Conversation.user_id == self.user_id,
                (Conversation.project.ilike(f"%{name}%")) | (Conversation.title.ilike(f"%{name}%")))
                .order_by(desc(Conversation.updated_at)).limit(5))).all()
        out = [f"- [{m.kind}] {m.subject}: {m.content}" for m in items]
        out += [f"- suhbat '{c.title}' ({c.updated_at:%Y-%m-%d}): {c.summary[:600]}" for c in convs if c.summary]
        return "\n".join(out) or "Bu loyiha bo'yicha xotira topilmadi."

    # ------------------------------------------------------------ self-learning
    async def lessons(self, limit: int = 30) -> list[str]:
        async with SessionLocal() as db:
            rows = (await db.scalars(select(Feedback).where(Feedback.user_id == self.user_id,
                                                            Feedback.lesson != "")
                                     .order_by(desc(Feedback.id)).limit(limit))).all()
        return [r.lesson for r in rows]

    # ------------------------------------------------------------ knowledge
    async def add_document(self, name: str, path: str, text: str, mime: str = "", size: int = 0) -> KnowledgeDoc:
        chunks = chunk_text(text)
        async with SessionLocal() as db:
            doc = KnowledgeDoc(user_id=self.user_id, name=name, path=path, mime=mime, size=size, chunks=len(chunks))
            db.add(doc)
            await db.flush()
            for i, c in enumerate(chunks):
                db.add(KnowledgeChunk(doc_id=doc.id, user_id=self.user_id, idx=i, text=c,
                                      embedding=await self._vec(c)))
            await db.commit()
            await db.refresh(doc)
            return doc

    async def search_knowledge(self, query: str, limit: int = 5) -> list[dict]:
        sem, loc = await self._query_vecs(query)
        async with SessionLocal() as db:
            rows = (await db.execute(select(KnowledgeChunk, KnowledgeDoc.name)
                                     .join(KnowledgeDoc, KnowledgeDoc.id == KnowledgeChunk.doc_id)
                                     .where(KnowledgeChunk.user_id == self.user_id))).all()
        scored = []
        for ch, docname in rows:
            vs = cosine(sem, ch.embedding) if sem and len(sem) == len(ch.embedding) else cosine(loc, ch.embedding)
            scored.append({"score": round(0.7 * vs + 0.3 * keyword_score(query, ch.text), 4),
                           "doc": docname, "doc_id": ch.doc_id, "idx": ch.idx, "text": ch.text})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]


def extract_text(path: str) -> str:
    """Read PDF / Word / Excel / CSV / text into plain text for the Knowledge Center."""
    from pathlib import Path
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    if ext == ".docx":
        import docx
        d = docx.Document(str(p))
        parts = [para.text for para in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts)
    if ext in (".xlsx", ".xlsm", ".xls", ".csv"):
        import pandas as pd
        if ext == ".csv":
            sheets = {"csv": pd.read_csv(p)}
        else:
            sheets = pd.read_excel(p, sheet_name=None)
        return "\n\n".join(f"## {n}\n{df.to_csv(index=False)}" for n, df in sheets.items())
    return p.read_text(encoding="utf-8", errors="ignore")
