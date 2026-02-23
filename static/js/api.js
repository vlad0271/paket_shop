const API_BASE = '/api';

export async function fetchPackages() {
    const response = await fetch(`${API_BASE}/packages`);
    if (!response.ok) throw new Error('Ошибка загрузки пакетов');
    return response.json();
}

export async function fetchImages() {
    const response = await fetch(`${API_BASE}/images`);
    if (!response.ok) throw new Error('Ошибка загрузки изображений');
    return response.json();
}

export async function fetchOptions() {
    const response = await fetch(`${API_BASE}/options`);
    if (!response.ok) throw new Error('Ошибка загрузки опций');
    return response.json();
}

export async function calculatePrice(data) {
    const response = await fetch(`${API_BASE}/calculate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!response.ok) throw new Error('Ошибка расчета цены');
    return response.json();
}

export async function fetchStandardSizes() {
    const response = await fetch(`${API_BASE}/standard-sizes`);
    if (!response.ok) throw new Error('Ошибка загрузки размеров');
    return response.json();
}

export async function createOrder(data) {
    const response = await fetch(`${API_BASE}/orders`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!response.ok) throw new Error('Ошибка создания заказа');
    return response.json();
}
