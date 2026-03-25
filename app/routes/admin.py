# app/routes/admin.py
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from functools import wraps
from app import db

from app.models.stadium import Stadium
from app.models.booking import Booking
from app.models.settings import Settings
from app.models.product import Product
from app.models.category import Category
from app.models.order import Order, OrderItem
from app.models.user import User
from app.models.expense import Expense
from datetime import datetime, date, timedelta, time
import os
import random
import io
from app.models.coach import Coach
from app.models.coach_training_request import CoachTrainingRequest

# Notifications
from app.services.notify import notify_admins
from sqlalchemy import func
from app.models.notification import Notification
from app.models.manual_debt import ManualDebt
from app.services.tapane_service import (
    sync_booking_to_tapane,
    sync_booking_status_to_tapane,
    sync_tapane_bookings_to_local,
)

# Services
from app.services.google_sheets import send_booking_to_sheet
from app.services.barcode_service import BarcodeService, XPrinterService

# ✅ Activity log
from app.models.activity_log import ActivityLog
from app.services.activity_service import log_activity

# POS
try:
    from app.models.pos_session import POSSession
except Exception:
    POSSession = None

# ✅ Image compression (Pillow)
try:
    from app.utils.image_tools import compress_product_image
except Exception:
    compress_product_image = None


def to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    v = str(value).strip().lower()
    return v in ("1", "true", "yes", "y", "on")


def generate_product_barcode():
    prefix = "743"
    timestamp = datetime.now().strftime("%y%m%d")
    random_part = ''.join([str(random.randint(0, 9)) for _ in range(3)])
    barcode_12 = f"{prefix}{timestamp}{random_part}"
    total = 0
    for i, digit in enumerate(barcode_12):
        if i % 2 == 0:
            total += int(digit)
        else:
            total += int(digit) * 3
    check_digit = (10 - (total % 10)) % 10
    return f"{barcode_12}{check_digit}"


admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/api/debug/ping', methods=['GET'])
@login_required
def debug_ping():
    return jsonify({"ok": True, "msg": "admin blueprint works"}), 200


UPLOAD_FOLDER = 'app/static/images/products'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
COACH_UPLOAD_FOLDER = 'app/static/images/coaches'


def save_coach_image(file):
    os.makedirs(COACH_UPLOAD_FOLDER, exist_ok=True)
    filename = secure_filename(file.filename)
    base = os.path.splitext(filename)[0]
    stamp = datetime.now().strftime('%Y%m%d%H%M%S')
    temp_name = f"temp_{stamp}_{filename}"
    temp_path = os.path.join(COACH_UPLOAD_FOLDER, temp_name)
    file.save(temp_path)
    final_name = f"{stamp}_{base}.webp"
    final_path = os.path.join(COACH_UPLOAD_FOLDER, final_name)
    if compress_product_image:
        try:
            out_path = compress_product_image(input_path=temp_path, output_path=final_path, max_size=(1200, 1200), quality=82, to_webp=True)
            try:
                os.remove(temp_path)
            except Exception:
                pass
            return f"images/coaches/{os.path.basename(out_path)}"
        except Exception:
            pass
    fallback_name = f"{stamp}_{filename}"
    fallback_path = os.path.join(COACH_UPLOAD_FOLDER, fallback_name)
    try:
        os.replace(temp_path, fallback_path)
    except Exception:
        fallback_name = temp_name
    return f"images/coaches/{fallback_name}"


def delete_coach_image(image_path):
    if not image_path:
        return
    image_path = str(image_path).strip()
    protected = {'images/coming-soon.jpg', 'images/coach.jpg', 'images/blackcourt.jpg'}
    if image_path in protected:
        return
    full_path = os.path.join('app/static', image_path.replace('images/', 'images/', 1))
    if os.path.exists(full_path):
        try:
            os.remove(full_path)
        except Exception:
            pass


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_product_image(file):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    filename = secure_filename(file.filename)
    base = os.path.splitext(filename)[0]
    stamp = datetime.now().strftime('%Y%m%d%H%M%S')
    temp_name = f"temp_{stamp}_{filename}"
    temp_path = os.path.join(UPLOAD_FOLDER, temp_name)
    file.save(temp_path)
    final_name = f"{stamp}_{base}.webp"
    final_path = os.path.join(UPLOAD_FOLDER, final_name)
    if compress_product_image:
        try:
            out_path = compress_product_image(input_path=temp_path, output_path=final_path, max_size=(900, 900), quality=78, to_webp=True)
            try:
                os.remove(temp_path)
            except Exception:
                pass
            return os.path.basename(out_path)
        except Exception:
            pass
    fallback_name = f"{stamp}_{filename}"
    fallback_path = os.path.join(UPLOAD_FOLDER, fallback_name)
    try:
        os.replace(temp_path, fallback_path)
    except Exception:
        fallback_name = temp_name
    return fallback_name


def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role != 'super_admin':
            flash('غير مصرح لك بهذا الإجراء', 'danger')
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def permission_required(permission_attr: str):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if getattr(current_user, "role", None) == "super_admin":
                return f(*args, **kwargs)
            if not getattr(current_user, permission_attr, False):
                flash("غير مصرح لك", "danger")
                return redirect(url_for('admin.dashboard'))
            return f(*args, **kwargs)
        return wrapper
    return decorator


# =====================================================================
# ✅ FIX 1: inject_admin_counts — فصل pending عن pending_cancel
# =====================================================================
@admin_bp.app_context_processor
def inject_admin_counts():
    if not current_user.is_authenticated:
        return {
            'pending_bookings_count': 0,
            'pending_orders_count': 0,
            'new_training_requests_count': 0,
            'cancel_requests_count': 0
        }

    # ✅ pending فقط — لا يشمل pending_cancel
    pending_bookings_count = Booking.query.filter(
        Booking.status == 'pending'
    ).count()

    pending_orders_count = Order.query.filter_by(status='pending').count()
    new_training_requests_count = CoachTrainingRequest.query.filter_by(status='new').count()

    # ✅ cancel requests عداد منفصل
    cancel_requests_count = Booking.query.filter_by(status='pending_cancel').count()

    return {
        'pending_bookings_count': pending_bookings_count,
        'pending_orders_count': pending_orders_count,
        'new_training_requests_count': new_training_requests_count,
        'cancel_requests_count': cancel_requests_count
    }


@admin_bp.route('/tapane/sync-bookings', methods=['POST', 'GET'])
@login_required
@permission_required('can_manage_bookings')
def sync_tapane_bookings():
    try:
        date_filter = (request.values.get('date') or '').strip()
        field_ids = request.values.getlist('field_id')
        if not field_ids:
            single_field = (request.values.get('field_id') or '').strip()
            if single_field:
                field_ids = [single_field]

        ok, result = sync_tapane_bookings_to_local(date=date_filter or None, field_ids=field_ids or None, page_size=100)

        if not ok:
            message = result.get('error') or 'Tapane sync failed'
            if request.is_json:
                return jsonify({'success': False, 'message': message, 'result': result}), 500
            flash(f'فشل مزامنة Tapane: {message}', 'danger')
            return redirect(url_for('admin.manage_bookings', source='tapane'))

        created_count = int(result.get('created', 0))
        updated_count = int(result.get('updated', 0))
        seen_count = int(result.get('seen', 0))
        errors = result.get('errors', [])
        msg = f'تمت مزامنة Tapane بنجاح ✅ | Seen: {seen_count} | Created: {created_count} | Updated: {updated_count}'
        if errors:
            msg += f' | Errors: {len(errors)}'

        try:
            log_activity(action="sync_tapane_bookings", entity_type="booking", entity_id=None,
                title="Synced Tapane bookings", note=msg, payment_method="system")
        except Exception as e:
            print("❌ Activity log error:", e)

        if request.is_json:
            return jsonify({'success': True, 'message': msg, 'result': result}), 200

        flash(msg, 'success')
        return redirect(url_for('admin.manage_bookings', source='tapane'))

    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f'خطأ أثناء مزامنة Tapane: {str(e)}', 'danger')
        return redirect(url_for('admin.manage_bookings', source='tapane'))


@admin_bp.route('/')
@login_required
def admin_home():
    if current_user.role == 'super_admin' or getattr(current_user, 'can_access_dashboard', False):
        return redirect(url_for('admin.dashboard'))
    elif getattr(current_user, 'can_manage_bookings', False):
        return redirect(url_for('admin.manage_bookings'))
    elif getattr(current_user, 'can_manage_products', False):
        return redirect(url_for('admin.manage_products'))
    elif getattr(current_user, 'can_manage_orders', False):
        return redirect(url_for('admin.manage_orders'))
    elif getattr(current_user, 'can_manage_stadiums', False):
        return redirect(url_for('admin.manage_stadiums'))
    elif getattr(current_user, 'can_view_reports', False):
        return redirect(url_for('admin.reports'))
    elif getattr(current_user, 'can_manage_settings', False):
        return redirect(url_for('admin.manage_settings'))
    else:
        flash('ليس لديك أي صلاحيات للوصول إلى لوحة التحكم', 'danger')
        return redirect(url_for('auth.logout'))


@admin_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'super_admin':
        if not getattr(current_user, 'can_access_dashboard', False):
            flash('غير مصرح لك بالوصول إلى لوحة التحكم', 'danger')
            return redirect(url_for('admin.admin_home'))

    total_bookings = Booking.query.count()
    total_revenue = db.session.query(db.func.sum(Booking.final_price)).filter(Booking.status.in_(['confirmed', 'completed'])).scalar() or 0
    today_bookings = Booking.query.filter(Booking.date == date.today()).count()
    today_revenue = db.session.query(db.func.sum(Booking.final_price)).filter(
        Booking.status.in_(['confirmed', 'completed']), Booking.date == date.today()).scalar() or 0
    pending_bookings = Booking.query.filter(Booking.status.in_(['pending', 'pending_cancel'])).count()
    total_products = Product.query.filter_by(is_active=True).count()
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status='pending').count()
    store_revenue = db.session.query(db.func.sum(Order.total_price)).filter(Order.status.in_(['confirmed', 'completed', 'delivered'])).scalar() or 0
    stadiums = Stadium.query.all()
    recent_bookings = Booking.query.order_by(Booking.created_at.desc()).limit(5).all()
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(5).all()
    pending_booking_list = Booking.query.filter_by(status='pending').order_by(Booking.created_at.desc()).limit(5).all()
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    today_logs = ActivityLog.query.filter(ActivityLog.created_at >= start, ActivityLog.created_at < end).order_by(ActivityLog.created_at.desc()).limit(30).all()

    return render_template('admin/dashboard.html',
        total_bookings=total_bookings, total_revenue=total_revenue,
        today_revenue=today_revenue, today_bookings=today_bookings,
        pending_bookings=pending_bookings, total_products=total_products,
        total_orders=total_orders, pending_orders=pending_orders,
        store_revenue=store_revenue, stadiums=stadiums,
        recent_bookings=recent_bookings, recent_orders=recent_orders,
        pending_booking_list=pending_booking_list, today_logs=today_logs)


