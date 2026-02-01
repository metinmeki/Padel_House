/**
 * Padel House Store - Cart JavaScript
 * Handles all cart operations: add, remove, update, clear
 */

// ============================================
// CART FUNCTIONALITY
// ============================================

// Add to cart function
function addToCart(productId, quantity = 1) {
    fetch('/store/cart/add', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            product_id: productId,
            quantity: quantity
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Update cart badge
            updateCartBadge(data.cart_count, data.total_items);

            // Show success notification
            showToast('تم إضافة المنتج للسلة', 'success');
        } else {
            showToast(data.message || 'حدث خطأ', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showToast('حدث خطأ في الاتصال', 'error');
    });
}

// Remove from cart function
function removeFromCart(productId) {
    if (!confirm('هل تريد حذف هذا المنتج من السلة؟')) {
        return;
    }

    fetch('/store/cart/remove', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ product_id: productId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Remove item from DOM if on cart page
            const cartItem = document.querySelector(`.cart-item[data-product-id="${productId}"]`);
            if (cartItem) {
                cartItem.remove();
            }

            // Update cart badge
            updateCartBadge(data.cart_count);

            // Update totals if on cart page
            if (document.getElementById('totalDisplay')) {
                document.getElementById('totalDisplay').textContent = formatPrice(data.total);
                document.getElementById('subtotalDisplay').textContent = formatPrice(data.total);
            }

            // Reload if cart is empty
            if (data.cart_count === 0) {
                location.reload();
            }

            showToast('تم حذف المنتج', 'success');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showToast('حدث خطأ', 'error');
    });
}

// Update cart quantity
function updateQuantity(productId, change) {
    fetch('/store/cart/update', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            product_id: productId,
            change: change
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Update quantity input
            const qtyInput = document.querySelector(`.qty-input[data-product-id="${productId}"]`);
            if (qtyInput) {
                qtyInput.value = data.item_quantity;
            }

            // Update item subtotal
            const cartItem = document.querySelector(`.cart-item[data-product-id="${productId}"]`);
            if (cartItem) {
                const subtotalEl = cartItem.querySelector('.item-subtotal');
                if (subtotalEl) {
                    subtotalEl.textContent = formatPrice(data.item_subtotal);
                }
            }

            // Update totals
            if (document.getElementById('totalDisplay')) {
                document.getElementById('totalDisplay').textContent = formatPrice(data.total);
            }
            if (document.getElementById('subtotalDisplay')) {
                document.getElementById('subtotalDisplay').textContent = formatPrice(data.total);
            }
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showToast('حدث خطأ', 'error');
    });
}

// Clear entire cart
function clearCart() {
    if (!confirm('هل تريد تفريغ السلة بالكامل؟')) {
        return;
    }

    fetch('/store/cart/clear', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('تم تفريغ السلة', 'success');
            setTimeout(() => location.reload(), 500);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showToast('حدث خطأ', 'error');
    });
}

// ============================================
// UTILITY FUNCTIONS
// ============================================

// Format price with commas and currency
function formatPrice(num) {
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",") + ' د.ع';
}

// Update cart badge in navbar
function updateCartBadge(count, totalItems = null) {
    const badge = document.querySelector('.cart-badge');
    const cartIcon = document.querySelector('.cart-icon-container');

    if (badge) {
        badge.textContent = totalItems || count;
        badge.style.display = count > 0 ? 'flex' : 'none';
    }

    // Add animation
    if (cartIcon) {
        cartIcon.classList.add('cart-bounce');
        setTimeout(() => {
            cartIcon.classList.remove('cart-bounce');
        }, 300);
    }
}

// Show toast notification
function showToast(message, type = 'info') {
    // Check if toast element exists
    let toast = document.getElementById('cartToast');

    // Create toast if doesn't exist
    if (!toast) {
        const toastHTML = `
            <div class="position-fixed bottom-0 end-0 p-3" style="z-index: 1050">
                <div id="cartToast" class="toast" role="alert">
                    <div class="toast-header">
                        <i class="toast-icon fas fa-info-circle me-2"></i>
                        <strong class="me-auto">تنبيه</strong>
                        <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
                    </div>
                    <div class="toast-body" id="toastMessage"></div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', toastHTML);
        toast = document.getElementById('cartToast');
    }

    const toastBody = document.getElementById('toastMessage');
    const toastIcon = toast.querySelector('.toast-icon');

    toastBody.textContent = message;

    // Set icon based on type
    if (type === 'success') {
        toastIcon.className = 'toast-icon fas fa-check-circle me-2 text-success';
    } else if (type === 'error') {
        toastIcon.className = 'toast-icon fas fa-exclamation-circle me-2 text-danger';
    } else {
        toastIcon.className = 'toast-icon fas fa-info-circle me-2';
        toastIcon.style.color = '#E57625';
    }

    const bsToast = new bootstrap.Toast(toast, { delay: 3000 });
    bsToast.show();
}

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', function() {

    // Add to cart buttons on products page
    document.querySelectorAll('.add-to-cart').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const productId = parseInt(this.dataset.productId);
            addToCart(productId);
        });
    });

    // Quantity buttons on cart page
    document.querySelectorAll('.qty-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const productId = parseInt(this.dataset.productId);
            const action = this.dataset.action;
            const change = action === 'increase' ? 1 : -1;

            const input = document.querySelector(`.qty-input[data-product-id="${productId}"]`);
            const currentQty = parseInt(input.value);

            // Don't allow going below 1
            if (currentQty <= 1 && change === -1) {
                showToast('الحد الأدنى للكمية هو 1', 'error');
                return;
            }

            updateQuantity(productId, change);
        });
    });

    // Remove buttons on cart page
    document.querySelectorAll('.remove-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const productId = parseInt(this.dataset.productId);
            removeFromCart(productId);
        });
    });

    // Clear cart button
    const clearCartBtn = document.getElementById('clearCartBtn');
    if (clearCartBtn) {
        clearCartBtn.addEventListener('click', clearCart);
    }

    // Load cart count on page load
    fetch('/store/cart/count')
        .then(response => response.json())
        .then(data => {
            updateCartBadge(data.count, data.total_items);
        })
        .catch(error => console.error('Error loading cart count:', error));
});

// ============================================
// PRODUCT PAGE FUNCTIONS
// ============================================

// Quick view modal (optional)
function quickView(productId) {
    fetch(`/store/product/${productId}`)
        .then(response => response.text())
        .then(html => {
            // Show in modal
            const modal = document.getElementById('quickViewModal');
            if (modal) {
                modal.querySelector('.modal-body').innerHTML = html;
                new bootstrap.Modal(modal).show();
            }
        })
        .catch(error => console.error('Error:', error));
}

// Filter products by category
function filterByCategory(categoryId) {
    const url = categoryId ? `/store?category=${categoryId}` : '/store';
    window.location.href = url;
}

// Filter products by price range
function filterByPrice() {
    const minPrice = document.getElementById('priceMin')?.value || 0;
    const maxPrice = document.getElementById('priceMax')?.value || 999999999;

    const currentUrl = new URL(window.location.href);
    currentUrl.searchParams.set('min_price', minPrice);
    currentUrl.searchParams.set('max_price', maxPrice);

    window.location.href = currentUrl.toString();
}

// Sort products
function sortProducts(sortBy) {
    const currentUrl = new URL(window.location.href);
    currentUrl.searchParams.set('sort', sortBy);
    window.location.href = currentUrl.toString();
}