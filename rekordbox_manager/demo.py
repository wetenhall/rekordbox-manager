"""Generated, copyright-free demo audio and an explicitly separate fixture format."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import tempfile

import numpy as np
import soundfile as sf

from .models import Cue, Grid, Track, Proposal
from .backups import BackupStore, digest, durable_json
from .guards import SafetyError


def create_demo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    library = root / "demo-library.json"
    if library.exists():
        return library
    (root / "audio").mkdir(exist_ok=True)
    (root / "analysis").mkdir(exist_ok=True)
    entries = []
    for identity, title, genre, bpm, intro in [
        ("house", "After Hours", "House", 128, 48),
        ("dnb", "Night Transit", "Drum and bass", 174, 64),
        ("techno", "Concrete Motion", "Techno", 138, 32),
    ]:
        sr, bars = 8000, 192
        seconds_per_beat = 60 / bpm
        lead = .2
        duration = bars * 4 * seconds_per_beat + lead
        samples = np.zeros(int(duration * sr), dtype=np.float32)
        rng = np.random.default_rng(7)
        kt = np.arange(int(sr * .18)) / sr
        kick = np.sin(2 * np.pi * (65 * kt - 70 * kt * kt)) * np.exp(-kt * 24)
        ht = np.arange(int(sr * .04)) / sr
        hat = rng.normal(0, .08, len(ht)) * np.exp(-ht * 90)
        for beat in range(bars * 4):
            bar = beat // 4
            strong = intro <= bar < 112 or 144 <= bar < 176
            in_break = 112 <= bar < 144
            gain = .65 if strong else (.025 if in_break else .14)
            at = int((beat * seconds_per_beat + lead) * sr)
            # The demonstration is deliberately simple, not a benchmark for real DnB.
            sound = kick * gain
            samples[at:at + len(sound)] += sound[:len(samples) - at]
            at += int(seconds_per_beat * sr / 2)
            if at + len(hat) < len(samples):
                samples[at:at + len(hat)] += hat * (1 if strong else .25)
        audio = root / "audio" / f"{identity}.wav"
        sf.write(audio, samples, sr, subtype="PCM_16")
        # A known 32 ms grid error exercises correction and approval.
        times = [i * seconds_per_beat + lead + .032 for i in range(bars * 4)]
        grid = {"times": times, "positions": [i % 4 + 1 for i in range(bars * 4)]}
        durable_json(root / "analysis" / f"{identity}.json", grid)
        entries.append({"id": identity, "title": title, "artist": "Manager demo · synthetic audio",
                        "genre": genre, "bpm": bpm, "duration": duration,
                        "audio": f"audio/{identity}.wav", "analysis": f"analysis/{identity}.json",
                        "cues": [{"time": 4 * seconds_per_beat, "label": "Protected hot cue", "kind": "hot", "end": None}]})
    durable_json(library, {"format": "manager-demo-v1", "tracks": entries})
    return library


class DemoLibrary:
    demo = True
    writable = True
    write_reason = "Changes affect only the generated demo library."
    name = "Demo library · synthetic audio"
    playlists = {"all": "Demo / All genres", "house": "Demo / House", "dnb": "Demo / Drum and bass", "techno": "Demo / Techno"}

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.root = self.path.parent
        self.reload()

    def reload(self):
        self.data = json.loads(self.path.read_text(encoding="utf-8"))
        if self.data.get("format") != "manager-demo-v1":
            raise ValueError("Not a Manager demo library.")
        self.fingerprints = {"demo-library.json": digest(self.path)}
        for t in self.data["tracks"]:
            self.fingerprints[str(Path(t["analysis"]))] = digest(self.root / t["analysis"])

    def tracks(self, playlist: str) -> list[Track]:
        result = []
        for t in self.data["tracks"]:
            if playlist not in ("all", t["id"]):
                continue
            analysis = self.root / t["analysis"]
            grid = Grid(**json.loads(analysis.read_text(encoding="utf-8")))
            result.append(Track(t["id"], t["title"], t["artist"], t["genre"], self.root / t["audio"],
                                t["duration"], t["bpm"], grid, [Cue(**c) for c in t["cues"]], [analysis]))
        return result

    def apply(self, proposals: list[Proposal], backups: BackupStore) -> Path:
        if not proposals or any(not p.can_apply for p in proposals):
            raise SafetyError("Every selected track must be reviewed before applying.")
        proposed = json.loads(json.dumps(self.data))
        by_id = {t["id"]: t for t in proposed["tracks"]}
        with tempfile.TemporaryDirectory(prefix="manager-stage-") as temp:
            stage = Path(temp)
            replacements = {}
            for proposal in proposals:
                t = by_id[proposal.track.id]
                if proposal.options.set_cues:
                    t["cues"] = [asdict(c) for c in proposal.cues]
                if proposal.options.fix_grid:
                    dest = stage / f"{t['id']}.json"
                    durable_json(dest, asdict(proposal.grid))
                    replacements[str(Path(t["analysis"]))] = dest
                    steps = np.diff(proposal.grid.times)
                    t["bpm"] = round(60 / float(np.median(steps)), 3)
            durable_json(stage / "demo-library.json", proposed)
            replacements["demo-library.json"] = stage / "demo-library.json"
            def validate_result():
                if json.loads(self.path.read_text(encoding="utf-8")) != proposed:
                    raise SafetyError("Read-back verification failed.")
                for relative, source in replacements.items():
                    if digest(self.root / relative) != digest(source):
                        raise SafetyError("Read-back verification failed.")
            backup = backups.install(self.root, replacements, self.fingerprints, lambda: None,
                                     validate_result, f"DEMO: updated {len(proposals)} track(s)")
        self.reload()
        return backup
