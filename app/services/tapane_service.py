import os
import requests
from datetime import datetime, timedelta, time

TAPANE_BASE_URL = os.getenv('TAPANE_BASE_URL', 'https://api.tapane.app/gateway/v1').rstrip('/')
TAPANE_API_KEY = os.getenv('TAPANE_API_KEY', '').strip()


def _headers():
    return {
        'X-API-Key': TAPANE_API_KEY,
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }


def _parse_response(response):
    try:
        return response.json()
    except Exception:
        return {'raw_response': response.text}


def _normalize_status_from_tapane(status: str) -> str:
    status = (status or '').strip().lower()
    mapping = {
        'pending': 'pending',
        'accepted': 'confirmed',
        'rejected': 'cancelled',
        'cancelled': 'cancelled',
        'completed': 'completed',
    }
    return mapping.get(status, 'pending')


def _normalize_status_to_tapane(status: str) -> str:
    status = (status or '').strip().lower()
    mapping = {
        'pending': 'pending',
        'pending_cancel': 'accepted',
        'confirmed': 'accepted',
        'cancelled': 'cancelled',
        'completed': 'completed',
    }
    return mapping.get(status, 'pending')


def ping_tapane():
    if not TAPANE_API_KEY:
        return False, {'error': 'Missing TAPANE_API_KEY'}

    url = f"{TAPANE_BASE_URL}/bookings?page=1&page_size=1"

    try:
        response = requests.get(url, headers=_headers(), timeout=15)
        return response.ok, {
            'status_code': response.status_code,
            'response': _parse_response(response)
        }
    except Exception as e:
        return False, {'error': str(e)}


def get_tapane_field_id(stadium):
    if not stadium:
        return ''

    mapped = os.getenv(f'TAPANE_FIELD_ID_{stadium.id}', '').strip()
    return mapped or str(stadium.id)


def build_tapane_booking_payload(booking):
    payload = {
        "field_id": get_tapane_field_id(booking.stadium),
        "date": booking.date.strftime('%Y-%m-%d') if booking.date else None,
        "customer_name": booking.customer_name,
        "customer_phone": booking.customer_phone,
    }

    if booking.start_time:
        start_hour = int(booking.start_time.hour) % 24
        duration = max(1, int(booking.duration_hours or 1))

        if duration <= 1:
            payload["hour"] = start_hour
        else:
            payload["hours"] = [((start_hour + i) % 24) for i in range(duration)]

    return payload


def create_tapane_booking(payload: dict):
    if not TAPANE_API_KEY:
        return False, {'error': 'Missing TAPANE_API_KEY'}

    url = f"{TAPANE_BASE_URL}/bookings"

    try:
        response = requests.post(url, json=payload, headers=_headers(), timeout=20)
        result = _parse_response(response)

        if response.ok:
            return True, result

        return False, {
            'status_code': response.status_code,
            'response': result
        }
    except Exception as e:
        return False, {'error': str(e)}


def update_tapane_booking_status(external_booking_id, status):
    if not TAPANE_API_KEY:
        return False, {'error': 'Missing TAPANE_API_KEY'}

    if not external_booking_id:
        return False, {'error': 'Missing external booking id'}

    url = f"{TAPANE_BASE_URL}/bookings/{external_booking_id}"
    payload = {"status": _normalize_status_to_tapane(status)}

    try:
        response = requests.patch(url, json=payload, headers=_headers(), timeout=20)
        result = _parse_response(response)

        if response.ok:
            return True, result

        return False, {
            'status_code': response.status_code,
            'response': result
        }
    except Exception as e:
        return False, {'error': str(e)}


def list_tapane_bookings(page=1, page_size=100, field_id=None, date=None, status=None):
    if not TAPANE_API_KEY:
        return False, {'error': 'Missing TAPANE_API_KEY'}

    params = {
        'page': page,
        'page_size': page_size,
    }

    if field_id not in (None, ''):
        params['field_id'] = str(field_id)
    if date not in (None, ''):
        params['date'] = str(date)
    if status not in (None, ''):
        params['status'] = str(status)

    url = f"{TAPANE_BASE_URL}/bookings"

    try:
        response = requests.get(url, headers=_headers(), params=params, timeout=20)
        result = _parse_response(response)

        if response.ok:
            return True, result

        return False, {
            'status_code': response.status_code,
            'response': result
        }
    except Exception as e:
        return False, {'error': str(e)}


