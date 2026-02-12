# app/services/notify.py
from app import db
from app.models.notification import Notification
from app.models.user import User


# app/services/notify.py
from app import db
from app.models.notification import Notification
from app.models.user import User

def notify_admins(title, message=None, url=None, ntype="info"):
    admins = User.query.filter(User.role.in_(["admin", "super_admin"])).all()

    if not admins:
        return False

    for admin in admins:
        n = Notification(
            user_id=admin.id,
            type=ntype,
            title=title,
            message=message,
            url=url,
            is_read=False
        )
        db.session.add(n)

    db.session.commit()
    return True