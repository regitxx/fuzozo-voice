"""User-owned settings. API keys are read from environment variables only."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
ROOT = Path(__file__).resolve().parent
DEFAULTS = {
    'ai_base_url': 'http://127.0.0.1:1234/v1', 'ai_model': '',
    'ai_api_key_env': 'FUZOZO_AI_API_KEY',
    'system_prompt': 'You are a friendly robot companion. Be concise, curious, and honest.',
    'tts_provider': 'macos', 'tts_voice': '', 'tts_url': '',
    'tts_model': '', 'tts_api_key_env': 'FUZOZO_TTS_API_KEY',
    'stt_model': 'base.en',
}

def settings():
    values = dict(DEFAULTS)
    path = ROOT/'config.json'
    if path.exists():
        supplied = json.loads(path.read_text())
        if not isinstance(supplied, dict) or set(supplied)-set(DEFAULTS):
            raise ValueError('Unknown config.json settings')
        values.update(supplied)
    if any(not isinstance(value, str) for value in values.values()):
        raise ValueError('Configuration values must be strings')
    if values['tts_provider'] not in ('macos', 'http-wav', 'compatible'):
        raise ValueError('Unknown TTS provider')
    for key in ('ai_base_url', 'tts_url'):
        if not values[key]: continue
        url = urlsplit(values[key])
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Use an HTTP(S) URL without embedded credentials, query, or fragment: '+key)
    return values

def auth_headers(variable):
    key = os.environ.get(variable, '')
    return {'Authorization': 'Bearer '+key} if key else {}
