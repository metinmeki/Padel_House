# app/translations.py
# Kurdish (Sorani) - Arabic - English translations

TRANSLATIONS = {
    'ku': {  # Kurdish (Sorani) - Default
        # General
        'site_name': 'پادڵ هاوس',
        'home': 'سەرەتا',
        'booking': 'حجزکردن',
        'store': 'فرۆشگا',
        'about': 'دەربارەی ئێمە',
        'contact': 'پەیوەندی',
        'login': 'چوونەژوورەوە',
        'logout': 'چوونەدەرەوە',
        'admin': 'بەڕێوەبەر',
        'dashboard': 'داشبۆرد',

        # Booking
        'book_now': 'ئێستا حجز بکە',
        'select_stadium': 'یاریگا هەڵبژێرە',
        'select_date': 'بەروار هەڵبژێرە',
        'select_time': 'کات هەڵبژێرە',
        'available': 'بەردەستە',
        'booked': 'حجزکراوە',
        'discount': 'داشکاندن',
        'price': 'نرخ',
        'total': 'کۆی گشتی',
        'confirm_booking': 'حجزکردن دڵنیابکەوە',
        'booking_success': 'حجزکردن سەرکەوتوو بوو',
        'booking_failed': 'حجزکردن سەرنەکەوت',
        'per_hour': 'بۆ کاتژمێرێک',
        'hour': 'کاتژمێر',
        'duration': 'ماوە',

        # Customer Info
        'customer_name': 'ناو',
        'customer_phone': 'ژمارەی مۆبایل',
        'customer_email': 'ئیمەیڵ',
        'your_name': 'ناوی تۆ',
        'your_phone': 'ژمارەی مۆبایلت',
        'your_email': 'ئیمەیڵەکەت',

        # Store
        'products': 'بەرهەمەکان',
        'add_to_cart': 'زیادکردن بۆ سەبەتە',
        'cart': 'سەبەتەی کڕین',
        'checkout': 'تەواوکردنی کڕین',
        'empty_cart': 'سەبەتە بەتاڵە',
        'continue_shopping': 'بەردەوامبوون لە کڕین',
        'place_order': 'ناردنی داواکاری',
        'order_success': 'داواکاری سەرکەوتوو بوو',
        'out_of_stock': 'نەماوە',
        'in_stock': 'بەردەستە',
        'quantity': 'بڕ',
        'remove': 'سڕینەوە',

        # Categories
        'all': 'هەموو',
        'rackets': 'ڕاکێتەکان',
        'balls': 'تۆپەکان',
        'clothes': 'جلەکان',
        'accessories': 'پێداویستییەکان',

        # Delivery
        'delivery_method': 'شێوازی گەیاندن',
        'pickup': 'وەرگرتن لە فرۆشگا',
        'delivery': 'گەیاندن بۆ ماڵ',
        'address': 'ناونیشان',
        'area': 'ناوچە',
        'notes': 'تێبینی',

        # Time & Date
        'today': 'ئەمڕۆ',
        'tomorrow': 'سبەینێ',
        'hours': 'کاتژمێر',
        'minutes': 'خولەک',
        'am': 'بەیانی',
        'pm': 'ئێوارە',

        # Status
        'pending': 'چاوەڕوان',
        'confirmed': 'دڵنیاکراوە',
        'completed': 'تەواوبوو',
        'cancelled': 'هەڵوەشێنرا',
        'delivered': 'گەیەندرا',

        # Footer
        'working_hours': 'کاتەکانی کارکردن',
        'quick_links': 'لینکە خێراکان',
        'contact_us': 'پەیوەندیمان پێوە بکە',
        'follow_us': 'شوێنمان بکەوە',
        'all_rights': 'هەموو مافەکان پارێزراون',

        # Stadium Names
        'stadium_1': 'یاریگای ١',
        'stadium_2': 'یاریگای ٢',

        # Location
        'duhok': 'دهۆک',
        'iraq': 'عێراق',

        # Messages
        'welcome': 'بەخێربێیت بۆ پادڵ هاوس',
        'best_courts': 'باشترین یاریگاکانی پادڵ لە دهۆک',
        'book_your_game': 'یاریەکەت حجز بکە',
        'discover_store': 'فرۆشگاکەمان ببینە',
        'no_bookings': 'هیچ حجزێک نییە',
        'no_products': 'هیچ بەرهەمێک نییە',
        'no_orders': 'هیچ داواکاریەک نییە',

        # Admin
        'settings': 'ڕێکخستنەکان',
        'users': 'بەکارهێنەران',
        'bookings': 'حجزەکان',
        'orders': 'داواکاریەکان',
        'stadiums': 'یاریگاکان',
        'reports': 'ڕاپۆرتەکان',
        'save': 'پاشەکەوتکردن',
        'edit': 'دەستکاریکردن',
        'delete': 'سڕینەوە',
        'add': 'زیادکردن',
        'search': 'گەڕان',
        'filter': 'فلتەر',
        'actions': 'کردارەکان',
        'view': 'بینین',
        'back': 'گەڕانەوە',
        'cancel': 'پاشگەزبوونەوە',
        'confirm': 'دڵنیاکردنەوە',
        'yes': 'بەڵێ',
        'no': 'نەخێر',

        # Currency
        'iqd': 'د.ع',
        'currency': 'دینار',
    },

    'ar': {  # Arabic
        # General
        'site_name': 'بادل هاوس',
        'home': 'الرئيسية',
        'booking': 'الحجز',
        'store': 'المتجر',
        'about': 'من نحن',
        'contact': 'اتصل بنا',
        'login': 'تسجيل الدخول',
        'logout': 'تسجيل الخروج',
        'admin': 'الإدارة',
        'dashboard': 'لوحة التحكم',

        # Booking
        'book_now': 'احجز الآن',
        'select_stadium': 'اختر الملعب',
        'select_date': 'اختر التاريخ',
        'select_time': 'اختر الوقت',
        'available': 'متاح',
        'booked': 'محجوز',
        'discount': 'خصم',
        'price': 'السعر',
        'total': 'المجموع',
        'confirm_booking': 'تأكيد الحجز',
        'booking_success': 'تم الحجز بنجاح',
        'booking_failed': 'فشل الحجز',
        'per_hour': 'للساعة',
        'hour': 'ساعة',
        'duration': 'المدة',

        # Customer Info
        'customer_name': 'الاسم',
        'customer_phone': 'رقم الهاتف',
        'customer_email': 'البريد الإلكتروني',
        'your_name': 'اسمك',
        'your_phone': 'رقم هاتفك',
        'your_email': 'بريدك الإلكتروني',

        # Store
        'products': 'المنتجات',
        'add_to_cart': 'أضف للسلة',
        'cart': 'سلة التسوق',
        'checkout': 'إتمام الشراء',
        'empty_cart': 'السلة فارغة',
        'continue_shopping': 'متابعة التسوق',
        'place_order': 'تأكيد الطلب',
        'order_success': 'تم الطلب بنجاح',
        'out_of_stock': 'نفذت الكمية',
        'in_stock': 'متوفر',
        'quantity': 'الكمية',
        'remove': 'حذف',

        # Categories
        'all': 'الكل',
        'rackets': 'المضارب',
        'balls': 'الكرات',
        'clothes': 'الملابس',
        'accessories': 'الإكسسوارات',

        # Delivery
        'delivery_method': 'طريقة التوصيل',
        'pickup': 'استلام من المتجر',
        'delivery': 'توصيل للمنزل',
        'address': 'العنوان',
        'area': 'المنطقة',
        'notes': 'ملاحظات',

        # Time & Date
        'today': 'اليوم',
        'tomorrow': 'غداً',
        'hours': 'ساعات',
        'minutes': 'دقائق',
        'am': 'صباحاً',
        'pm': 'مساءً',

        # Status
        'pending': 'قيد الانتظار',
        'confirmed': 'مؤكد',
        'completed': 'مكتمل',
        'cancelled': 'ملغي',
        'delivered': 'تم التوصيل',

        # Footer
        'working_hours': 'ساعات العمل',
        'quick_links': 'روابط سريعة',
        'contact_us': 'اتصل بنا',
        'follow_us': 'تابعنا',
        'all_rights': 'جميع الحقوق محفوظة',

        # Stadium Names
        'stadium_1': 'ملعب ١',
        'stadium_2': 'ملعب ٢',

        # Location
        'duhok': 'دهوك',
        'iraq': 'العراق',

        # Messages
        'welcome': 'مرحباً بك في بادل هاوس',
        'best_courts': 'أفضل ملاعب البادل في دهوك',
        'book_your_game': 'احجز مباراتك',
        'discover_store': 'اكتشف متجرنا',
        'no_bookings': 'لا توجد حجوزات',
        'no_products': 'لا توجد منتجات',
        'no_orders': 'لا توجد طلبات',

        # Admin
        'settings': 'الإعدادات',
        'users': 'المستخدمين',
        'bookings': 'الحجوزات',
        'orders': 'الطلبات',
        'stadiums': 'الملاعب',
        'reports': 'التقارير',
        'save': 'حفظ',
        'edit': 'تعديل',
        'delete': 'حذف',
        'add': 'إضافة',
        'search': 'بحث',
        'filter': 'تصفية',
        'actions': 'الإجراءات',
        'view': 'عرض',
        'back': 'رجوع',
        'cancel': 'إلغاء',
        'confirm': 'تأكيد',
        'yes': 'نعم',
        'no': 'لا',

        # Currency
        'iqd': 'د.ع',
        'currency': 'دينار',
    },

    'en': {  # English
        # General
        'site_name': 'Padel House',
        'home': 'Home',
        'booking': 'Booking',
        'store': 'Store',
        'about': 'About Us',
        'contact': 'Contact',
        'login': 'Login',
        'logout': 'Logout',
        'admin': 'Admin',
        'dashboard': 'Dashboard',

        # Booking
        'book_now': 'Book Now',
        'select_stadium': 'Select Stadium',
        'select_date': 'Select Date',
        'select_time': 'Select Time',
        'available': 'Available',
        'booked': 'Booked',
        'discount': 'Discount',
        'price': 'Price',
        'total': 'Total',
        'confirm_booking': 'Confirm Booking',
        'booking_success': 'Booking Successful',
        'booking_failed': 'Booking Failed',
        'per_hour': 'per hour',
        'hour': 'hour',
        'duration': 'Duration',

        # Customer Info
        'customer_name': 'Name',
        'customer_phone': 'Phone Number',
        'customer_email': 'Email',
        'your_name': 'Your Name',
        'your_phone': 'Your Phone',
        'your_email': 'Your Email',

        # Store
        'products': 'Products',
        'add_to_cart': 'Add to Cart',
        'cart': 'Shopping Cart',
        'checkout': 'Checkout',
        'empty_cart': 'Cart is Empty',
        'continue_shopping': 'Continue Shopping',
        'place_order': 'Place Order',
        'order_success': 'Order Successful',
        'out_of_stock': 'Out of Stock',
        'in_stock': 'In Stock',
        'quantity': 'Quantity',
        'remove': 'Remove',

        # Categories
        'all': 'All',
        'rackets': 'Rackets',
        'balls': 'Balls',
        'clothes': 'Clothes',
        'accessories': 'Accessories',

        # Delivery
        'delivery_method': 'Delivery Method',
        'pickup': 'Store Pickup',
        'delivery': 'Home Delivery',
        'address': 'Address',
        'area': 'Area',
        'notes': 'Notes',

        # Time & Date
        'today': 'Today',
        'tomorrow': 'Tomorrow',
        'hours': 'Hours',
        'minutes': 'Minutes',
        'am': 'AM',
        'pm': 'PM',

        # Status
        'pending': 'Pending',
        'confirmed': 'Confirmed',
        'completed': 'Completed',
        'cancelled': 'Cancelled',
        'delivered': 'Delivered',

        # Footer
        'working_hours': 'Working Hours',
        'quick_links': 'Quick Links',
        'contact_us': 'Contact Us',
        'follow_us': 'Follow Us',
        'all_rights': 'All Rights Reserved',

        # Stadium Names
        'stadium_1': 'Stadium 1',
        'stadium_2': 'Stadium 2',

        # Location
        'duhok': 'Duhok',
        'iraq': 'Iraq',

        # Messages
        'welcome': 'Welcome to Padel House',
        'best_courts': 'Best Padel Courts in Duhok',
        'book_your_game': 'Book Your Game',
        'discover_store': 'Discover Our Store',
        'no_bookings': 'No bookings found',
        'no_products': 'No products found',
        'no_orders': 'No orders found',

        # Admin
        'settings': 'Settings',
        'users': 'Users',
        'bookings': 'Bookings',
        'orders': 'Orders',
        'stadiums': 'Stadiums',
        'reports': 'Reports',
        'save': 'Save',
        'edit': 'Edit',
        'delete': 'Delete',
        'add': 'Add',
        'search': 'Search',
        'filter': 'Filter',
        'actions': 'Actions',
        'view': 'View',
        'back': 'Back',
        'cancel': 'Cancel',
        'confirm': 'Confirm',
        'yes': 'Yes',
        'no': 'No',

        # Currency
        'iqd': 'IQD',
        'currency': 'Dinar',
    }
}


def get_translation(key, lang='ku'):
    """Get translation for a key in specified language"""
    if lang not in TRANSLATIONS:
        lang = 'ku'  # Default to Kurdish
    return TRANSLATIONS.get(lang, {}).get(key, key)


def get_all_translations(lang='ku'):
    """Get all translations for a language"""
    if lang not in TRANSLATIONS:
        lang = 'ku'
    return TRANSLATIONS.get(lang, {})