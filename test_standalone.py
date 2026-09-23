import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import wave
import httpx
import ai_backend
import configuration
import speech_clip
from setup_device import parse_identity


def wav(channels=2, rate=16000, width=2):
    out=io.BytesIO()
    with wave.open(out,'wb') as w:
        w.setparams((channels,width,rate,0,'NONE','not compressed'))
        w.writeframes(b'\0'*(rate//10*channels*width))
    return out.getvalue()


class StandaloneTests(unittest.TestCase):
    def test_ai_uses_configured_model_endpoint_and_environment_auth(self):
        seen=[]
        def handle(request):
            seen.append(request)
            if request.url.path.endswith('/models'):
                return httpx.Response(200,json={'data':[{'id':'lab-model'}]})
            return httpx.Response(200,json={'choices':[{'message':{'content':' Hello lab. '}}]})
        cfg={'base':'https://ai.example.test/v1','model':'lab-model','key_env':'TEST_FUZOZO_KEY'}
        with patch.dict(os.environ,{'TEST_FUZOZO_KEY':'test-only-placeholder'}),httpx.Client(transport=httpx.MockTransport(handle)) as client:
            self.assertEqual(ai_backend.model_ids(client,cfg),['lab-model'])
            self.assertEqual(ai_backend.reply(client,cfg,[{'role':'user','content':'Hello'}]),'Hello lab.')
        self.assertEqual(str(seen[1].url),'https://ai.example.test/v1/chat/completions')
        self.assertEqual(seen[1].headers['authorization'],'Bearer test-only-placeholder')
        self.assertEqual(json.loads(seen[1].content)['model'],'lab-model')

    def test_empty_model_stops_before_network(self):
        client=Mock()
        with self.assertRaises(ValueError):
            ai_backend.reply(client,{'model':''},[])
        client.post.assert_not_called()

    def test_config_rejects_embedded_credentials(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(configuration,'ROOT',Path(temp)):
            Path(temp,'config.json').write_text(json.dumps({'ai_base_url':'https://name:password@example.test/v1'}))
            with self.assertRaises(ValueError): configuration.settings()

    def test_audio_normalizes_stereo_16k_to_mono_24k(self):
        data,seconds=speech_clip.normalize(wav())
        with wave.open(io.BytesIO(data),'rb') as w:
            self.assertEqual((w.getnchannels(),w.getsampwidth(),w.getframerate()),(1,2,24000))
        self.assertAlmostEqual(seconds,.1,places=3)

    def test_audio_rejects_unsupported_samples(self):
        with self.assertRaises(ValueError): speech_clip.normalize(wav(width=1))

    def test_tts_provider_contracts(self):
        for provider in ['http-wav','compatible']:
            seen=[]
            def handle(request):
                seen.append(request)
                return httpx.Response(200,content=wav())
            cfg=dict(configuration.DEFAULTS,tts_provider=provider,tts_url='https://voice.example.test/synthesize',tts_model='voice-model',tts_voice='voice-name')
            real_client=httpx.Client
            with patch.object(speech_clip,'settings',return_value=cfg),patch('speech_clip.httpx.Client',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw)):
                _,seconds=speech_clip.render('Hello')
            self.assertGreater(seconds,0)
            body=json.loads(seen[0].content)
            self.assertEqual(body.get('text',body.get('input')),'Hello')
            if provider=='compatible': self.assertEqual(body['response_format'],'wav')

    def test_identity_rejects_ambiguous_or_unrelated_macs(self):
        self.assertEqual(parse_identity(b'(123):get mac:02:00:00:00:00:01\r\n'),'020000000001')
        for data in [b'other:02:00:00:00:00:01',b'get mac:02:00:00:00:00:01\nget mac:02:00:00:00:00:02']:
            with self.assertRaises(ValueError): parse_identity(data)

if __name__=='__main__': unittest.main()
