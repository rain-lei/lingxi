"""Isolated UI test server. No local settings, production DB or cloud credentials."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import wave
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from providers.stepfun import StepFunClient
from server import DemoEngine, LingXiHandler, LingXiServer


class BrowserAudioProvider(StepFunClient):
    """Exercise the authenticated audio routes without contacting a provider."""

    def __init__(self):
        super().__init__(api_key='browser-test-placeholder')

    def transcribe_pcm(self, audio, language='zh'):
        return '你好，灵犀'

    def stream_chat(self, messages, *, reasoning_effort=None):
        yield '你好，我在这里。'

    def synthesize(self, text, speech_rate, mode, **options):
        audio = io.BytesIO()
        with wave.open(audio, 'wb') as output:
            output.setframerate(16000)
            output.setnchannels(1)
            output.setsampwidth(2)
            output.writeframes(b'\0\0' * 3200)
        return audio.getvalue(), 'audio/wav'


with tempfile.TemporaryDirectory() as directory, patch.object(LingXiHandler, '_local_setup_allowed', return_value=False), patch.object(LingXiHandler, 'log_message', lambda *args: None):
    engine = DemoEngine(Path(directory) / 'browser.db', stepfun=BrowserAudioProvider())
    server = LingXiServer(('127.0.0.1', 0), engine)
    server.companion_token = 'ui-test-only-token'
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(json.dumps({'base': f'http://127.0.0.1:{server.server_port}'}), flush=True)
    try:
        sys.stdin.read()  # Parent closes stdin even when an assertion fails.
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
