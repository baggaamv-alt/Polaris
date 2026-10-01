"""Tunable parameters. These are first guesses from docs/02_ARCHITECTURE.md, not facts.

Every value here is expected to be tuned against the benchmark suite; changes go in docs/DECISIONS.md.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_NETWORK = REPO_ROOT / "docs" / "seed" / "seed_network.yaml"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

SKUS = ["SKU-A", "SKU-B", "SKU-C", "SKU-D", "SKU-E"]
UNIT_VALUE_INR = {"SKU-A": 8000.0, "SKU-B": 40000.0, "SKU-C": 30000.0, "SKU-D": 18000.0, "SKU-E": 12000.0}

# ---------------- world simulator ----------------
WORLD_SEED = 20261001
SIM_START_ISO = "2026-10-12T08:00:00+00:00"
DEFAULT_CLOCK_SPEED = 60.0          # sim seconds per real second
TICK_REAL_S = 0.25
GPS_INTERVAL_S = 15.0               # sim seconds between vehicle reports
WAREHOUSE_INTERVAL_S = 60.0
PORT_INTERVAL_S = 300.0
N_VEHICLES = {"FLEET-A": 60, "FLEET-B": 50, "FLEET-C": 40}
CORRIDOR_SHUTTLES_PER_FLEET = 14    # trucks per fleet that shuttle W-HYD <-> W-VGA
TRUCK_CAPACITY = 40                  # pallets per truck (large multi-axle truck)
INIT_COVER_DAYS = (2.5, 4.5)        # lean network: 2.5-4.5 days of stock per warehouse and SKU
GPS_NOISE_M = 15.0
INVENTORY_NOISE_FRAC = 0.005
BASE_DEMAND_PER_SKU_DAY = 90.0      # units/day for a size-index 1.0 customer cluster
CUSTOMER_SIZE = {
    "C-DEL": 1.0, "C-MUM": 1.0, "C-BLR": 0.8, "C-HYD": 0.7, "C-CHE": 0.7, "C-KOL": 0.7,
    "C-PNQ": 0.5, "C-AMD": 0.5, "C-LKO": 0.4, "C-JAI": 0.35, "C-NAG": 0.3, "C-VGA": 0.3,
    "C-VTZ": 0.3, "C-KOC": 0.3, "C-BHU": 0.25,
}
PORT_IMPORT_SKUS = {"SKU-C": 0.25, "SKU-E": 0.25}   # share of port capacity/day importing these
FACTORY_OUTPUT_SKUS = ["SKU-C", "SKU-D"]
FACTORY_OUTPUT_SHARE = 0.3

# ---------------- trust engine ----------------
TRUST_WEIGHTS = {"schema": 0.10, "physics": 0.20, "kinematic": 0.20, "road": 0.15,
                 "route": 0.15, "temporal": 0.10, "statistical": 0.05, "context": 0.05}
FEED_WEIGHTS = {"schema": 0.10, "physics": 0.20, "reconcile": 0.30, "temporal": 0.10}
HARD_CHECKS = ("physics", "kinematic", "road")
HARD_FAIL_BELOW = 0.20
HARD_CAP = 0.20
TRUSTED_MIN = 0.80
QUARANTINE_BELOW = 0.50
INITIAL_TRUST = 0.85
RECOVERY_STEP = 0.02
COOLDOWN_READINGS = 5
COOLDOWN_SIM_S = 600.0
SPEED_OK_KMH = 100.0
SPEED_HARD_CAP_KMH = 120.0
IMPLIED_OK_KMH = 100.0
IMPLIED_ZERO_KMH = 130.0
ROAD_TOLERANCE_KM = 0.3
ROAD_DECAY_KM = 2.0
ROUTE_DECAY_KM = 1.0
CUSUM_K_KM = 0.2
CUSUM_H1 = 1.5
CUSUM_H2 = 3.0
CUSUM_SOFT_CAP = 0.70
CUSUM_HARD_CAP = 0.45
STALE_EVENT_S = 300.0
INDIA_BBOX = (6.5, 37.5, 68.0, 97.5)   # lat_min, lat_max, lon_min, lon_max

# ---------------- network mode ----------------
FRESH_FACTOR = 3.0
MODE_HYSTERESIS_S = 60.0
MODE_STABILITY_S = 600.0
F_NORMAL = 0.90
C_NORMAL = 0.85
F_BLIND = 0.50

# ---------------- blockage inference ----------------
# statistical check: None = weight only (0.05); a number caps reading trust when the model flags a reading
ANOMALY_SOFT_CAP = None

INF_MIN_VEHICLES = 4
INF_RADIUS_KM = 2.0
INF_MIN_STOP_S = 900.0
INF_STOP_SPEED = 5.0
INF_QUORUM = 3.2
INF_K_INDEPENDENT = 2
INF_MOVING_SPEED = 30.0
INF_CONF_BLOCK = 0.75
INF_CONF_SUSPECT = 0.40
INF_X_FLAG = 0.20
INF_YARD_RADIUS_KM = 3.0           # stops this close to a facility are loading/unloading, not blockages

# ---------------- planning ----------------
PERIOD_H = 6
N_PERIODS = 12
HORIZON_H = PERIOD_H * N_PERIODS
STOCKOUT_PENALTY_FACTOR = 1.5
SAFETY_STOCK_DAYS = 2.0
SAFETY_SLACK_FRACTION = 0.10         # safety-stock shortfall penalty = 10% of unit value per unit-period
CUSTOMER_BUFFER_H = 12.0            # goods already at customer sites at plan start (both LP and engine)
DELAY_COST_PER_UNIT_H = 40.0
CO2_PRICE_PER_KG = 5.0
SOLVER_TIME_LIMIT_S = 5.0
MC_RUNS = 200
MC_DEMAND_SIGMA = 0.08              # 72h aggregate demand uncertainty per run (log-normal sigma)
MC_DELAY_THETA = 0.025              # transit delay multiplier 1 + Gamma(4, theta): mean +10%
MC_DURATION_SIGMA = 0.4             # disruption duration uncertainty (log-normal sigma)
MIN_MEANINGFUL_SAVING = 0.005       # recommend acting only if expected cost falls by >0.5% vs doing nothing
PRESETS = {
    "cheapest":      {"cost": 1.0, "delay": 0.2, "stockout": 1.0, "risk": 0.2, "co2": 0.0},
    "fastest":       {"cost": 0.3, "delay": 1.0, "stockout": 1.0, "risk": 0.3, "co2": 0.0},
    "lowest_carbon": {"cost": 0.4, "delay": 0.2, "stockout": 1.0, "risk": 0.2, "co2": 1.0},
    "lowest_risk":   {"cost": 0.4, "delay": 0.3, "stockout": 1.0, "risk": 1.0, "co2": 0.0},
    "balanced":      {"cost": 0.6, "delay": 0.5, "stockout": 1.0, "risk": 0.6, "co2": 0.3},
}

# =====================================================================================================
# V2 additions. Every value below is a SIMULATED planning assumption, not a live market price.
# =====================================================================================================

# ---------------- shipment priority (derived from SKU class; synthetic rule) ----------------
SKU_PRIORITY = {"SKU-A": "NORMAL", "SKU-B": "CRITICAL", "SKU-C": "HIGH", "SKU-D": "NORMAL", "SKU-E": "NORMAL"}
SKU_CLASS = {"SKU-A": "Packaged food", "SKU-B": "Pharma", "SKU-C": "Electronics", "SKU-D": "Auto parts",
             "SKU-E": "Consumer goods"}
PRIORITY_CODE = {"NORMAL": 3, "HIGH": 2, "CRITICAL": 1}
# route planner: an option is rejected if its ETA exceeds this multiple of the fastest option (SLA proxy)
PRIORITY_DEADLINE_FACTOR = {"NORMAL": None, "HIGH": 1.6, "CRITICAL": 1.25}
PRIORITY_RISK_MULT = {"NORMAL": 1.0, "HIGH": 1.5, "CRITICAL": 2.5}

# ---------------- multimodal cost engine (bottom-up, per shipment) ----------------
PALLET_TONNES = 0.8
COST_MODEL = {
    "road": {"fuel_inr_per_l": 92.0, "km_per_l": 2.5, "toll_inr_per_km": 7.5, "crew_inr_per_h": 220.0,
             "operating_inr_per_km": 18.0, "maintenance_inr_per_km": 5.5, "truck_units": TRUCK_CAPACITY},
    "rail": {"kwh_per_tkm": 0.028, "inr_per_kwh": 8.0, "operating_inr_per_tkm": 1.05,
             "maintenance_inr_per_tkm": 0.12},
    "sea":  {"fuel_l_per_tkm": 0.004, "fuel_inr_per_l": 70.0, "operating_inr_per_tkm": 0.45,
             "maintenance_inr_per_tkm": 0.06},
    # handling when cargo changes mode at a node (INR per tonne, extra hours)
    "transfer": {("road", "rail"): (180.0, 6.0), ("rail", "road"): (180.0, 6.0),
                 ("road", "sea"): (260.0, 12.0), ("sea", "road"): (260.0, 12.0),
                 ("rail", "sea"): (220.0, 10.0), ("sea", "rail"): (220.0, 10.0)},
}
MODE_BASE_RISK = {"road": 0.03, "rail": 0.02, "sea": 0.04}
DIST_PRICE_PER_UNIT_KM = 0.5          # LP distance term (INR per unit-km) when the distance weight is used
WEIGHT_SCALE = 2.5                     # slider share (0..1) -> LP objective weight

# ---------------- resilience index ----------------
RESILIENCE_WEIGHTS = {"route_redundancy": 0.17, "supplier_dependency": 0.11, "warehouse_capacity": 0.09,
                      "recovery_time": 0.11, "disruption_exposure": 0.13, "inventory_buffer": 0.13,
                      "fleet_flexibility": 0.09, "data_reliability": 0.09, "weather_exposure": 0.08}
RESILIENCE_EVERY_S = 60.0              # sim seconds between recomputations
RESILIENCE_BANDS = ((85, "STRONG"), (65, "MODERATE"), (45, "WEAK"), (0, "CRITICAL"))
MC_RUNS_MIN, MC_RUNS_MAX = 50, 500
