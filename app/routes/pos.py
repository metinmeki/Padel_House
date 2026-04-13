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

pos_bp = Blueprint('pos', __name__, url_prefix='/pos')


# ---------- Helper: حساب وقت اللعب والسعر تلقائياً ----------
def compute_play_time_and_price(session: POSSession, settings: Settings):
    """
    Stadium billing:
    - Minimum 1 hour
    - Round up (ceil)
    - Price per hour from stadium.price_per_hour else settings.price_per_hour else 40000
    - If end_time exists while status == 'active' => freeze calc on end_time
    """
    if session.session_type != 'stadium':
        return 0, 0

    if not session.start_time:
        session.start_time = datetime.now()

    if session.status == 'active' and session.end_time:
        end_point = session.end_time
    else:
        end_point = datetime.now()

    minutes = int((end_point - session.start_time).total_seconds() // 60)
    minutes = max(0, minutes)

    billable_hours = max(1, int(math.ceil(minutes / 60.0)))

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
    stadiums = Stadium.query.filter_by(is_active=True, show_in_pos=True).order_by(Stadium.id.asc()).all()
    tables = Table.query.filter_by(is_active=True).order_by(Table.id.asc()).all()

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
            "end_time": sess.end_time,
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
        existing = (POSSession.query
            .filter_by(session_type='stadium', stadium_id=location_id_int, status='active')
            .order_by(POSSession.id.desc())
            .first())

        if existing:
            if existing.end_time:
                flash('يوجد جلسة منتهية اللعب ولم يتم الدفع بعد. الرجاء إنهاء الدفع أو إلغاء الجلسة.', 'warning')
            else:
                flash('يوجد جلسة نشطة بالفعل لهذا الملعب.', 'info')
            return redirect(url_for('pos.session_detail', session_id=existing.id))

        session_obj = POSSession(
            session_type='stadium',
            stadium_id=location_id_int,
            customer_name=customer_name,
            customer_phone=customer_phone,
            start_time=datetime.now(),
            end_time=None,
            status='active'
        )

    elif session_type == 'table':
        existing = (POSSession.query
            .filter_by(session_type='table', table_id=location_id_int, status='active')
            .order_by(POSSession.id.desc())
            .first())

        if existing:
            if existing.end_time:
                flash('يوجد جلسة منتهية ولم يتم الدفع بعد. الرجاء إنهاء الدفع أو إلغاء الجلسة.', 'warning')
            else:
                flash('يوجد جلسة نشطة بالفعل لهذه الطاولة.', 'info')
            return redirect(url_for('pos.session_detail', session_id=existing.id))

        session_obj = POSSession(
            session_type='table',
            table_id=location_id_int,
            customer_name=customer_name,
            customer_phone=customer_phone,
            start_time=datetime.now(),
            end_time=None,
            status='active'
        )
    else:
        flash('نوع جلسة غير صحيح!', 'error')
        return redirect(url_for('pos.index'))

    db.session.add(session_obj)
    db.session.commit()

    flash('تم بدء الجلسة بنجاح ✅', 'success')
    return redirect(url_for('pos.session_detail', session_id=session_obj.id))


# ==================== SESSION DETAILS ====================
@pos_bp.route('/session/<int:session_id>')
@login_required
def session_detail(session_id):
    session_obj = POSSession.query.get_or_404(session_id)
    products = Product.query.filter_by(is_active=True, show_in_pos=True).all()
    categories = Category.query.all()
    settings = Settings.query.first()

    stadium_price = None
    if session_obj.session_type == 'stadium' and session_obj.stadium_id:
        st = Stadium.query.get(session_obj.stadium_id)
        stadium_price = float(st.price_per_hour or 0) if st else 0

    play_minutes, play_price = compute_play_time_and_price(session_obj, settings)

    return render_template(
        'pos/session.html',
        session=session_obj,
        products=products,
        categories=categories,
        settings=settings,
        stadium_price_per_hour=stadium_price,
        play_minutes=play_minutes,
        play_price=play_price
    )


# ==================== FINISH PLAY ====================
@pos_bp.route('/session/<int:session_id>/finish-play', methods=['POST'])
@login_required
def finish_play(session_id):
    session_obj = POSSession.query.get_or_404(session_id)
    settings = Settings.query.first()

    if session_obj.status != 'active':
        flash('الجلسة ليست فعّالة', 'warning')
        return redirect(url_for('pos.session_detail', session_id=session_obj.id))

    if session_obj.session_type != 'stadium':
        flash('إنهاء اللعب متاح فقط للملاعب', 'warning')
        return redirect(url_for('pos.session_detail', session_id=session_obj.id))

    if session_obj.end_time:
        flash('تم إنهاء اللعب مسبقاً ✅', 'info')
        return redirect(url_for('pos.session_detail', session_id=session_obj.id))

    session_obj.end_time = datetime.now()

    minutes, price = compute_play_time_and_price(session_obj, settings)

    if hasattr(session_obj, "play_time_minutes"):
        session_obj.play_time_minutes = minutes
    if hasattr(session_obj, "play_time_price"):
        session_obj.play_time_price = price

    session_obj.calculate_total()
    db.session.commit()

    flash('تم إنهاء وقت اللعب ✅ (يمكنك الآن إضافة منتجات ثم إنهاء الدفع)', 'success')
    return redirect(url_for('pos.session_detail', session_id=session_obj.id))


# ==================== ADD ITEM ====================
@pos_bp.route('/session/<int:session_id>/add-item', methods=['POST'])
@login_required
def add_item(session_id):
    session_obj = POSSession.query.get_or_404(session_id)
    if session_obj.status != 'active':
        return jsonify({'success': False, 'message': 'الجلسة مغلقة!'})

    product_id = request.form.get('product_id')
    quantity = int(request.form.get('quantity', 1) or 1)
    quantity = max(1, quantity)

    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'المنتج غير موجود!'})

    if product.stock is not None and product.stock < quantity:
        return jsonify({'success': False, 'message': f'المخزون غير كافي! المتبقي: {product.stock}'})

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

    if product.stock is not None:
        product.stock -= quantity

    current_order.calculate_total()
    session_obj.calculate_total()
    db.session.commit()

    return jsonify({'success': True, 'message': 'تم إضافة المنتج ✅'})


