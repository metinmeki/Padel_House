# run.py - Production Ready
from app import create_app
import os

# ✅ Create app instance
app = create_app()

if __name__ == '__main__':
    # ✅ PRODUCTION SETTINGS

    # Set DEBUG=False for production deployment
    # Set DEBUG=True only for local development

    # Get debug mode from environment variable (defaults to False for safety)
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    print("🚀 Starting Padel House Server...")
    print(f"📍 Mode: {'Development (DEBUG ON)' if debug_mode else 'Production (DEBUG OFF)'}")
    print(f"🌐 Server: http://0.0.0.0:5000")
    print("=" * 60)

    # ✅ For production: debug=False
    # ✅ For development: set FLASK_DEBUG=True in .env file
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=debug_mode
    )