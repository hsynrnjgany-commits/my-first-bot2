# MARI — بارگذار بستهٔ fleet برای آزمون‌های آفلاین (کمک‌آزمون؛ خودش آزمون نیست)
# الگوی Stage 1: هیچ نصب/شبکه‌ای لازم نیست؛ بسته با importlib از مسیر بار می‌شود.

import importlib
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLEET_DIR = os.path.join(ROOT, "src", "fleet")
PKG_NAME = "mari_fleet"

SUBMODULES = (
    "contract", "sources", "integrity", "structure", "volume", "liquidity",
    "sessions", "derivatives", "crossmarket", "risk", "evaluator",
    "orchestrator", "quant", "scan", "onchain", "strategy_lab", "cost_model",
    "vol_target", "unified_report",
)


def load_fleet():
    if PKG_NAME in sys.modules:
        return sys.modules[PKG_NAME]
    spec = importlib.util.spec_from_file_location(
        PKG_NAME, os.path.join(FLEET_DIR, "__init__.py"),
        submodule_search_locations=[FLEET_DIR])
    package = importlib.util.module_from_spec(spec)
    sys.modules[PKG_NAME] = package
    spec.loader.exec_module(package)
    for name in SUBMODULES:
        module = importlib.import_module(f"{PKG_NAME}.{name}")
        setattr(package, name, module)
    return package
