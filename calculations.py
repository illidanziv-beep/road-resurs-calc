# calculations.py
# -*- coding: utf-8 -*-
"""
Модуль расчёта остаточного ресурса дорожных конструкций.
"""

from config import (
    VEHICLE_TYPES,
    SM_FORMULA_COEFFS,
    AVAILABLE_IRI_VALUES,
    STO_TO_GOST_MAPPING,
    GOST_TO_STO_MAPPING,
    KPR_REQUIRED,
    KPR_CURVE_STO_2_4_2013,
    IRI_LIMITS_GOST_50597,
)


# ==============================================================================
# 1. РАСЧЁТ Sm ПО ТАБЛИЦЕ
# ==============================================================================

def calculate_sm_table(vehicle_type, percent_empty, percent_loaded, percent_overload):
    total = percent_empty + percent_loaded + percent_overload
    if abs(total - 1.0) > 0.01:
        raise ValueError(f"Сумма долей должна быть равна 1.0, получено: {total}")

    data = VEHICLE_TYPES.get(vehicle_type)
    if data is None:
        raise ValueError(f"Тип ТС '{vehicle_type}' не найден в справочнике.")

    sm_empty = data["sm_empty"]
    sm_loaded = data["sm_loaded"]
    sm_overload = data["sm_overload"]

    if sm_loaded is None or sm_overload is None:
        return sm_empty

    return percent_empty * sm_empty + percent_loaded * sm_loaded + percent_overload * sm_overload


# ==============================================================================
# 2. РАСЧЁТ Sm ПО ФОРМУЛЕ 6.8
# ==============================================================================

def interpolate_iri(iri, available_iri):
    for val in available_iri:
        if abs(iri - val) < 1e-9:
            return val, val, 1.0
    if iri <= available_iri[0]:
        return available_iri[0], available_iri[0], 1.0
    if iri >= available_iri[-1]:
        return available_iri[-1], available_iri[-1], 1.0
    for i in range(len(available_iri) - 1):
        if available_iri[i] <= iri <= available_iri[i + 1]:
            low = available_iri[i]
            high = available_iri[i + 1]
            weight = (high - iri) / (high - low)
            return low, high, weight
    return available_iri[0], available_iri[0], 1.0


def get_coefficients_abc(vehicle_type, iri, design_load):
    coeffs_by_load = SM_FORMULA_COEFFS.get(design_load)
    if coeffs_by_load is None:
        raise ValueError(f"Нет коэффициентов для нагрузки {design_load} кН.")

    iri_low, iri_high, weight_low = interpolate_iri(iri, AVAILABLE_IRI_VALUES)

    if abs(iri_low - iri_high) < 1e-9:
        coeffs = coeffs_by_load.get(iri_low, {}).get(vehicle_type)
        if coeffs is None:
            raise ValueError(f"Нет коэффициентов для '{vehicle_type}' при IRI={iri_low}.")
        return coeffs

    coeffs_low = coeffs_by_load.get(iri_low, {}).get(vehicle_type)
    coeffs_high = coeffs_by_load.get(iri_high, {}).get(vehicle_type)

    if coeffs_low is None or coeffs_high is None:
        raise ValueError(f"Нет коэффициентов для '{vehicle_type}' при IRI={iri_low} или {iri_high}.")

    weight_high = 1.0 - weight_low
    return {
        "b": weight_low * coeffs_low["b"] + weight_high * coeffs_high["b"],
        "c1": weight_low * coeffs_low["c1"] + weight_high * coeffs_high["c1"],
        "c2": weight_low * coeffs_low["c2"] + weight_high * coeffs_high["c2"],
    }


def calculate_sm_formula(vehicle_type, iri, speed, mass, design_load):
    coeffs = get_coefficients_abc(vehicle_type, iri, design_load)
    return coeffs["b"] * (coeffs["c1"] ** speed) * (coeffs["c2"] ** mass)


def calculate_sm_weighted_formula(vehicle_type, iri, speed, masses, percents, design_load):
    sm_total = 0.0
    for state in ["empty", "loaded", "overload"]:
        mass = masses.get(state)
        percent = percents.get(state, 0.0)
        if mass is not None and percent > 0:
            sm_total += percent * calculate_sm_formula(vehicle_type, iri, speed, mass, design_load)
    return sm_total


# ==============================================================================
# 3. РАСЧЁТ ΣNp
# ==============================================================================

