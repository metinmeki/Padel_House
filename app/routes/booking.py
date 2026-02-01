# booking.py (routes) - Updated: New bookings are PENDING until admin approves
from flask import Blueprint, render_template, request, jsonify
from app import db
from app.models.stadium import Stadium
from app.models.booking import Booking
from app.models.settings import Settings
from app.services.google_sheets import send_booking_to_sheet
from datetime import datetime, date, time, timedelta
import json

booking_bp = Blueprint('booking', __name__)


# ===== GET BOOKING PAGE =====
@booking_bp.route('/')
def booking_page():
    stadiums = Stadium.query.filter_by(is_active=True).all()
    settings = Settings.query.first()
    return render_template('booking/booking.html', stadiums=stadiums, settings=settings)


# ===== API: GET TIME SLOTS (Original Route) =====
@booking_bp.route('/api/get-slots/<int:stadium_id>/<booking_date>', methods=['GET'])
def get_slots(stadium_id, booking_date):
    """
    Get available time slots for a specific stadium and date
    Returns: JSON array of time slots with availability status
    """
    return get_availability_slots(stadium_id, booking_date)


# ===== API: GET AVAILABILITY (New Route for Frontend) =====
@booking_bp.route('/api/availability', methods=['GET'])
def get_availability():
    """
    Get available time slots using query parameters
    Expected: ?stadium_id=1&date=2026-01-30
    """
    stadium_id = request.args.get('stadium_id', type=int)
    booking_date = request.args.get('date')

    if not stadium_id or not booking_date:
        return jsonify({'error': 'Missing stadium_id or date'}), 400

    return get_availability_slots(stadium_id, booking_date)


def get_availability_slots(stadium_id, booking_date):
    """
    Shared function to get available time slots
    """
    settings = Settings.query.first()

    if not settings:
        return jsonify({'error': 'Settings not configured'}), 500

    try:
        booking_date_obj = datetime.strptime(booking_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    # Check if stadium exists
    stadium = Stadium.query.get(stadium_id)
    if not stadium:
        return jsonify({'error': 'Stadium not found'}), 404

    # Get existing bookings for this date and stadium
    # Include PENDING bookings to block the slot until admin decides
    existing_bookings = Booking.query.filter_by(
        stadium_id=stadium_id
    ).filter(
        Booking.date == booking_date_obj,
        Booking.status.in_(['pending', 'confirmed'])  # Both block the slot
    ).all()

    # Mark booked hours
    booked_hours = set()
    pending_hours = set()  # Track pending separately for UI

    for booking in existing_bookings:
        # Handle both start_time as time object or start_hour as integer
        if hasattr(booking, 'start_time') and booking.start_time:
            start_h = booking.start_time.hour
        elif hasattr(booking, 'start_hour') and booking.start_hour is not None:
            start_h = booking.start_hour
        else:
            continue

        if hasattr(booking, 'end_time') and booking.end_time:
            end_h = booking.end_time.hour
        elif hasattr(booking, 'end_hour') and booking.end_hour is not None:
            end_h = booking.end_hour
        else:
            end_h = start_h + (booking.duration_hours or 1)

        # Handle overnight bookings
        if end_h == 0:
            end_h = 24

        for h in range(start_h, end_h):
            hour = h % 24
            booked_hours.add(hour)
            if booking.status == 'pending':
                pending_hours.add(hour)

    # Generate time slots
    slots = []
    opening = settings.opening_hour or 12  # Default 12
    closing = settings.closing_hour or 4  # Default 4
    discount_start = settings.discount_start_hour or 12
    discount_end = settings.discount_end_hour or 16
    price_per_hour = stadium.price_per_hour or settings.price_per_hour or 50000
    discount_percentage = settings.discount_percentage or 25

    # Build hours list (12 PM to 4 AM next day)
    hours = []
    for h in range(opening, 24):
        hours.append(h)
    for h in range(0, closing):
        hours.append(h)

    # Create slots
    for hour in hours:
        is_booked = hour in booked_hours
        is_pending = hour in pending_hours
        is_discount = discount_start <= hour < discount_end

        # Format time display
        display_time = f"{hour:02d}:00"

        # Calculate price
        if is_discount:
            slot_price = price_per_hour * (1 - discount_percentage / 100)
        else:
            slot_price = price_per_hour

        slot = {
            'hour': hour,
            'time': display_time,
            'is_booked': is_booked,
            'is_pending': is_pending,  # NEW: For UI to show different color
            'is_discount': is_discount,
            'discount_percentage': discount_percentage if is_discount else 0,
            'price': slot_price
        }
        slots.append(slot)

    return jsonify(slots)


# ===== API: CHECK AVAILABILITY =====
@booking_bp.route('/api/check-availability', methods=['POST'])
def check_availability():
    """
    Check if specific time slot is available
    Expected JSON: {stadium_id, date, start_hour, duration_hours}
    """
    data = request.json

    stadium_id = data.get('stadium_id')
    booking_date = data.get('date')
    start_hour = int(data.get('start_hour'))
    duration = int(data.get('duration_hours', 1))

    try:
        booking_date_obj = datetime.strptime(booking_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'available': False, 'message': 'Invalid date'}), 400

    # Check for conflicts (including PENDING bookings)
    conflicts = Booking.query.filter_by(
        stadium_id=stadium_id,
        date=booking_date_obj
    ).filter(
        Booking.status.in_(['pending', 'confirmed'])
    ).all()

    for booking in conflicts:
        if hasattr(booking, 'start_time') and booking.start_time:
            booked_start = booking.start_time.hour
        elif hasattr(booking, 'start_hour'):
            booked_start = booking.start_hour
        else:
            continue

        if hasattr(booking, 'end_time') and booking.end_time:
            booked_end = booking.end_time.hour if booking.end_time.hour != 0 else 24
        elif hasattr(booking, 'end_hour'):
            booked_end = booking.end_hour if booking.end_hour != 0 else 24
        else:
            booked_end = booked_start + (booking.duration_hours or 1)

        for h in range(start_hour, start_hour + duration):
            if booked_start <= h < booked_end:
                return jsonify({'available': False, 'message': 'Time slot already booked'}), 409

    return jsonify({'available': True, 'message': 'Slot is available'})


