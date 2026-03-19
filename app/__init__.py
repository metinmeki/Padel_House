# app/__init__.py
from flask import Flask, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
import os
import secrets
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()


def create_app(config_name='development'):
    app = Flask(__name__, instance_relative_config=True)

    # ---------------- SECURITY CONFIG ----------------
    app.config['SECRET_KEY'] = os.getenv(
        'SECRET_KEY',
        secrets.token_hex(32)
    )

    # ---------------- DB CONFIG ----------------
    # Always use the real SQLite database inside /instance
    os.makedirs(app.instance_path, exist_ok=True)
    instance_db_path = os.path.join(app.instance_path, 'padel_house.db')

    if config_name == 'production':
        app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
            'DATABASE_URL',
            f'sqlite:///{instance_db_path}'
        )
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{instance_db_path}'

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SESSION_PERMANENT'] = True

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'يرجى تسجيل الدخول أولاً'
    login_manager.login_message_category = 'warning'

    # ---------------- REGISTER BLUEPRINTS ----------------
    from app.routes.main import main_bp
    from app.routes.booking import booking_bp
    from app.routes.store import store_bp
    from app.routes.admin import admin_bp
    from app.routes.auth import auth_bp
    from app.routes.pos import pos_bp

    # إذا أضفت Tapane route فعلًا، فعّل هذين السطرين
    try:
        from app.routes.tapane import tapane_bp
        has_tapane = True
    except Exception:
        has_tapane = False

    app.register_blueprint(main_bp)
    app.register_blueprint(booking_bp, url_prefix='/booking')
    app.register_blueprint(store_bp, url_prefix='/store')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(pos_bp, url_prefix='/pos')

    if has_tapane:
        app.register_blueprint(tapane_bp, url_prefix='/tapane')

    # ---------------- USER LOADER ----------------
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ---------------- LANGUAGE SYSTEM (DEFAULT = ENGLISH) ----------------
    from app.models.settings import Settings
    from app.translations import get_translation

    @app.before_request
    def ensure_language():
        if 'lang' not in session:
            session['lang'] = 'en'

    @app.context_processor
    def inject_globals():
        settings = Settings.query.first()
        current_lang = session.get('lang', 'en')

        def t(key):
            return get_translation(key, current_lang)

        language_flags = {'ku': '🇮🇶', 'ar': '🇸🇦', 'en': '🇬🇧'}
        language_names = {'ku': 'کوردی', 'ar': 'العربية', 'en': 'English'}
        languages = ['en', 'ar', 'ku']
        is_rtl = current_lang in ['ku', 'ar']

        return {
            't': t,
            'settings': settings,
            'language_flags': language_flags,
            'language_names': language_names,
            'languages': languages,
            'current_lang': current_lang,
            'is_rtl': is_rtl
        }

    # ---------------- DATABASE INIT ----------------
    with app.app_context():
        db.create_all()

        # Settings
        if not Settings.query.first():
            default_settings = Settings(
                opening_hour=12,
                closing_hour=4,
                price_per_hour=40000,
                discount_percentage=25,
                discount_start_hour=12,
                discount_end_hour=16,
                site_name='Padel House',
                phone='+9647501234567',
                email='info@padelhouse.iq',
                address='Duhok, Iraq'
            )
            db.session.add(default_settings)
            db.session.commit()

        # Stadiums
        from app.models.stadium import Stadium
        if not Stadium.query.first():
            stadium1 = Stadium(
                name='یاریگای ١',
                description='یاریگایەکی پڕۆفیشناڵ',
                location='دهۆک',
                price_per_hour=40000,
                is_active=True
            )
            stadium2 = Stadium(
                name='یاریگای ٢',
                description='یاریگایەکی باش',
                location='دهۆک',
                price_per_hour=40000,
                is_active=True
            )
            db.session.add(stadium1)
            db.session.add(stadium2)
            db.session.commit()
            print('✅ تم إنشاء الملاعب')

        # Tables
        from app.models.table import Table
        if not Table.query.first():
            for i in range(1, 11):
                table = Table(
                    name=f'طاولة {i}',
                    capacity=4,
                    is_active=True
                )
                db.session.add(table)
            db.session.commit()
            print('✅ تم إنشاء 10 طاولات')

        # Super Admin
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                email='admin@padelhouse.iq',
                is_admin=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print('✅ تم إنشاء Super Admin')
        else:
            print('ℹ️ Super Admin already exists')

        print(f"📦 Using database: {app.config['SQLALCHEMY_DATABASE_URI']}")

    return app