# ========================================
# COACH TRAINING REQUESTS
# ========================================

@admin_bp.route('/training-requests')
@login_required
@permission_required('can_manage_bookings')
def manage_training_requests():
    from sqlalchemy import or_
    status_filter = request.args.get('status', 'all').strip()
    coach_filter = request.args.get('coach_id', 'all').strip()
    search_q = request.args.get('q', '').strip()
    query = CoachTrainingRequest.query
    if status_filter != 'all':
        query = query.filter(CoachTrainingRequest.status == status_filter)
    if coach_filter != 'all':
        try:
            query = query.filter(CoachTrainingRequest.coach_id == int(coach_filter))
        except (ValueError, TypeError):
            pass
    if search_q:
        like = f"%{search_q}%"
        query = query.filter(or_(CoachTrainingRequest.full_name.ilike(like), CoachTrainingRequest.phone.ilike(like)))
    requests_list = query.order_by(CoachTrainingRequest.created_at.desc()).all()
    coaches = Coach.query.order_by(Coach.id.asc()).all()
    return render_template('admin/training_requests.html', requests_list=requests_list, coaches=coaches,
        current_status=status_filter, current_coach=coach_filter, current_q=search_q)


@admin_bp.route('/api/training-request/<int:request_id>/status', methods=['POST'])
@login_required
@permission_required('can_manage_bookings')
def update_training_request_status(request_id):
    training_request = CoachTrainingRequest.query.get(request_id)
    if not training_request:
        return jsonify({'success': False, 'message': 'طلب التدريب غير موجود'}), 404
    data = request.json or {}
    new_status = (data.get('status') or '').strip().lower()
    allowed_statuses = ['new', 'contacted', 'scheduled', 'cancelled']
    if new_status not in allowed_statuses:
        return jsonify({'success': False, 'message': 'حالة غير صالحة'}), 400
    old_status = training_request.status
    training_request.status = new_status
    db.session.commit()
    try:
        log_activity(action="update_training_request_status", entity_type="coach_training_request",
            entity_id=training_request.id, title="Updated training request status",
            note=f"{training_request.full_name} | Old: {old_status} -> New: {new_status}", payment_method="system")
    except Exception as e:
        print("❌ Activity log error:", e)
    return jsonify({'success': True, 'message': 'تم تحديث حالة طلب التدريب بنجاح',
        'request_id': training_request.id, 'old_status': old_status, 'new_status': new_status})


@admin_bp.route('/api/training-request/<int:request_id>', methods=['DELETE'])
@login_required
@permission_required('can_manage_bookings')
def delete_training_request(request_id):
    training_request = CoachTrainingRequest.query.get(request_id)
    if not training_request:
        return jsonify({'success': False, 'message': 'طلب التدريب غير موجود'}), 404
    try:
        rid = training_request.id
        name = training_request.full_name
        db.session.delete(training_request)
        db.session.commit()
        try:
            log_activity(action="delete_training_request", entity_type="coach_training_request",
                entity_id=rid, title="Deleted training request", note=f"{name}", payment_method="system")
        except Exception as e:
            print("❌ Activity log error:", e)
        return jsonify({'success': True, 'message': 'تم حذف طلب التدريب بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ========================================
# PENDING BOOKINGS & CANCEL REQUESTS
# ========================================

def _map_local_status_to_external_event(status: str):
    status = (status or '').strip().lower()
    mapping = {
        'pending': 'booking.created',
        'confirmed': 'booking.accepted',
        'completed': 'booking.completed',
        'cancelled': 'booking.cancelled'
    }
    return mapping.get(status)


def _sync_booking_after_admin_status_change(booking, target_status):
    tapane_synced = False
    tapane_error = None
    try:
        if booking.source == 'website':
            if target_status == 'confirmed':
                if booking.external_booking_id:
                    ok, result = sync_booking_status_to_tapane(booking, target_status)
                else:
                    ok, result = sync_booking_to_tapane(booking)
            else:
                if booking.external_booking_id:
                    ok, result = sync_booking_status_to_tapane(booking, target_status)
                else:
                    return False, None
        elif booking.source == 'tapane':
            # ✅ الحجوزات من Tapane لا تحتاج sync عند القبول
            # Tapane هو اللي أرسل الحجز، يعرف حالته
            if target_status in ('cancelled', 'completed'):
                if booking.external_booking_id:
                    ok, result = sync_booking_status_to_tapane(booking, target_status)
                else:
                    return False, "Missing external_booking_id"
            else:
                return False, None

        tapane_synced = bool(ok)
        if not ok:
            tapane_error = str(result)
            print("❌ Tapane sync failed:", result)
            return tapane_synced, tapane_error

        if hasattr(booking, 'last_synced_at'):
            booking.last_synced_at = datetime.utcnow()
        mapped_external = _map_local_status_to_external_event(target_status)
        if mapped_external and hasattr(booking, 'external_status'):
            booking.external_status = mapped_external
        db.session.commit()
        return tapane_synced, None

    except Exception as e:
        tapane_error = str(e)
        print("❌ Tapane sync error:", e)
        return False, tapane_error


# =====================================================================
# ✅ FIX 2: pending_bookings — pending فقط، cancel requests منفصلة
# =====================================================================
@admin_bp.route('/pending-bookings')
@login_required
@permission_required('can_manage_bookings')
def pending_bookings():
    # ✅ pending فقط — لا يشمل pending_cancel
    bookings = Booking.query.filter(
        Booking.status == 'pending'
    ).order_by(Booking.created_at.desc()).all()
    stadiums = Stadium.query.all()
    return render_template('admin/pending_bookings.html', bookings=bookings, stadiums=stadiums)


# ✅ صفحة Cancel Requests المنفصلة
@admin_bp.route('/cancel-requests')
@login_required
@permission_required('can_manage_bookings')
def cancel_requests():
    # ✅ pending_cancel فقط
    bookings = Booking.query.filter(
        Booking.status == 'pending_cancel'
    ).order_by(Booking.created_at.desc()).all()
    return render_template('admin/cancel_requests.html', bookings=bookings)


@admin_bp.route('/api/booking/<int:booking_id>/approve', methods=['POST'])
@login_required
def approve_booking(booking_id):
    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'success': False, 'message': 'الحجز غير موجود'}), 404
    if booking.status != 'pending':
        return jsonify({'success': False, 'message': 'هذا الحجز ليس معلقاً'}), 400

    booking.status = 'confirmed'
    booking.confirmed_at = datetime.utcnow()
    if hasattr(booking, 'confirmed_by'):
        booking.confirmed_by = current_user.id

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'خطأ قاعدة البيانات: {str(e)}'}), 500

    tapane_synced, tapane_error = _sync_booking_after_admin_status_change(booking, 'confirmed')

    try:
        notify_admins(title="Booking approved ✅", message=f"Booking #{booking.id} confirmed for {booking.customer_name}",
            url=f"/admin/booking/{booking.id}", ntype="booking_approved")
    except Exception as e:
        print("❌ Notification error:", e)

    if not getattr(booking, 'sheet_sent', False):
        try:
            send_booking_to_sheet(booking)
            if hasattr(booking, 'sheet_sent'):
                booking.sheet_sent = True
            if hasattr(booking, 'sheet_sent_at'):
                booking.sheet_sent_at = datetime.utcnow()
            if hasattr(booking, 'sheet_last_error'):
                booking.sheet_last_error = None
            db.session.commit()
        except Exception as e:
            err = str(e)
            print("❌ Google Sheets error:", err)
            if hasattr(booking, 'sheet_last_error'):
                booking.sheet_last_error = err
                db.session.commit()
            return jsonify({'success': True, 'message': f'تم قبول الحجز ✅ لكن حدث خطأ في Google Sheets: {err}',
                'booking_id': booking.id, 'new_status': 'confirmed', 'sheet_sent': False,
                'tapane_synced': tapane_synced, 'tapane_error': tapane_error,
                'external_booking_id': booking.external_booking_id, 'external_status': booking.external_status}), 200

    try:
        log_activity(action="approve_booking", entity_type="booking", entity_id=booking.id,
            title="Approved booking",
            note=f"Customer: {booking.customer_name} | Stadium: {booking.stadium.name if booking.stadium else '-'} | Date: {booking.date}",
            amount=int(booking.final_price or 0), payment_method="booking")
    except Exception as e:
        print("❌ Activity log error:", e)

    return jsonify({'success': True, 'message': f'تم قبول حجز {booking.customer_name} بنجاح ✅',
        'booking_id': booking.id, 'new_status': 'confirmed', 'sheet_sent': True,
        'tapane_synced': tapane_synced, 'tapane_error': tapane_error,
        'external_booking_id': booking.external_booking_id, 'external_status': booking.external_status})


@admin_bp.route('/api/booking/<int:booking_id>/reject', methods=['POST'])
@login_required
def reject_booking(booking_id):
    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'success': False, 'message': 'الحجز غير موجود'}), 404
    if booking.status != 'pending':
        return jsonify({'success': False, 'message': 'هذا الحجز ليس معلقاً'}), 400

    data = request.json or {}
    rejection_reason = (data.get('reason') or '').strip()

    booking.status = 'cancelled'
    booking.confirmed_at = None
    if hasattr(booking, 'confirmed_by'):
        booking.confirmed_by = None
    if hasattr(booking, 'rejection_reason'):
        booking.rejection_reason = rejection_reason or None
    if rejection_reason:
        existing_notes = booking.notes or ''
        booking.notes = f"{existing_notes}\n[رفض] سبب الرفض: {rejection_reason}".strip()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'خطأ قاعدة البيانات: {str(e)}'}), 500

    tapane_synced, tapane_error = _sync_booking_after_admin_status_change(booking, 'cancelled')

    try:
        notify_admins(title="Booking rejected ❌",
            message=f"Booking #{booking.id} rejected for {booking.customer_name}. Reason: {rejection_reason or '-'}",
            url=f"/admin/booking/{booking.id}", ntype="booking_rejected")
    except Exception as e:
        print("❌ Notification error:", e)

    try:
        log_activity(action="reject_booking", entity_type="booking", entity_id=booking.id,
            title="Rejected booking", note=f"Customer: {booking.customer_name} | Reason: {rejection_reason or '-'}",
            amount=int(booking.final_price or 0), payment_method="booking")
    except Exception as e:
        print("❌ Activity log error:", e)

    return jsonify({'success': True, 'message': f'تم رفض حجز {booking.customer_name} ❌',
        'booking_id': booking.id, 'new_status': 'cancelled',
        'tapane_synced': tapane_synced, 'tapane_error': tapane_error,
        'external_booking_id': booking.external_booking_id, 'external_status': booking.external_status})


