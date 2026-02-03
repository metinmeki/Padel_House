from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models.product import Product
from app.models.category import Category
from app.models.stadium import Stadium
from app.models.table import Table
from app.models.settings import Settings
from app.models.pos_session import POSSession
from app.models.pos_order import POSOrder, POSOrderItem
from datetime import datetime

pos_bp = Blueprint('pos', __name__)


# ==================== الشاشة الرئيسية ====================
@pos_bp.route('/')
@login_required
def index():
    stadiums = Stadium.query.filter_by(is_active=True).all()
    tables = Table.query.filter_by(is_active=True).all()

    active_sessions = POSSession.query.filter_by(status='active').all()

    stadium_sessions = {s.stadium_id: s for s in active_sessions if s.session_type == 'stadium'}
    table_sessions = {s.table_id: s for s in active_sessions if s.session_type == 'table'}

    return render_template('pos/index.html',
                           stadiums=stadiums,
                           tables=tables,
                           stadium_sessions=stadium_sessions,
                           table_sessions=table_sessions)


# ==================== بدء جلسة جديدة ====================
@pos_bp.route('/start-session', methods=['POST'])
@login_required
def start_session():
    session_type = request.form.get('session_type')
    location_id = request.form.get('location_id')
    customer_name = request.form.get('customer_name', '')
    customer_phone = request.form.get('customer_phone', '')

    if session_type == 'stadium':
        existing = POSSession.query.filter_by(
            session_type='stadium',
            stadium_id=location_id,
            status='active'
        ).first()
        if existing:
            flash('يوجد جلسة نشطة لهذا الملعب!', 'error')
            return redirect(url_for('pos.index'))

        session = POSSession(
            session_type='stadium',
            stadium_id=location_id,
            customer_name=customer_name,
            customer_phone=customer_phone
        )
    elif session_type == 'table':
        existing = POSSession.query.filter_by(
            session_type='table',
            table_id=location_id,
            status='active'
        ).first()
        if existing:
            flash('يوجد جلسة نشطة لهذه الطاولة!', 'error')
            return redirect(url_for('pos.index'))

        session = POSSession(
            session_type='table',
            table_id=location_id,
            customer_name=customer_name,
            customer_phone=customer_phone
        )
    else:
        flash('نوع جلسة غير صحيح!', 'error')
        return redirect(url_for('pos.index'))

    db.session.add(session)
    db.session.commit()

    flash('تم بدء الجلسة بنجاح!', 'success')
    return redirect(url_for('pos.session_detail', session_id=session.id))


# ==================== تفاصيل الجلسة ====================
@pos_bp.route('/session/<int:session_id>')
@login_required
def session_detail(session_id):
    session = POSSession.query.get_or_404(session_id)
    # ✅ فقط المنتجات اللي show_in_pos=True
    products = Product.query.filter_by(is_active=True, show_in_pos=True).all()
    categories = Category.query.all()
    settings = Settings.query.first()

    return render_template('pos/session.html',
                           session=session,
                           products=products,
                           categories=categories,
                           settings=settings)


# ==================== إضافة منتج للجلسة ====================
@pos_bp.route('/session/<int:session_id>/add-item', methods=['POST'])
@login_required
def add_item(session_id):
    session = POSSession.query.get_or_404(session_id)

    if session.status != 'active':
        return jsonify({'success': False, 'message': 'الجلسة مغلقة!'})

    product_id = request.form.get('product_id')
    quantity = int(request.form.get('quantity', 1))

    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'المنتج غير موجود!'})

    current_order = POSOrder.query.filter_by(
        session_id=session_id,
        status='pending'
    ).first()

    if not current_order:
        current_order = POSOrder(session_id=session_id)
        db.session.add(current_order)
        db.session.flush()

    existing_item = POSOrderItem.query.filter_by(
        order_id=current_order.id,
        product_id=product_id
    ).first()

    if existing_item:
        existing_item.quantity += quantity
    else:
        item = POSOrderItem(
            order_id=current_order.id,
            product_id=product_id,
            quantity=quantity,
            price=product.price
        )
        db.session.add(item)

    current_order.calculate_total()
    session.calculate_total()

    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'تم إضافة المنتج!',
        'order_total': current_order.total_price,
        'session_total': session.total_amount
    })


# ==================== حذف منتج من الجلسة ====================
@pos_bp.route('/session/<int:session_id>/remove-item/<int:item_id>', methods=['POST'])
@login_required
def remove_item(session_id, item_id):
    session = POSSession.query.get_or_404(session_id)
    item = POSOrderItem.query.get_or_404(item_id)

    order = item.order
    db.session.delete(item)

    order.calculate_total()
    session.calculate_total()

    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'تم حذف المنتج!',
        'session_total': session.total_amount
    })


