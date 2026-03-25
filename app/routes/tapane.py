from flask import Blueprint, request, jsonify
from datetime import datetime, time, timedelta
import os
import hmac
import json
import logging

from app import db
from app.models.booking import Booking
from app.models.stadium import Stadium
from app.models.settings import Settings

# ✅ File logging
try:
    import os as _os
    _os.makedirs('/var/log', exist_ok=True)
    logging.basicConfig(
        filename='/var/log/padel_webhook.log',
        level=logging.DEBUG,
        format='%(asctime)s %(message)s'
    )
except Exception:
    logging.basicConfig(level=logging.DEBUG)

tapane_bp = Blueprint('tapane', __name__)

BASE_PRICE_PER_HOUR = 40000


def verify_tapane_api_key() -> bool:
    expected_api_key = (os.getenv("TAPANE_INBOUND_API_KEY") or "").strip()
    received_api_key = (request.headers.get("X-API-Key") or "").strip()

    if not expected_api_key:
        return False

    return hmac.compare_digest(received_api_key, expected_api_key)


def find_stadium_by_field_id(field_id: str):
    field_id = (field_id or "").strip()

    if not field_id:
        return None

    if field_id.isdigit():
        stadium = Stadium.query.filter_by(id=int(field_id)).first()
        if stadium:
            return stadium

    return Stadium.query.filter_by(name=field_id).first()


def map_tapane_event_to_local_status(event_name: str) -> str:
    event_name = (event_name or "").strip().lower()

    mapping = {
        "booking.created": "pending",
        "booking.accepted": "confirmed",
        "booking.rejected": "cancelled",
        "booking.cancelled": "cancelled",
        "booking.completed": "completed",
    }
    return mapping.get(event_name, "pending")


def safe_duration(duration: int) -> int:
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


def calculate_booking_prices(start_hour: int, duration_hours: int):
    settings = Settings.query.first()
    price_per_hour = int(BASE_PRICE_PER_HOUR)
    duration_hours = max(1, int(duration_hours or 1))

    if not settings:
        original_price = int(price_per_hour * duration_hours)
        return {
            "original_price": original_price,
            "discount_percentage": 0,
            "discount_amount": 0,
            "final_price": original_price
        }

    discount_percentage = settings.discount_percentage or 25
    discount_start = settings.discount_start_hour or 12
    discount_end = settings.discount_end_hour or 16

    original_price = int(price_per_hour * duration_hours)

    final_price = 0.0
    discounted_hours = 0

    for h in hours_covered(start_hour, duration_hours):
        if is_discount_hour(h, discount_start, discount_end):
            discounted_hours += 1
            final_price += price_per_hour * (1 - discount_percentage / 100)
        else:
            final_price += price_per_hour

    final_price = int(round(final_price))
    discount_amount = int(round(original_price - final_price))
    applied_discount_percentage = discount_percentage if discounted_hours > 0 else 0

    return {
        "original_price": original_price,
        "discount_percentage": applied_discount_percentage,
        "discount_amount": discount_amount,
        "final_price": final_price
    }


def parse_start_hour(data: dict):
    start_hour = data.get("start_hour")
    if start_hour is not None and str(start_hour).strip() != "":
        try:
            return int(start_hour) % 24, 0
        except Exception:
            pass

    hours = data.get("hours")
    if isinstance(hours, list) and hours:
        try:
            parsed_hours = sorted(int(h) % 24 for h in hours)
            return parsed_hours[0], 0
        except Exception:
            pass

    hour = data.get("hour")
    if hour is not None and str(hour).strip() != "":
        try:
            return int(hour) % 24, 0
        except Exception:
            pass

    start_time_value = str(data.get("start_time") or "").strip()
    if not start_time_value:
        return None, None

    try:
        if ":" in start_time_value and "T" not in start_time_value:
            parts = start_time_value.split(":")
            return int(parts[0]) % 24, int(parts[1]) % 60
    except Exception:
        pass

    try:
        dt = datetime.fromisoformat(start_time_value.replace("Z", "+00:00"))
        return dt.hour, dt.minute
    except Exception:
        pass

    return None, None