def calculate_kc(q, t_sl):
    if abs(q - 1.0) < 1e-9:
        return float(t_sl)
    return (q ** t_sl - 1.0) / (q - 1.0)


def calculate_total_np(traffic_by_type, sm_by_type, q, t_sl, trdg,
                       num_lanes=1, f_pol=0.7, k_n=1.49):
    kc = calculate_kc(q, t_sl)
    total = 0.0
    for vtype, n_sut in traffic_by_type.items():
        sm = sm_by_type.get(vtype, 0.0)
        if sm == 0 or n_sut == 0:
            continue
        total += n_sut * kc * trdg * 0.7 * sm * k_n
    if num_lanes > 0:
        total = total * f_pol / num_lanes
    return total / 1_000_000


# ==============================================================================
# 4. РАСЧЁТ ОСТАТОЧНОГО РЕСУРСА
# ==============================================================================

def calculate_residual_resource(np_project, np_fact):
    np_residual = np_project - np_fact
    percent_residual = (np_residual / np_project * 100) if np_project > 0 else 0.0
    return {
        "np_project": np_project,
        "np_fact": np_fact,
        "np_residual": np_residual,
        "percent_residual": percent_residual,
    }


# ==============================================================================
# 5. УНИВЕРСАЛЬНАЯ ФУНКЦИЯ РАСЧЁТА Sm
# ==============================================================================

def resolve_vehicle_type(vehicle_type):
    if vehicle_type in VEHICLE_TYPES:
        return [vehicle_type]
    if vehicle_type in GOST_TO_STO_MAPPING:
        return GOST_TO_STO_MAPPING[vehicle_type]
    return []


def _has_formula_coefficients(vehicle_type, iri, design_load):
    coeffs_by_load = SM_FORMULA_COEFFS.get(design_load)
    if coeffs_by_load is None:
        return False
    iri_low, iri_high, _ = interpolate_iri(iri, AVAILABLE_IRI_VALUES)
    for iri_val in {iri_low, iri_high}:
        if coeffs_by_load.get(iri_val, {}).get(vehicle_type) is not None:
            return True
    return False


def calculate_sm_universal(vehicle_type, sm_method, percent_empty, percent_loaded,
                           percent_overload, design_load, iri=None, speed=None,
                           vehicle_masses_dict=None):
    sto_types = resolve_vehicle_type(vehicle_type)
    if not sto_types:
        raise ValueError(f"Не удалось определить тип ТС '{vehicle_type}'.")

    sm_values = []
    methods_used = []

    for sto_type in sto_types:
        vdata = VEHICLE_TYPES.get(sto_type)
        if vdata is None:
            continue

        if sm_method == "table":
            sm = calculate_sm_table(sto_type, percent_empty, percent_loaded, percent_overload)
            methods_used.append("table")
        else:
            has_coeffs = _has_formula_coefficients(sto_type, iri, design_load)
            if has_coeffs:
                if vehicle_masses_dict and sto_type in vehicle_masses_dict:
                    masses = vehicle_masses_dict[sto_type]
                else:
                    masses = {
                        "empty": vdata["mass_empty"],
                        "loaded": vdata["mass_loaded"],
                        "overload": vdata["mass_overload"],
                    }
                percents = {
                    "empty": percent_empty,
                    "loaded": percent_loaded,
                    "overload": percent_overload,
                }
                sm = calculate_sm_weighted_formula(sto_type, iri, speed, masses, percents, design_load)
                methods_used.append("formula")
            else:
                sm = vdata["sm_empty"]
                methods_used.append("table_fallback")

        sm_values.append(sm)

    if not sm_values:
        return {"sm": 0.0, "method": "none", "sto_type": vehicle_type}

    if all(m == "formula" for m in methods_used):
        final_method = "formula"
    elif all(m == "table" for m in methods_used):
        final_method = "table"
    elif any(m == "table_fallback" for m in methods_used):
        final_method = "mixed"
    else:
        final_method = methods_used[0]

    return {
        "sm": sum(sm_values) / len(sm_values),
        "method": final_method,
        "sto_type": ", ".join(sto_types),
    }


# ==============================================================================
# 6. РАСЧЁТ ПО ПРОЧНОСТИ
# ==============================================================================

