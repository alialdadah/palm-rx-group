"""Synthetic patients and prescribers. Names and streets come from Faker; nothing is real."""

import string
from datetime import timedelta

from .models import Patient, Prescriber

# Letters Canada Post never uses in postal codes
POSTAL_LETTERS = [c for c in string.ascii_uppercase if c not in "DFIOQU"]


def make_prescribers(store, rng, fake):
    return [
        Prescriber(
            prescriber_id=f"{store['id_prefix']}DR{i:04d}",
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            license_number=str(rng.randint(10000, 99999)),
        )
        for i in range(1, store["prescribers"] + 1)
    ]


def _age(bands, rng):
    band = rng.choices(bands, weights=[b["share"] for b in bands])[0]
    return rng.randint(band["min"], band["max"])


def _postal_code(prefixes, rng):
    return f"{rng.choice(prefixes)} {rng.randint(0, 9)}{rng.choice(POSTAL_LETTERS)}{rng.randint(0, 9)}"


def make_patients(store, config, prescribers, rng, fake):
    settings = config["patients"]
    start = config["start_date"]
    patients = []
    for i in range(1, store["patients"] + 1):
        sex = "F" if rng.random() < settings["female_share"] else "M"
        age = _age(settings["age_bands"], rng)
        birthday = start - timedelta(days=round(age * 365.25) + rng.randint(0, 364))
        patients.append(
            Patient(
                patient_id=f"{store['id_prefix']}{i:06d}",
                first_name=fake.first_name_female() if sex == "F" else fake.first_name_male(),
                last_name=fake.last_name(),
                date_of_birth=birthday,
                sex=sex,
                address_line=fake.street_address(),
                city=store["city"],
                province="ON",
                postal_code=_postal_code(store["postal_prefixes"], rng),
                health_card_number=f"{rng.randint(1_000_000_000, 9_999_999_999)}{rng.choice(string.ascii_uppercase)}{rng.choice(string.ascii_uppercase)}",
                phone=f"{rng.choice(store['area_codes'])}-{rng.randint(200, 999)}-{rng.randint(0, 9999):04d}",
                usual_prescriber_id=rng.choice(prescribers).prescriber_id,
            )
        )
    return patients


def age_on(patient, day):
    years = day.year - patient.date_of_birth.year
    return years - ((day.month, day.day) < (patient.date_of_birth.month, patient.date_of_birth.day))
