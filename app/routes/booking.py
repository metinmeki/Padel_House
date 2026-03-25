from flask import Blueprint, render_template, request, jsonify
from app import db
from app.models.stadium import Stadium
from app.models.booking import Booking
from app.models.settings import Settings
from datetime import datetime, date, time, timedelta

booking_bp = Blueprint('booking', __name__)

BASE_PRICE_PER_HOUR = 40000


# -----------------------------
# Notifications Hook (SAFE)
# -----------------------------
def safe_notify_admins(
    title: str,
    message: str = "",
    url: str = "",
    ntype: str = "booking_created"
):
    try:
        from app.services.notify import notify_admins
        notify_admins(title=title, message=message, url=url, ntype=ntype)
        return True
    except ImportError:
        print("ℹ️ Notification service not installed yet.")
        return False
    except Exception as e:
        print("❌ Notification error:", e)
        return False


# -----------------------------
# Helpers
# -----------------------------
def build_hours_list(opening: int, closing: int):
    """
    opening=12, closing=4 => [12,13,...,23,0,1,2,3]
    """
    opening = int(opening or 12)
    closing = int(closing or 4)
    return list(range(opening, 24)) + list(range(0, closing))


def safe_duration(duration) -> int:
    try:
        d = int(duration)
    except Exception:
        d = 1
    return 1 if d < 1 else d


def hours_covered(start_hour: int, duration: int):
    start_hour = int(start_hour) % 24
    duration = safe_duration(duration)
    return [(start_hour + i) % 24 for i in range(duration)]


def is_discount_hour(hour: int, discount_start: int, discount_end: int):
    hour = int(hour) % 24
    ds = int(discount_start) % 24
    de = int(discount_end) % 24
    if ds == de:
        return False
    if ds < de:
        return ds <= hour <= de
    return hour >= ds or hour <= de


def booking_record_slots(booking: Booking):
    """
    Expand a booking into (date, hour) slots.
    date=2026-03-20, start=00:00, duration=2 => [(Mar20,0),(Mar20,1)]
    date=2026-03-20, start=23:00, duration=2 => [(Mar20,23),(Mar21,0)]
    """
    if not booking.start_time:
        return []
    start_dt = datetime.combine(booking.date, booking.start_time)
    duration = safe_duration(booking.duration_hours or 1)
    slots = []
    for i in range(duration):
        slot_dt = start_dt + timedelta(hours=i)
        slots.append((slot_dt.date(), slot_dt.hour))
    return slots


def get_midnight_save_date(booking_date_obj, start_hour: int, settings=None):
    """
    الساعات بعد منتصف الليل (0..closing) تُحفظ على اليوم التالي.
    مثال: user picks date=Mar19, hour=1 → saved as date=Mar20, start=01:00
    """
    if settings is None:
        settings = Settings.query.first()
    opening_hour = int(settings.opening_hour or 12) if settings else 12
    closing_hour = int(settings.closing_hour or 4) if settings else 4
    if opening_hour > closing_hour and int(start_hour) < closing_hour:
        return booking_date_obj + timedelta(days=1)
    return booking_date_obj


def get_blocking_bookings(stadium_id: int, booking_date_obj):
    """
    جلب الحجوزات التي تؤثر على اليوم المطلوب.
    نجلب اليوم السابق أيضاً لأن حجز 23:00 لمدة ساعتين يمتد لليوم التالي.
    """
    return Booking.query.filter(
        Booking.stadium_id == stadium_id,
        Booking.date.in_([
            booking_date_obj - timedelta(days=1),
            booking_date_obj,
        ]),
        Booking.status.in_(["pending", "confirmed", "pending_cancel"])
    ).all()


# -----------------------------
# Pages
# -----------------------------
@booking_bp.route('/')
def booking_page():
    stadiums = Stadium.query.filter_by(is_active=True).all()
    settings = Settings.query.first()
    return render_template('booking/booking.html', stadiums=stadiums, settings=settings)


# -----------------------------
# API: Pending count
# -----------------------------
@booking_bp.route('/api/pending-count', methods=['GET'])
def pending_count():
    count = Booking.query.filter_by(status='pending').count()
    return jsonify({'pending': count}), 200


# -----------------------------
# API: Availability
# -----------------------------
@booking_bp.route('/api/availability', methods=['GET'])
def get_availability():
    stadium_id = request.args.get('stadium_id', type=int)
    booking_date = request.args.get('date')
    if not stadium_id or not booking_date:
        return jsonify({'error': 'Missing stadium_id or date'}), 400
    return get_availability_slots(stadium_id, booking_date)


