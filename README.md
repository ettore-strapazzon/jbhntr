# JBHNTR

**An AI job-search agent that reads the market for you.**

JBHNTR scans job boards, niche sources and company career pages, then ranks each
role against both what the candidate wants and what the employer requires. The
output is a reasoned shortlist, not another feed to scroll.

Live at [jbhntr.app](https://jbhntr.app).

<!-- SCREENSHOT: replace with a real screenshot of the search results page -->
![JBHNTR search results](docs/screenshot.png)

---

## Why I built it

Job hunting is mostly noise. The roles worth applying to are spread across dozens
of boards and company career pages, LinkedIn hides most of them behind its feed,
and plain keyword search tends to either bury you or skip the one job that
actually fits. I wanted something closer to a good recruiter: one that
understands your background, reads a lot of postings, and hands back an honest
ranked shortlist when a scan runs; the shared corpus itself is refreshed on a
schedule.

## What it does

It aggregates widely, from broad engines like Adzuna, Careerjet and Jooble to
niche remote boards and companies' own career pages (Greenhouse, Lever, Ashby
and friends). The engine supports 25+ configured source endpoints and source
types, including free feeds, metered APIs and direct employer ATS boards.
Production availability varies by configuration and geography.

You give it a few companies you admire and it goes looking for others like them,
then keeps an eye on their job boards for you.

The scoring works both ways. It checks how well a role matches what you want, but
also whether you plausibly meet the job's main requirements, then sorts
everything into clear tiers from "apply now" down to "long shot", each with a
short note on why it fits and why it might not.

Under the hood, every job is embedded and matched to your profile by meaning, so
the expensive AI scoring only runs on a small, relevant shortlist. It pays
attention to location too (onsite, hybrid or remote, and which country), so an
Italy-based search doesn't fill up with roles in the US.

When you find something you like, it can draft a tailored CV and cover letter for
that specific role.

The whole thing runs as a web app with email or Google sign-in, a guided setup, a
freemium plan, and careful handling of your data (uploads are encrypted, and you
can export or delete everything).

## How it works

There are two halves. A scheduled job fetches from every source once for all
users, tags and embeds each posting, and stores it in a shared database, with a
cleanup pass that drops listings once they go dead. Searches then read from that
database: filter by location, rank by meaning, score the top of the list with AI.
Verdicts are cached, so running a similar search again costs almost nothing.

**Built with:** Python, FastAPI, SQLAlchemy, Postgres, Jinja2 and HTMX
(server-rendered, no JavaScript build step), fastembed for on-device embeddings,
Claude through OpenRouter, deployed on Railway behind Cloudflare.

The product was designed by Ettore Strapazzon and implemented through an extended
collaboration with AI coding agents. The repository documents the architecture,
trade-offs and tests so the system can be inspected rather than treated as a
black box. The reasoning behind the bigger decisions lives in [docs/](docs/).

> **Development note.** The architecture and the calls were mine; the
> implementation came out of a long back-and-forth with AI coding agents,
> including a few parts I had never written by hand before, like the embeddings,
> the shared job corpus and the ATS integrations.

## Running it locally

```bash
git clone https://github.com/<you>/jbhntr.git && cd jbhntr
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-web.txt
cp .env.example .env                                 # then fill in a few free keys
python -c "from web.app.db import init_db; init_db()"
uvicorn web.app.main:app --reload                    # http://localhost:8000
```

Everything works for free out of the box. The embeddings run locally with no key,
and the AI just needs one provider key (an OpenRouter key is enough). To put it
online, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

There's also the original personal CLI, which writes a ranked Google Sheet once a
day. See [config/profile.example.yaml](config/profile.example.yaml) and
`python -m jobhunter.run`.

## What's still on the list

- A proper free/paid split (free reads the cached database, paid triggers a fresh fetch)
- Crypto checkout in USDC/USDT, currently a "coming soon"
- Better matching on the borderline roles
- Paid data sources for the markets the free ones miss

## License

MIT, see [LICENSE](LICENSE).
