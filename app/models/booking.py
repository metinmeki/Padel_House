# booking.py - Updated with Pending/Approval System
from app import db
from datetime import datetime


class Booking(db.Model):
    __tablename__ = 'booking'

    id = db.Column(db.Integer, primary_key=True)
    stadium_id = db.Column(db.Integer, db.ForeignKey('stadium.id'), nullable=False)

    # Customer Info
    customer_name = db.Column(db.String(100), nullable=False)
    customer_phone = db.Column(db.String(20), nullable=False)
    customer_email = db.Column(db.String(100))

    # Booking Details
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    duration_hours = db.Column(db.Integer, nullable=False)

    # Pricing
    original_price = db.Column(db.Float, nullable=False)
    discount_percentage = db.Column(db.Integer, default=0)
    discount_amount = db.Column(db.Float, default=0)
    final_price = db.Column(db.Float, nullable=False)

    # Status: pending, confirmed, completed, cancelled
    status = db.Column(db.String(20), default='pending')

    # Notes and rejection reason
    notes = db.Column(db.Text)
    rejection_reason = db.Column(db.String(255))

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed_at = db.Column(db.DateTime)  # When admin approved
    confirmed_by = db.Column(db.Integer, db.ForeignKey('user.id'))  # Admin who approved

    def __repr__(self):
        return f'<Booking {self.id} - {self.customer_name} - {self.date}>'

    def to_dict(self):
        return {
            'id': self.id,
            'stadium_name': self.stadium.name if self.stadium else 'N/A',
            'stadium_id': self.stadium_id,
            'customer_name': self.customer_name,
            'customer_phone': self.customer_phone,
            'customer_email': self.customer_email,
            'date': str(self.date),
            'start_time': str(self.start_time) if self.start_time else None,
            'end_time': str(self.end_time) if self.end_time else None,
            'duration_hours': self.duration_hours,
            'original_price': self.original_price,
            'discount_percentage': self.discount_percentage,
            'discount_amount': self.discount_amount,
            'final_price': self.final_price,
            'status': self.status,
            'notes': self.notes,
            'rejection_reason': self.rejection_reason,
            'created_at': str(self.created_at) if self.created_at else None,
            'confirmed_at': str(self.confirmed_at) if self.confirmed_at else None
        }

    def get_status_badge(self):
        """Return Bootstrap badge class based on status"""
        badges = {
            'pending': 'badge-pending',
            'confirmed': 'badge-confirmed',
            'completed': 'badge-completed',
            'cancelled': 'badge-cancelled'
        }
        return badges.get(self.status, 'badge-secondary')

    def get_status_text(self, lang='ar'):
        """Return status text in specified language"""
        texts = {
            'pending': {'ar': 'قيد الانتظار', 'ku': 'چاوەڕوانی', 'en': 'Pending'},
            'confirmed': {'ar': 'مؤكد', 'ku': 'پشتڕاستکراوە', 'en': 'Confirmed'},
            'completed': {'ar': 'مكتمل', 'ku': 'تەواوبوو', 'en': 'Completed'},
            'cancelled': {'ar': 'ملغي', 'ku': 'هەڵوەشێندراوە', 'en': 'Cancelled'}
        }
        return texts.get(self.status, {}).get(lang, self.status)
