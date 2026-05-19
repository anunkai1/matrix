from __future__ import annotations

import html
import ipaddress
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable, List, Optional
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse
from urllib.request import HTTPSHandler, Request, build_opener


DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/?q={query}"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_SEARCH_RESULTS = 5
DEFAULT_MAX_FETCHED_PAGES = 2
DEFAULT_MAX_PAGE_CHARS = 3500
USER_AGENT = "Mozilla/5.0 (compatible; Server3PiWebContext/1.0)"
URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
FORCE_WEB_PREFIX_RE = re.compile(r"^\s*(?:web|browse|search)\s*[:\-]\s*", re.IGNORECASE)
WEB_TRIGGER_RE = re.compile(
    r"\b(latest|current|today|recent|news|look up|lookup|search the web|search online|browse the web|on the internet)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class FetchedPage:
    url: str
    title: str
    text: str


@dataclass(frozen=True)
class WebContextResult:
    query: str
    context_text: str
    search_results: List[SearchResult]
    fetched_pages: List[FetchedPage]


class _SearchResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: List[SearchResult] = []
        self._current_href: Optional[str] = None
        self._current_title_parts: List[str] = []
        self._current_snippet_parts: List[str] = []
        self._capture_title = False
        self._capture_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attrs_dict = dict(attrs)
        classes = attrs_dict.get("class", "") or ""
        if tag == "a" and "result__a" in classes:
            self._current_href = attrs_dict.get("href")
            self._current_title_parts = []
            self._capture_title = True
            self._current_snippet_parts = []
            return
        if tag in {"a", "div"} and "result__snippet" in classes:
            self._capture_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_title:
            self._capture_title = False
            title = _normalize_ws("".join(self._current_title_parts))
            url = _decode_duckduckgo_redirect(self._current_href or "")
            snippet = _normalize_ws("".join(self._current_snippet_parts))
            if title and url:
                self.results.append(SearchResult(title=title, url=url, snippet=snippet))
            self._current_href = None
            self._current_title_parts = []
            self._current_snippet_parts = []
            return
        if tag in {"a", "div"} and self._capture_snippet:
            self._capture_snippet = False

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._current_title_parts.append(data)
        if self._capture_snippet:
            self._current_snippet_parts.append(data)


class _ReadableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._title_parts: List[str] = []
        self._in_title = False
        self._text_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4"}:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4"}:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        self._text_parts.append(data)

    def title(self) -> str:
        return _normalize_ws("".join(self._title_parts))

    def text(self) -> str:
        raw = html.unescape("".join(self._text_parts))
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


class _NoRedirectHandler:
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # pragma: no cover
        del req, fp, code, msg, headers, newurl
        return None

    http_error_301 = http_error_302 = http_error_303 = http_error_307 = http_error_308 = redirect_request


