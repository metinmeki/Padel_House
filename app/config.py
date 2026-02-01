import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'default-secret-key')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///padel_house.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Padel House Settings
    PRICE_PER_PLAYER = 10000  # IQD
    DISCOUNT_PERCENTAGE = 25
    DISCOUNT_START_HOUR = 12
    DISCOUNT_END_HOUR = 16
    OPENING_HOUR = 12
    CLOSING_HOUR = 4  # 4 AM next day