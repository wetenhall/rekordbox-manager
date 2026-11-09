"""Prepare standard PCM WAV fixtures for testing inside Rekordbox itself.

Only writes generated test audio and a reference manifest; never accesses a
Rekordbox library. These simple signals test integration, not genre accuracy.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rekordbox_manager.demo import create_demo


def prepare(destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    reference = []
    with tempfile.TemporaryDirectory(prefix='manager-audio-fixtures-') as temp:
        root = Path(temp)
        create_demo(root)
        for identity, bpm, intro in [('house', 128, 48), ('dnb', 174, 64), ('techno', 138, 32)]:
            audio, rate = sf.read(root / 'audio' / f'{identity}.wav', dtype='float32')
            assert rate == 8000
            audio = resample_poly(audio, 441, 80)
            target = destination / f'Manager TEST - {identity} - {bpm} BPM.wav'
            sf.write(target, np.column_stack((audio, audio)), 44100, subtype='PCM_16')
            reference.append({
                'file': target.name, 'bpm': bpm, 'first_downbeat_seconds': .2,
                'first_drop_seconds': .2 + intro * 4 * 60 / bpm,
                'second_drop_seconds': .2 + 144 * 4 * 60 / bpm,
                'intro_bars': intro, 'second_breakdown_bars': 32,
                'note': 'Synthetic integration fixture, not a realistic genre benchmark.',
            })
    (destination / 'expected-positions.json').write_text(json.dumps(reference, indent=2) + '\n')
    (destination / 'Manager Integration Test.m3u8').write_text(
        '#EXTM3U\n' + '\n'.join(track['file'] for track in reference) + '\n', encoding='utf-8'
    )
    print(destination.resolve())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('dist/Rekordbox Test Audio'))
    prepare(parser.parse_args().output)
