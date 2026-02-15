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
from datetime import datetime, date, timedelta
import os
import random
import io

# Notifications
from app.services.notify import notify_admins
from sqlalchemy import func
from app.models.notification import Notification
from app.models.manual_debt import ManualDebt

# Services
from app.services.google_sheets import send_booking_to_sheet
from app.services.barcode_service import BarcodeService, XPrinterService

# ✅ Activity log
from app.models.activity_log import ActivityLog
from app.services.activity_service import log_activity
def to_bool(value, default=False):
    """
    Convert different checkbox/form values to boolean.
    Accepts: on/true/1/yes/y
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    v = str(value).strip().lower()
    return v in ("1", "true", "yes", "y", "on")
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


def generate_product_barcode():
    """Generate a unique 13-digit barcode for EAN-13 format"""
    prefix = "743"
    timestamp = datetime.now().strftime("%y%m%d")  # YYMMDD
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


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_product_image(file):
    """
    Saves product image in /static/images/products as optimized .webp
    If compress_product_image is not available, fallback to normal save.
    """
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    filename = secure_filename(file.filename)
    base = os.path.splitext(filename)[0]
    stamp = datetime.now().strftime('%Y%m%d%H%M%S')

    # temp original
    temp_name = f"temp_{stamp}_{filename}"
    temp_path = os.path.join(UPLOAD_FOLDER, temp_name)
    file.save(temp_path)

    # final name (webp)
    final_name = f"{stamp}_{base}.webp"
    final_path = os.path.join(UPLOAD_FOLDER, final_name)

    # compress if tool exists
    if compress_product_image:
        try:
            out_path = compress_product_image(
                input_path=temp_path,
                output_path=final_path,
                max_size=(900, 900),
                quality=78,
                to_webp=True
            )
            try:
                os.remove(temp_path)
            except Exception:
                pass
            return os.path.basename(out_path)
        except Exception:
            pass

    # Fallback (no compression)
    fallback_name = f"{stamp}_{filename}"
    fallback_path = os.path.join(UPLOAD_FOLDER, fallback_name)
    try:
        os.replace(temp_path, fallback_path)
    except Exception:
        fallback_name = temp_name
    return fallback_name

def to_bool(v, default=False):
    """Convert common HTML/JS truthy values to bool safely."""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("1", "true", "on", "yes", "y")

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

            # super admin always allowed
            if getattr(current_user, "role", None) == "super_admin":
                return f(*args, **kwargs)

            # check specific permission boolean in User model
            if not getattr(current_user, permission_attr, False):
                flash("غير مصرح لك", "danger")
                return redirect(url_for('admin.dashboard'))

            return f(*args, **kwargs)
        return wrapper
    return decorator


@admin_bp.app_context_processor
def inject_pending_count():
    if current_user.is_authenticated:
        pending_bookings_count = Booking.query.filter_by(status='pending').count()
        return {'pending_bookings_count': pending_bookings_count}
    return {'pending_bookings_count': 0}


@admin_bp.app_context_processor
def inject_pending_orders_count():
    if current_user.is_authenticated:
        pending_orders_count = Order.query.filter_by(status='pending').count()
        return {'pending_orders_count': pending_orders_count}
    return {'pending_orders_count': 0}


# ===== ADMIN HOME - Smart Redirect =====
@admin_bp.route('/')
@login_required
def admin_home():
    """Smart redirect to first accessible page"""
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


# ===== ADMIN DASHBOARD =====
@admin_bp.route('/dashboard')
@login_required
def dashboard():
    # ✅ Check dashboard permission
    if current_user.role != 'super_admin':
        if not getattr(current_user, 'can_access_dashboard', False):
            flash('غير مصرح لك بالوصول إلى لوحة التحكم', 'danger')
            return redirect(url_for('admin.admin_home'))

    total_bookings = Booking.query.count()

    total_revenue = db.session.query(
        db.func.sum(Booking.final_price)
    ).filter(Booking.status.in_(['confirmed', 'completed'])).scalar() or 0

    today_bookings = Booking.query.filter(
        Booking.date == date.today()
    ).count()

    today_revenue = db.session.query(
        db.func.sum(Booking.final_price)
    ).filter(
        Booking.status.in_(['confirmed', 'completed']),
        Booking.date == date.today()
    ).scalar() or 0

    pending_bookings = Booking.query.filter_by(status='pending').count()

    total_products = Product.query.filter_by(is_active=True).count()
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status='pending').count()

    store_revenue = db.session.query(
        db.func.sum(Order.total_price)
    ).filter(Order.status.in_(['confirmed', 'completed', 'delivered'])).scalar() or 0

    stadiums = Stadium.query.all()
    recent_bookings = Booking.query.order_by(Booking.created_at.desc()).limit(5).all()
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(5).all()
    pending_booking_list = Booking.query.filter_by(status='pending').order_by(Booking.created_at.desc()).limit(5).all()

    # ✅ TODAY LOGS (UTC)
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    today_logs = ActivityLog.query.filter(
        ActivityLog.created_at >= start,
        ActivityLog.created_at < end
    ).order_by(ActivityLog.created_at.desc()).limit(30).all()

    return render_template(
        'admin/dashboard.html',
        total_bookings=total_bookings,
        total_revenue=total_revenue,
        today_revenue=today_revenue,
        today_bookings=today_bookings,
        pending_bookings=pending_bookings,
        total_products=total_products,
        total_orders=total_orders,
        pending_orders=pending_orders,
        store_revenue=store_revenue,
        stadiums=stadiums,
        recent_bookings=recent_bookings,
        recent_orders=recent_orders,
        pending_booking_list=pending_booking_list,
        today_logs=today_logs
    )


# ========================================
# ===== PENDING BOOKINGS MANAGEMENT =====
# ========================================

@admin_bp.route('/pending-bookings')
@login_required
@permission_required('can_manage_bookings')
def pending_bookings():
    bookings = Booking.query.filter_by(status='pending').order_by(Booking.created_at.desc()).all()
    stadiums = Stadium.query.all()
    return render_template('admin/pending_bookings.html', bookings=bookings, stadiums=stadiums)


@admin_bp.route('/api/booking/<int:booking_id>/approve', methods=['POST'])
@login_required
def approve_booking(booking_id):
    booking = Booking.query.get(booking_id)

    if not booking:
        return jsonify({'success': False, 'message': 'الحجز غير موجود'}), 404
    if booking.status != 'pending':
        return jsonify({'success': False, 'message': 'هذا الحجز ليس معلقاً'}), 400

    # ✅ Approve
    booking.status = 'confirmed'
    booking.confirmed_at = datetime.utcnow()
    if hasattr(booking, 'confirmed_by'):
        booking.confirmed_by = current_user.id

    db.session.commit()

    # ✅ Notify (approved)
    try:
        notify_admins(
            title="Booking approved ✅",
            message=f"Booking #{booking.id} confirmed for {booking.customer_name}",
            url=f"/admin/booking/{booking.id}",
            ntype="booking_approved"
        )
    except Exception as e:
        print("❌ Notification error:", e)

    # ✅ Send to Google Sheets ONLY ONCE
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

            return jsonify({
                'success': True,
                'message': f'تم قبول الحجز ✅ لكن حدث خطأ أثناء الإرسال إلى Google Sheets: {err}',
                'booking_id': booking.id,
                'new_status': 'confirmed',
                'sheet_sent': False
            }), 200

    # ✅ LOG IT
    try:
        log_activity(
            action="approve_booking",
            entity_type="booking",
            entity_id=booking.id,
            title="Approved booking",
            note=f"Customer: {booking.customer_name} | Stadium: {booking.stadium.name if booking.stadium else '-'} | Date: {booking.date}",
            amount=int(booking.final_price or 0),
            payment_method="booking"
        )
    except Exception as e:
        print("❌ Activity log error:", e)

    return jsonify({
        'success': True,
        'message': f'تم قبول حجز {booking.customer_name} بنجاح ✅',
        'booking_id': booking.id,
        'new_status': 'confirmed',
        'sheet_sent': True
    })


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

    # ✅ reject
    booking.status = 'cancelled'
    if hasattr(booking, 'rejection_reason'):
        booking.rejection_reason = rejection_reason or None

    if rejection_reason:
        existing_notes = booking.notes or ''
        booking.notes = f"{existing_notes}\n[رفض] سبب الرفض: {rejection_reason}".strip()

    db.session.commit()

    # ✅ Notify (SAFE)
    try:
        notify_admins(
            title="Booking rejected ❌",
            message=f"Booking #{booking.id} rejected for {booking.customer_name}. Reason: {rejection_reason or '-'}",
            url=f"/admin/booking/{booking.id}",
            ntype="booking_rejected"
        )
    except Exception as e:
        print("❌ Notification error:", e)

    # ✅ LOG IT
    try:
        log_activity(
            action="reject_booking",
            entity_type="booking",
            entity_id=booking.id,
            title="Rejected booking",
            note=f"Customer: {booking.customer_name} | Reason: {rejection_reason or '-'}",
            amount=int(booking.final_price or 0),
            payment_method="booking"
        )
    except Exception as e:
        print("❌ Activity log error:", e)

    return jsonify({
        'success': True,
        'message': f'تم رفض حجز {booking.customer_name} ❌',
        'booking_id': booking.id,
        'new_status': 'cancelled'
    })


# ===== MANAGE BOOKINGS =====
from sqlalchemy import or_

@admin_bp.route('/bookings')
@login_required
@permission_required('can_manage_bookings')
def manage_bookings():
    status_filter = request.args.get('status', 'all')
    stadium_filter = request.args.get('stadium', 'all')
    date_filter = request.args.get('date', '').strip()
    search_q = request.args.get('q', '').strip()

    query = Booking.query

    # status
    if status_filter and status_filter != 'all':
        query = query.filter(Booking.status == status_filter)

    # stadium
    if stadium_filter and stadium_filter != 'all':
        try:
            query = query.filter(Booking.stadium_id == int(stadium_filter))
        except (ValueError, TypeError):
            pass

    # date (YYYY-MM-DD)
    if date_filter:
        try:
            d = datetime.strptime(date_filter, '%Y-%m-%d').date()
            query = query.filter(Booking.date == d)
        except ValueError:
            pass

    # search (name OR phone)
    if search_q:
        like = f"%{search_q}%"
        query = query.filter(
            or_(
                Booking.customer_name.ilike(like),
                Booking.customer_phone.ilike(like)
            )
        )

    bookings = query.order_by(Booking.date.desc(), Booking.created_at.desc()).all()
    stadiums = Stadium.query.all()

    return render_template(
        'admin/bookings.html',
        bookings=bookings,
        stadiums=stadiums,
        current_status=status_filter,
        current_stadium=stadium_filter,
        current_date=date_filter,
        current_q=search_q
    )


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
    reason = (data.get('reason') or '').strip()  # optional

    if new_status not in ['pending', 'confirmed', 'completed', 'cancelled']:
        return jsonify({'success': False, 'message': 'Invalid status'}), 400

    old_status = booking.status
    booking.status = new_status

    # ✅ If confirm from pending
    if new_status == 'confirmed' and old_status == 'pending':
        booking.confirmed_at = datetime.utcnow()
        if hasattr(booking, 'confirmed_by'):
            booking.confirmed_by = current_user.id

    # ✅ If cancelled (important: free slot again + keep phone/name)
    if new_status == 'cancelled':
        # clear approval info so it's not treated as approved anymore
        booking.confirmed_at = None
        if hasattr(booking, 'confirmed_by'):
            booking.confirmed_by = None

        # save reason in notes (optional)
        if reason:
            existing_notes = booking.notes or ''
            booking.notes = f"{existing_notes}\n[إلغاء بعد التأكيد] السبب: {reason}".strip()

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f'تم تحديث الحجز إلى {new_status}',
        'booking_id': booking.id,
        'old_status': old_status,
        'new_status': new_status
    })


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
# ===== PRODUCTS MANAGEMENT =====
# ========================================

# ========================================
# ===== PRODUCTS MANAGEMENT =====
# ========================================

@admin_bp.route('/products')
@login_required
@permission_required('can_manage_products')
def manage_products():
    # ✅ Admin should show ALL products (even hidden), just show badges in UI
    products = Product.query.order_by(Product.created_at.desc()).all()
    categories = Category.query.filter_by(is_active=True).all()
    return render_template('admin/products.html', products=products, categories=categories)


@admin_bp.route('/api/product', methods=['POST'])
@login_required
def add_product_api():
    """API endpoint for adding products via AJAX (FormData)"""
    try:
        name_ku = (request.form.get('name_ku') or '').strip()
        name_ar = (request.form.get('name_ar') or '').strip() or None
        name_en = (request.form.get('name_en') or '').strip() or None

        description_ku = (request.form.get('description_ku') or '').strip() or None
        description_ar = (request.form.get('description_ar') or '').strip() or None
        description_en = (request.form.get('description_en') or '').strip() or None

        price = request.form.get('price')
        stock = request.form.get('stock', 0)
        category_id = request.form.get('category_id')

        # ✅ IMPORTANT: these are your DB columns
        # ✅ FormData must send 1/0 (we will fix JS below)
        show_in_website = to_bool(request.form.get('show_in_website'), default=False)
        show_in_pos = to_bool(request.form.get('show_in_pos'), default=False)

        if not name_ku or not price:
            return jsonify({'success': False, 'message': 'ناو و نرخ پێویستن / الاسم والسعر مطلوبان'}), 400

        try:
            price_int = int(price)
        except (ValueError, TypeError):
            price_int = 0

        try:
            stock_int = int(stock or 0)
        except (ValueError, TypeError):
            stock_int = 0

        product = Product(
            name_ku=name_ku,
            name_ar=name_ar,
            name_en=name_en,
            description_ku=description_ku,
            description_ar=description_ar,
            description_en=description_en,
            price=price_int,
            stock=stock_int,
            category_id=int(category_id) if category_id else None,

            # ✅ correct
            show_in_website=show_in_website,
            show_in_pos=show_in_pos,

            is_active=True
        )

        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                product.image = save_product_image(file)

        db.session.add(product)
        db.session.flush()

        barcode_value, filename = BarcodeService.save_barcode_image(
            product.id,
            product.name_ku or product.name_ar or 'Product'
        )
        product.barcode = barcode_value

        db.session.commit()

        # ✅ LOG
        try:
            log_activity(
                action="add_product",
                entity_type="product",
                entity_id=product.id,
                title="Added product",
                note=f"{product.name_ku or product.name_ar or product.name_en} | Price: {product.price}",
                amount=int(product.price or 0),
                payment_method="store"
            )
        except Exception as e:
            print("❌ Activity log error:", e)

        # ✅ Optional print
        if to_bool(request.form.get('print_label'), default=False):
            try:
                XPrinterService.print_barcode_label(
                    product.id,
                    product.name_ku or product.name_ar,
                    product.price,
                    barcode_value
                )
            except Exception as e:
                print("❌ Print error:", e)

        return jsonify({
            'success': True,
            'message': 'بەرهەم بە سەرکەوتوویی زیادکرا / تمت إضافة المنتج بنجاح',
            'product': {
                'id': product.id,
                'name_ku': product.name_ku,
                'name_ar': product.name_ar,
                'name_en': product.name_en,
                'barcode': product.barcode,
                'price': product.price,
                'stock': product.stock,
                'category_id': product.category_id,
                'image': product.image,
                'show_in_website': product.show_in_website,
                'show_in_pos': product.show_in_pos,
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'هەڵە / خطأ: {str(e)}'}), 500


@admin_bp.route('/products/add', methods=['POST'])
@login_required
def add_product():
    if current_user.role not in ['admin', 'super_admin']:
        flash('Unauthorized', 'danger')
        return redirect(url_for('admin.dashboard'))

    try:
        product = Product(
            name_ku=request.form.get('name_ku'),
            name_ar=request.form.get('name_ar'),
            name_en=request.form.get('name_en'),
            description_ku=request.form.get('description_ku'),
            description_ar=request.form.get('description_ar'),
            description_en=request.form.get('description_en'),
            price=int(request.form.get('price', 0)),
            stock=int(request.form.get('stock', 0)),
            category_id=request.form.get('category_id') or None,

            # ✅ FIX: accept on/true/1/yes (default False if missing)
            show_in_website=to_bool(request.form.get('show_in_website'), default=False),
            show_in_pos=to_bool(request.form.get('show_in_pos'), default=False),
        )

        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                product.image = save_product_image(file)

        db.session.add(product)
        db.session.flush()

        barcode_value, filename = BarcodeService.save_barcode_image(product.id, product.name_ku or 'Product')
        product.barcode = barcode_value

        db.session.commit()

        # ✅ LOG IT
        try:
            log_activity(
                action="add_product",
                entity_type="product",
                entity_id=product.id,
                title="Added product",
                note=f"{product.name_ku or product.name_ar or product.name_en} | Price: {product.price}",
                amount=int(product.price or 0),
                payment_method="store"
            )
        except Exception as e:
            print("❌ Activity log error:", e)

        if to_bool(request.form.get('print_label'), default=False):
            try:
                success, message = XPrinterService.print_barcode_label(
                    product.id, product.name_ku or 'Product', product.price, barcode_value
                )
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
        success, message = XPrinterService.print_barcode_label(
            product.id, product.name_ku or 'Product', product.price, product.barcode
        )
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
            if 'name_ku' in request.form:
                product.name_ku = request.form['name_ku']
            if 'name_ar' in request.form:
                product.name_ar = request.form['name_ar']
            if 'name_en' in request.form:
                product.name_en = request.form['name_en']

            if 'description_ku' in request.form:
                product.description_ku = request.form['description_ku']
            if 'description_ar' in request.form:
                product.description_ar = request.form['description_ar']
            if 'description_en' in request.form:
                product.description_en = request.form['description_en']

            if 'category_id' in request.form:
                try:
                    product.category_id = int(request.form['category_id']) if request.form['category_id'] else None
                except (ValueError, TypeError):
                    product.category_id = None
            if 'price' in request.form:
                try:
                    product.price = int(request.form['price'])
                except (ValueError, TypeError):
                    pass
            if 'stock' in request.form:
                try:
                    product.stock = int(request.form['stock'])
                except (ValueError, TypeError):
                    pass

            product.is_active = request.form.get('is_active') == 'true'
            product.show_in_website = request.form.get('show_in_website') == 'true'
            product.show_in_pos = request.form.get('show_in_pos') == 'true'

            if 'barcode' in request.form:
                product.barcode = request.form['barcode'].strip() or None

            if 'image' in request.files:
                file = request.files['image']
                if file and file.filename and allowed_file(file.filename):
                    if product.image:
                        old_image_path = os.path.join(UPLOAD_FOLDER, product.image)
                        if os.path.exists(old_image_path):
                            try:
                                os.remove(old_image_path)
                            except Exception:
                                pass
                    product.image = save_product_image(file)

        elif request.is_json:
            data = request.json or {}
            if 'name_ku' in data:
                product.name_ku = data['name_ku']
            if 'name_ar' in data:
                product.name_ar = data['name_ar']
            if 'name_en' in data:
                product.name_en = data['name_en']
            if 'description_ku' in data:
                product.description_ku = data['description_ku']
            if 'description_ar' in data:
                product.description_ar = data['description_ar']
            if 'description_en' in data:
                product.description_en = data['description_en']
            if 'category_id' in data:
                product.category_id = data['category_id']
            if 'price' in data:
                try:
                    product.price = int(data['price'])
                except (ValueError, TypeError):
                    pass
            if 'stock' in data:
                try:
                    product.stock = int(data['stock'])
                except (ValueError, TypeError):
                    pass
            if 'is_active' in data:
                product.is_active = data['is_active']
            if 'show_in_website' in data:
                product.show_in_website = data['show_in_website']
            if 'show_in_pos' in data:
                product.show_in_pos = data['show_in_pos']
            if 'barcode' in data:
                product.barcode = data['barcode']

        db.session.commit()
        return jsonify({'success': True, 'message': 'تم تحديث المنتج بنجاح'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


from sqlalchemy import text

@admin_bp.route('/api/product/<int:product_id>', methods=['DELETE', 'POST'])
@login_required
def delete_product(product_id):
    print("🔥 DELETE/POST HIT product_id =", product_id)

    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'}), 404

    try:
        # delete related items (safe)
        db.session.execute(text('DELETE FROM order_item WHERE product_id = :pid'), {'pid': product_id})

        try:
            db.session.execute(text('DELETE FROM pos_order_item WHERE product_id = :pid'), {'pid': product_id})
        except Exception as e:
            print("⚠️ pos_order_item skip:", e)

        # delete image file
        if product.image:
            image_path = os.path.join(UPLOAD_FOLDER, product.image)
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception:
                    pass

        # delete product row
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


@admin_bp.route('/api/booking/<int:booking_id>', methods=['GET'])
@login_required
def get_booking_api(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    return jsonify(booking.to_dict())


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
# ===== CATEGORIES MANAGEMENT =====
# ========================================

# ========================================
# ===== CATEGORIES MANAGEMENT =====
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

    existing = Category.query.filter(
        func.lower(func.trim(Category.name_ku)) == name_ku.lower()
    ).first()

    if existing:
        return jsonify({'success': False, 'message': 'ئەم پۆلە پێشتر تۆمارکراوە'}), 409

    try:
        category = Category(
            name_ku=data.get('name_ku'),
            name_ar=data.get('name_ar') or None,
            name_en=data.get('name_en') or None,
            description_ku=data.get('description_ku') or None,
            description_ar=data.get('description_ar') or None,
            description_en=data.get('description_en') or None,
            is_active=True,

            # ✅ NEW (defaults to True if not sent)
            show_on_website=bool(data.get('show_on_website', True)),
            show_on_pos=bool(data.get('show_on_pos', True)),
        )

        db.session.add(category)
        db.session.commit()

        # ✅ LOG
        try:
            log_activity(
                action="add_category",
                entity_type="category",
                entity_id=category.id,
                title="Added category",
                note=f"{category.name_ku or category.name_ar or category.name_en}",
                payment_method="store"
            )
        except Exception as e:
            print("❌ Activity log error:", e)

        return jsonify({
            'success': True,
            'message': 'پۆل بە سەرکەوتوویی زیاد کرا',
            'category_id': category.id,
            'category': category.to_dict()
        }), 201

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
        # Names
        if 'name_ku' in data:
            category.name_ku = data['name_ku']
        if 'name_ar' in data:
            category.name_ar = data['name_ar'] or None
        if 'name_en' in data:
            category.name_en = data['name_en'] or None

        # Descriptions ✅ (your old PUT didn’t update these)
        if 'description_ku' in data:
            category.description_ku = data['description_ku'] or None
        if 'description_ar' in data:
            category.description_ar = data['description_ar'] or None
        if 'description_en' in data:
            category.description_en = data['description_en'] or None

        # Active
        if 'is_active' in data:
            category.is_active = bool(data['is_active'])

        # ✅ NEW visibility flags
        if 'show_on_website' in data:
            category.show_on_website = bool(data['show_on_website'])
        if 'show_on_pos' in data:
            category.show_on_pos = bool(data['show_on_pos'])

        db.session.commit()

        # ✅ LOG
        try:
            log_activity(
                action="update_category",
                entity_type="category",
                entity_id=category.id,
                title="Updated category",
                note=f"{category.name_ku or category.name_ar or category.name_en}",
                payment_method="store"
            )
        except Exception as e:
            print("❌ Activity log error:", e)

        return jsonify({
            'success': True,
            'message': 'تم تحديث التصنيف بنجاح',
            'category': category.to_dict()
        })

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

        # ✅ LOG
        try:
            log_activity(
                action="delete_category",
                entity_type="category",
                entity_id=cid,
                title="Deleted category",
                note=f"{cname}",
                payment_method="store"
            )
        except Exception as e:
            print("❌ Activity log error:", e)

        return jsonify({'success': True, 'message': 'تم حذف التصنيف بنجاح'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ========================================
# ===== ORDERS MANAGEMENT =====
# ========================================

@admin_bp.route('/orders')
@login_required
def manage_orders():
    status_filter = request.args.get('status', 'all')
    delivery_filter = request.args.get('delivery', 'all')
    date_filter = (request.args.get('date') or '').strip()   # YYYY-MM-DD
    q = (request.args.get('q') or '').strip()                # name or phone

    query = Order.query

    # ✅ Status filter
    if status_filter and status_filter != 'all':
        query = query.filter(Order.status == status_filter)

    # ✅ Delivery method filter
    if delivery_filter and delivery_filter != 'all':
        query = query.filter(Order.delivery_method == delivery_filter)

    # ✅ Date filter (by created_at DAY)
    if date_filter:
        try:
            d = datetime.strptime(date_filter, '%Y-%m-%d').date()
            start_dt = datetime.combine(d, datetime.min.time())
            end_dt = start_dt + timedelta(days=1)
            query = query.filter(Order.created_at >= start_dt, Order.created_at < end_dt)
        except ValueError:
            pass

    # ✅ Search filter (name OR phone)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Order.customer_name.ilike(like),
            Order.customer_phone.ilike(like)
        ))

    orders = query.order_by(Order.created_at.desc()).all()

    return render_template(
        'admin/orders.html',
        orders=orders,
        current_status=status_filter,
        current_delivery=delivery_filter,
        current_date=date_filter,
        current_q=q
    )


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

    # ✅ Restore stock only when moving to cancelled (first time)
    if new_status == 'cancelled' and old_status != 'cancelled':
        for item in order.items:
            if item.product and hasattr(item.product, "stock") and item.product.stock is not None:
                item.product.stock += int(item.quantity or 0)

    order.status = new_status
    db.session.commit()

    # ✅ Notify on important statuses (SAFE)
    try:
        if new_status == 'confirmed' and old_status != 'confirmed':
            notify_admins(
                title="Order confirmed ✅",
                message=f"Order #{order.id} confirmed for {order.customer_name} ({order.customer_phone})",
                url=f"/admin/order/{order.id}",
                ntype="order_confirmed"
            )

        elif new_status == 'cancelled' and old_status != 'cancelled':
            notify_admins(
                title="Order cancelled ❌",
                message=f"Order #{order.id} cancelled for {order.customer_name} ({order.customer_phone})",
                url=f"/admin/order/{order.id}",
                ntype="order_cancelled"
            )

    except Exception as e:
        print("❌ Notification error:", e)

    # ✅ Send to Google Sheets ONLY ONCE when confirmed
    if new_status == 'confirmed' and old_status != 'confirmed':
        sheet_already_sent = bool(getattr(order, "sheet_sent", False))

        if not sheet_already_sent:
            try:
                # Build items string
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

                if hasattr(order, "sheet_sent"):
                    order.sheet_sent = True
                if hasattr(order, "sheet_sent_at"):
                    order.sheet_sent_at = datetime.utcnow()
                if hasattr(order, "sheet_last_error"):
                    order.sheet_last_error = None

                db.session.commit()

            except Exception as e:
                print("❌ Google Sheets error:", e)
                if hasattr(order, "sheet_last_error"):
                    order.sheet_last_error = str(e)
                    db.session.commit()

    # ✅ LOG IT
    try:
        log_activity(
            action="update_order_status",
            entity_type="order",
            entity_id=order.id,
            title="Order status changed",
            note=f"Old: {old_status} → New: {new_status}",
            amount=int(order.total_price or 0),
            payment_method="store"
        )
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

        # ✅ LOG
        try:
            log_activity(
                action="delete_order",
                entity_type="order",
                entity_id=oid,
                title="Deleted order",
                note="Order deleted from admin",
                amount=total,
                payment_method="store"
            )
        except Exception as e:
            print("❌ Activity log error:", e)

        return jsonify({'success': True, 'message': 'تم حذف الطلب بنجاح'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ========================================
# ===== STADIUMS MANAGEMENT =====
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
        stadium = Stadium(
            name=data.get('name'),
            description=data.get('description'),
            location=data.get('location'),
            price_per_hour=float(data.get('price_per_hour', 50000)),
            image_url=data.get('image_url'),
            is_active=data.get('is_active', True)
        )

        db.session.add(stadium)
        db.session.commit()

        # ✅ LOG
        try:
            log_activity(
                action="add_stadium",
                entity_type="stadium",
                entity_id=stadium.id,
                title="Added stadium",
                note=f"{stadium.name}",
                payment_method="booking"
            )
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
        if 'name' in data:
            stadium.name = data['name']
        if 'description' in data:
            stadium.description = data['description']
        if 'location' in data:
            stadium.location = data['location']
        if 'price_per_hour' in data:
            stadium.price_per_hour = float(data['price_per_hour'])
        if 'is_active' in data:
            stadium.is_active = data['is_active']
        if 'image_url' in data:
            stadium.image_url = data['image_url']

        db.session.commit()

        # ✅ LOG
        try:
            log_activity(
                action="update_stadium",
                entity_type="stadium",
                entity_id=stadium.id,
                title="Updated stadium",
                note=f"{stadium.name} | Active: {stadium.is_active}",
                payment_method="booking"
            )
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

        # ✅ LOG
        try:
            log_activity(
                action="delete_stadium",
                entity_type="stadium",
                entity_id=sid,
                title="Deleted stadium",
                note=sname,
                payment_method="booking"
            )
        except Exception as e:
            print("❌ Activity log error:", e)

        return jsonify({'success': True, 'message': 'تم حذف الملعب بنجاح'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ========================================
# ===== SETTINGS =====
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
                try:
                    settings.opening_hour = int(data.get('opening_hour'))
                except (ValueError, TypeError):
                    pass
            if data.get('closing_hour') is not None:
                try:
                    settings.closing_hour = int(data.get('closing_hour'))
                except (ValueError, TypeError):
                    pass
            if data.get('price_per_hour') is not None:
                try:
                    settings.price_per_hour = float(data.get('price_per_hour'))
                except (ValueError, TypeError):
                    pass

            if data.get('discount_percentage') is not None:
                try:
                    settings.discount_percentage = int(data.get('discount_percentage'))
                except (ValueError, TypeError):
                    pass
            if data.get('discount_start_hour') is not None:
                try:
                    settings.discount_start_hour = int(data.get('discount_start_hour'))
                except (ValueError, TypeError):
                    pass
            if data.get('discount_end_hour') is not None:
                try:
                    settings.discount_end_hour = int(data.get('discount_end_hour'))
                except (ValueError, TypeError):
                    pass

            if data.get('site_name') is not None:
                settings.site_name = str(data.get('site_name')).strip()
            if data.get('phone') is not None:
                settings.phone = str(data.get('phone')).strip()
            if data.get('email') is not None:
                settings.email = str(data.get('email')).strip()
            if data.get('address') is not None:
                settings.address = str(data.get('address')).strip()

            if data.get('facebook') is not None:
                settings.facebook = str(data.get('facebook')).strip() or None
            if data.get('instagram') is not None:
                settings.instagram = str(data.get('instagram')).strip() or None
            if data.get('whatsapp') is not None:
                settings.whatsapp = str(data.get('whatsapp')).strip() or None

            db.session.commit()

            # ✅ LOG
            try:
                log_activity(
                    action="update_settings",
                    entity_type="settings",
                    entity_id=getattr(settings, "id", None),
                    title="Updated settings",
                    note="Admin updated system settings",
                    payment_method="system"
                )
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
# ===== USERS MANAGEMENT (Super Admin Only) =====
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
    """Handle form-based user creation"""
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
        user = User(
            username=username,
            email=f"{username}@padelhouse.local",
            role=role,
            is_active=True,
            can_manage_bookings=request.form.get('can_manage_bookings') == 'on',
            can_manage_products=request.form.get('can_manage_products') == 'on',
            can_manage_orders=request.form.get('can_manage_orders') == 'on',
            can_manage_stadiums=request.form.get('can_manage_stadiums') == 'on',
            can_manage_settings=request.form.get('can_manage_settings') == 'on',
            can_view_reports=request.form.get('can_view_reports') == 'on',
            can_access_dashboard=request.form.get('can_access_dashboard') == 'on'
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        try:
            log_activity(
                action="add_user",
                entity_type="user",
                entity_id=user.id,
                title="Created user",
                note=f"Username: {user.username} | Role: {user.role}",
                payment_method="system"
            )
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
    """Handle form-based user editing"""
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

        # Only update role if not editing yourself
        if user.id != current_user.id and role:
            user.role = role

        # Update password if provided
        if password:
            user.set_password(password)

        # ✅ Update permissions
        user.can_manage_bookings = request.form.get('can_manage_bookings') == 'on'
        user.can_manage_products = request.form.get('can_manage_products') == 'on'
        user.can_manage_orders = request.form.get('can_manage_orders') == 'on'
        user.can_manage_stadiums = request.form.get('can_manage_stadiums') == 'on'
        user.can_manage_settings = request.form.get('can_manage_settings') == 'on'
        user.can_view_reports = request.form.get('can_view_reports') == 'on'
        user.can_access_dashboard = request.form.get('can_access_dashboard') == 'on'

        db.session.commit()

        try:
            log_activity(
                action="update_user",
                entity_type="user",
                entity_id=user.id,
                title="Updated user",
                note=f"Username: {user.username} | Role: {user.role}",
                payment_method="system"
            )
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
    """Handle form-based user deletion"""
    if user_id == current_user.id:
        flash('You cannot delete yourself!', 'danger')
        return redirect(url_for('admin.manage_users'))

    user = User.query.get_or_404(user_id)
    username = user.username

    try:
        db.session.delete(user)
        db.session.commit()

        try:
            log_activity(
                action="delete_user",
                entity_type="user",
                entity_id=user_id,
                title="Deleted user",
                note=f"Username: {username}",
                payment_method="system"
            )
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
    """API endpoint for adding users via AJAX"""
    data = request.json or {}

    if not data.get('username') or not data.get('password'):
        return jsonify({'success': False, 'message': 'Username and password required'}), 400

    if User.query.filter_by(username=data['username']).first():
        return jsonify({'success': False, 'message': 'Username already exists'}), 409

    try:
        user = User(
            username=data['username'],
            email=f"{data['username']}@padelhouse.local",
            role=data.get('role', 'admin'),
            is_active=True,
            can_manage_bookings=data.get('can_manage_bookings', False),
            can_manage_products=data.get('can_manage_products', False),
            can_manage_orders=data.get('can_manage_orders', False),
            can_manage_stadiums=data.get('can_manage_stadiums', False),
            can_manage_settings=data.get('can_manage_settings', False),
            can_view_reports=data.get('can_view_reports', False),
            can_access_dashboard=data.get('can_access_dashboard', False)
        )
        user.set_password(data['password'])

        db.session.add(user)
        db.session.commit()

        try:
            log_activity(
                action="add_user",
                entity_type="user",
                entity_id=user.id,
                title="Created user",
                note=f"Username: {user.username} | Role: {user.role}",
                payment_method="system"
            )
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
    """API endpoint for updating users"""
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    data = request.json or {}

    try:
        if data.get('username'):
            if user.username != data['username']:
                user.email = f"{data['username']}@padelhouse.local"
            user.username = data['username']

        if data.get('password'):
            user.set_password(data['password'])

        # Update role only if not editing yourself
        if user.id != current_user.id and 'role' in data:
            user.role = data['role']

        if 'is_active' in data:
            user.is_active = bool(data['is_active'])

        # ✅ Update permissions from API
        if 'can_manage_bookings' in data:
            user.can_manage_bookings = bool(data['can_manage_bookings'])
        if 'can_manage_products' in data:
            user.can_manage_products = bool(data['can_manage_products'])
        if 'can_manage_orders' in data:
            user.can_manage_orders = bool(data['can_manage_orders'])
        if 'can_manage_stadiums' in data:
            user.can_manage_stadiums = bool(data['can_manage_stadiums'])
        if 'can_manage_settings' in data:
            user.can_manage_settings = bool(data['can_manage_settings'])
        if 'can_view_reports' in data:
            user.can_view_reports = bool(data['can_view_reports'])
        if 'can_access_dashboard' in data:
            user.can_access_dashboard = bool(data['can_access_dashboard'])

        db.session.commit()

        try:
            log_activity(
                action="update_user",
                entity_type="user",
                entity_id=user.id,
                title="Updated user",
                note=f"Username: {user.username} | Active: {user.is_active} | Role: {user.role}",
                payment_method="system"
            )
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
    """Toggle user active status"""
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    if user.id == current_user.id:
        return jsonify({'success': False, 'message': 'Cannot deactivate yourself'}), 403

    try:
        user.is_active = not user.is_active
        db.session.commit()

        try:
            log_activity(
                action="toggle_user",
                entity_type="user",
                entity_id=user.id,
                title="Toggled user status",
                note=f"Username: {user.username} | Active: {user.is_active}",
                payment_method="system"
            )
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
    """API endpoint for deleting users"""
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
            log_activity(
                action="delete_user",
                entity_type="user",
                entity_id=uid,
                title="Deleted user",
                note=f"Username: {uname}",
                payment_method="system"
            )
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
            try:
                settings.opening_hour = int(data['opening_hour'])
            except (ValueError, TypeError):
                pass
        if data.get('closing_hour') is not None:
            try:
                settings.closing_hour = int(data['closing_hour'])
            except (ValueError, TypeError):
                pass
        if data.get('price_per_hour') is not None:
            try:
                settings.price_per_hour = float(data['price_per_hour'])
            except (ValueError, TypeError):
                pass

        if data.get('discount_percentage') is not None:
            try:
                settings.discount_percentage = int(data['discount_percentage'])
            except (ValueError, TypeError):
                pass
        if data.get('discount_start_hour') is not None:
            try:
                settings.discount_start_hour = int(data['discount_start_hour'])
            except (ValueError, TypeError):
                pass
        if data.get('discount_end_hour') is not None:
            try:
                settings.discount_end_hour = int(data['discount_end_hour'])
            except (ValueError, TypeError):
                pass

        if data.get('site_name') is not None:
            settings.site_name = str(data['site_name']).strip()
        if data.get('phone') is not None:
            settings.phone = str(data['phone']).strip()
        if data.get('email') is not None:
            settings.email = str(data['email']).strip()
        if data.get('address') is not None:
            settings.address = str(data['address']).strip()

        if data.get('facebook') is not None:
            settings.facebook = str(data['facebook']).strip() or None
        if data.get('instagram') is not None:
            settings.instagram = str(data['instagram']).strip() or None
        if data.get('whatsapp') is not None:
            settings.whatsapp = str(data['whatsapp']).strip() or None

        db.session.commit()
        return jsonify({'success': True, 'message': 'Saved'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/pending-count', methods=['GET'])
@login_required
def admin_pending_count_api():
    count = Booking.query.filter_by(status='pending').count()
    return jsonify({'pending': count}), 200


# ========================================
# ===== NOTIFICATIONS API =====
# ========================================

@admin_bp.route('/api/notifications', methods=['GET'])
@login_required
def api_notifications():
    items = Notification.query.filter(
        (Notification.user_id == None) | (Notification.user_id == current_user.id)
    ).order_by(Notification.created_at.desc()).limit(20).all()

    return jsonify({
        "success": True,
        "items": [
            {
                "id": n.id,
                "title": n.title,
                "message": n.message,
                "url": n.url,
                "type": n.type,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None
            } for n in items
        ]
    })


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
# ===== UNIFIED REPORTS (Website + POS) =====
# ========================================

# ========================================
# ===== UPDATED REPORTS WITH EXPENSES =====
# ========================================
# Replace your existing reports() function in admin.py with this:

# ========================================
# ===== UPDATED REPORTS WITH EXPENSES =====
# ========================================
# Replace your existing reports() function in admin.py with this:

@admin_bp.route('/reports')
@login_required
@permission_required('can_view_reports')
def reports():
    """Unified reports page showing website bookings, store orders, POS sessions, Manual Debts + EXPENSES"""

    # Get date range
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

    # ===== WEBSITE BOOKINGS =====
    bookings = Booking.query.filter(
        Booking.date >= from_date,
        Booking.date <= to_date,
        Booking.status.in_(['confirmed', 'completed'])
    ).all()
    total_bookings = len(bookings)
    booking_revenue = sum(b.final_price or 0 for b in bookings)

    # ===== WEBSITE STORE ORDERS =====
    orders = Order.query.filter(
        Order.created_at >= start_datetime,
        Order.created_at <= end_datetime,
        Order.status.in_(['confirmed', 'completed', 'delivered'])
    ).all()
    total_orders = len(orders)
    order_revenue = sum(o.total_price or 0 for o in orders)

    # ===== POS SESSIONS =====
    pos_revenue = 0
    pos_cash = 0
    pos_card = 0
    total_pos_sessions = 0
    active_pos_sessions = 0

    if POSSession:
        pos_sessions = POSSession.query.filter(
            POSSession.created_at >= start_datetime,
            POSSession.created_at <= end_datetime,
            POSSession.status == 'paid'
        ).all()

        total_pos_sessions = len(pos_sessions)
        pos_revenue = sum(s.total_amount or 0 for s in pos_sessions)
        pos_cash = sum(s.total_amount or 0 for s in pos_sessions if s.payment_method == 'cash')
        pos_card = sum(s.total_amount or 0 for s in pos_sessions if s.payment_method == 'card')

        active_pos_sessions = POSSession.query.filter_by(status='active').count()

    # ===== TOTAL REVENUE =====
    total_revenue = booking_revenue + order_revenue + pos_revenue

    # ===== MANUAL DEBTS =====
    manual_debts = ManualDebt.query.filter(
        ManualDebt.date >= from_date,
        ManualDebt.date <= to_date
    ).order_by(ManualDebt.date.desc(), ManualDebt.id.desc()).all()

    manual_debt_count = len(manual_debts)
    manual_debt_total = sum((d.amount or 0) for d in manual_debts)
    manual_debt_paid_total = sum((d.paid_amount or 0) for d in manual_debts)
    manual_debt_remaining_total = sum(
        max(0, (d.amount or 0) - (d.paid_amount or 0)) for d in manual_debts
    )

    # ✅ ===== EXPENSES (NEW) =====
    expenses = Expense.query.filter(
        Expense.date >= from_date,
        Expense.date <= to_date
    ).order_by(Expense.date.desc(), Expense.id.desc()).all()

    expense_count = len(expenses)
    total_expenses = sum((e.amount or 0) for e in expenses)

    # Expenses by category
    expense_by_category = {}
    for exp in expenses:
        cat = exp.get_category_name()
        if cat not in expense_by_category:
            expense_by_category[cat] = 0
        expense_by_category[cat] += exp.amount

    # Expenses by payment method
    expense_cash = sum((e.amount or 0) for e in expenses if e.payment_method == 'cash')
    expense_card = sum((e.amount or 0) for e in expenses if e.payment_method == 'card')

    # ✅ ===== NET PROFIT (NEW) =====
    net_profit = total_revenue - total_expenses

    # ===== TODAY'S ACTIVITY LOG =====
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())

    activities = ActivityLog.query.filter(
        ActivityLog.created_at >= today_start,
        ActivityLog.created_at <= today_end
    ).order_by(ActivityLog.created_at.desc()).limit(50).all()

    return render_template(
        'admin/reports.html',
        from_date=from_date.strftime('%Y-%m-%d'),
        to_date=to_date.strftime('%Y-%m-%d'),

        # Bookings
        total_bookings=total_bookings,
        booking_revenue=booking_revenue,

        # Store Orders
        total_orders=total_orders,
        order_revenue=order_revenue,

        # POS
        total_pos_sessions=total_pos_sessions,
        active_pos_sessions=active_pos_sessions,
        pos_revenue=pos_revenue,
        pos_cash=pos_cash,
        pos_card=pos_card,

        # Total Revenue
        total_revenue=total_revenue,

        # Activity Log
        activities=activities,

        # Debts
        manual_debts=manual_debts,
        manual_debt_count=manual_debt_count,
        manual_debt_total=manual_debt_total,
        manual_debt_paid_total=manual_debt_paid_total,
        manual_debt_remaining_total=manual_debt_remaining_total,

        # ✅ Expenses (NEW)
        expenses=expenses,
        expense_count=expense_count,
        total_expenses=total_expenses,
        expense_by_category=expense_by_category,
        expense_cash=expense_cash,
        expense_card=expense_card,

        # ✅ Net Profit (NEW)
        net_profit=net_profit
    )

# ========================================
# ===== MANUAL DEBTS (ديون يدوية) =====
# ========================================

@admin_bp.route("/manual-debts/add", methods=["POST"])
@login_required
@permission_required('can_view_reports')
def add_manual_debt():
    try:
        name = (request.form.get("name") or "").strip()
        phone = (request.form.get("phone") or "").strip() or None
        note = (request.form.get("note") or "").strip() or None

        try:
            amount = int(request.form.get("amount") or 0)
        except (ValueError, TypeError):
            amount = 0

        if not name:
            flash("الاسم مطلوب", "danger")
            return redirect(url_for("admin.reports"))
        if amount <= 0:
            flash("المبلغ يجب أن يكون أكبر من صفر", "danger")
            return redirect(url_for("admin.reports"))

        # date
        date_str = request.form.get("date")
        try:
            debt_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            debt_date = date.today()

        # keep filter dates after add
        from_date = request.form.get("from")
        to_date = request.form.get("to")

        d = ManualDebt(
            name=name,
            phone=phone,
            amount=amount,
            paid_amount=0,
            note=note,
            date=debt_date,
            status="open"
        )

        db.session.add(d)
        db.session.commit()

        flash("تمت إضافة الدين بنجاح ✅", "success")
        return redirect(url_for("admin.reports", **{'from': from_date, 'to': to_date} if from_date and to_date else {}))

    except Exception as e:
        db.session.rollback()
        flash(f"خطأ: {str(e)}", "danger")
        return redirect(url_for("admin.reports"))
# ========================================
# ===== EXPENSES MANAGEMENT =====
# ========================================
# Add this to your admin.py file after the manual_debts routes

from app.models.expense import Expense


@admin_bp.route('/expenses')
@login_required
@permission_required('can_view_reports')
def manage_expenses():
    """صفحة إدارة المصاريف"""

    # Get filters
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

    # Build query
    query = Expense.query.filter(
        Expense.date >= from_date,
        Expense.date <= to_date
    )

    if category_filter != 'all':
        query = query.filter_by(category=category_filter)

    expenses = query.order_by(Expense.date.desc(), Expense.id.desc()).all()

    # Calculate totals by category
    category_totals = {}
    total_amount = 0

    for exp in expenses:
        cat = exp.category
        if cat not in category_totals:
            category_totals[cat] = 0
        category_totals[cat] += exp.amount
        total_amount += exp.amount

    # Get categories
    categories = Expense.get_categories()

    return render_template(
        'admin/expenses.html',
        expenses=expenses,
        categories=categories,
        category_totals=category_totals,
        total_amount=total_amount,
        from_date=from_date.strftime('%Y-%m-%d'),
        to_date=to_date.strftime('%Y-%m-%d'),
        current_category=category_filter
    )


# ========================================
# ===== EXPENSES MANAGEMENT =====
# ========================================

@admin_bp.route('/expenses/add', methods=['POST'])
@login_required
@permission_required('can_view_reports')
def add_expense():
    """إضافة مصروف جديد"""
    try:
        date_str = request.form.get('date')
        category = (request.form.get('category') or '').strip()
        amount_str = request.form.get('amount', '0')
        description = (request.form.get('description') or '').strip()
        payment_method = request.form.get('payment_method', 'cash')

        if not category:
            flash('الرجاء اختيار فئة المصروف', 'danger')
            return redirect(url_for('admin.reports'))

        try:
            amount = int(amount_str)
        except (ValueError, TypeError):
            amount = 0

        if amount <= 0:
            flash('المبلغ يجب أن يكون أكبر من صفر', 'danger')
            return redirect(url_for('admin.reports'))

        try:
            expense_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            expense_date = date.today()

        expense = Expense(
            date=expense_date,
            category=category,
            amount=amount,
            description=description,
            payment_method=payment_method,
            created_by=current_user.id
        )

        db.session.add(expense)
        db.session.commit()

        try:
            log_activity(
                action="add_expense",
                entity_type="expense",
                entity_id=expense.id,
                title="Added expense",
                note=f"{expense.get_category_name()} | {description or '-'}",
                amount=amount,
                payment_method="expense"
            )
        except Exception as e:
            print("❌ Activity log error:", e)

        flash(f'تمت إضافة المصروف بنجاح ✅ | المبلغ: {amount:,} IQD', 'success')

        from_date = request.form.get('from')
        to_date = request.form.get('to')

        return redirect(url_for('admin.reports',
                                **{'from': from_date, 'to': to_date}
                                if from_date and to_date else {}))

    except Exception as e:
        db.session.rollback()
        flash(f'خطأ: {str(e)}', 'danger')
        return redirect(url_for('admin.reports'))




@admin_bp.route('/expenses/<int:expense_id>/edit', methods=['POST'])
@login_required
@permission_required('can_view_reports')
def edit_expense(expense_id):
    """تعديل مصروف"""
    expense = Expense.query.get_or_404(expense_id)

    try:
        # Get form data
        date_str = request.form.get('date')
        category = (request.form.get('category') or '').strip()
        amount_str = request.form.get('amount', '0')
        description = (request.form.get('description') or '').strip()
        payment_method = request.form.get('payment_method', 'cash')
        reference_number = (request.form.get('reference_number') or '').strip() or None

        # Validate
        if not category:
            flash('الرجاء اختيار فئة المصروف', 'danger')
            return redirect(url_for('admin.manage_expenses'))

        try:
            amount = int(amount_str)
        except (ValueError, TypeError):
            amount = 0

        if amount <= 0:
            flash('المبلغ يجب أن يكون أكبر من صفر', 'danger')
            return redirect(url_for('admin.manage_expenses'))

        # Parse date
        try:
            expense_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            expense_date = expense.date

        # Update expense
        expense.date = expense_date
        expense.category = category
        expense.amount = amount
        expense.description = description
        expense.payment_method = payment_method
        expense.reference_number = reference_number
        expense.updated_at = datetime.utcnow()

        db.session.commit()

        # ✅ LOG IT
        try:
            log_activity(
                action="edit_expense",
                entity_type="expense",
                entity_id=expense.id,
                title="Updated expense",
                note=f"{expense.get_category_name()} | {description or '-'}",
                amount=amount,
                payment_method="expense"
            )
        except Exception as e:
            print("❌ Activity log error:", e)

        flash('تم تحديث المصروف بنجاح ✅', 'success')

        # Keep filters
        from_date = request.form.get('from')
        to_date = request.form.get('to')
        category_filter = request.form.get('category_filter', 'all')

        return redirect(url_for('admin.manage_expenses',
                                **{'from': from_date, 'to': to_date, 'category': category_filter}
                                if from_date and to_date else {}))

    except Exception as e:
        db.session.rollback()
        flash(f'خطأ: {str(e)}', 'danger')
        return redirect(url_for('admin.manage_expenses'))


@admin_bp.route('/expenses/<int:expense_id>/delete', methods=['POST', 'GET'])
@login_required
@permission_required('can_view_reports')
def delete_expense(expense_id):
    """حذف مصروف"""
    expense = Expense.query.get_or_404(expense_id)

    try:
        eid = expense.id
        eamount = expense.amount
        ecat = expense.get_category_name()

        db.session.delete(expense)
        db.session.commit()

        # ✅ LOG IT
        try:
            log_activity(
                action="delete_expense",
                entity_type="expense",
                entity_id=eid,
                title="Deleted expense",
                note=f"{ecat} | Amount: {eamount:,} IQD",
                amount=eamount,
                payment_method="expense"
            )
        except Exception as e:
            print("❌ Activity log error:", e)

        flash('تم حذف المصروف بنجاح ✅', 'success')

        # Keep filters
        from_date = request.args.get('from')
        to_date = request.args.get('to')
        category_filter = request.args.get('category', 'all')

        return redirect(url_for('admin.manage_expenses',
                                **{'from': from_date, 'to': to_date, 'category': category_filter}
                                if from_date and to_date else {}))

    except Exception as e:
        db.session.rollback()
        flash(f'خطأ: {str(e)}', 'danger')
        return redirect(url_for('admin.manage_expenses'))

@admin_bp.route("/manual-debts/<int:debt_id>/mark-paid", methods=["GET"])
@login_required
@permission_required('can_view_reports')
def mark_manual_debt_paid(debt_id):
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