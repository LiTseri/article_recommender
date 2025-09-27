import os
import re
import base64
import datetime as dt
from typing import List, Tuple, Dict

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import requests
from bs4 import BeautifulSoup
from time import sleep

# === Config / Debug switches ===
load_dotenv()
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "secrets/credentials.json")
TOKEN_PATH       = os.getenv("GMAIL_TOKEN_PATH",        "secrets/token.json")

# limits (ώστε να μη σέρνεται)
LIMIT_EMAILS    = int(os.getenv("LIMIT_EMAILS", "25"))   # πόσα emails max
LIMIT_LINKS     = int(os.getenv("LIMIT_LINKS", "40"))    # πόσα links max (πριν το κατέβασμα)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "6")) # δευτερόλεπτα ανά σελίδα

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ArticleRecommender/1.0)"}
URL_REGEX = re.compile(r'https?://[^\s<>\)\("]+')

SKIP_HOSTS = {
    # static assets / CDNs / fonts / images / tracking
    "fonts.gstatic.com", "fonts.googleapis.com", "static-assets", "cdn.",
    "media.beehiiv.com", "static_assets", "gstatic.com", "doubleclick.net",
    "facebook.com", "instagram.com", "tiktok.com", "twitter.com", "x.com",
    "mailto:", "accounts.google.com", "support.google", "google.com/mail"
}
SKIP_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
             ".woff", ".woff2", ".ttf", ".otf", ".css", ".js", ".mp4", ".mov"}

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
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)

def build_query(labels, start_date, end_date) -> str:
    parts = []
    for lab in labels:
        lab = lab.strip()
        if lab:
            parts.append(f'label:"{lab}"')
    if start_date:
        parts.append(f"after:{start_date}")   # YYYY/MM/DD
    if end_date:
        parts.append(f"before:{end_date}")    # YYYY/MM/DD
    return " ".join(parts).strip()

def _decode_body(data_b64: str) -> str:
    try:
        return base64.urlsafe_b64decode(data_b64.encode("utf-8")).decode("utf-8", errors="ignore")
    except Exception:
        return ""

def extract_email_body(msg: Dict) -> Tuple[str, str]:
    payload = msg.get("payload", {})
    parts = payload.get("parts")
    body_plain, body_html = "", ""

    def walk(p):
        nonlocal body_plain, body_html
        if "parts" in p:
            for sub in p["parts"]:
                walk(sub)
        else:
            mime = p.get("mimeType", "")
            data = p.get("body", {}).get("data")
            if data:
                text = _decode_body(data)
                if "text/plain" in mime:
                    body_plain += text + "\n"
                elif "text/html" in mime:
                    body_html += text + "\n"

    if parts:
        walk(payload)
    else:
        data = payload.get("body", {}).get("data")
        if data:
            mime = payload.get("mimeType", "")
            text = _decode_body(data)
            if "text/html" in mime:
                body_html += text
            else:
                body_plain += text

    return body_plain, body_html

def is_probably_article(url: str) -> bool:
    low = url.lower()
    # extensions
    if any(low.endswith(ext) for ext in SKIP_EXTS):
        return False
    # hosts/patterns
    if any(h in low for h in SKIP_HOSTS):
        return False
    # very short urls usually aren't articles
    if len(url) < 15:
        return False
    return True

def extract_links(text: str):
    if not text:
        return []
    urls = URL_REGEX.findall(text)
    cleaned = []
    for u in urls:
        u = u.rstrip(").,;\"'")
        if not is_probably_article(u):
            continue
        cleaned.append(u)
    # unique preserve order
    seen, out = set(), []
    for u in cleaned:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

