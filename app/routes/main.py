from flask import Blueprint, render_template, session, redirect, request, url_for, flash
from app import db
from app.models.stadium import Stadium
from app.models.product import Product
from app.models.coach import Coach
from app.models.coach_training_request import CoachTrainingRequest

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    stadiums = Stadium.query.filter_by(is_active=True).all()

    featured_products = Product.query.filter_by(
        is_active=True,
        show_in_website=True
    ).order_by(Product.created_at.desc()).limit(4).all()

    return render_template(
        'main/index.html',
        stadiums=stadiums,
        featured_products=featured_products
    )


@main_bp.route('/set-language/<lang>')
def set_language(lang):
    supported_languages = ['ku', 'ar', 'en']

    if lang in supported_languages:
        session['lang'] = lang

    return redirect(request.referrer or url_for('main.index'))


@main_bp.route('/about')
def about():
    return render_template('main/about.html')


@main_bp.route('/contact')
def contact():
    return render_template('main/contact.html')


@main_bp.route('/training')
def training():
    coaches = Coach.query.filter_by(is_active=True).order_by(Coach.id.asc()).all()
    return render_template('main/training.html', coaches=coaches)


@main_bp.route('/training/request', methods=['POST'])
def submit_training_request():
    coach_id = request.form.get('coach_id')
    package_name = (request.form.get('package_name') or '').strip()
    package_price = request.form.get('package_price') or 0
    package_sessions = request.form.get('package_sessions') or 0
    full_name = (request.form.get('full_name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    level = (request.form.get('level') or '').strip()
    note = (request.form.get('note') or '').strip()

    if not coach_id or not full_name or not phone or not package_name:
        flash('يرجى ملء جميع الحقول المطلوبة', 'warning')
        return redirect(url_for('main.training'))

    try:
        training_request = CoachTrainingRequest(
            coach_id=int(coach_id),
            full_name=full_name,
            phone=phone,
            level=level or None,
            note=note or None,
            package_name=package_name,
            package_price=int(package_price or 0),
            package_sessions=int(package_sessions or 0)
        )

        db.session.add(training_request)
        db.session.commit()

        flash('تم إرسال طلب التدريب بنجاح، سيتواصل معك فريقنا قريبًا.', 'success')

    except Exception as e:
        db.session.rollback()
        flash('حدث خطأ أثناء إرسال الطلب، حاول مرة أخرى.', 'danger')
        print("Training Request Error:", e)

    return redirect(url_for('main.training'))