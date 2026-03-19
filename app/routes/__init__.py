from flask import Flask
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
        app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///padel_house.db')
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///padel_house.db'

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Login manager configuration
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'يرجى تسجيل الدخول أولاً'
    login_manager.login_message_category = 'warning'

    from app.routes.main import main_bp
    from app.routes.booking import booking_bp
    from app.routes.store import store_bp
    from app.routes.admin import admin_bp
    from app.routes.auth import auth_bp
    from app.routes.tapane import tapane_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(booking_bp, url_prefix='/booking')
    app.register_blueprint(store_bp, url_prefix='/store')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(tapane_bp, url_prefix='/tapane')

    with app.app_context():
        db.create_all()

        from app.models.settings import Settings
        if not Settings.query.first():
            default_settings = Settings(
                opening_hour=12,
                closing_hour=4,
                price_per_hour=50000,
                discount_percentage=25,
                discount_start_hour=12,
                discount_end_hour=16,
                site_name='Padel House',
                phone='+964123456789',
                email='info@padelhouse.com',
                address='Baghdad, Iraq'
            )
            db.session.add(default_settings)
            db.session.commit()

        from app.models.stadium import Stadium
        if not Stadium.query.first():
            stadium1 = Stadium(
                name='استاد النمر',
                description='ملعب احترافي مجهز بأحدث المعدات',
                location='منطقة الحريطة',
                price_per_hour=50000,
                is_active=True
            )
            stadium2 = Stadium(
                name='استاد الصقر',
                description='ملعب عالي الجودة مع إضاءة ممتازة',
                location='منطقة الكرادة',
                price_per_hour=50000,
                is_active=True
            )
            db.session.add(stadium1)
            db.session.add(stadium2)
            db.session.commit()

    # Load user for login_manager
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    return app