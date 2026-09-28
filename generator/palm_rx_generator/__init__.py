"""Synthetic pharmacy data for Palm Rx Group's stores. See generator/config.toml for settings."""

import random
import shutil

from faker import Faker

from .export import assign_item_codes, write_store_a, write_store_b
from .people import make_patients, make_prescribers
from .simulate import simulate_store


def generate(config, catalog, out_dir):
    """Simulate every store in the config and write its files under out_dir/<store id>/.

    Returns {store id: StoreData} so callers (and tests) can inspect what was written.
    """
    results = {}
    for index, store in enumerate(config["stores"]):
        # Each store gets its own random streams, so changing one store never changes another.
        rng = random.Random(f"{config['seed']}-{store['id']}")
        fake = Faker("en_CA")
        fake.seed_instance(config["seed"] * 100 + index)

        prescribers = make_prescribers(store, rng, fake)
        patients = make_patients(store, config, prescribers, rng, fake)
        data = simulate_store(store, config, catalog, patients, prescribers, rng)

        folder = out_dir / store["id"]
        if folder.exists():
            shutil.rmtree(folder)  # no stale months left over from an earlier run
        folder.mkdir(parents=True)
        if store["export_format"] == "a":
            write_store_a(data, catalog, folder)
        else:
            item_codes = assign_item_codes(catalog, random.Random(f"{config['seed']}-{store['id']}-items"))
            write_store_b(data, catalog, folder, item_codes)
        results[store["id"]] = data
    return results