# ==================== تحديث كمية منتج ====================
@pos_bp.route('/session/<int:session_id>/update-quantity', methods=['POST'])
@login_required
def update_quantity(session_id):
    session = POSSession.query.get_or_404(session_id)

    item_id = request.form.get('item_id')
    quantity = int(request.form.get('quantity', 1))

    item = POSOrderItem.query.get_or_404(item_id)

    if quantity <= 0:
        db.session.delete(item)
    else:
        item.quantity = quantity

    item.order.calculate_total()
    session.calculate_total()

    db.session.commit()

    return jsonify({
        'success': True,
        'session_total': session.total_amount
    })


# ==================== إغلاق الجلسة والدفع ====================
@pos_bp.route('/session/<int:session_id>/close', methods=['POST'])
@login_required
def close_session(session_id):
    session = POSSession.query.get_or_404(session_id)

    payment_method = request.form.get('payment_method', 'cash')
    play_time_minutes = int(request.form.get('play_time_minutes', 0))
    play_time_price = float(request.form.get('play_time_price', 0))
    auto_discount = float(request.form.get('auto_discount', 0))
    manual_discount = float(request.form.get('manual_discount', 0))
    discount_note = request.form.get('discount_note', '')

    session.status = 'paid'
    session.end_time = datetime.now()
    session.payment_method = payment_method
    session.play_time_minutes = play_time_minutes
    session.play_time_price = play_time_price
    session.auto_discount = auto_discount
    session.manual_discount = manual_discount
    session.discount_note = discount_note

    session.calculate_total()

    for order in session.orders:
        order.status = 'delivered'

    db.session.commit()

    flash('تم إغلاق الجلسة بنجاح!', 'success')
    return redirect(url_for('pos.receipt', session_id=session.id))


# ==================== إلغاء الجلسة ====================
@pos_bp.route('/session/<int:session_id>/cancel', methods=['POST'])
@login_required
def cancel_session(session_id):
    session = POSSession.query.get_or_404(session_id)

    for order in session.orders:
        db.session.delete(order)

    db.session.delete(session)
    db.session.commit()

    flash('تم إلغاء الجلسة!', 'info')
    return redirect(url_for('pos.index'))


# ==================== الفاتورة ====================
@pos_bp.route('/receipt/<int:session_id>')
@login_required
def receipt(session_id):
    session = POSSession.query.get_or_404(session_id)
    settings = Settings.query.first()

    all_items = []
    for order in session.orders:
        for item in order.items:
            all_items.append(item)

    return render_template('pos/receipt.html',
                           session=session,
                           items=all_items,
                           settings=settings)


# ==================== بيع سريع ====================
@pos_bp.route('/quick-sale')
@login_required
def quick_sale():
    # ✅ فقط المنتجات اللي show_in_pos=True
    products = Product.query.filter_by(is_active=True, show_in_pos=True).all()
    categories = Category.query.all()

    return render_template('pos/quick_sale.html',
                           products=products,
                           categories=categories)


@pos_bp.route('/quick-sale/checkout', methods=['POST'])
@login_required
def quick_checkout():
    items = request.json.get('items', [])
    payment_method = request.json.get('payment_method', 'cash')

    if not items:
        return jsonify({'success': False, 'message': 'السلة فارغة!'})

    session = POSSession(
        session_type='takeaway',
        status='paid',
        payment_method=payment_method,
        end_time=datetime.now()
    )
    db.session.add(session)
    db.session.flush()

    order = POSOrder(session_id=session.id, status='delivered')
    db.session.add(order)
    db.session.flush()

    for item_data in items:
        product = Product.query.get(item_data['product_id'])
        if product:
            item = POSOrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=item_data['quantity'],
                price=product.price
            )
            db.session.add(item)

    order.calculate_total()
    session.calculate_total()

    db.session.commit()

    return jsonify({
        'success': True,
        'session_id': session.id,
        'total': session.total_amount
    })


# ==================== البحث بالباركود ====================
@pos_bp.route('/scan-barcode', methods=['POST'])
@login_required
def scan_barcode():
    barcode = request.form.get('barcode', '').strip()

    product = Product.query.filter_by(barcode=barcode, is_active=True, show_in_pos=True).first()

    if product:
        return jsonify({
            'success': True,
            'product': product.to_dict()
        })
    else:
        return jsonify({
            'success': False,
            'message': 'المنتج غير موجود!'
        })


# ==================== تقرير المبيعات ====================
@pos_bp.route('/reports')
@login_required
def reports():
    from sqlalchemy import func

    today = datetime.now().date()
    today_sales = db.session.query(func.sum(POSSession.total_amount)).filter(
        func.date(POSSession.created_at) == today,
        POSSession.status == 'paid'
    ).scalar() or 0

    today_sessions = POSSession.query.filter(
        func.date(POSSession.created_at) == today,
        POSSession.status == 'paid'
    ).count()

    recent_sessions = POSSession.query.filter_by(status='paid').order_by(
        POSSession.created_at.desc()
    ).limit(10).all()

    return render_template('pos/reports.html',
                           today_sales=today_sales,
                           today_sessions=today_sessions,
                           recent_sessions=recent_sessions)