"""VLM 세션 회귀 테스트. SDK를 import하지만 NPU는 열지 않습니다."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from hailo_platform import FormatOrder

from piwankanobi.vlm import VLMSession


class FakeVLM:
    """장치 컨텍스트와 이미지 수 검증을 재현하는 SDK 대역."""

    def __init__(self):
        self.context_usage = 0
        self.requests = []
        self.format_order = FormatOrder.NHWC
        self.frame_shape = (2, 4, 3)
        self.frame_dtype = np.uint8
        self.stream_chunks = ["first", " second"]
        self.chunks_consumed = 0
        self.stream_completed = False

    def get_context_usage_size(self):
        return self.context_usage

    def clear_context(self):
        self.context_usage = 0

    def input_frame_shape(self):
        return self.frame_shape

    def input_frame_format_type(self):
        return self.frame_dtype

    def input_frame_format_order(self):
        return self.format_order

    def _accept(self, prompt, frames):
        if self.context_usage and any(m["role"] == "system" for m in prompt):
            raise RuntimeError("System messages require a fresh context")
        images = sum(
            item["type"] == "image"
            for message in prompt
            for item in message["content"]
        )
        if images != len(frames):
            raise RuntimeError("Image placeholders must match supplied frames")
        self.requests.append((deepcopy(prompt), list(frames)))
        self.context_usage += 10

    def generate_all(self, prompt, frames, **kwargs):
        self._accept(prompt, frames)
        return "answer<|im_end|>"

    @contextmanager
    def generate(self, prompt, frames, **kwargs):
        self._accept(prompt, frames)

        def chunks():
            for chunk in self.stream_chunks:
                self.chunks_consumed += 1
                yield chunk
            self.stream_completed = True

        yield chunks()


class SessionContextTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeVLM()
        self.session = VLMSession(self.backend)

    def test_image_then_text_sends_only_new_message(self):
        image = np.zeros((2, 4, 3), dtype=np.uint8)
        with patch.object(self.session, "preprocess_image", return_value=image):
            self.assertEqual(self.session.ask("Describe", "picture.png"), "answer")
        self.session.ask("What color was it?")

        first_prompt, first_frames = self.backend.requests[0]
        self.assertEqual([m["role"] for m in first_prompt], ["system", "user"])
        self.assertEqual(len(first_frames), 1)
        second_prompt, second_frames = self.backend.requests[1]
        self.assertEqual(second_prompt, [{
            "role": "user",
            "content": [{"type": "text", "text": "What color was it?"}],
        }])
        self.assertEqual(second_frames, [])

    def test_ask_and_stream_share_backend_context(self):
        self.session.ask("First question")
        self.assertEqual("".join(self.session.stream("Follow up")), "first second")
        self.session.ask("One more")
        self.assertEqual(
            [[m["role"] for m in prompt] for prompt, _ in self.backend.requests],
            [["system", "user"], ["user"], ["user"]],
        )

    def test_interrupted_stream_keeps_backend_context(self):
        stream = self.session.stream("Start")
        self.assertEqual(next(stream), "first")
        stream.close()
        self.session.ask("Continue")
        self.assertEqual([m["role"] for m in self.backend.requests[-1][0]], ["user"])

    def test_reset_starts_fresh_context(self):
        self.session.ask("First conversation")
        self.session.reset()
        self.assertEqual(self.backend.context_usage, 0)
        self.session.ask("New conversation")
        self.assertEqual(
            [m["role"] for m in self.backend.requests[-1][0]], ["system", "user"],
        )

    def test_reset_failure_is_propagated(self):
        self.session.ask("Keep this context")
        with patch.object(self.backend, "clear_context", side_effect=RuntimeError("device failed")):
            with self.assertRaisesRegex(RuntimeError, "device failed"):
                self.session.reset()
        self.session.ask("Still the same conversation")
        self.assertEqual([m["role"] for m in self.backend.requests[-1][0]], ["user"])

    def test_external_context_clear_is_detected(self):
        self.session.ask("First")
        self.backend.clear_context()
        self.session.ask("After backend reset")
        self.assertEqual(
            [m["role"] for m in self.backend.requests[-1][0]], ["system", "user"],
        )


class ImagePreprocessingTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeVLM()
        self.session = VLMSession(self.backend)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "image.png"
        self.bgr = np.zeros((2, 4, 3), dtype=np.uint8)
        self.bgr[:] = (10, 20, 30)
        self.assertTrue(cv2.imwrite(str(self.path), self.bgr))

    def test_nhwc_preserves_rgb_shape_dtype_and_contiguous_bytes(self):
        self.backend.frame_dtype = np.float32
        image = self.session.preprocess_image(self.path)
        self.assertEqual(image.shape, (2, 4, 3))
        self.assertEqual(image.dtype, np.dtype(np.float32))
        self.assertTrue(image.flags.c_contiguous)
        np.testing.assert_array_equal(image[0, 0], [30, 20, 10])

    def test_rgb888_uses_the_same_rgb_packing(self):
        self.backend.format_order = FormatOrder.RGB888
        image = self.session.preprocess_image(self.path)
        np.testing.assert_array_equal(image, self.bgr[:, :, ::-1])

    def test_unsupported_layout_is_rejected(self):
        self.backend.format_order = FormatOrder.NCHW
        with self.assertRaisesRegex(ValueError, "지원하지 않는 모델 입력 형식"):
            self.session.preprocess_image(self.path)

    def test_unsupported_channel_count_is_rejected(self):
        self.backend.frame_shape = (2, 4, 1)
        with self.assertRaisesRegex(ValueError, "모델 채널 수=1"):
            self.session.preprocess_image(self.path)


class StreamCleanupTests(unittest.TestCase):
    def test_end_markers_split_at_every_boundary(self):
        for marker in ("<|im_end|>", ". [{'type'", "<|endoftext|>"):
            for split in range(1, len(marker)):
                with self.subTest(marker=marker, split=split):
                    backend = FakeVLM()
                    backend.stream_chunks = ["answer " + marker[:split], marker[split:], "ignored"]
                    answer = "".join(VLMSession(backend).stream("Question"))
                    self.assertEqual(answer, "answer ")
                    self.assertEqual(backend.chunks_consumed, 3)
                    self.assertTrue(backend.stream_completed)

    def test_marker_split_into_single_characters(self):
        backend = FakeVLM()
        backend.stream_chunks = ["answer"] + list("<|im_end|>") + ["ignored"]
        self.assertEqual("".join(VLMSession(backend).stream("Question")), "answer")
        self.assertTrue(backend.stream_completed)

    def test_ordinary_text_and_unmatched_prefixes_are_preserved(self):
        backend = FakeVLM()
        backend.stream_chunks = ["  Hello. <|im_", "example>\n", "Ending . [{'ty"]
        self.assertEqual(
            "".join(VLMSession(backend).stream("Question")),
            "  Hello. <|im_example>\nEnding . [{'ty",
        )

    def test_normal_text_is_yielded_before_reading_more_chunks(self):
        backend = FakeVLM()
        backend.stream_chunks = ["Hello", " later", "<|im_end|>"]
        stream = VLMSession(backend).stream("Question")
        self.assertEqual(next(stream), "Hello")
        self.assertEqual(backend.chunks_consumed, 1)
        self.assertEqual("".join(stream), " later")
        self.assertTrue(backend.stream_completed)

    def test_empty_stream_and_empty_chunks(self):
        for chunks in ([], ["", ""], ["<|im_end|>", "ignored"]):
            with self.subTest(chunks=chunks):
                backend = FakeVLM()
                backend.stream_chunks = chunks
                self.assertEqual(list(VLMSession(backend).stream("Question")), [])
                self.assertTrue(backend.stream_completed)


if __name__ == "__main__":
    unittest.main()
