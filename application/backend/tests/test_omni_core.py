import base64
import io
import json
import unittest
import wave

from app.omni_core import OmniError, parse_reply, read_stream, validate_audio


class OmniCoreTests(unittest.TestCase):
    def test_only_catalog_movements_are_accepted(self):
        reply = {"heard": "play that", "scene": "keyboard", "reply": "Ready", "movement": "tune"}
        self.assertEqual(parse_reply(json.dumps(reply), {"tune"})["movement"], "tune")
        with self.assertRaises(OmniError):
            parse_reply(json.dumps(reply), {"other"})

    def test_malformed_or_injected_commands_are_rejected(self):
        for value in ('[]', '{"reply": "ok"}', '{"heard":"", "scene":"", "reply":"ok", "movement":[0,1]}'):
            with self.assertRaises(OmniError):
                parse_reply(value, {"tune"})

    def test_fenced_json_and_observation_without_motion(self):
        value = '{"heard":"hello", "scene":"desk", "reply":"Hello", "movement":null}'
        self.assertIsNone(parse_reply('```json\n' + value + '\n```', set())["movement"])

    def test_stream_ignores_reasoning_and_usage(self):
        chunks = [{"choices": [{"delta": {"reasoning_content": "private"}}]},
                  {"choices": [{"delta": {"content": "hello"}}]}, {"choices": []}]
        lines = [b"data: " + json.dumps(c).encode() for c in chunks] + [b"data: [DONE]"]
        self.assertEqual(read_stream(lines), "hello")

    def test_provider_errors_are_not_silently_empty(self):
        with self.assertRaises(OmniError):
            read_stream([b'data: {"error":{"message":"bad request"}}'])

    def test_wav_audio_validation(self):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b'\x00\x00' * 1600)
        encoded = base64.b64encode(buffer.getvalue()).decode()
        self.assertEqual(validate_audio(encoded), encoded)
        for value in ('not base64!', base64.b64encode(b'not audio').decode()):
            with self.assertRaises(OmniError):
                validate_audio(value)


if __name__ == "__main__":
    unittest.main()