# ===== MANAGE BOOKINGS =====
from sqlalchemy import or_


@admin_bp.route('/bookings')
@login_required
@permission_required('can_manage_bookings')
def manage_bookings():
    status_filter = request.args.get('status', 'all')
    stadium_filter = request.args.get('stadium', 'all')
    source_filter = request.args.get('source', 'all')
    date_filter = request.args.get('date', '').strip()
    search_q = request.args.get('q', '').strip()
    query = Booking.query

    if status_filter and status_filter != 'all':
        query = query.filter(Booking.status == status_filter)
    if stadium_filter and stadium_filter != 'all':
        try:
            query = query.filter(Booking.stadium_id == int(stadium_filter))
        except (ValueError, TypeError):
            pass
    if source_filter and source_filter != 'all':
        if source_filter in ['website', 'tapane']:
            query = query.filter(Booking.source == source_filter)

    if date_filter:
        try:
            d = datetime.strptime(date_filter, '%Y-%m-%d').date()
            settings = Settings.query.first()
            closing_hour = int(settings.closing_hour or 4) if settings else 4
            query = query.filter(
                db.or_(
                    # Normal bookings on this day
                    db.and_(
                        Booking.date == d,
                        db.extract('hour', Booking.start_time) >= closing_hour
                    ),
                    # Midnight bookings: saved as next day but belong to this day
                    db.and_(
                        Booking.date == d + timedelta(days=1),
                        db.extract('hour', Booking.start_time) < closing_hour
                    )
                )
            )
        except ValueError:
            pass

    if search_q:
        like = f"%{search_q}%"
        query = query.filter(or_(Booking.customer_name.ilike(like), Booking.customer_phone.ilike(like)))

    bookings = query.order_by(Booking.date.desc(), Booking.created_at.desc()).all()
    stadiums = Stadium.query.all()

    return render_template('admin/bookings.html', bookings=bookings, stadiums=stadiums,
        current_status=status_filter, current_stadium=stadium_filter,
        current_source=source_filter, current_date=date_filter, current_q=search_q)


@admin_bp.route('/booking/<int:booking_id>')
@login_required
def booking_detail(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    return render_template('admin/booking_detail.html', booking=booking)


@admin_bp.route('/api/booking/<int:booking_id>/status', methods=['POST'])
@login_required
def update_booking_status(booking_id):
    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'success': False, 'message': 'Booking not found'}), 404

    data = request.json or {}
    new_status = (data.get('status') or '').strip().lower()
    reason = (data.get('reason') or '').strip()

    if new_status not in ['pending', 'pending_cancel', 'confirmed', 'completed', 'cancelled']:
        return jsonify({'success': False, 'message': 'Invalid status'}), 400

    old_status = booking.status
    booking.status = new_status

    if new_status == 'confirmed':
        if old_status in ['pending', 'pending_cancel']:
            booking.confirmed_at = datetime.utcnow()
            if hasattr(booking, 'confirmed_by'):
                booking.confirmed_by = current_user.id
        if old_status == 'pending_cancel':
            existing_notes = booking.notes or ''
            extra_note = '[Cancel request rejected by admin]'
            if extra_note not in existing_notes:
                booking.notes = f"{existing_notes}\n{extra_note}".strip()

    if new_status == 'pending_cancel':
        if not booking.confirmed_at:
            booking.confirmed_at = datetime.utcnow()
        if hasattr(booking, 'confirmed_by') and not getattr(booking, 'confirmed_by', None):
            booking.confirmed_by = current_user.id
        existing_notes = booking.notes or ''
        extra_note = '[Pending cancel request from Tapane]'
        if extra_note not in existing_notes:
            booking.notes = f"{existing_notes}\n{extra_note}".strip()

    if new_status == 'cancelled':
        booking.confirmed_at = None
        if hasattr(booking, 'confirmed_by'):
            booking.confirmed_by = None
        if reason:
            existing_notes = booking.notes or ''
            booking.notes = f"{existing_notes}\n[إلغاء بعد التأكيد] السبب: {reason}".strip()
        if hasattr(booking, 'rejection_reason') and reason:
            booking.rejection_reason = reason

    if new_status == 'completed':
        if not booking.confirmed_at:
            booking.confirmed_at = datetime.utcnow()
        if hasattr(booking, 'confirmed_by') and not getattr(booking, 'confirmed_by', None):
            booking.confirmed_by = current_user.id

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500

    tapane_synced, tapane_error = _sync_booking_after_admin_status_change(booking, new_status)

    return jsonify({'success': True, 'message': f'تم تحديث الحجز إلى {new_status}',
        'booking_id': booking.id, 'old_status': old_status, 'new_status': new_status,
        'tapane_synced': tapane_synced, 'tapane_error': tapane_error,
        'external_booking_id': booking.external_booking_id, 'external_status': booking.external_status})


@admin_bp.route('/api/booking/<int:booking_id>', methods=['GET'])
@login_required
def get_booking_api(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    return jsonify(booking.to_dict())


@admin_bp.route('/api/booking/<int:booking_id>', methods=['DELETE'])
@login_required
def delete_booking(booking_id):
    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'success': False, 'message': 'Booking not found'}), 404
    try:
        db.session.delete(booking)
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم حذف الحجز بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ========================================
# COACHES
# ========================================

@admin_bp.route('/coaches')
@login_required
@permission_required('can_manage_bookings')
def manage_coaches():
    coaches = Coach.query.order_by(Coach.created_at.desc()).all()
    return render_template('admin/coaches.html', coaches=coaches)


@admin_bp.route('/coaches/add', methods=['POST'])
@login_required
@permission_required('can_manage_bookings')
def add_coach():
    try:
        name = (request.form.get('name') or '').strip()
        bio = (request.form.get('bio') or '').strip() or None
        status = (request.form.get('status') or Coach.STATUS_AVAILABLE).strip()
        is_active = to_bool(request.form.get('is_active'), default=True)
        if not name:
            flash('اسم المدرب مطلوب', 'danger')
            return redirect(url_for('admin.manage_coaches'))
        if status not in [Coach.STATUS_AVAILABLE, Coach.STATUS_COMING_SOON]:
            status = Coach.STATUS_AVAILABLE
        coach = Coach(name=name, bio=bio, status=status, is_active=is_active)
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                coach.image = save_coach_image(file)
        db.session.add(coach)
        db.session.commit()
        try:
            log_activity(action="add_coach", entity_type="coach", entity_id=coach.id,
                title="Added coach", note=f"{coach.name} | Status: {coach.status}", payment_method="system")
        except Exception as e:
            print("❌ Activity log error:", e)
        flash('تمت إضافة المدرب بنجاح ✅', 'success')
        return redirect(url_for('admin.manage_coaches'))
    except Exception as e:
        db.session.rollback()
        flash(f'خطأ: {str(e)}', 'danger')
        return redirect(url_for('admin.manage_coaches'))


@admin_bp.route('/coaches/<int:coach_id>/edit', methods=['POST'])
@login_required
@permission_required('can_manage_bookings')
def edit_coach(coach_id):
    coach = Coach.query.get_or_404(coach_id)
    try:
        coach.name = (request.form.get('name') or coach.name).strip()
        coach.bio = (request.form.get('bio') or '').strip() or None
        status = (request.form.get('status') or coach.status).strip()
        if status in [Coach.STATUS_AVAILABLE, Coach.STATUS_COMING_SOON]:
            coach.status = status
        coach.is_active = to_bool(request.form.get('is_active'), default=bool(coach.is_active))
        remove_image = to_bool(request.form.get('remove_image'), default=False)
        if remove_image and coach.image:
            delete_coach_image(coach.image)
            coach.image = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                if coach.image:
                    delete_coach_image(coach.image)
                coach.image = save_coach_image(file)
        db.session.commit()
        try:
            log_activity(action="update_coach", entity_type="coach", entity_id=coach.id,
                title="Updated coach", note=f"{coach.name} | Status: {coach.status}", payment_method="system")
        except Exception as e:
            print("❌ Activity log error:", e)
        flash('تم تحديث المدرب بنجاح ✅', 'success')
        return redirect(url_for('admin.manage_coaches'))
    except Exception as e:
        db.session.rollback()
        flash(f'خطأ: {str(e)}', 'danger')
        return redirect(url_for('admin.manage_coaches'))


@admin_bp.route('/coaches/<int:coach_id>/delete', methods=['POST'])
@login_required
@permission_required('can_manage_bookings')
def delete_coach(coach_id):
    coach = Coach.query.get_or_404(coach_id)
    try:
        cid = coach.id
        cname = coach.name
        if coach.image:
            delete_coach_image(coach.image)
        db.session.delete(coach)
        db.session.commit()
        try:
            log_activity(action="delete_coach", entity_type="coach", entity_id=cid,
                title="Deleted coach", note=cname, payment_method="system")
        except Exception as e:
            print("❌ Activity log error:", e)
        flash('تم حذف المدرب بنجاح ✅', 'success')
        return redirect(url_for('admin.manage_coaches'))
    except Exception as e:
        db.session.rollback()
        flash(f'خطأ: {str(e)}', 'danger')
        return redirect(url_for('admin.manage_coaches'))


# ========================================
# PRODUCTS
# ========================================

@admin_bp.route('/products')
@login_required
@permission_required('can_manage_products')
def manage_products():
    products = Product.query.order_by(Product.created_at.desc()).all()
    categories = Category.query.filter_by(is_active=True).all()
    return render_template('admin/products.html', products=products, categories=categories)