def get_tapane_booking_details(booking_id):
    if not TAPANE_API_KEY:
        return False, {'error': 'Missing TAPANE_API_KEY'}

    if not booking_id:
        return False, {'error': 'Missing booking id'}

    url = f"{TAPANE_BASE_URL}/bookings/{booking_id}"

    try:
        response = requests.get(url, headers=_headers(), timeout=20)
        result = _parse_response(response)

        if response.ok:
            return True, result

        return False, {
            'status_code': response.status_code,
            'response': result
        }
    except Exception as e:
        return False, {'error': str(e)}


def extract_external_booking_id(result):
    if not isinstance(result, dict):
        return None

    data = result.get('data')

    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and first.get('id'):
            return str(first.get('id'))

    if isinstance(data, dict) and data.get('id'):
        return str(data.get('id'))

    for key in ['id', 'booking_id', 'external_booking_id', 'reference', 'uuid']:
        value = result.get(key)
        if value not in (None, ''):
            return str(value)

    return None


def extract_external_status(result, fallback='pending'):
    if not isinstance(result, dict):
        return fallback

    data = result.get('data')

    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and first.get('status'):
            return str(first.get('status'))

    if isinstance(data, dict) and data.get('status'):
        return str(data.get('status'))

    if result.get('status'):
        return str(result.get('status'))

    return fallback


def _extract_items_and_pagination(result):
    if not isinstance(result, dict):
        return [], {}

    data = result.get('data')

    if isinstance(data, dict):
        return data.get('items') or [], data.get('pagination') or {}

    if isinstance(data, list):
        return data, {}

    return result.get('items') or [], result.get('pagination') or {}


def _extract_customer_name(item):
    return (
        item.get('customer_name')
        or item.get('user_name')
        or item.get('name')
        or 'Tapane Customer'
    ).strip()


def _extract_customer_phone(item):
    return (
        item.get('customer_phone')
        or item.get('user_phone')
        or item.get('phone')
        or ''
    ).strip()


def _extract_booking_hours(item):
    if not isinstance(item, dict):
        return []

    hours = item.get('hours')
    if isinstance(hours, list) and hours:
        cleaned = []
        for h in hours:
            try:
                cleaned.append(int(h) % 24)
            except Exception:
                pass
        if cleaned:
            return cleaned

    hour = item.get('hour')
    if hour is not None and str(hour).strip() != '':
        try:
            return [int(hour) % 24]
        except Exception:
            return []

    return []


def _extract_duration_hours(item, hours_list):
    duration_hours = item.get('duration_hours')
    if duration_hours is not None and str(duration_hours).strip() != '':
        try:
            d = int(round(float(duration_hours)))
            return max(1, d)
        except Exception:
            pass

    duration_minutes = item.get('duration_minutes')
    if duration_minutes is not None and str(duration_minutes).strip() != '':
        try:
            minutes = int(duration_minutes)
            return max(1, int(round(minutes / 60.0)))
        except Exception:
            pass

    if hours_list:
        return max(1, len(hours_list))

    return 1


def sync_booking_to_tapane(booking):
    from app import db

    payload = build_tapane_booking_payload(booking)
    ok, result = create_tapane_booking(payload)

    if not ok:
        return False, result

    booking.external_booking_id = extract_external_booking_id(result) or booking.external_booking_id
    booking.external_status = extract_external_status(result, fallback='pending')
    booking.last_synced_at = datetime.utcnow()

    db.session.commit()
    return True, result


def sync_booking_status_to_tapane(booking, new_status):
    from app import db

    if not booking.external_booking_id:
        if new_status == 'confirmed':
            return sync_booking_to_tapane(booking)
        return False, {'error': 'Booking has no external_booking_id'}

    ok, result = update_tapane_booking_status(booking.external_booking_id, new_status)

    if not ok:
        return False, result

    booking.external_status = extract_external_status(
        result,
        fallback=_normalize_status_to_tapane(new_status)
    )
    booking.last_synced_at = datetime.utcnow()

    db.session.commit()
    return True, result


