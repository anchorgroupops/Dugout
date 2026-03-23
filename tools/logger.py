import json
import os
from datetime import datetime
from typing import Any, Dict

LOG_FILE = "logs/audit_trail.json"

def log_decision(category: str, input_data: Dict[str, Any], output_data: Dict[str, Any], rationale: str):
    """
    Records a deterministic decision (SWOT/Lineup) for auditability.
    """
    if not os.path.exists("logs"):
        os.makedirs("logs")

    entry = {
        "timestamp": datetime.now().isoformat(),
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
    log_decision("test", {"test": True}, {"result": "success"}, "Initialization test.")
