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


def chunk(delta=None, finish_reason=None):
    choices = [SimpleNamespace(delta=Delta(**delta), finish_reason=finish_reason)] if delta is not None else []
    return SimpleNamespace(choices=choices)


class FoundryTests(unittest.TestCase):
    def test_streams_reasoning_and_final_answer_without_tools(self):
        client = FakeClient([
            chunk({"reasoning_content": "Considering "}),
            chunk({"reasoning_content": "sources."}),
            chunk({"content": "Weekly reading"}, "stop"),
        ])
        seen = []
        result = Foundry(client).complete([{"role": "user", "content": "read"}], lambda *args: seen.append(args), Event())
        self.assertEqual(client.request["model"], DEPLOYMENT)
        self.assertTrue(client.request["stream"])
        self.assertNotIn("tools", client.request)
        self.assertEqual(result.content, "Weekly reading")
        self.assertIn(("reasoning", "sources."), seen)

    def test_filters_truncated_output(self):
        client = FakeClient([chunk({"content": "partial"}, "length")])
        with self.assertRaisesRegex(ValueError, "output limit"):
            Foundry(client).complete([{"role": "user", "content": "test"}], lambda *_: None, Event())
