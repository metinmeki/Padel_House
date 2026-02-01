import requests
import json

GOOGLE_SHEET_URL = "https://script.google.com/macros/s/AKfycbyQOn497BmMvIqTfItKRc4HoENwuyq3GgZLbb2_eEMeiCkm5uS3uorynKf4jgwf7vI1/exec"


def send_booking_to_sheet(booking):
    """Send booking data to Google Sheets"""
    try:
        data = {
            "type": "booking",
            "customer_name": booking.customer_name,
            "customer_phone": booking.customer_phone,
            "stadium": booking.stadium.name if booking.stadium else "غير محدد",
            "date": booking.date.strftime('%Y-%m-%d') if booking.date else "",
            "hours": f"{booking.start_time.strftime('%H:%M')}-{booking.end_time.strftime('%H:%M')}",
            "price": booking.final_price,
            "status": booking.status
        }

        response = requests.post(
            GOOGLE_SHEET_URL,
            data=json.dumps(data),
            headers={
                'Content-Type': 'text/plain;charset=utf-8',
            },
            timeout=30
        )

        print(f"✅ Booking sent to Google Sheets: {response.status_code}")
        return True

    except Exception as e:
        print(f"❌ Error sending booking to Google Sheets: {e}")
        return False


def send_order_to_sheet(order, items_text):
    """Send order data to Google Sheets"""
    try:
        data = {
            "type": "order",
            "customer_name": order.customer_name,
            "customer_phone": order.customer_phone,
            "products": items_text,
            "total": order.total_price,
            "address": order.customer_address or "استلام من المتجر",
            "status": order.status
        }

        response = requests.post(
            GOOGLE_SHEET_URL,
            data=json.dumps(data),
            headers={
                'Content-Type': 'text/plain;charset=utf-8',
            },
            timeout=30
        )

        print(f"✅ Order sent to Google Sheets: {response.status_code}")
        return True

    except Exception as e:
        print(f"❌ Error sending order to Google Sheets: {e}")
        return False