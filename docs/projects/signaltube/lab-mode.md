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

Persist topics for unattended overnight runs:

```bash
python3 ops/signaltube_lab.py topics add --topic "latest space videos" --max-candidates 24
python3 ops/signaltube_lab.py topics add --topic "LLM research" --max-candidates 24
python3 ops/signaltube_lab.py topics list
```

Run the configured overnight collector immediately:

```bash
python3 ops/signaltube_lab.py scheduled-collect
```

Publish the rendered feed to the shared FileGator host:

```bash
python3 ops/signaltube_lab.py publish --username "$SIGNALTUBE_PUBLISH_USERNAME" --password "$SIGNALTUBE_PUBLISH_PASSWORD"
```

Store ranking feedback signals:

```bash
python3 ops/signaltube_lab.py feedback --topic "latest space videos" --video-id abcDEF_1234 --signal save
python3 ops/signaltube_lab.py feedback --topic "latest space videos" --video-id abcDEF_1234 --signal too_clickbait
```

The rendered feed now copies the matching feedback CLI command to the clipboard when you click a feedback button, so the overnight ranker can learn from those stored signals on later runs.

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

Install the overnight timer on Server3:

```bash
bash ops/signaltube/install_overnight_collector.sh apply
sudo systemctl --no-pager --full status signaltube-lab-overnight.timer signaltube-lab-overnight.service
```

Timer configuration lives in `/etc/default/signaltube-lab`, with the repo example at `infra/env/signaltube-lab.env.example`.

If `SIGNALTUBE_PUBLISH_USERNAME` and `SIGNALTUBE_PUBLISH_PASSWORD` are present in that env file, both `scheduled-collect` and `render` now auto-publish the rendered feed to `https://mavali.top/projects/SignalTube/index.html` by default. Override the destination with:

- `SIGNALTUBE_PUBLISH_BASE_URL`
- `SIGNALTUBE_PUBLISH_PUBLIC_BASE_URL`
- `SIGNALTUBE_PUBLISH_REMOTE_DIR`
- `SIGNALTUBE_PUBLISH_REMOTE_NAME`
- `SIGNALTUBE_PUBLISH_PLAYWRIGHT_PYTHON`
