import io
import os
from barcode import Code128
from barcode.writer import ImageWriter
from PIL import Image
from datetime import datetime


class BarcodeService:
    @staticmethod
    def generate_barcode(product_id, product_name):
        """
        Generate barcode for product
        Returns: barcode_value (string), image_bytes
        """
        # Create barcode value from product_id (pad to 12 digits)
        barcode_value = f"{product_id:012d}"

        # Generate barcode image
        code128 = Code128(barcode_value, writer=ImageWriter())
        buffer = io.BytesIO()
        code128.write(buffer)

        return barcode_value, buffer.getvalue()

    @staticmethod
    def save_barcode_image(product_id, product_name):
        """Save barcode as image file"""
        barcode_value, image_bytes = BarcodeService.generate_barcode(product_id, product_name)

        # Create barcodes directory if not exists
        barcode_dir = os.path.join('app', 'static', 'barcodes')
        os.makedirs(barcode_dir, exist_ok=True)

        # Save image
        filename = f"barcode_{product_id}.png"
        filepath = os.path.join(barcode_dir, filename)

        with open(filepath, 'wb') as f:
            f.write(image_bytes)

        return barcode_value, filename


class XPrinterService:
    """
    Xprinter ESC/POS Integration
    """

    @staticmethod
    def print_barcode_label(product_id, product_name, price, barcode_value):
        """
        Print barcode label to Xprinter
        """
        try:
            from escpos.printer import Usb, Network

            # USB Connection (find your Xprinter vendor/product ID)
            # On Windows: Device Manager > Printers > Properties > Hardware IDs
            # On Linux: lsusb

            # Try USB first (replace with your IDs)
            try:
                # Common Xprinter USB IDs
                printer = Usb(0x0416, 0x5011)  # Replace with your actual IDs
            except:
                # Try Network if USB fails
                printer = Network("192.168.1.100")  # Replace with your printer IP

            # Print label
            printer.set(align='center', text_type='B', width=2, height=2)
            printer.text(f"{product_name}\n")

            printer.set(align='center', text_type='normal')
            printer.text(f"Price: {price} IQD\n")

            # Print barcode
            printer.barcode(barcode_value, 'CODE128', height=50, width=2, pos='BELOW')

            printer.text("\n")
            printer.cut()

            return True, "Label printed successfully"

        except Exception as e:
            return False, f"Print error: {str(e)}"

    @staticmethod
    def find_printer_ids():
        """
        Helper function to find Xprinter USB IDs
        Run this once to find your printer
        """
        try:
            import usb.core

            devices = usb.core.find(find_all=True)
            printers = []

            for device in devices:
                if device.idVendor and device.idProduct:
                    printers.append({
                        'vendor_id': hex(device.idVendor),
                        'product_id': hex(device.idProduct),
                        'manufacturer': usb.util.get_string(device,
                                                            device.iManufacturer) if device.iManufacturer else 'Unknown',
                        'product': usb.util.get_string(device, device.iProduct) if device.iProduct else 'Unknown'
                    })

            return printers
        except Exception as e:
            return []