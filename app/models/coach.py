from datetime import datetime
from app import db


class Coach(db.Model):
    __tablename__ = 'coach'

    STATUS_AVAILABLE = 'available'
    STATUS_COMING_SOON = 'coming_soon'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    image = db.Column(db.String(255), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default=STATUS_AVAILABLE)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    training_requests = db.relationship(
        'CoachTrainingRequest',
        backref='coach',
        lazy=True,
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<Coach {self.id} - {self.name}>'

    def is_available(self):
        return self.status == self.STATUS_AVAILABLE

    def is_coming_soon(self):
        return self.status == self.STATUS_COMING_SOON

    def get_status_text(self, lang='ar'):
        texts = {
            self.STATUS_AVAILABLE: {
                'ar': 'متاح',
                'ku': 'بەردەستە',
                'en': 'Available'
            },
            self.STATUS_COMING_SOON: {
                'ar': 'قريباً',
                'ku': 'بەمزووانە',
                'en': 'Coming Soon'
            }
        }
        return texts.get(self.status, {}).get(lang, self.status)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'image': self.image,
            'bio': self.bio,
            'status': self.status,
            'status_text_ar': self.get_status_text('ar'),
            'status_text_ku': self.get_status_text('ku'),
            'status_text_en': self.get_status_text('en'),
            'is_active': self.is_active,
            'created_at': str(self.created_at) if self.created_at else None
        }