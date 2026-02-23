import { createOrder } from './api.js';
import { getFormData } from './constructor.js';

export function initOrderForm() {
    const form = document.getElementById('order-form');
    form.addEventListener('submit', handleSubmit);

    const successModal = document.getElementById('success-modal');
    const closeBtn = successModal.querySelector('.close');

    closeBtn.addEventListener('click', () => {
        successModal.style.display = 'none';
    });
}

async function handleSubmit(e) {
    e.preventDefault();

    const constructorData = getFormData();
    const orderForm = e.target;
    const formData = new FormData(orderForm);

    const isUnknown  = constructorData.bag_size === 'unknown';
    const totalPrice = isUnknown
        ? 0
        : parseFloat(document.getElementById('total-price').textContent.replace(/\s/g, ''));

    const orderData = {
        customer_name: formData.get('customer_name'),
        customer_phone: formData.get('customer_phone'),
        customer_email: formData.get('customer_email') || null,
        bottles: constructorData.bottles,
        bag_size: constructorData.bag_size,
        custom_width: constructorData.custom_width,
        custom_length: constructorData.custom_length,
        custom_height: constructorData.custom_height,
        paper_type: constructorData.paper_type,
        color: constructorData.color,
        handle_type: constructorData.handle_type,
        has_print: constructorData.has_print,
        quantity: constructorData.quantity,
        total_price: totalPrice
    };

    try {
        const result = await createOrder(orderData);
        showSuccess(result.id);
        resetForms();
    } catch (error) {
        console.error('Ошибка создания заказа:', error);
        alert('Не удалось создать заказ. Попробуйте еще раз.');
    }
}

function showSuccess(orderId) {
    document.getElementById('constructor-modal').style.display = 'none';
    document.getElementById('order-number').textContent = orderId;
    document.getElementById('success-modal').style.display = 'block';
}

function resetForms() {
    document.getElementById('constructor-form').reset();
    document.getElementById('order-form').reset();
    document.getElementById('order-form-section').style.display = 'none';
    document.getElementById('unit-price').textContent = '0';
    document.getElementById('total-price').textContent = '0';
}
