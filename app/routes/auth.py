from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User

auth_bp = Blueprint('auth', __name__)


# ===== LOGIN =====
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login page"""
    if current_user.is_authenticated:
        # ✅ FIX: Check if they can access dashboard first
        if current_user.role == 'super_admin' or getattr(current_user, 'can_access_dashboard', False):
            return redirect(url_for('admin.dashboard'))
        elif getattr(current_user, 'can_manage_bookings', False):
            return redirect(url_for('admin.manage_bookings'))
        else:
            return redirect(url_for('admin.manage_products'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user, remember=bool(remember))

            # Check if there's a 'next' page requested
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)

            # ✅ SMART REDIRECT: Send user to first page they have access to
            # Super admin always goes to dashboard
            if user.role == 'super_admin':
                return redirect(url_for('admin.dashboard'))

            # Regular admin: redirect based on permissions
            if getattr(user, 'can_access_dashboard', False):
                return redirect(url_for('admin.dashboard'))
            elif getattr(user, 'can_manage_bookings', False):
                return redirect(url_for('admin.manage_bookings'))
            elif getattr(user, 'can_manage_products', False):
                return redirect(url_for('admin.manage_products'))
            elif getattr(user, 'can_manage_orders', False):
                return redirect(url_for('admin.manage_orders'))
            elif getattr(user, 'can_manage_stadiums', False):
                return redirect(url_for('admin.manage_stadiums'))
            elif getattr(user, 'can_view_reports', False):
                return redirect(url_for('admin.reports'))
            elif getattr(user, 'can_manage_settings', False):
                return redirect(url_for('admin.manage_settings'))
            else:
                # User has no permissions at all - logout and show error
                logout_user()
                flash('ليس لديك أي صلاحيات للوصول إلى لوحة التحكم', 'danger')
                return redirect(url_for('auth.login'))
        else:
            flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')

    return render_template('auth/login.html')


# ===== LOGOUT =====
@auth_bp.route('/logout')
@login_required
def logout():
    """User logout"""
    logout_user()
    flash('تم تسجيل الخروج بنجاح', 'success')
    return redirect(url_for('auth.login'))