from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, make_response
from flask_login import login_required
from app import db

from app.models.product import Product
from app.models.category import Category
from app.models.stadium import Stadium
from app.models.table import Table
from app.models.settings import Settings
from app.models.pos_session import POSSession
from app.models.pos_order import POSOrder, POSOrderItem
from app.models.manual_debt import ManualDebt

from datetime import datetime, timedelta
import math
import csv
from io import StringIO

# ✅ Define the blueprint FIRST
pos_bp = Blueprint('pos', __name__, url_prefix='/pos')


# ---------- Helper: حساب وقت اللعب والسعر تلقائياً ----------
def compute_play_time_and_price(session: POSSession, settings: Settings):
    """
    ✅ Stadium billing rules:
    - Minimum 1 hour
    - Round up (ceil)
    - Price is PER HOUR (uses stadium.price_per_hour if exists else settings.price_per_hour else 40000)

    ✅ NEW:
    - If session.end_time exists while status is still 'active', we treat it as "play finished"
      and freeze the calculation on end_time instead of now.
    Returns ONLY: (minutes, play_price)
    """
    if session.session_type != 'stadium':
        return 0, 0

    if not session.start_time:
        session.start_time = datetime.now()

    # ✅ If play already finished (we set end_time via finish-play button), use it
    end_point = None
    if session.status == 'active' and session.end_time:
        end_point = session.end_time
    else:
        end_point = datetime.now()

    minutes = int((end_point - session.start_time).total_seconds() // 60)
    minutes = max(0, minutes)

    # ✅ billable hours: min 1, round up
    billable_hours = max(1, int(math.ceil(minutes / 60.0)))

    # ✅ price per hour: stadium overrides settings
    price_per_hour = 0.0
    try:
        if session.stadium_id:
            st = Stadium.query.get(session.stadium_id)
            if st and st.price_per_hour:
                price_per_hour = float(st.price_per_hour)
    except Exception:
        pass

    if not price_per_hour:
        price_per_hour = float(getattr(settings, "price_per_hour", 0) or 0)

    if not price_per_hour:
        price_per_hour = 40000.0

    play_price = int(round(billable_hours * price_per_hour, 0))
    return minutes, play_price


# ==================== HOME ====================
@pos_bp.route('/')
@login_required
def index():
    stadiums = Stadium.query.filter_by(is_active=True).order_by(Stadium.id.asc()).limit(2).all()
    tables = Table.query.filter_by(is_active=True).order_by(Table.id.asc()).limit(10).all()

    settings = Settings.query.first()
    active_sessions = POSSession.query.filter_by(status='active').all()

    stadium_sessions = {s.stadium_id: s for s in active_sessions if s.session_type == 'stadium' and s.stadium_id}
    table_sessions = {s.table_id: s for s in active_sessions if s.session_type == 'table' and s.table_id}

    stadium_live = {}
    for st_id, sess in stadium_sessions.items():
        minutes, price = compute_play_time_and_price(sess, settings)
        stadium_live[st_id] = {
            "minutes": minutes,
            "price": price,
            "start_time": sess.start_time,
            "end_time": sess.end_time,  # ✅ so you can show "finished" on home if needed
        }

    return render_template(
        'pos/index.html',
        stadiums=stadiums,
        tables=tables,
        stadium_sessions=stadium_sessions,
        table_sessions=table_sessions,
        stadium_live=stadium_live,
        settings=settings
    )


# ==================== START SESSION ====================
@pos_bp.route('/start-session', methods=['POST'])
@login_required
def start_session():
    session_type = (request.form.get('session_type') or '').strip()
    location_id = request.form.get('location_id')
    customer_name = (request.form.get('customer_name') or '').strip()
    customer_phone = (request.form.get('customer_phone') or '').strip()

    if not location_id:
        flash('الرجاء اختيار موقع!', 'error')
        return redirect(url_for('pos.index'))

    try:
        location_id_int = int(location_id)
    except Exception:
        flash('المعرف غير صحيح!', 'error')
        return redirect(url_for('pos.index'))

    if session_type == 'stadium':
        existing = POSSession.query.filter_by(
            session_type='stadium',
            stadium_id=location_id_int,
            status='active'
        ).first()
        if existing:
            return redirect(url_for('pos.session_detail', session_id=existing.id))

        session = POSSession(
            session_type='stadium',
            stadium_id=location_id_int,
            customer_name=customer_name,
            customer_phone=customer_phone,
            start_time=datetime.now(),
            status='active'
        )

    elif session_type == 'table':
        existing = POSSession.query.filter_by(
            session_type='table',
            table_id=location_id_int,
            status='active'
        ).first()
        if existing:
            return redirect(url_for('pos.session_detail', session_id=existing.id))

        session = POSSession(
            session_type='table',
            table_id=location_id_int,
            customer_name=customer_name,
            customer_phone=customer_phone,
            start_time=datetime.now(),
            status='active'
        )
    else:
        flash('نوع جلسة غير صحيح!', 'error')
        return redirect(url_for('pos.index'))

    db.session.add(session)
    db.session.commit()

    flash('تم بدء الجلسة بنجاح ✅', 'success')
    return redirect(url_for('pos.session_detail', session_id=session.id))


# ==================== SESSION DETAILS ====================
@pos_bp.route('/session/<int:session_id>')
@login_required
def session_detail(session_id):
    session = POSSession.query.get_or_404(session_id)
    products = Product.query.filter_by(is_active=True, show_in_pos=True).all()
    categories = Category.query.all()
    settings = Settings.query.first()

    stadium_price = None
    if session.session_type == 'stadium' and session.stadium_id:
        st = Stadium.query.get(session.stadium_id)
        stadium_price = float(st.price_per_hour or 0) if st else 0

    # ✅ compute to show in page
    play_minutes, play_price = compute_play_time_and_price(session, settings)

    return render_template(
        'pos/session.html',
        session=session,
        products=products,
        categories=categories,
        settings=settings,
        stadium_price_per_hour=stadium_price,
        play_minutes=play_minutes,
        play_price=play_price
    )


# ==================== ✅ FINISH PLAY (NEW BUTTON) ====================
@pos_bp.route('/session/<int:session_id>/finish-play', methods=['POST'])
@login_required
def finish_play(session_id):
    """
    ✅ NEW:
    Stops the stadium timer WITHOUT closing payment.
    - Sets session.end_time (while status stays 'active')
    - Calculates and stores play_time_minutes + play_time_price (if fields exist)
    """
    session = POSSession.query.get_or_404(session_id)
    settings = Settings.query.first()

    if session.status != 'active':
        flash('الجلسة ليست فعّالة', 'warning')
        return redirect(url_for('pos.session_detail', session_id=session.id))

    if session.session_type != 'stadium':
        flash('إنهاء اللعب متاح فقط للملاعب', 'warning')
        return redirect(url_for('pos.session_detail', session_id=session.id))

    # ✅ if already finished, do nothing
    if session.end_time:
        flash('تم إنهاء اللعب مسبقاً ✅', 'info')
        return redirect(url_for('pos.session_detail', session_id=session.id))

    session.end_time = datetime.now()

    minutes, price = compute_play_time_and_price(session, settings)

    # store if your model has these columns
    if hasattr(session, "play_time_minutes"):
        session.play_time_minutes = minutes
    if hasattr(session, "play_time_price"):
        session.play_time_price = price

    # ✅ recalc totals
    session.calculate_total()
    db.session.commit()

    flash('تم إنهاء وقت اللعب ✅ (يمكنك الآن إضافة منتجات ثم إنهاء الدفع)', 'success')
    return redirect(url_for('pos.session_detail', session_id=session.id))


# ==================== ADD ITEM ====================
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

    current_order = POSOrder.query.filter_by(session_id=session_id, status='pending').first()
    if not current_order:
        current_order = POSOrder(session_id=session_id, status='pending')
        db.session.add(current_order)
        db.session.flush()

    existing_item = POSOrderItem.query.filter_by(order_id=current_order.id, product_id=product.id).first()
    if existing_item:
        existing_item.quantity += quantity
    else:
        db.session.add(POSOrderItem(
            order_id=current_order.id,
            product_id=product.id,
            quantity=quantity,
            price=product.price
        ))

    current_order.calculate_total()
    session.calculate_total()
    db.session.commit()

    return jsonify({'success': True, 'message': 'تم إضافة المنتج ✅'})


# ==================== REMOVE ITEM ====================
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

    return jsonify({'success': True})


# ==================== UPDATE QUANTITY ====================
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

    return jsonify({'success': True})


# ==================== CLOSE SESSION ====================
@pos_bp.route('/session/<int:session_id>/close', methods=['POST'])
@login_required
def close_session(session_id):
    session = POSSession.query.get_or_404(session_id)
    settings = Settings.query.first()

    payment_method = request.form.get('payment_method', 'cash')
    manual_discount = float(request.form.get('manual_discount', 0) or 0)
    discount_note = (request.form.get('discount_note') or '').strip()

    session.payment_method = payment_method
    session.manual_discount = manual_discount
    session.discount_note = discount_note

    # ✅ If play already finished using the button, do NOT override end_time/play_time
    # Otherwise, set end_time now and compute normally.
    if session.session_type == 'stadium':
        already_has_fixed_play = bool(getattr(session, "play_time_price", 0) or 0) and bool(session.end_time)

        if not already_has_fixed_play:
            session.end_time = datetime.now()
            play_minutes, play_price = compute_play_time_and_price(session, settings)
            if hasattr(session, "play_time_minutes"):
                session.play_time_minutes = play_minutes
            if hasattr(session, "play_time_price"):
                session.play_time_price = play_price
        else:
            # still ensure end_time exists
            if not session.end_time:
                session.end_time = datetime.now()

    else:
        session.end_time = datetime.now()

    # ✅ time-discount only (percentage + time window based on start hour)
    discount_percentage = int(getattr(settings, "discount_percentage", 0) or 0)
    discount_start = int(getattr(settings, "discount_start_hour", 12) or 12)
    discount_end = int(getattr(settings, "discount_end_hour", 16) or 16)

    auto_discount = 0
    try:
        play_price_for_discount = int(getattr(session, "play_time_price", 0) or 0)
        start_hour = session.start_time.hour if session.start_time else datetime.now().hour
        in_window = (start_hour >= discount_start and start_hour < discount_end)
        if in_window and discount_percentage > 0 and play_price_for_discount > 0:
            auto_discount = int(round(play_price_for_discount * (discount_percentage / 100.0), 0))
    except Exception:
        auto_discount = 0

    if hasattr(session, "auto_discount"):
        session.auto_discount = auto_discount

    session.status = 'paid'
    for order in session.orders:
        order.status = 'delivered'

    session.calculate_total()
    db.session.commit()

    flash('تم إغلاق الجلسة بنجاح ✅', 'success')
    return redirect(url_for('pos.receipt', session_id=session.id))


# ==================== ✅ FINISH SESSION AS DEBT ====================
@pos_bp.route('/session/<int:session_id>/finish-as-debt', methods=['POST'])
@login_required
def finish_session_as_debt(session_id):
    """
    ✅ Convert active session to manual debt instead of payment
    """
    session = POSSession.query.get_or_404(session_id)
    settings = Settings.query.first()

    if session.status != 'active':
        flash('الجلسة ليست نشطة!', 'warning')
        return redirect(url_for('pos.session_detail', session_id=session.id))

    # Get debt info from form
    name = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip() or None
    note = (request.form.get('note') or '').strip() or None

    if not name:
        flash('الاسم مطلوب!', 'danger')
        return redirect(url_for('pos.session_detail', session_id=session.id))

    try:
        # ✅ Calculate final totals
        if session.session_type == 'stadium':
            if not session.end_time:
                session.end_time = datetime.now()

            play_minutes, play_price = compute_play_time_and_price(session, settings)

            if hasattr(session, "play_time_minutes"):
                session.play_time_minutes = play_minutes
            if hasattr(session, "play_time_price"):
                session.play_time_price = play_price
        else:
            session.end_time = datetime.now()

        # Calculate total amount
        session.calculate_total()
        total_amount = int(session.total_amount or 0)

        if total_amount <= 0:
            flash('لا يمكن تسجيل دين بمبلغ صفر!', 'warning')
            return redirect(url_for('pos.session_detail', session_id=session.id))

        # Build debt note with session details
        debt_note_parts = []
        if note:
            debt_note_parts.append(note)

        # Add session info
        location_name = session.get_location_name()
        debt_note_parts.append(f"جلسة POS #{session.id} ({location_name})")

        # Add items if any
        items_list = []
        for order in session.orders:
            for item in order.items:
                try:
                    pname = item.product.name_ku or item.product.name_ar or "منتج"
                    items_list.append(f"{pname} x{item.quantity}")
                except Exception:
                    pass

        if items_list:
            debt_note_parts.append(" | ".join(items_list))

        final_note = " | ".join(debt_note_parts)

        # ✅ Create manual debt
        debt = ManualDebt(
            name=name,
            phone=phone,
            amount=total_amount,
            paid_amount=0,
            note=final_note,
            date=datetime.now().date(),
            status="open"
        )
        db.session.add(debt)

        # ✅ Mark session as paid with debt method
        session.status = 'paid'
        session.payment_method = 'debt'

        # Mark orders as delivered
        for order in session.orders:
            order.status = 'delivered'

        db.session.commit()

        flash(f'تم تسجيل الدين بنجاح ✅ | المبلغ: {total_amount:,} IQD', 'success')
        return redirect(url_for('pos.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'خطأ في تسجيل الدين: {str(e)}', 'danger')
        return redirect(url_for('pos.session_detail', session_id=session.id))


# ==================== CANCEL SESSION ====================
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


# ==================== RECEIPT ====================
@pos_bp.route('/receipt/<int:session_id>')
@login_required
def receipt(session_id):
    session = POSSession.query.get_or_404(session_id)
    settings = Settings.query.first()

    all_items = []
    for order in session.orders:
        all_items.extend(order.items)

    return render_template('pos/receipt.html', session=session, items=all_items, settings=settings)


# ==================== QUICK SALE ====================
@pos_bp.route('/quick-sale')
@login_required
def quick_sale():
    products = Product.query.filter_by(is_active=True, show_in_pos=True).all()
    categories = Category.query.all()
    return render_template('pos/quick_sale.html', products=products, categories=categories)


@pos_bp.route('/quick-sale/checkout', methods=['POST'])
@login_required
def quick_checkout():
    payload = request.json or {}
    items = payload.get('items', [])
    payment_method = payload.get('payment_method', 'cash')

    if not items:
        return jsonify({'success': False, 'message': 'السلة فارغة!'})

    session = POSSession(
        session_type='takeaway',
        status='paid',
        payment_method=payment_method,
        start_time=datetime.now(),
        end_time=datetime.now()
    )
    db.session.add(session)
    db.session.flush()

    order = POSOrder(session_id=session.id, status='delivered')
    db.session.add(order)
    db.session.flush()

    for it in items:
        product = Product.query.get(it.get('product_id'))
        if product:
            db.session.add(POSOrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=int(it.get('quantity', 1)),
                price=product.price
            ))

    order.calculate_total()
    session.calculate_total()
    db.session.commit()

    return jsonify({'success': True, 'session_id': session.id, 'total': session.total_amount})


@pos_bp.route('/quick-sale/debt', methods=['POST'])
@login_required
def quick_sale_debt():
    payload = request.json or {}
    name = (payload.get('name') or '').strip()
    phone = (payload.get('phone') or '').strip() or None
    note = (payload.get('note') or '').strip() or None
    items = payload.get('items', [])

    if not name:
        return jsonify({'success': False, 'message': 'الاسم مطلوب'}), 400

    if not items:
        return jsonify({'success': False, 'message': 'السلة فارغة!'}), 400

    total = 0
    lines = []
    for it in items:
        pid = it.get('product_id')
        qty = int(it.get('quantity') or 1)
        qty = max(1, qty)

        product = Product.query.get(pid)
        if not product:
            continue

        price = int(product.price or 0)
        total += price * qty
        lines.append(f"{product.name_ku} x{qty}")

    if total <= 0:
        return jsonify({'success': False, 'message': 'لا يمكن تسجيل دين بمبلغ 0'}), 400

    items_text = " | ".join(lines)
    final_note = note
    if items_text:
        final_note = (final_note + " | " if final_note else "") + items_text

    d = ManualDebt(
        name=name,
        phone=phone,
        amount=total,
        paid_amount=0,
        note=final_note,
        date=datetime.now().date(),
        status="open"
    )

    db.session.add(d)
    db.session.commit()

    return jsonify({'success': True, 'debt_id': d.id, 'total': total})


# ==================== BARCODE SCAN ====================
@pos_bp.route('/scan-barcode', methods=['POST'])
@login_required
def scan_barcode():
    barcode = None
    if request.is_json:
        barcode = (request.json.get('barcode') or '').strip()
    else:
        barcode = (request.form.get('barcode') or '').strip()

    print(f"🔍 BARCODE SCAN: Received '{barcode}'")

    if not barcode:
        return jsonify({'success': False, 'message': 'الباركود فارغ! / Empty barcode'})

    product = Product.query.filter_by(barcode=barcode).first()

    if not product:
        try:
            product_id = int(barcode)
            product = Product.query.get(product_id)
        except (ValueError, TypeError):
            product = None

    if not product:
        return jsonify({'success': False, 'message': f'المنتج غير موجود! الباركود: {barcode}'})

    return jsonify({
        'success': True,
        'product': {
            'id': product.id,
            'name_ku': product.name_ku,
            'price': float(product.price or 0),
            'image': product.image or ''
        }
    })


# ==================== EXPORT TO EXCEL ====================
@pos_bp.route('/api/export-excel')
@login_required
def export_excel():
    period = request.args.get('period', 'today')
    today = datetime.now().date()

    if period == 'today':
        start_date = datetime.combine(today, datetime.min.time())
    elif period == 'week':
        start_date = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
    elif period == 'month':
        start_date = datetime.combine(today.replace(day=1), datetime.min.time())
    else:
        start_date = datetime.combine(today, datetime.min.time())

    sessions = POSSession.query.filter(
        POSSession.created_at >= start_date,
        POSSession.status == 'paid'
    ).all()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Type', 'Customer', 'Amount', 'Payment', 'Discount', 'Time'])

    for s in sessions:
        writer.writerow([
            s.id,
            s.session_type,
            s.customer_name or 'زائر',
            s.total_amount or 0,
            s.payment_method or 'cash',
            (getattr(s, "auto_discount", 0) or 0) + (getattr(s, "manual_discount", 0) or 0),
            s.created_at.strftime('%Y-%m-%d %H:%M')
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=padel_reports_{period}_{today}.csv'
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    return response