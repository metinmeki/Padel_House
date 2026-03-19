from datetime import datetime
from app import db


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
    original_price = db.Column(db.Float, nullable=False, default=0)
    discount_percentage = db.Column(db.Integer, default=0)
    discount_amount = db.Column(db.Float, default=0)
    final_price = db.Column(db.Float, nullable=False, default=0)

    # Status: pending, pending_cancel, confirmed, completed, cancelled
    status = db.Column(db.String(20), default='pending')

    # External integration fields (Tapane)
    source = db.Column(db.String(20), nullable=False, default='website')  # website | tapane
    external_booking_id = db.Column(db.String(120), nullable=True, index=True)
    external_status = db.Column(db.String(50), nullable=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)

    # Google Sheets sync tracking
    sheet_sent = db.Column(db.Boolean, default=False)
    sheet_sent_at = db.Column(db.DateTime, nullable=True)
    sheet_last_error = db.Column(db.Text, nullable=True)

    # Notes and rejection reason
    notes = db.Column(db.Text)
    rejection_reason = db.Column(db.String(255))

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed_at = db.Column(db.DateTime)
    confirmed_by = db.Column(db.Integer, db.ForeignKey('user.id'))

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
            'source': self.source,
            'external_booking_id': self.external_booking_id,
            'external_status': self.external_status,
            'last_synced_at': str(self.last_synced_at) if self.last_synced_at else None,
            'notes': self.notes,
            'rejection_reason': self.rejection_reason,
            'created_at': str(self.created_at) if self.created_at else None,
            'confirmed_at': str(self.confirmed_at) if self.confirmed_at else None,
            'sheet_sent': bool(self.sheet_sent),
            'sheet_sent_at': str(self.sheet_sent_at) if self.sheet_sent_at else None,
            'sheet_last_error': self.sheet_last_error
        }

    def get_status_badge(self):
        badges = {
            'pending': 'badge-pending',
            'pending_cancel': 'badge-warning',
            'confirmed': 'badge-confirmed',
            'completed': 'badge-completed',
            'cancelled': 'badge-cancelled'
        }
        return badges.get(self.status, 'badge-secondary')

    def get_status_text(self, lang='ar'):
        texts = {
            'pending': {
                'ar': 'قيد الانتظار',
                'ku': 'چاوەڕوانی',
                'en': 'Pending'
            },
            'pending_cancel': {
                'ar': 'طلب إلغاء',
                'ku': 'داواکاری هەڵوەشاندنەوە',
                'en': 'Cancel Request'
            },
            'confirmed': {
                'ar': 'مؤكد',
                'ku': 'پشتڕاستکراوە',
                'en': 'Confirmed'
            },
            'completed': {
                'ar': 'مكتمل',
                'ku': 'تەواوبوو',
                'en': 'Completed'
            },
            'cancelled': {
                'ar': 'ملغي',
                'ku': 'هەڵوەشێندراوە',
                'en': 'Cancelled'
            }
        }
        return texts.get(self.status, {}).get(lang, self.status)