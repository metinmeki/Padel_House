from app import db
from datetime import datetime


class POSSession(db.Model):
    __tablename__ = 'pos_session'

    id = db.Column(db.Integer, primary_key=True)

    # نوع الجلسة
    session_type = db.Column(db.String(20), nullable=False)  # stadium, table, takeaway

    # الربط (واحد منهم فقط)
    stadium_id = db.Column(db.Integer, db.ForeignKey('stadium.id'), nullable=True)
    table_id = db.Column(db.Integer, db.ForeignKey('table.id'), nullable=True)

    # معلومات الزبون
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))

    # الوقت
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime, nullable=True)

    # الحالة والدفع
    status = db.Column(db.String(20), default='active')  # active, closed, paid
    payment_method = db.Column(db.String(20))  # cash, card
    total_amount = db.Column(db.Float, default=0)

    # ملاحظات
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    stadium = db.relationship('Stadium', backref='pos_sessions')
    table = db.relationship('Table', backref='pos_sessions')
    orders = db.relationship('POSOrder', backref='session', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<POSSession {self.id} - {self.session_type}>'

    def get_location_name(self):
        if self.session_type == 'stadium' and self.stadium:
            return self.stadium.name
        elif self.session_type == 'table' and self.table:
            return self.table.name
        return 'بيع سريع'

    def calculate_total(self):
        total = 0
        for order in self.orders:
            total += order.total_price
        self.total_amount = total
        return total

    def to_dict(self):
        return {
            'id': self.id,
            'session_type': self.session_type,
            'location_name': self.get_location_name(),
            'customer_name': self.customer_name,
            'start_time': str(self.start_time),
            'status': self.status,
            'total_amount': self.total_amount,
            'orders_count': len(self.orders)
        }