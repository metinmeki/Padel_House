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
# ✅ Helpers
# -----------------------------
def _get_cart():
    return session.get('cart', []) or []

def _save_cart(cart):
    session['cart'] = cart
    session.modified = True

def _cart_qty_for(cart, product_id):
    for it in cart:
        if it.get('product_id') == product_id:
            return int(it.get('quantity', 0) or 0)
    return 0

def _is_stock_limited(product: Product):
    # إذا عندك stock None اعتبره غير محدود (حسب منطقك الحالي)
    return hasattr(product, 'stock') and product.stock is not None

def _available_stock(product: Product):
    return int(product.stock or 0)

def _validate_cart_stock(cart_items):
    """
    ✅ يتأكد أن كل منتج في السلة:
    - موجود وفعال ويظهر بالموقع
    - والكمية المطلوبة <= stock (إذا كان stock محدود)
    يرجع (ok, message)
    """
    for item in cart_items:
        pid = item.get('product_id')
        qty = int(item.get('quantity', 1) or 1)
        qty = max(1, qty)

        product = Product.query.get(pid)
        if not product or not product.is_active or not product.show_in_website:
            return False, "يوجد منتج غير متاح في السلة. يرجى تحديث السلة."

        if _is_stock_limited(product):
            if _available_stock(product) < qty:
                pname = product.get_name('ar') if hasattr(product, 'get_name') else (product.name_ar or product.name_ku)
                return False, f"المخزون غير كافي للمنتج: {pname} | المتوفر: {_available_stock(product)}"

    return True, ""


# -----------------------------
# ✅ Store Products
# -----------------------------
@store_bp.route('/')
def products():
    """عرض المنتجات مع الفلترة حسب الفئة"""
    category_id = request.args.get('category', type=int)

    categories = Category.query.filter_by(is_active=True, show_on_website=True).all()
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
    cart_items = _get_cart()
    products = []
    total = 0

    for item in cart_items:
        product = Product.query.get(item['product_id'])
        if product and product.is_active and product.show_in_website:
            qty = int(item['quantity'] or 1)
            qty = max(1, qty)
            subtotal = product.price * qty
            products.append({
                'product': product,
                'quantity': qty,
                'subtotal': subtotal
            })
            total += subtotal

    return render_template('store/cart.html', cart_items=products, total=total, subtotal=total)


# -----------------------------
# ✅ Cart APIs
# -----------------------------
@store_bp.route('/cart/add', methods=['POST'])
def add_to_cart():
    """إضافة منتج للسلة + تحقق مخزون"""
    data = request.json or {}
    product_id = data.get('product_id')
    quantity = int(data.get('quantity', 1) or 1)
    quantity = max(1, quantity)

    product = Product.query.get(product_id)
    if not product or not product.is_active or not product.show_in_website:
        return jsonify({'success': False, 'message': 'المنتج غير متاح'}), 404

    cart = _get_cart()
    existing_qty = _cart_qty_for(cart, product.id)
    new_qty = existing_qty + quantity

    # ✅ تحقق المخزون مع مجموع السلة
    if _is_stock_limited(product):
        if _available_stock(product) <= 0:
            return jsonify({'success': False, 'message': 'المنتج غير متوفر حالياً'}), 400

        if _available_stock(product) < new_qty:
            pname = product.get_name('ar') if hasattr(product, 'get_name') else (product.name_ar or product.name_ku)
            return jsonify({
                'success': False,
                'message': f'المخزون غير كافي للمنتج: {pname} | المتوفر: {_available_stock(product)}'
            }), 400

    found = False
    for item in cart:
        if item['product_id'] == product.id:
            item['quantity'] = new_qty
            found = True
            break

    if not found:
        cart.append({'product_id': product.id, 'quantity': quantity})

    _save_cart(cart)

    total_items = sum(int(it.get('quantity', 0) or 0) for it in cart)
    return jsonify({'success': True, 'cart_count': len(cart), 'total_items': total_items})


@store_bp.route('/cart/remove', methods=['POST'])
def remove_from_cart():
    data = request.json or {}
    product_id = data.get('product_id')

    cart = _get_cart()
    cart = [item for item in cart if item['product_id'] != product_id]
    _save_cart(cart)

    return jsonify({'success': True, 'cart_count': len(cart)})


