import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from extract_audio_window import decode_window


class AudioWindowTests(unittest.TestCase):
    def test_window_matches_full_decode_with_global_sample_timing(self):
        import numpy as np
        import soundfile as sf
        from transcribe_funasr import decode_audio

        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / "synthetic.wav"
            times = np.arange(90 * 48000) / 48000
            signal = (np.sin(2 * np.pi * 713 * times) + np.sin(2 * np.pi * 1231 * times)) * 0.2
            sf.write(str(audio), signal, 48000, subtype="PCM_16")
            window, frames = decode_window(audio, 45_123, 52_456)
            full = decode_audio(audio)
            expected = (full[45_123 * 16:52_456 * 16] * 32768).astype(np.int16)
            np.testing.assert_array_equal(window, expected)
            self.assertEqual(len(window), 7333 * 16)
            self.assertGreater(frames, 0)

    def test_invalid_or_truncated_windows_do_not_produce_partial_success(self):
        import numpy as np
        import soundfile as sf

        with self.assertRaises(ValueError):
            decode_window("not-opened.wav", 1000, 900)
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / "short.wav"
            sf.write(str(audio), np.zeros(16000), 16000, subtype="PCM_16")
            with self.assertRaisesRegex(ValueError, "incomplete"):
                decode_window(audio, 0, 1500)


if __name__ == "__main__":
    unittest.main()