def parse_duration_hours(data: dict) -> int:
    duration_hours = data.get("duration_hours")
    if duration_hours:
        try:
            return max(1, int(round(float(duration_hours))))
        except Exception:
            pass

    duration_minutes = data.get("duration_minutes")
    if duration_minutes:
        try:
            return max(1, int(round(int(duration_minutes) / 60)))
        except Exception:
            pass

    hours = data.get("hours")
    if isinstance(hours, list) and hours:
        try:
            parsed_hours = sorted(int(h) % 24 for h in hours)
            return max(1, len(parsed_hours))
        except Exception:
            pass

    return 1


def booking_record_slots(booking: Booking):
    if not booking.start_time:
        return []

    start_dt = datetime.combine(booking.date, booking.start_time)
    duration = safe_duration(booking.duration_hours or 1)

    slots = []
    for i in range(duration):
        slot_dt = start_dt + timedelta(hours=i)
        slots.append((slot_dt.date(), slot_dt.hour))

    return slots


def booking_matches_calendar_day(booking: Booking, target_date):
    matched_hours = []
    for slot_date, slot_hour in booking_record_slots(booking):
        if slot_date == target_date:
            matched_hours.append(slot_hour)
    return matched_hours


def build_tapane_availability(stadium_id: int, booking_date_obj):
    settings = Settings.query.first()
    if not settings:
        return None, "Settings not configured", 500

    opening = int(settings.opening_hour or 12)
    closing = int(settings.closing_hour or 4)

    if opening > closing:
        tapane_day_hours = set(list(range(opening, 24)) + list(range(0, closing)))
    else:
        tapane_day_hours = set(range(opening, closing))

    bookings = Booking.query.filter(
        Booking.stadium_id == stadium_id,
        Booking.date.in_([
            booking_date_obj - timedelta(days=1),
            booking_date_obj,
            booking_date_obj + timedelta(days=1),
        ]),
        Booking.status.in_(["pending", "pending_cancel", "confirmed"])
    ).all()

    taken_hours = set()

    for booking in bookings:
        for slot_date, slot_hour in booking_record_slots(booking):
            if slot_hour not in tapane_day_hours:
                continue

            if slot_hour >= opening:
                if slot_date == booking_date_obj:
                    taken_hours.add(slot_hour)
            else:
                if slot_date == booking_date_obj or slot_date == booking_date_obj + timedelta(days=1):
                    taken_hours.add(slot_hour)

    available_slots = [{"hour": h} for h in range(24) if h not in taken_hours]
    booked_slots = [{"hour": h} for h in range(24) if h in taken_hours]

    return {
        "success": True,
        "data": {
            "availability": {
                "field_id": str(stadium_id),
                "date": booking_date_obj.strftime("%Y-%m-%d"),
                "available_slots": available_slots,
                "booked_slots": booked_slots
            }
        }
    }, None, 200


def find_booking_by_explicit_ids(tapane_booking_id: str, local_booking_id: str):
    # 1. ابحث بـ local_booking_id
    if local_booking_id and local_booking_id.isdigit():
        booking = Booking.query.filter_by(id=int(local_booking_id)).first()
        if booking:
            return booking

    # 2. ابحث بـ tapane UUID في external_booking_id
    if tapane_booking_id:
        booking = Booking.query.filter_by(external_booking_id=tapane_booking_id).first()
        if booking:
            return booking

    # 3. إذا tapane_booking_id رقم → ابحث بـ local ID
    if tapane_booking_id and tapane_booking_id.isdigit():
        booking = Booking.query.filter_by(id=int(tapane_booking_id)).first()
        if booking:
            return booking

    return None


