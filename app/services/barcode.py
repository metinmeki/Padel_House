"""
Barcode Generator Service for Padel House
توليد باركود EAN13 للمنتجات تلقائياً
"""

from barcode import EAN13, Code128
from barcode.writer import ImageWriter
import os
import random
from app import app
from flask import current_app


def generate_product_barcode(product_id, product_title="منتج"):
    """
    إنشاء باركود EAN13 فريد للمنتج

    Args:
        product_id: معرف المنتج
        product_title: اسم المنتج (للـ fallback)

    Returns:
        dict: barcode_number, image_path أو None
    """

    try:
        # ✅ إنشاء رقم EAN13 فريد (12 رقم + check digit تلقائي)
        # 626 = Iraq prefix
        random_digits = random.randint(1000000, 9999999)
        barcode_number = f"626{random_digits:07d}"

        # إنشاء مجلد الباركود
        barcode_dir = os.path.join(current_app.root_path, 'static', 'barcodes')
        os.makedirs(barcode_dir, exist_ok=True)

        # اسم الملف الفريد
        filename = f"prod_{product_id}_{barcode_number}.png"
        filepath = os.path.join(barcode_dir, filename)

        # ✅ إنشاء الباركود EAN13
        code = EAN13(barcode_number, writer=ImageWriter())

        # حفظ الصورة
        code.save(filepath)

        # مسار العرض في المتصفح
        image_url = f'/static/barcodes/{filename}'

        print(f"✅ Barcode generated: {barcode_number} -> {image_url}")

        return {
            'barcode_number': barcode_number,
            'image_path': image_url,
            'filename': filename
        }

    except Exception as e:
        print(f"❌ Barcode error for product {product_id}: {e}")
        return None


def generate_text_barcode(text, product_id=None):
    """
    باركود Code128 للنصوص (اسم المنتج)
    """
    try:
        if not product_id:
            product_id = random.randint(1000, 9999)

        barcode_dir = os.path.join(current_app.root_path, 'static', 'barcodes')
        os.makedirs(barcode_dir, exist_ok=True)

        filename = f"text_{product_id}_{text[:20].replace(' ', '_')}.png"
        filepath = os.path.join(barcode_dir, filename)

        code = Code128(text[:50], writer=ImageWriter())  # max 50 chars
        code.save(filepath)

        return f'/static/barcodes/{filename}'

    except Exception as e:
        print(f"❌ Text barcode error: {e}")
        return None


def regenerate_product_barcode(product_id):
    """
    إعادة إنشاء باركود لمنتج موجود
    """
    from app.models.product import Product

    product = Product.query.get(product_id)
    if not product:
        return None

    barcode_data = generate_product_barcode(product_id, product.title)
    if barcode_data:
        product.barcode = barcode_data['barcode_number']
        product.barcode_image = barcode_data['image_path']
        db.session.commit()
        return barcode_data
    return None


def bulk_generate_barcodes():
    """
    إنشاء باركود لكل المنتجات بدون باركود
    """
    from app import db
    from app.models.product import Product

    products = Product.query.filter(
        (Product.barcode == None) | (Product.barcode == '')
    ).all()

    results = []
    for product in products:
        barcode_data = generate_product_barcode(product.id, product.title)
        if barcode_data:
            product.barcode = barcode_data['barcode_number']
            product.barcode_image = barcode_data['image_path']
            results.append(product.id)

    db.session.commit()
    return {
        'success': True,
        'count': len(results),
        'products': results
    }


# ✅ دالة مساعدة للطباعة
def get_printable_barcode(product_id):
    """
    إرجاع مسار باركود جاهز للطباعة
    """
    from app.models.product import Product
    product = Product.query.get(product_id)

    if product and product.barcode_image:
        return {
            'image': product.barcode_image,
            'code': product.barcode,
            'title': product.title,
            'price': product.price
        }
    return None
