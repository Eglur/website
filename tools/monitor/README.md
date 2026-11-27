# Eglur morning briefing (prototype)

An 80/20 political monitor built only from public data. It's published at **www.eglurtech.com/monitor/**. It isn't linked from the site, and search engines are told not to index it.

Each weekday at 05:40 UTC it:
1. Reads the previous day's official Westminster business: written questions and answers (both Houses), ministerial statements, bill stages and Commons votes, plus Senedd written questions and answers.
2. Keeps the items that match the office's keywords.
3. Has Claude rank each item 0–10 against a plain-English office profile and explain it: what happened, why it matters to this office, and a suggested next step.
4. Publishes an Eglur-branded page. Items scoring 9+ go under **Needs you today** and 6–8 under **Worth knowing**. Past briefings are saved at `/monitor/archive.html`.

## One-time setup
1. **Create a Claude API key** in the Claude Console (console.anthropic.com) and set a monthly spend limit. API use is billed separately from a Claude.ai plan.
2. **Add the key to this repo:** open https://github.com/Eglur/website/settings/secrets/actions/new, set the name to `ANTHROPIC_API_KEY`, paste the key, and click **Add secret**.
3. **Run it:** open https://github.com/Eglur/website/actions/workflows/monitor.yml and click **Run workflow**. A minute or two later, the page is live.

Until the key is added, the briefing still runs in keyword-only mode, and the page says so.

## Tailoring
Edit `tools/monitor/profile.toml` on GitHub (open it and click the pencil icon). Saving the change re-runs the briefing.
- `description`: who the office is and what it cares about. This drives the AI's judgement most.
- `keywords`: the first-pass filter. `GP` matches GP and GPs. `farm*` matches farm, farmer and farming.
- `min_score`: raise it for a shorter briefing, lower it for a longer one.

## The side-by-side test
Run it for two weeks alongside a PolicyMogul trial set to the same topics. Each day, note what each one caught, what each one missed, which items wasted time, and the minutes it took to read each.

## Brand
The page uses the site's own tokens, wordmark, favicon and fonts. Colours are copied into `monitor.py`. The wordmark and `@font-face` rules are in `brand/`, and the font files are in `/fonts/` at the site root. If the site's brand changes, update `brand/` and the `:root` block in `monitor.py`.

## Testing offline
```
cd tools/monitor
python -m unittest discover tests -v                     # 15 tests, no internet needed
python tests/make_preview.py /tmp/preview                # sample briefing from real items
```

## If something goes wrong
- **Actions tab → the failed run → the red step** shows the error.
- *Push rejected (permission):* go to Settings → Actions → General → Workflow permissions and choose **Read and write**.
- *The page doesn't update but the run succeeded:* the Pages rebuild request was refused. Any later change to the site republishes it. Check the run's warning line.
- *One source fails:* the briefing still builds from the others, and the log shows a `WARNING` line.

## Things to know
- This repo is public, so the code, the profile and past briefings can be seen. That's fine for public data and an example profile. Don't add a real office's private priorities without their agreement.
- An unlisted page isn't a password-protected one: anyone with the link can read it.
- Parliamentary data is reused under the Open Parliament Licence v3.0, credited in the page footer.
- Senedd data is reused under the Open Government Licence.
- Next: Senedd plenary business and votes, Welsh Government and GOV.UK announcements, and a look-ahead of upcoming business.