# ==================== REMOVE ITEM ====================
@pos_bp.route('/session/<int:session_id>/remove-item/<int:item_id>', methods=['POST'])
@login_required
def remove_item(session_id, item_id):
    session_obj = POSSession.query.get_or_404(session_id)
    if session_obj.status != 'active':
        return jsonify({'success': False, 'message': 'الجلسة مغلقة!'})

    item = POSOrderItem.query.get_or_404(item_id)
    product = item.product

    if product and product.stock is not None:
        product.stock += int(item.quantity or 0)

    order = item.order
    db.session.delete(item)

    order.calculate_total()
    session_obj.calculate_total()
    db.session.commit()

    return jsonify({'success': True})


# ==================== UPDATE QUANTITY ====================
@pos_bp.route('/session/<int:session_id>/update-quantity', methods=['POST'])
@login_required
def update_quantity(session_id):
    session_obj = POSSession.query.get_or_404(session_id)
    if session_obj.status != 'active':
        return jsonify({'success': False, 'message': 'الجلسة مغلقة!'})

    item_id = request.form.get('item_id')
    new_qty = int(request.form.get('quantity', 1) or 1)

    item = POSOrderItem.query.get_or_404(item_id)
    product = item.product

    old_qty = int(item.quantity or 0)

    if new_qty <= 0:
        if product and product.stock is not None:
            product.stock += old_qty
        db.session.delete(item)
    else:
        delta = new_qty - old_qty
        if delta > 0:
            if product and product.stock is not None and product.stock < delta:
                return jsonify({'success': False, 'message': f'المخزون غير كافي! المتبقي: {product.stock}'})
            if product and product.stock is not None:
                product.stock -= delta
        elif delta < 0:
            if product and product.stock is not None:
                product.stock += (-delta)

        item.quantity = new_qty

    item.order.calculate_total()
    session_obj.calculate_total()
    db.session.commit()

    return jsonify({'success': True})


