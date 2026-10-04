import json
import os

# Путь к файлу относительно корня проекта
file_path = "APS.extension/lib/aps_rules.json"

# Новые паспортные данные Рубеж R3
rubezh_update = {
    "name": "Рубеж R3",
    # ИСПРАВЛЕНО: 'devices' вместо 'families', чтобы соответствовать v.devices[r.role].model в parity.js
    "devices": {
        "smoke": "ИП 212-64-R3",
        "heat": "ИП 101-29-PR-R3",
        "mcp": "ИПР 513-11-А-R3",
        "sounder": "ОПОП 124-R3",
        "panel": "R3-Рубеж-2ОП",
        "isolator": "ИЗ-1Б-R3"
    },
    "electrical": {
        "demo": False,
        "loop_voltage_v": 24.0,
        "_status_loop_voltage": "РЭ ППКОПУ «Рубеж-2ОП прот.R3» (ПАСН.425513.003 РЭ ред. 18), п. 1.3.6",
        "min_end_voltage_v": 24.0,
        "_status_min_end_voltage": "РЭ ППКОПУ «Рубеж-2ОП прот.R3», п. 1.3.6: Минимальное рабочее напряжение на клеммах АЛС",
        "loop_max_current_ma": 220,
        "_status_loop_max_current": "РЭ ППКОПУ «Рубеж-2ОП прот.R3», п. 1.3.5: Максимально допустимый ток АЛС",
        "max_loop_resistance_ohm": 300,
        "_status_max_loop_resistance": "РЭ ППКОПУ «Рубеж-2ОП прот.R3», п. 1.3.4: Макс. сопротивление двух проводов АЛС",
        "panel_current_ma": 400,
        "_status_panel_current": "РЭ ППКОПУ «Рубеж-2ОП прот.R3», п. 1.3.8, Таблица 1: Собственный ток потребления",
        "device_current_ma": {
            "smoke": 0.32,
            "_status_smoke": "РЭ ИП 212-64-R3, п. 2.6: Ток в дежурном режиме",
            "heat": 0.32,
            "_status_heat": "РЭ ИП 101-29-PR-R3, п. 2.7: Ток в дежурном режиме",
            "mcp": 0.46,
            "_status_mcp": "РЭ ИПР 513-11-А-R3, п. 2.3: Ток в дежурном режиме",
            "sounder": 0.2,
            "_status_sounder": "РЭ ОПОП 124-R3, п. 2.1: Ток потребления в дежурном режиме (до 2.2 мА в тревоге)",
            "isolator_standby": 0.7,
            "_status_isolator_standby": "РЭ ИП 212-64-R3, п. 2.7: Ток изолятора в дежурном режиме",
            "isolator_active": 10.0,
            "_status_isolator_active": "РЭ ИП 212-64-R3, п. 2.7: Ток изолятора при срабатывании"
        }
    },
    "max_loop_length_m": 3000,
    "_status_max_loop_length": "РЭ ППКОПУ «Рубеж-2ОП прот.R3», п. 1.3.14",
    "loops_per_panel": 2,
    "loop_fill_ratio": 0.8,
    # ИСПРАВЛЕНО: добавлено поле, которое явно используется в parity.js для расчета cap
    "max_addresses_per_loop": 127 
}
}

if os.path.exists(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Гарантируем наличие структуры vendors
        if "vendors" not in data:
            data["vendors"] = {}
            
        # Обновляем только раздел rubezh, сохраняя остальные (например, bolid)
        data["vendors"]["rubezh"] = rubezh_update
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        print("✅ Успешно! Файл aps_rules.json обновлен паспортными данными Рубеж R3.")
    except Exception as e:
        print(f"❌ Ошибка при обновлении файла: {e}")
else:
    print(f"❌ Файл не найден по пути: {file_path}")
    print("Убедитесь, что вы запускаете скрипт из корневой папки проекта aps-revit.")
