# app/routes/booking.py
from flask import Blueprint, render_template, request, jsonify
from app import db
from app.models.stadium import Stadium
from app.models.booking import Booking
from app.models.settings import Settings
from datetime import datetime, date, time, timedelta

booking_bp = Blueprint('booking', __name__)

# ✅ ثابت: ساعة واحدة = 40000
BASE_PRICE_PER_HOUR = 40000


# -----------------------------
# ✅ Notifications Hook (SAFE)
# -----------------------------
def safe_notify_admins(
        title: str,
        message: str = "",
        url: str = "",
        ntype: str = "booking_created"
):
    """
    Safe notification hook.
    - Uses Notification system if available
    - Never breaks booking flow
    - Logs error for debugging
    """
    try:
        # import inside try so booking never breaks
        from app.services.notify import notify_admins

        notify_admins(
            title=title,
            message=message,
            url=url,
            ntype=ntype
        )
        return True

    except ImportError:
        # notify.py not created yet
        print("ℹ️ Notification service not installed yet.")
        return False

    except Exception as e:
        # Real error (DB, User model, etc.)
        print("❌ Notification error:", e)
        return False


# -----------------------------
# Helpers
# -----------------------------
def build_hours_list(opening: int, closing: int):
    """
    Build business hours list. Example: opening=12, closing=4 => [12..23] + [0..3]
    """
    opening = int(opening or 12)
    closing = int(closing or 4)
    hours = list(range(opening, 24)) + list(range(0, closing))
    return [h % 24 for h in hours]


def hours_covered(start_hour: int, duration: int):
    """
    Return list of hours covered by booking: length=duration, with wrap-around.
    Example start=23, duration=2 => [23, 0]
    """
    start_hour = int(start_hour) % 24
    duration = int(duration)
    return [(start_hour + i) % 24 for i in range(duration)]


def is_discount_hour(hour: int, discount_start: int, discount_end: int):
    """
    Discount window can cross midnight.
    If start < end: hour in [start, end] (INCLUSIVE)
    If start > end: hour in [start..23] or [0..end]

    ✅ FIXED: Changed to <= de to include the end hour (16:00)
    Example: discount_start=12, discount_end=16 will include hours 12,13,14,15,16
    """
    hour = int(hour) % 24
    ds = int(discount_start) % 24
    de = int(discount_end) % 24

    if ds == de:
        return False  # no discount window
    if ds < de:
        return ds <= hour <= de  # ✅ Changed < to <=
    return hour >= ds or hour <= de  # ✅ Changed < to <= (crosses midnight)


def booking_record_hours(booking: Booking):
    """
    Convert existing booking record to list of hours covered.
    We rely on your model fields: start_time + duration_hours.
    ✅ Safety: if duration_hours is 0/None -> treat as 1
    """
    start_h = booking.start_time.hour
    duration = booking.duration_hours or 1
    if duration < 1:
        duration = 1
    return hours_covered(start_h, duration)


def safe_duration(duration: int) -> int:
    """✅ Never allow 0 hours."""
    try:
        d = int(duration)
    except Exception:
        d = 1
    return 1 if d < 1 else d


# -----------------------------
# Pages
# -----------------------------
@booking_bp.route('/')
def booking_page():
    stadiums = Stadium.query.filter_by(is_active=True).all()
    settings = Settings.query.first()
    return render_template('booking/booking.html', stadiums=stadiums, settings=settings)


