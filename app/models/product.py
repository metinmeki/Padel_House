from app import db
from datetime import datetime


class Product(db.Model):
    __tablename__ = 'product'

    id = db.Column(db.Integer, primary_key=True)

    # Multilingual names
    name_ku = db.Column(db.String(100), nullable=False)
    name_ar = db.Column(db.String(100))
    name_en = db.Column(db.String(100))

    # Multilingual descriptions
    description_ku = db.Column(db.Text)
    description_ar = db.Column(db.Text)
    description_en = db.Column(db.Text)

    # Product details
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    price = db.Column(db.Integer, nullable=False)
    stock = db.Column(db.Integer, default=0)
    image = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)

    # يظهر بالموقع أو POS
    show_in_website = db.Column(db.Boolean, default=True)
    show_in_pos = db.Column(db.Boolean, default=True)

    # باركود
    barcode = db.Column(db.String(50), unique=True, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now)

    # Relationship
    category = db.relationship('Category', back_populates='products')
    def __repr__(self):
        return f'<Product {self.name_ku}>'

    def get_name(self, lang='ku'):
        names = {
            'ku': self.name_ku,
            'ar': self.name_ar or self.name_ku,
            'en': self.name_en or self.name_ku
        }
        return names.get(lang, self.name_ku)

    def get_description(self, lang='ku'):
        descriptions = {
            'ku': self.description_ku,
            'ar': self.description_ar or self.description_ku,
            'en': self.description_en or self.description_ku
        }
        return descriptions.get(lang, self.description_ku)

    def to_dict(self):
        return {
            'id': self.id,
            'name_ku': self.name_ku,
            'name_ar': self.name_ar,
            'name_en': self.name_en,
            'category_id': self.category_id,
            'price': self.price,
            'stock': self.stock,
            'image': self.image,
            'is_active': self.is_active,
            'show_in_website': self.show_in_website,
            'show_in_pos': self.show_in_pos,
            'barcode': self.barcode
        }