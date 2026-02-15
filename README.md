# article_recommender
📬 AI Newsletter Article Recommender

An AI-powered local agent that analyzes your Gmail newsletter subscriptions and recommends the most relevant articles — using semantic ranking and LLM summaries.

This project combines Gmail API + OpenAI embeddings + LLM summarization to help you extract signal from newsletter overload.

🚀 What It Does

This AI agent:

Connects securely to your Gmail (read-only access)

Searches emails by label and date range

Extracts article links from newsletters

Filters noise (social links, ads, demo pages, tracking URLs)

Uses semantic embeddings (not just keywords)

Ranks articles based on relevance to your search topic

Generates structured AI summaries

Outputs a clean Markdown digest

All runs locally on your machine.

🧠 How It Works (High-Level Architecture)

Gmail API → fetches emails (read-only scope)

Link extraction + filtering → removes non-article noise

Embedding model (text-embedding-3-small) → semantic similarity ranking

LLM summarization (gpt-4o-mini) → structured summaries

Cost guard system → prevents unexpected API spending

Markdown output → saved in /output

🛡 Security Design

This project was designed to be safe for public repositories.

No credentials stored in code

No API keys committed

Uses .env for local configuration

Uses local secrets/ directory (gitignored)

Gmail scope: gmail.readonly

Cost control & token limits enabled

Sensitive files (never committed):

.env
secrets/
output/
credentials.json
token.json
openai_key.txt

📦 Setup

1️⃣ Clone the repository
git clone https://github.com/yourusername/article_recommender.git
cd article_recommender

2️⃣ Create virtual environment
python -m venv venv
source venv/bin/activate

3️⃣ Install dependencies
pip install -r requirements.txt

4️⃣ Create local secrets folder
mkdir secrets


Place inside:

credentials.json → Gmail OAuth Desktop credentials

openai_key.txt → your OpenAI API key (plain text)

5️⃣ Create .env

GMAIL_CREDENTIALS_PATH=secrets/credentials.json

GMAIL_TOKEN_PATH=secrets/token.json

OPENAI_API_KEY_PATH=secrets/openai_key.txt

DRY_RUN=0

SUMMARY_MODEL=gpt-4o-mini

SUMMARY_FALLBACK_MODEL=gpt-4o-mini


▶️ Run the Agent
python src/recommender.py


You will be prompted to enter:

Gmail label (e.g. InspoNews)

Date range

Optional search keyword

Number of articles

Output will be saved in:

output/daily_digest_YYYY-MM-DD.md

💰 Cost Control

This project includes:

Budget guard

Max articles limit

Max excerpt length

Max summary tokens

Optional DRY_RUN mode (0$ testing)

Typical cost per run: ~$0.001–$0.003

🧪 Example Output Structure

Each recommended article includes:

Email subject

Email date

Source URL

Semantic similarity score

Structured summary:

Key Points

Why It Matters

🔧 Tech Stack

Python

Gmail API

OpenAI API

Semantic Embeddings

BeautifulSoup

Requests

dotenv

Markdown output

🎯 Why This Project Matters

Newsletter overload is real.

This AI agent turns inbox noise into:

Focused knowledge

Strategically ranked content

AI-generated executive summaries

Built as a practical example of:

AI agent prototyping

LLM orchestration

Cost-aware AI engineering

Secure API integration

👑 Author

Built by Maria — Just a curious Product Manager
