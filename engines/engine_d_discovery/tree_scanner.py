
import pandas as pd
import numpy as np
import logging
from typing import List, Dict, Any, Optional, Tuple
from sklearn.tree import DecisionTreeClassifier, _tree
from sklearn.model_selection import TimeSeriesSplit

logger = logging.getLogger("TREE_SCANNER")


class DecisionTreeScanner:
    """
    Tier 2 Research: The Hunter.

    Responsibilities:
    -----------------
    1. Label Data: Create multi-class targets (vol-adjusted thresholds).
    2. Screen: Use gradient boosted trees to identify top features.
    3. Scan: Fit a shallow decision tree on screened features for rule extraction.
    4. Extract: Convert tree paths into human/machine readable rules.

    Two-stage ML pipeline:
      Stage 1 — GBT (LightGBM or sklearn fallback) for feature importance screening.
      Stage 2 — Shallow DecisionTree on top-K features for interpretable rule extraction.
    """

    LABEL_MAP = {
        2: "EXPLODE",
        1: "BULLISH",
        0: "STABLE",
        -1: "BEARISH",
        -2: "CRASH"
    }

    def __init__(
        self,
        max_depth: int = 4,
        min_samples_leaf: int = 50,
        min_prob: float = 0.60,
        top_k_features: int = 10,
        n_cv_splits: int = 5,
        vol_adjusted_targets: bool = True,
    ):
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.min_prob = min_prob
        self.top_k_features = top_k_features
        self.n_cv_splits = n_cv_splits
        self.vol_adjusted_targets = vol_adjusted_targets
        self.model = None
        self.screener_model = None
        self.feature_names = []
        self.screened_features = []
        self.cv_score = None  # cross-validated accuracy
        self.feature_importances = {}  # feature -> importance score

    def generate_targets(self, df: pd.DataFrame, lookahead_days: int = 3) -> pd.DataFrame:
        """
        Generate multi-class targets based on future returns.

        If vol_adjusted_targets is True, thresholds are scaled by rolling ATR%
        so that a 5% move in a low-vol stock (KO) is treated differently from
        a 5% move in a high-vol stock (TSLA).

        Labels:
            2 (EXPLODE): > +k_explode * ATR_pct
            1 (BULLISH): > +k_bullish * ATR_pct
            0 (STABLE):  within +/- k_bullish * ATR_pct
           -1 (BEARISH): < -k_bullish * ATR_pct
           -2 (CRASH):   < -k_explode * ATR_pct
        """
        df = df.copy()

        df["Future_Close"] = df["Close"].shift(-lookahead_days)
        df["Future_Ret"] = (df["Future_Close"] / df["Close"]) - 1.0

        if self.vol_adjusted_targets and "ATR_Pct" in df.columns:
            # Vol-adjusted thresholds per bar
            atr_pct = df["ATR_Pct"].clip(lower=0.005)  # floor to avoid near-zero
            k_explode = 2.0
            k_bullish = 0.5

            thresh_explode = k_explode * atr_pct
            thresh_bullish = k_bullish * atr_pct

            conditions = [
                df["Future_Ret"] > thresh_explode,
                df["Future_Ret"] > thresh_bullish,
                df["Future_Ret"] >= -thresh_bullish,
                df["Future_Ret"] > -thresh_explode,
            ]
            choices = [2, 1, 0, -1]
            df["Target"] = np.select(conditions, choices, default=-2)
            # NaN where Future_Ret is NaN
            df.loc[df["Future_Ret"].isna(), "Target"] = np.nan
        else:
            # Fixed thresholds (legacy behavior)
            def assign_label(ret):
                if pd.isna(ret):
                    return np.nan
                if ret > 0.05:
                    return 2
                if ret > 0.01:
                    return 1
                if ret >= -0.01:
                    return 0
                if ret > -0.05:
                    return -1
                return -2

            df["Target"] = df["Future_Ret"].apply(assign_label)

        return df

    def scan(self, feature_df: pd.DataFrame, target_col: str = "Target") -> List[Dict[str, Any]]:
        """
        Two-stage scanning pipeline:
        1. Prepare features (drop absolute columns, clean NaNs).
        2. Stage 1: GBT feature screening with time-series cross-validation.
        3. Stage 2: Shallow decision tree on top-K features for rule extraction.
        """
        if feature_df.empty or target_col not in feature_df.columns:
            logger.warning("[TreeScanner] No data or missing Target column.")
            return []

        # 1. Preparation
        data = feature_df.dropna(subset=[target_col]).copy()

        drop_cols = [
            target_col, "Future_Close", "Future_Ret", "Date", "ticker", "symbol",
            "Open", "High", "Low", "Close", "Volume", "trade_count", "vwap"
        ]

        valid_cols = [
            c for c in data.columns
            if c not in drop_cols and pd.api.types.is_numeric_dtype(data[c])
        ]

        X = data[valid_cols].dropna()
        y = data.loc[X.index, target_col]

        if X.empty or y.empty:
            logger.warning("[TreeScanner] X or y is empty after cleaning.")
            return []

        if len(X) < self.min_samples_leaf * 2:
            logger.warning(
                f"[TreeScanner] Not enough samples ({len(X)}) for robust tree "
                f"(need {self.min_samples_leaf * 2})."
            )
            return []

        all_features = X.columns.tolist()

        # 2. Stage 1: GBT feature importance screening with time-series CV
        screened_features = self._screen_features(X, y, all_features)
        self.screened_features = screened_features

        if not screened_features:
            logger.warning("[TreeScanner] No features survived screening.")
            return []

        # 3. Stage 2: Shallow decision tree on screened features
        X_screened = X[screened_features]
        self.feature_names = screened_features

        self.model = DecisionTreeClassifier(
            criterion="entropy",
            max_depth=self.max_depth,
            min_samples_leaf=self.min_samples_leaf,
            random_state=42,
            class_weight="balanced",
        )

        try:
            self.model.fit(X_screened, y)
        except Exception as e:
            logger.error(f"[TreeScanner] Decision tree fit failed: {e}")
            return []

        # 4. Extract Rules
        rules = self._extract_rules()
        logger.info(
            f"[TreeScanner] Discovered {len(rules)} rules from {len(screened_features)} "
            f"screened features (CV accuracy: {self.cv_score:.3f})."
        )
        return rules

    def _screen_features(
        self, X: pd.DataFrame, y: pd.Series, all_features: List[str]
    ) -> List[str]:
        """
        Stage 1: Fit a gradient boosted classifier to rank features by importance.
        Uses time-series cross-validation with purge gap for honest accuracy.
        Falls back to sklearn GradientBoostingClassifier if LightGBM is unavailable.
        """
        n_features = min(self.top_k_features, len(all_features))

        # Try LightGBM first, fall back to sklearn
        try:
            import lightgbm as lgb
            screener = lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                class_weight="balanced",
                random_state=42,
                verbosity=-1,
                n_jobs=1,
            )
            screener_name = "LightGBM"
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier
            screener = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.05,
                random_state=42,
            )
            screener_name = "sklearn.GradientBoosting"

        logger.info(f"[TreeScanner] Stage 1 screening with {screener_name}...")

        # Time-series cross-validation with purge gap
        cv_scores = []
        n_splits = min(self.n_cv_splits, len(X) // 200)  # need enough data per fold
        if n_splits < 2:
            # Not enough data for CV — fit on everything, report no CV score
            logger.warning("[TreeScanner] Not enough data for time-series CV. Fitting on full dataset.")
            try:
                screener.fit(X, y)
            except Exception as e:
                logger.error(f"[TreeScanner] Screener fit failed: {e}")
                return all_features[:n_features]

            self.cv_score = 0.0
        else:
            tscv = TimeSeriesSplit(n_splits=n_splits, gap=6)  # 6-bar purge gap (2x lookahead)

            for train_idx, test_idx in tscv.split(X):
                X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
                y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

                try:
                    screener.fit(X_train, y_train)
                    score = screener.score(X_test, y_test)
                    cv_scores.append(score)
                except Exception:
                    pass

            self.cv_score = float(np.mean(cv_scores)) if cv_scores else 0.0

            # Final fit on full data for feature importances
            try:
                screener.fit(X, y)
            except Exception as e:
                logger.error(f"[TreeScanner] Final screener fit failed: {e}")
                return all_features[:n_features]

        self.screener_model = screener

        # Extract feature importances
        importances = screener.feature_importances_
        feat_imp = dict(zip(all_features, importances))
        self.feature_importances = feat_imp

        # Select top-K features
        sorted_features = sorted(feat_imp.items(), key=lambda x: x[1], reverse=True)
        top_features = [f for f, _ in sorted_features[:n_features]]

        logger.info(
            f"[TreeScanner] Top {n_features} features: "
            + ", ".join(f"{f}({imp:.3f})" for f, imp in sorted_features[:n_features])
        )

        return top_features

    def _extract_rules(self) -> List[Dict[str, Any]]:
        """
        Recursively traverse the decision tree to find high-probability leaf nodes.
        """
        if not self.model:
            return []

        tree_ = self.model.tree_
        feature_names = self.feature_names
        classes = self.model.classes_

        discovered_rules = []

        def recurse(node: int, current_rule: List[str]):
            # IF LEAF NODE
            if tree_.feature[node] == _tree.TREE_UNDEFINED:
                counts = tree_.value[node][0]
                total_samples = counts.sum()

                if total_samples == 0:
                    return

                probs = counts / total_samples

                best_class_idx = np.argmax(probs)
                best_class_prob = probs[best_class_idx]
                best_class_label = classes[best_class_idx]

                # Skip stable (0)
                if best_class_label == 0:
                    return

                if best_class_prob >= self.min_prob:
                    human_label = self.LABEL_MAP.get(best_class_label, str(best_class_label))

                    rule_entry = {
                        "rule_string": " AND ".join(current_rule),
                        "target_class": int(best_class_label),
                        "target_name": human_label,
                        "probability": float(best_class_prob),
                        "samples": int(total_samples),
                        "logic_map": current_rule,
                        "cv_score": self.cv_score,
                    }
                    discovered_rules.append(rule_entry)
                return

            # IF DECISION NODE
            name = feature_names[tree_.feature[node]]
            threshold = tree_.threshold[node]

            recurse(tree_.children_left[node], current_rule + [f"{name} <= {threshold:.4f}"])
            recurse(tree_.children_right[node], current_rule + [f"{name} > {threshold:.4f}"])

        recurse(0, [])
        return discovered_rules


if __name__ == "__main__":
    # POC Test
    print("Testing Tree Scanner...")

    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=1000)
    df = pd.DataFrame(index=dates)
    df["Close"] = np.random.normal(100, 2, 1000).cumsum() + 100
    df["Open"] = df["Close"] + np.random.normal(0, 0.5, 1000)
    df["High"] = df[["Open", "Close"]].max(axis=1) + abs(np.random.normal(0, 1, 1000))
    df["Low"] = df[["Open", "Close"]].min(axis=1) - abs(np.random.normal(0, 1, 1000))
    df["Volume"] = np.random.randint(1000, 10000, 1000)
    df["RSI"] = np.random.uniform(20, 80, 1000)
    df["Volume_Z"] = np.random.normal(0, 1, 1000)
    df["ATR_Pct"] = 0.02  # constant for test

    mask = (df["RSI"] < 35) & (df["Volume_Z"] > 0.5)
    df["Future_Close"] = df["Close"]
    df["Future_Ret"] = np.random.normal(0, 0.02, 1000)
    df.loc[mask, "Future_Ret"] = np.random.normal(0.08, 0.01, sum(mask))

    scanner = DecisionTreeScanner(max_depth=3, min_prob=0.5, vol_adjusted_targets=False)

    def simple_label(ret):
        if ret > 0.05:
            return 2
        return 0
    df["Target"] = df["Future_Ret"].apply(simple_label)

    print(f"Explosion Cases: {len(df[df['Target'] == 2])}")

    rules = scanner.scan(df)

    print("\n--- Discovered Rules ---")
    for r in rules:
        print(f"Target: {r['target_name']} | Prob: {r['probability']:.2%} | Samples: {r['samples']}")
        print(f"  Rule: {r['rule_string']}")
    print(f"\nCV Score: {scanner.cv_score}")
    print(f"Screened features: {scanner.screened_features}")
