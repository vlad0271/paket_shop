import { calculatePrice } from './api.js';
import { getFormData } from './constructor.js';

export function initCalculator() {
    const calculateBtn = document.getElementById('calculate-btn');
    calculateBtn.addEventListener('click', handleCalculate);

    const form = document.getElementById('constructor-form');
    form.addEventListener('change', () => {
        const choice = document.querySelector('input[name="bottles"]:checked')?.value;
        if (choice !== 'unknown') {
            document.getElementById('order-form-section').style.display = 'none';
        }
    });
}

async function handleCalculate() {
    try {
        const data = getFormData();
        const result = await calculatePrice(data);

        displayPrice(result);
        showOrderForm();
    } catch (error) {
        console.error('Ошибка расчета:', error);
        alert('Не удалось рассчитать цену. Попробуйте еще раз.');
    }
}

function displayPrice(result) {
    document.getElementById('unit-price').textContent = Math.round(result.unit_price).toLocaleString('ru-RU');
    document.getElementById('total-price').textContent = Math.round(result.total_price).toLocaleString('ru-RU');

    const discountInfo = document.getElementById('discount-info');
    if (result.discount_percent > 0) {
        document.getElementById('discount-percent').textContent = result.discount_percent;
        discountInfo.style.display = 'block';
    } else {
        discountInfo.style.display = 'none';
    }
}

function showOrderForm() {
    document.getElementById('order-form-section').style.display = 'block';
}
