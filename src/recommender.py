import os
import re
import base64
import datetime as dt
from typing import List, Dict, Tuple
from urllib.parse import urlparse

from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from openai import OpenAI
import numpy as np


# =========================
# ENV + CONFIG
# =========================
load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "secrets/credentials.json")
TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "secrets/token.json")
OPENAI_API_KEY_PATH = os.getenv("OPENAI_API_KEY_PATH", "secrets/openai_key.txt")

# keep both naming styles supported
SUMMARY_MODEL = os.getenv("OPENAI_SUMMARY_MODEL", os.getenv("SUMMARY_MODEL", "gpt-4o-mini"))
SUMMARY_FALLBACK_MODEL = os.getenv("OPENAI_SUMMARY_FALLBACK_MODEL", os.getenv("SUMMARY_FALLBACK_MODEL", "gpt-4o-mini"))
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", os.getenv("EMBED_MODEL", "text-embedding-3-small"))

DRY_RUN = os.getenv("DRY_RUN", "0").strip().lower() in ("1", "true", "yes")

LIMIT_EMAILS = int(os.getenv("LIMIT_EMAILS", "25"))
LIMIT_LINKS = int(os.getenv("LIMIT_LINKS", "120"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))

MAX_ARTICLES = int(os.getenv("MAX_ARTICLES", "12"))
EXCERPT_CHARS = int(os.getenv("MAX_EXCERPT_CHARS", "2200"))
SUMMARY_TOKENS = int(os.getenv("MAX_SUMMARY_TOKENS", "260"))
BUDGET = float(os.getenv("BUDGET", "0.10"))

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ArticleRecommender/1.0)"}
URL_REGEX = re.compile(r'https?://[^\s<>\)\("]+')


# =========================
# NOISE FILTERING (strong but fair)
# =========================
SKIP_HOSTS = {
    "fonts.gstatic.com", "fonts.googleapis.com",
    "media.beehiiv.com", "gstatic.com",
    "doubleclick.net",
}
SKIP_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".otf",
    ".css", ".js", ".mp4", ".mov",
}

NOISE_URL_SUBSTRINGS = [
    "book-a-call", "demo", "pricing", "subscribe", "preferences",
    "media-kit", "mediakit", "sponsor", "advertis", "partners",
    "utm_", "ref=", "signup", "register", "/careers", "/jobs",
    "tiktok.com", "x.com/", "twitter.com/", "instagram.com/",
    "passionfroot.me", "link.courses.maven.com",
]

CONTENT_HINTS = [
    "/p/", "/post/", "/posts/", "/blog/", "/article/", "/news/",
    "/202", "substack.com", "medium.com", "archive.", "marktechpost",
    "towardsdatascience", "hbr.org", "arxiv.org", "github.com",
]

def looks_like_asset(url: str) -> bool:
    u = (url or "").lower()
    return any(u.endswith(ext) for ext in SKIP_EXTS)

