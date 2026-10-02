# main.py
# -*- coding: utf-8 -*-
"""
Главный файл приложения. Интерфейс на Streamlit.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

from config import (
    VEHICLE_TYPES,
    STO_TO_GOST_MAPPING,
    KPR_REQUIRED,
    AVAILABLE_CATEGORIES,
)
import calculations
import config_io
import report_generator


# ==============================================================================
# НАСТРОЙКА СТРАНИЦЫ
# ==============================================================================
st.set_page_config(
    page_title="Расчёт ресурса дорожных конструкций",
    page_icon="🛣️",
    layout="wide",
)


# ==============================================================================
# ИНИЦИАЛИЗАЦИЯ ЗНАЧЕНИЙ ПО УМОЛЧАНИЮ
# ==============================================================================
if "coef_a_input" not in st.session_state:
    st.session_state["coef_a_input"] = 0.096
if "coef_b_input" not in st.session_state:
    st.session_state["coef_b_input"] = 1.017
if "base_type_input" not in st.session_state:
    st.session_state["base_type_input"] = "Неукреплённое вяжущими (по умолчанию)"
if "vehicle_masses" not in st.session_state:
    st.session_state["vehicle_masses"] = {
        name: {
            "mass_empty": data["mass_empty"],
            "mass_loaded": data["mass_loaded"],
            "mass_overload": data["mass_overload"],
        }
        for name, data in VEHICLE_TYPES.items()
    }


# ==============================================================================
# ПРИМЕНЕНИЕ ОТЛОЖЕННОЙ КОНФИГУРАЦИИ
# ==============================================================================
_pending_config_message = config_io.apply_pending_config()


# ==============================================================================
# CALLBACK-ФУНКЦИИ
# ==============================================================================
def copy_current_iri_to_initial():
    if "current_iri" in st.session_state:
        st.session_state["iri_0_input"] = st.session_state["current_iri"]


def update_coefficients_ab():
    base_type = st.session_state.get("base_type_input", "Неукреплённое вяжущими (по умолчанию)")
    if base_type == "Неукреплённое вяжущими (по умолчанию)":
        st.session_state["coef_a_input"] = 0.096
        st.session_state["coef_b_input"] = 1.017
    elif base_type == "Укреплённое вяжущими":
        st.session_state["coef_a_input"] = 0.112
        st.session_state["coef_b_input"] = 0.874


# ==============================================================================
# ЗАГОЛОВОК
# ==============================================================================
st.title("🛣️ Расчёт остаточного ресурса дорожных конструкций")
st.markdown("""
Программа для оценки остаточного ресурса нежёстких дорожных одежд
в соответствии с **СТО АВТОДОР 2.4-2013** и **СТО АВТОДОР 2.28-2016**.
""")
st.divider()


# ==============================================================================
# БОКОВАЯ ПАНЕЛЬ
# ==============================================================================
st.sidebar.header("⚙️ Общие настройки")

st.sidebar.subheader("Параметры дороги")

road_category = st.sidebar.selectbox(
    "Категория автомобильной дороги",
    ["IА", "IБ", "IВ", "II", "III", "IV", "V"],
    index=0,
    key="road_category_input",
)

design_load = st.sidebar.selectbox(
    "Расчётная нагрузка, кН",
    [100, 115],
    index=1,
    key="design_load",
)

design_life = st.sidebar.number_input(
    "Расчётный срок службы, лет",
    min_value=1, max_value=50, value=18, step=1,
    key="design_life",
)

num_lanes = st.sidebar.number_input(
    "Количество полос движения (в одном направлении)",
    min_value=1, max_value=5, value=2, step=1,
    key="num_lanes",
)

st.sidebar.subheader("Параметры нагрузки")

q_growth_percent = st.sidebar.number_input(
    "Годовой прирост интенсивности, %",
    min_value=0.0, max_value=30.0, value=5.0, step=0.5,
    format="%.1f",
    key="q_growth_percent",
)
q_growth = 1.0 + q_growth_percent / 100.0

trdg = st.sidebar.number_input(
    "Расчётное число дней в году, Трдг",
    min_value=1, max_value=365, value=205, step=1,
    key="trdg",
)

st.sidebar.subheader("Проектный ресурс")
use_project_np = st.sidebar.checkbox(
    "Задать проектное ΣNp вручную",
    value=False,
    key="use_project_np",
)
if use_project_np:
    project_np_input = st.sidebar.number_input(
        "Проектное ΣNp, млн. авт.",
        min_value=0.001, max_value=100000.0, value=16.424, step=0.001,
        format="%.3f",
        key="project_np_input",
    )
else:
    project_np_input = None

st.sidebar.subheader("Текущее состояние")
st.sidebar.markdown("**Текущий IRI** — для расчёта Sm по формуле 6.8.")

current_iri = st.sidebar.number_input(
    "Текущий IRI (на момент диагностики), м/км",
    min_value=0.5, max_value=15.0, value=1.8, step=0.1, format="%.2f",
    key="current_iri",
)

years_in_operation = st.sidebar.number_input(
    "Фактический срок эксплуатации, лет",
    min_value=0, max_value=50, value=8, step=1,
    key="years_in_operation",
)

# --- Тип дорожной одежды ---
st.sidebar.subheader("Прочность конструкции")

road_type = st.sidebar.selectbox(
    "Тип дорожной одежды",
    ["Капитальный", "Облегчённый", "Переходный"],
    index=0,
    key="road_type_input",
)

available_cats = AVAILABLE_CATEGORIES.get(road_type, [])
if road_category not in available_cats:
    effective_category = available_cats[0] if available_cats else road_category
    st.sidebar.warning(
        f"⚠️ Категория **{road_category}** не применяется для "
        f"**{road_type}** дорожной одежды. "
        f"Автоматически использую **{effective_category}**."
    )
else:
    effective_category = road_category

kpr_category = effective_category

try:
    kpr_data = calculations.get_kpr_required(road_type, kpr_category)
    default_kpr_tr = kpr_data["kpr_tr"]
    default_kn = kpr_data["kn"]
except ValueError:
    default_kpr_tr = 1.20
    default_kn = 0.95
    st.sidebar.warning(
        f"⚠️ Нет данных Kпр_тр для '{road_type}' / '{kpr_category}'. "
        f"Использовано значение по умолчанию."
    )

kpr_tr = st.sidebar.number_input(
    "Kпр_тр (требуемый)",
    min_value=1.00, max_value=2.00, value=default_kpr_tr, step=0.01,
    format="%.2f",
    key="kpr_tr_input",
    help=f"Автозаполнение: {road_type} / {kpr_category} → {default_kpr_tr:.2f}",
)

kpr_input_method = st.sidebar.radio(
    "Способ ввода Kпр_факт",
    ["Ввести Kпр_факт напрямую", "Рассчитать через E_факт / E_тр"],
    index=0,
    key="kpr_input_method",
)

if kpr_input_method == "Ввести Kпр_факт напрямую":
    kpr_fact = st.sidebar.number_input(
        "Kпр_факт (фактический)",
        min_value=0.50, max_value=2.00, value=1.15, step=0.01,
        format="%.2f",
        key="kpr_fact_input",
    )
else:
    e_fact = st.sidebar.number_input(
        "E_факт (фактический модуль), МПа",
        min_value=50.0, max_value=2000.0, value=380.0, step=5.0,
        format="%.1f",
        key="e_fact_input",
    )
    e_tr = st.sidebar.number_input(
        "E_тр (требуемый модуль), МПа",
        min_value=50.0, max_value=2000.0, value=330.0, step=5.0,
        format="%.1f",
        key="e_tr_input",
    )
    kpr_fact = e_fact / e_tr if e_tr > 0 else 0.0
    st.sidebar.info(f"Kпр_факт = E_факт / E_тр = {kpr_fact:.3f}")

# --- Критический порог IRI ---
st.sidebar.markdown("**Критический порог IRI**")

use_gost_iri = st.sidebar.checkbox(
    "Определять порог автоматически по ГОСТ Р 50597-2017",
    value=True,
    key="use_gost_iri",
)

if use_gost_iri:
    try:
        iri_limit = calculations.get_iri_limit(road_category, road_type)
        st.sidebar.info(
            f"Порог IRI = **{iri_limit} м/км** "
            f"(ГОСТ Р 50597-2017, {road_category} / {road_type})"
        )
    except ValueError as e:
        st.sidebar.warning(f"⚠️ {e}")
        iri_limit = 4.0
else:
    iri_limit = st.sidebar.number_input(
        "Критический порог IRI, м/км",
        min_value=1.0, max_value=15.0, value=4.0, step=0.1,
        format="%.1f",
        key="iri_limit_input",
    )

st.sidebar.info(
    "ℹ️ Эти параметры используются во всех расчётах. "
    "Задайте их перед вводом интенсивности движения."
)

# --- Сохранение / загрузка конфигурации ---
st.sidebar.divider()
st.sidebar.subheader("💾 Конфигурация расчёта")
st.sidebar.caption("Сохраните параметры в JSON, чтобы не вводить заново.")

json_bytes = config_io.save_config_to_json()
st.sidebar.download_button(
    label="💾 Сохранить конфигурацию (JSON)",
    data=json_bytes,
    file_name=f"road_config_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
    mime="application/json",
    key="save_config_button",
    use_container_width=True,
)

uploaded_config = st.sidebar.file_uploader(
    "📂 Загрузить конфигурацию (JSON)",
    type=["json"],
    key="load_config_uploader",
)

if uploaded_config is not None:
    st.sidebar.button(
        "🔄 Восстановить параметры",
        key="apply_config_button",
        use_container_width=True,
        on_click=config_io.queue_config_for_loading,
        args=(uploaded_config,),
    )

if _pending_config_message:
    st.sidebar.success(_pending_config_message)


# ==============================================================================
# ВКЛАДКИ
# ==============================================================================
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Интенсивность",
    "🚗 Типы ТС",
    "🔮 Прогноз IRI",
    "🧮 Расчёт",
    "📈 Результаты",
])


# ------------------------------------------------------------------------------
# ВКЛАДКА 1: Интенсивность
# ------------------------------------------------------------------------------
with tab1:
    st.header("Интенсивность движения")

    classification = st.radio(
        "Классификация транспортных средств:",
        ["СТО АВТОДОР (19 типов)", "ГОСТ / ЕЭК ООН EUR 13 (13 типов)"],
        horizontal=True,
    )

    st.divider()

    if classification == "СТО АВТОДОР (19 типов)":
        st.subheader("Интенсивность по классификации СТО")
        st.write("Заполните столбец «Интенсивность, авт/сут» для нужных типов ТС.")

        vehicle_names = list(VEHICLE_TYPES.keys())
        initial_data = pd.DataFrame({
            "Тип транспортного средства": vehicle_names,
            "Интенсивность, авт/сут": [0] * len(vehicle_names),
        })

        edited_df = st.data_editor(
            initial_data,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Тип транспортного средства": st.column_config.TextColumn(
                    "Тип ТС", disabled=True, width="large",
                ),
                "Интенсивность, авт/сут": st.column_config.NumberColumn(
                    "Интенсивность, авт/сут",
                    min_value=0, step=1, format="%d",
                ),
            },
            key="traffic_input_table_sto",
        )
        st.session_state["traffic_df"] = edited_df
        st.session_state["classification"] = "СТО"
        st.session_state["type_column_name"] = "Тип транспортного средства"

        total_intensity = edited_df["Интенсивность, авт/сут"].sum()
        st.metric("Суммарная интенсивность, авт/сут", f"{total_intensity:,}")

    else:
        st.subheader("Интенсивность по классификации ГОСТ (EUR 13)")

        gost_categories = [
            "1. Легковые, малые грузовики",
            "2. Двухосный грузовик",
            "3. Трехосный грузовик",
            "4. Четырехосный грузовик",
            "5. Двухосный грузовик с прицепом",
            "6. Трехосный грузовик с прицепом",
            "7. Автопоезд, 2-ос. тягач + 1-ос. п/п",
            "8. Автопоезд, 2-ос. тягач + 2-ос. п/п",
            "9. Автопоезд, 2-ос. тягач + 3-ос. п/п",
            "10. Автопоезд, 3-ос. тягач + 1 или 2-ос. п/п",
            "11. Автопоезд, 3-ос. тягач + 3-ос. п/п",
            "12. Автобус",
            "13. Автомобиль с 7-ю и более осями",
        ]

        initial_data = pd.DataFrame({
            "Категория ТС (ГОСТ / EUR 13)": gost_categories,
            "Интенсивность, авт/сут": [0] * len(gost_categories),
        })

        edited_df = st.data_editor(
            initial_data,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Категория ТС (ГОСТ / EUR 13)": st.column_config.TextColumn(
                    "Категория ТС", disabled=True, width="large",
                ),
                "Интенсивность, авт/сут": st.column_config.NumberColumn(
                    "Интенсивность, авт/сут",
                    min_value=0, step=1, format="%d",
                ),
            },
            key="traffic_input_table_gost",
        )
        st.session_state["traffic_df"] = edited_df
        st.session_state["classification"] = "ГОСТ"
        st.session_state["type_column_name"] = "Категория ТС (ГОСТ / EUR 13)"

        total_intensity = edited_df["Интенсивность, авт/сут"].sum()
        st.metric("Суммарная интенсивность, авт/сут", f"{total_intensity:,}")

    st.divider()
    st.subheader("Или загрузите данные из CSV")
    uploaded_file = st.file_uploader("Выберите CSV-файл с интенсивностью", type=["csv"])
    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            st.write("Загруженные данные:")
            st.dataframe(df, use_container_width=True)
            st.success("Файл успешно загружен!")
        except Exception as e:
            st.error(f"Ошибка при чтении файла: {e}")


# ------------------------------------------------------------------------------
# ВКЛАДКА 2: Типы ТС
# ------------------------------------------------------------------------------
with tab2:
    st.header("Параметры типов транспортных средств")
    st.write("Справочник типов ТС с массами и коэффициентами приведения из Таблицы 6.1 СТО 2.4-2013.")

    vehicle_masses = st.session_state["vehicle_masses"]

    vehicle_table = pd.DataFrame([
        {
            "Тип ТС": name,
            "Масса пустого, т": vehicle_masses[name]["mass_empty"],
            "Масса гружёного, т": vehicle_masses[name]["mass_loaded"],
            "Масса перегруж., т": vehicle_masses[name]["mass_overload"],
            "Sm пуст.": VEHICLE_TYPES[name]["sm_empty"],
            "Sm груж.": VEHICLE_TYPES[name]["sm_loaded"],
            "Sm перегр.": VEHICLE_TYPES[name]["sm_overload"],
        }
        for name in VEHICLE_TYPES.keys()
    ])

    edited_masses = st.data_editor(
        vehicle_table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Тип ТС": st.column_config.TextColumn("Тип ТС", disabled=True, width="large"),
            "Масса пустого, т": st.column_config.NumberColumn(
                "Масса пустого, т", min_value=0.5, max_value=100.0, step=0.1, format="%.1f",
            ),
            "Масса гружёного, т": st.column_config.NumberColumn(
                "Масса гружёного, т", min_value=0.5, max_value=150.0, step=0.1, format="%.1f",
            ),
            "Масса перегруж., т": st.column_config.NumberColumn(
                "Масса перегруж., т", min_value=0.5, max_value=200.0, step=0.1, format="%.1f",
            ),
            "Sm пуст.": st.column_config.NumberColumn("Sm пуст.", disabled=True, format="%.4f"),
            "Sm груж.": st.column_config.NumberColumn("Sm груж.", disabled=True, format="%.4f"),
            "Sm перегр.": st.column_config.NumberColumn("Sm перегр.", disabled=True, format="%.4f"),
        },
        key="vehicle_masses_editor",
    )

    for _, row in edited_masses.iterrows():
        name = row["Тип ТС"]
        st.session_state["vehicle_masses"][name]["mass_empty"] = row["Масса пустого, т"]
        st.session_state["vehicle_masses"][name]["mass_loaded"] = row["Масса гружёного, т"]
        st.session_state["vehicle_masses"][name]["mass_overload"] = row["Масса перегруж., т"]

    if st.button("🔄 Сбросить массы к значениям по умолчанию", key="reset_masses_button"):
        st.session_state["vehicle_masses"] = {
            name: {
                "mass_empty": data["mass_empty"],
                "mass_loaded": data["mass_loaded"],
                "mass_overload": data["mass_overload"],
            }
            for name, data in VEHICLE_TYPES.items()
        }
        st.rerun()

    st.success("✅ Массы сохранены.")

    st.divider()
    st.subheader("Соответствие классификаций СТО ↔ ГОСТ (EUR 13)")

    mapping_table = pd.DataFrame([
        {"Тип ТС (СТО)": sto, "Категория (ГОСТ / EUR 13)": gost}
        for sto, gost in STO_TO_GOST_MAPPING.items()
    ])
    st.dataframe(mapping_table, use_container_width=True, hide_index=True)


# ------------------------------------------------------------------------------
# ВКЛАДКА 3: Прогноз IRI
# ------------------------------------------------------------------------------
with tab3:
    st.header("🔮 Прогнозирование продольной ровности (IRI)")
    st.write("**IRI_t = IRI_0 + a · (ΣN_ф.ед.)^b**  — формула 5.8 СТО 2.28-2016")

    st.info(
        f"""
        **Два разных показателя IRI:**

        | Показатель | Где задан | Значение |
        |---|---|---|
        | **Текущий IRI** | Боковая панель | **{current_iri:.2f}** м/км |
        | **Начальный IRI (IRI₀)** | Эта вкладка | — |
        """
    )

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Параметры модели")
        iri_0 = st.number_input(
            "Начальный IRI (IRI₀, на момент сдачи дороги), м/км",
            min_value=0.3, max_value=10.0, value=1.0, step=0.1,
            format="%.2f",
            key="iri_0_input",
        )
        st.button(
            "📋 Подставить текущий IRI как начальный",
            key="copy_iri_button",
            on_click=copy_current_iri_to_initial,
        )

        st.markdown("**Тип основания дорожной одежды:**")
        base_type = st.radio(
            "Выберите тип основания:",
            ["Неукреплённое вяжущими (по умолчанию)", "Укреплённое вяжущими", "Другой тип (ввести вручную)"],
            index=0,
            key="base_type_input",
            on_change=update_coefficients_ab,
        )

        coef_a = st.number_input(
            "Коэффициент a",
            min_value=0.0, max_value=10.0, step=0.001,
            format="%.4f",
            key="coef_a_input",
        )
        coef_b = st.number_input(
            "Коэффициент b (показатель степени)",
            min_value=0.5, max_value=3.0, step=0.001,
            format="%.4f",
            key="coef_b_input",
        )
        forecast_years = st.number_input(
            "Горизонт прогнозирования, лет",
            min_value=1, max_value=30, value=10, step=1,
            key="forecast_years_input",
        )

    with col2:
        st.subheader("Прогноз интенсивности")

        if "traffic_df" in st.session_state:
            traffic_df_check = st.session_state["traffic_df"]
            total_check = traffic_df_check["Интенсивность, авт/сут"].sum()
            st.metric("Текущая интенсивность, авт/сут", f"{total_check:,}")
        else:
            st.warning("⚠️ Данные об интенсивности не введены.")

        st.info(
            f"Годовой прирост q = **{q_growth_percent:.1f}%**\n\n"
            f"Количество полос = **{num_lanes}**\n\n"
            f"Расчётное число дней Трдг = **{trdg}**"
        )

    st.divider()

    if st.button("🔮 Построить прогноз IRI", type="primary", use_container_width=True):
        if "traffic_df" not in st.session_state:
            st.error("❌ Сначала введите интенсивность движения.")
            st.stop()

        traffic_df = st.session_state["traffic_df"]
        total_intensity = traffic_df["Интенсивность, авт/сут"].sum()

        if total_intensity == 0:
            st.error("❌ Интенсивность равна нулю.")
            st.stop()

        st.info("ℹ️ Доля наиболее нагруженной полосы — по примеру Б.1 СТО 2.28-2016.")

        lane_share = st.number_input(
            "Доля наиболее нагруженной полосы",
            min_value=0.10, max_value=1.00, value=0.51, step=0.01,
            format="%.2f",
            key="lane_share_input",
        )

        years_list = list(range(1, forecast_years + 1))
        np_fed_list = []
        iri_list = []

        for t in years_list:
            if abs(q_growth - 1.0) < 1e-9:
                kc_t = float(t)
            else:
                kc_t = (q_growth ** t - 1.0) / (q_growth - 1.0)

            np_fed = (total_intensity * kc_t * 365 * lane_share) / 1_000_000
            np_fed_list.append(np_fed)
            iri_t = iri_0 + coef_a * (np_fed ** coef_b)
            iri_list.append(iri_t)

        st.session_state["iri_forecast"] = {
            "years": years_list,
            "np_fed": np_fed_list,
            "iri": iri_list,
            "iri_0": iri_0,
            "coef_a": coef_a,
            "coef_b": coef_b,
        }

        st.success("✅ Прогноз построен!")

        forecast_df = pd.DataFrame({
            "Год эксплуатации": years_list,
            "ΣN_ф.ед., млн. авт.": [f"{v:.4f}" for v in np_fed_list],
            "Прогноз IRI, м/км": [f"{v:.3f}" for v in iri_list],
        })
        st.dataframe(forecast_df, use_container_width=True, hide_index=True)

        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(years_list, iri_list, marker="o", color="darkorange", linewidth=2, label="Прогноз IRI")
        ax.axhline(y=iri_0, color="gray", linestyle="--", alpha=0.6,
                   label=f"Начальный IRI = {iri_0:.2f}")
        ax.axhline(y=iri_limit, color="red", linestyle=":", alpha=0.6,
                   label=f"Критический порог (IRI = {iri_limit:.1f})")
        ax.set_xlabel("Годы эксплуатации")
        ax.set_ylabel("IRI, м/км")
        ax.set_title("Прогноз продольной ровности (IRI)")
        ax.grid(True, alpha=0.3)
        ax.legend()
        st.pyplot(fig)
        plt.close(fig)

        iri_final = iri_list[-1]
        st.divider()
        st.subheader("Интерпретация")

        if iri_final < iri_limit * 0.5:
            st.success(f"✅ Прогнозный IRI: **{iri_final:.3f} м/км**. Покрытие в отличном состоянии.")
        elif iri_final < iri_limit * 0.75:
            st.info(f"ℹ️ Прогнозный IRI: **{iri_final:.3f} м/км**. Покрытие в хорошем состоянии.")
        elif iri_final < iri_limit:
            st.warning(f"⚠️ Прогнозный IRI: **{iri_final:.3f} м/км**. Близко к порогу. Планируйте ремонт.")
        else:
            st.error(f"❌ Прогнозный IRI: **{iri_final:.3f} м/км**. Выше порога. Требуется ремонт.")


# ------------------------------------------------------------------------------
# ВКЛАДКА 4: Расчёт
# ------------------------------------------------------------------------------
with tab4:
    st.header("Параметры расчёта")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Метод расчёта Sm")
        sm_method = st.radio(
            "Как рассчитывать коэффициенты приведения?",
            ["По таблице (Таблица 6.1 СТО)", "По формуле (формула 6.8 СТО)"],
            index=0,
            key="sm_method",
        )

    with col2:
        st.subheader("Состав потока")
        percent_empty = st.slider("Доля пустых ТС, %", 0, 100, 30, 5, key="p_empty")
        percent_loaded = st.slider("Доля гружёных ТС, %", 0, 100, 60, 5, key="p_loaded")
        percent_overload = st.slider("Доля перегруженных ТС, %", 0, 100, 10, 5, key="p_overload")

        total_percent = percent_empty + percent_loaded + percent_overload
        if total_percent != 100:
            st.warning(f"⚠️ Сумма долей = {total_percent}%. Должно быть 100%.")
        else:
            st.success(f"✅ Сумма долей = 100%.")

    if sm_method == "По формуле (формула 6.8 СТО)":
        st.divider()
        st.subheader("Скорость движения")
        speed = st.number_input(
            "Скорость движения, км/ч",
            min_value=20, max_value=150, value=90, step=5,
            key="speed_input",
        )
    else:
        speed = None

    st.divider()
    st.subheader("Сводка параметров")

    summary_df = pd.DataFrame({
        "Параметр": ["Категория дороги", "Расчётная нагрузка", "Срок службы",
                     "Фактический срок", "Полос", "Прирост", "Трдг", "Текущий IRI", "Метод Sm"],
        "Значение": [road_category, f"{design_load} кН", f"{design_life} лет",
                     f"{years_in_operation} лет", num_lanes, f"{q_growth_percent:.1f}%",
                     f"{trdg} дней", f"{current_iri:.2f} м/км", sm_method],
    })
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    st.divider()

    if st.button("🧮 Рассчитать", type="primary", use_container_width=True):
        if "traffic_df" not in st.session_state:
            st.error("❌ Сначала введите интенсивность движения.")
            st.stop()

        if total_percent != 100:
            st.error("❌ Сумма долей должна быть 100%.")
            st.stop()

        traffic_df = st.session_state["traffic_df"]
        type_column = st.session_state.get("type_column_name", "Тип транспортного средства")

        traffic_by_type = {}
        for _, row in traffic_df.iterrows():
            vtype = row[type_column]
            n_sut = float(row["Интенсивность, авт/сут"])
            if n_sut > 0:
                traffic_by_type[vtype] = n_sut

        if not traffic_by_type:
            st.error("❌ Не введена интенсивность.")
            st.stop()

        percents = {
            "empty": percent_empty / 100.0,
            "loaded": percent_loaded / 100.0,
            "overload": percent_overload / 100.0,
        }

        sm_by_type = {}
        sm_info_by_type = {}
        sm_method_key = "table" if sm_method == "По таблице (Таблица 6.1 СТО)" else "formula"

        try:
            for vtype in traffic_by_type.keys():
                result = calculations.calculate_sm_universal(
                    vehicle_type=vtype,
                    sm_method=sm_method_key,
                    percent_empty=percents["empty"],
                    percent_loaded=percents["loaded"],
                    percent_overload=percents["overload"],
                    design_load=design_load,
                    iri=current_iri,
                    speed=speed,
                    vehicle_masses_dict=st.session_state["vehicle_masses"],
                )
                sm_by_type[vtype] = result["sm"]
                sm_info_by_type[vtype] = {
                    "method": result["method"],
                    "sto_type": result["sto_type"],
                }
        except Exception as e:
            st.error(f"❌ Ошибка при расчёте Sm: {e}")
            st.stop()

        try:
            np_project = calculations.calculate_total_np(
                traffic_by_type=traffic_by_type,
                sm_by_type=sm_by_type,
                q=q_growth,
                t_sl=design_life,
                trdg=trdg,
                num_lanes=num_lanes,
            )
            np_fact = calculations.calculate_total_np(
                traffic_by_type=traffic_by_type,
                sm_by_type=sm_by_type,
                q=q_growth,
                t_sl=years_in_operation,
                trdg=trdg,
                num_lanes=num_lanes,
            )
            residual = calculations.calculate_residual_resource(
                np_project=np_project,
                np_fact=np_fact,
            )
        except Exception as e:
            st.error(f"❌ Ошибка при расчёте: {e}")
            st.stop()

        st.session_state["results"] = {
            "sm_by_type": sm_by_type,
            "sm_info_by_type": sm_info_by_type,
            "traffic_by_type": traffic_by_type,
            "np_project": np_project,
            "np_fact": np_fact,
            "residual": residual,
            "sm_method": sm_method,
            "design_life": design_life,
            "years_in_operation": years_in_operation,
            "q_growth": q_growth,
            "trdg": trdg,
            "design_load": design_load,
            "current_iri": current_iri,
            "kpr_tr": kpr_tr,
            "kpr_fact": kpr_fact,
            "road_type": road_type,
            "kpr_category": kpr_category,
            "np_project_for_kpr": np_project,
        }

        st.success("✅ Расчёт выполнен!")
        st.info("👉 Перейдите на вкладку «📈 Результаты».")

        c1, c2, c3 = st.columns(3)
        c1.metric("ΣNp (проект), млн. авт.", f"{np_project:.4f}")
        c2.metric("ΣNp (факт), млн. авт.", f"{np_fact:.4f}")
        c3.metric("ΣNост, млн. авт.", f"{residual['np_residual']:.4f}",
                  delta=f"{residual['percent_residual']:.1f}% от проекта")


# ------------------------------------------------------------------------------
# ВКЛАДКА 5: Результаты
# ------------------------------------------------------------------------------
with tab5:
    st.header("📈 Результаты расчёта")

    if "results" not in st.session_state:
        st.info("🚧 Сначала выполните расчёт на вкладке «🧮 Расчёт».")
        st.stop()

    res = st.session_state["results"]
    residual = res["residual"]

    st.subheader("Сводные показатели")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ΣNp (проект)", f"{res['np_project']:.4f} млн. авт.")
    c2.metric("ΣNp (факт)", f"{res['np_fact']:.4f} млн. авт.")
    c3.metric("ΣNост", f"{residual['np_residual']:.4f} млн. авт.")
    c4.metric("Остаточный ресурс", f"{residual['percent_residual']:.1f} %")

    st.divider()

    # Прочность
    st.subheader("🏗️ Оценка прочности конструкции")

    kpr_tr_val = res.get("kpr_tr", None)
    kpr_fact_val = res.get("kpr_fact", None)

    if kpr_tr_val is not None and kpr_fact_val is not None:
        strength_eval = calculations.evaluate_strength(kpr_fact_val, kpr_tr_val)

        kpr_df = pd.DataFrame({
            "Параметр": ["Тип дорожной одежды", "Категория для Kпр",
                         "Kпр_тр (требуемый)", "Kпр_факт (фактический)"],
            "Значение": [res.get("road_type", "—"), res.get("kpr_category", "—"),
                         f"{kpr_tr_val:.3f}", f"{kpr_fact_val:.3f}"],
        })
        st.dataframe(kpr_df, use_container_width=True, hide_index=True)

        if strength_eval["color"] == "success":
            st.success(f"{strength_eval['status']}\n\n{strength_eval['recommendation']}")
        elif strength_eval["color"] == "warning":
            st.warning(f"{strength_eval['status']}\n\n{strength_eval['recommendation']}")
        else:
            st.error(f"{strength_eval['status']}\n\n{strength_eval['recommendation']}")

        st.markdown("---")
        show_kpr_estimate = st.checkbox(
            "Показать ориентировочную оценку остаточного ресурса по прочности",
            value=False,
            key="show_kpr_estimate",
        )

        if show_kpr_estimate:
            kpr_estimate = calculations.estimate_residual_by_kpr(
                kpr_fact=kpr_fact_val,
                kpr_tr=kpr_tr_val,
                np_project=res.get("np_project_for_kpr", 0.0),
            )
            col1, col2 = st.columns(2)
            col1.metric("Остаточный ресурс по прочности", f"{kpr_estimate['percent']:.1f} %")
            col2.metric("ΣNост (по прочности)", f"{kpr_estimate['np_residual']:.4f} млн. авт.")
            st.info(kpr_estimate["note"])
    else:
        st.info("ℹ️ Для оценки прочности задайте Kпр_тр и Kпр_факт в боковой панели.")

    st.divider()

    # Таблица Sm
    st.subheader("Коэффициенты приведения Sm")
    st.write(f"Метод: **{res['sm_method']}**")

    sm_info = res.get("sm_info_by_type", {})
    method_labels = {
        "table": "📊 Таблица 6.1", "formula": "🧮 Формула 6.8",
        "table_fallback": "📊 Таблица 6.1 (fallback)", "mixed": "🔀 Смешанный", "none": "—",
    }

    sm_table = pd.DataFrame([
        {
            "Тип ТС": v,
            "Sm": round(sm, 4),
            "Метод": method_labels.get(sm_info.get(v, {}).get("method", "—"), "—"),
        }
        for v, sm in res["sm_by_type"].items()
    ])
    sm_table = sm_table.sort_values("Sm", ascending=False)
    st.dataframe(sm_table, use_container_width=True, hide_index=True)

    fallback_types = [v for v, info in sm_info.items() if info.get("method") == "table_fallback"]
    if fallback_types:
        st.info(f"ℹ️ Для типов ТС: **{', '.join(fallback_types)}** использованы табличные значения (нет коэффициентов b, c1, c2).")

    st.divider()

    # График
    st.subheader("Накопление ΣNp по годам")

    traffic_by_type = res["traffic_by_type"]
    sm_by_type = res["sm_by_type"]
    q = res["q_growth"]
    trdg_val = res["trdg"]
    design_life_val = res["design_life"]
    years_fact = res["years_in_operation"]

    if use_project_np and project_np_input is not None:
        np_project_total = project_np_input
        years_project = list(range(1, design_life_val + 1))
        np_cumulative_project = [np_project_total] * len(years_project)
    else:
        years_project = list(range(1, design_life_val + 1))
        np_cumulative_project = []
        for t in years_project:
            np_t = calculations.calculate_total_np(
                traffic_by_type=traffic_by_type, sm_by_type=sm_by_type,
                q=q, t_sl=t, trdg=trdg_val, num_lanes=num_lanes,
            )
            np_cumulative_project.append(np_t)
        np_project_total = np_cumulative_project[-1] if np_cumulative_project else 0

    years_fact_list = list(range(1, years_fact + 1)) if years_fact > 0 else []
    np_cumulative_fact = []
    for t in years_fact_list:
        np_t = calculations.calculate_total_np(
            traffic_by_type=traffic_by_type, sm_by_type=sm_by_type,
            q=q, t_sl=t, trdg=trdg_val, num_lanes=num_lanes,
        )
        np_cumulative_fact.append(np_t)

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))

    if use_project_np and project_np_input is not None:
        ax.axhline(y=np_project_total, color="steelblue", linestyle="-", linewidth=2,
                   label=f"Предельный ресурс = {np_project_total:.3f} млн. авт.")
    else:
        ax.plot(years_project, np_cumulative_project, marker="o",
                label="Проектная кривая", color="steelblue")

    if np_cumulative_fact:
        ax.plot(years_fact_list, np_cumulative_fact, marker="s",
                label="Фактическая кривая", color="indianred")
        ax.axvline(x=years_fact, color="gray", linestyle="--", alpha=0.6,
                   label=f"Текущий момент (t = {years_fact} лет)")
        ax.scatter([years_fact], [np_cumulative_fact[-1]], color="red", s=80, zorder=5)

    ax.set_xlabel("Годы эксплуатации")
    ax.set_ylabel("ΣNp, млн. авт.")
    ax.set_title("Накопление суммарного числа приложений нагрузки")
    ax.grid(True, alpha=0.3)
    ax.legend()
    st.pyplot(fig)
    plt.close(fig)

    st.divider()

    # Интерпретация
    st.subheader("Интерпретация результатов")
    percent = residual["percent_residual"]

    if percent >= 75:
        st.success(f"✅ **Остаточный ресурс {percent:.1f}%** — конструкция в хорошем состоянии.")
    elif percent >= 50:
        st.info(f"ℹ️ **Остаточный ресурс {percent:.1f}%** — рекомендуется планировать содержание.")
    elif percent >= 25:
        st.warning(f"⚠️ **Остаточный ресурс {percent:.1f}%** — требуется детальное обследование.")
    elif percent >= 10:
        st.warning(f"⚠️ **Остаточный ресурс {percent:.1f}%** — близка к предельному состоянию.")
    else:
        st.error(f"❌ **Остаточный ресурс {percent:.1f}%** — ресурс практически исчерпан.")

    st.divider()

    # Скачивание
    st.subheader("📥 Скачать результаты")

    col_dl1, col_dl2 = st.columns(2)

    with col_dl1:
        csv_data = sm_table.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="📊 Скачать таблицу Sm (CSV)",
            data=csv_data,
            file_name="sm_results.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with col_dl2:
        try:
            road_params_for_report = {
                "road_category": road_category,
                "design_load": design_load,
                "design_life": design_life,
                "num_lanes": num_lanes,
                "q_growth_percent": q_growth_percent,
                "trdg": trdg,
                "years_in_operation": years_in_operation,
                "current_iri": current_iri,
                "iri_limit": iri_limit if 'iri_limit' in dir() else 4.0,
                "road_type": road_type,
                "kpr_category": kpr_category if 'kpr_category' in dir() else road_category,
                "kpr_tr": kpr_tr,
                "kpr_fact": kpr_fact,
            }

            iri_forecast_data = st.session_state.get("iri_forecast", None)

            docx_bytes = report_generator.generate_report(
                results=res,
                road_params=road_params_for_report,
                iri_forecast=iri_forecast_data,
            )

            st.download_button(
                label="📄 Скачать полный отчёт (DOCX)",
                data=docx_bytes,
                file_name=f"road_report_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"❌ Не удалось сформировать отчёт: {e}")


# ==============================================================================
# ПОДВАЛ
# ==============================================================================
st.divider()
st.caption("Разработано в соответствии с СТО АВТОДОР 2.4-2013 и СТО АВТОДОР 2.28-2016.")