# -*- coding: utf-8 -*-

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from config import ADMIN_PASSWORD, SHIFT_HOURS, DAYS, SHIFTS, SECRET_KEY
from database import Database
from scheduler import Scheduler
from functools import wraps
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = SECRET_KEY

db = Database()
scheduler = Scheduler(db)

# ---- Вспомогательные функции ----
def get_week_dates(start_date=None):
    if start_date is None:
        start_date = datetime.now().date()
    monday = start_date - timedelta(days=start_date.weekday())
    return {day: (monday + timedelta(days=i)).strftime('%d.%m') for i, day in enumerate(DAYS)}

def get_last_week_range():
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(days=7)
    end = monday - timedelta(days=1)
    return start, end

# ---- Декораторы ----
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('🔑 Пожалуйста, войдите в систему', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('🔑 Пожалуйста, войдите в систему', 'error')
            return redirect(url_for('login'))
        user = db.get_account_by_id(session['user_id'])
        if not user or user['role'] != 'admin':
            flash('⛔ У вас нет прав администратора', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# ---- Вход, выход, регистрация (без изменений) ----
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = db.authenticate(username, password)
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            flash(f'✅ Добро пожаловать, {user["full_name"]}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('❌ Неверный логин или пароль', 'error')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('👋 Вы вышли из системы', 'success')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        full_name = request.form.get('full_name', '').strip()
        if not username or not password:
            flash('❌ Заполните все поля', 'error')
            return redirect(url_for('register'))
        if not full_name:
            full_name = username
        if db.create_account(username, password, full_name):
            flash('✅ Регистрация успешна! Теперь войдите.', 'success')
            return redirect(url_for('login'))
        else:
            flash('❌ Пользователь с таким логином уже существует', 'error')
            return redirect(url_for('register'))
    return render_template('register.html')

# ---- Главная ----
@app.route('/')
def index():
    stats = db.get_stats()
    user = None
    if 'user_id' in session:
        user = db.get_account_by_id(session['user_id'])
    return render_template('index.html', stats=stats, user=user)

# ---- Пожелания ----
@app.route('/wish', methods=['GET', 'POST'])
@login_required
def wish():
    user = db.get_account_by_id(session['user_id'])
    if request.method == 'POST':
        db.clear_wishes_for_user(user['id'])
        for day in DAYS:
            shift = request.form.get(f'wish_{day}')
            if shift and shift in SHIFTS:
                db.add_wish(user['id'], day, shift)
        flash('✅ Ваши пожелания сохранены!', 'success')
        return redirect(url_for('wish'))
    
    all_users = db.get_all_accounts()
    users = [u for u in all_users if u[3] != 'admin']
    wishes = db.get_wishes()
    user_wishes = {}
    for u in users:
        user_wishes[u[2]] = {}
    for name, day, shift in wishes:
        if name in user_wishes:
            user_wishes[name][day] = shift
    my_wishes = {}
    for name, day, shift in wishes:
        if name == user['full_name']:
            my_wishes[day] = shift
    return render_template('wish.html', days=DAYS, shifts=SHIFTS, user=user,
                           users=users, user_wishes=user_wishes, my_wishes=my_wishes,
                           SHIFT_HOURS=SHIFT_HOURS)

# ---- Недоступные дни ----
@app.route('/unavailable', methods=['GET', 'POST'])
@login_required
def unavailable():
    user = db.get_account_by_id(session['user_id'])
    if request.method == 'POST':
        selected_days = request.form.getlist('unavailable_days')
        for day in DAYS:
            db.remove_unavailable_day(user['id'], day)
        for day in selected_days:
            if day in DAYS:
                db.add_unavailable_day(user['id'], day)
        flash('✅ Настройки недоступных дней сохранены!', 'success')
        return redirect(url_for('unavailable'))
    unavailable = db.get_unavailable_days(user['id'])
    return render_template('unavailable.html', days=DAYS, unavailable=unavailable, user=user)

# ---- Расписание ----
@app.route('/schedule')
def view_schedule():
    user = None
    if 'user_id' in session:
        user = db.get_account_by_id(session['user_id'])
    published = db.get_setting('schedule_published', '0')
    if published != '1':
        if not user or user['role'] != 'admin':
            return render_template('schedule.html', schedule=None, user=user, not_published=True)
    schedule = db.get_schedule()
    all_users = db.get_all_accounts()
    users = [u for u in all_users if u[3] != 'admin']
    user_schedule = {}
    for u in users:
        user_schedule[u[2]] = {}
    for day, shift, account_id, full_name in schedule:
        if full_name in user_schedule:
            hours = SHIFT_HOURS.get(shift, 0)
            user_schedule[full_name][day] = hours

    week_start_str = db.get_schedule_week_start()
    if week_start_str:
        week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
    else:
        week_start = datetime.now().date()
    week_dates = get_week_dates(week_start)

    return render_template('schedule.html',
                           schedule=user_schedule,
                           user=user,
                           days=DAYS,
                           users=users,
                           not_published=False,
                           SHIFT_HOURS=SHIFT_HOURS,
                           week_dates=week_dates)

# ---- Часы ----
@app.route('/hours')
def view_hours():
    user = None
    if 'user_id' in session:
        user = db.get_account_by_id(session['user_id'])
    
    if not user:
        flash('❌ Сначала войдите в систему', 'error')
        return redirect(url_for('login'))
    
    if user['role'] == 'admin':
        hours = db.get_hours()
        return render_template('hours.html', hours=hours, user=user, is_admin=True)
    else:
        week_start_str = db.get_schedule_week_start()
        if week_start_str:
            week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
            week_end = week_start + timedelta(days=6)
            hours = db.get_hours_for_user_week(user['id'], week_start_str, week_end.strftime('%Y-%m-%d'))
            week_label = f"неделя {week_start.strftime('%d.%m.%Y')} – {week_end.strftime('%d.%m.%Y')}"
        else:
            hours = db.get_hours_for_user_last_week(user['id'])
            start, end = get_last_week_range()
            week_label = f"прошлая неделя {start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}"
        return render_template('hours.html', hours=hours, user=user, is_admin=False, week_label=week_label)

# ---- Админ-панель ----
@app.route('/admin')
@admin_required
def admin():
    stats = db.get_stats()
    wishes = db.get_wishes()
    schedule = db.get_schedule()
    hours = db.get_hours()
    users = db.get_all_accounts()
    user = db.get_account_by_id(session['user_id'])
    
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    default_start_date = monday.strftime('%Y-%m-%d')
    
    return render_template('admin.html',
                           stats=stats,
                           wishes=wishes,
                           schedule=schedule,
                           hours=hours,
                           users=users,
                           days=DAYS,
                           shifts=SHIFTS,
                           user=user,
                           default_start_date=default_start_date)

# ---- Действия админа (добавлены новые экшены для зарплаты) ----
@app.route('/admin/action', methods=['POST'])
@admin_required
def admin_action():
    action = request.form.get('action')
    if action == 'generate':
        week_start = request.form.get('week_start')
        if week_start:
            try:
                datetime.strptime(week_start, '%Y-%m-%d')
            except ValueError:
                flash('❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД.', 'error')
                return redirect(url_for('admin'))
        else:
            today = datetime.now().date()
            days_until_monday = (7 - today.weekday()) % 7
            week_start = (today + timedelta(days=days_until_monday)).strftime('%Y-%m-%d')
        result = scheduler.generate(week_start)
        if result:
            flash(f'✅ Расписание сгенерировано для недели {week_start}! (черновик)', 'success')
        else:
            flash('❌ Нет сотрудников! Добавьте их через регистрацию.', 'error')
    elif action == 'clear_wishes':
        count = db.count_wishes()
        db.clear_wishes()
        flash(f'🗑️ Очищено {count} пожеланий!', 'success')
    elif action == 'add_hours':
        full_name = request.form.get('full_name')
        date = request.form.get('date')
        hours = request.form.get('hours')
        shift = request.form.get('shift')
        if full_name and date and hours and shift:
            try:
                db.add_hours(full_name, date, float(hours), shift)
                flash(f'✅ Часы добавлены: {full_name} - {hours}ч ({shift})', 'success')
            except:
                flash('❌ Ошибка добавления часов', 'error')
        else:
            flash('❌ Заполните все поля', 'error')
    elif action == 'publish':
        db.set_setting('schedule_published', '1')
        week_start = db.get_schedule_week_start()
        if week_start:
            db.auto_add_hours_for_week(week_start)
        flash('✅ Расписание опубликовано! Часы за неделю добавлены.', 'success')
    elif action == 'set_rate':
        rate = request.form.get('hourly_rate')
        try:
            rate = float(rate)
            db.set_hourly_rate(rate)
            flash(f'✅ Почасовая ставка установлена: {rate} руб/час', 'success')
        except ValueError:
            flash('❌ Введите корректное число', 'error')
    elif action == 'calculate_salary':
        week_start = request.form.get('week_start')
        if not week_start:
            flash('❌ Укажите дату начала недели', 'error')
            return redirect(url_for('admin'))
        try:
            datetime.strptime(week_start, '%Y-%m-%d')
        except ValueError:
            flash('❌ Неверный формат даты', 'error')
            return redirect(url_for('admin'))
        db.calculate_salary_for_week(week_start)
        flash(f'✅ Зарплата за неделю {week_start} рассчитана!', 'success')
    return redirect(url_for('admin'))

# ---- Редактирование расписания ----
@app.route('/admin/edit_schedule', methods=['GET', 'POST'])
@admin_required
def edit_schedule():
    if request.method == 'POST':
        for key, value in request.form.items():
            if key.startswith('cell_'):
                parts = key.split('_', 1)
                if len(parts) != 2:
                    continue
                day_shift = parts[1]
                day, shift = day_shift.split('_', 1)
                if day in DAYS and shift in SHIFTS:
                    account_id = int(value) if value else None
                    if account_id == 0:
                        db.c.execute('DELETE FROM schedule WHERE day = ? AND shift = ?', (day, shift))
                        db.conn.commit()
                    else:
                        db.update_schedule_cell(day, shift, account_id)
        flash('✅ Расписание обновлено!', 'success')
        return redirect(url_for('edit_schedule'))
    all_users = db.get_all_accounts()
    users = [u for u in all_users if u[3] != 'admin']
    schedule = db.get_schedule()
    schedule_dict = {}
    for day, shift, account_id, full_name in schedule:
        schedule_dict[(day, shift)] = account_id
    user = db.get_account_by_id(session['user_id'])
    week_start_str = db.get_schedule_week_start()
    if week_start_str:
        week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
    else:
        week_start = datetime.now().date()
    week_dates = get_week_dates(week_start)
    return render_template('edit_schedule.html',
                           days=DAYS,
                           shifts=SHIFTS,
                           users=users,
                           schedule_dict=schedule_dict,
                           user=user,
                           week_dates=week_dates)

# ---- Авторасстановка часов ----
@app.route('/admin/auto_hours', methods=['POST'])
@admin_required
def auto_hours():
    start_date = request.form.get('start_date')
    if not start_date:
        flash('❌ Укажите дату начала недели (понедельник).', 'error')
        return redirect(url_for('admin'))
    try:
        datetime.strptime(start_date, '%Y-%m-%d')
    except ValueError:
        flash('❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД.', 'error')
        return redirect(url_for('admin'))
    db.auto_add_hours_for_week(start_date)
    flash(f'✅ Часы за неделю, начинающуюся с {start_date}, успешно добавлены!', 'success')
    return redirect(url_for('admin'))

# ---- Добавить часы за предыдущую неделю ----
@app.route('/admin/add_previous_week_hours', methods=['POST'])
@admin_required
def add_previous_week_hours():
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    previous_monday = monday - timedelta(days=7)
    start_date = previous_monday.strftime('%Y-%m-%d')
    db.auto_add_hours_for_week(start_date)
    flash(f'✅ Часы за предыдущую неделю ({start_date}) успешно добавлены!', 'success')
    return redirect(url_for('admin'))

# ---- Очистка всех часов ----
@app.route('/admin/clear_hours', methods=['POST'])
@admin_required
def clear_hours():
    db.c.execute('DELETE FROM hours')
    db.conn.commit()
    flash('✅ Все часы удалены!', 'success')
    return redirect(url_for('admin'))

# ---- Сброс привязки к неделе ----
@app.route('/admin/clear_week_start', methods=['POST'])
@admin_required
def clear_week_start():
    db.c.execute('DELETE FROM settings WHERE key = "schedule_week_start"')
    db.conn.commit()
    flash('✅ Привязка к неделе сброшена. Расписание показывает текущую неделю.', 'success')
    return redirect(url_for('admin'))

# ---- Полный сброс БД ----
@app.route('/admin/clear_all', methods=['POST'])
@admin_required
def clear_all():
    db.c.execute('DELETE FROM accounts')
    db.c.execute('DELETE FROM wishes')
    db.c.execute('DELETE FROM unavailable_days')
    db.c.execute('DELETE FROM schedule')
    db.c.execute('DELETE FROM hours')
    db.c.execute('DELETE FROM settings')
    db.conn.commit()
    flash('🗑️ ВСЕ ДАННЫЕ УДАЛЕНЫ! Перезапустите сервер для восстановления администратора.', 'warning')
    return redirect(url_for('admin'))

# ---- СТРАНИЦА ЗАРПЛАТЫ ----
@app.route('/salary')
@admin_required
def salary():
    all_salaries = db.get_all_salaries()
    rate = db.get_hourly_rate()
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    default_week_start = monday.strftime('%Y-%m-%d')
    users = db.get_all_accounts()
    employees = [(u[0], u[2]) for u in users if u[3] != 'admin']
    # Получаем названия дополнительных полей
    extra_labels = db.get_all_extra_labels()  # список из трёх строк
    return render_template('salary.html',
                           all_salaries=all_salaries,
                           rate=rate,
                           default_week_start=default_week_start,
                           employees=employees,
                           extra_labels=extra_labels)

# ---- ОБНОВЛЕНИЕ ПРЕМИИ (бонус) ----
@app.route('/admin/update_salary_bonus', methods=['POST'])
@admin_required
def update_salary_bonus():
    salary_id = request.form.get('salary_id')
    bonus = request.form.get('bonus')
    if not salary_id:
        flash('❌ Ошибка: ID записи не указан', 'error')
        return redirect(url_for('salary'))
    try:
        salary_id = int(salary_id)
        if bonus:
            bonus = float(bonus)
            db.update_salary_bonus(salary_id, bonus)
        flash('✅ Премия обновлена!', 'success')
    except ValueError:
        flash('❌ Введите корректное число', 'error')
    return redirect(url_for('salary'))

# ---- ОБНОВЛЕНИЕ ДОПОЛНИТЕЛЬНЫХ ПОЛЕЙ (extra1, extra2, extra3) ----
@app.route('/admin/update_extra', methods=['POST'])
@admin_required
def update_extra():
    salary_id = request.form.get('salary_id')
    field_num = request.form.get('field_num')  # '1', '2' или '3'
    value = request.form.get('value')
    if not salary_id or not field_num:
        flash('❌ Ошибка: не все данные', 'error')
        return redirect(url_for('salary'))
    try:
        salary_id = int(salary_id)
        field_num = int(field_num)
        if field_num not in (1, 2, 3):
            raise ValueError
        if value:
            value = float(value)
            db.update_salary_extra(salary_id, field_num, value)
        flash('✅ Дополнительное поле обновлено!', 'success')
    except ValueError:
        flash('❌ Введите корректное число', 'error')
    return redirect(url_for('salary'))

# ---- ОБНОВЛЕНИЕ НАЗВАНИЙ ДОПОЛНИТЕЛЬНЫХ ПОЛЕЙ ----
@app.route('/admin/update_extra_labels', methods=['POST'])
@admin_required
def update_extra_labels():
    label1 = request.form.get('label1', '').strip()
    label2 = request.form.get('label2', '').strip()
    label3 = request.form.get('label3', '').strip()
    if not label1 or not label2 or not label3:
        flash('❌ Названия не могут быть пустыми', 'error')
        return redirect(url_for('salary'))
    db.set_extra_label(1, label1)
    db.set_extra_label(2, label2)
    db.set_extra_label(3, label3)
    flash('✅ Названия полей обновлены!', 'success')
    return redirect(url_for('salary'))

# ---- ДОБАВЛЕНИЕ КОРРЕКТИРОВКИ (премия или доп. поле) ----
@app.route('/admin/add_custom_adjustment', methods=['POST'])
@admin_required
def add_custom_adjustment():
    employee_id = request.form.get('employee_id')
    week_start = request.form.get('week_start')
    adjustment_type = request.form.get('adjustment_type')  # 'bonus', 'extra1', 'extra2', 'extra3'
    amount = request.form.get('amount')
    if not employee_id or not week_start or not adjustment_type or not amount:
        flash('❌ Заполните все поля', 'error')
        return redirect(url_for('salary'))
    try:
        amount = float(amount)
        # Проверяем, есть ли запись зарплаты за эту неделю для сотрудника
        db.c.execute('SELECT id FROM salaries WHERE account_id = ? AND week_start = ?', (employee_id, week_start))
        row = db.c.fetchone()
        if not row:
            # Создаём запись с нулевыми часами
            rate = db.get_hourly_rate()
            db.c.execute('INSERT INTO salaries (account_id, week_start, total_hours, rate, amount) VALUES (?, ?, ?, ?, ?)',
                         (employee_id, week_start, 0, rate, 0))
            db.conn.commit()
            salary_id = db.c.lastrowid
        else:
            salary_id = row[0]
        # Обновляем соответствующее поле
        if adjustment_type == 'bonus':
            db.update_salary_bonus(salary_id, amount)
        elif adjustment_type == 'extra1':
            db.update_salary_extra(salary_id, 1, amount)
        elif adjustment_type == 'extra2':
            db.update_salary_extra(salary_id, 2, amount)
        elif adjustment_type == 'extra3':
            db.update_salary_extra(salary_id, 3, amount)
        flash(f'✅ Корректировка добавлена!', 'success')
    except ValueError:
        flash('❌ Введите корректную сумму', 'error')
    return redirect(url_for('salary'))

# ---- API ----
@app.route('/api/wishes')
def api_wishes():
    wishes = db.get_wishes()
    return jsonify([{'name': w[0], 'day': w[1], 'shift': w[2]} for w in wishes])

@app.route('/api/schedule')
def api_schedule():
    schedule = db.get_schedule()
    return jsonify([{'day': s[0], 'shift': s[1], 'name': s[3]} for s in schedule])

# ---- Запуск ----
if __name__ == '__main__':
    print("=" * 50)
    print("🌐 ВЕБ-БОТ ДЛЯ РАСПИСАНИЯ ЗАПУЩЕН!")
    print("=" * 50)
    print("📊 База данных: schedule.db")
    print("👤 Админ: admin / admin123")
    print("⏰ Смены: утро(7ч), день(12ч), вечер(5ч)")
    print("💰 Почасовая ставка: 200 руб/час (можно изменить в админке)")
    print("=" * 50)
    print("🌐 Откройте в браузере: http://127.0.0.1:5000")
    print("=" * 50)
    print("Нажмите Ctrl+C для остановки")
    app.run(host='0.0.0.0', port=5000, debug=True)
