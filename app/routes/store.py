from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for
from app import db
from app.models.product import Product
from app.models.category import Category
from app.models.order import Order, OrderItem
from app.services.google_sheets import send_order_to_sheet

store_bp = Blueprint('store', __name__)


@store_bp.route('/')
def products():
    """عرض المنتجات مع الفلترة حسب الفئة"""
    # ✅ FIXED: Get category ID directly (not name mapping)
    category_id = request.args.get('category', type=int)
    categories = Category.query.filter_by(is_active=True).all()

    # ✅ Base query - only website products
    query = Product.query.filter_by(is_active=True, show_in_website=True)

    # ✅ Filter by category if selected
    if category_id:
        query = query.filter_by(category_id=category_id)

    products = query.all()

    return render_template('store/products.html',
                           categories=categories,
                           products=products,
                           current_category=category_id)


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
    return render_template('store/product_detail.html',
                           product=product,
                           related_products=related_products)


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

    return render_template('store/cart.html',
                           cart_items=products,
                           total=total,
                           subtotal=total)


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
    return jsonify({'success': True,
                    'cart_count': len(cart),
                    'total_items': total_items})


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
        return render_template('store/checkout.html',
                               cart_items=[],
                               total=0,
                               subtotal=0)

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

    return render_template('store/checkout.html',
                           cart_items=products,
                           total=total,
                           subtotal=total)


@store_bp.route('/api/order', methods=['POST'])
def api_place_order():
    """API endpoint for placing orders via AJAX"""
    try:
        data = request.json

        customer_name = data.get('customer_name')
        customer_phone = data.get('customer_phone')
        customer_email = data.get('customer_email', '')
        delivery_method = data.get('delivery_method', 'pickup')
        address = data.get('address', '')
        area = data.get('area', '')
        notes = data.get('notes', '')

        cart_items = data.get('items', [])
        if not cart_items:
            cart_items = session.get('cart', [])

        if not cart_items:
            return jsonify({'success': False, 'message': 'السلة فارغة'}), 400

        if not customer_name or not customer_phone:
            return jsonify({'success': False, 'message': 'الاسم ورقم الهاتف مطلوبان'}), 400

        total = 0
        items_list = []
        order_items_data = []

        for item in cart_items:
            product_id = item.get('id') or item.get('product_id')
            quantity = item.get('quantity', 1)

            product = Product.query.get(product_id)
            if product:
                subtotal = product.price * quantity
                total += subtotal

                product_name = product.get_name('ku') if hasattr(product, 'get_name') else getattr(product, 'name_ku', getattr(product, 'name', 'منتج'))
                items_list.append(f"{product_name} x{quantity}")

                order_items_data.append({
                    'product': product,
                    'quantity': quantity,
                    'price': product.price
                })

        if not order_items_data:
            return jsonify({'success': False, 'message': 'لم يتم العثور على منتجات صالحة'}), 400

        if delivery_method == 'delivery':
            total += 5000

        order_address = f"{area} - {address}" if delivery_method == 'delivery' else 'استلام من المتجر'

        order = Order(
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_email=customer_email,
            customer_address=order_address,
            notes=f"طريقة التوصيل: {delivery_method} | {notes}",
            total_price=total,
            status='pending'
        )

        db.session.add(order)
        db.session.flush()

        for item_data in order_items_data:
            product = item_data['product']
            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=item_data['quantity'],
                price=item_data['price']
            )
            db.session.add(order_item)

            if hasattr(product, 'stock') and product.stock >= item_data['quantity']:
                product.stock -= item_data['quantity']

        db.session.commit()

        flash('🔔 طلب متجر جديد! يرجى المراجعة', 'admin')

        try:
            send_order_to_sheet(order, " | ".join(items_list))
        except Exception as e:
            print(f"Google Sheets error: {e}")

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


@store_bp.route('/place-order', methods=['POST'])
def place_order():
    """Form-based order placement"""
    cart = session.get('cart', [])
    if not cart:
        flash('السلة فارغة', 'error')
        return redirect(url_for('store.cart'))

    try:
        customer_name = request.form.get('customer_name')
        customer_phone = request.form.get('customer_phone')
        customer_email = request.form.get('customer_email', '')
        delivery_method = request.form.get('delivery_method', 'pickup')
        address = request.form.get('address', '')
        area = request.form.get('area', '')
        notes = request.form.get('notes', '')

        if not customer_name or not customer_phone:
            flash('الاسم ورقم الهاتف مطلوبان', 'error')
            return redirect(url_for('store.checkout'))

        total = 0
        items_list = []

        for item in cart:
            product = Product.query.get(item['product_id'])
            if product:
                total += product.price * item['quantity']
                product_name = product.get_name('ku') if hasattr(product, 'get_name') else getattr(product, 'name_ku', getattr(product, 'name', 'منتج'))
                items_list.append(f"{product_name} x{item['quantity']}")

        order_address = f"{area} - {address}" if delivery_method == 'delivery' else 'استلام من المتجر'
        if delivery_method == 'delivery':
            total += 5000

        order = Order(
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_email=customer_email,
            customer_address=order_address,
            notes=f"طريقة التوصيل: {delivery_method} | {notes}",
            total_price=total,
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

                if hasattr(product, 'stock'):
                    product.stock -= item['quantity']

        db.session.commit()

        flash('🔔 طلب متجر جديد!', 'admin')
        flash('تم إرسال طلبك بنجاح!', 'success')

        try:
            send_order_to_sheet(order, " | ".join(items_list))
        except Exception as e:
            print(f"Google Sheets error: {e}")

        session['cart'] = []
        session.modified = True

        return render_template('store/order_success.html', order=order)

    except Exception as e:
        db.session.rollback()
        flash(f'خطأ في الطلب: {str(e)}', 'error')
        return redirect(url_for('store.checkout'))


@store_bp.route('/order-success/<int:order_id>')
@store_bp.route('/order/success/<int:order_id>')
def order_success(order_id):
    """صفحة نجاح الطلب"""
    order = Order.query.get_or_404(order_id)
    return render_template('store/order_success.html', order=order)