"""Motor katmanı testleri: ağ yok, model yok, anahtar yok (HTTP katmanı taklit edilir)."""
import base64
import io
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

import engines
from engines import base, text_tr
from engines import elevenlabs as el

FAKE_KEY = "sk_test_" + "0123456789abcdef" * 2   # sahte; gerçek anahtar değil


def wav_bytes(seconds=0.25, sr=24000, freq=220.0):
    t = np.arange(int(seconds * sr)) / sr
    buf = io.BytesIO()
    sf.write(buf, (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32), sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def json_resp(status, data, headers=None):
    return el.HttpResponse(status, headers or {"content-type": "application/json"}, json.dumps(data).encode())


SUBSCRIPTION = {"tier": "free", "character_count": 1000, "character_limit": 10000,
                "can_use_instant_voice_cloning": False, "voice_slots_used": 0, "voice_limit": 3,
                "next_character_count_reset_unix": 1}


class FakeTransport:
    """Sıralı/rotaya göre yanıt veren sahte HTTP katmanı; her çağrıyı kaydeder."""

    def __init__(self, routes):
        self.routes = {k: list(v) if isinstance(v, list) else v for k, v in routes.items()}
        self.calls = []

    def request(self, method, url, headers, body=None):
        self.calls.append(SimpleNamespace(method=method, url=url, headers=dict(headers), body=body))
        for prefix, value in self.routes.items():
            if f"{method} {url.split('://', 1)[1].split('/', 1)[1].split('?')[0]}".startswith(prefix):
                if isinstance(value, list):
                    return value.pop(0) if len(value) > 1 else value[0]
                return value
        raise AssertionError(f"beklenmeyen istek: {method} {url}")

    def count(self, prefix):
        return sum(1 for c in self.calls
                   if f"{c.method} {c.url.split('://', 1)[1].split('/', 1)[1].split('?')[0]}".startswith(prefix))


class ElevenLabsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sleeps = []

    def tearDown(self):
        self.tmp.cleanup()

    def engine(self, routes, env=None, **kw):
        self.transport = FakeTransport(routes)
        env = {"ELEVENLABS_API_KEY": FAKE_KEY} if env is None else env
        return el.ElevenLabsEngine(transport=self.transport, output_dir=self.root / "out",
                                   cache_dir=self.root / "cache", sleep=self.sleeps.append, env=env, **kw)


class SynthesisTests(ElevenLabsTestCase):
    def test_successful_tts_writes_app_wav_and_sends_expected_request(self):
        eng = self.engine({"GET v1/user/subscription": json_resp(200, SUBSCRIPTION),
                           "POST v1/text-to-speech/": el.HttpResponse(200, {"content-type": "audio/wav",
                                                                             "request-id": "r1"}, wav_bytes())})
        res = eng.synthesize("Toplantı 14:30'da, %25 indirim.", voice="voice123", quality="Dengeli", seed=7)
        info = sf.info(res.path)
        self.assertEqual((info.samplerate, info.channels, info.subtype), (48000, 1, "PCM_16"))
        self.assertAlmostEqual(info.duration, 0.25, places=2)
        self.assertEqual(res.sample_rate, 48000)
        call = [c for c in self.transport.calls if c.method == "POST"][0]
        self.assertIn("/v1/text-to-speech/voice123?output_format=wav_24000", call.url)
        self.assertEqual(call.headers["xi-api-key"], FAKE_KEY)
        body = json.loads(call.body)
        self.assertEqual(body["model_id"], "eleven_multilingual_v2")
        self.assertNotIn("language_code", body)          # multilingual_v2 desteklemiyor
        self.assertEqual(body["seed"], 7)
        self.assertIn("on dört otuz", body["text"])       # Türkçe normalizasyon uygulandı
        self.assertIn("yüzde yirmi beş", body["text"])
        self.assertEqual(res.meta["engine"], "elevenlabs")
        self.assertFalse(res.meta["cached"])
        self.assertEqual(res.meta["characters"], len(body["text"]))

    def test_quality_modes_map_to_models_and_language_code(self):
        eng = self.engine({"GET v1/user/subscription": json_resp(200, SUBSCRIPTION),
                           "POST v1/text-to-speech/": el.HttpResponse(200, {}, wav_bytes())})
        eng.synthesize("Merhaba.", voice="v", quality="Hızlı", use_cache=False)
        body = json.loads([c for c in self.transport.calls if c.method == "POST"][-1].body)
        self.assertEqual((body["model_id"], body["language_code"]), ("eleven_flash_v2_5", "tr"))
        self.assertEqual(eng.model_for("En İyi"), "eleven_v3")
        forced = self.engine({}, env={"ELEVENLABS_API_KEY": FAKE_KEY, "SESVER_ELEVENLABS_MODEL": "eleven_v4"})
        self.assertEqual(forced.model_for("Hızlı"), "eleven_v4")

    def test_wav_conversion_resamples_pcm_and_wav(self):
        sr_in = 22050
        pcm = (np.sin(np.linspace(0, 100, sr_in)) * 10000).astype("<i2").tobytes()
        audio, sr = el.decode_audio(pcm, "pcm_22050")
        self.assertEqual((sr, len(audio)), (22050, sr_in))
        out = self.root / "x.wav"
        self.assertEqual(el.to_app_wav(audio, sr, out), 48000)
        self.assertAlmostEqual(sf.info(str(out)).duration, 1.0, places=2)
        stereo = io.BytesIO()
        sf.write(stereo, np.zeros((4410, 2), dtype=np.float32), 44100, format="WAV")
        mono, sr2 = el.decode_audio(stereo.getvalue())
        self.assertEqual((mono.ndim, sr2), (1, 44100))
        with self.assertRaises(base.ServiceError):
            el.decode_audio(b"")

    def test_output_feeds_existing_effects_chain(self):
        import effects as fx
        eng = self.engine({"GET v1/user/subscription": json_resp(200, SUBSCRIPTION),
                           "POST v1/text-to-speech/": el.HttpResponse(200, {}, wav_bytes())})
        res = eng.synthesize("Merhaba.", voice="v")
        audio, sr = sf.read(res.path, dtype="float32", always_2d=True)   # app.py'deki okuma biçimi
        self.assertEqual(sr, 48000)
        out = fx.apply(audio.mean(axis=1), sr, [{"ad": "telefon", "yogunluk": 60},
                                                {"ad": "oda", "yogunluk": 40, "on_ayar": "salon"}])
        self.assertEqual(out.ndim, 1)
        self.assertGreaterEqual(out.shape[0], audio.shape[0])   # oda efekti yankı kuyruğu ekler
        self.assertTrue(np.isfinite(out).all())

    def test_cache_prevents_second_quota_spend(self):
        eng = self.engine({"GET v1/user/subscription": json_resp(200, SUBSCRIPTION),
                           "POST v1/text-to-speech/": el.HttpResponse(200, {}, wav_bytes())})
        first = eng.synthesize("Aynı metin.", voice="v", seed=1)
        second = eng.synthesize("Aynı metin.", voice="v", seed=1)
        self.assertEqual(self.transport.count("POST v1/text-to-speech/"), 1)
        self.assertTrue(second.meta["cached"])
        self.assertEqual(second.meta["credits"], 0.0)
        self.assertNotEqual(first.path, second.path)       # her üretim kendi dosyası (efekt yerinde yazmasın)
        eng.synthesize("Aynı metin.", voice="v", seed=2)    # ayar değişti → yeni istek
        eng.synthesize("Aynı metin.", voice="v", seed=1, voice_settings={"stability": 0.9})
        eng.synthesize("Aynı metin.", voice="v2", seed=1)
        self.assertEqual(self.transport.count("POST v1/text-to-speech/"), 4)

    def test_missing_voice_and_text_limits(self):
        eng = self.engine({})
        with self.assertRaises(base.EngineConfigError):
            eng.synthesize("Merhaba.", voice=None)
        with self.assertRaises(base.TextTooLongError):
            eng.synthesize("a" * 10_001, voice="v")
        self.assertEqual(self.transport.calls, [])          # sınır istek atılmadan yakalandı

    def test_instruction_is_reported_not_silently_dropped(self):
        eng = self.engine({"GET v1/user/subscription": json_resp(200, SUBSCRIPTION),
                           "POST v1/text-to-speech/": el.HttpResponse(200, {}, wav_bytes())})
        res = eng.synthesize("Merhaba.", voice="v", instruction="happy")
        self.assertTrue(res.meta["uyarilar"])


class ErrorTests(ElevenLabsTestCase):
    def test_401_maps_to_turkish_auth_error_without_retry(self):
        eng = self.engine({"GET v1/user/subscription": json_resp(401, {"detail": {
            "status": "invalid_api_key", "message": "Invalid API key"}})})
        with self.assertRaises(base.AuthError) as ctx:
            eng.usage()
        self.assertIn("anahtarı geçersiz", str(ctx.exception))
        self.assertEqual(ctx.exception.status, 401)
        self.assertEqual(self.transport.count("GET"), 1)
        self.assertEqual(self.sleeps, [])

    def test_missing_key_is_auth_error_before_any_request(self):
        eng = self.engine({}, env={})
        with self.assertRaises(base.AuthError) as ctx:
            eng.usage()
        self.assertIn("ELEVENLABS_API_KEY", str(ctx.exception))
        self.assertEqual(self.transport.calls, [])

    def test_429_retries_with_backoff_then_succeeds(self):
        busy = json_resp(429, {"detail": {"code": "concurrent_limit_exceeded"}}, {"retry-after": "2"})
        eng = self.engine({"GET v1/user/subscription": [busy, json_resp(429, {}), json_resp(200, SUBSCRIPTION)]},
                          backoff_base=1.0)
        info = eng.usage()
        self.assertEqual(info.remaining, 9000)
        self.assertEqual(self.transport.count("GET"), 3)
        self.assertEqual(len(self.sleeps), 2)
        self.assertEqual(self.sleeps[0], 2.0)              # Retry-After'a uyuldu
        self.assertGreaterEqual(self.sleeps[1], 2.0)        # üstel: 1*2^1 (+sapma)

    def test_429_exhausts_retries_and_raises_rate_limit_error(self):
        eng = self.engine({"GET v1/user/subscription": json_resp(429, {"detail": {
            "code": "rate_limit_exceeded"}})}, max_retries=2, backoff_max=5)
        with self.assertRaises(base.RateLimitError) as ctx:
            eng.usage()
        self.assertEqual(self.transport.count("GET"), 3)
        self.assertEqual(len(self.sleeps), 2)
        self.assertTrue(all(s <= 5 for s in self.sleeps))
        self.assertIn("yeniden deneme", str(ctx.exception))

    def test_quota_exceeded_from_api_is_not_retried(self):
        eng = self.engine({"GET v1/user/subscription": json_resp(200, SUBSCRIPTION),
                           "POST v1/text-to-speech/": json_resp(429, {"detail": {"code": "quota_exceeded"}})})
        with self.assertRaises(base.QuotaError):
            eng.synthesize("Merhaba.", voice="v")
        self.assertEqual(self.transport.count("POST"), 1)
        self.assertEqual(self.sleeps, [])

    def test_other_status_codes(self):
        cases = [(402, {}, base.QuotaError), (403, {}, base.PlanFeatureError), (404, {}, base.VoiceNotFoundError),
                 (500, {}, base.ServiceError), (422, {"detail": {"code": "max_character_limit_exceeded"}},
                                                    base.TextTooLongError), (400, {}, base.EngineError)]
        for status, data, cls in cases:
            err = el.map_error(json_resp(status, data))
            self.assertIsInstance(err, cls, status)
            self.assertTrue(str(err))

    def test_5xx_retried(self):
        eng = self.engine({"GET v1/user/subscription": [json_resp(503, {}), json_resp(200, SUBSCRIPTION)]})
        self.assertEqual(eng.usage().tier, "free")
        self.assertEqual(len(self.sleeps), 1)


class QuotaTests(ElevenLabsTestCase):
    def test_estimate_returns_characters_cost_and_remaining(self):
        eng = self.engine({"GET v1/user/subscription": json_resp(200, SUBSCRIPTION)})
        est = eng.estimate("a" * 800, quality="Dengeli")
        self.assertEqual((est.characters, est.credits, est.remaining, est.enough), (800, 800.0, 9000, True))
        self.assertEqual(est.model, "eleven_multilingual_v2")
        self.assertEqual(est.tier, "free")

    def test_insufficient_quota_raises_before_tts_request(self):
        low = dict(SUBSCRIPTION, character_count=9990)
        eng = self.engine({"GET v1/user/subscription": json_resp(200, low),
                           "POST v1/text-to-speech/": el.HttpResponse(200, {}, wav_bytes())})
        with self.assertRaises(base.QuotaError) as ctx:
            eng.synthesize("Bu metin on karakterden uzun.", voice="v")
        self.assertIn("kalan 10", str(ctx.exception))
        self.assertEqual(self.transport.count("POST"), 0)

    def test_usage_is_cached_and_spent_locally(self):
        eng = self.engine({"GET v1/user/subscription": json_resp(200, SUBSCRIPTION),
                           "POST v1/text-to-speech/": el.HttpResponse(200, {}, wav_bytes())})
        eng.synthesize("Merhaba.", voice="v")
        eng.synthesize("Merhaba dünya.", voice="v")
        self.assertEqual(self.transport.count("GET v1/user/subscription"), 1)
        self.assertEqual(eng.usage().remaining, 9000 - len("Merhaba.") - len("Merhaba dünya."))


class DesignTests(ElevenLabsTestCase):
    PREVIEW_TEXT = "Merhaba, bu ses tasarımı için hazırlanmış yüz karakterden uzun bir örnek cümledir; " \
                   "sakin ve anlaşılır biçimde okunmalıdır."

    def design_response(self, n=3):
        return json_resp(200, {"previews": [{"audio_base_64": base64.b64encode(wav_bytes()).decode(),
                                             "generated_voice_id": f"g{i}", "media_type": "audio/wav",
                                             "duration_secs": 0.25, "language": "tr"} for i in range(n)],
                               "text": self.PREVIEW_TEXT})

    def test_design_defaults_to_one_candidate_and_one_call(self):
        eng = self.engine({"GET v1/user/subscription": json_resp(200, SUBSCRIPTION),
                           "POST v1/text-to-voice/design": self.design_response()})
        previews = eng.design_voice("(middle-aged male, deep voice, calm)", self.PREVIEW_TEXT)
        self.assertEqual(len(previews), 1)
        self.assertEqual(self.transport.count("POST v1/text-to-voice/design"), 1)
        self.assertEqual(previews[0].id, "g0")
        self.assertEqual(sf.info(previews[0].path).samplerate, 48000)
        body = json.loads([c for c in self.transport.calls if c.method == "POST"][0].body)
        self.assertTrue(body["voice_description"].startswith("Native Turkish speaker. Middle-aged male"))
        self.assertEqual(body["model_id"], "eleven_multilingual_ttv_v2")

    def test_design_four_candidates_uses_two_calls(self):
        eng = self.engine({"GET v1/user/subscription": json_resp(200, SUBSCRIPTION),
                           "POST v1/text-to-voice/design": self.design_response()})
        previews = eng.design_voice("calm narrator", self.PREVIEW_TEXT, candidates=4, seed=11)
        self.assertEqual(len(previews), 4)
        self.assertEqual(self.transport.count("POST v1/text-to-voice/design"), 2)
        seeds = [json.loads(c.body)["seed"] for c in self.transport.calls if c.method == "POST"]
        self.assertEqual(seeds, [11, 12])

    def test_design_text_length_validated(self):
        eng = self.engine({})
        with self.assertRaises(base.EngineError):
            eng.design_voice("calm", "Kısa.")
        self.assertEqual(self.transport.calls, [])

    def test_voice_designer_description_maps(self):
        import voice_designer as vdes
        m = vdes.load_map()
        tarif = vdes.build_description(vdes.default_selections(m), m)[0]
        prompt = el.map_description(tarif)
        self.assertTrue(prompt.startswith("Native Turkish speaker."))
        self.assertNotIn("(", prompt)
        self.assertTrue(prompt.endswith("Excellent audio quality."))

    def test_save_designed_voice(self):
        eng = self.engine({"POST v1/text-to-voice": json_resp(200, {"voice_id": "new1", "name": "Anlatıcı"})})
        voice = eng.save_designed_voice("g0", "Anlatıcı", "calm narrator")
        self.assertEqual((voice.id, voice.category), ("new1", "generated"))
        body = json.loads(self.transport.calls[0].body)
        self.assertEqual(body["generated_voice_id"], "g0")


class CloneTests(ElevenLabsTestCase):
    def sample(self, name="ornek.wav"):
        path = self.root / name
        path.write_bytes(wav_bytes(1.0))
        return path

    def test_clone_without_consent_rejected_before_any_request(self):
        eng = self.engine({})
        for consent in (False, None, "evet", 1):
            with self.assertRaises(base.ConsentError):
                eng.clone_voice(str(self.sample()), "metin", consent)
        self.assertEqual(self.transport.calls, [])

    def test_protected_names_never_uploaded(self):
        eng = self.engine({})
        with self.assertRaises(base.ConsentError):
            eng.clone_voice(str(self.sample()), None, True, name="Yusuf sesi")
        with self.assertRaises(base.ConsentError):
            eng.clone_voice(str(self.sample("akif.wav")), None, True, name="deneme")
        self.assertEqual(self.transport.calls, [])

    def test_library_voice_needs_explicit_upload_permission(self):
        import voice_library as vlib
        eng = self.engine({})
        with patch.object(vlib, "VOICES_DIR", self.root):
            with self.assertRaises(base.ConsentError):
                eng.clone_voice(str(self.sample()), None, True, name="Kütüphane sesi")
        self.assertEqual(self.transport.calls, [])

    def test_free_plan_clone_blocked(self):
        eng = self.engine({"GET v1/user/subscription": json_resp(200, SUBSCRIPTION)})
        with self.assertRaises(base.PlanFeatureError):
            eng.clone_voice(str(self.sample()), None, True, name="Deneme")
        self.assertEqual(self.transport.count("POST"), 0)

    def test_clone_with_consent_uploads_multipart_without_transcript(self):
        paid = dict(SUBSCRIPTION, tier="starter", can_use_instant_voice_cloning=True)
        eng = self.engine({"GET v1/user/subscription": json_resp(200, paid),
                           "POST v1/voices/add": json_resp(200, {"voice_id": "c1", "requires_verification": False})})
        voice = eng.clone_voice(str(self.sample()), "gizli transkript", True, name="Deneme")
        self.assertEqual((voice.id, voice.category), ("c1", "cloned"))
        call = [c for c in self.transport.calls if c.method == "POST"][0]
        self.assertTrue(call.headers["Content-Type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="files"; filename="ornek.wav"', call.body)
        self.assertNotIn("gizli transkript".encode(), call.body)


class SecretTests(ElevenLabsTestCase):
    def test_mask_secret(self):
        self.assertEqual(el.mask_secret(FAKE_KEY), "***" + FAKE_KEY[-4:])
        self.assertEqual(el.mask_secret(""), "<yok>")
        self.assertEqual(el.mask_secret("kisa"), "***")

    def test_key_never_in_repr_errors_or_logs(self):
        eng = self.engine({"GET v1/user/subscription": json_resp(401, {"detail": {"status": "invalid_api_key"}})})
        self.assertNotIn(FAKE_KEY, repr(eng))
        # Anahtar nesne alanı olarak tutulmaz (yalnız ortam kaynağından istek anında okunur).
        own = {k: v for k, v in vars(eng).items() if k != "_env"}
        self.assertNotIn(FAKE_KEY, repr(own))
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": FAKE_KEY}), \
                self.assertLogs("sesver.engines.elevenlabs", level="INFO") as logs:
            el.log.info("hata ayıklama: anahtar=%s", FAKE_KEY)   # yanlışlıkla loglansa bile
            with self.assertRaises(base.AuthError) as ctx:
                eng.usage()
        joined = "\n".join(logs.output)
        self.assertNotIn(FAKE_KEY, joined)
        self.assertIn("***" + FAKE_KEY[-4:], joined)
        self.assertNotIn(FAKE_KEY, str(ctx.exception))

    def test_network_error_does_not_leak(self):
        class Boom:
            def request(self, *a, **k):
                raise OSError(f"bağlantı koptu {FAKE_KEY}")
        eng = el.ElevenLabsEngine(transport=Boom(), output_dir=self.root, sleep=self.sleeps.append,
                                  env={"ELEVENLABS_API_KEY": FAKE_KEY}, max_retries=1)
        with self.assertRaises(base.ServiceError) as ctx:
            eng.usage()
        self.assertNotIn(FAKE_KEY, str(ctx.exception))
        self.assertNotIn(FAKE_KEY, str(ctx.exception.__cause__))

    def test_no_key_literal_in_engine_sources(self):
        for path in Path(el.__file__).parent.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"sk_[0-9a-f]{20,}", path.name)


class SelectionTests(unittest.TestCase):
    def test_default_engine_is_voxcpm(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SESVER_ENGINE", None)
            self.assertEqual(engines.selected_engine_name(), "voxcpm")
            self.assertEqual(engines.get_engine().name, "voxcpm")
        self.assertEqual(engines.selected_engine_name({}), "voxcpm")
        self.assertEqual(engines.selected_engine_name({"SESVER_ENGINE": " ElevenLabs "}), "elevenlabs")

    def test_unknown_engine_rejected(self):
        with self.assertRaises(base.EngineConfigError):
            engines.selected_engine_name({"SESVER_ENGINE": "bulut"})

    def test_elevenlabs_selection_needs_no_key_until_request(self):
        with patch.dict(os.environ, {"SESVER_ENGINE": "elevenlabs"}):
            os.environ.pop("ELEVENLABS_API_KEY", None)
            eng = engines.get_engine()
            self.assertEqual(eng.name, "elevenlabs")
            self.assertFalse(eng.capabilities.local)
            self.assertEqual(eng.capabilities.default_candidates, 1)

    def test_app_does_not_use_engine_layer(self):
        """Arayüz bağlantısı yok: app.py motor katmanını içe aktarmıyor."""
        source = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("import engines", source)
        self.assertNotIn("from engines", source)
        self.assertNotIn("elevenlabs", source.lower())


class VoxCPMWrapperTests(unittest.TestCase):
    """İnce sarmalayıcı gerçek ``app.generate_audio``'yu çağırır; yalnız sinir ağı taklit edilir."""

    def setUp(self):
        import app
        self.app = app
        self.tmp = tempfile.TemporaryDirectory()
        self.model = SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000),
                                     generate=Mock(return_value=np.zeros(4800, dtype=np.float32)))
        self.patches = [patch.object(app, "OUTPUT_DIR", Path(self.tmp.name)),
                        patch.object(app, "get_model", return_value=self.model)]
        for p in self.patches:
            p.start()
        from engines.voxcpm import VoxCPMEngine
        self.engine = VoxCPMEngine()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_random_voice_matches_library_generate(self):
        res = self.engine.synthesize("Merhaba.", quality="En İyi", seed=5)
        self.assertEqual(sf.info(res.path).samplerate, 48000)
        self.assertEqual(res.meta["mode"], "referanssiz")
        kwargs = self.model.generate.call_args.kwargs
        self.assertEqual(kwargs.get("inference_timesteps"), 16)
        direct = list(self.app.library_generate("Merhaba.", "Nötr", "En İyi"))[-1]
        self.assertEqual(self.model.generate.call_args.kwargs.get("inference_timesteps"), 16)
        self.assertTrue(Path(direct[0]).is_file())

    def test_emotion_label_becomes_instruction(self):
        res = self.engine.synthesize("Merhaba.", instruction="Neşeli")
        self.assertEqual(res.meta["mode"], "tarif")
        self.assertIn(self.app.EMOTIONS["Neşeli"], self.model.generate.call_args.kwargs.get("text", ""))

    def test_errors_become_engine_errors(self):
        with self.assertRaises(base.EngineError):
            self.engine.synthesize("   ")
        with self.assertRaises(base.VoiceNotFoundError):
            self.engine.synthesize("Merhaba.", voice="yok-boyle-ses")

    def test_capabilities_and_usage(self):
        caps = self.engine.capabilities
        self.assertTrue(caps.local and caps.seed_deterministic and caps.continuation)
        self.assertEqual(caps.default_candidates, 4)
        self.assertFalse(self.engine.usage().metered)
        self.assertEqual(self.engine.estimate("abc").credits, 0.0)

    def test_clone_requires_consent(self):
        with self.assertRaises(base.ConsentError):
            self.engine.clone_voice("x.wav", "metin", False)


class TurkishNormalizerTests(unittest.TestCase):
    def test_numbers(self):
        cases = {0: "sıfır", 1: "bir", 10: "on", 21: "yirmi bir", 100: "yüz", 101: "yüz bir",
                 1000: "bin", 1001: "bin bir", 2025: "iki bin yirmi beş",
                 1_250_000: "bir milyon iki yüz elli bin", 3_000_000_000: "üç milyar"}
        for n, words in cases.items():
            self.assertEqual(text_tr.number_to_words(n), words)

    def test_normalize_text(self):
        n = text_tr.normalize
        self.assertEqual(n("Fiyat 1.250.000 TL."), "Fiyat bir milyon iki yüz elli bin Türk lirası.")
        self.assertEqual(n("%25 indirim"), "yüzde yirmi beş indirim")
        self.assertEqual(n("3,5 km yürüdük"), "üç virgül beş kilometre yürüdük")
        self.assertEqual(n("Saat 09:05"), "Saat dokuz beş")
        self.assertEqual(n("Dr. Ayşe ve Prof. Dr. Ali vb. kişiler"),
                         "Doktor Ayşe ve Profesör Doktor Ali ve benzeri kişiler")
        self.assertEqual(n("12 elma, 3 armut"), "on iki elma, üç armut")
        self.assertEqual(n(""), "")
        self.assertEqual(n("Sayı yok."), "Sayı yok.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    unittest.main()