def host_is_skipped(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        return host in SKIP_HOSTS
    except Exception:
        return False

def is_noise_url(url: str) -> bool:
    if not url:
        return True
    u = url.lower()
    if host_is_skipped(url) or looks_like_asset(url):
        return True
    if any(s in u for s in NOISE_URL_SUBSTRINGS):
        return True
    if u.rstrip("/") in ("https://x.com", "https://twitter.com", "https://tiktok.com"):
        return True
    return False

def prefer_content_url(url: str) -> bool:
    u = (url or "").lower()
    return any(h in u for h in CONTENT_HINTS)


# =========================
# OPENAI CLIENT
# =========================
def get_openai_client() -> OpenAI:
    if not OPENAI_API_KEY_PATH or not os.path.exists(OPENAI_API_KEY_PATH):
        raise RuntimeError("Missing OPENAI_API_KEY_PATH or file not found (secrets/openai_key.txt).")
    key = open(OPENAI_API_KEY_PATH, "r", encoding="utf-8").read().strip()
    return OpenAI(api_key=key)


# =========================
# GMAIL AUTH
# =========================
def get_gmail_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=8080)

        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        with open(TOKEN_PATH, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# =========================
# Gmail helpers
# =========================
def _header(payload: dict, name: str) -> str:
    for h in payload.get("headers", []) or []:
        if (h.get("name") or "").lower() == name.lower():
            return h.get("value") or ""
    return ""

def _internal_date_to_iso(msg: dict) -> str:
    try:
        ms = int(msg.get("internalDate", "0"))
        d = dt.datetime.utcfromtimestamp(ms / 1000.0).date()
        return d.isoformat()
    except Exception:
        return ""

def _decode_html_part(payload: dict) -> str:
    def walk(parts):
        for p in parts or []:
            mime = p.get("mimeType", "")
            if mime in ("text/html", "text/plain"):
                data = (p.get("body", {}) or {}).get("data")
                if data:
                    try:
                        return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                    except Exception:
                        pass
            inner = p.get("parts")
            if inner:
                got = walk(inner)
                if got:
                    return got
        return ""

    if payload.get("mimeType") in ("text/html", "text/plain"):
        data = (payload.get("body", {}) or {}).get("data")
        if data:
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            except Exception:
                pass

    return walk(payload.get("parts", []))

def read_email_and_links(service, msg_id: str) -> Tuple[Dict, List[str]]:
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    payload = msg.get("payload", {}) or {}

    subject = _header(payload, "Subject").strip() or "(no subject)"
    date_iso = _internal_date_to_iso(msg) or ""
    from_ = _header(payload, "From").strip()

    body = _decode_html_part(payload) or ""
    links = URL_REGEX.findall(body)

    uniq = []
    seen = set()
    for u in links:
        if u not in seen:
            seen.add(u)
            uniq.append(u)

    email_meta = {
        "id": msg_id,
        "subject": subject,
        "date": date_iso,
        "from": from_,
        "body": body,
    }
    return email_meta, uniq


# =========================
# URL resolve
# =========================
def resolve_url(url: str) -> str:
    try:
        r = requests.head(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if r.url:
            return r.url
    except Exception:
        pass
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        return r.url or url
    except Exception:
        return url


# =========================
# Web fetch
# =========================
def fetch_page_text(url: str) -> Tuple[str, str]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else "(no title)"
        text = soup.get_text(separator=" ", strip=True)
        return title, (text or "")[:EXCERPT_CHARS]
    except Exception:
        return "(no title)", ""


# =========================
# Embeddings + ranking
# =========================
def cosine_sim(a, b) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

def rank_candidates(client: OpenAI, candidates: List[Dict], query_text: str) -> List[Dict]:
    if not query_text.strip():
        for c in candidates:
            c["similarity"] = 0.0
            c["heur_score"] = (1 if prefer_content_url(c["url"]) else 0) * 100000 + len(c.get("excerpt", ""))
        return sorted(candidates, key=lambda x: x.get("heur_score", 0), reverse=True)

    texts = [query_text] + [c["title"] + "\n" + c["excerpt"] for c in candidates]
    emb = client.embeddings.create(model=EMBED_MODEL, input=texts)
    vecs = [d.embedding for d in emb.data]
    qv = vecs[0]

    for i, c in enumerate(candidates):
        c["similarity"] = cosine_sim(qv, vecs[i + 1])

    return sorted(candidates, key=lambda x: x["similarity"], reverse=True)


# =========================
# Diversity selection (NEW!)
# 1 per email όσο γίνεται, αλλιώς fill with next best
# =========================
def select_with_diversity(ranked: List[Dict], top_n: int) -> List[Dict]:
    if top_n <= 0:
        return []

    selected: List[Dict] = []
    used_emails = set()

    # Pass 1: pick best from distinct emails
    for c in ranked:
        eid = c.get("email_id")
        if eid and eid not in used_emails:
            selected.append(c)
            used_emails.add(eid)
            if len(selected) >= top_n:
                return selected

    # Pass 2: fill remaining with next best overall (can repeat emails)
    for c in ranked:
        if c in selected:
            continue
        selected.append(c)
        if len(selected) >= top_n:
            break

    return selected


# =========================
# Summaries
# =========================
def generate_summary(client: OpenAI, title: str, url: str, excerpt: str) -> str:
    prompt = (
        "You are summarizing ONE specific article from a newsletter.\n"
        "Return ONLY this markdown structure, in English:\n\n"
        "### Key Points:\n"
        "- (3 bullets)\n\n"
        "### Why It Matters:\n"
        "(1-2 sentences)\n\n"
        f"Article Title: {title}\n"
        f"Article URL: {url}\n\n"
        f"Content:\n{excerpt}"
    )

    if DRY_RUN:
        return "### Key Points:\n- (DRY_RUN)\n- (No API call)\n- \n\n### Why It Matters:\n(DRY_RUN)\n"

    resp = client.responses.create(
        model=SUMMARY_MODEL,
        input=[{"role": "user", "content": prompt}],
        max_output_tokens=SUMMARY_TOKENS,
    )
    txt = (resp.output_text or "").strip()
    if txt:
        return txt

    resp2 = client.responses.create(
        model=SUMMARY_FALLBACK_MODEL,
        input=[{"role": "user", "content": prompt}],
        max_output_tokens=SUMMARY_TOKENS,
    )
    txt2 = (resp2.output_text or "").strip()
    return txt2 if txt2 else "_(Summary unavailable — model returned empty output.)_"


# =========================
# MAIN
# =========================
def main():
    print("=== Gmail Article Recommender (Grouped by Email + Diversity 1/email) ===")
    print(f"[Config] LIMIT_EMAILS={LIMIT_EMAILS}, LIMIT_LINKS={LIMIT_LINKS}, TIMEOUT={REQUEST_TIMEOUT}s")
    print(f"[Models] EMBED={EMBED_MODEL} | SUMMARY={SUMMARY_MODEL} (fallback={SUMMARY_FALLBACK_MODEL}) | DRY_RUN={DRY_RUN}")

    labels = input("Labels (e.g. InspoNews,Newsletters): ").strip()
    start = input("Start date (YYYY/MM/DD): ").strip()
    end = input("End date (YYYY/MM/DD): ").strip()

    keyword = input(
        "Give me your search keyword (optional). If you want to make the search more specific, type it; otherwise hit Enter: "
    ).strip()

    top_n_raw = input("How many articles should I recommend (e.g. 5): ").strip()
    top_n = int(top_n_raw) if top_n_raw.isdigit() else 5
    top_n = max(1, min(top_n, MAX_ARTICLES))

    service = get_gmail_service()
    client = get_openai_client()

    gmail_query = f'label:"{labels}" after:{start} before:{end}'
    print(f"\n[1/5] Gmail query: {gmail_query}")

    results = service.users().messages().list(userId="me", q=gmail_query, maxResults=LIMIT_EMAILS).execute()
    msg_ids = [m["id"] for m in (results.get("messages") or [])]
    if not msg_ids:
        print("No emails found for that label/date range.")
        return

    print(f"\n[2/5] Reading {min(LIMIT_EMAILS, len(msg_ids))} emails & extracting links…")

    emails_by_id: Dict[str, Dict] = {}
    candidates: List[Dict] = []
    global_seen_urls = set()

    for i, msg_id in enumerate(msg_ids[:LIMIT_EMAILS], 1):
        email_meta, links = read_email_and_links(service, msg_id)
        emails_by_id[msg_id] = email_meta

        for raw_url in links:
            if len(candidates) >= LIMIT_LINKS:
                break
            if is_noise_url(raw_url):
                continue

            final_url = resolve_url(raw_url)
            if is_noise_url(final_url):
                continue

            # global dedup
            if final_url in global_seen_urls:
                continue
            global_seen_urls.add(final_url)

            title, excerpt = fetch_page_text(final_url)
            source = "web"

            if not excerpt.strip():
                excerpt = (email_meta.get("body") or "")[:EXCERPT_CHARS]
                source = "email"

            if not excerpt.strip():
                continue

            if (title or "").strip() in ("", "(no title)"):
                title = "(no title) — from email: " + email_meta.get("subject", "(no subject)")

            candidates.append({
                "url": final_url,
                "title": title,
                "excerpt": excerpt,
                "source": source,

                "email_id": msg_id,
                "email_subject": email_meta["subject"],
                "email_date": email_meta["date"],
                "email_from": email_meta["from"],
            })

        if i % 5 == 0:
            print(f"   - {i}/{min(LIMIT_EMAILS, len(msg_ids))} emails processed")

    print(f"   - Candidate articles collected: {len(candidates)}")
    if not candidates:
        print("No usable candidates (filters removed everything). Try widening date range.")
        return

    # Cost guard (rough)
    est = 0.001 + 0.00035 * top_n
    print(f"\n[Cost guard] Estimated run cost ≈ ${est:.4f} (budget ${BUDGET:.2f})")
    if est > BUDGET:
        print("❌ Estimated cost exceeds budget. Reduce top_n or increase BUDGET in .env.")
        return

    print("\n[3/5] Semantic ranking…")
    ranked_all = rank_candidates(client, candidates, keyword)

    # NEW: diversity selection
    ranked = select_with_diversity(ranked_all, top_n)

    print(f"\n[4/5] Generating summaries for top-{len(ranked)} (diverse) …")
    for idx, c in enumerate(ranked, 1):
        c["summary"] = generate_summary(client, c["title"], c["url"], c["excerpt"])
        print(f"   - {idx}/{len(ranked)} done")

    # Group results by email (for output clarity)
    grouped: Dict[str, List[Dict]] = {}
    for c in ranked:
        grouped.setdefault(c["email_id"], []).append(c)

    # Order email groups by appearance in ranked list
    email_order = []
    seen = set()
    for c in ranked:
        eid = c["email_id"]
        if eid not in seen:
            seen.add(eid)
            email_order.append(eid)

    print("\n[5/5] Writing markdown output…")
    today = dt.date.today().isoformat()
    os.makedirs("output", exist_ok=True)
    out_path = f"output/daily_digest_{today}.md"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Daily Digest ({today})\n\n")
        f.write(f"**Labels:** {labels}  |  **Dates:** {start} → {end}\n\n")
        f.write(f"**Search keyword (optional):** {keyword if keyword else '(none)'}\n\n")
        f.write(f"**Embedding model:** `{EMBED_MODEL}` | **Summary model:** `{SUMMARY_MODEL}`\n\n")
        f.write(f"**Mode:** Grouped by Email ✅ | **Diversity:** 1 article per email (as much as possible) ✅\n\n")
        f.write("---\n\n")

        f.write("## Top Picks (quick view)\n\n")
        for i, c in enumerate(ranked, 1):
            f.write(
                f"{i}. **{c['title']}**  \n"
                f"   - Article: {c['url']}  \n"
                f"   - From email: **{c['email_subject']}** ({c['email_date'] or 'unknown date'})\n\n"
            )

        f.write("---\n\n")
        f.write("## Picks grouped by Email\n\n")

        email_counter = 1
        for eid in email_order:
            meta = emails_by_id.get(eid, {})
            subj = meta.get("subject", "(no subject)")
            date_iso = meta.get("date", "(unknown)")
            sender = meta.get("from", "")

            f.write(f"### Email {email_counter}: {subj}\n")
            f.write(f"- **Date:** {date_iso}\n")
            if sender:
                f.write(f"- **Sender:** {sender}\n")
            f.write("\n")

            for j, c in enumerate(grouped.get(eid, []), 1):
                f.write(f"#### {email_counter}.{j} Article: {c['title']}\n")
                f.write(f"- URL: {c['url']}\n")
                if keyword.strip():
                    f.write(f"- Similarity: {c.get('similarity', 0.0):.4f}\n")
                f.write(f"- Excerpt source: {c.get('source','web')}\n\n")
                f.write(c["summary"].strip() + "\n\n")

            f.write("---\n\n")
            email_counter += 1

    print(f"✅ Done! Saved: {out_path}")


if __name__ == "__main__":
    main()

