"""Isolated UI test server. No local settings, production DB or cloud credentials."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from providers.stepfun import StepFunClient
from server import DemoEngine, LingXiHandler, LingXiServer

with tempfile.TemporaryDirectory() as directory, patch.object(LingXiHandler, '_local_setup_allowed', return_value=False), patch.object(LingXiHandler, 'log_message', lambda *args: None):
    engine = DemoEngine(Path(directory) / 'browser.db', stepfun=StepFunClient())
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
