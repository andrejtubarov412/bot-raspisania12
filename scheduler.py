# -*- coding: utf-8 -*-

from collections import defaultdict
from config import DAILY_HOURS, SHIFT_HOURS

class Scheduler:
    def __init__(self, db):
        self.db = db

    def generate(self):
        users = self.db.get_all_accounts()
        if not users:
            return None

        user_id_map = {u[2]: u[0] for u in users}
        user_names = [u[2] for u in users if u[3] != 'admin']
        if not user_names:
            return None

        # Получаем недоступные дни
        unavailable_by_user = {}
        for name in user_names:
            user_id = user_id_map[name]
            unavailable_by_user[name] = self.db.get_unavailable_days(user_id)

        # Получаем пожелания
        wishes = self.db.get_wishes()
        wishes_by_user = defaultdict(list)
        for name, day, shift in wishes:
            if name in user_names:
                wishes_by_user[name].append((day, shift))

        result = defaultdict(dict)
        assigned_count = defaultdict(int)

        # ШАГ 1: Назначаем по одному пожеланию на сотрудника (с учётом недоступных)
        sorted_users = sorted(wishes_by_user.keys(), key=lambda x: len(wishes_by_user[x]))
        for name in sorted_users:
            for day, shift in wishes_by_user[name]:
                if day in unavailable_by_user.get(name, []):
                    continue
                hours = SHIFT_HOURS.get(shift, 0)
                if hours == 0:
                    continue
                daily_norm = DAILY_HOURS[day]
                total_assigned = sum(result[day].values()) if day in result else 0
                if total_assigned + hours <= daily_norm:
                    result[day][name] = hours
                    assigned_count[name] += 1
                    break

        # ШАГ 2: Заполняем оставшиеся часы свободными сотрудниками (с учётом недоступных)
        for day in DAILY_HOURS.keys():
            daily_norm = DAILY_HOURS[day]
            total_assigned = sum(result[day].values()) if day in result else 0
            remaining = daily_norm - total_assigned
            if remaining > 0:
                free_employees = []
                for name in user_names:
                    if name not in result[day] and day not in unavailable_by_user.get(name, []):
                        free_employees.append(name)
                free_employees.sort(key=lambda x: assigned_count[x])
                for name in free_employees:
                    if remaining <= 0:
                        break
                    if remaining >= 12:
                        result[day][name] = 12
                        remaining -= 12
                    elif remaining >= 7:
                        result[day][name] = 7
                        remaining -= 7
                    elif remaining >= 5:
                        result[day][name] = 5
                        remaining -= 5
                    else:
                        result[day][name] = remaining
                        remaining = 0
                    assigned_count[name] += 1

        # ШАГ 3: Если кто-то остался без смены – принудительно назначаем (проверяя недоступные)
        for name in user_names:
            if assigned_count[name] == 0:
                for day in DAILY_HOURS.keys():
                    if day in unavailable_by_user.get(name, []):
                        continue
                    daily_norm = DAILY_HOURS[day]
                    total_assigned = sum(result[day].values()) if day in result else 0
                    remaining = daily_norm - total_assigned
                    if remaining >= 12:
                        result[day][name] = 12
                        assigned_count[name] += 1
                        break
                    elif remaining >= 7:
                        result[day][name] = 7
                        assigned_count[name] += 1
                        break
                    elif remaining >= 5:
                        result[day][name] = 5
                        assigned_count[name] += 1
                        break

        # Сохраняем результат в БД
        schedule_data = defaultdict(dict)
        for day, employees in result.items():
            for name, hours in employees.items():
                if hours == 12:
                    shift = 'день'
                elif hours == 7:
                    shift = 'утро'
                elif hours == 5:
                    shift = 'вечер'
                else:
                    shift = 'день'
                schedule_data[day][shift] = name

        self.db.save_schedule(schedule_data)
        # Помечаем расписание как черновик (не опубликовано)
        self.db.set_setting('schedule_published', '0')
        return result
