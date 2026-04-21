# cockpit/dashboard_v2/utils/styles.py
"""Centralized design system for the Trading Cockpit dashboard."""
from __future__ import annotations

# ============================================
# COLOR PALETTE
# ============================================
COLORS = {
    "bg_primary": "#0a0e14",
    "bg_secondary": "#0f1419",
    "bg_card": "rgba(15, 20, 26, 0.85)",
    "bg_elevated": "rgba(22, 27, 34, 0.9)",
    "bg_input": "rgba(22, 27, 34, 0.7)",
    "border": "rgba(56, 68, 77, 0.4)",
    "border_subtle": "rgba(56, 68, 77, 0.3)",
    "text_primary": "#f0f6fc",
    "text_secondary": "#c9d1d9",
    "text_muted": "#8b949e",
    "text_dim": "#6e7681",
    "accent_blue": "#58a6ff",
    "accent_green": "#3fb950",
    "accent_red": "#f85149",
    "accent_yellow": "#d29922",
    "accent_purple": "#a371f7",
}

# ============================================
# COMPONENT STYLES
# ============================================
CARD_STYLE = {
    "background": COLORS["bg_card"],
    "backdropFilter": "blur(20px)",
    "border": f"1px solid {COLORS['border']}",
    "borderRadius": "16px",
    "padding": "24px",
    "boxShadow": "0 4px 12px rgba(0, 0, 0, 0.4)",
}

CHART_CONTAINER = {
    **CARD_STYLE,
    "padding": "16px",
}

SECTION_HEADER = {
    "display": "flex",
    "alignItems": "center",
    "gap": "12px",
    "marginBottom": "16px",
    "paddingBottom": "12px",
    "borderBottom": f"1px solid {COLORS['border']}",
}

KPI_CARD_STYLE = {
    "background": COLORS["bg_elevated"],
    "border": f"1px solid {COLORS['border']}",
    "borderRadius": "12px",
    "padding": "16px 20px",
    "position": "relative",
    "overflow": "hidden",
    "transition": "all 0.2s ease",
}

BUTTON_PRIMARY = {
    "background": f"linear-gradient(135deg, {COLORS['accent_blue']}, #4090e0)",
    "color": "#ffffff",
    "padding": "10px 20px",
    "border": "none",
    "borderRadius": "10px",
    "cursor": "pointer",
    "fontWeight": "600",
    "fontSize": "13px",
    "transition": "all 0.2s ease",
    "boxShadow": f"0 2px 8px rgba(88, 166, 255, 0.25)",
}

BUTTON_DANGER = {
    "background": "linear-gradient(135deg, #f85149, #d03040)",
    "color": "#ffffff",
    "padding": "10px 20px",
    "border": "none",
    "borderRadius": "10px",
    "cursor": "pointer",
    "fontWeight": "600",
    "fontSize": "13px",
    "transition": "all 0.2s ease",
}

BUTTON_SECONDARY = {
    "background": COLORS["bg_elevated"],
    "color": COLORS["text_secondary"],
    "padding": "10px 20px",
    "border": f"1px solid {COLORS['border']}",
    "borderRadius": "10px",
    "cursor": "pointer",
    "fontWeight": "500",
    "fontSize": "13px",
    "transition": "all 0.2s ease",
}

INPUT_STYLE = {
    "background": COLORS["bg_input"],
    "color": COLORS["text_secondary"],
    "border": f"1px solid {COLORS['border']}",
    "borderRadius": "8px",
    "padding": "8px 12px",
    "fontSize": "13px",
    "width": "100%",
    "outline": "none",
}

TERMINAL_STYLE = {
    "background": "#0d1117",
    "color": COLORS["accent_green"],
    "fontFamily": "'SF Mono', 'Fira Code', 'Consolas', monospace",
    "fontSize": "12px",
    "padding": "16px",
    "borderRadius": "12px",
    "border": f"1px solid {COLORS['border_subtle']}",
    "whiteSpace": "pre-wrap",
    "wordBreak": "break-word",
    "overflowY": "auto",
    "maxHeight": "500px",
    "lineHeight": "1.5",
}

STATUS_BADGE_BASE = {
    "padding": "4px 12px",
    "borderRadius": "20px",
    "fontSize": "11px",
    "fontWeight": "600",
    "letterSpacing": "0.03em",
    "textTransform": "uppercase",
}

TAB_STYLE = {
    "padding": "12px 24px",
    "backgroundColor": COLORS["bg_card"],
    "border": f"1px solid {COLORS['border']}",
    "borderRadius": "10px",
    "color": COLORS["text_muted"],
    "fontWeight": "500",
    "fontSize": "13px",
    "marginRight": "8px",
    "transition": "all 0.25s ease",
}

TAB_SELECTED_STYLE = {
    **TAB_STYLE,
    "background": f"linear-gradient(135deg, rgba(88, 166, 255, 0.15), rgba(88, 166, 255, 0.05))",
    "borderColor": COLORS["accent_blue"],
    "color": COLORS["accent_blue"],
    "boxShadow": "0 0 20px rgba(88, 166, 255, 0.15)",
}

SUB_TAB_STYLE = {
    "padding": "8px 18px",
    "backgroundColor": "transparent",
    "border": f"1px solid {COLORS['border']}",
    "borderRadius": "8px",
    "color": COLORS["text_muted"],
    "fontWeight": "500",
    "fontSize": "12px",
    "marginRight": "6px",
    "transition": "all 0.2s ease",
}

SUB_TAB_SELECTED_STYLE = {
    **SUB_TAB_STYLE,
    "background": f"linear-gradient(135deg, rgba(88, 166, 255, 0.12), rgba(88, 166, 255, 0.04))",
    "borderColor": COLORS["accent_blue"],
    "color": COLORS["accent_blue"],
}

# ============================================
# HELPER FUNCTIONS
# ============================================

def status_badge(status: str) -> dict:
    """Return style dict for a status badge."""
    color_map = {
        "idle": (COLORS["text_muted"], f"rgba(139, 148, 158, 0.15)"),
        "running": (COLORS["accent_blue"], f"rgba(88, 166, 255, 0.15)"),
        "complete": (COLORS["accent_green"], f"rgba(63, 185, 80, 0.15)"),
        "error": (COLORS["accent_red"], f"rgba(248, 81, 73, 0.15)"),
    }
    color, bg = color_map.get(status, color_map["idle"])
    return {**STATUS_BADGE_BASE, "color": color, "background": bg}


def accent_line(color: str) -> dict:
    """Top accent gradient line for cards."""
    return {
        "position": "absolute",
        "top": "0",
        "left": "0",
        "right": "0",
        "height": "3px",
        "background": f"linear-gradient(90deg, {color}, transparent)",
    }