def fetch_page_info(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        ct = r.headers.get("Content-Type", "").lower()
        if "text/html" not in ct:
            return "", "", 0
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        meta_title = soup.find("meta", property="og:title")
        title = (meta_title.get("content") if meta_title and meta_title.has_attr("content")
                 else (soup.title.string if soup.title else "")).strip()
        desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        desc = desc_tag.get("content").strip() if desc_tag and desc_tag.has_attr("content") else ""
        text_len = len(soup.get_text(separator=" ", strip=True))
        return title, desc, text_len
    except Exception:
        return "", "", 0

def score_article(title: str, desc: str, text_len: int, keywords):
    # απλή βαθμολόγηση
    t, d = title.lower(), desc.lower()
    score = 0.0
    for kw in keywords:
        k = kw.strip().lower()
        if not k:
            continue
        if k in t:
            score += 2
        if k in d:
            score += 1
    score += min(text_len / 4000.0, 2.0)
    return score

def main():
    print("=== Gmail Article Recommender (clean fetch) ===")
    print(f"[Config] LIMIT_EMAILS={LIMIT_EMAILS}, LIMIT_LINKS={LIMIT_LINKS}, REQUEST_TIMEOUT={REQUEST_TIMEOUT}s")
    labels = [x.strip() for x in input("Labels (π.χ. Newsletters,AI): ").split(",") if x.strip()] or ["Newsletters"]
    start_date = input("Αρχική ημερομηνία (YYYY/MM/DD): ").strip()
    end_date   = input("Τελική ημερομηνία (YYYY/MM/DD): ").strip()
    keywords   = [x.strip() for x in input("Λέξεις-κλειδιά (AI,LLM,...): ").split(",") if x.strip()]
    try:
        top_k = int(input("Πόσα άρθρα (π.χ. 5): ").strip() or "5")
    except:
        top_k = 5

    service = get_gmail_service()
    query = build_query(labels, start_date, end_date)
    print(f"\n[1/4] Ψάχνω με query: {query}")

    # IDs
    ids = []
    req = service.users().messages().list(userId="me", q=query, maxResults=100)
    pages = 0
    while req is not None:
        resp = req.execute()
        page_ids = [m["id"] for m in resp.get("messages", [])]
        ids.extend(page_ids)
        pages += 1
        print(f"   - Σελίδα {pages}: +{len(page_ids)} ids (σύνολο {len(ids)})")
        if len(ids) >= LIMIT_EMAILS:
            print(f"   - Έπιασα το όριο {LIMIT_EMAILS} emails. Σταματάω.")
            break
        req = service.users().messages().list_next(previous_request=req, previous_response=resp)

    ids = ids[:LIMIT_EMAILS]
    if not ids:
        print("   → Δεν βρέθηκαν μηνύματα. Έλεγξε σωστή ορθογραφία label/ημερομηνίες.")
        return

    # Bodies & links
    print(f"\n[2/4] Διαβάζω {len(ids)} μηνύματα & εξάγω links…")
    all_links = []
    for i, mid in enumerate(ids, 1):
        if i % 5 == 0 or i == len(ids):
            print(f"   - Προχώρησα {i}/{len(ids)} μηνύματα…")
        msg = service.users().messages().get(userId="me", id=mid, format="full").execute()
        body_txt, body_html = extract_email_body(msg)
        links = set(extract_links(body_txt) + extract_links(body_html))
        all_links.extend(list(links))

    # unique & limit
    unique_links, seen = [], set()
    for u in all_links:
        if u not in seen:
            seen.add(u)
            unique_links.append(u)
    if not unique_links:
        print("   → Δεν βρέθηκαν χρήσιμα links στα emails.")
        return
    if len(unique_links) > LIMIT_LINKS:
        print(f"   - Πολλά links ({len(unique_links)}). Κρατάω τα πρώτα {LIMIT_LINKS}.")
        unique_links = unique_links[:LIMIT_LINKS]

    print(f"   - Θα αξιολογήσω {len(unique_links)} links…")

    # Fetch & score
    print("\n[3/4] Κατεβάζω σελίδες & δίνω score…")
    scored = []
    for i, url in enumerate(unique_links, 1):
        if i % 5 == 0 or i == len(unique_links):
            print(f"   - {i}/{len(unique_links)}…")
        title, desc, text_len = fetch_page_info(url)
        if not title and not desc and text_len == 0:
            continue
        s = score_article(title, desc, text_len, keywords)
        scored.append({"url": url, "title": title or "(no title)", "desc": desc, "len": text_len, "score": s})
        sleep(0.03)

    if not scored:
        print("   → Δεν μπόρεσα να αξιολογήσω links (ίσως ήταν όλα assets/redirects).")
        return

    # Sort & report
    print("\n[4/4] Ταξινόμηση & αναφορά…")
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:top_k]

    print("\n--- Προτεινόμενα άρθρα ---")
    for i, it in enumerate(top, 1):
        print(f"{i}. {it['title']}\n   {it['url']}\n   score={it['score']:.2f}  len≈{it['len']}\n")

    today = dt.date.today().isoformat()
    os.makedirs("output", exist_ok=True)
    report_path = os.path.join("output", f"daily_digest_{today}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Daily Digest ({today})\n\n")
        f.write(f"**Labels:** {', '.join(labels)}  |  **Ημερομηνίες:** {start_date or '-'} → {end_date or '-'}\n\n")
        if keywords:
            f.write(f"**Λέξεις-κλειδιά:** {', '.join(keywords)}\n\n")
        for i, it in enumerate(top, 1):
            f.write(f"{i}. [{it['title']}]({it['url']})\n")
            if it['desc']:
                f.write(f"   {it['desc']}\n")
            f.write(f"   _score={it['score']:.2f}, len≈{it['len']}_\n\n")
    print(f"Αποθηκεύτηκε: {report_path}\n✅ Έτοιμο!")
    

if __name__ == "__main__":
    main()