def _normalize_ws(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _decode_duckduckgo_redirect(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    if url.startswith("//"):
        return f"https:{url}"
    return url


def _is_safe_public_hostname(hostname: str) -> bool:
    normalized = (hostname or "").strip().lower()
    if not normalized or normalized in {"localhost", "localhost.localdomain"}:
        return False
    try:
        infos = socket.getaddrinfo(normalized, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def is_safe_public_http_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.username or parsed.password:
        return False
    return _is_safe_public_hostname(parsed.hostname or "")


def extract_public_http_urls(text: str) -> List[str]:
    urls: List[str] = []
    seen: set[str] = set()
    for match in URL_RE.finditer(text or ""):
        candidate = match.group(0).rstrip(").,!?]}'\"")
        if candidate in seen or not is_safe_public_http_url(candidate):
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def query_requires_web_context(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    if FORCE_WEB_PREFIX_RE.match(normalized):
        return True
    if extract_public_http_urls(normalized):
        return True
    return bool(WEB_TRIGGER_RE.search(normalized))


def _build_opener(*handlers):
    context = ssl.create_default_context()
    opener = build_opener(*handlers, HTTPSHandler(context=context))
    opener.addheaders = [("User-Agent", USER_AGENT)]
    return opener


def _urlopen_text(request: Request, *, timeout_seconds: int) -> tuple[str, str]:
    opener = _build_opener()
    with opener.open(request, timeout=timeout_seconds) as response:
        content_type = response.headers.get("Content-Type", "")
        charset_match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, re.IGNORECASE)
        charset = charset_match.group(1) if charset_match else "utf-8"
        body = response.read()
        return body.decode(charset, errors="replace"), content_type


def duckduckgo_search(query: str, *, max_results: int = DEFAULT_MAX_SEARCH_RESULTS, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> List[SearchResult]:
    if not query.strip():
        return []
    request = Request(DUCKDUCKGO_HTML_URL.format(query=quote_plus(query)))
    body, _content_type = _urlopen_text(request, timeout_seconds=timeout_seconds)
    parser = _SearchResultParser()
    parser.feed(body)
    results: List[SearchResult] = []
    seen: set[str] = set()
    for row in parser.results:
        if row.url in seen or not is_safe_public_http_url(row.url):
            continue
        seen.add(row.url)
        results.append(row)
        if len(results) >= max_results:
            break
    return results


def _open_without_redirects(url: str, *, timeout_seconds: int) -> tuple[int, dict[str, str], bytes]:
    opener = _build_opener(_NoRedirectHandler())
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def fetch_readable_page(
    url: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_chars: int = DEFAULT_MAX_PAGE_CHARS,
    max_redirects: int = 5,
) -> Optional[FetchedPage]:
    current_url = url
    for _ in range(max_redirects + 1):
        if not is_safe_public_http_url(current_url):
            return None
        status, headers, body = _open_without_redirects(current_url, timeout_seconds=timeout_seconds)
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("Location") or headers.get("location")
            if not location:
                return None
            current_url = urljoin(current_url, location)
            continue
        content_type = headers.get("Content-Type", headers.get("content-type", ""))
        if "text/html" in content_type.lower():
            charset_match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, re.IGNORECASE)
            charset = charset_match.group(1) if charset_match else "utf-8"
            parser = _ReadableTextParser()
            parser.feed(body.decode(charset, errors="replace"))
            text = parser.text()
            if not text:
                return None
            return FetchedPage(url=current_url, title=parser.title() or current_url, text=text[:max_chars].strip())
        if "text/" in content_type.lower() or "json" in content_type.lower():
            text = body.decode("utf-8", errors="replace").strip()
            if not text:
                return None
            return FetchedPage(url=current_url, title=current_url, text=text[:max_chars].strip())
        return None
    return None


def _research_query_text(raw_prompt_text: str, prompt_text: str) -> str:
    candidate = (raw_prompt_text or "").strip() or (prompt_text or "").strip()
    return FORCE_WEB_PREFIX_RE.sub("", candidate, count=1).strip()


def _web_context_enabled(config) -> bool:
    return bool(getattr(config, "pi_web_context_enabled", True))


def _max_search_results(config) -> int:
    return max(1, int(getattr(config, "pi_web_max_search_results", DEFAULT_MAX_SEARCH_RESULTS) or DEFAULT_MAX_SEARCH_RESULTS))


def _max_fetched_pages(config) -> int:
    return max(1, int(getattr(config, "pi_web_max_fetched_pages", DEFAULT_MAX_FETCHED_PAGES) or DEFAULT_MAX_FETCHED_PAGES))


def _max_page_chars(config) -> int:
    return max(500, int(getattr(config, "pi_web_max_page_chars", DEFAULT_MAX_PAGE_CHARS) or DEFAULT_MAX_PAGE_CHARS))


def _timeout_seconds(config) -> int:
    return max(5, int(getattr(config, "pi_web_timeout_seconds", DEFAULT_TIMEOUT_SECONDS) or DEFAULT_TIMEOUT_SECONDS))


def maybe_build_web_context(
    *,
    config,
    active_engine,
    prompt_text: str,
    raw_prompt_text: str,
    search_fn: Callable[..., List[SearchResult]] = duckduckgo_search,
    fetch_fn: Callable[..., Optional[FetchedPage]] = fetch_readable_page,
) -> Optional[WebContextResult]:
    if getattr(active_engine, "engine_name", "") != "pi":
        return None
    if not _web_context_enabled(config):
        return None
    query = _research_query_text(raw_prompt_text, prompt_text)
    if not query_requires_web_context(query):
        return None

    timeout_seconds = _timeout_seconds(config)
    max_page_chars = _max_page_chars(config)
    max_fetched_pages = _max_fetched_pages(config)
    fetched_pages: List[FetchedPage] = []
    search_results: List[SearchResult] = []
    direct_urls = extract_public_http_urls(query)

    if direct_urls:
        for url in direct_urls[:max_fetched_pages]:
            page = fetch_fn(url, timeout_seconds=timeout_seconds, max_chars=max_page_chars)
            if page is not None:
                fetched_pages.append(page)
    else:
        search_results = search_fn(query, max_results=_max_search_results(config), timeout_seconds=timeout_seconds)
        for row in search_results[:max_fetched_pages]:
            page = fetch_fn(row.url, timeout_seconds=timeout_seconds, max_chars=max_page_chars)
            if page is not None:
                fetched_pages.append(page)

    if not search_results and not fetched_pages:
        return None

    generated_at = datetime.now(timezone.utc).isoformat()
    lines = [
        "Live web context:",
        "- Use this context for facts that may have changed recently.",
        "- Prefer these fetched sources over stale model memory for current events, news, and linked pages.",
        "- If the sources are incomplete or conflict, say so plainly.",
        f"- Retrieved at: {generated_at}",
        f"- Research query: {query}",
    ]
    if search_results:
        lines.append("")
        lines.append("Search results:")
        for index, row in enumerate(search_results, start=1):
            lines.append(f"{index}. {row.title} — {row.url}")
            lines.append(f"   Snippet: {row.snippet or '(no snippet)'}")
    if fetched_pages:
        lines.append("")
        lines.append("Fetched source excerpts:")
        for index, page in enumerate(fetched_pages, start=1):
            lines.append(f"Source {index}: {page.title}")
            lines.append(f"URL: {page.url}")
            lines.append(page.text)
            lines.append("")
    return WebContextResult(
        query=query,
        context_text="\n".join(lines).strip(),
        search_results=search_results,
        fetched_pages=fetched_pages,
    )
