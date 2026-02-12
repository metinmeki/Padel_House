from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for
from app import db
from app.models.product import Product
from app.models.category import Category
from app.models.order import Order, OrderItem

store_bp = Blueprint('store', __name__)

# -----------------------------
# ✅ Notifications Hook (SAFE)
# -----------------------------
def safe_notify_admins(title: str, message: str = "", url: str = "", ntype: str = "order_created"):
    """
    Safe notification hook.
    - Uses Notification system if available
    - Never breaks order flow
    """
    try:
        from app.services.notify import notify_admins
        notify_admins(title=title, message=message, url=url, ntype=ntype)
        return True
    except ImportError:
        print("ℹ️ Notification service not installed yet.")
        return False
    except Exception as e:
        print("❌ Notification error:", e)
        return False


@store_bp.route('/')
def products():
    """عرض المنتجات مع الفلترة حسب الفئة"""
    category_id = request.args.get('category', type=int)
    categories = Category.query.filter_by(is_active=True).all()

    query = Product.query.filter_by(is_active=True, show_in_website=True)

    if category_id:
        query = query.filter_by(category_id=category_id)

    products = query.all()

    return render_template(
        'store/products.html',
        categories=categories,
        products=products,
        current_category=category_id
    )


@store_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    """صفحة تفاصيل المنتج"""
    product = Product.query.get_or_404(product_id)
    related_products = Product.query.filter(
        Product.category_id == product.category_id,
        Product.id != product.id,
        Product.is_active == True,
        Product.show_in_website == True
    ).limit(4).all()

    return render_template(
        'store/product_detail.html',
        product=product,
        related_products=related_products
    )


@store_bp.route('/cart')
def cart():
    """عرض السلة"""
    cart_items = session.get('cart', [])
    products = []
    total = 0

    for item in cart_items:
        product = Product.query.get(item['product_id'])
        if product:
            subtotal = product.price * item['quantity']
            products.append({
                'product': product,
                'quantity': item['quantity'],
                'subtotal': subtotal
            })
            total += subtotal

    return render_template(
        'store/cart.html',
        cart_items=products,
        total=total,
        subtotal=total
    )


@store_bp.route('/cart/add', methods=['POST'])
def add_to_cart():
    """إضافة منتج للسلة"""
    data = request.json
    product_id = data.get('product_id')
    quantity = data.get('quantity', 1)

    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'})

    if hasattr(product, 'stock') and product.stock <= 0:
        return jsonify({'success': False, 'message': 'المنتج غير متوفر حالياً'})

    cart = session.get('cart', [])

    found = False
    for item in cart:
        if item['product_id'] == product_id:
            item['quantity'] += quantity
            found = True
            break

    if not found:
        cart.append({'product_id': product_id, 'quantity': quantity})

    session['cart'] = cart
    session.modified = True

    total_items = sum(item['quantity'] for item in cart)
    return jsonify({'success': True, 'cart_count': len(cart), 'total_items': total_items})


@store_bp.route('/cart/remove', methods=['POST'])
def remove_from_cart():
    """حذف منتج من السلة"""
    data = request.json
    product_id = data.get('product_id')

    cart = session.get('cart', [])
    cart = [item for item in cart if item['product_id'] != product_id]
    session['cart'] = cart
    session.modified = True

    return jsonify({'success': True, 'cart_count': len(cart)})


@store_bp.route('/cart/update', methods=['POST'])
def update_cart():
    """تحديث كمية المنتج في السلة"""
    data = request.json
    product_id = data.get('product_id')
    change = data.get('change')
    quantity = data.get('quantity')

    cart = session.get('cart', [])

    for item in cart:
        if item['product_id'] == product_id:
            if change is not None:
                item['quantity'] += change
                if item['quantity'] < 1:
                    item['quantity'] = 1
            elif quantity is not None:
                item['quantity'] = max(1, quantity)
            break

    session['cart'] = cart
    session.modified = True

    total = 0
    for item in cart:
        product = Product.query.get(item['product_id'])
        if product:
            total += product.price * item['quantity']

    return jsonify({'success': True, 'total': total})


