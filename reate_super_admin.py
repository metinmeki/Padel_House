from app import create_app, db
from app.models.user import User

app = create_app()

with app.app_context():
    print("=" * 50)
    print("   Padel House - Create Super Admin")
    print("=" * 50)

    username = input("Enter username: ").strip()
    email = input("Enter email: ").strip()
    password = input("Enter password: ").strip()

    if User.query.filter_by(username=username).first():
        print(f"\n❌ Username already exists!")
        exit()

    if User.query.filter_by(email=email).first():
        print(f"\n❌ Email already exists!")
        exit()

    user = User(
        username=username,
        email=email,
        role=User.ROLE_SUPER_ADMIN,
    )
    user.set_password(password)
    user.sync_role_flags()

    db.session.add(user)
    db.session.commit()

    print("\n✅ Super Admin created successfully!")
    print(f"   Username : {user.username}")
    print(f"   Email    : {user.email}")
    print(f"   Role     : {user.role}")
    print("=" * 50)