@admin_bp.route('/api/product', methods=['POST'])
@login_required
def add_product_api():
    print(">>> add_product_api route HIT")
    try:
        name_ku = (request.form.get('name_ku') or '').strip()
        name_ar = (request.form.get('name_ar') or '').strip() or None
        name_en = (request.form.get('name_en') or '').strip() or None
        description_ku = (request.form.get('description_ku') or '').strip() or None
        description_ar = (request.form.get('description_ar') or '').strip() or None
        description_en = (request.form.get('description_en') or '').strip() or None
        cost_price = request.form.get('cost_price', 0)
        price = request.form.get('price')
        stock = request.form.get('stock', 0)
        category_id = request.form.get('category_id')
        show_in_website = to_bool(request.form.get('show_in_website'), default=False)
        show_in_pos = to_bool(request.form.get('show_in_pos'), default=False)
        is_active = to_bool(request.form.get('is_active'), default=True)

        # ✅ باركود الشركة الأصلي
        barcode_input = (request.form.get('barcode') or '').strip() or None

        if not name_ku or not price:
            return jsonify({'success': False, 'message': 'ناو و نرخ پێویستن / الاسم والسعر مطلوبان'}), 400
        try:
            cost_price_int = int(str(cost_price).replace(',', '').strip() or 0)
        except (ValueError, TypeError):
            cost_price_int = 0
        try:
            price_int = int(str(price).replace(',', '').strip() or 0)
        except (ValueError, TypeError):
            price_int = 0
        try:
            stock_int = int(str(stock).replace(',', '').strip() or 0)
        except (ValueError, TypeError):
            stock_int = 0

        product = Product(name_ku=name_ku, name_ar=name_ar, name_en=name_en,
            description_ku=description_ku, description_ar=description_ar, description_en=description_en,
            cost_price=cost_price_int, price=price_int, stock=stock_int,
            category_id=int(category_id) if category_id else None,
            show_in_website=show_in_website, show_in_pos=show_in_pos, is_active=is_active)

        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                product.image = save_product_image(file)

        db.session.add(product)
        db.session.flush()

        # ✅ إذا أدخل باركود الشركة استخدمه، وإلا ولّد تلقائي
        if barcode_input:
            product.barcode = barcode_input
        else:
            barcode_value, filename = BarcodeService.save_barcode_image(product.id, product.name_ku or product.name_ar or 'Product')
            product.barcode = barcode_value

        db.session.commit()

        try:
            log_activity(action="add_product", entity_type="product", entity_id=product.id,
                title="Added product",
                note=f"{product.name_ku or product.name_ar or product.name_en} | Cost: {product.cost_price} | Price: {product.price}",
                amount=int(product.price or 0), payment_method="store")
        except Exception as e:
            print("❌ Activity log error:", e)

        if to_bool(request.form.get('print_label'), default=False):
            try:
                XPrinterService.print_barcode_label(product.id, product.name_ku or product.name_ar, product.price, product.barcode)
            except Exception as e:
                print("❌ Print error:", e)

        return jsonify({'success': True, 'message': 'بەرهەم بە سەرکەوتوویی زیادکرا / تمت إضافة المنتج بنجاح',
            'product': {'id': product.id, 'name_ku': product.name_ku, 'name_ar': product.name_ar,
                'name_en': product.name_en, 'barcode': product.barcode, 'cost_price': product.cost_price,
                'price': product.price, 'stock': product.stock, 'category_id': product.category_id,
                'image': product.image, 'show_in_website': product.show_in_website,
                'show_in_pos': product.show_in_pos, 'is_active': product.is_active}}), 201
    except Exception as e:
        db.session.rollback()
        print("❌ add_product_api ERROR:", str(e))
        return jsonify({'success': False, 'message': f'هەڵە / خطأ: {str(e)}'}), 500


@admin_bp.route('/products/add', methods=['POST'])
@login_required
def add_product():
    if current_user.role not in ['admin', 'super_admin']:
        flash('Unauthorized', 'danger')
        return redirect(url_for('admin.dashboard'))
    try:
        # ✅ باركود الشركة الأصلي
        barcode_input = (request.form.get('barcode') or '').strip() or None

        product = Product(
            name_ku=request.form.get('name_ku'), name_ar=request.form.get('name_ar'),
            name_en=request.form.get('name_en'), description_ku=request.form.get('description_ku'),
            description_ar=request.form.get('description_ar'), description_en=request.form.get('description_en'),
            price=int(request.form.get('price', 0)), stock=int(request.form.get('stock', 0)),
            category_id=request.form.get('category_id') or None,
            show_in_website=to_bool(request.form.get('show_in_website'), default=False),
            show_in_pos=to_bool(request.form.get('show_in_pos'), default=False))

        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                product.image = save_product_image(file)

        db.session.add(product)
        db.session.flush()

        # ✅ إذا أدخل باركود الشركة استخدمه، وإلا ولّد تلقائي
        if barcode_input:
            product.barcode = barcode_input
        else:
            barcode_value, filename = BarcodeService.save_barcode_image(product.id, product.name_ku or 'Product')
            product.barcode = barcode_value

        db.session.commit()

        try:
            log_activity(action="add_product", entity_type="product", entity_id=product.id,
                title="Added product",
                note=f"{product.name_ku or product.name_ar or product.name_en} | Price: {product.price}",
                amount=int(product.price or 0), payment_method="store")
        except Exception as e:
            print("❌ Activity log error:", e)

        if to_bool(request.form.get('print_label'), default=False):
            try:
                success, message = XPrinterService.print_barcode_label(product.id, product.name_ku or 'Product', product.price, product.barcode)
                if not success:
                    flash(f'زیادکرا بەڵام چاپکردن سەرکەوتوو نەبوو: {message}', 'warning')
                else:
                    flash('بەرهەم زیادکرا و لێبڵ چاپکرا!', 'success')
            except Exception:
                flash('بەرهەم زیادکرا بەڵام چاپکردن سەرکەوتوو نەبوو', 'warning')
        else:
            flash('بەرهەم بە سەرکەوتوویی زیادکرا!', 'success')
        return redirect(url_for('admin.manage_products'))
    except Exception as e:
        db.session.rollback()
        flash(f'هەڵە: {str(e)}', 'danger')
        return redirect(url_for('admin.manage_products'))


@admin_bp.route('/products/<int:product_id>/print-barcode')
@login_required
def print_product_barcode(product_id):
    if current_user.role not in ['admin', 'super_admin']:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    product = Product.query.get_or_404(product_id)
    if not product.barcode:
        barcode_value, filename = BarcodeService.save_barcode_image(product.id, product.name_ku or 'Product')
        product.barcode = barcode_value
        db.session.commit()
    try:
        success, message = XPrinterService.print_barcode_label(product.id, product.name_ku or 'Product', product.price, product.barcode)
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/products/<int:product_id>/barcode-image')
@login_required
def get_barcode_image(product_id):
    product = Product.query.get_or_404(product_id)
    if not product.barcode:
        barcode_value, filename = BarcodeService.save_barcode_image(product.id, product.name_ku or 'Product')
        product.barcode = barcode_value
        db.session.commit()
    try:
        barcode_value, image_bytes = BarcodeService.generate_barcode(product.id, product.name_ku or 'Product')
        return send_file(io.BytesIO(image_bytes), mimetype='image/png', as_attachment=False)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/product/<int:product_id>', methods=['PUT', 'POST'])
