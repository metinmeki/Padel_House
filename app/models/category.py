# app/models/category.py
from app import db
from datetime import datetime


class Category(db.Model):
    __tablename__ = 'category'

    id = db.Column(db.Integer, primary_key=True)
    
    # Multilingual names
    name_ku = db.Column(db.String(100), nullable=False)
    name_ar = db.Column(db.String(100))
    name_en = db.Column(db.String(100))
    
    # Multilingual descriptions
    description_ku = db.Column(db.Text)
    description_ar = db.Column(db.Text)
    description_en = db.Column(db.Text)
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    products = db.relationship('Product', backref='category', lazy=True)

    def __repr__(self):
        return f'<Category {self.name_ku}>'

    def get_name(self, lang='ku'):
        """Get name in specified language"""
        names = {
            'ku': self.name_ku,
            'ar': self.name_ar or self.name_ku,
            'en': self.name_en or self.name_ku
        }
        return names.get(lang, self.name_ku)

    def to_dict(self):
        return {
            'id': self.id,
            'name_ku': self.name_ku,
            'name_ar': self.name_ar,
            'name_en': self.name_en,
            'is_active': self.is_active
        }
