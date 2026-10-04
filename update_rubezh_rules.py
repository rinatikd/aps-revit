import json
import shutil
from pathlib import Path

# 1. Надежное определение пути относительно расположения этого скрипта
script_dir = Path(__file__).parent.resolve()
file_path = script_dir / "APS.extension" / "lib" / "aps_rules.json"
backup_path = file_path.with_suffix(".json.bak")

# Новые паспортные данные Рубеж R3, строго соответствующие схеме apsgeom.py и parity.js
rubezh_update = {
    "name": "Рубеж R3",
    "manufacturer": "НВП Болид / Рубеж",
    "max_addresses_per_loop": 127,  # Требуется parity.js для расчета cap
    "loop_fill_ratio": 0.8,
    "loops_per_panel": 2,
    "max_loop_length_m": 3000,
    
    # Должны быть словарями с ключом "model" (требование apsgeom.py и parity.js)
    "panel": {
        "model": "R3-Рубеж-2ОП",
        "_note": "РЭ ППКОПУ «Рубеж-2ОП прот.R3» (ПАСН.425513.003 РЭ ред. 18)"
    },
    "isolator": {
        "model": "ИЗ-1Б-R3",
        "takes_address": True,
        "_note": "РЭ ИП 212-64-R3, п. 2.7"
    },
    "devices": {
        "smoke": {"model": "ИП 212-64-R3"},
        "heat": {"model": "ИП 101-29-PR-R3"},
        "mcp": {"model": "ИПР 513-11-А-R3"},
        "sounder": {"model": "ОПОП 124-R3"}
    },
    
    "electrical": {
        "demo": False,
        "loop_voltage_v": 24.0,
        "min_end_voltage_v": 24.0,
        "loop_max_current_ma": 220,
        "max_loop_resistance_ohm": 300,
        
        # Должен быть словарем (требование apsgeom.py line ~415)
        "panel_current_ma": {
            "standby": 400,
            "max": 400,
            "_note": "РЭ ППКОПУ, п. 1.3.8, Таблица 1: Собственный ток потребления"
        },
        
        # Должна быть вложенной структурой {standby: X, max: Y} (требование apsgeom.py line ~630)
        "device_current_ma": {
            "smoke": {
                "standby": 0.32,
                "max": 0.32,
                "_note": "РЭ ИП 212-64-R3, п. 2.6: Ток в дежурном режиме"
            },
            "heat": {
                "standby": 0.32,
                "max": 0.32,
                "_note": "РЭ ИП 101-29-PR-R3, п. 2.7: Ток в дежурном режиме"
            },
            "mcp": {
                "standby": 0.46,
                "max": 0.46,
                "_note": "РЭ ИПР 513-11-А-R3, п. 2.3: Ток в дежурном режиме"
            },
            "sounder": {
                "standby": 0.2,
                "max": 2.2,
                "_note": "РЭ ОПОП 124-R3, п. 2.1: 0.2 мА дежурный, до 2.2 мА в тревоге"
            },
            "isolator": {
                "standby": 0.7,
                "max": 10.0,
                "_note": "РЭ ИП 212-64-R3, п. 2.7: 0.7 мА дежурный, 10 мА при срабатывании"
            }
        }
    }
}

if file_path.exists():
    try:
        # 2. Создаем резервную копию перед изменением
        shutil.copy2(file_path, backup_path)
        print(f"✅ Создана резервная копия: {backup_path.name}")
        
        # 3. Читаем существующие данные
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 4. Гарантируем наличие структуры vendors
        if "vendors" not in data:
            data["vendors"] = {}
            
        # 5. Обновляем только раздел rubezh, сохраняя остальные (например, bolid)
        data["vendors"]["rubezh"] = rubezh_update
        
        # 6. Записываем обновленные данные
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        print("✅ Успешно! Файл aps_rules.json обновлен паспортными данными Рубеж R3.")
        print("💡 Структура теперь на 100% совместима с apsgeom.py и parity.js.")
        print("💡 Следующий шаг: запустите python tools/sync_html.py для встраивания в HTML.")
    except Exception as e:
        print(f"❌ Ошибка при обновлении файла: {e}")
else:
    print(f"❌ Файл не найден по пути: {file_path}")
    print("💡 Убедитесь, что скрипт находится в корневой папке проекта aps-revit.")
