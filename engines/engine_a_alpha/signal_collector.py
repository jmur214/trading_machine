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
import os


class SignalCollector:
    def __init__(self, edges: Dict[str, object], debug: bool = False):
        self.edges = dict(edges or {})
        self.debug = bool(debug)

    # --- introspection helpers --- #
    def _call_edge(self, edge_obj: object, data_map: Dict[str, pd.DataFrame], now: pd.Timestamp) -> Dict[str, float]:
        def is_alpha_debug():
            return os.environ.get("ALPHA_DEBUG") or self.debug

        if self.debug:
            from debug_config import is_debug_enabled
            if is_debug_enabled("COLLECTOR"):
                print(f"[COLLECTOR][DEBUG] Attempting edge object: {edge_obj}")

        # 1) function compute_signals(...)
        fn = getattr(edge_obj, "compute_signals", None)
        if callable(fn):
            if self.debug:
                from debug_config import is_debug_enabled
                if is_debug_enabled("COLLECTOR"):
                    print(f"[COLLECTOR][DEBUG] Calling compute_signals() for {edge_obj}")
            result = fn(data_map, now)
            if self.debug:
                from debug_config import is_debug_enabled
                if is_debug_enabled("COLLECTOR"):
                    print(f"[COLLECTOR][DEBUG] Result from compute_signals(): {result}")
            if is_alpha_debug():
                print(f"[ALPHA][TRACE][Collector] compute_signals returned {len(result or {})} entries")
            return dict(result or {})

        # 2) function generate_signals(...)
        gs = getattr(edge_obj, "generate_signals", None)
        if callable(gs):
            if self.debug:
                from debug_config import is_debug_enabled
                if is_debug_enabled("COLLECTOR"):
                    print(f"[COLLECTOR][DEBUG] Calling generate_signals() for {edge_obj}")
            result = gs(data_map, now)
            if self.debug:
                from debug_config import is_debug_enabled
                if is_debug_enabled("COLLECTOR"):
                    print(f"[COLLECTOR][DEBUG] Result from generate_signals(): {result}")
            if is_alpha_debug():
                print(f"[ALPHA][TRACE][Collector] generate_signals returned {len(result or {})} entries")
            return dict(result or {})

        # 3) function generate(...)
        gn = getattr(edge_obj, "generate", None)
        if callable(gn):
            if self.debug:
                from debug_config import is_debug_enabled
                if is_debug_enabled("COLLECTOR"):
                    print(f"[COLLECTOR][DEBUG] Calling generate() for {edge_obj}")
            result = gn(data_map, now)
            if self.debug:
                from debug_config import is_debug_enabled
                if is_debug_enabled("COLLECTOR"):
                    print(f"[COLLECTOR][DEBUG] Result from generate(): {result}")
            if is_alpha_debug():
                print(f"[ALPHA][TRACE][Collector] generate returned {len(result or {})} entries")
            return dict(result or {})

        # 4) class Edge(...).compute_signals(...)
        if inspect.isclass(edge_obj):
            try:
                if self.debug:
                    from debug_config import is_debug_enabled
                    if is_debug_enabled("COLLECTOR"):
                            print(f"[COLLECTOR][DEBUG] Instantiating edge class {edge_obj}")
                inst = edge_obj()  # no-arg ctor
                m = getattr(inst, "compute_signals", None)
                if callable(m):
                    if self.debug:
                        from debug_config import is_debug_enabled
                        if is_debug_enabled("COLLECTOR"):
                            print(f"[COLLECTOR][DEBUG] Calling class.compute_signals() for {edge_obj}")
                    result = m(data_map, now)
                    if self.debug:
                        from debug_config import is_debug_enabled
                        if is_debug_enabled("COLLECTOR"):
                            print(f"[COLLECTOR][DEBUG] Result from class.compute_signals(): {result}")
                    if is_alpha_debug():
                        print(f"[ALPHA][TRACE][Collector] class.compute_signals returned {len(result or {})} entries")
                    return dict(result or {})
            except Exception as inst_err:
                if self.debug:
                    from debug_config import is_debug_enabled
                    if is_debug_enabled("COLLECTOR"):
                        print(f"[COLLECTOR][DEBUG] Failed to instantiate edge class {edge_obj}: {inst_err}")

        if self.debug:
            from debug_config import is_debug_enabled
            if is_debug_enabled("COLLECTOR"):
                print(f"[COLLECTOR][DEBUG] Edge {edge_obj} not supported — no recognized function found.")
        return {}

    # --- public --- #
    def collect(self, data_map: Dict[str, pd.DataFrame], now: pd.Timestamp) -> Dict[str, Dict[str, float]]:
        """
        Returns:
            scores[ticker][edge_name] = raw_score (float)
        """
        scores: Dict[str, Dict[str, float]] = {}

        import re
        # Broaden pattern to accept uppercase letters, digits, dots, dashes; case insensitive handled by upper()
        ticker_pattern = re.compile(r"^[A-Z0-9.\-]{1,12}$")

        for edge_name, edge_obj in self.edges.items():
            if self.debug:
                from debug_config import is_debug_enabled
                if is_debug_enabled("COLLECTOR"):
                    print(f"[COLLECTOR][DEBUG] Executing edge: {edge_name}")

            # --- DEBUG: Print all raw signals (keys/values/types) if ALPHA_DEBUG is set ---
            signals = None
            try:
                signals = self._call_edge(edge_obj, data_map, now)  # ticker->score
                if os.getenv("ALPHA_DEBUG") == "1":
                    print(f"[ALPHA][DEBUG][Collector] Raw signals for edge '{edge_name}':")
                    if isinstance(signals, dict):
                        for k, v in signals.items():
                            print(f"    key={repr(k)} ({type(k).__name__}), value={repr(v)} ({type(v).__name__})")
                    else:
                        print(f"    [WARN] signals is not a dict: {type(signals)}")

                m = signals
                if self.debug or os.getenv("ALPHA_DEBUG"):
                    sample_items = list(m.items())[:3] if isinstance(m, dict) else []
                    print(f"[ALPHA][TRACE][Collector][RAW_RESULT] Edge '{edge_name}' type={type(m).__name__}, len={len(m) if hasattr(m, '__len__') else 'N/A'} sample={sample_items}")

                if not isinstance(m, dict):
                    if self.debug:
                        from debug_config import is_debug_enabled
                        if is_debug_enabled("COLLECTOR"):
                            print(f"[COLLECTOR][DEBUG] Edge {edge_name} returned non-dict: {type(m)}")
                    continue

                # --- Insert debug block to print raw keys in m if debug or ALPHA_DEBUG ---
                if self.debug or os.getenv("ALPHA_DEBUG"):
                    raw_keys = list(m.keys())
                    print(f"[ALPHA][TRACE][Collector] Edge '{edge_name}' raw keys: {raw_keys}")

                # --- Improved normalization for keys (tuple, MultiIndex, etc.) ---
                normalized_values = {}
                tuple_patterns = set()
                normalized_tickers = set()

                skip_invalid_pattern = 0
                skip_non_numeric = 0
                skip_non_finite = 0
                kept_entries = 0

                for key, val in m.items():
                    ticker = None
                    # Handle tuple key (e.g., MultiIndex) by flattening to first ticker-like part
                    if isinstance(key, tuple):
                        found = False
                        for part in key:
                            part_str = str(part).strip()
                            part_str_upper = part_str.upper()
                            if ticker_pattern.match(part_str_upper):
                                ticker = part_str_upper
                                found = True
                                break
                        if not found:
                            # fallback: join all parts as string uppercased
                            ticker = "".join(str(p).upper() for p in key)
                        tuple_patterns.add(key)
                        if self.debug or os.environ.get("ALPHA_DEBUG"):
                            print(f"[ALPHA][TRACE][Collector] Normalized tuple {key} -> '{ticker}'")
                    elif isinstance(key, str):
                        ticker = key.strip().upper()
                    else:
                        # fallback: str conversion uppercased
                        ticker = str(key).upper()

                    # Only keep tickers matching pattern or fallback if no match at all
                    if not ticker or not ticker_pattern.match(ticker):
                        if self.debug or os.environ.get("ALPHA_DEBUG"):
                            print(f"[ALPHA][TRACE][Collector][SKIP] Invalid ticker pattern: key={key}, normalized={ticker}")
                        skip_invalid_pattern += 1
                        continue

                    # Store val if numeric and finite
                    try:
                        fval = float(val)
                    except Exception:
                        if self.debug or os.environ.get("ALPHA_DEBUG"):
                            print(f"[ALPHA][TRACE][Collector][SKIP] Non-numeric value: key={key}, value={val}")
                        skip_non_numeric += 1
                        continue

                    if not pd.notna(fval) or not (abs(fval) < float("inf")):
                        if self.debug or os.environ.get("ALPHA_DEBUG"):
                            print(f"[ALPHA][TRACE][Collector][SKIP] Non-finite numeric: key={key}, value={val}")
                        skip_non_finite += 1
                        continue

                    normalized_values.setdefault(ticker, []).append(fval)
                    normalized_tickers.add(ticker)
                    kept_entries += 1

                if self.debug or os.environ.get("ALPHA_DEBUG"):
                    print(f"[ALPHA][TRACE][Collector][SUMMARY] Edge '{edge_name}' skips: pattern={skip_invalid_pattern}, non_numeric={skip_non_numeric}, non_finite={skip_non_finite}, kept={kept_entries}")

                # Average values per ticker (in case of duplicates from tuple keys)
                averaged = {tkr: sum(vals) / len(vals) for tkr, vals in normalized_values.items() if vals}

                # Map normalized tickers to edge_name and values
                for tkr, val in averaged.items():
                    scores.setdefault(tkr, {})
                    scores[tkr][edge_name] = val

                if (self.debug or os.environ.get("ALPHA_DEBUG")) and normalized_tickers:
                    print(f"[ALPHA][TRACE][Collector] Edge '{edge_name}' normalized tickers: {sorted(normalized_tickers)}")
                if (self.debug or os.environ.get("ALPHA_DEBUG")) and tuple_patterns:
                    patterns_str = ", ".join(str(p) for p in tuple_patterns)
                    print(f"[ALPHA][TRACE][Collector] Edge '{edge_name}' tuple key patterns: {patterns_str}")

                if not averaged and self.debug:
                    from debug_config import is_debug_enabled
                    if is_debug_enabled("COLLECTOR"):
                        print(f"[COLLECTOR][DEBUG] Edge {edge_name} returned empty result after normalization")

            except Exception as e:
                if self.debug:
                    from debug_config import is_debug_enabled
                    if is_debug_enabled("COLLECTOR"):
                        print(f"[COLLECTOR][DEBUG] Edge '{edge_name}' failed: {e}")

        if self.debug or os.environ.get("ALPHA_DEBUG"):
            num_tickers = len(scores)
            sample_entries = []
            for tkr, edges_dict in list(scores.items())[:2]:
                for ename, val in list(edges_dict.items())[:2]:
                    sample_entries.append(f"{tkr}:{ename}={val}")
            sample_str = ", ".join(sample_entries)
            print(f"[ALPHA][TRACE][Collector] Finished collection. tickers={num_tickers} edges={list(self.edges.keys())} normalized sample={sample_str}")

        return scores