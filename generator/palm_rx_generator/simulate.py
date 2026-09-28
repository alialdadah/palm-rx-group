"""Day-by-day simulation of one store: prescriptions, stock, deliveries and adjustments.

Each day runs in a fixed order so the inventory equation always balances:
opening + deliveries - dispensed + adjustments = closing.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from .catalog import by_group
from .models import Adjustment, Drug, Fill, InvoiceLine, Patient, Prescription, Snapshot, StoreData
from .people import age_on

OUTCOMES = ("on_time", "late", "early", "switch", "stop")


@dataclass
class Therapy:
    therapy_id: int
    patient: Patient
    drug: Drug
    days_supply: int
    prescriber_id: str
    odds: tuple  # probabilities in OUTCOMES order
    rx: Prescription
    next_fill_number: int
    active: bool = True


@dataclass
class Request:
    """A fill a patient wants. It waits in line while the drug is out of stock."""

    patient: Patient
    drug: Drug
    days_supply: int
    prescriber_id: str
    kind: str
    therapy: Therapy | None = None
    rx: Prescription | None = None

    @property
    def quantity(self):
        return self.days_supply * self.drug.doses_per_day


def _poisson(mean, rng):
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _days(start, end):
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


class StoreSimulation:
    def __init__(self, store, config, catalog, patients, prescribers, rng):
        self.store = store
        self.config = config
        self.groups = by_group(catalog)
        self.patients = patients
        self.prescribers = prescribers
        self.rng = rng
        self.start = config["start_date"]
        self.end = config["end_date"]
        self.window_days = (self.end - self.start).days + 1
        flu = config["flu"]
        self.season = (flu["season_start"], flu["season_end"])

        self.prescriptions = []
        self.therapies = []
        self.due = defaultdict(list)  # date -> therapies due that day
        self.one_offs = defaultdict(list)  # date -> acute and flu requests
        self.base_rate = defaultdict(float)  # expected units per day, all year
        self.flu_rate = defaultdict(float)  # expected units per day, flu season only
        self.data = StoreData(store=store, patients=patients, prescribers=prescribers)

    # --- planning ------------------------------------------------------------

    def _new_rx(self, start_date):
        rx = Prescription(key=len(self.prescriptions), start_date=start_date)
        self.prescriptions.append(rx)
        return rx

    def _prescriber_for(self, patient):
        if self.rng.random() < self.config["patients"]["usual_prescriber_share"]:
            return patient.usual_prescriber_id
        return self.rng.choice(self.prescribers).prescriber_id

    def _chronic_odds(self, reliability):
        c = self.config["chronic"]
        late = c["late"] * 2 * (1 - reliability)
        stop = c["stop"] * 2 * (1 - reliability)
        early = c["early"] * 2 * reliability
        switch = c["switch"]
        return (1 - late - stop - early - switch, late, early, switch, stop)

    def _plan_chronic(self, patient):
        c = self.config["chronic"]
        age = age_on(patient, self.start)
        band = next(b for b in self.config["patients"]["age_bands"] if b["min"] <= age <= b["max"])
        if self.rng.random() >= band["chronic"]:
            return
        count = self.rng.choices([1, 2, 3], weights=c["therapies_per_patient"])[0]
        weights = dict(c["group_weights"])
        odds = self._chronic_odds(self.rng.random())
        for _ in range(count):
            group = self.rng.choices(list(weights), weights=list(weights.values()))[0]
            del weights[group]
            drug = self.rng.choice(self.groups[group])
            days_supply = 90 if self.rng.random() < c["ninety_day_share"] else 30
            if self.rng.random() < c["already_running_share"]:
                first_due = self.start + timedelta(days=self.rng.randrange(days_supply))
                rx_start = first_due - timedelta(days=self.rng.randrange(c["new_rx_after_days"]))
                prior_fills = (first_due - rx_start).days // days_supply
            else:
                first_due = self.start + timedelta(days=self.rng.randrange(self.window_days))
                rx_start, prior_fills = first_due, 0
            therapy = Therapy(
                therapy_id=len(self.therapies) + 1,
                patient=patient,
                drug=drug,
                days_supply=days_supply,
                prescriber_id=self._prescriber_for(patient),
                odds=odds,
                rx=self._new_rx(rx_start),
                next_fill_number=prior_fills + 1,
            )
            self.therapies.append(therapy)
            self.due[first_due].append(therapy)
            self.base_rate[drug.din] += drug.doses_per_day

    def _plan_acute(self, patient):
        a = self.config["acute"]
        expected = a["fills_per_patient_per_year"] * self.window_days / 365
        for _ in range(_poisson(expected, self.rng)):
            day = self.start + timedelta(days=self.rng.randrange(self.window_days))
            group = self.rng.choices(list(a["group_weights"]), weights=list(a["group_weights"].values()))[0]
            drug = self.rng.choice(self.groups[group])
            request = Request(
                patient=patient,
                drug=drug,
                days_supply=self.rng.choice(a["days_supply"][group]),
                prescriber_id=self._prescriber_for(patient),
                kind="acute",
                rx=self._new_rx(day),
            )
            self.one_offs[day].append(request)
            self.base_rate[drug.din] += request.quantity / self.window_days

    def _plan_flu(self, patient):
        f = self.config["flu"]
        share = f["share_65_plus"] if age_on(patient, f["season_start"]) >= 65 else f["share_under_65"]
        if self.rng.random() >= share:
            return
        length = (f["season_end"] - f["season_start"]).days
        peak = (f["season_peak"] - f["season_start"]).days
        day = f["season_start"] + timedelta(days=int(self.rng.triangular(0, length, peak)))
        if not self.start <= day <= self.end:
            return
        drug = self.rng.choice(self.groups["flu_vaccine"])
        request = Request(patient=patient, drug=drug, days_supply=1, prescriber_id="", kind="flu", rx=self._new_rx(day))
        self.one_offs[day].append(request)
        self.flu_rate[drug.din] += 1 / (length + 1)

    def plan(self):
        for patient in self.patients:
            self._plan_chronic(patient)
            self._plan_acute(patient)
            self._plan_flu(patient)

    # --- running -------------------------------------------------------------

    def _rate(self, din, day):
        in_season = self.season[0] <= day <= self.season[1]
        return self.base_rate.get(din, 0.0) + (self.flu_rate.get(din, 0.0) if in_season else 0.0)

    def _dispense(self, request, day):
        drug, quantity = request.drug, request.quantity
        self.on_hand[drug.din] -= quantity
        pricing = self.config["pricing"]
        if request.kind == "flu":
            drug_cost, fee = 0.0, pricing["injection_fee"]
        else:
            drug_cost = round(quantity * drug.unit_price * (1 + pricing["odb_markup"]), 2)
            fee = pricing["dispensing_fee"]

        therapy = request.therapy
        if therapy:
            rx, fill_number = therapy.rx, therapy.next_fill_number
            therapy.next_fill_number += 1
        else:
            rx, fill_number = request.rx, 1
        self.data.fills.append(
            Fill(
                rx=rx,
                fill_number=fill_number,
                dispense_date=day,
                patient_id=request.patient.patient_id,
                prescriber_id=request.prescriber_id,
                din=drug.din,
                quantity=quantity,
                days_supply=request.days_supply,
                drug_cost=drug_cost,
                fee=fee,
                kind=request.kind,
                therapy_id=therapy.therapy_id if therapy else None,
            )
        )
        if therapy:
            self._schedule_next(therapy, day)

    def _schedule_next(self, therapy, day):
        c = self.config["chronic"]
        outcome = self.rng.choices(OUTCOMES, weights=therapy.odds)[0]
        if outcome == "stop":
            therapy.active = False
            return
        if outcome == "early":
            gap = therapy.days_supply - self.rng.randint(*c["early_days"])
        elif outcome == "late":
            gap = therapy.days_supply + self.rng.randint(*c["late_extra_days"])
        else:
            gap = therapy.days_supply + self.rng.randint(*c["on_time_extra_days"])
        next_due = day + timedelta(days=gap)
        if next_due > self.end:
            return

        if outcome == "switch":
            same_group = self.groups[therapy.drug.group]
            others = [d for d in same_group if d.atc_code != therapy.drug.atc_code] or same_group
            therapy.drug = self.rng.choice(others)
        if outcome == "switch" or (next_due - therapy.rx.start_date).days >= c["new_rx_after_days"]:
            therapy.rx = self._new_rx(next_due)
            therapy.next_fill_number = 1
        self.due[next_due].append(therapy)

    def _receive_deliveries(self, day):
        arriving = [din for din, (when, _) in self.pending.items() if when == day]
        if not arriving:
            return
        p = self.config["purchasing"]
        by_supplier = defaultdict(list)
        for din in arriving:
            drug = self.drugs[din]
            supplier = p["vaccine_supplier"] if drug.group == "flu_vaccine" else p["wholesaler"]
            by_supplier[supplier].append(din)
        for supplier in sorted(by_supplier):
            self.invoice_seq += 1
            number = f"{self.store['id_prefix']}-INV-{self.invoice_seq:06d}"
            for din in sorted(by_supplier[supplier]):
                drug = self.drugs[din]
                packs = self.pending.pop(din)[1]
                quantity = packs * drug.pack_size
                if self.rng.random() < p["above_odb_share"]:
                    factor = self.rng.uniform(*p["above_odb_factor"])
                else:
                    factor = self.rng.uniform(*p["cost_factor"])
                unit_cost = round(drug.unit_price * factor, 4)
                self.on_hand[din] += quantity
                self.data.invoice_lines.append(
                    InvoiceLine(number, day, supplier, din, packs, quantity, unit_cost, round(quantity * unit_cost, 2))
                )

    def _adjust(self, day):
        per_week = self.config["inventory"]["adjustments_per_week"]
        if self.rng.random() >= per_week / 7:
            return
        in_stock = [din for din, qty in self.on_hand.items() if qty > 0]
        if not in_stock:
            return
        din = self.rng.choice(in_stock)
        stock = self.on_hand[din]
        reason = self.rng.choice(["expired", "damaged", "count_correction"])
        if reason == "expired":
            quantity = -self.rng.randint(1, min(stock, 10))
        elif reason == "damaged":
            quantity = -self.rng.randint(1, min(stock, 3))
        else:
            quantity = self.rng.choice([-2, -1, 1, 2])
            if -quantity > stock:
                quantity = -quantity
        self.on_hand[din] += quantity
        self.data.adjustments.append(Adjustment(day, din, quantity, reason))

    def _reorder(self, day, waiting):
        inv = self.config["inventory"]
        shortfall = defaultdict(int)
        for request in waiting:
            shortfall[request.drug.din] += request.quantity
        for din, stock in self.on_hand.items():
            if din in self.pending:
                continue
            rate = self._rate(din, day)
            need = max(0, shortfall[din] - stock)
            if stock >= inv["reorder_below_days"] * rate and not need:
                continue
            target = inv["order_up_to_days"] * rate + shortfall[din]
            if target <= stock:
                continue
            packs = max(1, math.ceil((target - stock) / self.drugs[din].pack_size))
            delay = 2 if self.rng.random() < inv["late_delivery_share"] else 1
            self.pending[din] = (day + timedelta(days=delay), packs)

    def run(self):
        self.plan()
        self.drugs = {d.din: d for group in self.groups.values() for d in group}
        self.on_hand = {}
        self.pending = {}  # din -> (delivery date, packs)
        self.invoice_seq = 0

        opening_days = self.config["inventory"]["opening_days"]
        for din in sorted(set(self.base_rate) | set(self.flu_rate)):
            rate = self._rate(din, self.start)
            if rate > 0:
                pack = self.drugs[din].pack_size
                self.on_hand[din] = max(1, math.ceil(opening_days * rate / pack)) * pack
                self.data.snapshots.append(Snapshot(self.start - timedelta(days=1), din, self.on_hand[din]))

        waiting = []
        for day in _days(self.start, self.end):
            self._receive_deliveries(day)
            requests = waiting
            requests += [
                Request(t.patient, t.drug, t.days_supply, t.prescriber_id, "chronic", therapy=t)
                for t in self.due.pop(day, [])
                if t.active
            ]
            requests += self.one_offs.pop(day, [])
            waiting = []
            for request in requests:
                din = request.drug.din
                self.on_hand.setdefault(din, 0)
                if self.on_hand[din] >= request.quantity:
                    self._dispense(request, day)
                else:
                    waiting.append(request)
            self._adjust(day)
            for din, stock in self.on_hand.items():
                self.data.snapshots.append(Snapshot(day, din, stock))
            self._reorder(day, waiting)

        self._number_prescriptions()
        return self.data

    def _number_prescriptions(self):
        """Rx numbers increase with each prescription's start date, like a real pharmacy system."""
        used = {id(f.rx): f.rx for f in self.data.fills}
        for number, rx in enumerate(sorted(used.values(), key=lambda r: (r.start_date, r.key)), start=100001):
            rx.rx_number = number


def simulate_store(store, config, catalog, patients, prescribers, rng):
    return StoreSimulation(store, config, catalog, patients, prescribers, rng).run()
