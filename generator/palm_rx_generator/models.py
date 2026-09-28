"""Records the generator creates. Quantities are always in units (tablets, mL, doses)."""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Drug:
    din: str
    brand_name: str
    generic_name: str
    strength: str
    dosage_form: str
    atc_code: str
    group: str
    unit_price: float
    pack_size: int
    doses_per_day: int
    is_narcotic: bool


@dataclass(frozen=True)
class Patient:
    patient_id: str
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    address_line: str
    city: str
    province: str
    postal_code: str
    health_card_number: str
    phone: str
    usual_prescriber_id: str


@dataclass(frozen=True)
class Prescriber:
    prescriber_id: str
    first_name: str
    last_name: str
    license_number: str


@dataclass
class Prescription:
    """One Rx number. Chronic therapies get a new one after a year or on a drug switch."""

    key: int
    start_date: date
    rx_number: int = 0  # assigned once all prescriptions are known, in start-date order


@dataclass
class Fill:
    rx: Prescription
    fill_number: int
    dispense_date: date
    patient_id: str
    prescriber_id: str  # empty for pharmacist-given flu shots
    din: str
    quantity: int
    days_supply: int
    drug_cost: float
    fee: float
    kind: str  # chronic, acute or flu
    therapy_id: int | None = None


@dataclass(frozen=True)
class Snapshot:
    snapshot_date: date
    din: str
    on_hand: int


@dataclass(frozen=True)
class Adjustment:
    adjustment_date: date
    din: str
    quantity: int  # signed: negative removes stock
    reason: str  # expired, damaged, count_correction


@dataclass(frozen=True)
class InvoiceLine:
    invoice_number: str
    invoice_date: date
    supplier: str
    din: str
    packs: int
    quantity: int  # units = packs x pack size
    unit_cost: float
    line_total: float


@dataclass
class StoreData:
    store: dict
    patients: list[Patient]
    prescribers: list[Prescriber]
    fills: list[Fill] = field(default_factory=list)
    snapshots: list[Snapshot] = field(default_factory=list)
    adjustments: list[Adjustment] = field(default_factory=list)
    invoice_lines: list[InvoiceLine] = field(default_factory=list)
