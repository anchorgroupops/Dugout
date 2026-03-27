import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict

LOG_FILE = "logs/audit_trail.json"
ET = ZoneInfo("America/New_York")

def log_decision(category: str, input_data: Dict[str, Any], output_data: Dict[str, Any], rationale: str):
    """
    Records a deterministic decision (SWOT/Lineup) for auditability.
    Timestamps are forced to America/New_York.
    """
    if not os.path.exists("logs"):
        os.makedirs("logs")

    now_et = datetime.now(ET)

    entry = {
        "timestamp": now_et.isoformat(),
        "category": category,
        "input": input_data,
        "output": output_data,
        "rationale": rationale
    }

    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        else:
            history = []
        
        history.append(entry)
        
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
            
        print(f"[AUDIT] Decision logged to {LOG_FILE}")
    except Exception as e:
        print(f"[AUDIT] Failed to log decision: {e}")

if __name__ == "__main__":
    # Test entry
    log_decision("test", {"test": True}, {"result": "success"}, "Timezone alignment test.")
