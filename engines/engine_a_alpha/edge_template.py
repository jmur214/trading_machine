
from typing import Dict, Any, List
import random

class EdgeTemplate:
    """
    Interface for edges that support autonomous parameter generation.
    """
    @classmethod
    def get_hyperparameter_space(cls) -> Dict[str, Any]:
        """
        Returns a dictionary defining the parameter space.
        Example:
        {
            "lookback": {"type": "int", "min": 5, "max": 50},
            "threshold": {"type": "float", "min": 0.5, "max": 3.0}
        }
        """
        raise NotImplementedError

    @classmethod
    def sample_params(cls) -> Dict[str, Any]:
        """
        Generates a valid random parameter set based on the space.
        """
        space = cls.get_hyperparameter_space()
        params = {}
        for name, spec in space.items():
            if isinstance(spec, list):
                # Implicit choice
                params[name] = random.choice(spec)
            elif isinstance(spec, dict):
                if spec["type"] == "int":
                    params[name] = random.randint(spec["min"], spec["max"])
                elif spec["type"] == "float":
                    params[name] = round(random.uniform(spec["min"], spec["max"]), 2)
                elif spec["type"] == "choice":
                    params[name] = random.choice(spec["options"])
        return params