@store_bp.route('/cart/update', methods=['POST'])
def update_cart():
    """تعديل الكمية + تحقق المخزون"""
    data = request.json or {}
    product_id = data.get('product_id')
    change = data.get('change')
    quantity = data.get('quantity')

    cart = _get_cart()

    for item in cart:
        if item['product_id'] == product_id:
            if change is not None:
                new_qty = max(1, int(item['quantity'] or 1) + int(change))
            elif quantity is not None:
                new_qty = max(1, int(quantity))
            else:
                new_qty = max(1, int(item['quantity'] or 1))

            product = Product.query.get(product_id)
            if not product or not product.is_active or not product.show_in_website:
                return jsonify({'success': False, 'message': 'المنتج غير متاح'}), 404

            if _is_stock_limited(product):
                if _available_stock(product) < new_qty:
                    pname = product.get_name('ar') if hasattr(product, 'get_name') else (product.name_ar or product.name_ku)
                    return jsonify({
                        'success': False,
                        'message': f'المخزون غير كافي للمنتج: {pname} | المتوفر: {_available_stock(product)}'
                    }), 400

            item['quantity'] = new_qty
            break

    _save_cart(cart)

    total = 0
    for item in cart:
        product = Product.query.get(item['product_id'])
        if product and product.is_active and product.show_in_website:
            total += product.price * int(item['quantity'] or 1)

    return jsonify({'success': True, 'total': total})


@store_bp.route('/cart/clear', methods=['POST'])
def clear_cart():
    session['cart'] = []
    session.modified = True
    return jsonify({'success': True})


@store_bp.route('/cart/count')
def cart_count():
    cart = _get_cart()
    total_items = sum(int(item.get('quantity', 0) or 0) for item in cart)
    return jsonify({'count': len(cart), 'total_items': total_items})


# -----------------------------
# ✅ Checkout Pages
# -----------------------------
@store_bp.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart_items = _get_cart()
    if not cart_items:
        return render_template('store/checkout.html', cart_items=[], total=0, subtotal=0)

    products = []
    total = 0

    for item in cart_items:
        product = Product.query.get(item['product_id'])
        if product and product.is_active and product.show_in_website:
            qty = max(1, int(item['quantity'] or 1))
            subtotal = product.price * qty
            products.append({
                'product': product,
                'quantity': qty,
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

        cart_items = data.get('items', []) or _get_cart()

        if not cart_items:
            return jsonify({'success': False, 'message': 'السلة فارغة'}), 400

        if not customer_name or not customer_phone:
            return jsonify({'success': False, 'message': 'الاسم ورقم الهاتف مطلوبان'}), 400

        if delivery_method == 'delivery' and (not address or not area):
            return jsonify({'success': False, 'message': 'يرجى إدخال المنطقة والعنوان للتوصيل'}), 400

        # ✅ توحيد شكل العناصر (id / product_id)
        normalized_cart = []
        for item in cart_items:
            pid = item.get('id') or item.get('product_id')
            qty = int(item.get('quantity', 1) or 1)
            qty = max(1, qty)
            normalized_cart.append({'product_id': pid, 'quantity': qty})

        # ✅ تحقق المخزون قبل أي شيء
        ok, msg = _validate_cart_stock(normalized_cart)
        if not ok:
            return jsonify({'success': False, 'message': msg}), 400

        subtotal = 0
        items_list = []
        order_items_data = []

        for item in normalized_cart:
            product_id = item['product_id']
            quantity = item['quantity']

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

        # ✅ إنشاء العناصر + خصم المخزون (بعد التحقق)
        for item_data in order_items_data:
            product = item_data['product']
            qty = item_data['quantity']

            db.session.add(OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=qty,
                price=item_data['price']
            ))

            if _is_stock_limited(product):
                # حماية إضافية (حتى لو صار طلبين بنفس اللحظة)
                if _available_stock(product) < qty:
                    db.session.rollback()
                    pname = product.get_name('ar') if hasattr(product, 'get_name') else (product.name_ar or product.name_ku)
                    return jsonify({'success': False, 'message': f'المخزون تغير أثناء الطلب. المنتج: {pname}'}), 400
                product.stock = _available_stock(product) - qty

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


# -----------------------------
# ✅ Place Order (FORM)
# -----------------------------
@store_bp.route('/place-order', methods=['POST'])
def place_order():
    cart = _get_cart()
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

        # ✅ تحقق مخزون قبل إنشاء الطلب
        ok, msg = _validate_cart_stock(cart)
        if not ok:
            flash(msg, 'error')
            return redirect(url_for('store.cart'))

        subtotal = 0
        items_list = []
        items_for_create = []

        for item in cart:
            product = Product.query.get(item['product_id'])
            if product and product.is_active and product.show_in_website:
                qty = max(1, int(item['quantity'] or 1))
                subtotal += product.price * qty
                pname = product.get_name('ku') if hasattr(product, 'get_name') else getattr(product, 'name_ku', 'منتج')
                items_list.append(f"{pname} x{qty}")
                items_for_create.append((product, qty))

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

        for product, qty in items_for_create:
            db.session.add(OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=qty,
                price=product.price
            ))

            if _is_stock_limited(product):
                if _available_stock(product) < qty:
                    db.session.rollback()
                    pname = product.get_name('ar') if hasattr(product, 'get_name') else (product.name_ar or product.name_ku)
                    flash(f'المخزون تغير أثناء الطلب. المنتج: {pname}', 'error')
                    return redirect(url_for('store.cart'))
                product.stock = _available_stock(product) - qty

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