# debug_config.py
# Global debug settings for all modules

DEBUG_LEVELS = {
    "ALPHA": False,
    "ALPHA_INFO": False,
    "BACKTEST_CONTROLLER": False,
    "BACKTEST_CONTROLLER_INFO": False,
    "COLLECTOR": False,
    "DATA_MANAGER": False,
    "DATA_MANAGER_INFO": False,
    "EDGE": False,
    "EDGE_INFO": False,
    "EDGE_DB": False,
    "EDGE_DB_INFO": False,
    "EXEC": False,
    "EXEC_INFO": False,
    "HARNESS": False,
    "HARNESS_INFO": False,
    "LOGGER": False,
    "LOGGER_INFO": False,
    "NEWS_EDGE": False,
    "PROMOTE": False,
    "PROMOTE_INFO": False,
    "RISK": False,
    "RISK_INFO": False,
    "TEST_EDGE": False,
    "TEST_EDGE_INFO": False
}

# Global toggle to fully enable or disable CockpitLogger
LOGGER_ENABLED = True  # Set to False to silence all trade/snapshot logging

def is_debug_enabled(section: str) -> bool:
    """
    Check if debugging is enabled for a given section.
    Example: if is_debug_enabled("ALPHA"): print("debug message")
    """
    return DEBUG_LEVELS.get(section.upper(), False)

def is_info_enabled(section: str) -> bool:
    """
    Check if info-level logging is enabled for a given section.
    Example: if is_info_enabled("ALPHA"): print("info message")
    """
    return DEBUG_LEVELS.get(f"{section.upper()}_INFO", False)