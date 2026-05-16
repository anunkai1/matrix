import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

import telegram_bridge.engine_control_commands as engine_control_commands
import telegram_bridge.engine_control_actions as engine_control_actions
import telegram_bridge.engine_control_mutations as engine_control_mutations
from telegram_bridge.handler_models import CallbackActionResult
from telegram_bridge.state_store import State, StateRepository


class TestEngineControlMutations(unittest.TestCase):
    def test_set_engine_for_scope_rejects_missing_venice_key(self):
        state = State()
        config = make_config(venice_api_key="")

        text = engine_control_mutations.set_engine_for_scope(
            state,
            config,
            "tg:1",
            "venice",
            display_engine_name=lambda value: value,
            normalize_engine_name=lambda value: value,
            selectable_engine_plugins=lambda _config: ["codex", "venice"],
            set_chat_engine=lambda *_args: self.fail("set_chat_engine should not be called"),
        )

        self.assertIn("VENICE_API_KEY is missing", text)

    def test_set_engine_for_scope_rejects_unavailable_engine(self):
        state = State()
        config = make_config()

        text = engine_control_mutations.set_engine_for_scope(
            state,
            config,
            "tg:1",
            "pi",
            display_engine_name=lambda value: value,
            normalize_engine_name=lambda value: value,
            selectable_engine_plugins=lambda _config: ["codex"],
            set_chat_engine=lambda *_args: self.fail("set_chat_engine should not be called"),
        )

        self.assertIn("Unknown or unavailable engine: pi", text)

    def test_set_pi_provider_for_scope_preserves_state_when_no_models_reported(self):
        state = State(chat_pi_providers={"tg:1": "venice"}, chat_pi_models={"tg:1": "model-a"})
        repo = StateRepository(state)
        config = make_config()

        text = engine_control_mutations.set_pi_provider_for_scope(
            state,
            config,
            "tg:1",
            "deepseek",
            normalize_pi_provider_name=lambda value: value,
            pi_provider_model_names=lambda _config: [],
            get_chat_pi_model=repo.get_chat_pi_model,
            resolve_pi_model_candidate=lambda *_args: None,
            set_chat_pi_provider=repo.set_chat_pi_provider,
            set_chat_pi_model=repo.set_chat_pi_model,
        )

        self.assertIn("Pi provider was not changed", text)
        self.assertEqual(repo.get_chat_pi_provider("tg:1"), "venice")
        self.assertEqual(repo.get_chat_pi_model("tg:1"), "model-a")

    def test_set_pi_model_for_scope_reports_unavailable_model(self):
        state = State()
        config = make_config()

        text = engine_control_mutations.set_pi_model_for_scope(
            state,
            config,
            "tg:1",
            "missing-model",
            build_engine_runtime_config=lambda *_args: SimpleNamespace(pi_provider="venice", pi_model="model-a"),
            pi_provider_model_names=lambda _config: ["model-a"],
            resolve_pi_model_candidate=lambda *_args: None,
            configured_pi_provider=lambda runtime_config: runtime_config.pi_provider,
            set_chat_pi_model=lambda *_args: self.fail("set_chat_pi_model should not be called"),
            configured_pi_model=lambda runtime_config: runtime_config.pi_model,
            build_pi_model_source_text=lambda *_args: "global default",
        )

        self.assertIn("Model not available for Pi provider `venice`", text)

    def test_set_codex_effort_for_scope_reports_unsupported_effort(self):
        state = State()
        config = make_config()

        text = engine_control_mutations.set_codex_effort_for_scope(
            state,
            config,
            "tg:1",
            "extreme",
            build_engine_runtime_config=lambda *_args: SimpleNamespace(codex_model="gpt-5.4", codex_reasoning_effort="medium"),
            configured_codex_model=lambda runtime_config: runtime_config.codex_model,
            resolve_codex_effort_candidate=lambda *_args: None,
            set_chat_codex_effort=lambda *_args: self.fail("set_chat_codex_effort should not be called"),
            configured_codex_reasoning_effort=lambda runtime_config: runtime_config.codex_reasoning_effort,
            build_codex_effort_source_text=lambda *_args: "global default",
        )

        self.assertIn("Reasoning effort not supported for Codex model `gpt-5.4`", text)

    def test_resolve_engine_for_scope_reuses_matching_default_engine(self):
        state = State(chat_engines={"tg:1": "pi"})
        config = make_config()
        default_engine = SimpleNamespace(engine_name="pi")

        resolved = engine_control_mutations.resolve_engine_for_scope(
            state,
            config,
            "tg:1",
            default_engine,
            get_chat_engine=lambda runtime_state, scope_key: runtime_state.chat_engines.get(scope_key),
            normalize_engine_name=lambda value: value,
            build_default_plugin_registry=lambda: self.fail("registry should not be built"),
            configured_default_engine=lambda _config: "codex",
        )

        self.assertIs(resolved, default_engine)


