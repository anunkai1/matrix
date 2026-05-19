import unittest
from types import SimpleNamespace

from telegram_bridge import web_context


class _PiEngine:
    engine_name = "pi"


class _CodexEngine:
    engine_name = "codex"


class WebContextTests(unittest.TestCase):
    def test_query_requires_web_context_for_latest_news(self):
        self.assertTrue(web_context.query_requires_web_context("latest AI news today"))

    def test_query_requires_web_context_for_public_url(self):
        self.assertTrue(web_context.query_requires_web_context("summarize https://example.com/page"))

    def test_query_requires_web_context_false_for_plain_prompt(self):
        self.assertFalse(web_context.query_requires_web_context("refactor this function"))

    def test_blocks_private_and_local_urls(self):
        self.assertFalse(web_context.is_safe_public_http_url("http://127.0.0.1/test"))
        self.assertFalse(web_context.is_safe_public_http_url("http://localhost/test"))

    def test_maybe_build_web_context_searches_and_fetches_for_pi(self):
        config = SimpleNamespace(
            pi_web_context_enabled=True,
            pi_web_max_search_results=3,
            pi_web_max_fetched_pages=2,
            pi_web_max_page_chars=500,
            pi_web_timeout_seconds=5,
        )

        def fake_search(query, *, max_results, timeout_seconds):
            self.assertEqual(query, "latest server3 news")
            self.assertEqual(max_results, 3)
            self.assertEqual(timeout_seconds, 5)
            return [
                web_context.SearchResult(
                    title="Server3 update",
                    url="https://example.com/server3",
                    snippet="A fresh update.",
                )
            ]

        def fake_fetch(url, *, timeout_seconds, max_chars):
            self.assertEqual(url, "https://example.com/server3")
            self.assertEqual(timeout_seconds, 5)
            self.assertEqual(max_chars, 500)
            return web_context.FetchedPage(
                url=url,
                title="Server3 update",
                text="Server3 is healthy today.",
            )

        result = web_context.maybe_build_web_context(
            config=config,
            active_engine=_PiEngine(),
            prompt_text="latest server3 news",
            raw_prompt_text="latest server3 news",
            search_fn=fake_search,
            fetch_fn=fake_fetch,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result.search_results), 1)
        self.assertEqual(len(result.fetched_pages), 1)
        self.assertIn("Server3 is healthy today.", result.context_text)

    def test_maybe_build_web_context_fetches_direct_url_without_search(self):
        config = SimpleNamespace(
            pi_web_context_enabled=True,
            pi_web_max_search_results=3,
            pi_web_max_fetched_pages=2,
            pi_web_max_page_chars=500,
            pi_web_timeout_seconds=5,
        )

        def fake_search(query, *, max_results, timeout_seconds):
            raise AssertionError("search should not run for direct URL prompts")

        def fake_fetch(url, *, timeout_seconds, max_chars):
            return web_context.FetchedPage(
                url=url,
                title="Example page",
                text="Fetched directly from the provided URL.",
            )

        result = web_context.maybe_build_web_context(
            config=config,
            active_engine=_PiEngine(),
            prompt_text="summarize https://example.com/report",
            raw_prompt_text="summarize https://example.com/report",
            search_fn=fake_search,
            fetch_fn=fake_fetch,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.search_results, [])
        self.assertEqual(len(result.fetched_pages), 1)
        self.assertIn("Fetched directly from the provided URL.", result.context_text)

    def test_maybe_build_web_context_skips_non_pi_engines(self):
        result = web_context.maybe_build_web_context(
            config=SimpleNamespace(pi_web_context_enabled=True),
            active_engine=_CodexEngine(),
            prompt_text="latest server3 news",
            raw_prompt_text="latest server3 news",
            search_fn=lambda *args, **kwargs: [],
            fetch_fn=lambda *args, **kwargs: None,
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