@store_bp.route('/cart/clear', methods=['POST'])
def clear_cart():
    """تفريغ السلة"""
    session['cart'] = []
    session.modified = True
    return jsonify({'success': True})


@store_bp.route('/cart/count')
def cart_count():
    """عدد العناصر في السلة"""
    cart = session.get('cart', [])
    total_items = sum(item['quantity'] for item in cart)
    return jsonify({'count': len(cart), 'total_items': total_items})


@store_bp.route('/checkout', methods=['GET', 'POST'])
def checkout():
    """صفحة الدفع"""
    cart_items = session.get('cart', [])

    if not cart_items:
        return render_template('store/checkout.html', cart_items=[], total=0, subtotal=0)

    products = []
    total = 0

    for item in cart_items:
        product = Product.query.get(item['product_id'])
        if product:
            subtotal = product.price * item['quantity']
            products.append({
                'product': product,
                'quantity': item['quantity'],
                'subtotal': subtotal
            })
            total += subtotal

    return render_template('store/checkout.html', cart_items=products, total=total, subtotal=total)


# -----------------------------
# ✅ API Order (AJAX)
# -----------------------------
@store_bp.route('/api/order', methods=['POST'])
def create_order_api():
    """API endpoint for placing orders via AJAX"""
    try:
        data = request.json or {}

        customer_name = (data.get('customer_name') or '').strip()
        customer_phone = (data.get('customer_phone') or '').strip()
        customer_email = (data.get('customer_email') or '').strip()

        delivery_method = (data.get('delivery_method') or data.get('deliveryMethod') or 'pickup').strip().lower()
        if delivery_method not in ['pickup', 'delivery']:
            delivery_method = 'pickup'

        address = (data.get('address') or '').strip()
        area = (data.get('area') or '').strip()
        notes = data.get('notes', '')

        cart_items = data.get('items', []) or session.get('cart', [])

        if not cart_items:
            return jsonify({'success': False, 'message': 'السلة فارغة'}), 400

        if not customer_name or not customer_phone:
            return jsonify({'success': False, 'message': 'الاسم ورقم الهاتف مطلوبان'}), 400

        if delivery_method == 'delivery' and (not address or not area):
            return jsonify({'success': False, 'message': 'يرجى إدخال المنطقة والعنوان للتوصيل'}), 400

        subtotal = 0
        items_list = []
        order_items_data = []

        for item in cart_items:
            product_id = item.get('id') or item.get('product_id')
            quantity = int(item.get('quantity', 1) or 1)

            product = Product.query.get(product_id)
            if product:
                item_subtotal = product.price * quantity
                subtotal += item_subtotal

                product_name = product.get_name('ku') if hasattr(product, 'get_name') else getattr(product, 'name_ku', getattr(product, 'name', 'منتج'))
                items_list.append(f"{product_name} x{quantity}")

                order_items_data.append({
                    'product': product,
                    'quantity': quantity,
                    'price': product.price
                })

        if not order_items_data:
            return jsonify({'success': False, 'message': 'لم يتم العثور على منتجات صالحة'}), 400

        delivery_fee = 5000 if delivery_method == 'delivery' else 0
        total_price = subtotal + delivery_fee

        # ✅ Create order (PENDING)
        order = Order(
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_email=customer_email,
            delivery_method=delivery_method,
            area=area if delivery_method == 'delivery' else None,
            address=address if delivery_method == 'delivery' else None,
            notes=notes,
            total_price=total_price,
            status='pending'
        )

        db.session.add(order)
        db.session.flush()

        # Add items + update stock
        for item_data in order_items_data:
            product = item_data['product']
            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=item_data['quantity'],
                price=item_data['price']
            )
            db.session.add(order_item)

            if hasattr(product, 'stock') and product.stock is not None:
                if product.stock >= item_data['quantity']:
                    product.stock -= item_data['quantity']

        db.session.commit()

        # ✅ Notify admins about new order
        safe_notify_admins(
            title="New store order 🛒",
            message=f"Order #{order.id} pending | {customer_name} | {customer_phone} | Items: " + " | ".join(items_list),
            url=f"/admin/orders?highlight={order.id}",
            ntype="order_created"
        )

        # ✅ IMPORTANT: do NOT send to Google Sheets here anymore.
        # It will be sent ONLY after admin confirms in admin.py.

        session['cart'] = []
        session.modified = True

        return jsonify({
            'success': True,
            'message': 'تم إرسال الطلب بنجاح! رقم الطلب: ' + str(order.id),
            'order_id': order.id
        })

    except Exception as e:
        db.session.rollback()
        print(f"Order error: {e}")
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


