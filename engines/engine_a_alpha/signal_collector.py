# engines/engine_a_alpha/signal_collector.py
"""
SignalCollector
---------------

Calls each active edge module to obtain raw (unnormalized) scores per ticker.

Edge module conventions supported (first match wins):
- function compute_signals(data_map: Dict[str, DataFrame], now: Timestamp) -> Dict[str, float]
- function generate_signals(data_map: Dict[str, DataFrame], now: Timestamp) -> Dict[str, float]
- function generate(data_map: Dict[str, DataFrame], now: Timestamp) -> Dict[str, float]
- class Edge with method compute_signals(self, data_map, now)

Returned values may be any real number; downstream will normalize/clamp.
"""

from __future__ import annotations
from typing import Dict
import inspect
import pandas as pd


class SignalCollector:
    def __init__(self, edges: Dict[str, object], debug: bool = False):
        self.edges = dict(edges or {})
        self.debug = bool(debug)

    # --- introspection helpers --- #
    def _call_edge(self, edge_obj: object, data_map: Dict[str, pd.DataFrame], now: pd.Timestamp) -> Dict[str, float]:
        if self.debug:
            print(f"[COLLECTOR][DEBUG] Attempting edge object: {edge_obj}")

        # 1) function compute_signals(...)
        fn = getattr(edge_obj, "compute_signals", None)
        if callable(fn):
            if self.debug:
                print(f"[COLLECTOR][DEBUG] Calling compute_signals() for {edge_obj}")
            result = fn(data_map, now)
            if self.debug:
                print(f"[COLLECTOR][DEBUG] Result from compute_signals(): {result}")
            return dict(result or {})

        # 2) function generate_signals(...)
        gs = getattr(edge_obj, "generate_signals", None)
        if callable(gs):
            if self.debug:
                print(f"[COLLECTOR][DEBUG] Calling generate_signals() for {edge_obj}")
            result = gs(data_map, now)
            if self.debug:
                print(f"[COLLECTOR][DEBUG] Result from generate_signals(): {result}")
            return dict(result or {})

        # 3) function generate(...)
        gn = getattr(edge_obj, "generate", None)
        if callable(gn):
            if self.debug:
                print(f"[COLLECTOR][DEBUG] Calling generate() for {edge_obj}")
            result = gn(data_map, now)
            if self.debug:
                print(f"[COLLECTOR][DEBUG] Result from generate(): {result}")
            return dict(result or {})

        # 4) class Edge(...).compute_signals(...)
        if inspect.isclass(edge_obj):
            try:
                if self.debug:
                    print(f"[COLLECTOR][DEBUG] Instantiating edge class {edge_obj}")
                inst = edge_obj()  # no-arg ctor
                m = getattr(inst, "compute_signals", None)
                if callable(m):
                    if self.debug:
                        print(f"[COLLECTOR][DEBUG] Calling class.compute_signals() for {edge_obj}")
                    result = m(data_map, now)
                    if self.debug:
                        print(f"[COLLECTOR][DEBUG] Result from class.compute_signals(): {result}")
                    return dict(result or {})
            except Exception as inst_err:
                if self.debug:
                    print(f"[COLLECTOR][DEBUG] Failed to instantiate edge class {edge_obj}: {inst_err}")

        if self.debug:
            print(f"[COLLECTOR][DEBUG] Edge {edge_obj} not supported — no recognized function found.")
        return {}

    # --- public --- #
    def collect(self, data_map: Dict[str, pd.DataFrame], now: pd.Timestamp) -> Dict[str, Dict[str, float]]:
        """
        Returns:
            scores[ticker][edge_name] = raw_score (float)
        """
        scores: Dict[str, Dict[str, float]] = {}

        for edge_name, edge_obj in self.edges.items():
            if self.debug:
                print(f"[COLLECTOR][DEBUG] Executing edge: {edge_name}")

            try:
                m = self._call_edge(edge_obj, data_map, now)  # ticker->score

                if not isinstance(m, dict):
                    if self.debug:
                        print(f"[COLLECTOR][DEBUG] Edge {edge_name} returned non-dict: {type(m)}")
                    continue

                if not m and self.debug:
                    print(f"[COLLECTOR][DEBUG] Edge {edge_name} returned empty result")

                for tkr, val in m.items():
                    scores.setdefault(tkr, {})
                    try:
                        scores[tkr][edge_name] = float(val)
                    except Exception as conv_err:
                        if self.debug:
                            print(f"[COLLECTOR][DEBUG] Edge {edge_name} bad value for {tkr}: {val} ({conv_err})")
                        continue

            except Exception as e:
                if self.debug:
                    print(f"[COLLECTOR][DEBUG] Edge '{edge_name}' failed: {e}")

        return scores