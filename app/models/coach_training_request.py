from datetime import datetime
from app import db


class CoachTrainingRequest(db.Model):
    __tablename__ = 'coach_training_requests'

    id = db.Column(db.Integer, primary_key=True)

    coach_id = db.Column(db.Integer, db.ForeignKey('coach.id'), nullable=False)

    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    level = db.Column(db.String(50), nullable=True)
    note = db.Column(db.Text, nullable=True)

    package_name = db.Column(db.String(100), nullable=True)
    package_price = db.Column(db.Integer, default=0)
    package_sessions = db.Column(db.Integer, default=0)

    status = db.Column(db.String(20), default='new')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<CoachTrainingRequest {self.id} - {self.full_name}>'