# ==================== CLOSE SESSION ====================
@pos_bp.route('/session/<int:session_id>/close', methods=['POST'])
@login_required
def close_session(session_id):
    session_obj = POSSession.query.get_or_404(session_id)
    settings = Settings.query.first()

    payment_method  = request.form.get('payment_method', 'cash')
    manual_discount = float(request.form.get('manual_discount', 0) or 0)
    discount_note   = (request.form.get('discount_note') or '').strip()

    session_obj.payment_method  = payment_method
    session_obj.manual_discount = manual_discount
    session_obj.discount_note   = discount_note

    # time calc
    if session_obj.session_type == 'stadium':
        already_has_fixed_play = bool(getattr(session_obj, "play_time_price", 0) or 0) and bool(session_obj.end_time)
        if not already_has_fixed_play:
            session_obj.end_time = datetime.now()
            play_minutes, play_price = compute_play_time_and_price(session_obj, settings)
            if hasattr(session_obj, "play_time_minutes"):
                session_obj.play_time_minutes = play_minutes
            if hasattr(session_obj, "play_time_price"):
                session_obj.play_time_price = play_price
        else:
            if not session_obj.end_time:
                session_obj.end_time = datetime.now()
    else:
        session_obj.end_time = datetime.now()

    # auto discount (time window)
    discount_percentage = int(getattr(settings, "discount_percentage", 0) or 0)
    discount_start      = int(getattr(settings, "discount_start_hour", 12) or 12)
    discount_end        = int(getattr(settings, "discount_end_hour", 16) or 16)

    auto_discount = 0
    try:
        play_price_for_discount = int(getattr(session_obj, "play_time_price", 0) or 0)
        start_hour = session_obj.start_time.hour if session_obj.start_time else datetime.now().hour
        in_window  = (start_hour >= discount_start and start_hour < discount_end)
        if in_window and discount_percentage > 0 and play_price_for_discount > 0:
            auto_discount = int(round(play_price_for_discount * (discount_percentage / 100.0), 0))
    except Exception:
        auto_discount = 0

    if hasattr(session_obj, "auto_discount"):
        session_obj.auto_discount = auto_discount

    for order in session_obj.orders:
        order.status = 'delivered'

    session_obj.status = 'paid'
    session_obj.calculate_total()
    db.session.commit()

    flash('تم إغلاق الجلسة بنجاح ✅', 'success')
    return redirect(url_for('pos.receipt', session_id=session_obj.id))


