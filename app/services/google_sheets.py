# app/services/google_sheet.py
import json
import requests

GOOGLE_SHEET_URL = "https://script.google.com/macros/s/AKfycbyQOn497BmMvIqTfItKRc4HoENwuyq3GgZLbb2_eEMeiCkm5uS3uorynKf4jgwf7vI1/exec"


def send_booking_to_sheet(booking):
    """Send booking data to Google Sheets (call this AFTER admin approves)."""
    try:
        data = {
            "type": "booking",
            "customer_name": getattr(booking, "customer_name", "") or "",
            "customer_phone": getattr(booking, "customer_phone", "") or "",
            "stadium": booking.stadium.name if getattr(booking, "stadium", None) else "غير محدد",
            "date": booking.date.strftime('%Y-%m-%d') if getattr(booking, "date", None) else "",
            "hours": (
                f"{booking.start_time.strftime('%H:%M')}-{booking.end_time.strftime('%H:%M')}"
                if getattr(booking, "start_time", None) and getattr(booking, "end_time", None)
                else ""
            ),
            "price": float(getattr(booking, "final_price", 0) or 0),
            "status": getattr(booking, "status", "") or ""
        }

        response = requests.post(
            GOOGLE_SHEET_URL,
            data=json.dumps(data),
            headers={'Content-Type': 'text/plain;charset=utf-8'},
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
        delivery_method = (getattr(order, "delivery_method", "") or "").lower()

        if delivery_method == "delivery":
            area = getattr(order, "area", None)
            address = getattr(order, "address", None)

            if area and address:
                address_text = f"{area} - {address}"
            elif address:
                address_text = str(address)
            elif area:
                address_text = str(area)
            else:
                address_text = "عنوان غير متوفر"
        else:
            address_text = "استلام من المتجر"

        data = {
            "type": "order",
            "customer_name": getattr(order, "customer_name", "") or "",
            "customer_phone": getattr(order, "customer_phone", "") or "",
            "products": items_text or "",
            "total": float(getattr(order, "total_price", 0) or 0),
            "address": address_text,
            "status": getattr(order, "status", "") or ""
        }

        response = requests.post(
            GOOGLE_SHEET_URL,
            data=json.dumps(data),
            headers={'Content-Type': 'text/plain;charset=utf-8'},
            timeout=30
        )

        print(f"✅ Order sent to Google Sheets: {response.status_code}")
        return True

    except Exception as e:
        print(f"❌ Error sending order to Google Sheets: {e}")
        return False