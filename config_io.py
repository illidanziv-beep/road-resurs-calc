# config_io.py
# -*- coding: utf-8 -*-
"""
Модуль сохранения и загрузки конфигурации расчёта.
"""

import json
from datetime import datetime
import pandas as pd


SCALAR_KEYS = [
    "road_category_input", "design_load", "design_life", "num_lanes",
    "q_growth_percent", "trdg",
    "use_project_np", "project_np_input",
    "current_iri", "years_in_operation",
    "use_gost_iri", "iri_limit_input",
    "road_type_input", "kpr_tr_input", "kpr_input_method",
    "kpr_fact_input", "e_fact_input", "e_tr_input",
    "iri_0_input", "base_type_input", "coef_a_input", "coef_b_input",
    "forecast_years_input", "lane_share_input",
    "sm_method", "p_empty", "p_loaded", "p_overload", "speed_input",
    "classification", "type_column_name",
    "vehicle_masses",
]


def save_config_to_json():
    import streamlit as st
    config = {
        "_meta": {
            "version": "1.0",
            "saved_at": datetime.now().isoformat(),
            "description": "Конфигурация расчёта остаточного ресурса",
        },
        "scalars": {},
        "traffic_df": None,
    }
    for key in SCALAR_KEYS:
        if key in st.session_state:
            value = st.session_state[key]
            try:
                json.dumps(value)
                config["scalars"][key] = value
            except (TypeError, ValueError):
                continue
    if "traffic_df" in st.session_state:
        df = st.session_state["traffic_df"]
        if isinstance(df, pd.DataFrame):
            config["traffic_df"] = df.to_dict(orient="records")
    return json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8")


def queue_config_for_loading(uploaded_file):
    import streamlit as st
    try:
        if hasattr(uploaded_file, "read"):
            raw = uploaded_file.read()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
        else:
            raw = uploaded_file
        config = json.loads(raw)
        st.session_state["_pending_config"] = config
        st.session_state["_pending_config_message"] = "✅ Конфигурация загружена."
    except Exception as e:
        st.session_state["_pending_config"] = None
        st.session_state["_pending_config_message"] = f"❌ Ошибка: {e}"


def apply_pending_config():
    import streamlit as st
    config = st.session_state.get("_pending_config")
    if config is None:
        return None
    st.session_state["_pending_config"] = None
    message = st.session_state.pop("_pending_config_message", None)
    try:
        for key, value in config.get("scalars", {}).items():
            st.session_state[key] = value
        traffic_records = config.get("traffic_df")
        if traffic_records is not None:
            st.session_state["traffic_df"] = pd.DataFrame(traffic_records)
        return message or "✅ Конфигурация загружена."
    except Exception as e:
        return f"❌ Ошибка при восстановлении: {e}"