# -----------------------------
# ✅ Form-based order placement
# -----------------------------
@store_bp.route('/place-order', methods=['POST'])
def place_order():
    """Form-based order placement"""
    cart = session.get('cart', [])
    if not cart:
        flash('السلة فارغة', 'error')
        return redirect(url_for('store.cart'))

    try:
        customer_name = (request.form.get('customer_name') or '').strip()
        customer_phone = (request.form.get('customer_phone') or '').strip()
        customer_email = (request.form.get('customer_email') or '').strip()

        delivery_method = (request.form.get('delivery_method') or 'pickup').strip().lower()
        if delivery_method not in ['pickup', 'delivery']:
            delivery_method = 'pickup'

        address = (request.form.get('address') or '').strip()
        area = (request.form.get('area') or '').strip()
        notes = request.form.get('notes', '')

        if not customer_name or not customer_phone:
            flash('الاسم ورقم الهاتف مطلوبان', 'error')
            return redirect(url_for('store.checkout'))

        if delivery_method == 'delivery' and (not address or not area):
            flash('يرجى إدخال المنطقة والعنوان للتوصيل', 'error')
            return redirect(url_for('store.checkout'))

        subtotal = 0
        items_list = []

        for item in cart:
            product = Product.query.get(item['product_id'])
            if product:
                subtotal += product.price * item['quantity']
                product_name = product.get_name('ku') if hasattr(product, 'get_name') else getattr(product, 'name_ku', getattr(product, 'name', 'منتج'))
                items_list.append(f"{product_name} x{item['quantity']}")

        delivery_fee = 5000 if delivery_method == 'delivery' else 0
        total_price = subtotal + delivery_fee

        order = Order(
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_email=customer_email,
            delivery_method=delivery_method,
            area=area if delivery_method == 'delivery' else None,
            address=address if delivery_method == 'delivery' else None,
            notes=notes,
            total_price=total_price,
            status='pending'
        )

        db.session.add(order)
        db.session.flush()

        for item in cart:
            product = Product.query.get(item['product_id'])
            if product:
                order_item = OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=item['quantity'],
                    price=product.price
                )
                db.session.add(order_item)

                if hasattr(product, 'stock') and product.stock is not None:
                    if product.stock >= item['quantity']:
                        product.stock -= item['quantity']

        db.session.commit()

        # ✅ Notify admins about new order
        safe_notify_admins(
            title="New store order 🛒",
            message=f"Order #{order.id} pending | {customer_name} | {customer_phone} | Items: " + " | ".join(items_list),
            url=f"/admin/orders?highlight={order.id}",
            ntype="order_created"
        )

        flash('تم إرسال طلبك بنجاح!', 'success')

        session['cart'] = []
        session.modified = True

        return render_template('store/order_success.html', order=order)

    except Exception as e:
        db.session.rollback()
        flash(f'خطأ في الطلب: {str(e)}', 'error')
        return redirect(url_for('store.checkout'))


@store_bp.route('/order-success/<int:order_id>')
def order_success(order_id):
    """صفحة نجاح الطلب"""
    order = Order.query.get_or_404(order_id)
    return render_template('store/order_success.html', order=order)