class TestEngineControlCommands(unittest.TestCase):
    def test_handle_engine_command_routes_to_set_action(self):
        client = FakeTelegramClient()
        observed = {}

        def fake_build_action_result(_state, _config, _scope_key, action, engine_name=""):
            observed["action"] = action
            observed["engine_name"] = engine_name
            return CallbackActionResult(text="ok")

        handled = engine_control_commands.handle_engine_command(
            State(),
            make_config(),
            client,
            "tg:1",
            1,
            None,
            10,
            "/engine pi",
            normalize_engine_name=lambda value: value,
            build_engine_action_result=fake_build_action_result,
            send_control_result_fn=engine_control_commands.send_control_result,
        )

        self.assertTrue(handled)
        self.assertEqual(observed, {"action": "set", "engine_name": "pi"})
        self.assertEqual(client.messages[0][1], "ok")

    def test_handle_engine_command_normalizes_ollama_s4_alias(self):
        client = FakeTelegramClient()
        observed = {}

        def fake_build_action_result(_state, _config, _scope_key, action, engine_name=""):
            observed["action"] = action
            observed["engine_name"] = engine_name
            return CallbackActionResult(text="ok")

        handled = engine_control_commands.handle_engine_command(
            State(),
            make_config(),
            client,
            "tg:1",
            1,
            None,
            11,
            "/engine ollama(s4)",
            normalize_engine_name=lambda value: "gemma" if value == "ollama(s4)" else value,
            build_engine_action_result=fake_build_action_result,
            send_control_result_fn=engine_control_commands.send_control_result,
        )

        self.assertTrue(handled)
        self.assertEqual(observed, {"action": "set", "engine_name": "gemma"})
        self.assertEqual(client.messages[0][1], "ok")

    def test_handle_model_command_reports_pi_validation_error(self):
        client = FakeTelegramClient()

        def fake_build_model_action_result(_state, _config, _scope_key, action, *, engine_name="", value="", page_index=None):
            del page_index
            if action == "set" and engine_name == "pi" and value == "bad-model":
                raise RuntimeError("catalog down")
            return CallbackActionResult(text="ok")

        handled = engine_control_commands.handle_model_command(
            State(),
            make_config(),
            client,
            "tg:1",
            1,
            None,
            20,
            "/model bad-model",
            model_active_engine_name=lambda *_args: "pi",
            build_model_action_result=fake_build_model_action_result,
            build_model_list_text=lambda *_args: "list",
            brief_health_error=lambda exc: str(exc),
            send_control_result_fn=engine_control_commands.send_control_result,
        )

        self.assertTrue(handled)
        self.assertIn("Failed to validate Pi models", client.messages[0][1])
        self.assertIn("catalog down", client.messages[0][1])

    def test_handle_model_command_reports_gemma_validation_error(self):
        client = FakeTelegramClient()

        def fake_build_model_action_result(_state, _config, _scope_key, action, *, engine_name="", value="", page_index=None):
            del page_index
            if action == "set" and engine_name == "gemma" and value == "bad-model":
                raise RuntimeError("catalog down")
            return CallbackActionResult(text="ok")

        handled = engine_control_commands.handle_model_command(
            State(),
            make_config(),
            client,
            "tg:1",
            1,
            None,
            21,
            "/model bad-model",
            model_active_engine_name=lambda *_args: "gemma",
            build_model_action_result=fake_build_model_action_result,
            build_model_list_text=lambda *_args: "list",
            brief_health_error=lambda exc: str(exc),
            send_control_result_fn=engine_control_commands.send_control_result,
        )

        self.assertTrue(handled)
        self.assertIn("Failed to validate Ollama (S4) models", client.messages[0][1])
        self.assertIn("catalog down", client.messages[0][1])

    def test_handle_effort_command_falls_back_to_status_for_non_codex_engine(self):
        client = FakeTelegramClient()
        observed = {}

        def fake_build_effort_action_result(_state, _config, _scope_key, action, value=""):
            observed["action"] = action
            observed["value"] = value
            return CallbackActionResult(text="status")

        handled = engine_control_commands.handle_effort_command(
            State(),
            make_config(),
            client,
            "tg:1",
            1,
            None,
            30,
            "/effort high",
            model_active_engine_name=lambda *_args: "pi",
            build_effort_action_result=fake_build_effort_action_result,
            build_effort_list_text=lambda *_args: "list",
            send_control_result_fn=engine_control_commands.send_control_result,
        )

        self.assertTrue(handled)
        self.assertEqual(observed, {"action": "status", "value": ""})
        self.assertEqual(client.messages[0][1], "status")

    def test_handle_pi_command_reports_unknown_command(self):
        client = FakeTelegramClient()

        handled = engine_control_commands.handle_pi_command(
            State(),
            make_config(),
            client,
            "tg:1",
            1,
            None,
            40,
            "/pi nope",
            build_engine_runtime_config=lambda *_args: SimpleNamespace(pi_provider="venice", pi_model="model-a"),
            build_pi_status_text=lambda *_args: "status",
            build_pi_provider_action_result=lambda *_args, **_kwargs: CallbackActionResult(text="providers"),
            build_pi_models_text=lambda *_args: "models",
            brief_health_error=lambda exc: str(exc),
            clear_chat_pi_provider=lambda *_args: False,
            clear_chat_pi_model=lambda *_args: False,
            configured_pi_provider=lambda runtime_config: runtime_config.pi_provider,
            build_pi_provider_source_text=lambda *_args: "global default",
            configured_pi_model=lambda runtime_config: runtime_config.pi_model,
            build_pi_model_source_text=lambda *_args: "global default",
            pi_provider_model_names=lambda *_args: ["model-a"],
            resolve_pi_model_candidate=lambda *_args: "model-a",
            set_chat_pi_model=lambda *_args: None,
            send_control_result_fn=engine_control_commands.send_control_result,
        )

        self.assertTrue(handled)
        self.assertIn("Unknown /pi command", client.messages[0][1])


