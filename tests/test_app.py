import unittest
import json
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from app.agent import _answer_chunk_text, _answer_text, ask_agent, stream_agent
from app.catalog import TrialCatalog
from app.main import app
from scripts.generate_demo_data import build_demo_data


DATA_DIR = Path(__file__).resolve().parents[1] / "sample-data"


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = TrialCatalog(DATA_DIR)

    def test_import_and_normalization(self):
        self.assertEqual(len(self.catalog.trials), 6)
        self.assertEqual(len(self.catalog.trials["T01"]["observations"]), 2)
        self.assertEqual(self.catalog.trials["T02"]["treated_yield_t_ha"], 7.8)
        self.assertEqual(self.catalog.trials["T02"]["country"], "Germany")
        self.assertEqual(self.catalog.trials["T04"]["crop"], "Potato")
        self.assertEqual(self.catalog.trials["T06"]["country"], "Spain")

    def test_conflict_and_missing_value_remain_visible(self):
        self.assertEqual(self.catalog.trials["T03"]["status"], "conflicting")
        self.assertIsNone(self.catalog.trials["T03"]["increase_pct"])
        self.assertEqual(
            {observation["treated_yield_t_ha"] for observation in self.catalog.trials["T03"]["observations"]},
            {42.0, 44.0},
        )
        self.assertEqual(self.catalog.trials["T05"]["status"], "incomplete")
        self.assertEqual(self.catalog.trials["T05"]["treated_yield_t_ha"], 8.1)
        self.assertIsNone(self.catalog.trials["T05"]["control_yield_t_ha"])
        self.assertIsNone(self.catalog.trials["T05"]["increase_pct"])

    def test_alias_search_and_empty_evidence(self):
        self.assertEqual(
            [trial["trial_id"] for trial in self.catalog.search(crop="wheat", product="HARVESTPLUS", country="DE")],
            ["T02", "T05"],
        )
        self.assertEqual(self.catalog.search(crop="rice", product="Harvest Plus"), [])
        self.assertEqual([trial["trial_id"] for trial in self.catalog.search(trial_id="t03")], ["T03"])


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_search_compare_and_sources(self):
        with patch("app.main.catalog", TrialCatalog(DATA_DIR)):
            response = self.client.get("/api/trials", params={"crop": "Wheat", "trial_type": "Scientific", "year_from": 2021, "year_to": 2025})
            self.assertEqual(response.status_code, 200)
            self.assertEqual([trial["trial_id"] for trial in response.json()["trials"]], ["T01", "T06"])
            comparison = self.client.post("/api/compare", json={"trial_ids": ["T01", "T02"]})
            self.assertEqual(comparison.status_code, 200)
            self.assertEqual(len(comparison.json()["trials"]), 2)
            self.assertIn("Trial T03 summary", self.client.get("/api/sources/T03_summary.txt").text)
            self.assertEqual(self.client.get("/api/sources/../README.md").status_code, 404)

    def test_agent_stream_emits_sse_frames(self):
        events = iter([{"type": "status", "status": "running", "message": "Looking"},
                       {"type": "final", "status": "completed", "answer": "Done", "tools_used": 1, "sources": []}])
        with patch("app.main.stream_agent", return_value=events):
            response = self.client.post("/api/agent/stream", json={"question": "Find wheat trials"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertIn('"type": "status"', response.text)
        self.assertIn('"type": "final"', response.text)


class ScriptedModel:
    """Exercise the real graph and tools without a paid model call."""

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if not results:
            name, args = "search_trials", {"crop": "Wheat", "product": "Harvest Plus"}
        elif len(results) == 1:
            name, args = "get_trial", {"trial_id": "T01"}
        elif len(results) == 2:
            name, args = "read_source", {"source_name": "trials_a.csv"}
        else:
            return AIMessage(content=[{"type": "text", "text": "**T01** shows a 5% descriptive yield increase (`trials_a.csv`).", "extras": {"signature": "private"}}])
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{len(results)}"}])


class GeneratedDataScriptedModel:
    """Follow a generated trial through search, inspection, and source reading."""

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        results = [message for message in messages if isinstance(message, ToolMessage)]
        actions = [
            ("search_trials", {"crop": "Potato", "product": "Root Boost"}),
            ("get_trial", {"trial_id": "T22"}),
            ("read_source", {"source_name": "T22_synthetic_report.txt"}),
        ]
        if len(results) == len(actions):
            return AIMessage(content="T22 has conflicting synthetic source values; no single effect can be reported.")
        name, args = actions[len(results)]
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"generated-{len(results)}"}])


class StreamingScriptedModel(BaseChatModel):
    """A real streaming chat model interface with one evidence lookup."""

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "streaming-scripted-model"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        chunks = [part.message for part in self._stream(messages, stop, run_manager, **kwargs)]
        message = chunks[0]
        for chunk in chunks[1:]:
            message += chunk
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content=message.content, tool_calls=message.tool_calls,
        ))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        if not any(isinstance(message, ToolMessage) for message in messages):
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="", tool_call_chunks=[{"name": "search_trials",
                                               "args": json.dumps({"crop": "Wheat"}),
                                               "id": "search-1", "index": 0}],
            ))
        else:
            for token in ["T01 ", "shows ", "a 5% yield difference."]:
                yield ChatGenerationChunk(message=AIMessageChunk(content=token))


