// app/static/js/booking.js

class BookingSystem {
    constructor() {
        console.log('BookingSystem initialized');
        this.stadiumId = null;
        this.selectedDate = null;
        this.selectedHour = null;
        this.duration = 1;
        this.settings = {};
        this.stadium = null;
        this.init();
    }

    async init() {
        console.log('Initializing booking system...');
        this.loadSettings();
        this.attachEventListeners();
    }

    loadSettings() {
        const settingsElement = document.querySelector('[data-settings]');
        if (settingsElement) {
            try {
                this.settings = JSON.parse(settingsElement.dataset.settings);
                console.log('Settings loaded:', this.settings);
            } catch (e) {
                console.error('Error parsing settings:', e);
            }
        }
    }

    attachEventListeners() {
        console.log('Attaching event listeners...');

        // Stadium selector
        const stadiumTabs = document.querySelectorAll('.stadium-tab');
        console.log('Found', stadiumTabs.length, 'stadium tabs');

        stadiumTabs.forEach(tab => {
            tab.addEventListener('click', (e) => {
                console.log('Stadium clicked');
                e.preventDefault();
                this.selectStadium(tab);
            });
        });

        // Date picker
        const dateInput = document.getElementById('booking-date');
        if (dateInput) {
            dateInput.addEventListener('change', (e) => {
                console.log('Date changed:', e.target.value);
                this.selectDate(e);
            });
        }

        // Duration selector
        const durationSelect = document.getElementById('duration');
        if (durationSelect) {
            durationSelect.addEventListener('change', (e) => {
                this.duration = parseInt(e.target.value);
                console.log('Duration changed:', this.duration);
                if (this.selectedHour !== null) {
                    this.updateBookingSummary();
                }
            });
        }

        // Submit form
        const bookingForm = document.getElementById('booking-form');
        if (bookingForm) {
            bookingForm.addEventListener('submit', (e) => {
                console.log('Form submitted');
                this.submitBooking(e);
            });
        }
    }

    selectStadium(tab) {
        this.stadiumId = parseInt(tab.dataset.stadiumId);
        this.stadium = {
            id: this.stadiumId,
            name: tab.dataset.stadiumName,
            price: parseFloat(tab.dataset.price)
        };

        console.log('Stadium selected:', this.stadium);

        // Update UI
        document.querySelectorAll('.stadium-tab').forEach(t => {
            t.classList.remove('active');
        });
        tab.classList.add('active');

        // Clear previous selections
        this.selectedDate = null;
        this.selectedHour = null;
        document.getElementById('booking-date').value = '';
        document.getElementById('time-slots').innerHTML = '';
    }

    selectDate(event) {
        this.selectedDate = event.target.value;

        console.log('Date selected:', this.selectedDate);

        // Validate date
        const selectedDateObj = new Date(this.selectedDate);
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        if (selectedDateObj < today) {
            alert('لا يمكن حجز تاريخ ماضي');
            event.target.value = '';
            this.selectedDate = null;
            return;
        }

        if (this.stadiumId) {
            this.loadTimeSlots();
        } else {
            alert('يرجى اختيار الملعب أولاً');
        }
    }

    async loadTimeSlots() {
        if (!this.stadiumId || !this.selectedDate) {
            console.warn('Missing stadiumId or selectedDate');
            return;
        }

        console.log('Loading time slots for stadium', this.stadiumId, 'date', this.selectedDate);

        try {
            const response = await fetch(
                `/booking/api/get-slots/${this.stadiumId}/${this.selectedDate}`
            );

            console.log('Response status:', response.status);

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const slots = await response.json();
            console.log('Slots loaded:', slots);
            this.renderTimeSlots(slots);
        } catch (error) {
            console.error('Error loading slots:', error);
            alert('خطأ في تحميل الأوقات المتاحة: ' + error.message);
        }
    }

    renderTimeSlots(slots) {
        const slotsContainer = document.getElementById('time-slots');
        if (!slotsContainer) {
            console.warn('Slots container not found');
            return;
        }

        console.log('Rendering', slots.length, 'slots');
        slotsContainer.innerHTML = '';

        slots.forEach(slot => {
            const slotElement = document.createElement('button');
            slotElement.type = 'button';
            slotElement.classList.add('time-slot', 'btn', 'm-1');

            // Set the data attribute
            slotElement.setAttribute('data-hour', slot.hour.toString());

            let slotText = slot.time;

            if (slot.is_booked) {
                slotElement.classList.add('booked', 'btn-danger', 'disabled');
                slotElement.disabled = true;
                slotText += ' (محجوز)';
            } else if (slot.is_discount) {
                slotElement.classList.add('discount', 'btn-warning');
                slotText += ' (-25%)';
            } else {
                slotElement.classList.add('available', 'btn-success');
            }

            slotElement.textContent = slotText;

            // Add click listener
            slotElement.addEventListener('click', (e) => {
                if (!slotElement.classList.contains('booked')) {
                    e.preventDefault();
                    this.selectTimeSlot(slotElement);
                }
            });

            slotsContainer.appendChild(slotElement);
            console.log('Added slot - hour:', slot.hour);
        });
    }