def find_existing_tapane_booking_by_slot(
    field_id: str,
    booking_date_str: str,
    parsed_hour: int
):
    if not field_id or not booking_date_str or parsed_hour is None:
        return None

    try:
        booking_date_obj = datetime.strptime(booking_date_str, "%Y-%m-%d").date()
    except Exception:
        return None

    stadium = find_stadium_by_field_id(field_id)
    if not stadium:
        return None

    candidates = Booking.query.filter(
        Booking.stadium_id == stadium.id,
        Booking.date.in_([booking_date_obj, booking_date_obj - timedelta(days=1)]),
        Booking.status.in_(["pending", "pending_cancel", "confirmed", "completed", "cancelled"])
    ).all()

    for booking in candidates:
        if booking.source != "tapane":
            continue

        for slot_date, slot_hour in booking_record_slots(booking):
            if slot_date == booking_date_obj and slot_hour == parsed_hour:
                return booking

    return None


def find_existing_website_booking_by_slot(
    stadium_id: int,
    booking_date_obj,
    parsed_hour: int,
    parsed_minute: int,
    duration_hours: int
):
    settings = Settings.query.first()
    opening_hour = int(settings.opening_hour or 12) if settings else 12
    closing_hour = int(settings.closing_hour or 4) if settings else 4

    # ✅ Use the same save_date logic as the website
    if opening_hour > closing_hour and parsed_hour < closing_hour:
        actual_save_date = booking_date_obj + timedelta(days=1)
    else:
        actual_save_date = booking_date_obj

    # ✅ Build the requested slots using save_date (same as website)
    requested_start_dt = datetime.combine(
        actual_save_date,
        time(hour=parsed_hour, minute=parsed_minute or 0)
    )
    requested_slots = set()
    for i in range(duration_hours):
        slot_dt = requested_start_dt + timedelta(hours=i)
        requested_slots.add((slot_dt.date(), slot_dt.hour))

    # ✅ Search using actual_save_date, not booking_date_obj
    candidates = Booking.query.filter(
        Booking.stadium_id == stadium_id,
        Booking.date == actual_save_date,
        Booking.status.in_(["pending", "confirmed", "pending_cancel"]),
        Booking.source == "website"
    ).all()

    for booking in candidates:
        existing_slots = set(booking_record_slots(booking))
        if requested_slots.intersection(existing_slots):
            return booking

    return None


def get_midnight_save_date(booking_date_obj, parsed_hour: int):
    settings = Settings.query.first()
    opening_hour = int(settings.opening_hour or 12) if settings else 12
    closing_hour = int(settings.closing_hour or 4) if settings else 4

    if opening_hour > closing_hour and parsed_hour < closing_hour:
        return booking_date_obj + timedelta(days=1)

    return booking_date_obj


def _is_tapane_uuid(value: str) -> bool:
    if not value:
        return False
    if value.isdigit():
        return False
    return '-' in value


