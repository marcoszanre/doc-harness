import unittest
from threading import Event
from types import SimpleNamespace

from doc_harness.foundry import DEPLOYMENT, Foundry


class Delta:
    def __init__(self, **fields):
        self.fields = fields

    def model_dump(self, exclude_none=False):
        return self.fields


class Stream:
    def __init__(self, chunks):
        self.chunks = chunks

    def __enter__(self):
        return iter(self.chunks)

    def __exit__(self, *_):
        pass


class FakeClient:
    def __init__(self, chunks):
        self.chunks = chunks
        self.request = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.request = kwargs
        return Stream(self.chunks)


def chunk(delta=None, finish_reason=None, usage=None):
    choices = [SimpleNamespace(delta=Delta(**delta), finish_reason=finish_reason)] if delta is not None else []
    return SimpleNamespace(choices=choices, usage=SimpleNamespace(**usage) if usage else None)


class FoundryTests(unittest.TestCase):
    def test_streams_reasoning_and_final_answer_without_tools(self):
        client = FakeClient([
            chunk({"reasoning_content": "Considering "}),
            chunk({"reasoning_content": "sources."}),
            chunk({"content": "Weekly reading"}, "stop"),
            chunk(usage={"prompt_tokens": 111, "completion_tokens": 37}),
        ])
        seen = []
        result = Foundry(client).complete([{"role": "user", "content": "read"}], lambda *args: seen.append(args), Event())
        self.assertEqual(client.request["model"], DEPLOYMENT)
        self.assertTrue(client.request["stream"])
        self.assertEqual(client.request["stream_options"], {"include_usage": True})
        self.assertNotIn("tools", client.request)
        self.assertEqual(result.content, "Weekly reading")
        self.assertEqual((result.input_tokens, result.output_tokens), (111, 37))
        self.assertIn(("reasoning", "sources."), seen)

    def test_usage_callback_sees_each_completed_request(self):
        client = FakeClient([
            chunk({"content": "OK"}, "stop"),
            chunk(usage={"prompt_tokens": 9, "completion_tokens": 2}),
        ])
        model = Foundry(client)
        reported = []
        model.on_usage = reported.append
        model.complete([{"role": "user", "content": "OK"}], lambda *_: None, Event())
        self.assertEqual((reported[0].input_tokens, reported[0].output_tokens), (9, 2))

    def test_interrupted_stream_reports_unavailable_usage(self):
        model = Foundry(FakeClient([chunk({"content": "partial"})]))
        reported = []
        model.on_usage = reported.append
        cancel = Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            model.complete([{"role": "user", "content": "test"}], lambda *_: None, cancel)
        self.assertEqual(len(reported), 1)
        self.assertIsNone(reported[0].input_tokens)
        self.assertIsNone(reported[0].output_tokens)

    def test_filters_truncated_output(self):
        client = FakeClient([chunk({"content": "partial"}, "length")])
        with self.assertRaisesRegex(ValueError, "output limit"):
            Foundry(client).complete([{"role": "user", "content": "test"}], lambda *_: None, Event())