    selectTimeSlot(element) {
        console.log('selectTimeSlot called');
        console.log('Element:', element);
        console.log('data-hour:', element.getAttribute('data-hour'));

        const hourStr = element.getAttribute('data-hour');

        if (!hourStr) {
            console.error('No hour data found!');
            alert('خطأ في الحصول على البيانات');
            return;
        }

        const hour = parseInt(hourStr);

        if (isNaN(hour)) {
            console.error('Hour is not a valid number:', hourStr);
            alert('خطأ في معالجة الوقت');
            return;
        }

        console.log('Hour selected:', hour);

        // Remove previous selection
        document.querySelectorAll('.time-slot.selected').forEach(slot => {
            slot.classList.remove('selected');
        });

        // Add selection
        element.classList.add('selected');
        this.selectedHour = hour;

        // Update hidden input
        const selectedHourInput = document.getElementById('selected-hour');
        if (selectedHourInput) {
            selectedHourInput.value = hour;
        }

        // Update summary
        this.updateBookingSummary();
    }

    updateBookingSummary() {
        if (this.selectedHour === null || !this.stadium) {
            console.log('Missing selectedHour or stadium for summary');
            return;
        }

        const summaryDiv = document.getElementById('booking-summary');
        if (!summaryDiv) return;

        const isDiscount = this.settings.discount_start_hour <= this.selectedHour &&
                          this.selectedHour < this.settings.discount_end_hour;

        const originalPrice = this.stadium.price * this.duration;
        const discount = isDiscount ? (originalPrice * this.settings.discount_percentage / 100) : 0;
        const finalPrice = originalPrice - discount;

        const endHour = (this.selectedHour + this.duration) % 24;

        let html = `
            <div class="mb-2">
                <small><strong>الملعب:</strong> ${this.stadium.name}</small>
            </div>
            <div class="mb-2">
                <small><strong>التاريخ:</strong> ${this.selectedDate}</small>
            </div>
            <div class="mb-2">
                <small><strong>الوقت:</strong> ${String(this.selectedHour).padStart(2, '0')}:00 - ${String(endHour).padStart(2, '0')}:00</small>
            </div>
            <div class="mb-2">
                <small><strong>المدة:</strong> ${this.duration} ساعة</small>
            </div>
            <div class="mb-2">
                <small><strong>السعر الأساسي:</strong> ${originalPrice.toLocaleString('ar-IQ')} د.ع</small>
            </div>
        `;

        if (isDiscount) {
            html += `
                <div class="mb-2 text-success">
                    <small><strong>الخصم (25%):</strong> -${discount.toLocaleString('ar-IQ')} د.ع</small>
                </div>
            `;
        }

        html += `
            <div class="mb-2 border-top pt-2">
                <strong>المجموع: ${finalPrice.toLocaleString('ar-IQ')} د.ع</strong>
            </div>
        `;

        summaryDiv.innerHTML = html;
    }

    async submitBooking(event) {
        event.preventDefault();

        console.log('Submitting booking...');

        // Validate
        if (!this.stadiumId || !this.selectedDate || this.selectedHour === null) {
            alert('يرجى اختيار الملعب والتاريخ والوقت');
            return;
        }

        const form = event.currentTarget;
        const customerName = document.getElementById('customer-name').value;
        const customerPhone = document.getElementById('customer-phone').value;
        const customerEmail = document.getElementById('customer-email').value;

        if (!customerName || !customerPhone) {
            alert('يرجى إدخال الاسم ورقم الهاتف');
            return;
        }

        // Show loading
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = 'جاري المعالجة...';

        try {
            const response = await fetch('/booking/api/create-booking', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    stadium_id: this.stadiumId,
                    date: this.selectedDate,
                    start_hour: this.selectedHour,
                    duration_hours: this.duration,
                    customer_name: customerName,
                    customer_phone: customerPhone,
                    customer_email: customerEmail
                })
            });

            console.log('Response status:', response.status);

            const result = await response.json();
            console.log('Result:', result);

            if (result.success) {
                alert('تم الحجز بنجاح!');
                // Redirect to confirmation page
                window.location.href = `/booking/confirmation/${result.booking_id}`;
            } else {
                alert('خطأ: ' + result.message);
            }
        } catch (error) {
            console.error('Error:', error);
            alert('حدث خطأ في إنشاء الحجز: ' + error.message);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM loaded, creating BookingSystem...');
    new BookingSystem();
});