# ===== API: CREATE BOOKING =====
@booking_bp.route('/api/create-booking', methods=['POST'])
def create_booking():
    """
    Create new booking - STATUS IS NOW 'pending' UNTIL ADMIN APPROVES
    Expected JSON: {
        stadium_id, date, start_hour, duration_hours,
        customer_name, customer_phone, customer_email
    }
    """
    data = request.json
    settings = Settings.query.first()

    # Validation
    required_fields = ['stadium_id', 'date', 'start_hour', 'duration_hours',
                       'customer_name', 'customer_phone']

    for field in required_fields:
        if field not in data or not data[field]:
            return jsonify({'success': False, 'message': f'Missing {field}'}), 400

    try:
        # Parse data
        stadium_id = int(data['stadium_id'])
        booking_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        start_hour = int(data['start_hour'])
        duration = int(data['duration_hours'])

        # Check if date is valid (not in past)
        if booking_date < date.today():
            return jsonify({'success': False, 'message': 'Cannot book past dates'}), 400

        # Check stadium exists
        stadium = Stadium.query.get(stadium_id)
        if not stadium:
            return jsonify({'success': False, 'message': 'Stadium not found'}), 404

        # Calculate times
        start_time_obj = time(hour=start_hour, minute=0)
        end_hour = (start_hour + duration) % 24
        end_time_obj = time(hour=end_hour, minute=0)

        # Check availability (including pending bookings)
        conflicts = Booking.query.filter_by(
            stadium_id=stadium_id,
            date=booking_date
        ).filter(
            Booking.status.in_(['pending', 'confirmed'])
        ).all()

        for booking in conflicts:
            if hasattr(booking, 'start_time') and booking.start_time:
                booked_start = booking.start_time.hour
            elif hasattr(booking, 'start_hour'):
                booked_start = booking.start_hour
            else:
                continue

            if hasattr(booking, 'end_time') and booking.end_time:
                booked_end = booking.end_time.hour if booking.end_time.hour != 0 else 24
            elif hasattr(booking, 'end_hour'):
                booked_end = booking.end_hour if booking.end_hour != 0 else 24
            else:
                booked_end = booked_start + (booking.duration_hours or 1)

            for h in range(start_hour, start_hour + duration):
                if booked_start <= h < booked_end:
                    return jsonify({'success': False, 'message': 'Time slot already booked'}), 409

        # Calculate pricing
        price_per_hour = stadium.price_per_hour or settings.price_per_hour or 50000
        discount_percentage = settings.discount_percentage or 25
        is_discount = settings.discount_start_hour <= start_hour < settings.discount_end_hour

        original_price = price_per_hour * duration
        discount_amount = (original_price * discount_percentage / 100) if is_discount else 0
        final_price = original_price - discount_amount

        # ============================================
        # IMPORTANT: Status is now 'pending' by default
        # Admin must approve the booking
        # ============================================
        new_booking = Booking(
            stadium_id=stadium_id,
            customer_name=data['customer_name'],
            customer_phone=data['customer_phone'],
            customer_email=data.get('customer_email', ''),
            date=booking_date,
            duration_hours=duration,
            status='pending',  # <-- CHANGED FROM 'confirmed' TO 'pending'
            notes=data.get('notes', '')
        )

        # Set time fields based on model structure
        if hasattr(Booking, 'start_time'):
            new_booking.start_time = start_time_obj
            new_booking.end_time = end_time_obj
        if hasattr(Booking, 'start_hour'):
            new_booking.start_hour = start_hour
            new_booking.end_hour = end_hour

        # Set price fields based on model structure
        if hasattr(Booking, 'original_price'):
            new_booking.original_price = original_price
        if hasattr(Booking, 'base_price'):
            new_booking.base_price = original_price
        if hasattr(Booking, 'discount_percentage'):
            new_booking.discount_percentage = discount_percentage if is_discount else 0
        if hasattr(Booking, 'discount_amount'):
            new_booking.discount_amount = discount_amount
        if hasattr(Booking, 'final_price'):
            new_booking.final_price = final_price
        if hasattr(Booking, 'total_price'):
            new_booking.total_price = final_price

        db.session.add(new_booking)
        db.session.commit()

        # 🔔 Send to Google Sheets
        try:
            send_booking_to_sheet(new_booking)
        except Exception as e:
            print(f"Google Sheets error: {e}")

        return jsonify({
            'success': True,
            # Updated message to inform customer about pending status
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


# ===== API: GET BOOKING DETAILS =====
@booking_bp.route('/api/booking/<int:booking_id>', methods=['GET'])
def get_booking(booking_id):
    """Get specific booking details"""
    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found'}), 404

    return jsonify(booking.to_dict())


# ===== API: GET ALL BOOKINGS (Admin) =====
@booking_bp.route('/api/bookings', methods=['GET'])
def get_all_bookings():
    """Get all bookings (for admin dashboard)"""
    stadium_id = request.args.get('stadium_id', type=int)
    status = request.args.get('status')

    query = Booking.query

    if stadium_id:
        query = query.filter_by(stadium_id=stadium_id)

    if status:
        query = query.filter_by(status=status)

    bookings = query.order_by(Booking.date.desc()).all()

    return jsonify([booking.to_dict() for booking in bookings])


# ===== API: GET PENDING BOOKINGS COUNT =====
@booking_bp.route('/api/pending-count', methods=['GET'])
def get_pending_count():
    """Get count of pending bookings for notification badge"""
    count = Booking.query.filter_by(status='pending').count()
    return jsonify({'count': count})


# ===== API: CANCEL BOOKING =====
@booking_bp.route('/api/booking/<int:booking_id>/cancel', methods=['POST'])
def cancel_booking(booking_id):
    """Cancel a booking"""
    booking = Booking.query.get(booking_id)

    if not booking:
        return jsonify({'success': False, 'message': 'Booking not found'}), 404

    if booking.status == 'cancelled':
        return jsonify({'success': False, 'message': 'Booking already cancelled'}), 400

    booking.status = 'cancelled'
    db.session.commit()

    return jsonify({'success': True, 'message': 'Booking cancelled successfully'})


# ===== CONFIRMATION PAGE =====
@booking_bp.route('/confirmation/<int:booking_id>')
def confirmation(booking_id):
    """Show booking confirmation - Now shows PENDING status"""
    booking = Booking.query.get(booking_id)
    if not booking:
        return render_template('404.html'), 404

    return render_template('booking/confirmation.html', booking=booking)
