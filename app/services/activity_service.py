# app/services/activity_service.py
from datetime import datetime
from flask_login import current_user
from app import db
from app.models.activity_log import ActivityLog

def log_activity(
    action: str,
    entity_type: str = None,
    entity_id: int = None,
    title: str = None,
    note: str = None,
    amount: int = None,
    payment_method: str = None,
    user_id: int = None
):
    """
    Save activity log row.
    If user_id not provided -> use current_user (if authenticated).
    """
    try:
        uid = user_id
        if uid is None:
            try:
                if current_user and getattr(current_user, "is_authenticated", False):
                    uid = current_user.id
            except Exception:
                uid = None

        row = ActivityLog(
            user_id=uid,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            note=note,
            amount=amount,
            payment_method=payment_method,
            created_at=datetime.utcnow()
        )

        db.session.add(row)
        db.session.commit()
        return True

    except Exception as e:
        db.session.rollback()
        print("❌ Activity log error:", e)
        return False