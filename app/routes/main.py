from flask import Blueprint, render_template
from app.models.stadium import Stadium
from app.models.product import Product

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    stadiums = Stadium.query.filter_by(is_active=True).all()
    # Get featured products for homepage (latest 4 active products)
    featured_products = Product.query.filter_by(is_active=True).order_by(Product.created_at.desc()).limit(4).all()
    return render_template('main/index.html', stadiums=stadiums, featured_products=featured_products)


@main_bp.route('/set-language/<lang>')
def set_language(lang):
    from flask import session, redirect, request

    supported_languages = ['ku', 'ar', 'en']

    if lang in supported_languages:
        session['lang'] = lang

    # Go back to the previous page
    return redirect(request.referrer or url_for('main.index'))

@main_bp.route('/about')
def about():
    return render_template('main/about.html')


@main_bp.route('/contact')
def contact():
    return render_template('main/contact.html')