# SignalTube Lab Mode

SignalTube Lab Mode is the first local experiment for an AI-curated YouTube-style front page.

The initial provider uses Browser Brain against a logged-out disposable browser profile. It is intentionally bounded:

- no YouTube account automation
- no downloads
- no transcript harvesting at scale
- no infinite crawler
- minimal cached data: video id, title, channel, publish timestamp when available, source topic, and derived playback/thumbnail URLs
- Browser Brain discovery is expected to be fragile if YouTube changes the page

Run a small collection:

```bash
ops/signaltube_lab_browser.sh start
python3 ops/signaltube_lab.py collect --topic "latest space videos" --topic "LLM research"
```

Collection enriches each candidate with `yt-dlp` metadata by default so the rendered feed can show the publishing date/time for each video without downloading media. Use `--skip-youtube-metadata` for a faster Browser Brain-only discovery pass when publish times are not needed.

Render an existing feed:

```bash
python3 ops/signaltube_lab.py render
```

Global options such as `--db`, `--html`, and `--browser-brain-url` must be placed before the subcommand:

```bash
python3 ops/signaltube_lab.py --html /tmp/signaltube-feed.html render
```

Default local outputs:

- SQLite DB: `private/signaltube/signaltube.sqlite`
- HTML feed: `private/signaltube/feed.html`
- Disposable Browser Brain state: `private/signaltube/browser-brain`

The collector refuses to run if a Browser Brain snapshot looks logged into YouTube. It also requires a visible logged-out marker by default, because this lab mode should not operate through the owner's personal YouTube session.

It also refuses Browser Brain `existing_session` mode. Run this against a managed disposable Browser Brain profile, not the visible TV/login browser.

The helper `ops/signaltube_lab_browser.sh` starts that disposable managed Browser Brain server on `127.0.0.1:47832`.