@tapane_bp.route('/webhook', methods=['GET', 'POST'])
def tapane_webhook():
    if request.method == 'GET':
        action = (request.args.get("action") or "").strip().lower()
        field_id = (request.args.get("field_id") or request.args.get("external_field_id") or "").strip()
        booking_date = (request.args.get("date") or "").strip()

        if not action and field_id and booking_date:
            action = "availability"

        if action != "availability":
            return jsonify({"success": False, "message": "Unsupported GET action"}), 400

        if not field_id or not booking_date:
            return jsonify({"success": False, "message": "Missing field_id or date"}), 400

        try:
            booking_date_obj = datetime.strptime(booking_date, "%Y-%m-%d").date()
        except Exception:
            return jsonify({"success": False, "message": "Invalid date format"}), 400

        stadium = find_stadium_by_field_id(field_id)
        if not stadium:
            return jsonify({"success": False, "message": "Field mapping not found"}), 404

        payload, error_message, status_code = build_tapane_availability(stadium.id, booking_date_obj)
        if error_message:
            return jsonify({"success": False, "message": error_message}), status_code

        return jsonify(payload), 200

    if not verify_tapane_api_key():
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    # ✅ Log كل webhook لملف
    try:
        logging.info("WEBHOOK: " + json.dumps(data, ensure_ascii=False))
    except Exception:
        pass

    event_name = (data.get("event") or "").strip().lower()
    tapane_booking_id = str(data.get("booking_id") or "").strip()
    local_booking_id = str(data.get("external_booking_id") or "").strip()
    field_id = str(data.get("external_field_id") or data.get("field_id") or "").strip()

    customer_name = (data.get("customer_name") or "Tapane Customer").strip()
    customer_phone = (data.get("customer_phone") or "").strip()
    customer_email = (data.get("customer_email") or "").strip()
    notes = (data.get("notes") or "").strip()

    if not event_name or not tapane_booking_id:
        return jsonify({"success": False, "message": "Missing event or booking_id"}), 400

    local_status = map_tapane_event_to_local_status(event_name)
    parsed_hour, parsed_minute = parse_start_hour(data)
    duration_hours = parse_duration_hours(data)

    # -------------------------------------------------
    # booking.created
    # -------------------------------------------------
    if event_name == "booking.created":
        booking_date = str(data.get("date") or "").strip()

        if not field_id or not booking_date or parsed_hour is None:
            return jsonify({"success": False, "message": "Missing required fields"}), 400

        try:
            booking_date_obj = datetime.strptime(booking_date, "%Y-%m-%d").date()
        except Exception:
            return jsonify({"success": False, "message": "Invalid booking date"}), 400

        stadium = find_stadium_by_field_id(field_id)
        if not stadium:
            return jsonify({"success": False, "message": "Field mapping not found"}), 404

        save_date = get_midnight_save_date(booking_date_obj, parsed_hour)

        start_dt = datetime.combine(
            save_date,
            time(hour=parsed_hour, minute=parsed_minute or 0)
        )
        end_dt = start_dt + timedelta(hours=duration_hours)

        price_data = calculate_booking_prices(parsed_hour, duration_hours)

        booking = None

        if tapane_booking_id:
            booking = Booking.query.filter_by(external_booking_id=tapane_booking_id).first()

        if not booking and local_booking_id and local_booking_id.isdigit():
            candidate = Booking.query.filter_by(id=int(local_booking_id)).first()
            if candidate:
                booking = candidate

        if not booking:
            existing = find_existing_website_booking_by_slot(
                stadium_id=stadium.id,
                booking_date_obj=booking_date_obj,
                parsed_hour=parsed_hour,
                parsed_minute=parsed_minute or 0,
                duration_hours=duration_hours
            )
            if existing:
                booking = existing

        if booking:
            booking.stadium_id = stadium.id
            booking.customer_name = customer_name
            booking.customer_phone = customer_phone
            booking.customer_email = customer_email
            booking.duration_hours = duration_hours
            booking.original_price = price_data["original_price"]
            booking.discount_percentage = price_data["discount_percentage"]
            booking.discount_amount = price_data["discount_amount"]
            booking.final_price = price_data["final_price"]
            if notes:
                booking.notes = notes
            booking.status = "pending"
            booking.external_status = event_name
            booking.external_booking_id = tapane_booking_id
            if not booking.source:
                booking.source = "tapane"
            booking.last_synced_at = datetime.utcnow()
        else:
            booking = Booking(
                stadium_id=stadium.id,
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_email=customer_email,
                date=save_date,
                start_time=start_dt.time(),
                end_time=end_dt.time(),
                duration_hours=duration_hours,
                original_price=price_data["original_price"],
                discount_percentage=price_data["discount_percentage"],
                discount_amount=price_data["discount_amount"],
                final_price=price_data["final_price"],
                status="pending",
                notes=notes,
                source="tapane",
                external_booking_id=tapane_booking_id,
                external_status=event_name,
                last_synced_at=datetime.utcnow()
            )
            db.session.add(booking)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({
                "success": False,
                "message": "Database error",
                "error": str(e)
            }), 500

        # ✅ Tapane يحفظ هذا الـ id كـ external_booking_id في future events
        return jsonify({"id": str(booking.id)}), 200

    # -------------------------------------------------
    # All other events (accepted, cancelled, completed, rejected)
    # -------------------------------------------------
    booking = find_booking_by_explicit_ids(
        tapane_booking_id=tapane_booking_id,
        local_booking_id=local_booking_id
    )

    if not booking:
        booking = find_existing_tapane_booking_by_slot(
            field_id=field_id,
            booking_date_str=str(data.get("date") or "").strip(),
            parsed_hour=parsed_hour
        )

    if not booking:
        return jsonify({"success": False, "message": "Booking not found"}), 404

    # ✅ Website bookings: سمح بالتحديث فقط إذا كان الـ external_booking_id يطابق
    if booking.source == "website":
        is_matched_by_tapane_id = tapane_booking_id and booking.external_booking_id == tapane_booking_id
        is_matched_by_local_id = local_booking_id and local_booking_id.isdigit() and booking.id == int(local_booking_id)
        # ✅ إذا tapane_booking_id هو رقم ويطابق الـ local id
        is_matched_by_local_number = tapane_booking_id and tapane_booking_id.isdigit() and booking.id == int(
            tapane_booking_id)
        if not is_matched_by_tapane_id and not is_matched_by_local_id and not is_matched_by_local_number:
            return jsonify({"success": False, "message": "Refusing to update unrelated website booking"}), 409

    if data.get("date"):
        try:
            booking_date_obj = datetime.strptime(str(data.get("date")).strip(), "%Y-%m-%d").date()
            booking.date = get_midnight_save_date(booking_date_obj, parsed_hour) if parsed_hour is not None else booking_date_obj
        except Exception:
            pass

    if parsed_hour is not None:
        start_dt = datetime.combine(
            booking.date,
            time(hour=parsed_hour, minute=parsed_minute or 0)
        )
        end_dt = start_dt + timedelta(hours=duration_hours)
        booking.start_time = start_dt.time()
        booking.end_time = end_dt.time()
        booking.duration_hours = duration_hours

    # ✅ منطق الإلغاء الصحيح
    if event_name == "booking.cancelled":
        if booking.status in ("cancelled", "completed"):
            # مُلغى أو منتهي مسبقاً — لا تغيير
            pass
        else:
            # أي حالة أخرى (pending, confirmed, pending_cancel) → طلب إلغاء للأدمن
            booking.status = "pending_cancel"
            existing_notes = booking.notes or ""
            extra_note = "[Cancel request received from Tapane]"
            if extra_note not in existing_notes:
                booking.notes = f"{existing_notes}\n{extra_note}".strip()

    elif event_name == "booking.accepted":
        booking.status = "confirmed"

    elif event_name == "booking.completed":
        booking.status = "completed"

    elif event_name == "booking.rejected":
        booking.status = "cancelled"

    else:
        booking.status = local_status

    if customer_name:
        booking.customer_name = customer_name
    if customer_phone:
        booking.customer_phone = customer_phone
    if customer_email:
        booking.customer_email = customer_email
    if notes:
        booking.notes = notes

    booking.external_status = event_name

    # ✅ لا تُحدّث external_booking_id إلا إذا كان UUID حقيقي
    if _is_tapane_uuid(tapane_booking_id):
        booking.external_booking_id = tapane_booking_id

    if not booking.source:
        booking.source = "tapane"

    booking.last_synced_at = datetime.utcnow()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "message": "Database error",
            "error": str(e)
        }), 500

    return jsonify({
        "success": True,
        "message": "Booking updated successfully",
        "booking_id": booking.id,
        "new_status": booking.status,
        "source": booking.source
    }), 200