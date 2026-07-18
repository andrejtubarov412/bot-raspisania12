# -*- coding: utf-8 -*-

import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta, datetime

class Database:
    def __init__(self, db_name='schedule.db'):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.c = self.conn.cursor()
        # 1. Создаём таблицы (без данных)
        self._create_tables()
        # 2. Выполняем миграции (добавляем новые столбцы, если их нет)
        self._migrate_accounts()
        self._migrate_salaries()
        self._deduplicate_salaries()
        # 3. Теперь можно работать с данными – все столбцы уже существуют
        self._init_data()

    def _create_tables(self):
        self.c.execute('''CREATE TABLE IF NOT EXISTS accounts
                         (id INTEGER PRIMARY KEY,
                          username TEXT UNIQUE,
                          password_hash TEXT,
                          full_name TEXT,
                          role TEXT DEFAULT 'user')''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS wishes
                         (id INTEGER PRIMARY KEY,
                          account_id INTEGER,
                          day TEXT,
                          shift TEXT,
                          FOREIGN KEY(account_id) REFERENCES accounts(id))''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS unavailable_days
                         (id INTEGER PRIMARY KEY,
                          account_id INTEGER,
                          day TEXT,
                          FOREIGN KEY(account_id) REFERENCES accounts(id),
                          UNIQUE(account_id, day))''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS schedule
                         (id INTEGER PRIMARY KEY,
                          day TEXT,
                          shift TEXT,
                          account_id INTEGER,
                          FOREIGN KEY(account_id) REFERENCES accounts(id))''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS hours
                         (id INTEGER PRIMARY KEY,
                          account_id INTEGER,
                          date TEXT,
                          hours REAL,
                          shift TEXT,
                          FOREIGN KEY(account_id) REFERENCES accounts(id))''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS settings
                         (key TEXT PRIMARY KEY,
                          value TEXT)''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS salaries
                         (id INTEGER PRIMARY KEY,
                          account_id INTEGER,
                          week_start TEXT,
                          total_hours REAL,
                          rate REAL,
                          amount REAL,
                          bonus REAL DEFAULT 0,
                          deduction REAL DEFAULT 0,
                          extra1 REAL DEFAULT 0,
                          extra2 REAL DEFAULT 0,
                          extra3 REAL DEFAULT 0,
                          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                          FOREIGN KEY(account_id) REFERENCES accounts(id))''')
        self.conn.commit()

    def _migrate_accounts(self):
        """Добавляет столбцы fixed_extra1, fixed_extra2, fixed_extra3 в таблицу accounts, если их нет."""
        self.c.execute("PRAGMA table_info(accounts)")
        columns = [row[1] for row in self.c.fetchall()]
        if 'fixed_extra1' not in columns:
            self.c.execute('ALTER TABLE accounts ADD COLUMN fixed_extra1 REAL DEFAULT 0')
        if 'fixed_extra2' not in columns:
            self.c.execute('ALTER TABLE accounts ADD COLUMN fixed_extra2 REAL DEFAULT 0')
        if 'fixed_extra3' not in columns:
            self.c.execute('ALTER TABLE accounts ADD COLUMN fixed_extra3 REAL DEFAULT 0')
        self.conn.commit()

    def _migrate_salaries(self):
        """Добавляет столбцы extra1, extra2, extra3 в таблицу salaries, если их нет."""
        self.c.execute("PRAGMA table_info(salaries)")
        columns = [row[1] for row in self.c.fetchall()]
        if 'extra1' not in columns:
            self.c.execute('ALTER TABLE salaries ADD COLUMN extra1 REAL DEFAULT 0')
        if 'extra2' not in columns:
            self.c.execute('ALTER TABLE salaries ADD COLUMN extra2 REAL DEFAULT 0')
        if 'extra3' not in columns:
            self.c.execute('ALTER TABLE salaries ADD COLUMN extra3 REAL DEFAULT 0')
        self.conn.commit()

    def _deduplicate_salaries(self):
        """Удаляет дублирующиеся записи в таблице salaries, оставляя самую свежую (с наибольшим id) для каждой пары (account_id, week_start)."""
        self.c.execute('''
            DELETE FROM salaries
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM salaries
                GROUP BY account_id, week_start
            )
        ''')
        self.conn.commit()

    def _init_data(self):
        """Создаёт администратора и устанавливает настройки по умолчанию, если их нет."""
        admin = self.get_account_by_username('admin')
        if not admin:
            self.create_account('admin', 'admin123', full_name='Администратор', role='admin')

        if self.get_hourly_rate() is None:
            self.set_hourly_rate(200)

        if self.get_extra_label(1) is None:
            self.set_extra_label(1, 'Дотация обеда')
        if self.get_extra_label(2) is None:
            self.set_extra_label(2, 'Надбавка за вечер')
        if self.get_extra_label(3) is None:
            self.set_extra_label(3, 'Переупаковка товаров')

    # ---- Аккаунты ----
    def create_account(self, username, password, full_name=None, role='user'):
        password_hash = generate_password_hash(password)
        try:
            self.c.execute('INSERT INTO accounts (username, password_hash, full_name, role, fixed_extra1, fixed_extra2, fixed_extra3) VALUES (?, ?, ?, ?, 0, 0, 0)',
                           (username, password_hash, full_name or username, role))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_account_by_username(self, username):
        self.c.execute('SELECT id, username, password_hash, full_name, role, fixed_extra1, fixed_extra2, fixed_extra3 FROM accounts WHERE username = ?', (username,))
        row = self.c.fetchone()
        if row:
            return {'id': row[0], 'username': row[1], 'password_hash': row[2], 'full_name': row[3], 'role': row[4],
                    'fixed_extra1': row[5], 'fixed_extra2': row[6], 'fixed_extra3': row[7]}
        return None

    def get_account_by_id(self, account_id):
        self.c.execute('SELECT id, username, full_name, role, fixed_extra1, fixed_extra2, fixed_extra3 FROM accounts WHERE id = ?', (account_id,))
        row = self.c.fetchone()
        if row:
            return {'id': row[0], 'username': row[1], 'full_name': row[2], 'role': row[3],
                    'fixed_extra1': row[4], 'fixed_extra2': row[5], 'fixed_extra3': row[6]}
        return None

    def authenticate(self, username, password):
        account = self.get_account_by_username(username)
        if account and check_password_hash(account['password_hash'], password):
            return account
        return None

    def get_all_accounts(self):
        self.c.execute('SELECT id, username, full_name, role, fixed_extra1, fixed_extra2, fixed_extra3 FROM accounts ORDER BY username')
        return self.c.fetchall()

    # ---- Постоянные надбавки сотрудников ----
    def get_employee_fixed_extras(self, account_id):
        self.c.execute('SELECT fixed_extra1, fixed_extra2, fixed_extra3 FROM accounts WHERE id = ?', (account_id,))
        row = self.c.fetchone()
        if row:
            return row[0], row[1], row[2]
        return 0.0, 0.0, 0.0

    def set_employee_fixed_extras(self, account_id, val1, val2, val3):
        self.c.execute('UPDATE accounts SET fixed_extra1 = ?, fixed_extra2 = ?, fixed_extra3 = ? WHERE id = ?',
                       (val1, val2, val3, account_id))
        self.conn.commit()
        return True

    # ---- Пожелания (без изменений) ----
    def add_wish(self, account_id, day, shift):
        self.c.execute('DELETE FROM wishes WHERE account_id = ? AND day = ?', (account_id, day))
        self.c.execute('INSERT INTO wishes (account_id, day, shift) VALUES (?, ?, ?)', (account_id, day, shift))
        self.conn.commit()
        return True

    def clear_wishes_for_user(self, account_id):
        self.c.execute('DELETE FROM wishes WHERE account_id = ?', (account_id,))
        self.conn.commit()

    def get_wishes(self):
        self.c.execute('SELECT a.full_name, w.day, w.shift FROM wishes w JOIN accounts a ON w.account_id = a.id ORDER BY w.day')
        return self.c.fetchall()

    def get_wishes_by_day(self, day):
        self.c.execute('SELECT a.full_name, w.shift FROM wishes w JOIN accounts a ON w.account_id = a.id WHERE w.day = ?', (day,))
        return self.c.fetchall()

    def clear_wishes(self):
        self.c.execute('DELETE FROM wishes')
        self.conn.commit()

    # ---- Недоступные дни (без изменений) ----
    def add_unavailable_day(self, account_id, day):
        try:
            self.c.execute('INSERT OR REPLACE INTO unavailable_days (account_id, day) VALUES (?, ?)', (account_id, day))
            self.conn.commit()
            return True
        except:
            return False

    def remove_unavailable_day(self, account_id, day):
        self.c.execute('DELETE FROM unavailable_days WHERE account_id = ? AND day = ?', (account_id, day))
        self.conn.commit()
        return True

    def get_unavailable_days(self, account_id):
        self.c.execute('SELECT day FROM unavailable_days WHERE account_id = ?', (account_id,))
        return [row[0] for row in self.c.fetchall()]

    def get_unavailable_for_day(self, day):
        self.c.execute('SELECT a.full_name FROM unavailable_days u JOIN accounts a ON u.account_id = a.id WHERE u.day = ?', (day,))
        return [row[0] for row in self.c.fetchall()]

    def clear_unavailable_days(self):
        self.c.execute('DELETE FROM unavailable_days')
        self.conn.commit()

    # ---- Расписание (без изменений) ----
    def save_schedule(self, data):
        self.c.execute('DELETE FROM schedule')
        for day, shifts in data.items():
            for shift, full_name in shifts.items():
                self.c.execute('SELECT id FROM accounts WHERE full_name = ?', (full_name,))
                row = self.c.fetchone()
                if row:
                    account_id = row[0]
                    self.c.execute('INSERT INTO schedule (day, shift, account_id) VALUES (?, ?, ?)',
                                   (day, shift, account_id))
        self.conn.commit()

    def get_schedule(self):
        self.c.execute('SELECT s.day, s.shift, s.account_id, a.full_name FROM schedule s JOIN accounts a ON s.account_id = a.id ORDER BY s.day')
        return self.c.fetchall()

    def update_schedule_cell(self, day, shift, account_id):
        self.c.execute('UPDATE schedule SET account_id = ? WHERE day = ? AND shift = ?', (account_id, day, shift))
        self.conn.commit()
        return True

    # ---- Часы (без изменений) ----
    def add_hours(self, full_name, date, hours, shift):
        self.c.execute('SELECT id FROM accounts WHERE full_name = ?', (full_name,))
        row = self.c.fetchone()
        if not row:
            return False
        account_id = row[0]
        self.c.execute('INSERT INTO hours (account_id, date, hours, shift) VALUES (?, ?, ?, ?)',
                       (account_id, date, hours, shift))
        self.conn.commit()
        return True

    def get_hours(self):
        self.c.execute('SELECT a.full_name, SUM(h.hours) FROM hours h JOIN accounts a ON h.account_id = a.id GROUP BY a.full_name ORDER BY SUM(h.hours) DESC')
        return self.c.fetchall()

    def get_hours_for_user_last_week(self, account_id):
        today = datetime.now().date()
        monday = today - timedelta(days=today.weekday())
        start = monday - timedelta(days=7)
        end = monday - timedelta(days=1)
        self.c.execute('SELECT date, hours, shift FROM hours WHERE account_id = ? AND date BETWEEN ? AND ? ORDER BY date',
                       (account_id, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')))
        return self.c.fetchall()

    def get_hours_for_user_week(self, account_id, start_date, end_date):
        self.c.execute('SELECT date, hours, shift FROM hours WHERE account_id = ? AND date BETWEEN ? AND ? ORDER BY date',
                       (account_id, start_date, end_date))
        return self.c.fetchall()

    # ---- Статистика (без изменений) ----
    def count_wishes(self):
        self.c.execute('SELECT COUNT(*) FROM wishes')
        return self.c.fetchone()[0]

    def get_stats(self):
        return {
            'users': self.c.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],
            'wishes': self.c.execute('SELECT COUNT(*) FROM wishes').fetchone()[0],
            'schedule': self.c.execute('SELECT COUNT(*) FROM schedule').fetchone()[0],
            'hours': self.c.execute('SELECT COUNT(*) FROM hours').fetchone()[0],
            'unavailable': self.c.execute('SELECT COUNT(*) FROM unavailable_days').fetchone()[0]
        }

    # ---- Настройки ----
    def get_setting(self, key, default=None):
        self.c.execute('SELECT value FROM settings WHERE key = ?', (key,))
        row = self.c.fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        self.c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        self.conn.commit()

    def set_schedule_week_start(self, week_start):
        self.c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
                       ('schedule_week_start', week_start))
        self.conn.commit()

    def get_schedule_week_start(self):
        return self.get_setting('schedule_week_start')

    # ---- Ставка для зарплаты ----
    def set_hourly_rate(self, rate):
        self.set_setting('hourly_rate', str(rate))

    def get_hourly_rate(self):
        rate = self.get_setting('hourly_rate')
        return float(rate) if rate else 200.0

    # ---- Названия дополнительных полей ----
    def set_extra_label(self, num, label):
        self.set_setting(f'extra_label_{num}', label)

    def get_extra_label(self, num):
        return self.get_setting(f'extra_label_{num}')

    def get_all_extra_labels(self):
        return [self.get_extra_label(i) or f'Поле {i}' for i in range(1, 4)]

    # ---- Зарплата (исправленный метод) ----
    def calculate_salary_for_week(self, week_start_str):
        start_date = datetime.strptime(week_start_str, '%Y-%m-%d').date()
        end_date = start_date + timedelta(days=6)
        rate = self.get_hourly_rate()
        accounts = self.get_all_accounts()
        for acc in accounts:
            account_id = acc[0]
            if acc[3] == 'admin':
                continue
            fixed1, fixed2, fixed3 = self.get_employee_fixed_extras(account_id)
            self.c.execute('SELECT SUM(hours) FROM hours WHERE account_id = ? AND date BETWEEN ? AND ?',
                           (account_id, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')))
            total = self.c.fetchone()[0] or 0.0
            amount = total * rate

            self.c.execute('SELECT id FROM salaries WHERE account_id = ? AND week_start = ?',
                           (account_id, start_date.strftime('%Y-%m-%d')))
            row = self.c.fetchone()
            if row:
                salary_id = row[0]
                self.c.execute('''UPDATE salaries
                                  SET total_hours = ?, rate = ?, amount = ?, extra1 = ?, extra2 = ?, extra3 = ?
                                  WHERE id = ?''',
                               (total, rate, amount, fixed1, fixed2, fixed3, salary_id))
            else:
                self.c.execute('''INSERT INTO salaries
                                  (account_id, week_start, total_hours, rate, amount, extra1, extra2, extra3)
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                               (account_id, start_date.strftime('%Y-%m-%d'), total, rate, amount, fixed1, fixed2, fixed3))
        self.conn.commit()
        return True

    def get_all_salaries(self):
        self.c.execute('''SELECT s.id, a.full_name, s.week_start, s.total_hours, s.rate, s.amount,
                                 s.bonus, s.extra1, s.extra2, s.extra3
                          FROM salaries s
                          JOIN accounts a ON s.account_id = a.id
                          ORDER BY s.week_start DESC, a.full_name''')
        return self.c.fetchall()

    def update_salary_bonus(self, salary_id, bonus):
        self.c.execute('UPDATE salaries SET bonus = ? WHERE id = ?', (bonus, salary_id))
        self.conn.commit()
        return True

    def update_salary_extra(self, salary_id, field_num, value):
        if field_num == 1:
            self.c.execute('UPDATE salaries SET extra1 = ? WHERE id = ?', (value, salary_id))
        elif field_num == 2:
            self.c.execute('UPDATE salaries SET extra2 = ? WHERE id = ?', (value, salary_id))
        elif field_num == 3:
            self.c.execute('UPDATE salaries SET extra3 = ? WHERE id = ?', (value, salary_id))
        self.conn.commit()
        return True

    # ---- Авторасстановка часов за неделю (без изменений) ----
    def auto_add_hours_for_week(self, start_date_str):
        day_to_offset = {
            'понедельник': 0,
            'вторник': 1,
            'среда': 2,
            'четверг': 3,
            'пятница': 4,
            'суббота': 5,
            'воскресенье': 6
        }
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        schedule = self.get_schedule()
        for day, shift, account_id, full_name in schedule:
            if day not in day_to_offset:
                continue
            offset = day_to_offset[day]
            current_date = start_date + timedelta(days=offset)
            from config import SHIFT_HOURS
            hours = SHIFT_HOURS.get(shift, 0)
            if hours == 0:
                continue
            self.c.execute('SELECT id FROM hours WHERE account_id = ? AND date = ? AND shift = ?',
                           (account_id, current_date.strftime('%Y-%m-%d'), shift))
            if self.c.fetchone() is None:
                self.c.execute('INSERT INTO hours (account_id, date, hours, shift) VALUES (?, ?, ?, ?)',
                               (account_id, current_date.strftime('%Y-%m-%d'), hours, shift))
        self.conn.commit()
        return True

    def close(self):
        self.conn.close()