class TestEngineControlActions(unittest.TestCase):
    def test_build_engine_action_result_uses_reset_branch_and_picker(self):
        result = engine_control_actions.build_engine_action_result(
            State(),
            make_config(),
            "tg:1",
            "reset",
            reset_engine_for_scope=lambda *_args: "reset-ok",
            set_engine_for_scope=lambda *_args: self.fail("set branch should not run"),
            build_engine_status_text=lambda *_args: self.fail("status branch should not run"),
            build_engine_picker_markup=lambda *_args: {"inline_keyboard": [[{"text": "x"}]]},
        )

        self.assertEqual(result.text, "reset-ok")
        self.assertIsInstance(result.reply_markup, dict)

    def test_build_pi_provider_action_result_uses_menu_branch(self):
        result = engine_control_actions.build_pi_provider_action_result(
            State(),
            make_config(),
            "tg:1",
            "menu",
            set_pi_provider_for_scope=lambda *_args: self.fail("set branch should not run"),
            build_engine_picker_markup=lambda *_args: self.fail("engine picker should not run"),
            build_pi_providers_text=lambda *_args: "providers",
            build_provider_picker_markup=lambda *_args: {"inline_keyboard": [[{"text": "provider"}]]},
        )

        self.assertEqual(result.text, "providers")
        self.assertEqual(result.reply_markup["inline_keyboard"][0][0]["text"], "provider")

    def test_build_model_action_result_uses_status_for_unknown_engine(self):
        result = engine_control_actions.build_model_action_result(
            State(),
            make_config(),
            "tg:1",
            "set",
            value="anything",
            page_index=2,
            model_active_engine_name=lambda *_args: "venice",
            reset_model_for_scope=lambda *_args: self.fail("reset branch should not run"),
            set_codex_model_for_scope=lambda *_args: self.fail("codex branch should not run"),
            set_gemma_model_for_scope=lambda *_args: self.fail("gemma branch should not run"),
            set_pi_model_for_scope=lambda *_args: self.fail("pi branch should not run"),
            build_model_status_text=lambda *_args: "status-text",
            build_model_picker_markup=lambda *_args, **kwargs: {"page": kwargs["page_index"]},
        )

        self.assertEqual(result.text, "status-text")
        self.assertEqual(result.reply_markup, {"page": 2})

    def test_build_provider_picker_markup_falls_back_to_static_choices(self):
        result = engine_control_actions.build_provider_picker_markup(
            State(),
            make_config(),
            "tg:1",
            view_builder=lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")),
            build_engine_runtime_config=lambda *_args: SimpleNamespace(pi_provider="deepseek"),
            configured_pi_provider=lambda runtime_config: runtime_config.pi_provider,
            provider_choices=[("venice", "Venice"), ("deepseek", "DeepSeek")],
            provider_callback_data=lambda action, value: f"{action}:{value}",
            compact_inline_keyboard=lambda buttons, columns=2: {
                "inline_keyboard": [[{"text": label, "callback_data": data} for label, data in buttons[:columns]]]
            },
            engine_callback_data=lambda engine_name, action: f"{engine_name}:{action}",
        )

        self.assertIsInstance(result, dict)
        callback_values = [button["callback_data"] for row in result["inline_keyboard"] for button in row]
        self.assertIn("set:venice", callback_values)
        self.assertIn("set:deepseek", callback_values)
        self.assertIn("pi:menu", callback_values)

    def test_build_model_picker_markup_returns_none_on_view_failure(self):
        result = engine_control_actions.build_model_picker_markup(
            State(),
            make_config(),
            "tg:1",
            page_index=0,
            view_builder=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
