# admin.py (routes) - Updated with Pending Bookings Approval System
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
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
from datetime import datetime, date
import os
import random


def generate_product_barcode():
    """Generate a unique 13-digit barcode for EAN-13 format"""
    # Prefix: 743 (custom for Padel House)
    prefix = "743"

    # Timestamp: YYMMDD (6 digits)
    timestamp = datetime.now().strftime("%y%m%d")

    # Random: 3 digits
    random_part = ''.join([str(random.randint(0, 9)) for _ in range(3)])

    # Combine first 12 digits
    barcode_12 = f"{prefix}{timestamp}{random_part}"

    # Calculate check digit (EAN-13 algorithm)
    total = 0
    for i, digit in enumerate(barcode_12):
        if i % 2 == 0:
            total += int(digit)
        else:
            total += int(digit) * 3
    check_digit = (10 - (total % 10)) % 10

    return f"{barcode_12}{check_digit}"


admin_bp = Blueprint('admin', __name__)

UPLOAD_FOLDER = 'app/static/images/products'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def super_admin_required(f):
    """Decorator to require super_admin role"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role != 'super_admin':
            return jsonify({'success': False, 'message': 'غير مصرح لك بهذا الإجراء'}), 403
        return f(*args, **kwargs)

    return decorated_function


# ===== CONTEXT PROCESSOR FOR PENDING COUNT =====
@admin_bp.app_context_processor
def inject_pending_count():
    """Inject pending bookings count into all admin templates"""
    if current_user.is_authenticated:
        pending_bookings_count = Booking.query.filter_by(status='pending').count()
        return {'pending_bookings_count': pending_bookings_count}
    return {'pending_bookings_count': 0}


# ===== ADMIN DASHBOARD =====
@admin_bp.route('/')
@admin_bp.route('/dashboard')
@login_required
def dashboard():
    """Admin dashboard with statistics"""
    # 1. Booking statistics
    total_bookings = Booking.query.count()

    # Calculate Total Revenue
    total_revenue = db.session.query(
        db.func.sum(Booking.final_price)
    ).filter(Booking.status.in_(['confirmed', 'completed'])).scalar() or 0

    # Calculate Today's Bookings Count
    today_bookings = Booking.query.filter(
        Booking.date == date.today()
    ).count()

    # Calculate Today's Revenue
    today_revenue = db.session.query(
        db.func.sum(Booking.final_price)
    ).filter(
        Booking.status.in_(['confirmed', 'completed']),
        Booking.date == date.today()
    ).scalar() or 0

    # Pending bookings count
    pending_bookings = Booking.query.filter_by(status='pending').count()

    # 2. Store statistics
    total_products = Product.query.filter_by(is_active=True).count()
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status='pending').count()

    # Calculate store revenue
    store_revenue = db.session.query(
        db.func.sum(Order.total_price)
    ).filter(Order.status.in_(['confirmed', 'completed', 'delivered'])).scalar() or 0

    stadiums = Stadium.query.all()
    recent_bookings = Booking.query.order_by(Booking.created_at.desc()).limit(5).all()
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(5).all()

    # Get pending bookings for quick access
    pending_booking_list = Booking.query.filter_by(status='pending').order_by(Booking.created_at.desc()).limit(5).all()

    return render_template('admin/dashboard.html',
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
                           pending_booking_list=pending_booking_list
                           )


# ========================================
# ===== PENDING BOOKINGS MANAGEMENT =====
# ========================================

@admin_bp.route('/pending-bookings')
@login_required
def pending_bookings():
    """View all pending bookings that need admin approval"""
    bookings = Booking.query.filter_by(status='pending').order_by(Booking.created_at.desc()).all()
    stadiums = Stadium.query.all()
    return render_template('admin/pending_bookings.html',
                           bookings=bookings,
                           stadiums=stadiums)


@admin_bp.route('/api/booking/<int:booking_id>/approve', methods=['POST'])
@login_required
def approve_booking(booking_id):
    """Approve a pending booking - Admin calls customer then approves"""
    booking = Booking.query.get(booking_id)

    if not booking:
        return jsonify({'success': False, 'message': 'الحجز غير موجود'}), 404

    if booking.status != 'pending':
        return jsonify({'success': False, 'message': 'هذا الحجز ليس معلقاً'}), 400

    # Update booking status
    booking.status = 'confirmed'
    booking.confirmed_at = datetime.utcnow()

    # Record who approved it (if field exists)
    if hasattr(booking, 'confirmed_by'):
        booking.confirmed_by = current_user.id

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f'تم قبول حجز {booking.customer_name} بنجاح ✅',
        'booking_id': booking.id,
        'new_status': 'confirmed'
    })


@admin_bp.route('/api/booking/<int:booking_id>/reject', methods=['POST'])
@login_required
def reject_booking(booking_id):
    """Reject a pending booking with optional reason"""
    booking = Booking.query.get(booking_id)

    if not booking:
        return jsonify({'success': False, 'message': 'الحجز غير موجود'}), 404

    if booking.status != 'pending':
        return jsonify({'success': False, 'message': 'هذا الحجز ليس معلقاً'}), 400

    data = request.json or {}
    rejection_reason = data.get('reason', '')

    # Update booking status
    booking.status = 'cancelled'

    # Store rejection reason
    if hasattr(booking, 'rejection_reason'):
        booking.rejection_reason = rejection_reason

    # Also add to notes for backup
    if rejection_reason:
        existing_notes = booking.notes or ''
        booking.notes = f"{existing_notes}\n[رفض] سبب الرفض: {rejection_reason}".strip()

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f'تم رفض حجز {booking.customer_name} ❌',
        'booking_id': booking.id,
        'new_status': 'cancelled'
    })


# ===== MANAGE BOOKINGS =====
@admin_bp.route('/bookings')
@login_required
def manage_bookings():
    """View and manage all bookings"""
    status_filter = request.args.get('status', 'all')
    stadium_filter = request.args.get('stadium', 'all')

    query = Booking.query

    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    if stadium_filter != 'all':
        query = query.filter_by(stadium_id=int(stadium_filter))

    bookings = query.order_by(Booking.date.desc(), Booking.created_at.desc()).all()
    stadiums = Stadium.query.all()

    return render_template('admin/bookings.html',
                           bookings=bookings,
                           stadiums=stadiums,
                           current_status=status_filter,
                           current_stadium=stadium_filter
                           )


# ===== BOOKING DETAILS =====
@admin_bp.route('/booking/<int:booking_id>')
@login_required
def booking_detail(booking_id):
    """View specific booking details"""
    booking = Booking.query.get_or_404(booking_id)
    return render_template('admin/booking_detail.html', booking=booking)


# ===== UPDATE BOOKING STATUS =====
@admin_bp.route('/api/booking/<int:booking_id>/status', methods=['POST'])
@login_required
def update_booking_status(booking_id):
    """Update booking status"""
    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'success': False, 'message': 'Booking not found'}), 404

    data = request.json
    new_status = data.get('status')

    if new_status not in ['pending', 'confirmed', 'completed', 'cancelled']:
        return jsonify({'success': False, 'message': 'Invalid status'}), 400

    old_status = booking.status
    booking.status = new_status

    # If confirming, record confirmation time
    if new_status == 'confirmed' and old_status == 'pending':
        booking.confirmed_at = datetime.utcnow()
        if hasattr(booking, 'confirmed_by'):
            booking.confirmed_by = current_user.id

    db.session.commit()

    return jsonify({'success': True, 'message': f'تم تحديث الحجز إلى {new_status}'})


# ===== DELETE BOOKING =====
@admin_bp.route('/api/booking/<int:booking_id>', methods=['DELETE'])
@login_required
def delete_booking(booking_id):
    """Delete booking"""
    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'success': False, 'message': 'Booking not found'}), 404

    db.session.delete(booking)
    db.session.commit()

    return jsonify({'success': True, 'message': 'تم حذف الحجز بنجاح'})


# ========================================
# ===== PRODUCTS MANAGEMENT =====
# ========================================

@admin_bp.route('/products')
@login_required
def manage_products():
    """View and manage all products"""
    products = Product.query.order_by(Product.created_at.desc()).all()
    categories = Category.query.filter_by(is_active=True).all()
    return render_template('admin/products.html', products=products, categories=categories)


@admin_bp.route('/api/product', methods=['POST'])
@login_required
def add_product():
    try:
        # Multilingual names
        name_ku = request.form.get('name_ku')
        name_ar = request.form.get('name_ar')
        name_en = request.form.get('name_en')

        # Multilingual descriptions
        description_ku = request.form.get('description_ku')
        description_ar = request.form.get('description_ar')
        description_en = request.form.get('description_en')

        category_id = request.form.get('category_id')
        price = request.form.get('price')
        stock = request.form.get('stock', 0)
        is_active = request.form.get('is_active', 'true') == 'true'

        # ✅ جديد: أين يظهر المنتج
        show_in_website = request.form.get('show_in_website', 'true') == 'true'
        show_in_pos = request.form.get('show_in_pos', 'true') == 'true'

        # ✅ باركود - توليد تلقائي فقط لمنتجات المتجر (الموقع)
        barcode = request.form.get('barcode', '').strip()
        if not barcode and show_in_website:
            # Auto-generate barcode ONLY for store/website products
            barcode = generate_product_barcode()
        elif not barcode:
            # No barcode for POS-only items (coffee, food, etc.)
            barcode = None

        # Validation
        if not name_ku or not price or not category_id:
            return jsonify({
                'success': False,
                'message': 'ناوی کوردی، نرخ و پۆل پێویستن'
            }), 400

        # Handle image upload
        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                image_filename = filename

        product = Product(
            name_ku=name_ku,
            name_ar=name_ar,
            name_en=name_en,
            description_ku=description_ku,
            description_ar=description_ar,
            description_en=description_en,
            category_id=int(category_id),
            price=int(price),
            stock=int(stock),
            image=image_filename,
            is_active=is_active,
            show_in_website=show_in_website,
            show_in_pos=show_in_pos,
            barcode=barcode
        )

        db.session.add(product)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'بەرهەم بە سەرکەوتوویی زیاد کرا',
            'product_id': product.id
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/product/<int:product_id>', methods=['PUT', 'POST'])
@login_required
def update_product(product_id):
    """Update product - FIXED to handle all fields including visibility"""
    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'}), 404

    try:
        # Handle form data
        if request.form:
            # Multilingual names
            if 'name_ku' in request.form:
                product.name_ku = request.form['name_ku']
            if 'name_ar' in request.form:
                product.name_ar = request.form['name_ar']
            if 'name_en' in request.form:
                product.name_en = request.form['name_en']

            # Multilingual descriptions
            if 'description_ku' in request.form:
                product.description_ku = request.form['description_ku']
            if 'description_ar' in request.form:
                product.description_ar = request.form['description_ar']
            if 'description_en' in request.form:
                product.description_en = request.form['description_en']

            # Basic fields
            if 'category_id' in request.form:
                product.category_id = int(request.form['category_id']) if request.form['category_id'] else None
            if 'price' in request.form:
                product.price = int(request.form['price'])
            if 'stock' in request.form:
                product.stock = int(request.form['stock'])

            # ✅ FIXED: Handle checkboxes properly (unchecked = not in form = false)
            product.is_active = request.form.get('is_active') == 'true'
            product.show_in_website = request.form.get('show_in_website') == 'true'
            product.show_in_pos = request.form.get('show_in_pos') == 'true'

            # Barcode
            if 'barcode' in request.form:
                product.barcode = request.form['barcode'].strip() or None

            # Handle image upload
            if 'image' in request.files:
                file = request.files['image']
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"

                    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                    file.save(os.path.join(UPLOAD_FOLDER, filename))

                    # Delete old image if exists
                    if product.image:
                        old_image_path = os.path.join(UPLOAD_FOLDER, product.image)
                        if os.path.exists(old_image_path):
                            os.remove(old_image_path)

                    product.image = filename

        # Handle JSON data
        elif request.is_json:
            data = request.json
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
                product.price = int(data['price'])
            if 'stock' in data:
                product.stock = int(data['stock'])
            if 'is_active' in data:
                product.is_active = data['is_active']
            if 'show_in_website' in data:
                product.show_in_website = data['show_in_website']
            if 'show_in_pos' in data:
                product.show_in_pos = data['show_in_pos']
            if 'barcode' in data:
                product.barcode = data['barcode']

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'تم تحديث المنتج بنجاح'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/product/<int:product_id>', methods=['DELETE'])
@login_required
def delete_product(product_id):
    """Delete product"""
    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'}), 404

    try:
        # Delete image file if exists
        if product.image:
            image_path = os.path.join(UPLOAD_FOLDER, product.image)
            if os.path.exists(image_path):
                os.remove(image_path)

        db.session.delete(product)
        db.session.commit()

        return jsonify({'success': True, 'message': 'تم حذف المنتج بنجاح'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/product/<int:product_id>/toggle', methods=['POST'])
@login_required
def toggle_product(product_id):
    """Toggle product active status"""
    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'}), 404

    product.is_active = not product.is_active
    db.session.commit()

    status = 'مفعل' if product.is_active else 'معطل'
    return jsonify({'success': True, 'message': f'تم تحديث المنتج: {status}', 'is_active': product.is_active})


# ========================================
# ===== BARCODE PRINTING =====
# ========================================

@admin_bp.route('/print-barcodes')
@login_required
def print_barcodes():
    """Barcode printing page"""
    products = Product.query.filter_by(is_active=True).order_by(Product.name_ku).all()
    categories = Category.query.filter_by(is_active=True).all()
    return render_template('admin/print_barcodes.html', products=products, categories=categories)


@admin_bp.route('/api/product/<int:product_id>/regenerate-barcode', methods=['POST'])
@login_required
def regenerate_barcode(product_id):
    """Regenerate barcode for a product"""
    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'}), 404

    # Generate new barcode
    new_barcode = generate_product_barcode()

    # Make sure it's unique
    while Product.query.filter_by(barcode=new_barcode).first():
        new_barcode = generate_product_barcode()

    product.barcode = new_barcode
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'تم توليد باركود جديد',
        'barcode': new_barcode
    })


# ========================================
# ===== CATEGORIES MANAGEMENT =====
# ========================================

@admin_bp.route('/categories')
@login_required
def manage_categories():
    """View and manage all categories"""
    categories = Category.query.order_by(Category.created_at.desc()).all()
    return render_template('admin/categories.html', categories=categories)


@admin_bp.route('/api/category', methods=['POST'])
@login_required
def add_category():
    data = request.get_json()

    if not data or not data.get('name_ku'):
        return jsonify({
            'success': False,
            'message': 'ناوی پۆل (کوردی) پێویستە'
        }), 400

    if Category.query.filter_by(name_ku=data['name_ku']).first():
        return jsonify({
            'success': False,
            'message': 'ئەم پۆلە پێشتر تۆمارکراوە'
        }), 409

    category = Category(
        name_ku=data['name_ku'],
        name_ar=data.get('name_ar'),
        name_en=data.get('name_en'),
        description_ku=data.get('description_ku'),
        description_ar=data.get('description_ar'),
        description_en=data.get('description_en'),
        is_active=True
    )

    db.session.add(category)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'پۆل بە سەرکەوتوویی زیاد کرا',
        'category_id': category.id
    }), 201


@admin_bp.route('/api/category/<int:category_id>', methods=['PUT'])
@login_required
def update_category(category_id):
    """Update category"""
    category = Category.query.get(category_id)
    if not category:
        return jsonify({'success': False, 'message': 'التصنيف غير موجود'}), 404

    data = request.json

    if 'name' in data:
        category.name = data['name']
    if 'name_en' in data:
        category.name_en = data['name_en']
    if 'is_active' in data:
        category.is_active = data['is_active']

    db.session.commit()

    return jsonify({'success': True, 'message': 'تم تحديث التصنيف بنجاح'})


@admin_bp.route('/api/category/<int:category_id>', methods=['DELETE'])
@login_required
def delete_category(category_id):
    """Delete category"""
    category = Category.query.get(category_id)
    if not category:
        return jsonify({'success': False, 'message': 'التصنيف غير موجود'}), 404

    # Check if has products
    if category.products:
        return jsonify({'success': False, 'message': 'لا يمكن حذف تصنيف يحتوي على منتجات'}), 409

    db.session.delete(category)
    db.session.commit()

    return jsonify({'success': True, 'message': 'تم حذف التصنيف بنجاح'})


# ========================================
# ===== ORDERS MANAGEMENT =====
# ========================================

@admin_bp.route('/orders')
@login_required
def manage_orders():
    """View and manage all orders"""
    status_filter = request.args.get('status', 'all')

    query = Order.query

    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    orders = query.order_by(Order.created_at.desc()).all()

    return render_template('admin/orders.html',
                           orders=orders,
                           current_status=status_filter
                           )


@admin_bp.route('/order/<int:order_id>')
@login_required
def order_detail(order_id):
    """View specific order details"""
    order = Order.query.get_or_404(order_id)
    return render_template('admin/order_detail.html', order=order)


@admin_bp.route('/api/order/<int:order_id>/status', methods=['POST'])
@login_required
def update_order_status(order_id):
    """Update order status"""
    order = Order.query.get(order_id)
    if not order:
        return jsonify({'success': False, 'message': 'الطلب غير موجود'}), 404

    data = request.json
    new_status = data.get('status')

    if new_status not in ['pending', 'confirmed', 'processing', 'delivered', 'cancelled']:
        return jsonify({'success': False, 'message': 'حالة غير صالحة'}), 400

    # If cancelling, restore stock
    if new_status == 'cancelled' and order.status != 'cancelled':
        for item in order.items:
            item.product.stock += item.quantity

    order.status = new_status
    db.session.commit()

    return jsonify({'success': True, 'message': f'تم تحديث الطلب بنجاح'})


@admin_bp.route('/api/order/<int:order_id>', methods=['DELETE'])
@login_required
def delete_order(order_id):
    """Delete order"""
    order = Order.query.get(order_id)
    if not order:
        return jsonify({'success': False, 'message': 'الطلب غير موجود'}), 404

    # Restore stock if order wasn't cancelled
    if order.status != 'cancelled':
        for item in order.items:
            item.product.stock += item.quantity

    # Delete order items first
    OrderItem.query.filter_by(order_id=order_id).delete()
    db.session.delete(order)
    db.session.commit()

    return jsonify({'success': True, 'message': 'تم حذف الطلب بنجاح'})


# ========================================
# ===== STADIUMS MANAGEMENT =====
# ========================================

@admin_bp.route('/stadiums')
@login_required
def manage_stadiums():
    """View and manage stadiums"""
    stadiums = Stadium.query.all()
    return render_template('admin/stadiums.html', stadiums=stadiums)


@admin_bp.route('/api/stadium', methods=['POST'])
@login_required
def add_stadium():
    """Add new stadium"""
    data = request.json

    if Stadium.query.filter_by(name=data.get('name')).first():
        return jsonify({'success': False, 'message': 'اسم الملعب موجود مسبقاً'}), 409

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

    return jsonify({
        'success': True,
        'message': 'تم إضافة الملعب بنجاح',
        'stadium': stadium.to_dict()
    }), 201


@admin_bp.route('/api/stadium/<int:stadium_id>', methods=['PUT'])
@login_required
def update_stadium(stadium_id):
    """Update stadium details"""
    stadium = Stadium.query.get(stadium_id)
    if not stadium:
        return jsonify({'success': False, 'message': 'الملعب غير موجود'}), 404

    data = request.json

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

    return jsonify({
        'success': True,
        'message': 'تم تحديث الملعب بنجاح',
        'stadium': stadium.to_dict()
    })


@admin_bp.route('/api/stadium/<int:stadium_id>', methods=['DELETE'])
@login_required
def delete_stadium(stadium_id):
    """Delete stadium"""
    stadium = Stadium.query.get(stadium_id)
    if not stadium:
        return jsonify({'success': False, 'message': 'الملعب غير موجود'}), 404

    if stadium.bookings:
        return jsonify({'success': False, 'message': 'لا يمكن حذف ملعب لديه حجوزات'}), 409

    db.session.delete(stadium)
    db.session.commit()

    return jsonify({'success': True, 'message': 'تم حذف الملعب بنجاح'})


# ========================================
# ===== SETTINGS =====
# ========================================

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def manage_settings():
    """View and manage settings"""
    if request.method == 'POST':
        settings = Settings.query.first()
        if not settings:
            settings = Settings()
            db.session.add(settings)

        if request.is_json:
            data = request.json
        else:
            data = request.form

        if 'opening_hour' in data:
            settings.opening_hour = int(data['opening_hour'])
        if 'closing_hour' in data:
            settings.closing_hour = int(data['closing_hour'])
        if 'price_per_hour' in data:
            settings.price_per_hour = float(data['price_per_hour'])
        if 'discount_percentage' in data:
            settings.discount_percentage = int(data['discount_percentage'])
        if 'discount_start_hour' in data:
            settings.discount_start_hour = int(data['discount_start_hour'])
        if 'discount_end_hour' in data:
            settings.discount_end_hour = int(data['discount_end_hour'])
        if 'phone' in data:
            settings.phone = data['phone']
        if 'email' in data:
            settings.email = data['email']
        if 'address' in data:
            settings.address = data['address']

        db.session.commit()

        if request.is_json:
            return jsonify({
                'success': True,
                'message': 'تم تحديث الإعدادات بنجاح',
                'settings': settings.to_dict()
            })
        else:
            return redirect(url_for('admin.manage_settings'))

    settings = Settings.query.first()
    return render_template('admin/settings.html', settings=settings)


# ========================================
# ===== REPORTS =====
# ========================================

@admin_bp.route('/reports')
@login_required
def reports():
    """View reports and analytics"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Booking reports
    booking_query = Booking.query.filter(Booking.status.in_(['confirmed', 'completed']))

    # Order reports
    order_query = Order.query.filter(Order.status.in_(['confirmed', 'delivered']))

    if start_date:
        start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
        booking_query = booking_query.filter(Booking.date >= start_date_obj)
        order_query = order_query.filter(db.func.date(Order.created_at) >= start_date_obj)

    if end_date:
        end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
        booking_query = booking_query.filter(Booking.date <= end_date_obj)
        order_query = order_query.filter(db.func.date(Order.created_at) <= end_date_obj)

    bookings = booking_query.all()
    orders = order_query.all()

    # Booking statistics
    booking_revenue = sum(b.final_price for b in bookings)
    total_discount = sum(b.discount_amount for b in bookings)

    # Order statistics
    order_revenue = sum(o.total_price for o in orders)

    # Total revenue
    total_revenue = booking_revenue + order_revenue

    # Stadium stats
    stadium_stats = {}
    for booking in bookings:
        if booking.stadium.name not in stadium_stats:
            stadium_stats[booking.stadium.name] = {'count': 0, 'revenue': 0}
        stadium_stats[booking.stadium.name]['count'] += 1
        stadium_stats[booking.stadium.name]['revenue'] += booking.final_price

    return render_template('admin/reports.html',
                           bookings=bookings,
                           orders=orders,
                           booking_revenue=booking_revenue,
                           order_revenue=order_revenue,
                           total_revenue=total_revenue,
                           total_discount=total_discount,
                           stadium_stats=stadium_stats,
                           start_date=start_date,
                           end_date=end_date
                           )


