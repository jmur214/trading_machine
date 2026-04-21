
import os
import sys
import pandas as pd
from datetime import datetime, time
import logging
import time as time_lib
from pathlib import Path

# Setup paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from engines.engine_d_discovery.discovery import DiscoveryEngine
from scripts.run_evolution_cycle import AutonomousEvolution
from scripts.update_data import update_all_data
from scripts.run_shadow_paper import run_shadow_session
from scripts.harvest_data import harvest
from scripts.train_gate import train_gate_model

# Basic Logger
logging.basicConfig(level=logging.INFO, format='[AUTONOMOUS] %(message)s')
logger = logging.getLogger("AUTO")

def is_market_open():
    """
    Simple check: Mon-Fri, 9:30 AM - 4:00 PM EST.
    """
    now = datetime.now()
    if now.weekday() >= 5: return False # Sat/Sun
    current_time = now.time()
    return time(9, 30) <= current_time <= time(16, 0)

def run_cycle():
    logger.info("--- Starting Autonomous Cycle (Hunt -> Backtest -> Learn -> Exec) ---")
    
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 1. Update Data
    logger.info(">> STEP 1: Updating Data...")
    try:
        update_all_data()
    except Exception as e:
        logger.error(f"Data update failed: {e}")
        
    # 2. The Hunter (Discovery)
    logger.info(">> STEP 2: The Hunter (Pattern Discovery)...")
    try:
        evo = AutonomousEvolution(root_dir)
        discovery = DiscoveryEngine()
        candidates = discovery.hunt(evo.data_map)
        if candidates:
            logger.info(f"Hunter found {len(candidates)} new candidates. Saving to Registry...")
            discovery.save_candidates(candidates)
        else:
            logger.info("Hunter return no new patterns.")
    except Exception as e:
        logger.error(f"Hunter failed: {e}")

    # 3. Validation (Evolution)
    logger.info(">> STEP 3: Backtest Validation (Evolution)...")
    try:
        evo = AutonomousEvolution(root_dir)
        evo.run_cycle(n_candidates=0) 
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        
    # 4. LEARNING (Harvest & Train)
    logger.info(">> STEP 4: Learning (Harvest & Train SignalGate)...")
    try:
        # Harvest data from the backtest/logs we just generated? 
        # Or previous logs. Harvest grabs 'trades.csv'.
        # Since Evolution just ran, it might have updated logs? 
        # Evolution currently runs validation in memory or temp.
        # Ideally we harvest from the *proven* trades or paper trades.
        # For now, we harvest whatever is in trades.csv (Production history).
        harvest()
        train_gate_model()
    except Exception as e:
        # Don't fail the cycle for learning errors, just log
        logger.error(f"Learning failed: {e}")

    # 5. Execution (Shadow/Live)
    logger.info(">> STEP 5: Execution...")
    try:
        # Executes 'active' strategies and monitors 'candidates'
        run_shadow_session()
    except Exception as e:
        logger.error(f"Execution failed: {e}")

    logger.info("--- Cycle Complete ---\n")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--loop":
        logger.info("Entering Infinite Autonomous Loop (Interval: 1 hour)")
        while True:
            run_cycle()
            time_lib.sleep(3600) # Sleep 1 hour
    else:
        run_cycle()