@login_required
def update_product(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'}), 404
    try:
        if request.form:
            if 'name_ku' in request.form: product.name_ku = (request.form.get('name_ku') or '').strip()
            if 'name_ar' in request.form: product.name_ar = (request.form.get('name_ar') or '').strip() or None
            if 'name_en' in request.form: product.name_en = (request.form.get('name_en') or '').strip() or None
            if 'description_ku' in request.form: product.description_ku = (request.form.get('description_ku') or '').strip() or None
            if 'description_ar' in request.form: product.description_ar = (request.form.get('description_ar') or '').strip() or None
            if 'description_en' in request.form: product.description_en = (request.form.get('description_en') or '').strip() or None
            if 'category_id' in request.form:
                try:
                    product.category_id = int(request.form.get('category_id')) if request.form.get('category_id') else None
                except (ValueError, TypeError):
                    product.category_id = None
            if 'cost_price' in request.form:
                try: product.cost_price = int(request.form.get('cost_price') or 0)
                except (ValueError, TypeError): pass
            if 'price' in request.form:
                try: product.price = int(request.form.get('price') or 0)
                except (ValueError, TypeError): pass
            if 'stock' in request.form:
                stock_raw = request.form.get('stock')
                if stock_raw is not None and str(stock_raw).strip() != "":
                    try: product.stock = int(stock_raw)
                    except (ValueError, TypeError): pass
            product.is_active = to_bool(request.form.get('is_active'), default=bool(product.is_active))
            product.show_in_website = to_bool(request.form.get('show_in_website'), default=bool(product.show_in_website))
            product.show_in_pos = to_bool(request.form.get('show_in_pos'), default=bool(product.show_in_pos))

            # ✅ تحقق من تكرار الباركود قبل الحفظ
            if 'barcode' in request.form:
                new_barcode = (request.form.get('barcode') or '').strip() or None
                if new_barcode:
                    existing = Product.query.filter_by(barcode=new_barcode).first()
                    if existing and existing.id != product_id:
                        return jsonify({
                            'success': False,
                            'message': f'هذا الباركود مستخدم مسبقاً في منتج: {existing.name_ku or existing.name_ar or "#" + str(existing.id)}'
                        }), 409
                product.barcode = new_barcode

            if 'image' in request.files:
                file = request.files['image']
                if file and file.filename and allowed_file(file.filename):
                    if product.image:
                        old_image_path = os.path.join(UPLOAD_FOLDER, product.image)
                        if os.path.exists(old_image_path):
                            try: os.remove(old_image_path)
                            except Exception: pass
                    product.image = save_product_image(file)

        elif request.is_json:
            data = request.json or {}
            if 'name_ku' in data: product.name_ku = (data.get('name_ku') or '').strip()
            if 'name_ar' in data: product.name_ar = (data.get('name_ar') or '').strip() or None
            if 'name_en' in data: product.name_en = (data.get('name_en') or '').strip() or None
            if 'description_ku' in data: product.description_ku = (data.get('description_ku') or '').strip() or None
            if 'description_ar' in data: product.description_ar = (data.get('description_ar') or '').strip() or None
            if 'description_en' in data: product.description_en = (data.get('description_en') or '').strip() or None
            if 'category_id' in data: product.category_id = data.get('category_id')
            if 'cost_price' in data:
                try: product.cost_price = int(data.get('cost_price') or 0)
                except (ValueError, TypeError): pass
            if 'price' in data:
                try: product.price = int(data.get('price') or 0)
                except (ValueError, TypeError): pass
            if 'stock' in data:
                try: product.stock = int(data.get('stock'))
                except (ValueError, TypeError): pass
            if 'is_active' in data: product.is_active = bool(data.get('is_active'))
            if 'show_in_website' in data: product.show_in_website = bool(data.get('show_in_website'))
            if 'show_in_pos' in data: product.show_in_pos = bool(data.get('show_in_pos'))

            # ✅ تحقق من تكرار الباركود قبل الحفظ
            if 'barcode' in data:
                new_barcode = (data.get('barcode') or '').strip() or None
                if new_barcode:
                    existing = Product.query.filter_by(barcode=new_barcode).first()
                    if existing and existing.id != product_id:
                        return jsonify({
                            'success': False,
                            'message': f'هذا الباركود مستخدم مسبقاً في منتج: {existing.name_ku or existing.name_ar or "#" + str(existing.id)}'
                        }), 409
                product.barcode = new_barcode

        db.session.commit()
        return jsonify({'success': True, 'message': 'تم تحديث المنتج بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

from sqlalchemy import text


@admin_bp.route('/api/product/<int:product_id>/delete', methods=['DELETE', 'POST'])
@login_required
def delete_product(product_id):
    print("🔥 DELETE HIT product_id =", product_id)
    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'}), 404
    try:
        db.session.execute(text('DELETE FROM order_item WHERE product_id = :pid'), {'pid': product_id})
        try:
            db.session.execute(text('DELETE FROM pos_order_item WHERE product_id = :pid'), {'pid': product_id})
        except Exception as e:
            print("⚠️ pos_order_item skip:", e)
        if product.image:
            image_path = os.path.join(UPLOAD_FOLDER, product.image)
            if os.path.exists(image_path):
                try: os.remove(image_path)
                except Exception: pass
        db.session.delete(product)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Deleted ✅'})
    except Exception as e:
        db.session.rollback()
        print("❌ delete error:", e)
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/order/<int:order_id>', methods=['GET'])
@login_required
def get_order_api(order_id):
    order = Order.query.get_or_404(order_id)
    return jsonify(order.to_dict())


@admin_bp.route('/api/product/<int:product_id>/toggle', methods=['POST'])
@login_required
def toggle_product(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'}), 404
    product.is_active = not product.is_active
    db.session.commit()
    status = 'مفعل' if product.is_active else 'معطل'
    return jsonify({'success': True, 'message': f'تم تحديث المنتج: {status}', 'is_active': product.is_active})


@admin_bp.route('/print-barcodes')
@login_required
def print_barcodes():
    products = Product.query.filter_by(is_active=True).order_by(Product.name_ku).all()
    categories = Category.query.filter_by(is_active=True).all()
    return render_template('admin/print_barcodes.html', products=products, categories=categories)


@admin_bp.route('/api/product/<int:product_id>/regenerate-barcode', methods=['POST'])
@login_required
def regenerate_barcode(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'}), 404
    new_barcode = generate_product_barcode()
    while Product.query.filter_by(barcode=new_barcode).first():
        new_barcode = generate_product_barcode()
    product.barcode = new_barcode
    db.session.commit()
    return jsonify({'success': True, 'message': 'تم توليد باركود جديد', 'barcode': new_barcode})


# ========================================
# CATEGORIES
# ========================================

@admin_bp.route('/categories')
@login_required
def manage_categories():
    categories = Category.query.order_by(Category.created_at.desc()).all()
    return render_template('admin/categories.html', categories=categories)


@admin_bp.route('/api/category', methods=['POST'])
@login_required
def add_category():
    data = request.get_json() or {}
    name_ku = (data.get('name_ku') or '').strip()
    if not name_ku:
        return jsonify({'success': False, 'message': 'ناوی پۆل (کوردی) پێویستە'}), 400
    existing = Category.query.filter(func.lower(func.trim(Category.name_ku)) == name_ku.lower()).first()
    if existing:
        return jsonify({'success': False, 'message': 'ئەم پۆلە پێشتر تۆمارکراوە'}), 409
    try:
        category = Category(name_ku=data.get('name_ku'), name_ar=data.get('name_ar') or None,
            name_en=data.get('name_en') or None, description_ku=data.get('description_ku') or None,
            description_ar=data.get('description_ar') or None, description_en=data.get('description_en') or None,
            is_active=True, show_on_website=bool(data.get('show_on_website', True)), show_on_pos=bool(data.get('show_on_pos', True)))
        db.session.add(category)
        db.session.commit()
        try:
            log_activity(action="add_category", entity_type="category", entity_id=category.id,
                title="Added category", note=f"{category.name_ku or category.name_ar or category.name_en}", payment_method="store")
        except Exception as e:
            print("❌ Activity log error:", e)
        return jsonify({'success': True, 'message': 'پۆل بە سەرکەوتوویی زیاد کرا',
            'category_id': category.id, 'category': category.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/category/<int:category_id>', methods=['PUT'])
@login_required
def update_category(category_id):
    category = Category.query.get(category_id)
    if not category:
        return jsonify({'success': False, 'message': 'التصنيف غير موجود'}), 404
    data = request.get_json() or {}
    try:
        if 'name_ku' in data: category.name_ku = data['name_ku']
        if 'name_ar' in data: category.name_ar = data['name_ar'] or None
        if 'name_en' in data: category.name_en = data['name_en'] or None
        if 'description_ku' in data: category.description_ku = data['description_ku'] or None
        if 'description_ar' in data: category.description_ar = data['description_ar'] or None
        if 'description_en' in data: category.description_en = data['description_en'] or None
        if 'is_active' in data: category.is_active = bool(data['is_active'])
        if 'show_on_website' in data: category.show_on_website = bool(data['show_on_website'])
        if 'show_on_pos' in data: category.show_on_pos = bool(data['show_on_pos'])
        db.session.commit()
        try:
            log_activity(action="update_category", entity_type="category", entity_id=category.id,
                title="Updated category", note=f"{category.name_ku or category.name_ar or category.name_en}", payment_method="store")
        except Exception as e:
            print("❌ Activity log error:", e)
        return jsonify({'success': True, 'message': 'تم تحديث التصنيف بنجاح', 'category': category.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/category/<int:category_id>', methods=['DELETE'])
@login_required
def delete_category(category_id):
    category = Category.query.get(category_id)
    if not category:
        return jsonify({'success': False, 'message': 'التصنيف غير موجود'}), 404
    if getattr(category, 'products', None) and category.products:
        return jsonify({'success': False, 'message': 'لا يمكن حذف تصنيف يحتوي على منتجات'}), 409
    try:
        cid = category.id
        cname = category.name_ku or category.name_ar or category.name_en
        db.session.delete(category)
        db.session.commit()
        try:
            log_activity(action="delete_category", entity_type="category", entity_id=cid,
                title="Deleted category", note=f"{cname}", payment_method="store")
        except Exception as e:
            print("❌ Activity log error:", e)
        return jsonify({'success': True, 'message': 'تم حذف التصنيف بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ========================================
# ORDERS
# ========================================

@admin_bp.route('/orders')
@login_required
def manage_orders():
    status_filter = request.args.get('status', 'all')
    delivery_filter = request.args.get('delivery', 'all')
    date_filter = (request.args.get('date') or '').strip()
    q = (request.args.get('q') or '').strip()
    query = Order.query
    if status_filter and status_filter != 'all':
        query = query.filter(Order.status == status_filter)
    if delivery_filter and delivery_filter != 'all':
        query = query.filter(Order.delivery_method == delivery_filter)
    if date_filter:
        try:
            d = datetime.strptime(date_filter, '%Y-%m-%d').date()
            start_dt = datetime.combine(d, datetime.min.time())
            end_dt = start_dt + timedelta(days=1)
            query = query.filter(Order.created_at >= start_dt, Order.created_at < end_dt)
        except ValueError:
            pass
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Order.customer_name.ilike(like), Order.customer_phone.ilike(like)))
    orders = query.order_by(Order.created_at.desc()).all()
    return render_template('admin/orders.html', orders=orders, current_status=status_filter,
        current_delivery=delivery_filter, current_date=date_filter, current_q=q)


@admin_bp.route('/order/<int:order_id>')
@login_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('admin/order_detail.html', order=order)


@admin_bp.route('/api/order/<int:order_id>/status', methods=['POST'])
@login_required
def update_order_status(order_id):
    order = Order.query.get(order_id)
    if not order:
        return jsonify({'success': False, 'message': 'الطلب غير موجود'}), 404
    data = request.json or {}
    new_status = (data.get('status') or '').strip()
    if new_status not in ['pending', 'confirmed', 'processing', 'delivered', 'cancelled']:
        return jsonify({'success': False, 'message': 'حالة غير صالحة'}), 400
    old_status = order.status
    if new_status == 'cancelled' and old_status != 'cancelled':
        for item in order.items:
            if item.product and hasattr(item.product, "stock") and item.product.stock is not None:
                item.product.stock += int(item.quantity or 0)
    order.status = new_status
    db.session.commit()
    try:
        if new_status == 'confirmed' and old_status != 'confirmed':
            notify_admins(title="Order confirmed ✅",
                message=f"Order #{order.id} confirmed for {order.customer_name} ({order.customer_phone})",
                url=f"/admin/order/{order.id}", ntype="order_confirmed")
        elif new_status == 'cancelled' and old_status != 'cancelled':
            notify_admins(title="Order cancelled ❌",
                message=f"Order #{order.id} cancelled for {order.customer_name} ({order.customer_phone})",
                url=f"/admin/order/{order.id}", ntype="order_cancelled")
    except Exception as e:
        print("❌ Notification error:", e)
    if new_status == 'confirmed' and old_status != 'confirmed':
        sheet_already_sent = bool(getattr(order, "sheet_sent", False))
        if not sheet_already_sent:
            try:
                items_list = []
                for it in (order.items or []):
                    pname = "-"
                    try:
                        if it.product:
                            if hasattr(it.product, "get_name"):
                                pname = it.product.get_name('ku')
                            else:
                                pname = getattr(it.product, "name_ku", getattr(it.product, "name_ar", getattr(it.product, "name_en", "Product")))
                    except Exception:
                        pass
                    items_list.append(f"{pname} x{int(it.quantity or 0)}")
                items_str = " | ".join(items_list)
                from app.services.google_sheets import send_order_to_sheet
                send_order_to_sheet(order, items_str)
                if hasattr(order, "sheet_sent"): order.sheet_sent = True
                if hasattr(order, "sheet_sent_at"): order.sheet_sent_at = datetime.utcnow()
                if hasattr(order, "sheet_last_error"): order.sheet_last_error = None
                db.session.commit()
            except Exception as e:
                print("❌ Google Sheets error:", e)
                if hasattr(order, "sheet_last_error"):
                    order.sheet_last_error = str(e)
                    db.session.commit()
    try:
        log_activity(action="update_order_status", entity_type="order", entity_id=order.id,
            title="Order status changed", note=f"Old: {old_status} → New: {new_status}",
            amount=int(order.total_price or 0), payment_method="store")
    except Exception as e:
        print("❌ Activity log error:", e)
    return jsonify({'success': True, 'message': 'تم تحديث الطلب بنجاح', 'new_status': new_status})


@admin_bp.route('/api/order/<int:order_id>', methods=['DELETE'])
@login_required
def delete_order(order_id):
    order = Order.query.get(order_id)
    if not order:
        return jsonify({'success': False, 'message': 'الطلب غير موجود'}), 404
    try:
        if order.status != 'cancelled':
            for item in order.items:
                if item.product:
                    item.product.stock += item.quantity
        oid = order.id
        total = int(order.total_price or 0)
        OrderItem.query.filter_by(order_id=order_id).delete()
        db.session.delete(order)
        db.session.commit()
        try:
            log_activity(action="delete_order", entity_type="order", entity_id=oid,
                title="Deleted order", note="Order deleted from admin", amount=total, payment_method="store")
        except Exception as e:
            print("❌ Activity log error:", e)
        return jsonify({'success': True, 'message': 'تم حذف الطلب بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ========================================
# STADIUMS
# ========================================

@admin_bp.route('/stadiums')
@login_required
@permission_required('can_manage_stadiums')
def manage_stadiums():
    stadiums = Stadium.query.all()
    return render_template('admin/stadiums.html', stadiums=stadiums)


@admin_bp.route('/api/stadium', methods=['POST'])
@login_required
def add_stadium():
    data = request.json or {}
    if Stadium.query.filter_by(name=data.get('name')).first():
        return jsonify({'success': False, 'message': 'اسم الملعب موجود مسبقاً'}), 409
    try:
        stadium = Stadium(name=data.get('name'), description=data.get('description'),
            location=data.get('location'), price_per_hour=float(data.get('price_per_hour', 50000)),
            image_url=data.get('image_url'), is_active=data.get('is_active', True))
        db.session.add(stadium)
        db.session.commit()
        try:
            log_activity(action="add_stadium", entity_type="stadium", entity_id=stadium.id,
                title="Added stadium", note=f"{stadium.name}", payment_method="booking")
        except Exception as e:
            print("❌ Activity log error:", e)
        return jsonify({'success': True, 'message': 'تم إضافة الملعب بنجاح', 'stadium': stadium.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/stadium/<int:stadium_id>', methods=['PUT'])
@login_required
def update_stadium(stadium_id):
    stadium = Stadium.query.get(stadium_id)
    if not stadium:
        return jsonify({'success': False, 'message': 'الملعب غير موجود'}), 404
    data = request.json or {}
    try:
        if 'name' in data: stadium.name = data['name']
        if 'description' in data: stadium.description = data['description']
        if 'location' in data: stadium.location = data['location']
        if 'price_per_hour' in data: stadium.price_per_hour = float(data['price_per_hour'])
        if 'is_active' in data: stadium.is_active = data['is_active']
        if 'image_url' in data: stadium.image_url = data['image_url']
        db.session.commit()
        try:
            log_activity(action="update_stadium", entity_type="stadium", entity_id=stadium.id,
                title="Updated stadium", note=f"{stadium.name} | Active: {stadium.is_active}", payment_method="booking")
        except Exception as e:
            print("❌ Activity log error:", e)
        return jsonify({'success': True, 'message': 'تم تحديث الملعب بنجاح', 'stadium': stadium.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/stadium/<int:stadium_id>', methods=['DELETE'])
@login_required
def delete_stadium(stadium_id):
    stadium = Stadium.query.get(stadium_id)
    if not stadium:
        return jsonify({'success': False, 'message': 'الملعب غير موجود'}), 404
    if getattr(stadium, 'bookings', None) and stadium.bookings:
        return jsonify({'success': False, 'message': 'لا يمكن حذف ملعب لديه حجوزات'}), 409
    try:
        sid = stadium.id
        sname = stadium.name
        db.session.delete(stadium)
        db.session.commit()
        try:
            log_activity(action="delete_stadium", entity_type="stadium", entity_id=sid,
                title="Deleted stadium", note=sname, payment_method="booking")
        except Exception as e:
            print("❌ Activity log error:", e)
        return jsonify({'success': True, 'message': 'تم حذف الملعب بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ========================================
# SETTINGS
# ========================================

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@permission_required('can_manage_settings')
def manage_settings():
    settings = Settings.query.first()
    if not settings:
        settings = Settings()
        db.session.add(settings)
        db.session.commit()
    if request.method == 'POST':
        try:
            data = request.get_json(silent=True) if request.is_json else request.form
            data = data or {}
            if data.get('opening_hour') is not None:
                try: settings.opening_hour = int(data.get('opening_hour'))
                except (ValueError, TypeError): pass
            if data.get('closing_hour') is not None:
                try: settings.closing_hour = int(data.get('closing_hour'))
                except (ValueError, TypeError): pass
            if data.get('price_per_hour') is not None:
                try: settings.price_per_hour = float(data.get('price_per_hour'))
                except (ValueError, TypeError): pass
            if data.get('discount_percentage') is not None:
                try: settings.discount_percentage = int(data.get('discount_percentage'))
                except (ValueError, TypeError): pass
            if data.get('discount_start_hour') is not None:
                try: settings.discount_start_hour = int(data.get('discount_start_hour'))
                except (ValueError, TypeError): pass
            if data.get('discount_end_hour') is not None:
                try: settings.discount_end_hour = int(data.get('discount_end_hour'))
                except (ValueError, TypeError): pass
            if data.get('site_name') is not None: settings.site_name = str(data.get('site_name')).strip()
            if data.get('phone') is not None: settings.phone = str(data.get('phone')).strip()
            if data.get('email') is not None: settings.email = str(data.get('email')).strip()
            if data.get('address') is not None: settings.address = str(data.get('address')).strip()
            if data.get('facebook') is not None: settings.facebook = str(data.get('facebook')).strip() or None
            if data.get('instagram') is not None: settings.instagram = str(data.get('instagram')).strip() or None
            if data.get('whatsapp') is not None: settings.whatsapp = str(data.get('whatsapp')).strip() or None
            db.session.commit()
            try:
                log_activity(action="update_settings", entity_type="settings",
                    entity_id=getattr(settings, "id", None), title="Updated settings",
                    note="Admin updated system settings", payment_method="system")
            except Exception as e:
                print("❌ Activity log error:", e)
            if request.is_json:
                return jsonify({'success': True, 'message': 'Saved'}), 200
            flash('تم تحديث الإعدادات بنجاح', 'success')
            return redirect(url_for('admin.manage_settings'))
        except Exception as e:
            db.session.rollback()
            if request.is_json:
                return jsonify({'success': False, 'message': str(e)}), 500
            flash(f'خطأ: {str(e)}', 'danger')
            return redirect(url_for('admin.manage_settings'))
    return render_template('admin/settings.html', settings=settings)


# ========================================
# USERS
# ========================================

@admin_bp.route('/users')
@login_required
@super_admin_required
def manage_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)


@admin_bp.route('/users/add', methods=['POST'])
@login_required
@super_admin_required
def add_user_form():
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'admin')
    if not username or not password:
        flash('Username and password are required', 'danger')
        return redirect(url_for('admin.manage_users'))
    if User.query.filter_by(username=username).first():
        flash('Username already exists', 'danger')
        return redirect(url_for('admin.manage_users'))
    try:
        user = User(username=username, email=f"{username}@padelhouse.local", role=role, is_active=True,
            can_manage_bookings=request.form.get('can_manage_bookings') == 'on',
            can_manage_products=request.form.get('can_manage_products') == 'on',
            can_manage_orders=request.form.get('can_manage_orders') == 'on',
            can_manage_stadiums=request.form.get('can_manage_stadiums') == 'on',
            can_manage_settings=request.form.get('can_manage_settings') == 'on',
            can_view_reports=request.form.get('can_view_reports') == 'on',
            can_access_dashboard=request.form.get('can_access_dashboard') == 'on')
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        try:
            log_activity(action="add_user", entity_type="user", entity_id=user.id,
                title="Created user", note=f"Username: {user.username} | Role: {user.role}", payment_method="system")
        except Exception as e:
            print("❌ Activity log error:", e)
        flash(f'User {username} created successfully!', 'success')
        return redirect(url_for('admin.manage_users'))
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('admin.manage_users'))


@admin_bp.route('/users/edit/<int:user_id>', methods=['POST'])
@login_required
@super_admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    username = request.form.get('username')
    role = request.form.get('role')
    password = request.form.get('password')
    if not username:
        flash('Username is required', 'danger')
        return redirect(url_for('admin.manage_users'))
    try:
        if user.username != username:
            user.email = f"{username}@padelhouse.local"
        user.username = username
        if user.id != current_user.id and role:
            user.role = role
        if password:
            user.set_password(password)
        user.can_manage_bookings = request.form.get('can_manage_bookings') == 'on'
        user.can_manage_products = request.form.get('can_manage_products') == 'on'
        user.can_manage_orders = request.form.get('can_manage_orders') == 'on'
        user.can_manage_stadiums = request.form.get('can_manage_stadiums') == 'on'
        user.can_manage_settings = request.form.get('can_manage_settings') == 'on'
        user.can_view_reports = request.form.get('can_view_reports') == 'on'
        user.can_access_dashboard = request.form.get('can_access_dashboard') == 'on'
        db.session.commit()
        try:
            log_activity(action="update_user", entity_type="user", entity_id=user.id,
                title="Updated user", note=f"Username: {user.username} | Role: {user.role}", payment_method="system")
        except Exception as e:
            print("❌ Activity log error:", e)
        flash(f'User {username} updated successfully!', 'success')
        return redirect(url_for('admin.manage_users'))
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('admin.manage_users'))


@admin_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
@super_admin_required
def delete_user_form(user_id):
    if user_id == current_user.id:
        flash('You cannot delete yourself!', 'danger')
        return redirect(url_for('admin.manage_users'))
    user = User.query.get_or_404(user_id)
    username = user.username
    try:
        db.session.delete(user)
        db.session.commit()
        try:
            log_activity(action="delete_user", entity_type="user", entity_id=user_id,
                title="Deleted user", note=f"Username: {username}", payment_method="system")
        except Exception as e:
            print("❌ Activity log error:", e)
        flash(f'User {username} deleted successfully!', 'success')
        return redirect(url_for('admin.manage_users'))
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('admin.manage_users'))


@admin_bp.route('/api/user', methods=['POST'])
@login_required
@super_admin_required
def add_user():
    data = request.json or {}
    if not data.get('username') or not data.get('password'):
        return jsonify({'success': False, 'message': 'Username and password required'}), 400
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'success': False, 'message': 'Username already exists'}), 409
    try:
        user = User(username=data['username'], email=f"{data['username']}@padelhouse.local",
            role=data.get('role', 'admin'), is_active=True,
            can_manage_bookings=data.get('can_manage_bookings', False),
            can_manage_products=data.get('can_manage_products', False),
            can_manage_orders=data.get('can_manage_orders', False),
            can_manage_stadiums=data.get('can_manage_stadiums', False),
            can_manage_settings=data.get('can_manage_settings', False),
            can_view_reports=data.get('can_view_reports', False),
            can_access_dashboard=data.get('can_access_dashboard', False))
        user.set_password(data['password'])
        db.session.add(user)
        db.session.commit()
        try:
            log_activity(action="add_user", entity_type="user", entity_id=user.id,
                title="Created user", note=f"Username: {user.username} | Role: {user.role}", payment_method="system")
        except Exception as e:
            print("❌ Activity log error:", e)
        return jsonify({'success': True, 'message': 'User created successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/user/<int:user_id>', methods=['PUT'])
@login_required
@super_admin_required
def update_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    data = request.json or {}
    try:
        if data.get('username'):
            if user.username != data['username']:
                user.email = f"{data['username']}@padelhouse.local"
            user.username = data['username']
        if data.get('password'): user.set_password(data['password'])
        if user.id != current_user.id and 'role' in data: user.role = data['role']
        if 'is_active' in data: user.is_active = bool(data['is_active'])
        for perm in ['can_manage_bookings', 'can_manage_products', 'can_manage_orders',
                     'can_manage_stadiums', 'can_manage_settings', 'can_view_reports', 'can_access_dashboard']:
            if perm in data: setattr(user, perm, bool(data[perm]))
        db.session.commit()
        try:
            log_activity(action="update_user", entity_type="user", entity_id=user.id,
                title="Updated user", note=f"Username: {user.username} | Active: {user.is_active} | Role: {user.role}",
                payment_method="system")
        except Exception as e:
            print("❌ Activity log error:", e)
        return jsonify({'success': True, 'message': 'User updated successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/user/<int:user_id>/toggle', methods=['POST'])
@login_required
@super_admin_required
def toggle_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    if user.id == current_user.id:
        return jsonify({'success': False, 'message': 'Cannot deactivate yourself'}), 403
    try:
        user.is_active = not user.is_active
        db.session.commit()
        try:
            log_activity(action="toggle_user", entity_type="user", entity_id=user.id,
                title="Toggled user status", note=f"Username: {user.username} | Active: {user.is_active}", payment_method="system")
        except Exception as e:
            print("❌ Activity log error:", e)
        return jsonify({'success': True, 'message': 'User status updated', 'is_active': user.is_active})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/user/<int:user_id>', methods=['DELETE'])
@login_required
@super_admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        return jsonify({'success': False, 'message': 'Cannot delete yourself'}), 403
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    uname = user.username
    uid = user.id
    try:
        db.session.delete(user)
        db.session.commit()
        try:
            log_activity(action="delete_user", entity_type="user", entity_id=uid,
                title="Deleted user", note=f"Username: {uname}", payment_method="system")
        except Exception as e:
            print("❌ Activity log error:", e)
        return jsonify({'success': True, 'message': 'User deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/settings', methods=['POST'])
@login_required
def api_settings_alias():
    settings = Settings.query.first()
    if not settings:
        settings = Settings()
        db.session.add(settings)
        db.session.commit()
    try:
        data = request.get_json(silent=True) or {}
        if data.get('opening_hour') is not None:
            try: settings.opening_hour = int(data['opening_hour'])
            except (ValueError, TypeError): pass
        if data.get('closing_hour') is not None:
            try: settings.closing_hour = int(data['closing_hour'])
            except (ValueError, TypeError): pass
        if data.get('price_per_hour') is not None:
            try: settings.price_per_hour = float(data['price_per_hour'])
            except (ValueError, TypeError): pass
        if data.get('discount_percentage') is not None:
            try: settings.discount_percentage = int(data['discount_percentage'])
            except (ValueError, TypeError): pass
        if data.get('discount_start_hour') is not None:
            try: settings.discount_start_hour = int(data['discount_start_hour'])
            except (ValueError, TypeError): pass
        if data.get('discount_end_hour') is not None:
            try: settings.discount_end_hour = int(data['discount_end_hour'])
            except (ValueError, TypeError): pass
        if data.get('site_name') is not None: settings.site_name = str(data['site_name']).strip()
        if data.get('phone') is not None: settings.phone = str(data['phone']).strip()
        if data.get('email') is not None: settings.email = str(data['email']).strip()
        if data.get('address') is not None: settings.address = str(data['address']).strip()
        if data.get('facebook') is not None: settings.facebook = str(data['facebook']).strip() or None
        if data.get('instagram') is not None: settings.instagram = str(data['instagram']).strip() or None
        if data.get('whatsapp') is not None: settings.whatsapp = str(data['whatsapp']).strip() or None
        db.session.commit()
        return jsonify({'success': True, 'message': 'Saved'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/pending-count', methods=['GET'])
@login_required
def admin_pending_count_api():
    count = Booking.query.filter(Booking.status == 'pending').count()
    return jsonify({'pending': count}), 200


# ========================================
# NOTIFICATIONS
# ========================================

@admin_bp.route('/api/notifications', methods=['GET'])
@login_required
def api_notifications():
    items = Notification.query.filter(
        (Notification.user_id == None) | (Notification.user_id == current_user.id)
    ).order_by(Notification.created_at.desc()).limit(20).all()
    return jsonify({"success": True, "items": [
        {"id": n.id, "title": n.title, "message": n.message, "url": n.url,
         "type": n.type, "is_read": n.is_read,
         "created_at": n.created_at.isoformat() if n.created_at else None}
        for n in items]})


@admin_bp.route('/api/notifications/unread-count', methods=['GET'])
@login_required
def api_notifications_unread_count():
    count = Notification.query.filter(
        ((Notification.user_id == None) | (Notification.user_id == current_user.id)),
        Notification.is_read == False
    ).count()
    return jsonify({"success": True, "count": count})


@admin_bp.route('/api/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def api_notifications_mark_read(notif_id):
    n = Notification.query.get_or_404(notif_id)
    if n.user_id is not None and n.user_id != current_user.id:
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    n.is_read = True
    db.session.commit()
    return jsonify({"success": True})


# ========================================
# REPORTS
# ========================================

@admin_bp.route('/reports')
@login_required
@permission_required('can_view_reports')
def reports():
    from_date_str = request.args.get('from')
    to_date_str = request.args.get('to')
    try:
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date() if from_date_str else date.today()
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date() if to_date_str else date.today()
    except (ValueError, TypeError):
        from_date = date.today()
        to_date = date.today()
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    start_datetime = datetime.combine(from_date, datetime.min.time())
    end_datetime = datetime.combine(to_date, datetime.max.time())
    bookings = Booking.query.filter(Booking.date >= from_date, Booking.date <= to_date, Booking.status.in_(['confirmed', 'completed'])).all()
    total_bookings = len(bookings)
    booking_revenue = sum(b.final_price or 0 for b in bookings)
    orders = Order.query.filter(Order.created_at >= start_datetime, Order.created_at <= end_datetime, Order.status.in_(['confirmed', 'completed', 'delivered'])).all()
    total_orders = len(orders)
    order_revenue = sum(o.total_price or 0 for o in orders)
    pos_revenue = pos_cash = pos_card = total_pos_sessions = active_pos_sessions = 0
    if POSSession:
        pos_sessions = POSSession.query.filter(POSSession.created_at >= start_datetime, POSSession.created_at <= end_datetime, POSSession.status == 'paid').all()
        total_pos_sessions = len(pos_sessions)
        pos_revenue = sum(s.total_amount or 0 for s in pos_sessions)
        pos_cash = sum(s.total_amount or 0 for s in pos_sessions if s.payment_method == 'cash')
        pos_card = sum(s.total_amount or 0 for s in pos_sessions if s.payment_method == 'card')
        active_pos_sessions = POSSession.query.filter_by(status='active').count()
    total_revenue = booking_revenue + order_revenue + pos_revenue
    manual_debts = ManualDebt.query.filter(ManualDebt.date >= from_date, ManualDebt.date <= to_date).order_by(ManualDebt.date.desc(), ManualDebt.id.desc()).all()
    manual_debt_count = len(manual_debts)
    manual_debt_total = sum((d.amount or 0) for d in manual_debts)
    manual_debt_paid_total = sum((d.paid_amount or 0) for d in manual_debts)
    manual_debt_remaining_total = sum(max(0, (d.amount or 0) - (d.paid_amount or 0)) for d in manual_debts)
    expenses = Expense.query.filter(Expense.date >= from_date, Expense.date <= to_date).order_by(Expense.date.desc(), Expense.id.desc()).all()
    expense_count = len(expenses)
    total_expenses = sum((e.amount or 0) for e in expenses)
    expense_by_category = {}
    for exp in expenses:
        cat = exp.get_category_name()
        if cat not in expense_by_category: expense_by_category[cat] = 0
        expense_by_category[cat] += exp.amount
    expense_cash = sum((e.amount or 0) for e in expenses if e.payment_method == 'cash')
    expense_card = sum((e.amount or 0) for e in expenses if e.payment_method == 'card')
    net_profit = total_revenue - total_expenses
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())
    activities = ActivityLog.query.filter(ActivityLog.created_at >= today_start, ActivityLog.created_at <= today_end).order_by(ActivityLog.created_at.desc()).limit(50).all()
    return render_template('admin/reports.html',
        from_date=from_date.strftime('%Y-%m-%d'), to_date=to_date.strftime('%Y-%m-%d'),
        total_bookings=total_bookings, booking_revenue=booking_revenue,
        total_orders=total_orders, order_revenue=order_revenue,
        total_pos_sessions=total_pos_sessions, active_pos_sessions=active_pos_sessions,
        pos_revenue=pos_revenue, pos_cash=pos_cash, pos_card=pos_card,
        total_revenue=total_revenue, activities=activities,
        manual_debts=manual_debts, manual_debt_count=manual_debt_count,
        manual_debt_total=manual_debt_total, manual_debt_paid_total=manual_debt_paid_total,
        manual_debt_remaining_total=manual_debt_remaining_total,
        expenses=expenses, expense_count=expense_count, total_expenses=total_expenses,
        expense_by_category=expense_by_category, expense_cash=expense_cash,
        expense_card=expense_card, net_profit=net_profit)


# ========================================
# MANUAL DEBTS
# ========================================

@admin_bp.route("/manual-debts/add", methods=["POST"])
@login_required
@permission_required('can_view_reports')
def add_manual_debt():
    try:
        name = (request.form.get("name") or "").strip()
        phone = (request.form.get("phone") or "").strip() or None
        note = (request.form.get("note") or "").strip() or None
        try: amount = int(request.form.get("amount") or 0)
        except (ValueError, TypeError): amount = 0
        if not name:
            flash("الاسم مطلوب", "danger")
            return redirect(url_for("admin.reports"))
        if amount <= 0:
            flash("المبلغ يجب أن يكون أكبر من صفر", "danger")
            return redirect(url_for("admin.reports"))
        date_str = request.form.get("date")
        try: debt_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError): debt_date = date.today()
        from_date = request.form.get("from")
        to_date = request.form.get("to")
        d = ManualDebt(name=name, phone=phone, amount=amount, paid_amount=0, note=note, date=debt_date, status="open")
        db.session.add(d)
        db.session.commit()
        flash("تمت إضافة الدين بنجاح ✅", "success")
        return redirect(url_for("admin.reports", **{'from': from_date, 'to': to_date} if from_date and to_date else {}))
    except Exception as e:
        db.session.rollback()
        flash(f"خطأ: {str(e)}", "danger")
        return redirect(url_for("admin.reports"))


@admin_bp.route("/manual-debts/<int:debt_id>/mark-paid", methods=["GET"])
@login_required
@permission_required('can_view_reports')
def mark_manual_debt_paid_route(debt_id):
    try:
        from_date = request.args.get("from")
        to_date = request.args.get("to")
        d = ManualDebt.query.get_or_404(debt_id)
        d.paid_amount = int(d.amount or 0)
        d.status = "paid"
        db.session.commit()
        flash("تم تسديد الدين ✅", "success")
        return redirect(url_for("admin.reports", **{'from': from_date, 'to': to_date} if from_date and to_date else {}))
    except Exception as e:
        db.session.rollback()
        flash(f"خطأ: {str(e)}", "danger")
        return redirect(url_for("admin.reports"))


# ========================================
# EXPENSES
# ========================================

from app.models.expense import Expense


@admin_bp.route('/expenses')
@login_required
@permission_required('can_view_reports')
def manage_expenses():
    from_date_str = request.args.get('from')
    to_date_str = request.args.get('to')
    category_filter = request.args.get('category', 'all')
    try:
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date() if from_date_str else date.today()
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date() if to_date_str else date.today()
    except (ValueError, TypeError):
        from_date = date.today()
        to_date = date.today()
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    query = Expense.query.filter(Expense.date >= from_date, Expense.date <= to_date)
    if category_filter != 'all':
        query = query.filter_by(category=category_filter)
    expenses = query.order_by(Expense.date.desc(), Expense.id.desc()).all()
    category_totals = {}
    total_amount = 0
    for exp in expenses:
        cat = exp.category
        if cat not in category_totals: category_totals[cat] = 0
        category_totals[cat] += exp.amount
        total_amount += exp.amount
    categories = Expense.get_categories()
    return render_template('admin/expenses.html', expenses=expenses, categories=categories,
        category_totals=category_totals, total_amount=total_amount,
        from_date=from_date.strftime('%Y-%m-%d'), to_date=to_date.strftime('%Y-%m-%d'),
        current_category=category_filter)


@admin_bp.route('/expenses/add', methods=['POST'])
@login_required
@permission_required('can_view_reports')
def add_expense():
    try:
        date_str = request.form.get('date')
        category = (request.form.get('category') or '').strip()
        amount_str = request.form.get('amount', '0')
        description = (request.form.get('description') or '').strip()
        payment_method = request.form.get('payment_method', 'cash')
        if not category:
            flash('الرجاء اختيار فئة المصروف', 'danger')
            return redirect(url_for('admin.reports'))
        try: amount = int(amount_str)
        except (ValueError, TypeError): amount = 0
        if amount <= 0:
            flash('المبلغ يجب أن يكون أكبر من صفر', 'danger')
            return redirect(url_for('admin.reports'))
        try: expense_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError): expense_date = date.today()
        expense = Expense(date=expense_date, category=category, amount=amount,
            description=description, payment_method=payment_method, created_by=current_user.id)
        db.session.add(expense)
        db.session.commit()
        try:
            log_activity(action="add_expense", entity_type="expense", entity_id=expense.id,
                title="Added expense", note=f"{expense.get_category_name()} | {description or '-'}",
                amount=amount, payment_method="expense")
        except Exception as e:
            print("❌ Activity log error:", e)
        flash(f'تمت إضافة المصروف بنجاح ✅ | المبلغ: {amount:,} IQD', 'success')
        from_date = request.form.get('from')
        to_date = request.form.get('to')
        return redirect(url_for('admin.reports', **({'from': from_date, 'to': to_date} if from_date and to_date else {})))
    except Exception as e:
        db.session.rollback()
        flash(f'خطأ: {str(e)}', 'danger')
        return redirect(url_for('admin.reports'))


# =====================================================================
# ✅ FIX 3: admin_live_dashboard — أضف cancel_requests للـ JS badge
# =====================================================================
@admin_bp.route('/api/live-dashboard', methods=['GET'])
@login_required
def admin_live_dashboard():
    total_bookings = Booking.query.count()

    # ✅ pending فقط للـ badge الأصفر
    pending_bookings_count = Booking.query.filter(
        Booking.status == 'pending'
    ).count()

    # ✅ cancel requests منفصل للـ badge الأحمر
    cancel_requests_count = Booking.query.filter_by(status='pending_cancel').count()

    pending_orders_count = Order.query.filter_by(status='pending').count()
    new_training_requests_count = CoachTrainingRequest.query.filter_by(status='new').count()
    unread_notifications_count = Notification.query.filter(
        ((Notification.user_id == None) | (Notification.user_id == current_user.id)),
        Notification.is_read == False
    ).count()
    today_bookings = Booking.query.filter(Booking.date == date.today()).count()
    today_revenue = db.session.query(db.func.sum(Booking.final_price)).filter(
        Booking.status.in_(['confirmed', 'completed']), Booking.date == date.today()).scalar() or 0
    total_orders = Order.query.count()
    store_revenue = db.session.query(db.func.sum(Order.total_price)).filter(
        Order.status.in_(['confirmed', 'completed', 'delivered'])).scalar() or 0
    total_products = Product.query.filter_by(is_active=True).count()

    return jsonify({'success': True,
        'counts': {
            'pending_bookings': pending_bookings_count,
            'cancel_requests': cancel_requests_count,      # ✅ جديد
            'pending_orders': pending_orders_count,
            'new_training_requests': new_training_requests_count,
            'unread_notifications': unread_notifications_count
        },
        'stats': {
            'total_bookings': total_bookings,
            'today_bookings': today_bookings,
            'today_revenue': float(today_revenue or 0),
            'total_orders': total_orders,
            'store_revenue': float(store_revenue or 0),
            'total_products': total_products
        }
    })


@admin_bp.route('/dashboard/live-data')
@login_required
def dashboard_live_data():
    if current_user.role != 'super_admin':
        if not getattr(current_user, 'can_access_dashboard', False):
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    today = date.today()
    start_of_day = datetime.combine(today, time.min)
    end_of_day = datetime.combine(today, time.max)
    today_bookings = Booking.query.filter(Booking.date == today).count()
    pending_bookings = Booking.query.filter(Booking.status.in_(['pending', 'pending_cancel'])).count()
    today_orders = Order.query.filter(Order.created_at >= start_of_day, Order.created_at <= end_of_day).count()
    today_revenue = db.session.query(func.coalesce(func.sum(Booking.final_price), 0)).filter(
        Booking.status.in_(['confirmed', 'completed']), Booking.date == today).scalar() or 0
    recent_bookings = Booking.query.order_by(Booking.created_at.desc()).limit(8).all()
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(8).all()
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    today_logs = ActivityLog.query.filter(ActivityLog.created_at >= start, ActivityLog.created_at < end).order_by(ActivityLog.created_at.desc()).limit(20).all()
    return jsonify({'success': True, 'today_bookings': today_bookings, 'pending_bookings': pending_bookings,
        'today_orders': today_orders, 'today_revenue': float(today_revenue or 0),
        'recent_bookings': [{'id': b.id, 'customer_name': b.customer_name,
            'stadium_name': b.stadium.name if getattr(b, 'stadium', None) else '-',
            'date': str(b.date) if b.date else '-', 'status': b.status or 'pending'} for b in recent_bookings],
        'recent_orders': [{'id': o.id, 'customer_name': o.customer_name,
            'total_price': float(o.total_price or 0), 'status': o.status or 'pending'} for o in recent_orders],
        'today_logs': [{'id': log.id, 'time': log.created_at.strftime('%H:%M:%S') if log.created_at else '-',
            'title': log.title, 'note': log.note, 'action': log.action,
            'entity_type': log.entity_type, 'entity_id': log.entity_id,
            'payment_method': log.payment_method,
            'username': log.user.username if getattr(log, 'user', None) else '-',
            'amount': float(log.amount) if log.amount is not None else None} for log in today_logs]
    }), 200


@admin_bp.route('/expenses/<int:expense_id>/edit', methods=['POST'])
@login_required
@permission_required('can_view_reports')
def edit_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    try:
        date_str = request.form.get('date')
        category = (request.form.get('category') or '').strip()
        amount_str = request.form.get('amount', '0')
        description = (request.form.get('description') or '').strip()
        payment_method = request.form.get('payment_method', 'cash')
        reference_number = (request.form.get('reference_number') or '').strip() or None
        if not category:
            flash('الرجاء اختيار فئة المصروف', 'danger')
            return redirect(url_for('admin.manage_expenses'))
        try: amount = int(amount_str)
        except (ValueError, TypeError): amount = 0
        if amount <= 0:
            flash('المبلغ يجب أن يكون أكبر من صفر', 'danger')
            return redirect(url_for('admin.manage_expenses'))
        try: expense_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError): expense_date = expense.date
        expense.date = expense_date
        expense.category = category
        expense.amount = amount
        expense.description = description
        expense.payment_method = payment_method
        expense.reference_number = reference_number
        expense.updated_at = datetime.utcnow()
        db.session.commit()
        try:
            log_activity(action="edit_expense", entity_type="expense", entity_id=expense.id,
                title="Updated expense", note=f"{expense.get_category_name()} | {description or '-'}",
                amount=amount, payment_method="expense")
        except Exception as e:
            print("❌ Activity log error:", e)
        flash('تم تحديث المصروف بنجاح ✅', 'success')
        from_date = request.form.get('from')
        to_date = request.form.get('to')
        category_filter = request.form.get('category_filter', 'all')
        return redirect(url_for('admin.manage_expenses',
            **({'from': from_date, 'to': to_date, 'category': category_filter} if from_date and to_date else {})))
    except Exception as e:
        db.session.rollback()
        flash(f'خطأ: {str(e)}', 'danger')
        return redirect(url_for('admin.manage_expenses'))


@admin_bp.route('/expenses/<int:expense_id>/delete', methods=['POST', 'GET'])
@login_required
@permission_required('can_view_reports')
def delete_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    try:
        eid = expense.id
        eamount = expense.amount
        ecat = expense.get_category_name()
        db.session.delete(expense)
        db.session.commit()
        try:
            log_activity(action="delete_expense", entity_type="expense", entity_id=eid,
                title="Deleted expense", note=f"{ecat} | Amount: {eamount:,} IQD",
                amount=eamount, payment_method="expense")
        except Exception as e:
            print("❌ Activity log error:", e)
        flash('تم حذف المصروف بنجاح ✅', 'success')
        from_date = request.args.get('from')
        to_date = request.args.get('to')
        category_filter = request.args.get('category', 'all')
        return redirect(url_for('admin.manage_expenses',
            **({'from': from_date, 'to': to_date, 'category': category_filter} if from_date and to_date else {})))
    except Exception as e:
        db.session.rollback()
        flash(f'خطأ: {str(e)}', 'danger')
        return redirect(url_for('admin.manage_expenses'))