# -----------------------------
# ✅ API: Pending count (fix your console 404)
# called: GET /booking/api/pending-count
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

    existing_bookings = Booking.query.filter_by(stadium_id=stadium_id, date=booking_date_obj).filter(
        Booking.status.in_(['pending', 'confirmed'])
    ).all()

    booked_hours = set()
    pending_hours = set()

    for b in existing_bookings:
        hrs = booking_record_hours(b)
        for h in hrs:
            booked_hours.add(h)
            if b.status == 'pending':
                pending_hours.add(h)

    opening = settings.opening_hour or 12
    closing = settings.closing_hour or 4
    discount_start = settings.discount_start_hour or 12
    discount_end = settings.discount_end_hour or 16
    discount_percentage = settings.discount_percentage or 25

    price_per_hour = int(BASE_PRICE_PER_HOUR)
    hours = build_hours_list(opening, closing)

    slots = []
    for hour in hours:
        is_booked = hour in booked_hours
        is_pending = hour in pending_hours
        is_disc = is_discount_hour(hour, discount_start, discount_end)

        display_time = f"{hour:02d}:00"

        slot_price = price_per_hour
        if is_disc:
            slot_price = price_per_hour * (1 - discount_percentage / 100)

        slot_price = int(round(slot_price))

        slots.append({
            'hour': hour,
            'time': display_time,
            'is_booked': is_booked,
            'is_pending': is_pending,
            'is_discount': is_disc,
            'discount_percentage': discount_percentage if is_disc else 0,
            'price': slot_price
        })

    return jsonify(slots)


# -----------------------------
# API: Check availability (range)
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
        booking_date_obj = datetime.strptime(booking_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'available': False, 'message': 'Invalid date'}), 400

    start_hour = int(start_hour) % 24
    requested_hours = set(hours_covered(start_hour, duration))

    conflicts = Booking.query.filter_by(stadium_id=stadium_id, date=booking_date_obj).filter(
        Booking.status.in_(['pending', 'confirmed'])
    ).all()

    for b in conflicts:
        if requested_hours.intersection(set(booking_record_hours(b))):
            return jsonify({'available': False, 'message': 'Time slot already booked'}), 409

    return jsonify({'available': True, 'message': 'Slot is available'})


# -----------------------------
# API: Create booking (range)
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

        if booking_date < date.today():
            return jsonify({'success': False, 'message': 'Cannot book past dates'}), 400

        stadium = Stadium.query.get(stadium_id)
        if not stadium:
            return jsonify({'success': False, 'message': 'Stadium not found'}), 404

        requested_hours = set(hours_covered(start_hour, duration))
        conflicts = Booking.query.filter_by(stadium_id=stadium_id, date=booking_date).filter(
            Booking.status.in_(['pending', 'confirmed'])
        ).all()

        for b in conflicts:
            if requested_hours.intersection(set(booking_record_hours(b))):
                return jsonify({'success': False, 'message': 'Time slot already booked'}), 409

        start_dt = datetime.combine(booking_date, time(hour=start_hour, minute=0))
        end_dt = start_dt + timedelta(hours=duration)

        start_time_obj = start_dt.time()
        end_time_obj = end_dt.time()

        price_per_hour = int(BASE_PRICE_PER_HOUR)

        discount_percentage = settings.discount_percentage or 25
        discount_start = settings.discount_start_hour or 12
        discount_end = settings.discount_end_hour or 16

        original_price = int(price_per_hour * duration)

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
        applied_discount_percentage = discount_percentage if discounted_hours > 0 else 0

        new_booking = Booking(
            stadium_id=stadium_id,
            customer_name=data['customer_name'],
            customer_phone=data['customer_phone'],
            customer_email=data.get('customer_email', ''),
            date=booking_date,
            start_time=start_time_obj,
            end_time=end_time_obj,
            duration_hours=duration,
            original_price=original_price,
            discount_percentage=applied_discount_percentage,
            discount_amount=discount_amount,
            final_price=final_price,
            status='pending',
            notes=data.get('notes', '')
        )

        db.session.add(new_booking)
        db.session.commit()

        # ✅ Notify admins about new booking
        safe_notify_admins(
            title="New booking request",
            message=f"Booking #{new_booking.id} is pending approval",
            url=f"/admin/booking/{new_booking.id}",
            ntype="booking_created"
        )

        # ✅ IMPORTANT: do NOT send to Google Sheets here anymore.
        # It will be sent ONLY after admin approves in admin.py.

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