class RepeatingSearchModel:
    """Keep requesting tools until the graph's evidence budget forces a summary."""

    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        parent = self

        class ToolBinding:
            def invoke(self, messages):
                parent.calls += 1
                return AIMessage(content="", tool_calls=[{
                    "name": "search_trials", "args": {"trial_id": "T01"},
                    "id": f"repeat-{parent.calls}",
                }])

        return ToolBinding()

    def invoke(self, messages):
        return AIMessage(content="T01 has a descriptive yield difference in this fictional catalog.")


class AgentTests(unittest.TestCase):
    def test_missing_replication_is_not_misreported(self):
        self.assertEqual(_answer_text("an unreplicated demonstration trial"),
                         "a demonstration trial with replication not documented")
        self.assertEqual(_answer_chunk_text([
            {"type": "thinking", "text": "private analysis"},
            {"type": "text", "text": "Visible answer", "extras": {"signature": "private"}},
        ]), "Visible answer")

    def test_graph_uses_results_for_subsequent_actions(self):
        run = ask_agent(TrialCatalog(DATA_DIR), "What happened in T01?", model=ScriptedModel())
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["tools_used"], 3)
        self.assertEqual([step["tool"] for step in run["steps"] if step["kind"] == "tool_call"],
                         ["search_trials", "get_trial", "read_source"])
        self.assertIn("T01", run["answer"])
        self.assertNotIn("signature", run["answer"])
        self.assertNotIn("**", run["answer"])
        self.assertNotIn("`", run["answer"])
        self.assertEqual(run["sources"], ["trials_a.csv", "trials_b.csv"])

    def test_stream_exposes_decisions_and_intermediate_results(self):
        events = list(stream_agent(TrialCatalog(DATA_DIR), "What happened in T01?", model=ScriptedModel()))
        self.assertEqual(events[0]["type"], "status")
        self.assertEqual(events[-1]["status"], "completed")
        calls = [event for event in events if event["type"] == "tool_call"]
        results = [event for event in events if event["type"] == "tool_result"]
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(results), 3)
        self.assertIn("relevant trials", calls[0]["decision"])
        self.assertIn("Found", results[0]["summary"])
        self.assertIn('"trial_id": "T01"', results[1]["content"])

    def test_streams_answer_chunks_before_final(self):
        events = list(stream_agent(TrialCatalog(DATA_DIR), "Find wheat trials", model=StreamingScriptedModel()))
        self.assertEqual(events[-1]["status"], "completed")
        tokens = [event["text"] for event in events if event["type"] == "answer_token"]
        self.assertEqual(tokens, ["T01 ", "shows ", "a 5% yield difference."])
        self.assertLess(next(i for i, event in enumerate(events) if event["type"] == "answer_token"),
                        len(events) - 1)

    def test_repeated_tool_requests_finish_at_evidence_budget(self):
        model = RepeatingSearchModel()
        with patch("app.agent.MAX_TOOL_ROUNDS", 3):
            events = list(stream_agent(TrialCatalog(DATA_DIR), "What happened in T01?", model=model))
        self.assertEqual(model.calls, 3)
        self.assertEqual(events[-1]["status"], "completed")
        self.assertEqual(events[-1]["tools_used"], 3)
        self.assertIn("T01", events[-1]["answer"])
        self.assertNotIn("Recursion limit", events[-1]["answer"])


class GeneratedDataTests(unittest.TestCase):
    def test_generated_files_load_through_catalog_api_and_agent(self):
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            manifest = build_demo_data(output_dir)
            catalog = TrialCatalog(output_dir)
            self.assertEqual(manifest["total_trials"], 54)
            self.assertEqual(len(catalog.trials), 54)
            self.assertEqual(catalog.trials["T10"]["status"], "consistent")
            self.assertEqual(len(catalog.trials["T10"]["observations"]), 2)
            self.assertEqual(catalog.trials["T13"]["status"], "incomplete")
            self.assertIsNotNone(catalog.trials["T13"]["treated_yield_t_ha"])
            self.assertEqual(catalog.trials["T22"]["status"], "conflicting")
            self.assertIsNone(catalog.trials["T22"]["treated_yield_t_ha"])
            self.assertEqual(catalog.trials["T22"]["control_yield_t_ha"], 42.83)
            self.assertIsNone(catalog.trials["T22"]["increase_pct"])
            self.assertIn("fictional", catalog.source_text("T22_synthetic_report.txt"))

            with patch("app.main.catalog", catalog):
                client = TestClient(app)
                self.assertEqual(client.get("/api/health").json()["trial_count"], 54)
                self.assertGreater(client.get("/api/trials", params={"crop": "Potato"}).json()["count"], 10)
                self.assertEqual([trial["trial_id"] for trial in client.get("/api/trials", params={"trial_id": "t22"}).json()["trials"]], ["T22"])
                comparison = client.post("/api/compare", json={"trial_ids": ["T10", "T22"]}).json()
                self.assertEqual([trial["status"] for trial in comparison["trials"]], ["consistent", "conflicting"])
                self.assertIn("fictional", client.get("/api/sources/T22_synthetic_report.txt").text)

            run = ask_agent(catalog, "What happened in T22?", model=GeneratedDataScriptedModel())
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["tools_used"], 3)
            self.assertIn("T22_synthetic_report.txt", run["sources"])
            self.assertIn("conflicting", run["answer"])


if __name__ == "__main__":
    unittest.main()