# ========================================
# ===== USER MANAGEMENT (Super Admin Only) =====
# ========================================

@admin_bp.route('/users')
@login_required
def manage_users():
    """View and manage users - Super Admin only"""
    if current_user.role != 'super_admin':
        return redirect(url_for('admin.dashboard'))

    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)


@admin_bp.route('/api/user', methods=['POST'])
@login_required
def add_user():
    """Add new admin user - Super Admin only"""
    if current_user.role != 'super_admin':
        return jsonify({'success': False, 'message': 'غير مصرح لك بهذا الإجراء'}), 403

    data = request.json

    # Validate
    if not data.get('username') or not data.get('email') or not data.get('password'):
        return jsonify({'success': False, 'message': 'جميع الحقول مطلوبة'}), 400

    # Check if exists
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'success': False, 'message': 'اسم المستخدم موجود مسبقاً'}), 409

    if User.query.filter_by(email=data['email']).first():
        return jsonify({'success': False, 'message': 'البريد الإلكتروني موجود مسبقاً'}), 409

    try:
        user = User(
            username=data['username'],
            email=data['email'],
            role='admin',
            is_active=True,
            can_manage_bookings=data.get('can_manage_bookings', True),
            can_manage_products=data.get('can_manage_products', True),
            can_manage_orders=data.get('can_manage_orders', True),
            can_manage_stadiums=data.get('can_manage_stadiums', False),
            can_manage_settings=data.get('can_manage_settings', False),
            can_view_reports=data.get('can_view_reports', False)
        )
        user.set_password(data['password'])

        db.session.add(user)
        db.session.commit()

        return jsonify({'success': True, 'message': 'تم إنشاء المشرف بنجاح'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/user/<int:user_id>', methods=['PUT'])
@login_required
def update_user(user_id):
    """Update admin user - Super Admin only"""
    if current_user.role != 'super_admin':
        return jsonify({'success': False, 'message': 'غير مصرح لك بهذا الإجراء'}), 403

    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'المستخدم غير موجود'}), 404

    if user.role == 'super_admin':
        return jsonify({'success': False, 'message': 'لا يمكن تعديل Super Admin'}), 403

    data = request.json

    try:
        if data.get('email'):
            user.email = data['email']
        if data.get('password'):
            user.set_password(data['password'])

        user.is_active = data.get('is_active', user.is_active)
        user.can_manage_bookings = data.get('can_manage_bookings', user.can_manage_bookings)
        user.can_manage_products = data.get('can_manage_products', user.can_manage_products)
        user.can_manage_orders = data.get('can_manage_orders', user.can_manage_orders)
        user.can_manage_stadiums = data.get('can_manage_stadiums', user.can_manage_stadiums)
        user.can_manage_settings = data.get('can_manage_settings', user.can_manage_settings)
        user.can_view_reports = data.get('can_view_reports', user.can_view_reports)

        db.session.commit()

        return jsonify({'success': True, 'message': 'تم تحديث المشرف بنجاح'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/user/<int:user_id>/toggle', methods=['POST'])
@login_required
def toggle_user(user_id):
    """Toggle user active status - Super Admin only"""
    if current_user.role != 'super_admin':
        return jsonify({'success': False, 'message': 'غير مصرح لك بهذا الإجراء'}), 403

    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'المستخدم غير موجود'}), 404

    if user.role == 'super_admin':
        return jsonify({'success': False, 'message': 'لا يمكن تعطيل Super Admin'}), 403

    user.is_active = not user.is_active
    db.session.commit()

    status = 'نشط' if user.is_active else 'معطل'
    return jsonify({'success': True, 'message': f'تم تحديث الحالة: {status}'})


@admin_bp.route('/api/user/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    """Delete admin user - Super Admin only"""
    if current_user.role != 'super_admin':
        return jsonify({'success': False, 'message': 'غير مصرح لك بهذا الإجراء'}), 403

    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'المستخدم غير موجود'}), 404

    if user.role == 'super_admin':
        return jsonify({'success': False, 'message': 'لا يمكن حذف Super Admin'}), 403

    if user.id == current_user.id:
        return jsonify({'success': False, 'message': 'لا يمكنك حذف حسابك'}), 403

    try:
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم حذف المشرف بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500