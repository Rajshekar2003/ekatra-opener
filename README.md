# Cold-email opener tool

Give it a company website. It drafts a 3-line opener for a cold email to the founder, using only what the site says.

## Run
```bash
pip install -r requirements.txt
export GEMINI_API_KEY=your_key        # free key: https://aistudio.google.com/apikey
python opener.py https://company.com
python opener.py --file urls.txt --workers 4 --out results.json
python test_opener.py                 # offline tests, no key needed
```
Model name can be changed: `export LLM_MODEL=<model-name>`.

## What runs where
- **Code:** URL safety (blocks private addresses, also on redirects), fetch with time and size limits, text cleanup, 7-day cache per domain, retries, and output checks (3 lines, no banned phrases, the quoted detail must appear word for word on the page).
- **Model:** picks one real detail from the page and writes 3 short lines. Nothing else.
- **Human:** anything that fails the checks is returned as `needs_human` with a reason. It never sends email.

## At 1,000 runs a day
About 2M input and 0.12M output tokens. Cost = tokens x your model's price (check the current price page). Cache hits cost nothing.
Breaks first: JavaScript-only or bot-blocked sites, API rate limits, thin sites. Next fixes: a queue with a rate limiter and a headless-browser fallback.

Windows PowerShell: use `$env:GEMINI_API_KEY="your_key"` instead of `export`.

## Sample output
`sample_results.json` has real results for 5 company sites (made with `urls.txt`).

## Known limits
- The word-for-word check proves the quoted detail is on the page. It does not prove the meaning is right. Early on, one run credited a customer quote on a site to the company itself. The prompt now says to use only what the company itself does. A second model pass that checks meaning is the next step.
- Line 2 of each opener is a guess about a problem, not a fact.
- Sites that need JavaScript to show text, or that block bots, return `needs_human` or `fetch_failed`.
- It only drafts text. It never sends email.