# ==================== FINISH SESSION AS DEBT ====================
@pos_bp.route('/session/<int:session_id>/finish-as-debt', methods=['POST'])
@login_required
def finish_session_as_debt(session_id):
    session_obj = POSSession.query.get_or_404(session_id)
    settings    = Settings.query.first()

    if session_obj.status != 'active':
        flash('الجلسة ليست نشطة!', 'warning')
        return redirect(url_for('pos.session_detail', session_id=session_obj.id))

    name  = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip() or None
    note  = (request.form.get('note') or '').strip() or None

    if not name:
        flash('الاسم مطلوب!', 'danger')
        return redirect(url_for('pos.session_detail', session_id=session_obj.id))

    try:
        if session_obj.session_type == 'stadium':
            if not session_obj.end_time:
                session_obj.end_time = datetime.now()

            play_minutes, play_price = compute_play_time_and_price(session_obj, settings)
            if hasattr(session_obj, "play_time_minutes"):
                session_obj.play_time_minutes = play_minutes
            if hasattr(session_obj, "play_time_price"):
                session_obj.play_time_price = play_price
        else:
            session_obj.end_time = datetime.now()

        session_obj.calculate_total()
        total_amount = int(session_obj.total_amount or 0)

        if total_amount <= 0:
            flash('لا يمكن تسجيل دين بمبلغ صفر!', 'warning')
            return redirect(url_for('pos.session_detail', session_id=session_obj.id))

        debt_note_parts = []
        if note:
            debt_note_parts.append(note)

        location_name = session_obj.get_location_name()
        debt_note_parts.append(f"جلسة POS #{session_obj.id} ({location_name})")

        items_list = []
        for order in session_obj.orders:
            for item in order.items:
                try:
                    pname = item.product.name_ku or item.product.name_ar or "منتج"
                    items_list.append(f"{pname} x{item.quantity}")
                except Exception:
                    pass

        if items_list:
            debt_note_parts.append(" | ".join(items_list))

        final_note = " | ".join(debt_note_parts)

        for order in session_obj.orders:
            order.status = 'delivered'

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

        session_obj.status         = 'paid'
        session_obj.payment_method = 'debt'

        db.session.commit()

        flash(f'تم تسجيل الدين بنجاح ✅ | المبلغ: {total_amount:,} IQD', 'success')
        return redirect(url_for('pos.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'خطأ في تسجيل الدين: {str(e)}', 'danger')
        return redirect(url_for('pos.session_detail', session_id=session_obj.id))


# ==================== CANCEL SESSION ====================
@pos_bp.route('/session/<int:session_id>/cancel', methods=['POST'])
@login_required
def cancel_session(session_id):
    session_obj = POSSession.query.get_or_404(session_id)

    for order in session_obj.orders:
        for item in order.items:
            try:
                product = item.product
                if product and product.stock is not None:
                    product.stock += int(item.quantity or 0)
            except Exception:
                pass
        db.session.delete(order)

    db.session.delete(session_obj)
    db.session.commit()

    flash('تم إلغاء الجلسة!', 'info')
    return redirect(url_for('pos.index'))


# ==================== RECEIPT ====================
@pos_bp.route('/receipt/<int:session_id>')
@login_required
def receipt(session_id):
    session_obj = POSSession.query.get_or_404(session_id)
    settings    = Settings.query.first()

    all_items = []
    for order in session_obj.orders:
        all_items.extend(order.items)

    return render_template('pos/receipt.html', session=session_obj, items=all_items, settings=settings)


# ==================== QUICK SALE ====================
@pos_bp.route('/quick-sale')
@login_required
def quick_sale():
    products   = Product.query.filter_by(is_active=True, show_in_pos=True).all()
    categories = Category.query.all()
    return render_template('pos/quick_sale.html', products=products, categories=categories)


@pos_bp.route('/quick-sale/checkout', methods=['POST'])
@login_required
def quick_checkout():
    payload        = request.json or {}
    items          = payload.get('items', [])
    payment_method = payload.get('payment_method', 'cash')
    discount_type  = payload.get('discount_type', 'pct')
    discount_value = float(payload.get('discount_value', 0) or 0)

    if not items:
        return jsonify({'success': False, 'message': 'السلة فارغة!'})

    # ── stock check ──────────────────────────────────────────
    for it in items:
        product = Product.query.get(it.get('product_id'))
        if not product:
            continue
        qty = max(1, int(it.get('quantity', 1) or 1))
        if product.stock is not None and product.stock < qty:
            return jsonify({'success': False, 'message': f'المخزون غير كافي لـ {product.name_ku}! المتبقي: {product.stock}'}), 400

    # ── create session ────────────────────────────────────────
    session_obj = POSSession(
        session_type='takeaway',
        status='paid',
        payment_method=payment_method,
        start_time=datetime.now(),
        end_time=datetime.now()
    )
    db.session.add(session_obj)
    db.session.flush()

    order = POSOrder(session_id=session_obj.id, status='delivered')
    db.session.add(order)
    db.session.flush()

    subtotal = 0
    for it in items:
        product = Product.query.get(it.get('product_id'))
        if product:
            qty = max(1, int(it.get('quantity', 1) or 1))
            db.session.add(POSOrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=qty,
                price=product.price
            ))
            if product.stock is not None:
                product.stock -= qty
            subtotal += int(product.price or 0) * qty

    # ── discount calculation ──────────────────────────────────
    if discount_value > 0:
        if discount_type == 'pct':
            discount_amount = round(subtotal * discount_value / 100)
        else:
            discount_amount = round(discount_value)
        discount_amount = min(subtotal, int(discount_amount))
    else:
        discount_amount = 0

    # ── save discount fields ──────────────────────────────────
    if hasattr(session_obj, 'discount_type'):
        session_obj.discount_type = discount_type
    if hasattr(session_obj, 'discount_value'):
        session_obj.discount_value = discount_value
    if hasattr(session_obj, 'discount_amount'):
        session_obj.discount_amount = discount_amount
    # fallback: also store in manual_discount so receipt works before migration
    if hasattr(session_obj, 'manual_discount'):
        session_obj.manual_discount = discount_amount

    order.calculate_total()
    session_obj.calculate_total()

    # override with discounted total
    session_obj.total_amount = (session_obj.total_amount or subtotal) - discount_amount

    db.session.commit()

    return jsonify({'success': True, 'session_id': session_obj.id, 'total': session_obj.total_amount})


@pos_bp.route('/quick-sale/debt', methods=['POST'])
@login_required
def quick_sale_debt():
    payload        = request.json or {}
    name           = (payload.get('name') or '').strip()
    phone          = (payload.get('phone') or '').strip() or None
    note           = (payload.get('note') or '').strip() or None
    items          = payload.get('items', [])
    discount_type  = payload.get('discount_type', 'pct')
    discount_value = float(payload.get('discount_value', 0) or 0)

    if not name:
        return jsonify({'success': False, 'message': 'الاسم مطلوب'}), 400
    if not items:
        return jsonify({'success': False, 'message': 'السلة فارغة!'}), 400

    # ── stock check ──────────────────────────────────────────
    for it in items:
        pid     = it.get('product_id')
        qty     = max(1, int(it.get('quantity') or 1))
        product = Product.query.get(pid)
        if not product:
            continue
        if product.stock is not None and product.stock < qty:
            return jsonify({'success': False, 'message': f'المخزون غير كافي لـ {product.name_ku}! المتبقي: {product.stock}'}), 400

    # ── build items & subtotal ────────────────────────────────
    subtotal = 0
    lines    = []

    for it in items:
        pid     = it.get('product_id')
        qty     = max(1, int(it.get('quantity') or 1))
        product = Product.query.get(pid)
        if not product:
            continue

        price     = int(product.price or 0)
        subtotal += price * qty
        lines.append(f"{product.name_ku} x{qty}")

        if product.stock is not None:
            product.stock -= qty

    if subtotal <= 0:
        return jsonify({'success': False, 'message': 'لا يمكن تسجيل دين بمبلغ 0'}), 400

    # ── discount calculation ──────────────────────────────────
    if discount_value > 0:
        if discount_type == 'pct':
            discount_amount = round(subtotal * discount_value / 100)
        else:
            discount_amount = round(discount_value)
        discount_amount = min(subtotal, int(discount_amount))
    else:
        discount_amount = 0

    total = subtotal - discount_amount

    # ── build note ────────────────────────────────────────────
    items_text = " | ".join(lines)
    if discount_amount > 0:
        disc_label = f"{int(discount_value)}%" if discount_type == 'pct' else f"{discount_amount:,} IQD"
        items_text += f" | خصم: {disc_label}"

    final_note = (note + " | " if note else "") + items_text if items_text else note

    # ── save debt ─────────────────────────────────────────────
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

    if not barcode:
        return jsonify({'success': False, 'message': 'الباركود فارغ! / Empty barcode'})

    product = Product.query.filter_by(barcode=barcode).first()

    if not product:
        try:
            product_id = int(barcode)
            product    = Product.query.get(product_id)
        except (ValueError, TypeError):
            product = None

    if not product:
        return jsonify({'success': False, 'message': f'المنتج غير موجود! الباركود: {barcode}'})

    return jsonify({
        'success': True,
        'product': {
            'id':      product.id,
            'name_ku': product.name_ku,
            'price':   float(product.price or 0),
            'image':   product.image or ''
        }
    })


# ==================== EXPORT TO EXCEL ====================
@pos_bp.route('/api/export-excel')
@login_required
def export_excel():
    period = request.args.get('period', 'today')
    today  = datetime.now().date()

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
        total_discount = (
            (getattr(s, "auto_discount",    0) or 0) +
            (getattr(s, "manual_discount",  0) or 0) +
            (getattr(s, "discount_amount",  0) or 0)
        )
        writer.writerow([
            s.id,
            s.session_type,
            s.customer_name or 'زائر',
            s.total_amount or 0,
            s.payment_method or 'cash',
            total_discount,
            s.created_at.strftime('%Y-%m-%d %H:%M')
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=padel_reports_{period}_{today}.csv'
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    return response


# ==================== TABLE MANAGEMENT ====================

@pos_bp.route('/tables/manage')
@login_required
def manage_tables():
    tables = Table.query.order_by(Table.id.asc()).all()
    return render_template('pos/manage_tables.html', tables=tables)


@pos_bp.route('/tables/add', methods=['POST'])
@login_required
def add_table():
    name     = (request.form.get('name') or '').strip()
    capacity = request.form.get('capacity', 4)

    if not name:
        flash('اسم الطاولة مطلوب!', 'danger')
        return redirect(url_for('pos.manage_tables'))

    existing = Table.query.filter_by(name=name).first()
    if existing:
        flash(f'يوجد طاولة باسم "{name}" مسبقاً!', 'warning')
        return redirect(url_for('pos.manage_tables'))

    try:
        capacity = int(capacity)
    except Exception:
        capacity = 4

    new_table = Table(name=name, capacity=capacity, is_active=True)
    db.session.add(new_table)
    db.session.commit()

    flash(f'تم إضافة "{name}" بنجاح ✅', 'success')
    return redirect(url_for('pos.manage_tables'))


@pos_bp.route('/tables/<int:table_id>/edit', methods=['POST'])
@login_required
def edit_table(table_id):
    table    = Table.query.get_or_404(table_id)
    name     = (request.form.get('name') or '').strip()
    capacity = request.form.get('capacity', table.capacity)
    is_active = request.form.get('is_active') == '1'

    if not name:
        flash('اسم الطاولة مطلوب!', 'danger')
        return redirect(url_for('pos.manage_tables'))

    existing = Table.query.filter(Table.name == name, Table.id != table_id).first()
    if existing:
        flash(f'يوجد طاولة باسم "{name}" مسبقاً!', 'warning')
        return redirect(url_for('pos.manage_tables'))

    try:
        capacity = int(capacity)
    except Exception:
        capacity = 4

    table.name      = name
    table.capacity  = capacity
    table.is_active = is_active
    db.session.commit()

    flash('تم تعديل الطاولة بنجاح ✅', 'success')
    return redirect(url_for('pos.manage_tables'))


@pos_bp.route('/tables/<int:table_id>/delete', methods=['POST'])
@login_required
def delete_table(table_id):
    table = Table.query.get_or_404(table_id)

    active_session = POSSession.query.filter_by(
        session_type='table',
        table_id=table_id,
        status='active'
    ).first()

    if active_session:
        flash(f'لا يمكن حذف "{table.name}" - يوجد جلسة نشطة الآن!', 'danger')
        return redirect(url_for('pos.manage_tables'))

    name = table.name
    db.session.delete(table)
    db.session.commit()

    flash(f'تم حذف "{name}" بنجاح 🗑️', 'success')
    return redirect(url_for('pos.manage_tables'))


@pos_bp.route('/tables/<int:table_id>/toggle', methods=['POST'])
@login_required
def toggle_table(table_id):
    table            = Table.query.get_or_404(table_id)
    table.is_active  = not table.is_active
    db.session.commit()
    status = 'مفعّل' if table.is_active else 'مخفي'
    return jsonify({'success': True, 'is_active': table.is_active, 'message': f'{table.name} - {status}'})