from app import create_app

app = create_app()


# Create Super Admin
def create_super_admin():
    with app.app_context():
        from app import db
        from app.models.user import User

        # Check if super admin exists
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@padelhouse.iq',
                role='super_admin'
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print('✅ Super Admin created!')
            print('   Username: admin')
            print('   Password: admin123')
        else:
            print('ℹ️ Super Admin already exists')


if __name__ == '__main__':
    create_super_admin()
    app.run(debug=True, port=5000)