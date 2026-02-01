# app/models/settings.py
from app import db
from datetime import datetime


class Settings(db.Model):
    __tablename__ = 'settings'

    id = db.Column(db.Integer, primary_key=True)
    
    # Business Hours
    opening_hour = db.Column(db.Integer, default=12)  # 12 PM
    closing_hour = db.Column(db.Integer, default=4)   # 4 AM next day
    
    # Pricing
    price_per_hour = db.Column(db.Float, default=80000)
    
    # Discount Settings
    discount_percentage = db.Column(db.Integer, default=25)
    discount_start_hour = db.Column(db.Integer, default=12)
    discount_end_hour = db.Column(db.Integer, default=16)
    
    # Site Info
    site_name = db.Column(db.String(100), default='Padel House')
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    address = db.Column(db.Text)
    
    # Social Media
    facebook_url = db.Column(db.String(200))
    instagram_url = db.Column(db.String(200))
    twitter_url = db.Column(db.String(200))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Settings {self.site_name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'opening_hour': self.opening_hour,
            'closing_hour': self.closing_hour,
            'price_per_hour': self.price_per_hour,
            'discount_percentage': self.discount_percentage,
            'discount_start_hour': self.discount_start_hour,
            'discount_end_hour': self.discount_end_hour,
            'site_name': self.site_name,
            'phone': self.phone,
            'email': self.email,
            'address': self.address
        }
