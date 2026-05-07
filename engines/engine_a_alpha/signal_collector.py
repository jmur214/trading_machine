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

        # No recognized method found. Pre-2026-05-07 this returned {} silently,
        # which masked the same typo class as the check_signal/compute_signals
        # bug fixed earlier (project_alpha_diagnosis_2026_04_22.md, F2 in audit
        # health_check.md). A typo'd method name on an edge would silently
        # produce zero signals and therefore zero trades, with the failure
        # invisible under standard logging. Raise loudly instead — the caller's
        # narrowed-except (post-2026-05-07) re-raises AttributeError as a
        # programmer error rather than swallowing it.
        available_methods = sorted(
            m for m in dir(edge_obj)
            if not m.startswith("_") and callable(getattr(edge_obj, m, None))
        )
        # Prefer to flag near-matches that look like typos
        expected_methods = ["compute_signals", "generate_signals", "generate"]
        near_matches = [
            m for m in available_methods
            if any(
                exp in m or m in exp or
                # rough Levenshtein-1 check via prefix overlap
                (len(m) >= 4 and m[:5] == exp[:5])
                for exp in expected_methods
            )
        ]
        hint = ""
        if near_matches:
            hint = (
                f" Found similarly-named methods: {near_matches}. "
                f"Possible typo? Edge interface expects one of "
                f"{expected_methods}."
            )
        raise AttributeError(
            f"SignalCollector: edge {edge_obj!r} has no recognized signal "
            f"method. Searched for: {expected_methods}.{hint}"
        )

    # --- helper for converting various signal formats to ticker->score dict --- #
    def _convert_signals_to_dict(self, signals):
        import pandas as pd

        def extract_score_from_dict(d):
            # Try keys in order: score, signal, or derive from side/confidence
            if not isinstance(d, dict):
                return None
            if "score" in d:
                return d["score"]
            if "signal" in d:
                return d["signal"]
            side = d.get("side")
            confidence = d.get("confidence")
            if side is not None and confidence is not None:
                try:
                    conf = float(confidence)
                    if side in [1, "long", "Long", "LONG"]:
                        return conf
                    elif side in [-1, "short", "Short", "SHORT"]:
                        return -conf
                except Exception:
                    pass
            return None

        # If signals is list of dicts, map to {ticker: score}
        if isinstance(signals, list):
            result = {}
            for item in signals:
                if not isinstance(item, dict):
                    continue
                ticker = item.get("ticker") or item.get("symbol") or item.get("asset")
                if ticker is None:
                    continue
                score = extract_score_from_dict(item)
                if score is not None:
                    result[str(ticker).upper()] = float(score)
            return result

        # If signals is dict, check if values are dicts or primitives
        if isinstance(signals, dict):
            # Check if values are dicts with nested info
            if signals and all(isinstance(v, dict) for v in signals.values()):
                result = {}
                for k, v in signals.items():
                    score = extract_score_from_dict(v)
                    if score is not None:
                        result[str(k).upper()] = float(score)
                return result
            else:
                # Assume dict of ticker->score directly
                try:
                    # Try to convert all values to float
                    result = {str(k).upper(): float(v) for k, v in signals.items()}
                    return result
                except Exception:
                    pass

        # Unsupported type
        if self.debug or os.environ.get("ALPHA_DEBUG"):
            print(f"[ALPHA][TRACE][Collector][WARN] Unsupported signals type: {type(signals)}")
        return None

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

            signals = None
            try:
                try:
                    signals = self._call_edge(edge_obj, data_map, now)  # ticker->score or other format
                except Exception as exc:
                    # Retry with combined DataFrame if error contains "'dict' object has no attribute 'loc'"
                    if "'dict' object has no attribute 'loc'" in str(exc):
                        combined_df = pd.concat(data_map.values(), axis=1)
                        try:
                            signals = self._call_edge(edge_obj, combined_df, now)
                        except Exception as exc2:
                            if self.debug:
                                from debug_config import is_debug_enabled
                                if is_debug_enabled("COLLECTOR"):
                                    print(f"[COLLECTOR][DEBUG] Edge '{edge_name}' failed after retry: {exc2}")
                            signals = None
                    else:
                        raise

                if os.getenv("ALPHA_DEBUG") == "1":
                    print(f"[ALPHA][DEBUG][Collector] Raw signals for edge '{edge_name}':")
                    if isinstance(signals, (dict, list)):
                        if isinstance(signals, dict):
                            for k, v in signals.items():
                                print(f"    key={repr(k)} ({type(k).__name__}), value={repr(v)} ({type(v).__name__})")
                        else:
                            for i, item in enumerate(signals[:3]):
                                print(f"    item[{i}]: {repr(item)}")
                    else:
                        print(f"    [WARN] signals is not a dict or list: {type(signals)}")

                # Convert signals to normalized dict ticker->score
                m = self._convert_signals_to_dict(signals)
                if m is None:
                    if self.debug:
                        from debug_config import is_debug_enabled
                        if is_debug_enabled("COLLECTOR"):
                            print(f"[COLLECTOR][DEBUG] Edge {edge_name} returned unsupported signals type, skipping.")
                    continue

                if self.debug or os.getenv("ALPHA_DEBUG"):
                    sample_items = list(m.items())[:3] if isinstance(m, dict) else []
                    print(f"[ALPHA][TRACE][Collector][RAW_RESULT] Edge '{edge_name}' type={type(m).__name__}, len={len(m) if hasattr(m, '__len__') else 'N/A'} sample={sample_items}")

                if not isinstance(m, dict):
                    if self.debug:
                        from debug_config import is_debug_enabled
                        if is_debug_enabled("COLLECTOR"):
                            print(f"[COLLECTOR][DEBUG] Edge {edge_name} returned non-dict after conversion: {type(m)}")
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
                # Narrowed-catch pattern (2026-05-07, mirrors the gauntlet
                # remediation in project_phase_a_substrate_cleanup_2026_05_07).
                # Programmer errors propagate so a typo'd edge method or
                # missing import fails LOUDLY at startup rather than silently
                # producing zero signals across the whole backtest.
                if isinstance(e, (TypeError, AttributeError, NameError, AssertionError, ImportError)):
                    raise
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