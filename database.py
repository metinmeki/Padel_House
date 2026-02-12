from app import db
from app.models.user import User

user = User.query.filter_by(username='your_username').first()
print(f"Current role: {user.role}")

# If not super_admin, fix it:
if user.role != 'super_admin':
    user.role = 'super_admin'
    user.sync_role_flags()
    db.session.commit()
    print("✅ Updated to super_admin")