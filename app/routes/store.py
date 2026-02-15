from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for, abort
from app import db
from app.models.product import Product
from app.models.category import Category
from app.models.order import Order, OrderItem

store_bp = Blueprint('store', __name__)


# -----------------------------
# ✅ Notifications Hook (SAFE)
# -----------------------------
def safe_notify_admins(title: str, message: str = "", url: str = "", ntype: str = "order_created"):
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


# -----------------------------
# ✅ Store Products
# -----------------------------
@store_bp.route('/')
def products():
    """عرض المنتجات مع الفلترة حسب الفئة"""
    category_id = request.args.get('category', type=int)

    # ✅ only categories that should appear on website
    categories = Category.query.filter_by(is_active=True, show_on_website=True).all()

    # ✅ only products visible on website
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

    # ✅ block opening hidden/inactive products
    if not product.is_active or not product.show_in_website:
        abort(404)

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
        if product and product.is_active and product.show_in_website:
            subtotal = product.price * item['quantity']
            products.append({
                'product': product,
                'quantity': item['quantity'],
                'subtotal': subtotal
            })
            total += subtotal

    return render_template('store/cart.html', cart_items=products, total=total, subtotal=total)


@store_bp.route('/cart/add', methods=['POST'])
def add_to_cart():
    """إضافة منتج للسلة"""
    data = request.json or {}
    product_id = data.get('product_id')
    quantity = int(data.get('quantity', 1) or 1)

    product = Product.query.get(product_id)
    if not product or not product.is_active or not product.show_in_website:
        return jsonify({'success': False, 'message': 'المنتج غير متاح'}), 404

    if hasattr(product, 'stock') and product.stock is not None and product.stock <= 0:
        return jsonify({'success': False, 'message': 'المنتج غير متوفر حالياً'}), 400

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
    data = request.json or {}
    product_id = data.get('product_id')

    cart = session.get('cart', [])
    cart = [item for item in cart if item['product_id'] != product_id]
    session['cart'] = cart
    session.modified = True

    return jsonify({'success': True, 'cart_count': len(cart)})


@store_bp.route('/cart/update', methods=['POST'])
def update_cart():
    data = request.json or {}
    product_id = data.get('product_id')
    change = data.get('change')
    quantity = data.get('quantity')

    cart = session.get('cart', [])

    for item in cart:
        if item['product_id'] == product_id:
            if change is not None:
                item['quantity'] = max(1, int(item['quantity']) + int(change))
            elif quantity is not None:
                item['quantity'] = max(1, int(quantity))
            break

    session['cart'] = cart
    session.modified = True

    total = 0
    for item in cart:
        product = Product.query.get(item['product_id'])
        if product and product.is_active and product.show_in_website:
            total += product.price * item['quantity']

    return jsonify({'success': True, 'total': total})


@store_bp.route('/cart/clear', methods=['POST'])
def clear_cart():
    session['cart'] = []
    session.modified = True
    return jsonify({'success': True})


@store_bp.route('/cart/count')
def cart_count():
    cart = session.get('cart', [])
    total_items = sum(item['quantity'] for item in cart)
    return jsonify({'count': len(cart), 'total_items': total_items})


@store_bp.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart_items = session.get('cart', [])
    if not cart_items:
        return render_template('store/checkout.html', cart_items=[], total=0, subtotal=0)

    products = []
    total = 0

    for item in cart_items:
        product = Product.query.get(item['product_id'])
        if product and product.is_active and product.show_in_website:
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
            if product and product.is_active and product.show_in_website:
                item_subtotal = product.price * quantity
                subtotal += item_subtotal

                pname = product.get_name('ku') if hasattr(product, 'get_name') else getattr(product, 'name_ku', 'منتج')
                items_list.append(f"{pname} x{quantity}")

                order_items_data.append({
                    'product': product,
                    'quantity': quantity,
                    'price': product.price
                })

        if not order_items_data:
            return jsonify({'success': False, 'message': 'لم يتم العثور على منتجات صالحة'}), 400

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

        for item_data in order_items_data:
            product = item_data['product']
            qty = item_data['quantity']

            db.session.add(OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=qty,
                price=item_data['price']
            ))

            if hasattr(product, 'stock') and product.stock is not None and product.stock >= qty:
                product.stock -= qty

        db.session.commit()

        safe_notify_admins(
            title="New store order 🛒",
            message=f"Order #{order.id} pending | {customer_name} | {customer_phone} | Items: " + " | ".join(items_list),
            url=f"/admin/orders?highlight={order.id}",
            ntype="order_created"
        )

        session['cart'] = []
        session.modified = True

        return jsonify({'success': True, 'message': f'تم إرسال الطلب بنجاح! رقم الطلب: {order.id}', 'order_id': order.id})

    except Exception as e:
        db.session.rollback()
        print(f"Order error: {e}")
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500


@store_bp.route('/place-order', methods=['POST'])
def place_order():
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
            if product and product.is_active and product.show_in_website:
                subtotal += product.price * item['quantity']
                pname = product.get_name('ku') if hasattr(product, 'get_name') else getattr(product, 'name_ku', 'منتج')
                items_list.append(f"{pname} x{item['quantity']}")

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
            if product and product.is_active and product.show_in_website:
                db.session.add(OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=item['quantity'],
                    price=product.price
                ))

                if hasattr(product, 'stock') and product.stock is not None and product.stock >= item['quantity']:
                    product.stock -= item['quantity']

        db.session.commit()

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
    order = Order.query.get_or_404(order_id)
    return render_template('store/order_success.html', order=order)