def sync_tapane_bookings_to_local(date=None, field_ids=None, page_size=100):
    from app import db
    from app.models.booking import Booking
    from app.models.stadium import Stadium

    if not TAPANE_API_KEY:
        return False, {'error': 'Missing TAPANE_API_KEY'}

    if not field_ids:
        stadiums = Stadium.query.order_by(Stadium.id.asc()).all()
        field_ids = [str(s.id) for s in stadiums]
    else:
        field_ids = [str(x) for x in field_ids]

    created_count = 0
    updated_count = 0
    seen_count = 0
    errors = []

    for field_id in field_ids:
        page = 1

        while True:
            ok, result = list_tapane_bookings(
                page=page,
                page_size=page_size,
                field_id=field_id,
                date=date
            )

            if not ok:
                errors.append({
                    'field_id': field_id,
                    'page': page,
                    'error': result
                })
                break

            items, pagination = _extract_items_and_pagination(result)

            if not items:
                break

            stadium = Stadium.query.filter_by(id=int(field_id)).first() if str(field_id).isdigit() else None
            if not stadium:
                errors.append({
                    'field_id': field_id,
                    'page': page,
                    'error': f'Local stadium not found for field_id={field_id}'
                })
                break

            for item in items:
                try:
                    seen_count += 1

                    tapane_id = str(item.get('id') or '').strip()
                    booking_date = str(item.get('date') or '').strip()

                    if not tapane_id or not booking_date:
                        continue

                    # Fetch full booking details because list API may be incomplete
                    ok_details, details = get_tapane_booking_details(tapane_id)
                    details_item = item

                    if ok_details and isinstance(details, dict):
                        data = details.get('data')
                        if isinstance(data, dict):
                            details_item = data

                    user_name = _extract_customer_name(details_item)
                    user_phone = _extract_customer_phone(details_item)

                    hours_list = _extract_booking_hours(details_item)
                    if not hours_list:
                        # fallback to list item if details endpoint still doesn't include hours
                        hours_list = _extract_booking_hours(item)

                    if not hours_list:
                        continue

                    hours_list = list(dict.fromkeys(int(h) % 24 for h in hours_list))

                    tapane_status = str(
                        details_item.get('status') or item.get('status') or 'pending'
                    ).strip().lower()

                    start_hour = int(hours_list[0]) % 24
                    duration_hours = len(hours_list)

                    date_obj = datetime.strptime(booking_date, '%Y-%m-%d').date()
                    start_dt = datetime.combine(date_obj, time(hour=start_hour, minute=0))
                    end_dt = start_dt + timedelta(hours=duration_hours)

                    local_status = _normalize_status_from_tapane(tapane_status)

                    booking = Booking.query.filter_by(
                        external_booking_id=tapane_id,
                        source='tapane'
                    ).first()

                    if booking:
                        if booking.status != 'pending_cancel':
                            booking.status = local_status

                        booking.stadium_id = stadium.id
                        booking.customer_name = user_name
                        booking.customer_phone = user_phone or booking.customer_phone or '-'
                        booking.date = date_obj
                        booking.start_time = start_dt.time()
                        booking.end_time = end_dt.time()
                        booking.duration_hours = duration_hours
                        booking.external_status = tapane_status
                        booking.last_synced_at = datetime.utcnow()

                        existing_notes = booking.notes or ''
                        import_note = '[Imported/updated from Tapane sync]'
                        if import_note not in existing_notes:
                            booking.notes = f"{existing_notes}\n{import_note}".strip()

                        updated_count += 1
                    else:
                        booking = Booking(
                            stadium_id=stadium.id,
                            customer_name=user_name,
                            customer_phone=user_phone or '-',
                            customer_email=None,
                            date=date_obj,
                            start_time=start_dt.time(),
                            end_time=end_dt.time(),
                            duration_hours=duration_hours,
                            original_price=0,
                            discount_percentage=0,
                            discount_amount=0,
                            final_price=0,
                            status=local_status,
                            notes='Imported from Tapane',
                            source='tapane',
                            external_booking_id=tapane_id,
                            external_status=tapane_status,
                            last_synced_at=datetime.utcnow()
                        )
                        db.session.add(booking)
                        created_count += 1

                except Exception as e:
                    errors.append({
                        'field_id': field_id,
                        'page': page,
                        'item': item,
                        'error': str(e)
                    })

            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                errors.append({
                    'field_id': field_id,
                    'page': page,
                    'error': f'Database commit failed: {str(e)}'
                })
                break

            total_pages = int(pagination.get('total_pages') or 1)
            current_page = int(pagination.get('page') or page)

            if current_page >= total_pages:
                break

            page += 1

    return True, {
        'created': created_count,
        'updated': updated_count,
        'seen': seen_count,
        'errors': errors
    }