def get_kpr_required(road_type, category):
    data = KPR_REQUIRED.get(road_type, {}).get(category)
    if data is None:
        raise ValueError(f"Нет данных Kпр_тр для '{road_type}' / '{category}'.")
    return data


def evaluate_strength(kpr_fact, kpr_tr):
    if kpr_fact < 1.00:
        return {
            "status": "❌ Прочность НЕДОСТАТОЧНА",
            "recommendation": ("Требуется капитальный ремонт или усиление конструкции. "
                               "Необходимо проведение специализированного обследования."),
            "color": "error", "level": "critical",
        }
    elif abs(kpr_fact - 1.00) < 1e-9:
        return {
            "status": "🟡 Прочность на грани отказа",
            "recommendation": ("Запас прочности исчерпан. Рекомендуется детальное обследование "
                               "и планирование ремонтных работ."),
            "color": "warning", "level": "critical",
        }
    elif kpr_fact < kpr_tr:
        return {
            "status": "⚠️ Прочность ниже проектной, но работоспособна",
            "recommendation": ("Прочность обеспечена (Kпр > 1), но ниже проектного уровня. "
                               "Рекомендуется мониторинг и профилактические мероприятия."),
            "color": "warning", "level": "below_project",
        }
    elif abs(kpr_fact - kpr_tr) < 1e-9:
        return {
            "status": "✅ Прочность соответствует проектной",
            "recommendation": "Конструкция работает в соответствии с проектом.",
            "color": "success", "level": "ok",
        }
    else:
        return {
            "status": "✅ Прочность выше проектной",
            "recommendation": "Конструкция имеет запас прочности выше проектного.",
            "color": "success", "level": "ok",
        }


def estimate_residual_by_kpr(kpr_fact, kpr_tr, np_project):
    if kpr_fact < 1.00:
        return {
            "percent": 0.0, "np_residual": 0.0,
            "note": "Конструкция достигла отказа (Kпр < 1.00).",
        }
    if abs(kpr_tr - 1.00) < 1e-9:
        return {
            "percent": 0.0, "np_residual": 0.0,
            "note": "Проектный Kпр_тр = 1.00 — ресурс не определён.",
        }

    kpr_relative = 1.00 + (kpr_fact - 1.00) * 0.30 / (kpr_tr - 1.00)

    points = sorted(KPR_CURVE_STO_2_4_2013.items(), key=lambda x: x[1])

    if kpr_relative <= 1.00:
        return {
            "percent": 0.0, "np_residual": 0.0,
            "note": "Ориентировочно: остаточный ресурс по прочности практически исчерпан.",
        }
    if kpr_relative >= 1.30:
        return {
            "percent": 100.0, "np_residual": np_project,
            "note": "Ориентировочно: фактическая прочность выше проектной.",
        }

    for i in range(len(points) - 1):
        perc_low, kpr_low = points[i]
        perc_high, kpr_high = points[i + 1]
        if kpr_low <= kpr_relative <= kpr_high:
            weight_high = (kpr_relative - kpr_low) / (kpr_high - kpr_low)
            percent = perc_low + weight_high * (perc_high - perc_low)
            return {
                "percent": percent,
                "np_residual": np_project * percent / 100.0,
                "note": ("⚠️ Ориентировочная оценка. Методика НЕ утверждена нормативно."),
            }

    return {"percent": 0.0, "np_residual": 0.0, "note": "Не удалось определить."}


# ==============================================================================
# 7. ПОРОГ IRI ПО ГОСТ Р 50597-2017
# ==============================================================================

def get_iri_limit(category, road_type):
    by_category = IRI_LIMITS_GOST_50597.get(category)
    if by_category is None:
        raise ValueError(f"Нет данных IRI-порога для категории '{category}'.")

    iri_limit = by_category.get(road_type)
    if iri_limit is None:
        available = list(by_category.keys())
        if available:
            iri_limit = by_category[available[0]]
        else:
            raise ValueError(f"Нет данных IRI-порога для '{category}' / '{road_type}'.")

    return iri_limit


# ==============================================================================
# 8. ПРОВЕРКА
# ==============================================================================
if __name__ == "__main__":
    sm = calculate_sm_table(
        "2.2. Грузовые средние (2-5 т)",
        percent_empty=0.3, percent_loaded=0.6, percent_overload=0.1,
    )
    print(f"Sm: {sm:.4f}")
    print("✅ Проверка пройдена!")