@booking_bp.route('/api/get-slots/<int:stadium_id>/<booking_date>', methods=['GET'])
def get_slots(stadium_id, booking_date):
    return get_availability_slots(stadium_id, booking_date)


def get_availability_slots(stadium_id, booking_date):
    settings = Settings.query.first()
    if not settings:
        return jsonify({'error': 'Settings not configured'}), 500

    try:
        booking_date_obj = datetime.strptime(booking_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    stadium = Stadium.query.get(stadium_id)
    if not stadium:
        return jsonify({'error': 'Stadium not found'}), 404

    opening = int(settings.opening_hour or 12)
    closing = int(settings.closing_hour or 4)
    discount_start = int(settings.discount_start_hour or 12)
    discount_end = int(settings.discount_end_hour or 16)
    discount_percentage = int(settings.discount_percentage or 25)
    price_per_hour = int(BASE_PRICE_PER_HOUR)

    # ✅ المنطق الصحيح:
    # كل ساعة في قائمة العرض لها "save_date" فعلي في قاعدة البيانات.
    # نبني خريطة: hour → real_date_in_db
    # ثم نفحص الحجوزات بناءً على (real_date, hour) وليس بشروط معقدة.

    hours = build_hours_list(opening, closing)

    # بناء خريطة hour → real_save_date
    hour_to_save_date = {}
    for h in hours:
        hour_to_save_date[h] = get_midnight_save_date(booking_date_obj, h, settings)

    # جمع كل التواريخ الفعلية المطلوبة
    all_save_dates = set(hour_to_save_date.values())
    # أضف اليوم السابق لأن حجز 23:00 قد يمتد
    all_save_dates.add(booking_date_obj - timedelta(days=1))

    existing_bookings = Booking.query.filter(
        Booking.stadium_id == stadium_id,
        Booking.date.in_(list(all_save_dates)),
        Booking.status.in_(["pending", "confirmed", "pending_cancel"])
    ).all()

    # بناء مجموعة (date, hour) لكل حالة
    confirmed_slots = set()
    pending_slots = set()
    pending_cancel_slots = set()

    for b in existing_bookings:
        for slot_date, slot_hour in booking_record_slots(b):
            key = (slot_date, slot_hour)
            if b.status == 'confirmed':
                confirmed_slots.add(key)
            elif b.status == 'pending':
                pending_slots.add(key)
            elif b.status == 'pending_cancel':
                pending_cancel_slots.add(key)

    slots = []
    for hour in hours:
        real_date = hour_to_save_date[hour]
        key = (real_date, hour)

        is_booked = key in confirmed_slots
        is_pending = key in pending_slots
        is_pending_cancel = key in pending_cancel_slots
        is_disc = is_discount_hour(hour, discount_start, discount_end)

        slot_price = price_per_hour
        if is_disc:
            slot_price = int(round(price_per_hour * (1 - discount_percentage / 100)))

        slots.append({
            'hour': hour,
            'time': f"{hour:02d}:00",
            'is_booked': is_booked,
            'is_pending': is_pending,
            'is_pending_cancel': is_pending_cancel,
            'is_discount': is_disc,
            'discount_percentage': discount_percentage if is_disc else 0,
            'price': slot_price
        })

    return jsonify(slots), 200


# -----------------------------
# API: Check availability
# -----------------------------
@booking_bp.route('/api/check-availability', methods=['POST'])
def check_availability():
    data = request.json or {}

    stadium_id = data.get('stadium_id')
    booking_date = data.get('date')
    start_hour = data.get('start_hour')
    duration = safe_duration(data.get('duration_hours', 1))

    if not stadium_id or not booking_date or start_hour is None:
        return jsonify({'available': False, 'message': 'Missing fields'}), 400

    try:
        stadium_id = int(stadium_id)
        booking_date_obj = datetime.strptime(booking_date, '%Y-%m-%d').date()
        start_hour = int(start_hour) % 24
    except ValueError:
        return jsonify({'available': False, 'message': 'Invalid input'}), 400

    settings = Settings.query.first()
    save_date = get_midnight_save_date(booking_date_obj, start_hour, settings)

    requested_start_dt = datetime.combine(save_date, time(hour=start_hour, minute=0))
    requested_slots = set()
    for i in range(duration):
        slot_dt = requested_start_dt + timedelta(hours=i)
        requested_slots.add((slot_dt.date(), slot_dt.hour))

    conflicts = get_blocking_bookings(stadium_id, save_date)
    for b in conflicts:
        if requested_slots.intersection(set(booking_record_slots(b))):
            return jsonify({'available': False, 'message': 'Time slot already booked'}), 409

    return jsonify({'available': True, 'message': 'Slot is available'}), 200


# -----------------------------
# API: Create booking
# -----------------------------
@booking_bp.route('/api/create-booking', methods=['POST'])
def create_booking():
    data = request.json or {}
    settings = Settings.query.first()

    if not settings:
        return jsonify({'success': False, 'message': 'Settings not configured'}), 500

    required_fields = ['stadium_id', 'date', 'start_hour', 'duration_hours', 'customer_name', 'customer_phone']
    for field in required_fields:
        if field not in data or data[field] in (None, ''):
            return jsonify({'success': False, 'message': f'Missing {field}'}), 400

    try:
        stadium_id = int(data['stadium_id'])
        booking_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        start_hour = int(data['start_hour']) % 24
        duration = safe_duration(data.get('duration_hours', 1))

        # ✅ التاريخ الفعلي للحفظ
        save_date = get_midnight_save_date(booking_date, start_hour, settings)

        if save_date < date.today():
            return jsonify({'success': False, 'message': 'Cannot book past dates'}), 400

        stadium = Stadium.query.get(stadium_id)
        if not stadium:
            return jsonify({'success': False, 'message': 'Stadium not found'}), 404

        requested_start_dt = datetime.combine(save_date, time(hour=start_hour, minute=0))
        requested_slots = set()
        for i in range(duration):
            slot_dt = requested_start_dt + timedelta(hours=i)
            requested_slots.add((slot_dt.date(), slot_dt.hour))

        conflicts = get_blocking_bookings(stadium_id, save_date)
        for b in conflicts:
            if requested_slots.intersection(set(booking_record_slots(b))):
                return jsonify({'success': False, 'message': 'Time slot already booked'}), 409

        start_dt = requested_start_dt
        end_dt = start_dt + timedelta(hours=duration)

        price_per_hour = int(BASE_PRICE_PER_HOUR)
        discount_percentage = int(settings.discount_percentage or 25)
        discount_start = int(settings.discount_start_hour or 12)
        discount_end = int(settings.discount_end_hour or 16)

        original_price = price_per_hour * duration
        final_price = 0.0
        discounted_hours = 0

        for h in hours_covered(start_hour, duration):
            if is_discount_hour(h, discount_start, discount_end):
                discounted_hours += 1
                final_price += price_per_hour * (1 - discount_percentage / 100)
            else:
                final_price += price_per_hour

        final_price = int(round(final_price))
        discount_amount = int(round(original_price - final_price))
        applied_discount = discount_percentage if discounted_hours > 0 else 0

        new_booking = Booking(
            stadium_id=stadium_id,
            customer_name=data['customer_name'],
            customer_phone=data['customer_phone'],
            customer_email=data.get('customer_email', ''),
            date=save_date,
            start_time=start_dt.time(),
            end_time=end_dt.time(),
            duration_hours=duration,
            original_price=original_price,
            discount_percentage=applied_discount,
            discount_amount=discount_amount,
            final_price=final_price,
            status='pending',
            notes=data.get('notes', ''),
            source='website'
        )

        db.session.add(new_booking)
        db.session.commit()

        safe_notify_admins(
            title="New booking request",
            message=f"Booking #{new_booking.id} is pending approval",
            url=f"/admin/booking/{new_booking.id}",
            ntype="booking_created"
        )

        return jsonify({
            'success': True,
            'message': 'تم استلام حجزك بنجاح! سيتواصل معك فريقنا قريباً للتأكيد',
            'message_en': 'Your booking has been received! Our team will contact you shortly to confirm.',
            'message_ku': 'حجزەکەت وەرگیرا! تیمەکەمان بەزووی پەیوەندیت پێوە دەکات بۆ پشتڕاستکردنەوە.',
            'booking_id': new_booking.id,
            'status': 'pending'
        }), 201

    except Exception as e:
        db.session.rollback()
        print(f"Booking error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# -----------------------------
# Confirmation page
# -----------------------------
@booking_bp.route('/confirmation/<int:booking_id>')
def confirmation(booking_id):
    booking = Booking.query.get(booking_id)
    if not booking:
        return render_template('404.html'), 404
    return render_template('booking/confirmation.html', booking=booking)