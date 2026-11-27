"""Add the delivery-time table policy to the frozen Gaia2 window runner."""
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
DESIGN = json.loads((HERE / "protocol.json").read_text())
source = HERE.parent / "delivery-window" / "run.py"
spec = importlib.util.spec_from_file_location("gaia_delivery_window", source)
window = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = window
spec.loader.exec_module(window)

original_delivery_text = window.delivery_text


def delivery_text(pending, current_epoch, arm):
    if arm != "delivery_table":
        return original_delivery_text(pending, current_epoch, arm)
    phase = "replacement" if current_epoch else "initial_order"
    if "product_id" not in DESIGN["delivery_table"][phase]:
        return f"{window.DENIAL} {window.SPEC['denial_feedback']}"
    return f"{window.RECEIPT} product_id={pending.value}"


if __name__ == "__main__":
    window.SPEC = {**window.SPEC, "arms": DESIGN["arms"]}
    window.delivery_text = delivery_text
    window.main()
