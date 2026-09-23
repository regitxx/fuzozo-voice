"""Chat Completions adapter for configurable local or hosted AI systems."""
from configuration import settings as load_settings, auth_headers
SYSTEM = load_settings()['system_prompt']

def settings():
    cfg = load_settings()
    return {'base': cfg['ai_base_url'].rstrip('/'), 'model': cfg['ai_model'],
            'key_env': cfg['ai_api_key_env']}

def model_ids(client, config):
    response = client.get(config['base']+'/models', headers=auth_headers(config['key_env']))
    response.raise_for_status()
    return [row['id'] for row in response.json()['data']]

def reply(client, config, messages):
    if not config['model']:
        raise ValueError('Set ai_model in config.json to a model served by your endpoint')
    response = client.post(config['base']+'/chat/completions',
        headers=auth_headers(config['key_env']),
        json={'model': config['model'], 'messages': messages, 'stream': False})
    response.raise_for_status()
    content = response.json()['choices'][0]['message']['content']
    if not isinstance(content, str) or not content.strip():
        raise ValueError('AI returned no spoken text')
    return content.strip()
