# app/__init__.py
from flask import Flask, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
import os
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()


def create_app(config_name='development'):
    app = Flask(__name__)

    if config_name == 'production':
        app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
            'DATABASE_URL',
            'sqlite:///padel_house.db'
        )
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///padel_house.db'

    app.config['SECRET_KEY'] = os.getenv(
        'SECRET_KEY',
        'dev-secret-key-change-in-production'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SESSION_PERMANENT'] = True

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'يرجى تسجيل الدخول أولاً'
    login_manager.login_message_category = 'warning'

    # Register Blueprints
    from app.routes.main import main_bp
    from app.routes.booking import booking_bp
    from app.routes.store import store_bp
    from app.routes.admin import admin_bp
    from app.routes.auth import auth_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(booking_bp, url_prefix='/booking')
    app.register_blueprint(store_bp, url_prefix='/store')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # User loader
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Language System
    from app.models.settings import Settings
    from app.translations import get_translation

    @app.context_processor
    def inject_globals():
        settings = Settings.query.first()
        current_lang = session.get('lang', 'ku')
        
        def t(key):
            return get_translation(key, current_lang)
        
        language_flags = {'ku': '🇮🇶', 'ar': '🇸🇦', 'en': '🇬🇧'}
        language_names = {'ku': 'کوردی', 'ar': 'العربية', 'en': 'English'}
        languages = ['ku', 'ar', 'en']
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

    # Database Init
    with app.app_context():
        db.create_all()

        if not Settings.query.first():
            default_settings = Settings(
                opening_hour=12,
                closing_hour=4,
                price_per_hour=80000,
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

        from app.models.stadium import Stadium
        if not Stadium.query.first():
            stadium1 = Stadium(
                name='یاریگای ١',
                description='یاریگایەکی پڕۆفیشناڵ',
                location='دهۆک',
                price_per_hour=80000,
                is_active=True
            )
            stadium2 = Stadium(
                name='یاریگای ٢',
                description='یاریگایەکی باش',
                location='دهۆک',
                price_per_hour=80000,
                is_active=True
            )
            db.session.add(stadium1)
            db.session.add(stadium2)
            db.session.commit()

        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                email='admin@padelhouse.iq',
                role='super_admin'
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()

    return app