# SignalTube Lab Mode

SignalTube Lab Mode is the first local experiment for an AI-curated YouTube-style front page.

The initial provider uses Browser Brain against a logged-out disposable browser profile. It is intentionally bounded:

- no YouTube account automation
- no downloads
- no transcript harvesting at scale
- no infinite crawler
- minimal cached data: video id, title, source topic, and derived playback/thumbnail URLs
- Browser Brain discovery is expected to be fragile if YouTube changes the page

Run a small collection:

```bash
python3 ops/signaltube_lab.py collect --topic "latest space videos" --topic "LLM research"
```

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

The collector refuses to run if a Browser Brain snapshot looks logged into YouTube. It also requires a visible logged-out marker by default, because this lab mode should not operate through the owner's personal YouTube session.

It also refuses Browser Brain `existing_session` mode. Run this against a managed disposable Browser Brain profile, not the visible TV/login browser.
