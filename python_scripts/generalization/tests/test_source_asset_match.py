"""Run in Blender: conservative unknown-model control-map correspondence."""
import copy
import json
from pathlib import Path
import shutil
import sys
import uuid
from types import SimpleNamespace

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'addons'))
from random_play_toon.materials import source_asset_match as match
from random_play_toon._vendor.mmd_tools.core import pmx


def save_pixels(path, pixels):
    image = bpy.data.images.new('matching fixture', width=pixels.shape[1], height=pixels.shape[0])
    image.colorspace_settings.name = 'Non-Color'
    image.pixels.foreach_set(pixels.astype(np.float32).ravel())
    image.filepath_raw = str(path)
    # Blender sniffs the image header. PNG fixtures named *Diffuse.dds let this
    # test exercise pairing without shipping copyrighted or compressed assets.
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)


def main():
    y, x = np.mgrid[:64, :64]
    pixels = np.stack(((x * 7 % 64) / 64, (y * 5 % 64) / 64,
                       ((x + y * 3) % 64) / 64, np.ones_like(x)), axis=2)
    uv = [(x/8, y/8) for y in range(9) for x in range(9)]
    faces = [(y*9+x, y*9+x+1, (y+1)*9+x) for y in range(8) for x in range(8)]
    model = SimpleNamespace(vertices=[SimpleNamespace(uv=(u, 1-v)) for u,v in uv], faces=faces)
    original_load = pmx.load
    pmx.load = lambda _: model
    outcomes = []
    test_root = (ROOT / 'experiments' / 'SourceAssetMatchTests').resolve()
    test_root.mkdir(parents=True, exist_ok=True)
    try:
        root = test_root / ('run-' + uuid.uuid4().hex)
        root.mkdir()
        try:
            root = root.resolve()
            assert root.is_relative_to(test_root) and root != test_root
            source = root / 'source.png'
            assets = root / 'maps'
            assets.mkdir()
            save_pixels(source, pixels)
            base_profile = {'uncalibrated': True, 'materials': [
                {'index': 0, 'face_start': 0, 'face_count': len(faces), 'maps': {}, 'role': 'hair'}]}

            def run():
                profile = copy.deepcopy(base_profile)
                inputs = {'pmx': 'fixture.pmx', 'textures': {'0': str(source)}, 'maps': {'0': {}}}
                audit = match.resolve(profile, inputs, assets)
                return profile, inputs, audit

            save_pixels(assets / 'AtlasDiffuse.dds', pixels)
            save_pixels(assets / 'AtlasLightMap.dds', pixels)
            profile, inputs, audit = run()
            assert audit[0]['accepted'] and profile['materials'][0]['dds_flip_v'] is False
            assert inputs['maps']['0']['LightMap'].endswith('AtlasLightMap.dds')
            outcomes.append('matching surface accepted')

            original_sha = match._sha
            for failed_name in ('AtlasDiffuse.dds', 'AtlasLightMap.dds', 'source.png'):
                def unreadable(path, failed_name=failed_name):
                    if path.name == failed_name:
                        raise PermissionError('fixture optional asset unavailable')
                    return original_sha(path)
                match._sha = unreadable
                try:
                    profile, inputs, audit = run()
                    assert not profile['materials'][0]['maps'] and not inputs['maps']['0']
                finally:
                    match._sha = original_sha
            outcomes.append('unreadable optional diffuse/control/source evidence safely skipped')

            (assets / 'BrokenDiffuse.dds').write_bytes(b'not an image')
            profile, _, audit = run()
            assert audit[0]['accepted']
            (assets / 'BrokenDiffuse.dds').unlink()
            outcomes.append('corrupt optional image does not block valid match')

            save_pixels(assets / 'AtlasDiffuse.dds', pixels[::-1].copy())
            profile, _, audit = run()
            assert audit[0]['accepted'] and profile['materials'][0]['dds_flip_v'] is True
            outcomes.append('vertical convention inferred from samples')

            shutil.copyfile(assets / 'AtlasDiffuse.dds', assets / 'OtherDiffuse.dds')
            save_pixels(assets / 'OtherLightMap.dds', 1-pixels)
            profile, inputs, audit = run()
            assert not audit[0]['accepted'] and audit[0]['ambiguous_companions']
            assert not profile['materials'][0]['maps'] and not inputs['maps']['0']
            outcomes.append('same albedo with conflicting controls rejected')
            (assets / 'OtherDiffuse.dds').unlink()
            (assets / 'OtherLightMap.dds').unlink()

            rng = np.random.default_rng(5)
            wrong = rng.random((64,64,4)); wrong[:,:,3] = 1
            save_pixels(assets / 'AtlasDiffuse.dds', wrong)
            profile, _, audit = run()
            assert not audit[0]['accepted'] and not profile['materials'][0]['maps']
            outcomes.append('wrong atlas rejected')

            flat = np.ones((64,64,4), dtype=np.float32) * .5; flat[:,:,3] = 1
            save_pixels(source, flat); save_pixels(assets / 'AtlasDiffuse.dds', flat)
            profile, _, audit = run()
            assert not audit[0]['accepted']
            outcomes.append('flat patch cannot certify an atlas')

            known = copy.deepcopy(base_profile); known['uncalibrated'] = False
            before = copy.deepcopy(known)
            assert match.resolve(known, {}, assets) == [] and known == before
            assert match.resolve(base_profile, {}, '') == []
            outcomes.append('known profiles and absent optional assets untouched')
        finally:
            assert root.resolve().is_relative_to(test_root) and root.resolve() != test_root
            shutil.rmtree(root)
    finally:
        pmx.load = original_load
    print(json.dumps({'passed': outcomes}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
